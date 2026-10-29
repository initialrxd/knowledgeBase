"""Virtual-environment paths without assuming the host is Windows."""
from __future__ import annotations

import sys
from pathlib import Path


def venv_executable(environment: Path, name="python", platform=None) -> Path:
    windows = (platform or sys.platform) == "win32"
    return environment / ("Scripts" if windows else "bin") / (name + ".exe" if windows else name)
