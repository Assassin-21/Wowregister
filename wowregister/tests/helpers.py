"""Keep test scratch files inside the writable project, including cleanup."""

import shutil
import uuid
from pathlib import Path


class ProjectTemporaryDirectory:
    def __init__(self):
        workspace = Path(__file__).resolve().parents[2]
        self.base = (workspace / "data" / "test_tmp").resolve()
        if not self.base.is_relative_to(workspace):
            raise RuntimeError("Test temp directory must stay within the project")
        self.base.mkdir(parents=True, exist_ok=True)
        # Python 3.13 Windows applies special ACLs to mode 0o700, which can
        # exclude the sandbox identity. Inherit the writable project ACL instead.
        self.path = self.base / f"test_{uuid.uuid4().hex}"
        self.path.mkdir()
        self.name = str(self.path)

    def cleanup(self):
        target = self.path.resolve()
        if target.parent != self.base or not target.name.startswith("test_"):
            raise RuntimeError("Test cleanup target is outside its base")
        if target.exists():
            shutil.rmtree(target)

    def __enter__(self):
        return self.name

    def __exit__(self, *args):
        self.cleanup()


def temporary_directory() -> ProjectTemporaryDirectory:
    return ProjectTemporaryDirectory()
