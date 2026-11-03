"""Read packaged resources without depending on the current working directory."""
from pathlib import Path
import sys


def resource_root():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
