from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse

from voicestax import create_voice_app, VoiceSettings


settings = VoiceSettings(
    llm_system_prompt="You are a voice assistant named {settings.app_name}.",
    first_speaker="assistant",
    initial_message=(
        "Hello! I am {settings.app_name} your AI Assistant. "
        "How can I help?"
    ),
)


def create_app():
    app = create_voice_app(settings=settings)

    base_dir = Path(__file__).parent
    html_path = base_dir / "examples" / "html" / "chatbot.html"

    @app.get("/")
    async def serve_html():
        return FileResponse(html_path)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
    )