"""Developer build: bundle the browser UI, Python runtime and active profiles."""
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    config = json.loads((ROOT / "wowregister/default_service.json").read_text(encoding="utf-8"))
    if not config.get("url", "").startswith("https://"):
        raise SystemExit("请先配置生产验证接口 wowregister/default_service.json，再构建正式 EXE。")
    data = ["wowregister/panel.html", "wowregister/default_service.json",
            "data/registration/direct/macro.json", "data/registration/ruleset/macro.json",
            "data/registration/ruleset/macro_1.json"]
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--windowed",
               "--name", "Wowregister", "--distpath", str(ROOT / "dist"),
               "--workpath", str(ROOT / "build"), "--specpath", str(ROOT / "build")]
    for name in data:
        command += ["--add-data", str(ROOT / name) + ":" + str(Path(name).parent)]
    subprocess.run(command + [str(ROOT / "launcher.py")], cwd=ROOT, check=True)
    with zipfile.ZipFile(ROOT / "dist/Wowregister-Windows-x64.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(ROOT / "dist/Wowregister.exe", "Wowregister.exe")
        archive.write(ROOT / "docs/EXE使用说明.txt", "使用说明.txt")
    print(ROOT / "dist/Wowregister-Windows-x64.zip")


if __name__ == "__main__":
    main()
