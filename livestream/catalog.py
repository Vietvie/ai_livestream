from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import re
import unicodedata

def _normalized(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    return "".join(char for char in value if not unicodedata.combining(char))


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[\w]+", _normalized(value), flags=re.UNICODE))


@dataclass
class CatalogMatch:
    score: float
    product: dict[str, Any]


class ProductCatalog:
    def __init__(self, products: list[dict[str, Any]], top_k: int = 5):
        self.products = products
        self.top_k = max(1, top_k)
        self._documents = [self._document(product) for product in products]
        self._token_sets = [_tokens(document) for document in self._documents]

    @classmethod
    def from_file(cls, path: str, top_k: int = 5) -> "ProductCatalog":
        source = Path(path)
        if not source.exists():
            return cls([], top_k=top_k)
        with source.open("r", encoding="utf-8") as handle:
            if source.suffix.lower() in {".yaml", ".yml"}:
                import yaml

                payload = yaml.safe_load(handle) or []
            else:
                payload = json.load(handle)
        products = payload.get("products", []) if isinstance(payload, dict) else payload
        if not isinstance(products, list):
            raise ValueError("Product catalog must contain a list of products")
        return cls([item for item in products if isinstance(item, dict)], top_k=top_k)

    @staticmethod
    def _document(product: dict[str, Any]) -> str:
        return json.dumps(product, ensure_ascii=False, sort_keys=True)

    def search(self, query: str) -> list[CatalogMatch]:
        if not self.products:
            return []
        query_text = _normalized(query)
        query_tokens = _tokens(query)
        matches: list[CatalogMatch] = []
        for product, document, tokens in zip(self.products, self._documents, self._token_sets):
            normalized_document = _normalized(document)
            overlap = len(query_tokens & tokens)
            score = float(overlap)
            name = _normalized(str(product.get("name", "")))
            sku = _normalized(str(product.get("sku", product.get("id", ""))))
            if name and name in query_text:
                score += 8.0
            if sku and sku in query_text:
                score += 10.0
            if query_text and query_text in normalized_document:
                score += 3.0
            matches.append(CatalogMatch(score=score, product=product))
        matches.sort(key=lambda item: item.score, reverse=True)
        positive = [item for item in matches if item.score > 0]
        return (positive or matches[: min(2, len(matches))])[: self.top_k]

    def context_for(self, query: str, max_chars: int = 8000) -> str:
        selected = [match.product for match in self.search(query)]
        context = json.dumps(selected, ensure_ascii=False, indent=2)
        return context[:max_chars]

    def public_products(self) -> list[dict[str, Any]]:
        return self.products
