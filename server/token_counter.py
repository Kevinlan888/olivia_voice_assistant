"""Lightweight token-counting utilities backed by tiktoken."""

from __future__ import annotations

import tiktoken

# cl100k_base covers GPT-4o / GPT-4 / GPT-3.5-turbo and is a reasonable
# approximation for other chat models (e.g. Qwen) as well.
_enc = tiktoken.get_encoding("cl100k_base")

# Per-message overhead in the OpenAI chat format:
#   every message: <|start|>{role/name}\n … content … <|end|>\n  →  ~4 tokens
_MSG_OVERHEAD = 4
# Every reply is primed with <|start|>assistant<|message|> → 3 tokens
_REPLY_PRIME = 3


def count_tokens(text: str) -> int:
    """Return the token count for a plain string."""
    return len(_enc.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """Return the total token count for a list of OpenAI-format messages."""
    total = 0
    for msg in messages:
        total += _MSG_OVERHEAD
        for value in msg.values():
            if isinstance(value, str):
                total += count_tokens(value)
    total += _REPLY_PRIME
    return total
