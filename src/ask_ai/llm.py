"""Clients for the LLMs that can be mentioned in a post."""

from functools import cache

import anthropic
from google import genai
from google.genai import types

from ask_ai.config import settings

SYSTEM_PROMPT = (
    "You were mentioned in a post on a discussion forum. Your reply will be "
    "published as a comment on that post, so answer the post directly."
)


class LLMError(Exception):
    """The LLM call succeeded but produced no usable answer."""


# Clients are created lazily so the app can start without API keys configured.


@cache
def _anthropic_client() -> anthropic.Anthropic:
    key = settings.anthropic_api_key
    return anthropic.Anthropic(api_key=key.get_secret_value() if key else None)


@cache
def _gemini_client() -> genai.Client:
    key = settings.gemini_api_key
    return genai.Client(api_key=key.get_secret_value() if key else None)


def ask_claude(query: str) -> str:
    response = _anthropic_client().beta.messages.create(
        model=settings.claude_model,
        max_tokens=16000,
        output_config={"effort": "medium"},
        # If a safety classifier declines, retry on a suitable fallback model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
    )
    if response.stop_reason == "refusal":
        raise LLMError("Claude declined to answer")
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise LLMError("Claude returned an empty response")
    return text


def ask_gemini(query: str) -> str:
    response = _gemini_client().models.generate_content(
        model=settings.gemini_model,
        contents=query,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    text = response.text
    if not text or not text.strip():
        raise LLMError("Gemini returned an empty response")
    return text
