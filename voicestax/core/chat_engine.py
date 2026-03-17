# VoiceStax/core/chat_engine.py

"""
ChatEngine: Handles conversation context and streaming LLM responses with interrupt support.
"""

from typing import List, Dict, Optional
import json
from voicestax.utils.exceptions import LLMError
from voicestax.utils.logger import logger

class ChatEngine:
    """Manages conversation history and interacts with LLM client."""

    def __init__(self, llm_client, max_history: int = 12):
        self.llm_client = llm_client
        self.conversation_history: List[Dict] = []
        self.max_history = max_history

    async def get_intent_and_response(
        self,
        user_text: str,
        session
    ) -> Dict:
        
        """
        Single LLM call to generate both intent and response.
        Supports interruption via session.cancel_event.
        """

        # -------- Reset cancel event for new response --------
        session.cancel_event.clear()

        # -------- Update history --------
        self.conversation_history.append({"role": "user", "content": user_text})
        self.conversation_history = self.conversation_history[-self.max_history:]

        # -------- System prompt --------
        system = session.system_prompt

        messages = [{"role": "system", "content": system}] + self.conversation_history

        full_response = ""

        try:
            stream = self.llm_client.stream_chat(messages=messages)

            for chunk in stream:

                # ⚡ Stop streaming if barge-in occurred
                if session.cancel_event.is_set():
                    break

                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_response += delta.content

        except Exception as e:
            logger.error(f"[LLM ERROR]: {e}")
            raise LLMError(f"LLM request failed: {e}") from e

        # -------- Parse JSON safely --------
        try:
            parsed = json.loads(full_response)
        except Exception:
            parsed = {"intent": "continue", "response": full_response}

        # -------- Save assistant response --------
        self.conversation_history.append({"role": "assistant", "content": parsed["response"]})

        return parsed
