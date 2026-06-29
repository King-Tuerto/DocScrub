"""
DocScrub FastAPI application entry point.

Usage:
    from backend.main import create_app, load_config
    app = create_app(config=load_config("config.json"))
"""

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from backend.db.database import init_db
from backend.routes import upload, anonymize, review, export, reidentify, images, roster

# ---------------------------------------------------------------------------
# Project root (absolute, resolved at import time)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """
    Load configuration from a JSON file.

    Raises:
        FileNotFoundError: if the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def get_server_config() -> dict:
    """Return the server bind configuration (host / port)."""
    return {"host": "127.0.0.1", "port": 8000}


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    config: Optional[dict] = None,
    frontend_dir: Optional[Path] = None,
) -> FastAPI:
    # Configure application-level logging so pipeline/LLM logs appear in the
    # terminal alongside uvicorn output.  basicConfig is a no-op if the root
    # logger already has handlers (e.g. in tests), so this is safe to call here.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    """
    Create and configure the FastAPI application.

    Args:
        config: Configuration dict (see config.json for keys).
                Defaults to loading from the project-root config.json.
        frontend_dir: Path to the frontend directory.
                      Defaults to <project_root>/frontend.
    """
    if config is None:
        config = load_config(_PROJECT_ROOT / "config.json")

    if frontend_dir is None:
        frontend_dir = _PROJECT_ROOT / "frontend"

    # Ensure output directory exists
    output_dir = Path(config.get("output_directory", "./output"))
    if not output_dir.is_absolute():
        output_dir = _PROJECT_ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialise database
    db_path = Path(config.get("db_path", "./docscrub.db"))
    if not db_path.is_absolute():
        db_path = _PROJECT_ROOT / db_path
    init_db(db_path)

    app = FastAPI(title="DocScrub", version="0.1.0")

    # Store config and db_path on app state for use by routes
    app.state.config = config
    app.state.db_path = db_path

    # ---------------------------------------------------------------------------
    # API routes (registered before static mount so they take priority)
    # ---------------------------------------------------------------------------

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    @app.get("/models")
    def list_models_proxy():
        """Proxy to LLM endpoint model list — avoids CORS issues from browser."""
        from backend.services.llm_client import LLMClient, LLMUnreachableError
        client = LLMClient(
            endpoint=config.get("llm_endpoint", "http://localhost:11434"),
            model=config.get("default_model", "llama3.1:8b"),
        )
        try:
            return {"models": client.list_models()}
        except LLMUnreachableError:
            return {"models": [], "error": "LLM endpoint unreachable"}

    app.include_router(upload.router)
    app.include_router(anonymize.router)
    app.include_router(review.router)
    app.include_router(export.router)
    app.include_router(reidentify.router)
    app.include_router(images.router)
    app.include_router(roster.router)

    # ---------------------------------------------------------------------------
    # Static frontend (must be last — catches-all remaining paths)
    # ---------------------------------------------------------------------------
    if frontend_dir.exists():
        # Serve /css, /js sub-paths explicitly so they resolve correctly
        app.mount(
            "/css",
            StaticFiles(directory=str(frontend_dir / "css")),
            name="css",
        )
        app.mount(
            "/js",
            StaticFiles(directory=str(frontend_dir / "js")),
            name="js",
        )

        @app.get("/")
        def serve_index():
            return FileResponse(str(frontend_dir / "index.html"))

    return app
