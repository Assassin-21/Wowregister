"""Loopback-only browser controls for the licensed Windows replay engine."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from urllib.parse import urlsplit, parse_qs
import webbrowser

from wowregister.licensing import client
from wowregister.licensing.device import device_id
from wowregister.paths import resource_root
from wowregister.registration.chain import run_cycle, validate_settings
from wowregister.registration.windows import PlaybackStopped


class Controller:
    def __init__(self, runner=run_cycle):
        self.runner = runner
        self.lock = threading.RLock()
        self.logs = deque(maxlen=2000)
        self.sequence = 0
        self.thread = None
        self.stop_event = threading.Event()
        self.state, self.message = "idle", "请先激活卡密，然后选择模式和轮数。"
        self.mode, self.repeat, self.cycle = 1, 1, 0
        self.auth_busy = False
        self.authorized = False
        self.machine = device_id()

    def report(self, message):
        with self.lock:
            self.sequence += 1
            self.logs.append({"id": self.sequence, "text": str(message)})
            if "按 F6 开始" in message and self.state != "stopping":
                self.state, self.message = "waiting", "请切回游戏角色列表，按 F6 开始。"

    def authorize(self, card=None):
        with self.lock:
            if self.auth_busy or self.thread is not None and self.thread.is_alive():
                raise RuntimeError("请先停止正在运行的脚本，再进行激活")
            self.auth_busy = True
        try:
            client.require_license(card=card, allow_prompt=False)
            with self.lock:
                self.authorized = True
                self.message = "卡密验证通过，可以启动脚本。"
            self.report("卡密验证通过，已加密保存到本机。")
        except Exception:
            with self.lock:
                self.authorized = False
            raise
        finally:
            with self.lock:
                self.auth_busy = False

    def restore_authorization(self):
        try:
            self.authorize()
        except Exception:
            pass  # A first-time user simply sees the activation form.

    def start(self, mode, repeat):
        validate_settings(mode, repeat)
        with self.lock:
            if self.auth_busy:
                raise RuntimeError("正在验证卡密，请稍候")
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError("脚本已启动，请先停止当前任务")
            client.check_active()
            self.stop_event = threading.Event()
            self.mode, self.repeat, self.cycle = mode, repeat, 0
            self.state, self.message = "waiting", "正在准备，请切回游戏并按 F6。"
            self.thread = threading.Thread(target=self._run, name="registration-replay", daemon=False)
            self.thread.start()

    def _run(self):
        try:
            self.runner(self.mode, self.repeat, stop_event=self.stop_event, report=self.report,
                        on_cycle=self.on_cycle, allow_game_path_change=True)
            with self.lock:
                self.state, self.message = "completed", "已完成设置的轮数，请核对游戏结果。"
        except PlaybackStopped as exc:
            with self.lock:
                self.state, self.message = "stopped", str(exc)
            self.report(str(exc))
        except Exception as exc:
            with self.lock:
                self.state, self.message = "failed", str(exc)
            self.report(f"脚本已停止：{exc}")

    def on_cycle(self, current, total):
        with self.lock:
            self.cycle = current
            if self.state != "stopping":
                self.state, self.message = "running", f"正在执行第 {current} / {total} 轮，F10 可停止。"

    def stop(self):
        with self.lock:
            self.stop_event.set()
            if self.thread is not None and self.thread.is_alive():
                self.state, self.message = "stopping", "正在停止并释放按键…"

    def snapshot(self, after=0):
        with self.lock:
            try:
                client.check_active()
                self.authorized = True
            except RuntimeError:
                self.authorized = False
            return {"state": self.state, "message": self.message, "mode": self.mode,
                    "repeat": self.repeat, "cycle": self.cycle, "authorized": self.authorized,
                    "auth_busy": self.auth_busy, "device_id": self.machine,
                    "busy": self.thread is not None and self.thread.is_alive(),
                    "logs": [line for line in self.logs if line["id"] > after][:250]}

    def close(self):
        self.stop()
        if self.thread is not None:
            self.thread.join(timeout=5)


class PanelServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, controller, port=0):
        self.controller, self.token = controller, secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data, content_type="application/json; charset=utf-8"):
        body = data.encode("utf-8") if isinstance(data, str) else json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def allowed_host(self):
        return self.headers.get("Host") == urlsplit(self.server.origin).netloc

    def do_GET(self):
        if not self.allowed_host():
            self.reply(403, {"error": "请求来源无效"})
            return
        route = urlsplit(self.path)
        if route.path == "/":
            html = (resource_root() / "wowregister/panel.html").read_text(encoding="utf-8")
            self.reply(200, html.replace("__SESSION_TOKEN__", json.dumps(self.server.token)), "text/html; charset=utf-8")
        elif route.path == "/api/status":
            try:
                after = max(0, int(parse_qs(route.query).get("after", ["0"])[0]))
                self.reply(200, self.server.controller.snapshot(after))
            except ValueError:
                self.reply(400, {"error": "日志位置无效"})
        else:
            self.reply(404, {"error": "页面不存在"})

    def do_POST(self):
        if (not self.allowed_host() or self.headers.get("Origin") != self.server.origin
                or not secrets.compare_digest(self.headers.get("X-Wowregister-Token", ""), self.server.token)):
            self.reply(403, {"error": "请求来源无效，请刷新本地页面"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 4096 or self.headers.get_content_type() != "application/json":
                raise ValueError("请求格式无效")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("请求格式无效")
            controller = self.server.controller
            if self.path == "/api/start":
                controller.start(payload.get("mode"), payload.get("repeat"))
            elif self.path == "/api/stop":
                controller.stop()
            elif self.path == "/api/activate":
                card = payload.get("card")
                if not isinstance(card, str) or not 1 <= len(card.strip()) <= 128:
                    raise ValueError("请输入有效卡密")
                controller.authorize(card.strip())
            elif self.path == "/api/quit":
                controller.stop()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.reply(404, {"error": "操作不存在"})
                return
            self.reply(200, {"ok": True})
        except (ValueError, OSError, RuntimeError) as exc:
            self.reply(400, {"error": str(exc)})

    def log_message(self, format, *args):
        pass  # Never log card payloads or local session tokens.


def main():
    parser = argparse.ArgumentParser(description="Wowregister 本地操作页面")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()
    controller = Controller()
    server = PanelServer(controller, args.port)
    threading.Thread(target=controller.restore_authorization, daemon=True).start()
    if not args.no_open:
        webbrowser.open(server.origin)
    elif __import__("sys").stdout is not None:
        print(server.origin, flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        controller.close()
        server.server_close()


if __name__ == "__main__":
    main()
