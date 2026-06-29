#!/usr/bin/env python3
"""
Create a "DocScrub" shortcut on the user's Desktop.

Called by setup.bat. Uses PowerShell's WScript.Shell COM object so
no third-party libraries are needed.

The shortcut launches start.bat minimised (WindowStyle 7) so the terminal
sits in the taskbar while the server runs. Closing it from the taskbar
stops the server cleanly.

Exit code 0 = success, 1 = failure.
"""
import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).parent.resolve()

    cmd = Path(os.environ.get("ComSpec", r"C:\Windows\System32\cmd.exe"))
    start_bat = root / "start.bat"
    desktop = Path(os.path.expandvars("%USERPROFILE%")) / "Desktop"
    shortcut_path = desktop / "DocScrub.lnk"
    icon = root / "assets" / "docscrub.ico"

    arguments = f'/c ""{start_bat}""'

    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut('{shortcut_path}')
$s.TargetPath       = '{cmd}'
$s.Arguments        = '{arguments}'
$s.WorkingDirectory = '{root}'
$s.IconLocation     = '{icon}'
$s.Description      = 'DocScrub -- Document Anonymizer'
$s.WindowStyle      = 7
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
