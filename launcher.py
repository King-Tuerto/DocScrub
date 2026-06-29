#!/usr/bin/env python3
"""
DocScrub launcher.

Starts the uvicorn server in the background (no console window on Windows),
opens the browser, then shows a small status window. Closing the window
terminates the server cleanly.

Invoked by:
  - The desktop shortcut created by setup.bat  (via pythonw.exe)
  - start.bat  (fallback, shows a brief cmd flash before this runs)
"""
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
URL = "http://127.0.0.1:8000"
PORT = 8000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_in_use() -> bool:
    """Return True if something is already listening on PORT."""
    for _ in range(3):
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1.0):
                return True
        except OSError:
            pass
    return False


def _start_server() -> subprocess.Popen:
    kwargs: dict = {}
    if sys.platform == "win32":
        # No console window on Windows
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "backend.main:create_app",
            "--factory",
            "--host", "127.0.0.1",
            "--port", str(PORT),
            "--log-level", "warning",
            "--no-access-log",
        ],
        cwd=ROOT,
        **kwargs,
    )


def _wait_then_open_browser() -> None:
    for _ in range(20):          # up to 10 seconds
        time.sleep(0.5)
        if _port_in_use():
            break
    webbrowser.open(URL)


# ---------------------------------------------------------------------------
# Status window (Tkinter)
# ---------------------------------------------------------------------------

def _run_tk_window(proc: subprocess.Popen) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.title("DocScrub")
    root.geometry("320x130")
    root.resizable(False, False)

    # Icon
    icon_path = ROOT / "assets" / "docscrub.ico"
    if icon_path.exists():
        try:
            root.iconbitmap(str(icon_path))
        except Exception:
            pass

    # Centre on screen
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - 320) // 2
    y = (sh - 130) // 2
    root.geometry(f"320x130+{x}+{y}")

    tk.Label(
        root,
        text="● DocScrub is running",
        font=("Segoe UI", 12, "bold"),
        fg="#0d9488",
        pady=12,
    ).pack()

    tk.Label(
        root,
        text="Close this window to stop the server.",
        font=("Segoe UI", 9),
        fg="#666",
    ).pack()

    tk.Button(
        root,
        text="Open in Browser",
        command=lambda: webbrowser.open(URL),
        font=("Segoe UI", 9),
        padx=10,
        pady=4,
        relief="flat",
        bg="#0d9488",
        fg="white",
        activebackground="#0f766e",
        activeforeground="white",
        cursor="hand2",
    ).pack(pady=10)

    def on_close() -> None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


# ---------------------------------------------------------------------------
# Fallback: no Tkinter (server-only mode, stop with Ctrl+C)
# ---------------------------------------------------------------------------

def _run_console(proc: subprocess.Popen) -> None:
    print(f"DocScrub is running at {URL}")
    print("Press Ctrl+C to stop.")
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    os.chdir(ROOT)

    if _port_in_use():
        webbrowser.open(URL)
        return

    proc = _start_server()
    threading.Thread(target=_wait_then_open_browser, daemon=True).start()

    try:
        _run_tk_window(proc)
    except ImportError:
        _run_console(proc)

    # Ensure the process is gone — on_close may have already killed it
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


if __name__ == "__main__":
    main()
