"""
FastAPI Application Factory for VoiceStax Voice Agent API

This module creates and configures the FastAPI application instance for the VoiceStax voice agent API.
It handles the initialization of the FastAPI app, integration of WebSocket routes, and provides
a global app instance ready for deployment with Uvicorn.

The module provides:
- create_voice_app(): Factory function that sets up and returns a configured FastAPI application
- app: Global FastAPI application instance for Uvicorn server
"""
from fastapi import FastAPI 
from voicestax.config.settings import VoiceSettings, get_settings
from typing import Optional

def create_voice_app(settings: Optional[VoiceSettings] = None) -> FastAPI:
    """
    Create FastAPI app for VoiceStax voice agent.
    Pass a VoiceSettings instance to override any defaults.
    Falls back to .env if nothing is passed.
    """
    
    resolved_settings = get_settings(override=settings)
    app = FastAPI(title="VoiceStax Voice Agent")
    
    # Import here to avoid circular imports and pass settings in
    from voicestax.api.websocket_routes import create_router
    app.include_router(create_router(resolved_settings))
    return app

