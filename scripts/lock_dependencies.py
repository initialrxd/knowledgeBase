"""Write portable, UTF-8 dependency locks without local editable paths."""
import subprocess
import sys
from pathlib import Path

from platform_paths import venv_executable

project = Path(__file__).resolve().parent.parent
for environment, output in ((".venv", "requirements.lock.txt"), (".venv-webui", "requirements-webui.lock.txt")):
    python = venv_executable(project / environment)
    if not python.exists():
        continue
    lines = subprocess.check_output([str(python), "-m", "pip", "freeze", "--exclude-editable"], text=True).splitlines()
    lines = [line + '; sys_platform == "win32"' if line.lower().startswith("pywin32==") else line for line in lines]
    # Keep the existing Windows snapshot when freezing a different platform.
    if sys.platform != "win32":
        output = output.replace(".lock.txt", f".{sys.platform}.lock.txt")
    (project / output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Locked {len(lines)} packages: {output}")
