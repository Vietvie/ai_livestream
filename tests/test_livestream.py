from __future__ import annotations

import json
import time
from types import SimpleNamespace

from livestream.catalog import ProductCatalog
from livestream.dummy_agent import DummyProductAgent
from livestream.openai_agent import OpenAIProductAgent, SentenceBuffer
from livestream.orchestrator import LivestreamOrchestrator
from livestream.scripts import Script, ScriptStore
from livestream.settings import AutomationSettings, LivestreamSettings


class FakeAvatar:
    sessionid = "0"

    def __init__(self):
        self.messages = []
        self.interrupted = False

    def put_msg_txt(self, text, metadata=None):
        self.messages.append((text, metadata or {}))

    def flush_talk(self):
        self.interrupted = True

    def is_speaking(self):
        return False


class FakeSessions:
    def __init__(self, avatar):
        self.avatar = avatar

    def get_session(self, session_id):
        return self.avatar if str(session_id) == "0" else None


class FakeAgent:
    def __init__(self):
        self.catalog = ProductCatalog([])

    def reply(self, question, session_id, on_sentence):
        answer = f"Trả lời: {question}"
        on_sentence(answer)
        return answer


def test_catalog_prefers_named_product():
    catalog = ProductCatalog(
        [
            {"sku": "A1", "name": "Máy xay Alpha", "price_vnd": 100},
            {"sku": "B2", "name": "Nồi Beta", "price_vnd": 200},
        ]
    )
    context = json.loads(catalog.context_for("Máy xay Alpha giá bao nhiêu?"))
    assert context[0]["sku"] == "A1"


def test_dummy_agent_needs_no_openai_key():
    catalog = ProductCatalog(
        [{"sku": "A1", "name": "Máy xay Alpha", "price_vnd": 299000, "promotion": "Không"}]
    )
    agent = DummyProductAgent(catalog)
    phrases = []
    answer = agent.reply("Máy xay Alpha giá bao nhiêu?", "0", phrases.append)
    assert "299.000 đồng" in answer
    assert phrases


def test_sentence_buffer_emits_phrases():
    phrases = []
    buffer = SentenceBuffer(phrases.append, min_chars=3)
    buffer.feed("Xin chào, đây là ")
    buffer.feed("livestream.")
    buffer.finish()
    assert "".join(phrases) == "Xin chào,đây là livestream."


def test_openai_agent_streams_responses_api_output():
    class Event:
        def __init__(self, event_type, delta=""):
            self.type = event_type
            self.delta = delta

    class Responses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return [
                Event("response.output_text.delta", "Sản phẩm A "),
                Event("response.output_text.delta", "giá 100 nghìn."),
                Event("response.completed"),
            ]

    responses = Responses()
    settings = LivestreamSettings().openai
    agent = OpenAIProductAgent(
        settings,
        ProductCatalog([{"sku": "A", "name": "Sản phẩm A", "price_vnd": 100000}]),
    )
    agent._client = SimpleNamespace(responses=responses)
    phrases = []
    answer = agent.reply("Sản phẩm A giá bao nhiêu?", "0", phrases.append)
    assert answer == "Sản phẩm A giá 100 nghìn."
    assert responses.kwargs["stream"] is True
    assert responses.kwargs["model"] == settings.model
    assert "price_vnd" in responses.kwargs["input"][-1]["content"]
    assert "".join(phrases) == answer


def test_comment_is_answered_and_duplicate_is_dropped():
    avatar = FakeAvatar()
    settings = LivestreamSettings(
        automation=AutomationSettings(enabled=False, default_session_id="0")
    )
    orchestrator = LivestreamOrchestrator(
        settings, FakeAgent(), ScriptStore([]), FakeSessions(avatar)
    )
    orchestrator.start()
    try:
        assert orchestrator.submit_comment("Giá bao nhiêu?", external_id="c-1") is True
        assert orchestrator.submit_comment("Giá bao nhiêu?", external_id="c-1") is False
        deadline = time.time() + 2
        while not avatar.messages and time.time() < deadline:
            time.sleep(0.01)
        assert avatar.messages[0][0] == "Trả lời: Giá bao nhiêu?"
        assert avatar.interrupted is True
    finally:
        orchestrator.stop()


def test_idle_script_runs():
    avatar = FakeAvatar()
    settings = LivestreamSettings(
        automation=AutomationSettings(
            enabled=True,
            default_session_id="0",
            idle_seconds=0.02,
            poll_seconds=0.01,
        )
    )
    orchestrator = LivestreamOrchestrator(
        settings,
        FakeAgent(),
        ScriptStore([Script(id="hello", text="Xin chào cả nhà")]),
        FakeSessions(avatar),
    )
    orchestrator.start()
    try:
        deadline = time.time() + 2
        while not avatar.messages and time.time() < deadline:
            time.sleep(0.01)
        assert avatar.messages[0][0] == "Xin chào cả nhà"
        assert avatar.messages[0][1]["source"] == "script"
    finally:
        orchestrator.stop()
