"""Write the optional Open WebUI dependency lock independently."""
import subprocess
import sys
from pathlib import Path

from platform_paths import venv_executable

project = Path(__file__).resolve().parent.parent
python = venv_executable(project / ".venv-webui")
if not python.exists():
    raise SystemExit("Open WebUI environment is missing; run scripts/openwebui.py install first.")
lines = subprocess.check_output([str(python), "-m", "pip", "freeze", "--exclude-editable"], text=True).splitlines()
lines = [line + '; sys_platform == "win32"' if line.lower().startswith("pywin32==") else line for line in lines]
output = "requirements-webui.lock.txt" if sys.platform == "win32" else f"requirements-webui.{sys.platform}.lock.txt"
(project / output).write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Locked {len(lines)} Open WebUI packages: {output}")
