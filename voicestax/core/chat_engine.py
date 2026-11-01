"""
ChatEngine manages conversation history, builds LLM message payloads,
streams responses, and stops early when a session interrupt is requested.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from voicestax.schemas.llm_schemas import LLMResponse
from voicestax.utils.exceptions import LLMError
from voicestax.utils.logger import logger


class ChatEngine:
    """Manage conversation history and interact with an LLM provider."""

    UNPARSEABLE_RESPONSE = (
        "Sorry, I didn't catch that properly. Could you say it again?"
    )

    # Keys under which models sometimes nest the real payload,
    # e.g. tool-call style {"name": "assistant", "arguments": {...}}.
    _WRAPPER_KEYS = ("arguments", "parameters", "args", "input", "output", "content")

    @classmethod
    def _find_response_payload(cls, value: Any, depth: int = 0) -> dict | None:
        """Return the first nested dict that contains a "response" field."""

        if depth > 4:
            return None

        # Tool-call arguments are often a JSON-encoded string.
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                return None

        if not isinstance(value, dict):
            return None

        if isinstance(value.get("response"), str):
            return value

        for key in cls._WRAPPER_KEYS:
            if key in value:
                found = cls._find_response_payload(value[key], depth + 1)
                if found is not None:
                    return found

        return None

    @classmethod
    def _recover_structured_response(cls, raw: str) -> LLMResponse | None:
        """Best-effort extraction of an LLMResponse from malformed model output."""

        start = raw.find("{")
        end = raw.rfind("}")

        if start == -1 or end <= start:
            return None

        payload = cls._find_response_payload(raw[start : end + 1])

        if payload is None or not payload["response"].strip():
            return None

        intent = payload.get("intent")
        if intent not in LLMResponse.model_fields["intent"].annotation.__args__:
            intent = "conversation"

        return LLMResponse(intent=intent, response=payload["response"].strip())
    
    
    @classmethod
    def _recover_labeled_response(cls, raw: str) -> LLMResponse | None:
        """Recover responses formatted as 'Intent: ...\\nResponse: ...'."""

        import re

        match = re.search(
            r"^\s*Intent\s*:\s*(conversation|clarification|"
            r"end_conversation|human_handoff)\s*"
            r"\n\s*Response\s*:\s*(.*?)\s*$",
            raw,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if not match:
            return None

        intent = match.group(1).lower()
        response = match.group(2).strip()

        # Remove a matching pair of surrounding quotes only.
        if (
            len(response) >= 2
            and response[0] == response[-1]
            and response[0] in {'"', "'"}
        ):
            response = response[1:-1].strip()

        if not response:
            return None

        return LLMResponse(intent=intent, response=response)


    def __init__(
        self,
        llm_client,
        max_history: int = 12,
    ):
        # If max_history is too small, the conversation may be cut off too early
        # So 6 user assistant message pairs are kept
        if max_history < 2:
            raise ValueError(
                "max_history must be at least 2"
            )

        self.llm_client = llm_client
        self.max_history = max_history

    def _trim_history(
        self,
        history: list[dict[str, Any]],
    ) -> None:
        """
        Keep the most recent complete conversation turns.

        A turn normally consists of one user message and one assistant
        message. The system message is not stored in conversation history.
        """

        if len(history) <= self.max_history:
            return

        trimmed = history[-self.max_history :]

        # Avoid starting with an orphan assistant message.
        if trimmed and trimmed[0].get("role") == "assistant":
            trimmed = trimmed[1:]

        history[:] = trimmed

    def _build_messages(
        self,
        session,
    ) -> list[dict[str, str]]:
        """Build the system message plus conversation history."""

        system_prompt = session.settings.llm_system_prompt
        
        logger.info(
            "%s [LLM] System prompt contains json=%s",
            session.log_prefix(),
            "json" in system_prompt.lower(),
        )

        return [
            {
                "role": "system",
                "content": system_prompt,
            },
            *session.conversation_history,
        ]

    async def _stream_response(
        self,
        messages: list[dict[str, str]],
        session,
    ) -> str:
        """
        Execute the synchronous provider stream in a worker thread.

        This prevents the synchronous SDK from blocking the
        asyncio event loop.
        """

        def consume_stream() -> str:
            full_response = ""
            
            # Call the provider's stream_chat method to get a streaming response.
            stream = self.llm_client.stream_chat(
                messages=messages
            )
            
            # Iterate over the streaming chunks and build the full response.
            for chunk in stream:
                # Check if the session has been interrupted (e.g., by barge-in).
                if session.cancel_event.is_set():
                    logger.info(
                        "%s [LLM] Streaming interrupted by barge-in",
                        session.log_prefix(),
                    )
                    break

                try:
                    choices = chunk.choices
                    
                    if not choices:
                        continue

                    delta = choices[0].delta

                    if delta and delta.content:
                        full_response += delta.content

                except (AttributeError, IndexError, TypeError) as exc:
                    logger.warning(
                        "%s [LLM] Ignoring malformed stream chunk: %s",
                        session.log_prefix(),
                        exc,
                    )

            return full_response
        
        system_prompt = next(
            (
                message["content"]
                for message in messages
                if message.get("role") == "system"
            ),
            "",
        )

        logger.debug(
            "%s [LLM] Request check: system_prompt_has_json=%s, "
            "system_prompt_start=%r",
            session.log_prefix(),
            "json" in system_prompt.lower(),
            system_prompt[:250],
        )

        return await asyncio.to_thread(consume_stream)

    async def get_intent_and_response(
        self,
        user_text: str,
        session,
    ) -> LLMResponse:
        """
        Generate an intent and response using one LLM call.

        The provider must implement:

            stream_chat(messages=messages)

        The provider should return an iterable of streaming chunks.
        """

        if not user_text or not user_text.strip():
            raise LLMError(
                "User text cannot be empty"
            )

        history = session.conversation_history

        user_message = {
            "role": "user",
            "content": user_text.strip(),
        }
        
        # Add user message to session history before sending to LLM
        history.append(user_message)
        self._trim_history(history)

       # Build the full message payload including system prompt and conversation history
        messages = self._build_messages(session)

        full_response = ""
        interrupted = False

        # Record the time when the LLM request starts for latency metrics
        session.llm_start_time = time.perf_counter()

        logger.info(
            "%s [LLM] Sending request: messages=%d",
            session.log_prefix(),
            len(messages),
        )

        try:
            # Stream the response from the LLM provider in a separate thread to avoid blocking the event loop.
            full_response = await self._stream_response(
                messages=messages,
                session=session,
            )
            
            # Check if the session was interrupted during streaming (e.g., by barge-in).
            interrupted = session.cancel_event.is_set()

        
        except Exception as exc:
            error_body = getattr(exc, "body", None)

            # Some LLM JSON-mode failures include the generated plain text
            # in the error body. Recover it when it is available.
            failed_generation = None

            if isinstance(error_body, dict):
                failed_generation = error_body.get(
                    "failed_generation"
                )

                # Some SDK errors wrap the API body in an "error" object.
                if isinstance(error_body.get("error"), dict):
                    failed_generation = (
                        failed_generation
                        or error_body["error"].get("failed_generation")
                    )

            if (
                isinstance(failed_generation, str)
                and failed_generation.strip()
                and not session.cancel_event.is_set()
            ):
                recovered_text = failed_generation.strip()

                logger.warning(
                    "%s [LLM] Recovering plain-text generation "
                    "after provider JSON validation failure",
                    session.log_prefix(),
                )

                full_response = recovered_text
                interrupted = False

            else:
                # Remove the user message because the LLM request failed.
                if history and history[-1] is user_message:
                    history.pop()

                if error_body:
                    logger.error(
                        "%s [LLM] Error details: %s",
                        session.log_prefix(),
                        error_body,
                    )

                logger.error(
                    "%s [LLM ERROR] Request failed: %s: %s",
                    session.log_prefix(),
                    type(exc).__name__,
                    exc,
                )

                raise LLMError(
                    f"LLM request failed: {exc}"
                ) from exc

        finally:
            # Record the time when the LLM request ends for latency metrics
            session.llm_end_time = time.perf_counter()

            # Calculate the latency in milliseconds and record it in the session's latency metrics.
            llm_latency = (
                session.llm_end_time
                - session.llm_start_time
            ) * 1000

            session.record_latency(
                "llm_latency",
                round(llm_latency, 2),
            )

            logger.info(
                "%s [LLM] Stream finished: chars=%d latency=%.2f ms",
                session.log_prefix(),
                len(full_response),
                llm_latency,
            )
        
        # Handle interrupted or empty responses, and parse the structured response if available.
        if interrupted:
            logger.info(
                "%s [LLM] Discarding interrupted partial response",
                session.log_prefix(),
            )

            # Remove the user message because no valid assistant turn
            # was completed.
            if history and history[-1] is user_message:
                history.pop()

            raise LLMError(
                "LLM response interrupted by barge-in"
            )
        
        # Handle empty responses by removing the user message and raising an error.
        if not full_response.strip():
            if history and history[-1] is user_message:
                history.pop()

            logger.error(
                "%s [LLM ERROR] Empty response received",
                session.log_prefix(),
            )

            raise LLMError(
                "LLM returned an empty response"
            )

        try:
            # Parse the full response as JSON to extract the intent and response fields.
            parsed = LLMResponse.model_validate_json(
                full_response
            )

            logger.info(
                "%s [LLM] Structured response parsed successfully: "
                "intent=%s",
                session.log_prefix(),
                parsed.intent,
            )

        except Exception:
            logger.warning(
                "%s [LLM] Structured response parsing failed. "
                "Raw response starts with: %r",
                session.log_prefix(),
                full_response[:300],
            )

            # Recover the intent/response object when the model wrapped it,
            # e.g. a tool-call shape {"name": ..., "arguments": {...}} or
            # JSON surrounded by markdown fences or extra text.
            
            parsed = self._recover_structured_response(full_response)

            if parsed is None:
                parsed = self._recover_labeled_response(full_response)

            if parsed is not None:
                logger.info(
                    "%s [LLM] Recovered structured response "
                    "from malformed output: intent=%s",
                    session.log_prefix(),
                    parsed.intent,
                )
            elif full_response.lstrip().startswith(("{", "[")):
                # Never speak raw JSON to the user.
                parsed = LLMResponse(
                    intent="conversation",
                    response=self.UNPARSEABLE_RESPONSE,
                )
            else:
                # Plain-text reply without a recognized wrapper.
                parsed = LLMResponse(
                    intent="conversation",
                    response=full_response.strip(),
                )

        # Append the assistant's response to the session conversation history 
        history.append(
            {
                "role": "assistant",
                "content": parsed.response,
            }
        )

        self._trim_history(history)

        logger.info(
            "%s [LLM] Response ready: intent=%s chars=%d",
            session.log_prefix(),
            parsed.intent,
            len(parsed.response),
        )

        return parsed