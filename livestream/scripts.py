from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import random

@dataclass
class Script:
    id: str
    text: str
    enabled: bool = True
    mode: str = "direct"
    audiotype: int | None = None


class ScriptStore:
    def __init__(self, scripts: list[Script], shuffle: bool = False):
        self.scripts = [script for script in scripts if script.enabled and script.text.strip()]
        self.shuffle = shuffle
        self._index = 0

    @classmethod
    def from_file(cls, path: str, shuffle: bool = False) -> "ScriptStore":
        import yaml

        source = Path(path)
        if not source.exists():
            return cls([], shuffle=shuffle)
        with source.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or []
        rows = payload.get("scripts", []) if isinstance(payload, dict) else payload
        scripts = []
        for index, row in enumerate(rows if isinstance(rows, list) else []):
            if isinstance(row, str):
                scripts.append(Script(id=f"script-{index + 1}", text=row))
            elif isinstance(row, dict):
                scripts.append(
                    Script(
                        id=str(row.get("id", f"script-{index + 1}")),
                        text=str(row.get("text", "")),
                        enabled=bool(row.get("enabled", True)),
                        mode=str(row.get("mode", "direct")),
                        audiotype=(int(row["audiotype"]) if row.get("audiotype") is not None else None),
                    )
                )
        return cls(scripts, shuffle=shuffle)

    def next(self) -> Script | None:
        if not self.scripts:
            return None
        if self.shuffle:
            return random.choice(self.scripts)
        script = self.scripts[self._index % len(self.scripts)]
        self._index += 1
        return script

    def get(self, script_id: str) -> Script | None:
        return next((script for script in self.scripts if script.id == script_id), None)

    def list(self) -> list[dict[str, object]]:
        return [
            {
                "id": script.id,
                "text": script.text,
                "mode": script.mode,
                "audiotype": script.audiotype,
            }
            for script in self.scripts
        ]
