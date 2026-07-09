"""
FastAPI app factory.

Phase 1: health + token-protected read endpoints. Later phases mount the control
router, the WebSocket hub, and (in production) serve the built React PWA from
webapp/static as same-origin static files.
"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from webapp import ws
from webapp.routers import config, control, monitor
from webapp.settings import get_settings

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class SPAStaticFiles(StaticFiles):
    """Serve real files; fall back to index.html on 404 so client-side routes
    (e.g. a hard refresh on /settings) work. /api and /ws match earlier routers,
    so this only affects front-end paths."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Dream Machine — Trading Bot", version="0.1.0",
                  docs_url="/api/docs", openapi_url="/api/openapi.json")

    # CORS only for the Vite dev server; the built PWA is served same-origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.dev_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        """Unauthenticated liveness probe — no secrets, just 'am I up'."""
        return {"ok": True, "service": "dream-machine", "version": "0.1.0",
                "token_configured": settings.token is not None}

    app.include_router(monitor.router)
    app.include_router(control.router)
    app.include_router(config.router)
    app.include_router(ws.router)

    # Serve the built PWA if present (production). Absent during backend-only dev.
    if os.path.isdir(_STATIC_DIR):
        app.mount("/", SPAStaticFiles(directory=_STATIC_DIR, html=True), name="static")

    return app


app = create_app()
