"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, health, masters, retention, webhooks
from app.config import get_settings
from app.database import Base, engine


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Alembic owns production schema changes. Automatic table creation is a
    # local-development convenience and is disabled in production.
    if not get_settings().is_production:
        Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    if errors := settings.production_errors():
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))
    app = FastAPI(
        title="Agricultural Market Intelligence API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(health.router)
    app.include_router(webhooks.router, prefix=settings.api_prefix)
    app.include_router(admin.router, prefix=settings.api_prefix)
    app.include_router(masters.router, prefix=settings.api_prefix)
    app.include_router(retention.router, prefix=settings.api_prefix)
    return app


app = create_app()
