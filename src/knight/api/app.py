import os

from api.config import settings
from api.routers.health import router as health_router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title=settings.title, description=settings.description, version=settings.version
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS") or [],
    allow_credentials=bool(os.getenv("ALLOW_CREDENTIALS")),
    allow_methods=settings.cors_methods,
    allow_headers=settings.cors_headers,
)

# Include routes
app.include_router(health_router, prefix=settings.api_base_prefix)
