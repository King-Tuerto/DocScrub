"""
V2 Piece 14 — UX improvements

1. DATABASE INIT robustness
   _PROJECT_ROOT uses Path(__file__).resolve() so it is always absolute.
   init_db is called with a resolved absolute path in both the factory call
   and the lifespan handler.  The lifespan uses the closure variable, not
   app.state, to avoid any Starlette state-attachment timing edge cases.

2. END SESSION BUTTON
   The footer must have an "End Session" button (not "Stop Server").
   The button triggers /shutdown and shows a clean stopped message.

3. CSV TEMPLATE DOWNLOAD
   GET /template/csv returns a well-formed CSV with the correct column
   headers and two example rows, served with the correct filename.

4. README accuracy
   Column name is student_id (not id).  Covered indirectly by checking
   the template CSV uses student_id.
"""

import csv
import io
from pathlib import Path


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_client(tmp_path):
    from fastapi.testclient import TestClient
    from backend.main import create_app

    config = {
        "db_path": str(tmp_path / "test.db"),
        "output_directory": str(tmp_path / "output"),
        "llm_endpoint": "http://localhost:11434",
        "default_model": "llama3.1:8b",
    }
    return TestClient(create_app(config=config))


# ---------------------------------------------------------------------------
# Issue 1 — DB init robustness
# ---------------------------------------------------------------------------

class TestProjectRootIsAbsolute:
    def test_project_root_resolved(self):
        """_PROJECT_ROOT must be an absolute path regardless of how __file__ is set."""
        from backend.main import _PROJECT_ROOT
        assert _PROJECT_ROOT.is_absolute(), (
            f"_PROJECT_ROOT is not absolute: {_PROJECT_ROOT!r}"
        )

    def test_project_root_contains_config_json(self):
        """_PROJECT_ROOT must point to the actual project root (has config.json)."""
        from backend.main import _PROJECT_ROOT
        assert (_PROJECT_ROOT / "config.json").exists(), (
            f"config.json not found under _PROJECT_ROOT={_PROJECT_ROOT!r}"
        )


class TestDbPathAlwaysAbsolute:
    def test_app_state_db_path_is_absolute(self, tmp_path):
        """app.state.db_path must always be absolute after create_app()."""
        from backend.main import create_app
        config = {
            "db_path": "./docscrub_test.db",  # intentionally relative
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        app = create_app(config=config)
        assert app.state.db_path.is_absolute(), (
            f"app.state.db_path is not absolute: {app.state.db_path!r}"
        )
        # Clean up the created DB
        try:
            app.state.db_path.unlink(missing_ok=True)
        except Exception:
            pass

    def test_db_tables_exist_after_factory_call(self, tmp_path):
        """Tables must exist immediately after create_app() — no request needed."""
        import sqlite3
        from backend.main import create_app

        db_path = tmp_path / "fresh.db"
        config = {
            "db_path": str(db_path),
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        create_app(config=config)

        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        for t in ("jobs", "files", "mappings", "roster_entries"):
            assert t in tables, f"Table '{t}' missing after create_app()"

    def test_lifespan_reinitialises_deleted_db(self, tmp_path):
        """
        Simulate the delete-and-relaunch scenario:
        factory creates DB → DB is deleted → lifespan startup recreates it.
        """
        import sqlite3
        from fastapi.testclient import TestClient
        from backend.main import create_app

        db_path = tmp_path / "lifecycle.db"
        config = {
            "db_path": str(db_path),
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        app = create_app(config=config)

        # Simulate: user deletes the DB after the factory ran but before first use
        db_path.unlink()
        assert not db_path.exists()

        # The lifespan startup (triggered by TestClient context manager) must recreate it
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200

        assert db_path.exists(), "DB was not recreated by lifespan"
        conn = sqlite3.connect(str(db_path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
        assert "jobs" in tables


# ---------------------------------------------------------------------------
# Issue 2 — End Session button
# ---------------------------------------------------------------------------

class TestEndSessionButton:
    def test_html_has_end_session_button(self):
        """index.html must contain an 'End Session' button element."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "End Session" in html, "No 'End Session' text found in index.html"

    def test_html_no_longer_has_stop_server(self):
        """The old 'Stop Server' button label must be gone."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        # The button text "■ Stop Server" must be removed
        assert "■ Stop Server" not in html

    def test_end_session_btn_class_in_css(self):
        """CSS must define .end-session-btn styling."""
        css = Path("frontend/css/styles.css").read_text(encoding="utf-8")
        assert ".end-session-btn" in css

    def test_end_session_calls_shutdown(self):
        """The End Session JS must call POST /shutdown."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "/shutdown" in html

    def test_end_session_shows_stopped_message(self):
        """After clicking, the page must display a 'has stopped' message."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        # The page-replacement string must mention DocScrub stopping
        assert "DocScrub has stopped" in html

    def test_shutdown_route_registered_in_app(self, tmp_path):
        """/shutdown must appear in the app's route table — no live call needed."""
        from backend.main import create_app

        config = {
            "db_path": str(tmp_path / "test.db"),
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        app = create_app(config=config)
        routes = {r.path for r in app.routes if hasattr(r, "path")}
        assert "/shutdown" in routes, f"/shutdown not registered. Routes: {routes}"


# ---------------------------------------------------------------------------
# Issue 3 — CSV template download
# ---------------------------------------------------------------------------

class TestCsvTemplate:
    def test_template_endpoint_returns_200(self, tmp_path):
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        assert resp.status_code == 200

    def test_template_content_type_is_csv(self, tmp_path):
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        assert "text/csv" in resp.headers.get("content-type", "")

    def test_template_filename_header(self, tmp_path):
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        cd = resp.headers.get("content-disposition", "")
        assert "docscrub_name_list_template.csv" in cd

    def test_template_has_correct_headers(self, tmp_path):
        """CSV must have the exact canonical column names."""
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        assert reader.fieldnames is not None
        expected = {
            "first_name", "last_name", "preferred_name",
            "student_id", "email", "also_remove",
        }
        assert set(reader.fieldnames) == expected, (
            f"CSV headers mismatch. Got: {reader.fieldnames}"
        )

    def test_template_has_two_example_rows(self, tmp_path):
        """CSV must contain exactly 2 example data rows."""
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 2, f"Expected 2 example rows, got {len(rows)}"

    def test_template_uses_student_id_not_id(self, tmp_path):
        """Column must be named 'student_id', not the old 'id' name."""
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        assert "student_id" in resp.text
        # Old incorrect name must not appear as a column header
        lines = resp.text.splitlines()
        header_fields = [f.strip() for f in lines[0].split(",")]
        assert "id" not in header_fields, (
            "Column named 'id' found — must be 'student_id'"
        )

    def test_template_example_rows_have_semicolon_in_also_remove(self, tmp_path):
        """Second example row must demonstrate semicolon-separated also_remove values."""
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        also_remove_values = [r["also_remove"] for r in rows]
        assert any(";" in v for v in also_remove_values), (
            "No example with semicolons in also_remove — template is missing the multi-value demo"
        )

    def test_template_is_parseable_by_roster_parser(self, tmp_path):
        """The template CSV must parse cleanly through the actual roster parser."""
        from backend.services.roster_parser import parse_roster
        client = _make_client(tmp_path)
        resp = client.get("/template/csv")
        entries = parse_roster(resp.content, filename="docscrub_name_list_template.csv")
        assert len(entries) == 2
        first_names = {e.first_name for e in entries}
        assert "Jane" in first_names
        assert "John" in first_names

    def test_template_link_present_in_html(self):
        """index.html must contain a link or reference to /template/csv."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "/template/csv" in html

    def test_template_download_attribute_present(self):
        """The template link must have a download attribute pointing to the correct filename."""
        html = Path("frontend/index.html").read_text(encoding="utf-8")
        assert "docscrub_name_list_template.csv" in html
