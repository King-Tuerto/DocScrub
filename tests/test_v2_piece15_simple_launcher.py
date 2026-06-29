"""
V2 Piece 15 — Replace launcher.py with simple start.bat

Verifies:
1. launcher.py is gone — no dead code left in the repo
2. start.bat contains the required commands (init_db call, uvicorn --factory,
   browser open via "start http://", close-window-to-stop mechanic)
3. create_shortcut.py targets cmd.exe and start.bat (not pythonw / launcher.py)
4. No references to launcher.py remain in source files
"""

from pathlib import Path


ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# launcher.py must be gone
# ---------------------------------------------------------------------------

class TestLauncherGone:
    def test_launcher_py_deleted(self):
        assert not (ROOT / "launcher.py").exists(), (
            "launcher.py still exists — it must be deleted"
        )

    def test_no_source_file_imports_launcher(self):
        """No .py source file outside tests/ should reference launcher.py."""
        bad = []
        for f in ROOT.rglob("*.py"):
            if "tests" in f.parts:
                continue
            if "launcher" in f.read_text(encoding="utf-8", errors="ignore"):
                bad.append(str(f.relative_to(ROOT)))
        assert not bad, f"launcher.py referenced in source files: {bad}"

    def test_readme_does_not_mention_launcher(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        assert "launcher.py" not in readme, "README.md still references launcher.py"


# ---------------------------------------------------------------------------
# start.bat — required content
# ---------------------------------------------------------------------------

class TestStartBat:
    def _bat(self) -> str:
        return (ROOT / "start.bat").read_text(encoding="utf-8", errors="replace")

    def test_start_bat_exists(self):
        assert (ROOT / "start.bat").exists()

    def test_runs_init_db_via_python(self):
        """Must call python -c with create_app to ensure DB is initialised."""
        bat = self._bat()
        assert "from backend.main import create_app" in bat, (
            "start.bat must call 'from backend.main import create_app' to initialise the DB"
        )

    def test_starts_uvicorn_with_factory(self):
        bat = self._bat()
        assert "uvicorn" in bat
        assert "--factory" in bat

    def test_opens_browser(self):
        """Must open http://127.0.0.1:8000 automatically."""
        bat = self._bat()
        assert "127.0.0.1:8000" in bat
        # 'start' is the Windows command to open a URL in the default browser
        assert "start" in bat.lower()

    def test_changes_to_script_directory(self):
        """cd /d %~dp0 so relative paths resolve correctly."""
        bat = self._bat()
        assert "%~dp0" in bat

    def test_no_pythonw_reference(self):
        """No pythonw — terminal window must stay visible."""
        bat = self._bat()
        assert "pythonw" not in bat.lower()

    def test_no_launcher_reference(self):
        bat = self._bat()
        assert "launcher" not in bat.lower()

    def test_error_handling_present(self):
        """Must check errorlevel after python init so failures are visible."""
        bat = self._bat()
        assert "errorlevel" in bat.lower()


# ---------------------------------------------------------------------------
# create_shortcut.py — must target cmd.exe + start.bat
# ---------------------------------------------------------------------------

class TestCreateShortcut:
    def _src(self) -> str:
        return (ROOT / "create_shortcut.py").read_text(encoding="utf-8")

    def test_window_style_minimised(self):
        """WindowStyle = 7 makes the terminal start minimised in the taskbar."""
        src = self._src()
        assert "WindowStyle" in src
        assert "7" in src

    def test_targets_cmd_not_pythonw(self):
        src = self._src()
        assert "cmd" in src.lower(), "create_shortcut.py must target cmd.exe"
        assert "pythonw" not in src.lower(), (
            "create_shortcut.py must not reference pythonw.exe"
        )

    def test_references_start_bat(self):
        src = self._src()
        assert "start.bat" in src, "create_shortcut.py must point to start.bat"

    def test_no_launcher_reference(self):
        src = self._src()
        assert "launcher" not in src.lower()
