"""FastAPI Application Factory for INTELX."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from intelx.api.router import root_api_router
from intelx.app.lifespan import lifespan
from intelx.app.middleware import RequestContextMiddleware
from intelx.core.errors import (
    IntelXError,
    generic_exception_handler,
    intelx_exception_handler,
)
from intelx.core.version import PROJECT_NAME, __version__
from intelx.web.routes import web_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=PROJECT_NAME,
        version=__version__,
        description="Standalone, evidence-driven research & intelligence platform",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # 1. Register middleware (RequestContextMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2. Register exception handlers
    app.add_exception_handler(IntelXError, intelx_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)

    # 3. Mount static assets
    static_dir = Path(__file__).parent.parent / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 4. Register routers
    app.include_router(root_api_router)
    app.include_router(web_router)

    return app
