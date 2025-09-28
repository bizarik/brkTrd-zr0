"""Main FastAPI application for brākTrād"""

from contextlib import asynccontextmanager
import structlog
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import redis.asyncio as redis
from prometheus_client import make_asgi_app
import uvicorn

from config import settings
from models import Base, UserSettings
from database import engine, get_db, AsyncSessionLocal
from routers import (
    headlines, sentiment, analytics, opportunities, 
    settings as settings_router, portfolio as portfolio_router
    # returns as returns_router  # Temporarily disabled until migration is run
)
from services.cache import CacheManager
from services.scheduler import TaskScheduler

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


# Global instances
cache_manager = None
task_scheduler = None
redis_client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global cache_manager, task_scheduler, redis_client
    
    try:
        # Initialize database
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Load persisted user settings into runtime config (so keys apply after restarts)
        try:
            async with AsyncSessionLocal() as s:
                result = await s.execute(
                    __import__("sqlalchemy").select(UserSettings).where(UserSettings.user_id == "default")
                )
                us = result.scalar_one_or_none()
                if us:
                    if us.finviz_api_key:
                        settings.finviz_api_key = us.finviz_api_key
                    if us.groq_api_key:
                        settings.groq_api_key = us.groq_api_key
                    if us.openrouter_api_key:
                        settings.openrouter_api_key = us.openrouter_api_key
                    if us.finviz_portfolio_numbers:
                        settings.finviz_portfolio_numbers = us.finviz_portfolio_numbers
                    if us.selected_models:
                        settings.selected_models = us.selected_models
        except Exception:
            pass

        # Initialize Redis (with fallback if Redis is not available)
        try:
            redis_client = await redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,  # 5 second timeout
                socket_connect_timeout=5.0
            )
            # Test connection
            await redis_client.ping()
        except Exception as e:
            logger.warning("redis_connection_failed", error=str(e))
            redis_client = None  # App will work without Redis, just no caching
        
        # Initialize cache manager
        cache_manager = CacheManager(redis_client)
        
        # Initialize task scheduler
        task_scheduler = TaskScheduler(redis_client)
        await task_scheduler.start()
        # Expose scheduler via app state for routers to access without circular imports
        app.state.task_scheduler = task_scheduler
        
        logger.info("application_started", environment=settings.environment)
        
        # Validate API keys
        if not settings.finviz_api_key:
            logger.warning("finviz_api_key_not_configured")
        
        if not settings.groq_api_key and not settings.openrouter_api_key:
            logger.warning("no_model_api_keys_configured")
        
        yield
        
    finally:
        # Cleanup
        if task_scheduler:
            await task_scheduler.stop()
        
        if redis_client:
            await redis_client.close()
        
        await engine.dispose()
        
        logger.info("application_stopped")


# Create FastAPI app
app = FastAPI(
    title="brākTrād",
    description="Lightning-fast day/swing trading app with multi-model sentiment analysis",
    version="1.0.0",
    lifespan=lifespan
)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(
    headlines.router,
    prefix="/api/headlines",
    tags=["headlines"]
)

app.include_router(
    sentiment.router,
    prefix="/api/sentiment",
    tags=["sentiment"]
)

app.include_router(
    analytics.router,
    prefix="/api/analytics",
    tags=["analytics"]
)

app.include_router(
    opportunities.router,
    prefix="/api/opportunities",
    tags=["opportunities"]
)

app.include_router(
    settings_router.router,
    prefix="/api/settings",
    tags=["settings"]
)

app.include_router(
    portfolio_router.router,
    prefix="/api/portfolio",
    tags=["portfolio"]
)

# app.include_router(
#     returns_router.router,
#     prefix="/api/returns",
#     tags=["returns"]
# )


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "environment": settings.environment,
        "version": "1.0.0"
    }


# Metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Handle uncaught exceptions"""
    logger.error(
        "unhandled_exception",
        path=request.url.path,
        method=request.method,
        error=str(exc),
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": "An unexpected error occurred"
        }
    )


# WebSocket endpoint for real-time updates
from fastapi import WebSocket, WebSocketDisconnect
from typing import Set

class ConnectionManager:
    """Manage WebSocket connections"""
    
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
    
    async def connect(self, websocket: WebSocket):
        """Accept new connection"""
        await websocket.accept()
        self.active_connections.add(websocket)
    
    def disconnect(self, websocket: WebSocket):
        """Remove connection"""
        self.active_connections.discard(websocket)
    
    async def broadcast(self, message: dict):
        """Broadcast to all connections"""
        disconnected = set()
        
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                disconnected.add(connection)
        
        # Remove disconnected clients
        self.active_connections -= disconnected


manager = ConnectionManager()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)
    
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# Startup tasks are now handled in the lifespan context manager


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_config={
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "default": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": "INFO",
                "handlers": ["default"],
            },
        }
    )
