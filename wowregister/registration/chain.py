"""Direct creation, bounded Enter retry, then recorded return route."""
import argparse
from pathlib import Path
from .macro import load, replay, random_name, checkpoint_image, image_error
from .windows import Desktop, wait_for_start

ROOT = Path(__file__).resolve().parents[2] / "data/registration"

def split_direct(macro):
    actions = macro["actions"]
    slots = [a.get("slot") for a in actions if a["type"] == "name"]
    if slots != [0, 1]:
        raise ValueError("direct 必须依次填写两个名字")
    last_name = max(i for i, a in enumerate(actions) if a["type"] == "name")
    tail = actions[last_name+1:]
    if len(tail) != 1 or tail[0]["type"] != "checkpoint" or tail[0].get("purpose", "failure") != "failure":
        raise ValueError("direct 必须在第二段名字后直接录制 F9 并保存，不能再录其他点击")
    return {**macro, "actions": actions[:last_name+1]}, tail[0]

def yellow_pixels(image):
    image = image.convert("RGB")
    width = image.width
    return {(i % width, i // width) for i, (r, g, b) in enumerate(image.getdata())
            if r >= 150 and g >= 120 and b < min(r, g) * .6}


def matches_checkpoint(expected, actual):
    if expected.size != actual.size:
        return False
    reference = yellow_pixels(expected)
    if len(reference) < 100:
        return image_error(expected, actual) <= .02
    observed = yellow_pixels(actual)
    if not observed:
        return False
    # Compare text silhouettes, ignoring non-yellow translucent backgrounds.
    # A small translation tolerance accommodates subpixel rendering/position jitter.
    for dx in range(-2, 3):
        for dy in range(-2, 3):
            shifted = {(x+dx, y+dy) for x, y in reference}
            overlap = len(shifted & observed)
            precision = overlap / len(observed)
            recall = overlap / len(reference)
            if precision >= .8 and recall >= .8:
                return True
    return False


def enter_until(desktop, checkpoint, timeout=60):
    expected = checkpoint_image(checkpoint)
    desktop.guard()
    already_matches = matches_checkpoint(expected, desktop.capture(checkpoint["box"]))
    desktop.guard()
    if already_matches:
        raise RuntimeError("尚未按回车就已匹配 F9 图片，检查点可能截到了背景。已停止，不执行返回路线；请重录失败提示文字区域")
    print("开始自动回车，约每秒 1.5 次，等待 F9 失败提示", flush=True)
    presses = 0
    deadline, next_enter, matches = desktop.now()+timeout, desktop.now(), 0
    while True:
        desktop.guard()
        matched = matches_checkpoint(expected, desktop.capture(checkpoint["box"]))
        desktop.guard()
        if matched and matches == 0:
            print("检测到失败提示，暂停回车并确认画面", flush=True)
        matches = matches + 1 if matched else 0
        if matches >= 2:
            if not presses:
                raise RuntimeError("尚未发送回车就匹配图片，已停止；请核对 F9 检查点")
            return
        if desktop.now() >= deadline:
            raise RuntimeError("等待 F9 图片超时，已停止回车和返回操作；请核对是否成功或页面变化")
        # Pause Enter on the first matching frame so it cannot dismiss the target dialog.
        if not matched and desktop.now() >= next_enter:
            desktop.press_enter()
            presses += 1
            print(f"已发送第 {presses} 次回车", flush=True)
            next_enter = desktop.now()+.67
        desktop.wait(.1)

def validate_route(direct, route):
    if any(a["type"] != "click" for a in route["actions"]):
        raise ValueError("ruleset 需要重录为返回路线：从 F9 弹窗开始，到 direct 起点结束，不要再次填名")
    for field in ("executable", "client_size", "dpi"):
        if direct.get(field) != route.get(field):
            raise ValueError("两份录制的程序、尺寸或 DPI 不一致，请重录")

def route_path(mode):
    if mode not in (1, 2):
        raise ValueError("模式只能选择 1 或 2")
    return ROOT / "ruleset" / ("macro.json" if mode == 1 else "macro_1.json")


def main():
    parser = argparse.ArgumentParser(description="direct → 自动回车直到 F9 → ruleset 返回路线 → direct")
    parser.add_argument("--mode", type=int, choices=(1, 2), help="1: macro.json；2: macro_1.json")
    parser.add_argument("--repeat", type=int)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    try:
        direct = load(ROOT / "direct/macro.json")
        mode = args.mode if args.mode is not None else int(input("选择模式 1/2（1=macro.json，2=macro_1.json，默认 1）：") or "1")
        path = route_path(mode)
        route = load(path)
        print(f"模式 {mode}：{path}", flush=True)
        prefix, checkpoint = split_direct(direct)
        validate_route(direct, route)
        repeat = args.repeat if args.repeat is not None else int(input("执行轮数（首次填 1）：") or "1")
        if not 1 <= repeat <= 10000 or not 1 <= args.timeout <= 600:
            raise ValueError("轮数需 1–10000，回车等待上限需 1–600 秒")
        desktop = Desktop()
        wait_for_start(desktop)
        desktop.bind(direct)
        desktop.wait(.4)
        for cycle in range(repeat):
            print(f"组合流程 {cycle+1}/{repeat}", flush=True)
            replay(prefix, desktop, name_factory=lambda: [random_name(), random_name()], timing="direct")
            enter_until(desktop, checkpoint, args.timeout)
            print("已匹配 F9，执行返回路线", flush=True)
            replay(route, desktop, timing="ruleset")
        print("已完成，停在 direct 起点。", flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"组合流程已停止：{exc}", flush=True)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
