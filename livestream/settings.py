from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os

@dataclass
class OpenAISettings:
    provider: str = "dummy"
    model: str = "gpt-4.1-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url: str | None = None
    system_prompt: str = (
        "Bạn là tư vấn viên livestream thân thiện, trả lời bằng tiếng Việt tự nhiên, "
        "ngắn gọn và dễ đọc thành lời. Chỉ dùng dữ liệu sản phẩm được cung cấp; "
        "nếu thiếu thông tin thì nói rõ và đề nghị nhân viên xác nhận. Không tự tạo "
        "giá, khuyến mãi, tồn kho, công dụng y tế hoặc chính sách bảo hành."
    )
    max_history_turns: int = 6
    max_context_chars: int = 8000


@dataclass
class AutomationSettings:
    enabled: bool = True
    default_session_id: str = "0"
    idle_seconds: float = 25.0
    poll_seconds: float = 0.5
    interrupt_idle_on_comment: bool = True
    script_file: str = "data/scripts.yaml"
    shuffle: bool = False


@dataclass
class CatalogSettings:
    file: str = "data/products.json"
    top_k: int = 5


@dataclass
class ApiSettings:
    token_env: str = "LIVESTREAM_API_TOKEN"
    allow_unauthenticated: bool = False
    protected_paths: list[str] = field(
        default_factory=lambda: [
            "/human",
            "/humanaudio",
            "/record",
            "/interrupt_talk",
            "/set_audiotype",
            "/api/admin",
            "/api/avatar",
            "/api/livestream",
            "/api/v1",
        ]
    )


@dataclass
class LivestreamSettings:
    openai: OpenAISettings = field(default_factory=OpenAISettings)
    automation: AutomationSettings = field(default_factory=AutomationSettings)
    catalog: CatalogSettings = field(default_factory=CatalogSettings)
    api: ApiSettings = field(default_factory=ApiSettings)

    @property
    def api_token(self) -> str:
        return os.getenv(self.api.token_env, "").strip()


def _section(cls, data: dict[str, Any], name: str):
    raw = data.get(name) or {}
    allowed = cls.__dataclass_fields__.keys()
    return cls(**{key: value for key, value in raw.items() if key in allowed})


def load_settings(path: str | os.PathLike[str]) -> LivestreamSettings:
    import yaml

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Livestream config not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("Livestream config must be a YAML object")
    return LivestreamSettings(
        openai=_section(OpenAISettings, data, "openai"),
        automation=_section(AutomationSettings, data, "automation"),
        catalog=_section(CatalogSettings, data, "catalog"),
        api=_section(ApiSettings, data, "api"),
    )
