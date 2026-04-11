import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from knight.api.config import settings
from knight.api.routers.health import router as health_router
from knight.api.routers.webhooks import router as webhook_router
from knight.runtime.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title=settings.title,
    description=settings.description,
    version=settings.version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS") or [],
    allow_credentials=bool(os.getenv("ALLOW_CREDENTIALS")),
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

app.include_router(health_router, prefix=settings.api_base_prefix)
app.include_router(webhook_router, prefix=settings.api_base_prefix)
