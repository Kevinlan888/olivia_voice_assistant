"""
Sentence splitter for streaming LLM output → progressive TTS.

Accumulates tokens and emits complete sentences for TTS synthesis,
supporting both Chinese and English punctuation.
"""

from __future__ import annotations

import re

# Sentence-ending punctuation
_ZH_TERMINATORS = set("。！？；…")
_EN_TERMINATORS = set(".!?;")
# Chinese comma — used as fallback split point for long sentences
_ZH_COMMA = "，"
_EN_COMMA = ","

# When a sentence exceeds this length without a terminator, split at comma
_LONG_SENTENCE_CHARS = 40
# Minimum sentence length before we allow splitting
_MIN_SENTENCE_CHARS = 6


class SentenceSplitter:
    """Accumulates streaming tokens and yields complete sentences.

    Usage::

        splitter = SentenceSplitter()
        for token in llm_tokens:
            for sentence in splitter.feed(token):
                await tts.synthesize_stream(sentence)
        # Flush remaining text
        for sentence in splitter.flush():
            await tts.synthesize_stream(sentence)
    """

    def __init__(
        self,
        min_chars: int = _MIN_SENTENCE_CHARS,
        long_chars: int = _LONG_SENTENCE_CHARS,
    ):
        self._buffer = ""
        self._min_chars = min_chars
        self._long_chars = long_chars

    def feed(self, token: str) -> list[str]:
        """Feed a token; return zero or more complete sentences."""
        self._buffer += token
        return self._try_split()

    def flush(self) -> list[str]:
        """Flush any remaining text as a final sentence."""
        text = self._buffer.strip()
        self._buffer = ""
        if text:
            return [text]
        return []

    def _try_split(self) -> list[str]:
        sentences: list[str] = []
        while True:
            idx = self._find_split_point()
            if idx < 0:
                break
            sentence = self._buffer[: idx + 1].strip()
            self._buffer = self._buffer[idx + 1 :]
            if sentence:
                sentences.append(sentence)
        return sentences

    def _find_split_point(self) -> int:
        """Find the best character index to split at, or -1."""
        buf = self._buffer

        # Look for sentence-ending punctuation
        for i, ch in enumerate(buf):
            if ch in _ZH_TERMINATORS or ch in _EN_TERMINATORS:
                if i + 1 >= self._min_chars:
                    return i
                # Even if short, if the next char starts a new sentence, split
                if i + 1 < len(buf) and not buf[i + 1].isspace():
                    return i

        # For long buffers, split at the last comma
        if len(buf) >= self._long_chars:
            # Find last comma
            last_zh = buf.rfind(_ZH_COMMA)
            last_en = buf.rfind(_EN_COMMA)
            last_comma = max(last_zh, last_en)
            if last_comma >= self._min_chars:
                return last_comma

        return -1
