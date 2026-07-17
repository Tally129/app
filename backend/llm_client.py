"""
LLM client with vendor auto-fallback.

Priority:
  1. `ANTHROPIC_API_KEY` set  → direct Anthropic SDK  (BAA-covered inference)
  2. `EMERGENT_LLM_KEY` set   → emergentintegrations proxy (dev / preview only)
  3. Neither set              → raise HTTPException(503)

Every AI endpoint (SOAP drafting, form/protocol transcription, supplement extract,
document classification) should call `complete_text()` from this module instead of
importing SDKs directly. That way "signing the Anthropic BAA" is one env-var flip.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

logger = logging.getLogger("nms.llm")

# --- Constants -------------------------------------------------------------- #
DEFAULT_ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
DEFAULT_EMERGENT_MODEL = "claude-sonnet-4-5-20250929"


def provider() -> str:
    """Which provider will `complete_text()` actually call? Handy for /api/health."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic_direct"
    if os.environ.get("EMERGENT_LLM_KEY"):
        return "emergent_proxy"
    return "none"


async def complete_text(
    system_prompt: str,
    user_message: str,
    *,
    session_id: str = "nms",
    max_tokens: int = 4096,
    temperature: float = 0.2,
) -> str:
    """Return the full assistant text for a single-turn prompt.

    Routes to Anthropic direct if `ANTHROPIC_API_KEY` is set; otherwise falls back
    to Emergent's proxy. Raises `RuntimeError("no_llm_key")` if neither is set.
    """
    anth_key = os.environ.get("ANTHROPIC_API_KEY")
    if anth_key:
        return await _complete_anthropic_direct(
            anth_key, system_prompt, user_message,
            max_tokens=max_tokens, temperature=temperature,
        )

    em_key = os.environ.get("EMERGENT_LLM_KEY")
    if em_key:
        return await _complete_emergent(
            em_key, system_prompt, user_message,
            session_id=session_id, max_tokens=max_tokens, temperature=temperature,
        )

    raise RuntimeError("no_llm_key")


# --- Anthropic direct ------------------------------------------------------- #
async def _complete_anthropic_direct(
    api_key: str, system_prompt: str, user_message: str,
    *, max_tokens: int, temperature: float,
) -> str:
    try:
        from anthropic import AsyncAnthropic  # official SDK
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(f"anthropic SDK missing: {e}")
    client = AsyncAnthropic(api_key=api_key, timeout=90.0)
    resp = await client.messages.create(
        model=DEFAULT_ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    # response.content is a list of content blocks; take the concatenated text
    parts: List[str] = []
    for block in getattr(resp, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    out = "".join(parts).strip()
    logger.info("LLM anthropic_direct model=%s tokens_out=%s", DEFAULT_ANTHROPIC_MODEL, len(out))
    return out


# --- Emergent proxy fallback ----------------------------------------------- #
async def _complete_emergent(
    api_key: str, system_prompt: str, user_message: str,
    *, session_id: str, max_tokens: int, temperature: float,
) -> str:
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except ImportError as e:
        raise RuntimeError(f"emergentintegrations missing: {e}")
    chat = (
        LlmChat(api_key=api_key, session_id=session_id, system_message=system_prompt)
        .with_model("anthropic", DEFAULT_EMERGENT_MODEL)
    )
    resp = await chat.send_message(UserMessage(text=user_message))
    text = getattr(resp, "text", None) or str(resp)
    logger.info("LLM emergent_proxy tokens_out=%s", len(text))
    return text.strip()
