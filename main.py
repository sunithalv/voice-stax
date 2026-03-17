"""
Main entry point for the application.

This module initializes and runs a FastAPI web server that provides a voice-enabled
chatbot interface. It serves an interactive HTML chatbot UI and manages WebSocket
connections for real-time voice conversation capabilities.

The application uses uvicorn as the ASGI server and runs on http://0.0.0.0:8000
with the chatbot interface accessible at the root endpoint.
"""
from pathlib import Path
from fastapi.responses import FileResponse
import uvicorn

from voicestax import create_voice_app,VoiceSettings
from voicestax.utils.logger import setup_logging, logger

def create_app():
    logger.info("Initializing VoiceStax application...")
    settings = VoiceSettings(
        llm_system_prompt=(
            "You are a customer support agent for VoiceStax. "
        ),

        first_speaker="assistant",
        initial_message="Hi! Welcome to VoiceStax support. How can I help?",
    )
    
    logger.debug("VoiceSettings created: first_speaker=%s", settings.first_speaker)
    app = create_voice_app(settings=settings)
    logger.info("VoiceApp created successfully")

    # Serve chatbot HTML at root
    base_dir = Path(__file__).parent
    html_path = base_dir / "examples" / "html" / "chatbot.html"
    
    if not html_path.exists():
        logger.warning("chatbot.html not found at: %s", html_path)
    else:
        logger.info("chatbot.html found at: %s", html_path)
        
    @app.get("/")
    async def serve_html():
        if html_path.exists():
            logger.debug("Serving chatbot.html from: %s", html_path)
            return FileResponse(html_path)
        logger.error("chatbot.html missing at runtime: %s", html_path)
        return {"error": "chatbot.html not found", "path": str(html_path)}

    return app

if __name__ == "__main__":
    # ── Initialize logging before anything else ──────────────────────────────
    setup_logging(level="INFO")          # change to "DEBUG" for verbose output

    app = create_app()

    logger.info("Starting uvicorn server on http://0.0.0.0:8000")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        reload=False
    )
    logger.info("Server stopped")

