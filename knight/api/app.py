from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from knight.api.config import settings
from knight.api.routers.github import router as github_router
from knight.api.routers.health import router as health_router
from knight.api.routers.webhooks import router as webhook_router
from knight.daemon.poller import CloudPoller
from knight.runtime.logging_config import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    poller = CloudPoller()
    poller.start()
    yield
    poller.stop()


app = FastAPI(
    title=settings.title,
    description=settings.description,
    version=settings.version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

app.include_router(health_router, prefix=settings.api_base_prefix)
app.include_router(webhook_router, prefix=settings.api_base_prefix)
app.include_router(github_router, prefix=settings.api_base_prefix)
