import json
import re
from pydantic import BaseModel, field_validator
from typing import Literal

class LLMResponse(BaseModel):
    intent: Literal["continue", "end_session"] = "continue"
    response: str

    @field_validator("response")
    @classmethod
    def strip_embedded_json(cls, v: str) -> str:
        # Remove any trailing JSON blob the model accidentally appended
        cleaned = re.sub(r'\{.*"intent".*\}', '', v, flags=re.DOTALL).strip()
        return cleaned or v