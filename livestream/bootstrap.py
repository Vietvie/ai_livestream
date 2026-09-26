from __future__ import annotations

from livestream.catalog import ProductCatalog
from livestream.dummy_agent import DummyProductAgent
from livestream.openai_agent import OpenAIProductAgent
from livestream.orchestrator import LivestreamOrchestrator
from livestream.scripts import ScriptStore
from livestream.settings import load_settings


def create_orchestrator(config_path: str, session_manager) -> LivestreamOrchestrator:
    settings = load_settings(config_path)
    catalog = ProductCatalog.from_file(settings.catalog.file, top_k=settings.catalog.top_k)
    scripts = ScriptStore.from_file(
        settings.automation.script_file, shuffle=settings.automation.shuffle
    )
    if settings.openai.provider.lower() == "openai":
        agent = OpenAIProductAgent(settings.openai, catalog)
    else:
        agent = DummyProductAgent(catalog)
    return LivestreamOrchestrator(settings, agent, scripts, session_manager)
