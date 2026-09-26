from __future__ import annotations

from collections.abc import Callable
from typing import Any
import re

from livestream.catalog import ProductCatalog


def _format_price(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{int(value):,}".replace(",", ".") + " đồng"
    return str(value or "chưa được cấu hình")


class DummyProductAgent:
    """Deterministic local dialogue for validating TTS/lip-sync without an API key."""

    def __init__(self, catalog: ProductCatalog):
        self.catalog = catalog

    def clear_history(self, session_id: str) -> None:
        return None

    def reply(self, question: str, session_id: str, on_sentence: Callable[[str], None]) -> str:
        question = question.strip()
        matches = self.catalog.search(question)
        product = matches[0].product if matches else None
        normalized = question.lower()

        if product is None:
            answer = (
                "Xin chào, đây là nội dung thử nghiệm không dùng OpenAI. "
                "Hệ thống chuyển văn bản thành giọng nói và đồng bộ khẩu hình đang hoạt động."
            )
        elif any(word in normalized for word in ("giá", "bao nhiêu", "khuyến mãi")):
            answer = (
                f"{product.get('name', 'Sản phẩm')} hiện có giá mẫu là "
                f"{_format_price(product.get('price_vnd'))}. "
                f"Khuyến mãi: {product.get('promotion', 'chưa cấu hình')}."
            )
        else:
            features = product.get("features") or []
            feature_text = ", ".join(str(item) for item in features[:3])
            answer = (
                f"Đây là phần giới thiệu thử nghiệm cho {product.get('name', 'sản phẩm')}. "
                f"{product.get('description', '')}"
            )
            if feature_text:
                answer += f" Các điểm nổi bật gồm {feature_text}."

        # Keep the same streaming-to-TTS behavior as the OpenAI agent.
        phrases = [item.strip() for item in re.findall(r"[^.!?。！？]+[.!?。！？]?", answer)]
        for phrase in phrases:
            if phrase:
                on_sentence(phrase)
        return answer
