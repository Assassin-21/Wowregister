"""Owner-only offline card generator. Outputs stay in the ignored data folder."""
import argparse
from datetime import datetime, timedelta, timezone
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from license_server.api.verify import key_hash


def main():
    parser = argparse.ArgumentParser(description="生成卡密与 JSONBin 导入数据；不会联网修改远端")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--days", type=int, default=30, help="有效天数，0 表示永久")
    parser.add_argument("--device-id", required=True, help="目标电脑的 64 位机器码")
    parser.add_argument("--output", type=Path, default=Path("data/licensing"))
    args = parser.parse_args()
    if not 1 <= args.count <= 1000 or not 0 <= args.days <= 36500:
        parser.error("count 需 1–1000，days 需 0–36500")
    if not re.fullmatch(r"[a-f0-9]{64}", args.device_id):
        parser.error("机器码应为 64 位小写十六进制")
    pepper = os.environ.get("LICENSE_PEPPER") or getpass.getpass("输入 Vercel 的 LICENSE_PEPPER（不会显示）：")
    if len(pepper) < 32:
        parser.error("LICENSE_PEPPER 至少 32 个字符，必须与服务端相同")
    expires = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat() if args.days else None
    record, cards = {"schema_version": 1, "licenses": {}}, []
    for _ in range(args.count):
        card = "WA-" + secrets.token_hex(16).upper()
        record["licenses"][key_hash(card, pepper)] = dict(enabled=True, expires_at=expires, device_id=args.device_id)
        cards.append(card)
    args.output.mkdir(parents=True, exist_ok=True)
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + secrets.token_hex(3)
    json_path, cards_path = args.output / (tag + "_jsonbin.json"), args.output / (tag + "_cards.txt")
    json_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    cards_path.write_text("\n".join(cards) + "\n", encoding="utf-8")
    print(f"已生成 {args.count} 张卡：\nJSONBin 数据：{json_path.resolve()}\n卡密明文（请妥善保管）：{cards_path.resolve()}")
    print("已有卡密时，请将新 licenses 条目合并到原 Bin；不要覆盖原数据。")


if __name__ == "__main__":
    main()
