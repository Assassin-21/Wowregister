"""Macro format and replay engine; no desktop input on import."""
import base64
import io
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data/registration/macro.json"


def validate_name(name):
    if not isinstance(name, str) or not name:
        raise ValueError("每段名字不能为空")
    units = 0
    for char in name:
        if "a" <= char <= "z" or "A" <= char <= "Z":
            units += 1
        elif any(low <= ord(char) <= high for low, high in ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0x20000, 0x323AF))):
            units += 2
        else:
            raise ValueError("每段名字只允许汉字或英文字母")
    if units > 12:
        raise ValueError("每段名字最多 6 个汉字或 12 个英文字母；混合时汉字计 2，字母计 1，上限 12")
    return name


def validate_names(names):
    if not isinstance(names, list) or len(names) != 2:
        raise ValueError("需要分别提供两个输入框的名字")
    for name in names:
        validate_name(name)


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def validate(macro):
    if not isinstance(macro, dict) or macro.get("version") != 2:
        raise ValueError("需要双名字 v2 录制文件；旧的单名字文件请重新录制")
    size = macro.get("client_size")
    if not isinstance(size, list) or len(size) != 2 or not all(type(v) is int and 1 <= v <= 32768 for v in size):
        raise ValueError("窗口尺寸无效")
    if not isinstance(macro.get("executable"), str) or not macro["executable"]:
        raise ValueError("缺少目标程序路径")
    validate_names(macro.get("names"))
    actions = macro.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 2000:
        raise ValueError("录制应包含 1–2000 个动作")
    for action in actions:
        if not isinstance(action, dict) or not number(action.get("delay"), 0, 600):
            raise ValueError("动作等待时间应为 0–600 秒")
        kind = action.get("type")
        if kind == "click":
            if action.get("button") not in ("left", "right") or not number(action.get("hold"), 0, 2):
                raise ValueError("仅支持左右键短点击，不支持拖拽或长按")
            if not all(type(action.get(k)) is int and 0 <= action[k] < bound for k, bound in zip(("x", "y"), size)):
                raise ValueError("点击位置超出目标窗口")
        elif kind == "checkpoint":
            box = action.get("box")
            if (not isinstance(box, list) or len(box) != 4 or not all(type(v) is int for v in box)
                    or not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1])):
                raise ValueError("检查点区域无效")
            image = checkpoint_image(action)
            if image.size != (box[2] - box[0], box[3] - box[1]):
                raise ValueError("检查点图片尺寸不一致")
            if sum(ImageStat.Stat(image).stddev) < 12:
                raise ValueError("检查点画面过于单一；请选包含固定失败文字的区域")
        elif kind == "name":
            if type(action.get("slot")) is not int or action["slot"] not in (0, 1):
                raise ValueError("名字动作必须指定第一个或第二个输入框")
        else:
            raise ValueError("未知动作类型")
    return macro


def checkpoint_image(action):
    encoded = action.get("image", "")
    if not isinstance(encoded, str) or len(encoded) > 1_000_000:
        raise ValueError("检查点图片过大")
    try:
        with Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))) as image:
            if image.width * image.height > 250_000:
                raise ValueError("检查点图片过大")
            return image.convert("RGB")
    except Exception as exc:
        raise ValueError("无法读取检查点图片") from exc


def encode_image(image):
    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG")
    return base64.b64encode(output.getvalue()).decode("ascii")


def image_error(expected, actual):
    if actual.size != expected.size:
        return 1.0
    # Count changed pixels so a changed line of text is not diluted by a dark background.
    # This is a visual gate, not semantic success detection.
    channels = ImageChops.difference(expected, actual.convert("RGB")).split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    histogram = maximum.histogram()
    return sum(histogram[25:]) / (expected.width * expected.height)


def load(path):
    if path.stat().st_size > 10_000_000:
        raise ValueError("录制文件过大")
    return validate(json.loads(path.read_text(encoding="utf-8")))


def save(path, macro):
    validate(macro)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(macro, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def validate_replay(macro, repeat, interval, timeout, tolerance):
    validate(macro)
    if type(repeat) is not int or not 1 <= repeat <= 10000:
        raise ValueError("回放次数应为 1–10000")
    if not number(interval, 2, 600) or not number(timeout, 1, 120) or not number(tolerance, .001, .2):
        raise ValueError("间隔需 2–600 秒，检查点超时需 1–120 秒，图像容差需 0.001–0.2")
    actions = macro["actions"]
    checkpoints = [i for i, a in enumerate(actions) if a["type"] == "checkpoint"]
    names = [i for i, a in enumerate(actions) if a["type"] == "name"]
    if repeat > 1 and (not checkpoints or (names and max(checkpoints) < max(names))):
        raise ValueError("循环回放必须在输入角色名之后录制 F9 失败提示检查点")


def replay(macro, desktop, repeat=1, interval=5, timeout=20, tolerance=.02, report=print):
    validate_replay(macro, repeat, interval, timeout, tolerance)
    actions = macro["actions"]
    for cycle in range(1, repeat + 1):
        report(f"第 {cycle}/{repeat} 轮")
        for index, action in enumerate(actions, 1):
            desktop.wait(action["delay"])
            desktop.guard()
            report(f"  动作 {index}: {action['type']}")
            if action["type"] == "checkpoint":
                expected = checkpoint_image(action)
                deadline = desktop.now() + timeout
                matches = 0
                while True:
                    desktop.guard()
                    error = image_error(expected, desktop.capture(action["box"]))
                    matches = matches + 1 if error <= tolerance else 0
                    if matches >= 2:
                        break
                    if desktop.now() >= deadline:
                        raise RuntimeError(f"未看到录制的失败提示，停止回放（可能成功、页面变化或响应超时；需人工查看）。图像误差 {error:.3f}")
                    desktop.wait(.15)
                desktop.guard()
            elif action["type"] == "name":
                desktop.type_name(macro["names"][action["slot"]])
            else:
                desktop.click(action)
        if cycle < repeat:
            desktop.wait(interval)
    report("已达到回放次数上限；请查看实际注册结果。")
