"""
Piece 1 — Project Scaffold & Config

Tests:
- Required directories exist after scaffold
- config.json loads with correct defaults
- FastAPI app boots and serves a health check
- start.bat exists
"""

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Directory structure
# ---------------------------------------------------------------------------

class TestDirectoryStructure:
    def test_backend_dir_exists(self):
        assert (PROJECT_ROOT / "backend").is_dir()

    def test_backend_routes_dir_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes").is_dir()

    def test_backend_services_dir_exists(self):
        assert (PROJECT_ROOT / "backend" / "services").is_dir()

    def test_backend_models_dir_exists(self):
        assert (PROJECT_ROOT / "backend" / "models").is_dir()

    def test_backend_db_dir_exists(self):
        assert (PROJECT_ROOT / "backend" / "db").is_dir()

    def test_frontend_dir_exists(self):
        assert (PROJECT_ROOT / "frontend").is_dir()

    def test_frontend_css_dir_exists(self):
        assert (PROJECT_ROOT / "frontend" / "css").is_dir()

    def test_frontend_js_dir_exists(self):
        assert (PROJECT_ROOT / "frontend" / "js").is_dir()

    def test_output_dir_exists(self):
        assert (PROJECT_ROOT / "output").is_dir()

    def test_mappings_dir_exists(self):
        assert (PROJECT_ROOT / "mappings").is_dir()

    def test_tests_dir_exists(self):
        assert (PROJECT_ROOT / "tests").is_dir()


# ---------------------------------------------------------------------------
# Source files exist
# ---------------------------------------------------------------------------

class TestSourceFilesExist:
    def test_main_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "main.py").is_file()

    def test_schemas_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "models" / "schemas.py").is_file()

    def test_database_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "db" / "database.py").is_file()

    def test_file_reader_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "file_reader.py").is_file()

    def test_image_extractor_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "image_extractor.py").is_file()

    def test_llm_client_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "llm_client.py").is_file()

    def test_regex_engine_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "regex_engine.py").is_file()

    def test_mapper_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "mapper.py").is_file()

    def test_replacer_py_exists(self):
        assert (PROJECT_ROOT / "backend" / "services" / "replacer.py").is_file()

    def test_upload_route_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes" / "upload.py").is_file()

    def test_anonymize_route_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes" / "anonymize.py").is_file()

    def test_review_route_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes" / "review.py").is_file()

    def test_export_route_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes" / "export.py").is_file()

    def test_reidentify_route_exists(self):
        assert (PROJECT_ROOT / "backend" / "routes" / "reidentify.py").is_file()

    def test_index_html_exists(self):
        assert (PROJECT_ROOT / "frontend" / "index.html").is_file()

    def test_styles_css_exists(self):
        assert (PROJECT_ROOT / "frontend" / "css" / "styles.css").is_file()

    def test_app_js_exists(self):
        assert (PROJECT_ROOT / "frontend" / "js" / "app.js").is_file()

    def test_start_bat_exists(self):
        assert (PROJECT_ROOT / "start.bat").is_file()


# ---------------------------------------------------------------------------
# config.json
# ---------------------------------------------------------------------------

class TestConfig:
    def test_config_json_exists(self):
        assert (PROJECT_ROOT / "config.json").is_file()

    def test_config_is_valid_json(self):
        text = (PROJECT_ROOT / "config.json").read_text(encoding="utf-8")
        data = json.loads(text)
        assert isinstance(data, dict)

    def test_config_has_llm_endpoint(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert "llm_endpoint" in data
        assert data["llm_endpoint"] == "http://localhost:11434"

    def test_config_has_default_model(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert "default_model" in data

    def test_config_has_output_directory(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert "output_directory" in data

    def test_config_has_db_path(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert "db_path" in data

    def test_config_has_image_review_default(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert data.get("image_review_default") == "remove"

    def test_config_has_custom_regex_patterns(self):
        data = json.loads((PROJECT_ROOT / "config.json").read_text())
        assert "custom_regex_patterns" in data
        assert isinstance(data["custom_regex_patterns"], list)

    def test_config_loader_returns_dict(self):
        from backend.main import load_config
        config = load_config(PROJECT_ROOT / "config.json")
        assert isinstance(config, dict)
        assert "llm_endpoint" in config

    def test_config_loader_missing_file_raises(self):
        from backend.main import load_config
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/path/config.json"))


# ---------------------------------------------------------------------------
# FastAPI app bootstrap
# ---------------------------------------------------------------------------

class TestAppBootstrap:
    def test_app_imports(self):
        from backend.main import create_app
        assert callable(create_app)

    def test_app_creates_instance(self, default_config, tmp_path):
        from backend.main import create_app
        config = dict(default_config)
        config["db_path"] = str(tmp_path / "test.db")
        app = create_app(config=config)
        assert app is not None

    def test_health_check_returns_200(self, app_client):
        response = app_client.get("/health")
        assert response.status_code == 200

    def test_health_check_returns_ok(self, app_client):
        response = app_client.get("/health")
        data = response.json()
        assert data.get("status") == "ok"

    def test_app_binds_localhost_only(self, default_config, tmp_path):
        """create_app should expose a host config defaulting to 127.0.0.1."""
        from backend.main import get_server_config
        cfg = get_server_config()
        assert cfg["host"] == "127.0.0.1"

    def test_app_uses_port_8000(self, default_config, tmp_path):
        from backend.main import get_server_config
        cfg = get_server_config()
        assert cfg["port"] == 8000
