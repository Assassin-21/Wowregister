"""Inspect or replay a saved character-registration macro."""
import argparse
from pathlib import Path

from .macro import DEFAULT_PATH, load, replay, validate, validate_replay, random_name
from .windows import Desktop, wait_for_start


def main():
    parser = argparse.ArgumentParser(description="回放注册操作；默认一轮。F6 开始，F10 停止，切走目标窗口也会停止")
    parser.add_argument("--macro", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--name-first", help="覆盖第一个框的名字")
    parser.add_argument("--name-second", help="覆盖第二个框的名字")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--tolerance", type=float, default=.02)
    parser.add_argument("--inspect", action="store_true", help="只打印动作，不监听热键、不发送输入")
    parser.add_argument("--interactive", action="store_true", help="启动时询问回放次数，供双击入口使用")
    parser.add_argument("--timing", choices=("recorded", "direct", "ruleset"), default="recorded")
    args = parser.parse_args()
    try:
        macro = load(args.macro)
        for slot, value in enumerate((args.name_first, args.name_second)):
            if value is not None:
                macro["names"][slot] = value
        validate(macro)
        print(f"录制文件：{args.macro.resolve()}\n目标程序：{macro['executable']}\n录制时名字：{macro['names']}\n窗口尺寸：{macro['client_size']}")
        for index, action in enumerate(macro["actions"], 1):
            detail = f" ({action['x']}, {action['y']}) {action['button']}" if action["type"] == "click" else (f" 输入框 {action['slot']+1}" if action["type"] == "name" else "")
            print(f"{index:02d}. 等待 {action['delay']:.2f}s → {action['type']}{detail}")
        if args.inspect:
            return 0
        repeat = int(input("回放次数（首次建议 1；输入 30 表示最多 30 轮，默认 1）：") or "1") if args.interactive else args.repeat
        # Validate all replay settings before the user switches windows; no input is emitted.
        validate_replay(macro, repeat, args.interval, args.timeout, args.tolerance)
        print("每轮自动生成两个 8–10 位字母名字（命令行指定的名字除外）。", flush=True)
        desktop = Desktop()
        wait_for_start(desktop)
        desktop.bind(macro)
        desktop.wait(.4)  # Let the initiating F6 key be released.
        replay(macro, desktop, repeat, args.interval, args.timeout, args.tolerance, report=lambda message: print(message, flush=True),
               name_factory=lambda: [args.name_first if args.name_first is not None else random_name(),
                                     args.name_second if args.name_second is not None else random_name()], timing=args.timing)
        return 0
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"回放已停止：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
