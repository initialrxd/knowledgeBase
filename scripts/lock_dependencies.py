"""Write portable, UTF-8 dependency locks without local editable paths."""
import subprocess
import sys
from pathlib import Path

from platform_paths import venv_executable

project = Path(__file__).resolve().parent.parent
python = venv_executable(project / ".venv")
if not python.exists():
    raise SystemExit("Knowledge environment is missing; run scripts/manage.py install first.")
lines = subprocess.check_output([str(python), "-m", "pip", "freeze", "--exclude-editable"], text=True).splitlines()
lines = [line + '; sys_platform == "win32"' if line.lower().startswith("pywin32==") else line for line in lines]
output = "requirements.lock.txt" if sys.platform == "win32" else f"requirements.{sys.platform}.lock.txt"
(project / output).write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Locked {len(lines)} knowledge packages: {output}")
