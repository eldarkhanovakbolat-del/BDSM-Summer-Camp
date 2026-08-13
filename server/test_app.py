from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import app as camp
from server.providers.ai import (
    AIProvider,
    OpenAICompatibleProvider,
    ProviderError,
    build_audience_ai_provider,
)
from server.providers.memory import MemoryProvider


class FakeAI(AIProvider):
    name = "fake"
    configured = True

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_audience = False

    def complete(self, messages, *, purpose, session_id):
        self.calls.append({"messages": messages, "purpose": purpose, "session_id": session_id})
        if purpose == "audience":
            if self.fail_audience:
                raise ProviderError("audience unavailable")
            return "AUDIENCE|眠猫|leans closer|这节课比想象中更有意思\nSUGGESTION|告诉我你更好奇哪一部分"
        return "这是来自用户自己 AI 后端的回复。"


class FakeMemory(MemoryProvider):
    name = "fake"
    enabled = True

    def __init__(self) -> None:
        self.recalls: list[dict] = []
        self.writes: list[dict] = []

    def recall(self, **values):
        self.recalls.append(values)
        return "用户和 AI 以前一起聊过信任。"

    def remember(self, **values):
        self.writes.append(values)


def topic(title="Consent"):
    return {
        "title": title,
        "description": "BDSM Wiki source description",
        "source_url": f"https://www.bdsmwiki.info/{title}",
        "content": "ORIGINAL_WIKI_ENTRY_CONTENT",
        "revision": "1",
    }


class CampPromptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = camp.Store(Path(self.temp.name) / "app.db")
        self.fake_ai = FakeAI()
        self.fake_memory = FakeMemory()
        self.camp_ai = camp.CampAI(self.fake_ai, self.fake_memory)
        self.session_id = self.store.create_session({
            "visitor_id": str(uuid.uuid4()),
            "topic": "Consent",
            "mode": "study",
            "audience_enabled": True,
            "audience_style": "好奇",
            "audience_activity": "经常评论",
            "ai_name": "",
        })
        with self.store.connect() as db:
            self.row = db.execute("SELECT * FROM sessions WHERE id = ?", (self.session_id,)).fetchone()

    def tearDown(self):
        self.temp.cleanup()

    def test_main_receives_history_wiki_and_memory(self):
        messages = [
            {"role": "user", "input_type": "thought", "content": "之前的问题"},
            {"role": "main_ai", "input_type": "reply", "content": "之前的回答"},
            {"role": "audience", "input_type": "reply", "content": "不应进入主历史"},
        ]
        result = self.camp_ai.generate(self.row, topic(), messages, "question", "这次的问题")
        self.assertEqual(result["main_reply"], "这是来自用户自己 AI 后端的回复。")
        main = self.fake_ai.calls[0]
        self.assertEqual(main["purpose"], "main")
        joined = "\n".join(item["content"] for item in main["messages"])
        self.assertIn("ORIGINAL_WIKI_ENTRY_CONTENT", joined)
        self.assertIn("用户和 AI 以前一起聊过信任", joined)
        self.assertIn("之前的问题", joined)
        self.assertNotIn("不应进入主历史", joined)
        self.assertEqual(len(self.fake_memory.recalls), 1)
        self.assertEqual(len(self.fake_memory.writes), 1)

    def test_audience_is_separate_and_never_receives_memory_or_persona(self):
        self.camp_ai.persona = "PRIVATE_PERSONA_TEXT"
        self.camp_ai.generate(self.row, topic(), [], "speech", "你好")
        audience = self.fake_ai.calls[1]
        self.assertEqual(audience["purpose"], "audience")
        joined = "\n".join(item["content"] for item in audience["messages"])
        self.assertNotIn("PRIVATE_PERSONA_TEXT", joined)
        self.assertNotIn("用户和 AI 以前一起聊过信任", joined)
        self.assertNotIn("ORIGINAL_WIKI_ENTRY_CONTENT", joined)
        self.assertTrue(audience["session_id"].startswith("audience:"))
        self.assertTrue(all(call["namespace"].startswith("visitor:") and call["namespace"].endswith(":main") for call in self.fake_memory.recalls + self.fake_memory.writes))

    def test_audience_can_use_a_separate_ai_provider(self):
        audience_ai = FakeAI()
        camp_ai = camp.CampAI(self.fake_ai, self.fake_memory, audience_ai)
        camp_ai.generate(self.row, topic(), [], "speech", "你好")
        self.assertEqual([call["purpose"] for call in self.fake_ai.calls], ["main"])
        self.assertEqual([call["purpose"] for call in audience_ai.calls], ["audience"])

    def test_opening_does_not_read_or_write_long_term_memory(self):
        self.camp_ai.generate(self.row, topic(), [], "ooc", "开始", opening=True)
        self.assertEqual(self.fake_memory.recalls, [])
        self.assertEqual(self.fake_memory.writes, [])

    def test_audience_failure_does_not_drop_main_reply(self):
        self.fake_ai.fail_audience = True
        result = self.camp_ai.generate(self.row, topic(), [], "speech", "继续")
        self.assertEqual(result["main_reply"], "这是来自用户自己 AI 后端的回复。")
        self.assertEqual(result["audience"], [])

    def test_no_de_eroticizing_hidden_guidance(self):
        prompt = self.camp_ai._main_instructions(self.row, topic(), "speech", False, "")
        for forbidden in ("保持教育语气", "不要太露骨", "只推进一步", "必须提醒风险"):
            self.assertNotIn(forbidden, prompt)


class ProviderContractTests(unittest.TestCase):
    def test_openai_provider_health_never_contains_secret(self):
        old = dict(os.environ)
        try:
            os.environ.update({
                "AI_BASE_URL": "http://127.0.0.1:9999/v1",
                "AI_MODEL": "example-model",
                "AI_API_KEY": "do-not-leak-this-key",
            })
            provider = OpenAICompatibleProvider()
            health = json.dumps(provider.health())
            self.assertNotIn("do-not-leak-this-key", health)
            self.assertNotIn("AI_API_KEY", health)
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_reserved_isolation_headers_cannot_be_overridden(self):
        captured = {}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                return

            def do_POST(self):
                captured["purpose"] = self.headers.get("X-Camp-Purpose")
                captured["session"] = self.headers.get("X-Camp-Session")
                captured["custom"] = self.headers.get("X-Custom")
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        old = dict(os.environ)
        try:
            os.environ.update({
                "AI_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
                "AI_MODEL": "example-model",
                "AI_EXTRA_HEADERS_JSON": json.dumps({
                    "X-Camp-Purpose": "main",
                    "X-Camp-Session": "private",
                    "X-Custom": "allowed",
                }),
            })
            provider = OpenAICompatibleProvider()
            reply = provider.complete(
                [{"role": "user", "content": "test"}],
                purpose="audience",
                session_id="audience:public-session",
            )
            self.assertEqual(reply, "ok")
            self.assertEqual(captured, {
                "purpose": "audience",
                "session": "audience:public-session",
                "custom": "allowed",
            })
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
            os.environ.clear()
            os.environ.update(old)

    def test_separate_audience_provider_does_not_inherit_main_secret(self):
        old = dict(os.environ)
        try:
            for key in list(os.environ):
                if key.startswith("AI_") or key.startswith("AUDIENCE_AI_"):
                    os.environ.pop(key)
            os.environ.update({
                "AI_BASE_URL": "https://main.example.invalid/v1",
                "AI_MODEL": "main-model",
                "AI_API_KEY": "main-secret",
                "AI_EXTRA_HEADERS_JSON": '{"X-Private-Identity":"main"}',
                "AI_EXTRA_BODY_JSON": '{"private_identity":"main"}',
                "AUDIENCE_AI_BASE_URL": "https://audience.example.invalid/v1",
                "AUDIENCE_AI_MODEL": "audience-model",
            })
            main = OpenAICompatibleProvider()
            audience = build_audience_ai_provider(main)
            self.assertIsNot(audience, main)
            self.assertIsInstance(audience, OpenAICompatibleProvider)
            self.assertEqual(audience.base_url, "https://audience.example.invalid/v1")
            self.assertEqual(audience.model, "audience-model")
            self.assertEqual(audience.api_key, "")
            self.assertEqual(audience.extra_headers, {})
            self.assertEqual(audience.extra_body, {})
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_audience_provider_reuses_main_when_not_configured(self):
        old = dict(os.environ)
        try:
            for key in list(os.environ):
                if key.startswith("AUDIENCE_AI_"):
                    os.environ.pop(key)
            main = FakeAI()
            self.assertIs(build_audience_ai_provider(main), main)
        finally:
            os.environ.clear()
            os.environ.update(old)


class StageApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = dict(os.environ)
        os.environ.update({
            "CAMP_DB_PATH": str(Path(self.temp.name) / "app.db"),
            "CAMP_BIND_HOST": "127.0.0.1",
            "CAMP_PORT": "0",
            "CAMP_ALLOWED_ORIGINS": "http://localhost:3000",
            "AI_MODEL": "fake-model",
        })
        self.app = camp.App()
        self.fake_ai = FakeAI()
        self.app.ai_provider = self.fake_ai
        self.app.audience_ai_provider = self.fake_ai
        self.app.memory_provider = FakeMemory()
        self.app.camp_ai = camp.CampAI(
            self.fake_ai,
            self.app.memory_provider,
            self.app.audience_ai_provider,
        )
        self.app.wiki.topic = lambda title: topic(title)
        self.server = camp.Server(("127.0.0.1", 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.visitor = str(uuid.uuid4())

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        os.environ.clear()
        os.environ.update(self.old)
        self.temp.cleanup()

    def request(self, method, path, body=None, origin="http://localhost:3000"):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Origin": origin},
        )
        with urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def test_health_is_neutral(self):
        status, payload = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "bdsm-summer-camp")
        self.assertEqual(payload["ai"]["provider"], "fake")
        self.assertEqual(payload["audience_ai"]["provider"], "fake")
        self.assertEqual(payload["memory"]["provider"], "fake")

    def test_create_resume_and_all_input_types(self):
        status, payload = self.request("POST", "/api/sessions", {
            "visitor_id": self.visitor,
            "topic": "Consent",
            "mode": "study",
            "ai_name": "",
            "audience_enabled": True,
            "audience_style": "好奇",
            "audience_activity": "偶尔评论",
        })
        self.assertEqual(status, 201)
        session_id = payload["session"]["id"]
        self.assertEqual(payload["session"]["messages"][0]["speaker"], "AI")
        for input_type in camp.INPUT_TYPES:
            status, payload = self.request("POST", f"/api/sessions/{session_id}/messages", {
                "visitor_id": self.visitor,
                "input_type": input_type,
                "content": f"测试 {input_type}",
            })
            self.assertEqual(status, 200)
        status, resumed = self.request("GET", f"/api/sessions/{session_id}?visitor_id={self.visitor}")
        self.assertEqual(status, 200)
        self.assertEqual(resumed["session"]["id"], session_id)

    def test_origin_is_restricted(self):
        with self.assertRaises(HTTPError) as raised:
            self.request("GET", "/health", origin="https://not-allowed.example")
        self.assertEqual(raised.exception.code, 403)

    def test_recent_sessions_do_not_fetch_wiki(self):
        session_id = self.app.store.create_session({
            "visitor_id": self.visitor,
            "topic": "Consent",
            "mode": "study",
            "ai_name": "",
            "audience_enabled": False,
            "audience_style": "好奇",
            "audience_activity": "偶尔评论",
        })

        def should_not_fetch(_title):
            raise AssertionError("recent-session summaries must not fetch the wiki")

        self.app.wiki.topic = should_not_fetch
        status, payload = self.request("GET", f"/api/sessions?visitor_id={self.visitor}")
        self.assertEqual(status, 200)
        self.assertEqual(payload["sessions"][0]["id"], session_id)

    def test_rate_limiter_removes_stale_visitors(self):
        self.app.rates["stale-visitor"] = camp.deque([camp.time.monotonic() - 120])
        self.app.last_rate_cleanup = camp.time.monotonic() - 301
        self.assertTrue(self.app.rate_allowed(self.visitor))
        self.assertNotIn("stale-visitor", self.app.rates)

    def test_wiki_failure_returns_json_for_resume_and_message(self):
        session_id = self.app.store.create_session({
            "visitor_id": self.visitor,
            "topic": "Consent",
            "mode": "study",
            "ai_name": "",
            "audience_enabled": False,
            "audience_style": "好奇",
            "audience_activity": "偶尔评论",
        })

        def unavailable(_title):
            raise RuntimeError("BDSM Wiki 暂时无法访问，请稍后再试")

        self.app.wiki.topic = unavailable
        with self.assertRaises(HTTPError) as resumed:
            self.request("GET", f"/api/sessions/{session_id}?visitor_id={self.visitor}")
        self.assertEqual(resumed.exception.code, 502)
        self.assertIn("BDSM Wiki", json.loads(resumed.exception.read())["message"])

        with self.assertRaises(HTTPError) as messaged:
            self.request("POST", f"/api/sessions/{session_id}/messages", {
                "visitor_id": self.visitor,
                "input_type": "speech",
                "content": "继续",
            })
        self.assertEqual(messaged.exception.code, 502)
        self.assertIn("BDSM Wiki", json.loads(messaged.exception.read())["message"])


if __name__ == "__main__":
    unittest.main()
