"""Write portable, UTF-8 dependency locks without local editable paths."""
import subprocess
from pathlib import Path

project = Path(__file__).resolve().parent.parent
for environment, output in ((".venv", "requirements.lock.txt"), (".venv-webui", "requirements-webui.lock.txt")):
    python = project / environment / "Scripts" / "python.exe"
    if not python.exists():
        continue
    lines = subprocess.check_output([str(python), "-m", "pip", "freeze", "--exclude-editable"], text=True).splitlines()
    lines = [line + '; sys_platform == "win32"' if line.lower().startswith("pywin32==") else line for line in lines]
    (project / output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Locked {len(lines)} packages: {output}")
