#!/usr/bin/env python3
"""
Create a "DocScrub" shortcut on the user's Desktop.

Called by setup.bat. Uses PowerShell's WScript.Shell COM object so
no third-party libraries are needed.

Exit code 0 = success, 1 = failure.
"""
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).parent.resolve()

    # Prefer pythonw.exe (no console window) over python.exe
    pythonw = Path(sys.executable).parent / "pythonw.exe"
    if not pythonw.exists():
        pythonw = Path(sys.executable)

    desktop = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
    shortcut_path = desktop / "DocScrub.lnk"
    launcher = root / "launcher.py"
    icon = root / "assets" / "docscrub.ico"

    # Build PowerShell script as a string — avoids all cmd.exe escaping issues
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath      = '{pythonw}'
$s.Arguments       = '"{launcher}"'
$s.WorkingDirectory = '{root}'
$s.IconLocation    = '{icon}'
$s.Description     = 'DocScrub — Document Anonymizer'
$s.Save()
"""

    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"Shortcut error: {result.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"Shortcut created: {shortcut_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
