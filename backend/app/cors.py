import os

from fastapi.middleware.cors import CORSMiddleware


DEFAULT_FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def install_global_cors(app):
    """Wrap FastAPI's full middleware stack so even unhandled 500s get CORS headers."""
    configured_value = os.getenv("CORS_ORIGINS")
    allowed_origins = (
        [origin.strip() for origin in configured_value.split(",") if origin.strip()]
        if configured_value is not None
        else list(DEFAULT_FRONTEND_ORIGINS)
    )
    if "*" in allowed_origins:
        raise RuntimeError("CORS_ORIGINS must list explicit origins when credentials are enabled")
    app.middleware_stack = CORSMiddleware(
        app.build_middleware_stack(),
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    return app
