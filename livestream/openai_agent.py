from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from threading import Lock
from typing import Any
import os
import re

from livestream.catalog import ProductCatalog
from livestream.settings import OpenAISettings


class SentenceBuffer:
    """Turn token deltas into TTS-sized phrases without waiting for full output."""

    def __init__(self, emit: Callable[[str], None], min_chars: int = 10, max_chars: int = 120):
        self.emit = emit
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.buffer = ""

    def feed(self, delta: str) -> None:
        self.buffer += delta
        while self.buffer:
            match = re.search(r"[,.!?;:\n，。！？；：]", self.buffer)
            if match and match.end() >= self.min_chars:
                self._flush(match.end())
            elif len(self.buffer) >= self.max_chars:
                split = self.buffer.rfind(" ", 0, self.max_chars)
                self._flush(split if split >= self.min_chars else self.max_chars)
            else:
                break

    def finish(self) -> None:
        if self.buffer.strip():
            self.emit(self.buffer.strip())
        self.buffer = ""

    def _flush(self, end: int) -> None:
        phrase = self.buffer[:end].strip()
        self.buffer = self.buffer[end:]
        if phrase:
            self.emit(phrase)


class OpenAIProductAgent:
    def __init__(self, settings: OpenAISettings, catalog: ProductCatalog):
        self.settings = settings
        self.catalog = catalog
        self._client = None
        self._history: dict[str, deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=max(2, settings.max_history_turns * 2))
        )
        self._lock = Lock()

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            api_key = os.getenv(self.settings.api_key_env, "").strip()
            if not api_key:
                raise RuntimeError(
                    f"Missing OpenAI API key. Set environment variable {self.settings.api_key_env}."
                )
            kwargs: dict[str, Any] = {"api_key": api_key}
            if self.settings.base_url:
                kwargs["base_url"] = self.settings.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def clear_history(self, session_id: str) -> None:
        with self._lock:
            self._history.pop(session_id, None)

    def reply(self, question: str, session_id: str, on_sentence: Callable[[str], None]) -> str:
        question = question.strip()
        if not question:
            return ""
        product_context = self.catalog.context_for(
            question, max_chars=self.settings.max_context_chars
        )
        with self._lock:
            history = list(self._history[session_id])

        inputs: list[dict[str, str]] = history + [
            {
                "role": "user",
                "content": (
                    f"DỮ LIỆU SẢN PHẨM LIÊN QUAN:\n{product_context or 'Không có dữ liệu.'}\n\n"
                    f"CÂU HỎI KHÁCH HÀNG:\n{question}"
                ),
            }
        ]
        stream = self._get_client().responses.create(
            model=self.settings.model,
            instructions=self.settings.system_prompt,
            input=inputs,
            stream=True,
        )

        pieces: list[str] = []
        buffer = SentenceBuffer(on_sentence)
        for event in stream:
            if getattr(event, "type", "") == "response.output_text.delta":
                delta = getattr(event, "delta", "") or ""
                pieces.append(delta)
                buffer.feed(delta)
        buffer.finish()
        answer = "".join(pieces).strip()
        if answer:
            with self._lock:
                self._history[session_id].append({"role": "user", "content": question})
                self._history[session_id].append({"role": "assistant", "content": answer})
        return answer
