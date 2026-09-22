"""
FastAPI application factory for the VoiceStax voice agent API.

This module creates and configures a FastAPI application instance for
the VoiceStax voice agent API. It resolves VoiceStax settings, registers
the WebSocket routes, and returns the configured application.

The module provides:
- create_voice_app(): Factory function that creates a configured
  FastAPI application for deployment with an ASGI server such as Uvicorn.
"""
from fastapi import FastAPI
from typing import Optional

from voicestax.config.settings import VoiceSettings, get_settings
from voicestax import __version__
from voicestax.utils.logger import logger


def create_voice_app(
    settings: Optional[VoiceSettings] = None,
    custom_llm_provider=None,
) -> FastAPI:
    """
    Create a configured FastAPI application for VoiceStax.

    If settings are provided, they override the defaults.
    Otherwise, settings are loaded from environment variables/.env.
    """

    resolved_settings = get_settings(override=settings)

    logger.info("Creating VoiceStax FastAPI application")

    app = FastAPI(
        title="VoiceStax Voice Agent",
        version=__version__,
        description=(
            "Real-time voice agent framework with pluggable "
            "STT, LLM, and TTS providers."
        ),
    )

    from voicestax.api.websocket_routes import create_router

    app.include_router(
        create_router(
            resolved_settings,
            custom_llm_provider=custom_llm_provider,
        )
    )

    logger.info("WebSocket router registered")

    return app