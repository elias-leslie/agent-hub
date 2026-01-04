"""
agent-hub API Server
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    # Startup
    print(f"Starting agent-hub on port {settings.port}")
    yield
    # Shutdown
    print("Shutting down agent-hub")


app = FastAPI(
    title="agent-hub",
    description="Unified agentic AI service for Claude/Gemini workloads",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3002"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy", "service": "agent-hub"}


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Welcome to agent-hub", "docs": "/docs"}


# Import and include routers here
# from app.api import router
# app.include_router(router, prefix="/api")
