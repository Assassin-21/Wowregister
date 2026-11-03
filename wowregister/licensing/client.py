"""HTTPS license client. No service secrets or bypass switches in the client."""
import getpass
import json
import os
from pathlib import Path
import threading
import time
import sys
from urllib import error, parse, request

from .device import device_id, protect
from wowregister.paths import resource_root

ROOT = resource_root()
CACHE = Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data"))) / "Wowregister/license.dat"
_session = None
_lock = threading.Lock()


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a card to a different URL.


def service_url():
    url = os.environ.get("WOWREGISTER_LICENSE_URL", "").strip()
    external = Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT
    for path in (external / "license_client.json", ROOT / "wowregister/default_service.json"):
        if not url and path.exists():
            url = json.loads(path.read_text(encoding="utf-8")).get("url", "").strip()
    parsed = parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("请在 license_client.json 中设置 HTTPS 验证接口 url；参见 docs/LICENSING.md")
    return url


def verify(url, card, machine):
    payload = json.dumps({"license_key": card, "device_id": machine}).encode("utf-8")
    req = request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with request.build_opener(NoRedirect()).open(req, timeout=30) as response:
            raw = response.read(8193)
            if len(raw) > 8192:
                raise ValueError("response too large")
            data = json.loads(raw)
    except error.HTTPError as exc:
        if exc.code == 403:
            try:
                code = json.loads(exc.read(2048)).get("code")
            except (OSError, ValueError, AttributeError):
                code = None
            messages = {"invalid_card": "卡密不存在或格式不正确，请核对卡密",
                        "disabled": "该卡密已被停用，请联系管理员", "expired": "该卡密已到期，请联系管理员",
                        "bound_to_other_device": "该卡密已在另一台电脑激活，不能在本机使用"}
            raise RuntimeError(messages.get(code, "卡密验证未通过，请联系管理员核对状态")) from None
        raise RuntimeError("授权服务暂不可用，已停止；请稍后重试") from None
    except (OSError, ValueError) as exc:
        raise RuntimeError("无法完成在线授权，已停止；请检查网络和验证服务") from exc
    if not isinstance(data, dict) or data.get("ok") is not True or data.get("device_id") != machine:
        raise RuntimeError("授权响应无效，已停止")


class Session:
    def __init__(self, url, card, machine):
        self.url, self.card, self.machine = url, card, machine
        self.failure = None
        self.deadline = time.monotonic() + 120
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)

    def _heartbeat(self):
        while not self.closed.wait(45):
            try:
                verify(self.url, self.card, self.machine)
                self.deadline = time.monotonic() + 120
            except Exception:
                self.failure = "在线授权复核失败，已停止；请检查卡密状态及网络后重新启动"
                return

    def check(self):
        if self.failure or time.monotonic() >= self.deadline:
            raise RuntimeError(self.failure or "在线授权已超时，请重新启动")


def prompt_card(gui=False):
    if gui:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk()
        root.withdraw()
        try:
            card = simpledialog.askstring("Wowregister 激活", "请输入卡密：", show="*", parent=root)
        finally:
            root.destroy()
        return (card or "").strip()
    return getpass.getpass("请输入卡密（不会显示）：").strip()


def check_active():
    if _session is None:
        raise RuntimeError("尚未激活卡密，请先运行 activate_license.cmd")
    _session.check()


def require_license(gui=False, card=None, allow_prompt=True):
    global _session
    with _lock:
        if _session is not None and card is None:
            _session.check()
            return _session
        url, machine = service_url(), device_id()
        if card is None and CACHE.exists():
            try:
                cache = json.loads(protect(CACHE.read_bytes(), decrypt=True))
                if cache.get("url") == url and cache.get("device_id") == machine:
                    card = cache.get("card")
            except (RuntimeError, OSError, ValueError):
                pass
        if not card:
            if not allow_prompt:
                raise RuntimeError("请先输入卡密激活")
            card = prompt_card(gui)
        if not card:
            raise RuntimeError("未输入卡密，已取消")
        verify(url, card, machine)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        temporary = CACHE.with_suffix(".tmp")
        temporary.write_bytes(protect(json.dumps(dict(url=url, card=card, device_id=machine)).encode("utf-8")))
        temporary.replace(CACHE)
        if _session is not None:
            _session.closed.set()
        _session = Session(url, card, machine)
        _session.thread.start()
        return _session


def authorize_gui():
    try:
        return require_license(gui=True)
    except (RuntimeError, OSError, ValueError) as exc:
        from tkinter import messagebox
        messagebox.showerror("授权未完成", str(exc))
        return None


def watch_gui(root, on_failure):
    def tick():
        try:
            check_active()
        except RuntimeError as exc:
            from tkinter import messagebox
            messagebox.showerror("授权已停止", str(exc), parent=root)
            on_failure()
            return
        root.after(1000, tick)
    root.after(1000, tick)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="查看机器码或激活卡密")
    parser.add_argument("--device-id", action="store_true")
    parser.add_argument("--forget", action="store_true", help="删除本机缓存；不会解除服务端绑定")
    args = parser.parse_args()
    try:
        if args.device_id:
            print(device_id())
        elif args.forget:
            CACHE.unlink(missing_ok=True)
            print("本机缓存已删除；服务端绑定仍保留。")
        else:
            require_license(card=prompt_card())
            print("激活成功，已加密保存到当前 Windows 账号。")
        return 0
    except (RuntimeError, OSError, ValueError, KeyboardInterrupt, EOFError) as exc:
        print(f"授权未完成：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
