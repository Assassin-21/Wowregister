"""Record clicks, F7 text actions, and F9 failure-image checkpoints."""
import argparse
from datetime import datetime
from pathlib import Path
import time

from .macro import DEFAULT_PATH, checkpoint_image, encode_image, save, validate, validate_names, random_name
from .windows import Desktop, wait_for_start


def record(desktop, names, checkpoint_size=(240, 80)):
    desktop.bind()
    macro = dict(version=2, executable=desktop.executable,
                 client_size=list(desktop.initial_geometry[2:]), dpi=desktop.dpi,
                 names=names, recorded_at=datetime.now().astimezone().isoformat(), actions=[])
    # Validate the name before any F7 input can be sent.
    validate_names(names)
    last_end = desktop.now()
    keys = (0x75, 0x76, 0x77, 0x78, 1, 2)  # F6, F7, F8, F9, left, right
    previous = {key: desktop.down(key) for key in keys}
    pending = None
    print("录制中：F7 填第一个框的名字；F8 填第二个框的名字；F9 失败提示检查点；F6 保存；F10 丢弃本次。", flush=True)
    while True:
        desktop.guard()
        current = {key: desktop.down(key) for key in keys}
        pressed = {key for key in keys if current[key] and not previous[key]}
        now = desktop.now()
        if len(macro["actions"]) >= 2000:
            raise RuntimeError("动作过多，请缩短录制")
        if 0x75 in pressed:
            if pending or current[1] or current[2]:
                raise RuntimeError("请松开鼠标后再结束录制")
            if not macro["actions"]:
                raise RuntimeError("未录制任何动作")
            # Preserve the final wait after returning to the starting page.
            tail = now - last_end
            if tail > 600:
                raise RuntimeError("最后等待超过 600 秒，请重新录制")
            macro["actions"][0]["delay"] += tail
            return macro
        if pending:
            if current[pending[0]] and any(key in pressed for key in (0x76, 0x77, 0x78, 1, 2)):
                raise RuntimeError("不支持同时按多个鼠标按钮或在按住鼠标时使用热键")
            key, action, began = pending
            if now - began > 2:
                raise RuntimeError("不支持超过 2 秒的长按")
            if not current[key]:
                x, y = desktop.position()
                if abs(x - action["x"]) > 8 or abs(y - action["y"]) > 8:
                    raise RuntimeError("检测到拖拽；本工具只支持点击")
                action["hold"] = now - began
                macro["actions"].append(action)
                print(f"已录制点击：({action['x']}, {action['y']})", flush=True)
                last_end, pending = now, None
        if pending is None and (1 in pressed or 2 in pressed):
            if current[1] and current[2]:
                raise RuntimeError("不支持同时按左右键")
            x, y = desktop.position()
            key = 1 if 1 in pressed else 2
            pending = (key, dict(type="click", delay=now-last_end, x=x, y=y,
                                 button="left" if key == 1 else "right"), now)
        elif pending is None and (0x76 in pressed or 0x77 in pressed):
            slot = 0 if 0x76 in pressed else 1
            action = dict(type="name", slot=slot, delay=now-last_end)
            # F7 itself is not replayed; send the configured name now for an accurate recording.
            desktop.type_name(names[slot])
            macro["actions"].append(action)
            last_end = desktop.now()
            print(f"已发送并录制第 {slot+1} 个框的名字：{names[slot]}（请核对游戏输入框）", flush=True)
        elif pending is None and 0x78 in pressed:
            x, y = desktop.position()
            width, height = macro["client_size"]
            cw, ch = min(checkpoint_size[0], width), min(checkpoint_size[1], height)
            left, top = max(0, min(x-cw//2, width-cw)), max(0, min(y-ch//2, height-ch))
            box = [left, top, left+cw, top+ch]
            action = dict(type="checkpoint", purpose="failure", delay=now-last_end, box=box,
                          image=encode_image(desktop.capture(box)))
            try:
                validate({**macro, "actions": [action]})
            except ValueError as exc:
                print(f"检查点未保存：{exc}。录制仍在继续，请换到固定文字区域重试。", flush=True)
                previous = current
                time.sleep(.005)
                continue
            macro["actions"].append(action)
            last_end = desktop.now()
            print(f"已记录失败提示检查点：{box}。应覆盖固定失败文字，不能只截通用确定按钮。", flush=True)
        previous = current
        time.sleep(.005)


def main():
    parser = argparse.ArgumentParser(description="录制注册操作：F6 开始/保存，F7 第一段名字，F8 第二段名字，F9 失败检查点，F10 取消")
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--name-first", help="第一个输入框的名字")
    parser.add_argument("--name-second", help="第二个输入框的名字")
    parser.add_argument("--checkpoint-width", type=int, default=240)
    parser.add_argument("--checkpoint-height", type=int, default=80)
    args = parser.parse_args()
    try:
        if not 40 <= args.checkpoint_width <= 600 or not 20 <= args.checkpoint_height <= 300:
            raise ValueError("检查点宽度需 40–600，高度需 20–300")
        names = [args.name_first if args.name_first is not None else random_name(),
                 args.name_second if args.name_second is not None else random_name()]
        validate_names(names)
        print(f"自动填名：{names[0]} / {names[1]}。点击两个输入框后分别按 F7 / F8。", flush=True)
        desktop = Desktop()
        wait_for_start(desktop)
        macro = record(desktop, names, (args.checkpoint_width, args.checkpoint_height))
        save(args.output, macro)
        print(f"已保存 {len(macro['actions'])} 个动作：{args.output.resolve()}")
        for index, action in enumerate((a for a in macro["actions"] if a["type"] == "checkpoint"), 1):
            preview = args.output.parent / f"{args.output.stem}_checkpoint_{index:02d}.png"
            try:
                checkpoint_image(action).save(preview)
                print(f"检查点预览：{preview.resolve()}")
            except OSError as exc:
                print(f"预览导出失败（JSON 已保存，不影响回放）：{exc}")
        if not any(a["type"] == "checkpoint" and a.get("purpose", "failure") == "failure" for a in macro["actions"]):
            print("未录制 F9 失败检查点；此文件只能单轮回放。")
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"录制已停止：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
