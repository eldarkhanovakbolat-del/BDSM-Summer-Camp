#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import Request, urlopen

try:
    from .providers import (
        AIProvider,
        MemoryProvider,
        build_ai_provider,
        build_audience_ai_provider,
        build_memory_provider,
    )
except ImportError:  # Direct execution: python server/app.py
    from providers import (
        AIProvider,
        MemoryProvider,
        build_ai_provider,
        build_audience_ai_provider,
        build_memory_provider,
    )


APP_VERSION = "1.0.0"
WIKI_API = "https://www.bdsmwiki.info/api.php"
WIKI_ORIGIN = "https://www.bdsmwiki.info"
INPUT_TYPES = {"speech", "action", "thought", "question", "ooc"}
INPUT_TYPE_LABELS = {
    "speech": "说话",
    "action": "行动",
    "thought": "想法",
    "question": "提问",
    "ooc": "OOC",
}
MODES = {"study", "experience"}
AUDIENCE_STYLES = {"温柔", "好奇", "调侃", "冷静"}
AUDIENCE_ACTIVITY = {"偶尔评论", "经常评论"}
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_dotenv(path: Path | None = None) -> None:
    """Load a small KEY=VALUE .env file without adding a Python dependency."""
    source = path or Path(__file__).resolve().parents[1] / ".env"
    try:
        lines = source.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


class TextExtractor(HTMLParser):
    BLOCKED = {"script", "style", "table", "nav", "footer", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in self.BLOCKED:
            self._blocked += 1
        elif not self._blocked and tag in {"p", "li", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.BLOCKED and self._blocked:
            self._blocked -= 1
        elif not self._blocked and tag in {"p", "li", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._blocked:
            value = data.strip()
            if value:
                self.parts.append(value)

    def text(self) -> str:
        joined = " ".join(self.parts)
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\s*\n\s*", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


class Store:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init(self) -> None:
        with self.connect() as db:
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("PRAGMA synchronous = NORMAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS wiki_cache (
                    title TEXT PRIMARY KEY,
                    description TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    revision TEXT NOT NULL DEFAULT '',
                    fetched_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    visitor_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    audience_enabled INTEGER NOT NULL,
                    audience_style TEXT NOT NULL,
                    audience_activity TEXT NOT NULL,
                    ai_name TEXT NOT NULL DEFAULT '',
                    suggestions_json TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    input_type TEXT NOT NULL,
                    speaker TEXT NOT NULL,
                    content TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_visitor_updated
                    ON sessions(visitor_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_messages_session_id
                    ON messages(session_id, id);
                PRAGMA optimize;
                """
            )
            session_columns = {
                row["name"] for row in db.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if "ai_name" not in session_columns:
                db.execute("ALTER TABLE sessions ADD COLUMN ai_name TEXT NOT NULL DEFAULT ''")

    def cached_topic(self, title: str, max_age: int = 604800) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM wiki_cache WHERE title = ?", (title,)).fetchone()
        if not row or int(row["fetched_at"]) < int(time.time()) - max_age:
            return None
        return dict(row)

    def save_topic(self, topic: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO wiki_cache(title, description, source_url, content, revision, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(title) DO UPDATE SET description=excluded.description,
                   source_url=excluded.source_url, content=excluded.content,
                   revision=excluded.revision, fetched_at=excluded.fetched_at""",
                (
                    topic["title"], topic["description"], topic["source_url"],
                    topic["content"], topic.get("revision", ""), int(time.time()),
                ),
            )

    def topic_any_age(self, title: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM wiki_cache WHERE title = ?", (title,)).fetchone()
        return dict(row) if row else None

    def create_session(self, values: dict[str, Any]) -> str:
        session_id = str(uuid.uuid4())
        now = utc_now()
        with self.connect() as db:
            db.execute(
                """INSERT INTO sessions(id, visitor_id, topic, mode, audience_enabled,
                   audience_style, audience_activity, ai_name, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, values["visitor_id"], values["topic"], values["mode"],
                    int(values["audience_enabled"]), values["audience_style"],
                    values["audience_activity"], values["ai_name"], now, now,
                ),
            )
        return session_id

    def get_session_row(self, session_id: str, visitor_id: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM sessions WHERE id = ? AND visitor_id = ?",
                (session_id, visitor_id),
            ).fetchone()

    def recent_sessions(self, visitor_id: str) -> list[sqlite3.Row]:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM sessions WHERE visitor_id = ? ORDER BY updated_at DESC LIMIT 10",
                (visitor_id,),
            ).fetchall()

    def delete_session(self, session_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def messages(self, session_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_message(
        self, session_id: str, role: str, input_type: str, speaker: str,
        content: str, action: str = "",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.connect() as db:
            cursor = db.execute(
                """INSERT INTO messages(session_id, role, input_type, speaker, content, action, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, role, input_type, speaker, content, action, now),
            )
            db.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id))
            message_id = cursor.lastrowid
        return {
            "id": message_id, "session_id": session_id, "role": role,
            "input_type": input_type, "speaker": speaker, "content": content,
            "action": action, "created_at": now,
        }

    def save_suggestions(self, session_id: str, suggestions: list[str]) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE sessions SET suggestions_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(suggestions, ensure_ascii=False), utc_now(), session_id),
            )


class WikiClient:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.catalog_path = Path(
            os.environ.get("CAMP_WIKI_CATALOG", str(Path(__file__).with_name("wiki_catalog.json")))
        )
        self._catalog: dict[str, Any] | None = None

    @staticmethod
    def _request(params: dict[str, str], timeout: int = 15) -> dict[str, Any]:
        query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params.items())
        request = Request(
            f"{WIKI_API}?{query}",
            headers={"User-Agent": f"BDSMSummerCamp/{APP_VERSION} (self-hosted client)"},
        )
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read(2_000_000).decode("utf-8"))

    def topic(self, title: str) -> dict[str, Any]:
        cached = self.store.cached_topic(title)
        if cached:
            return cached
        try:
            payload = self._request({
                "action": "parse", "page": title, "prop": "text|revid|displaytitle",
                "format": "json", "formatversion": "2", "redirects": "1",
            })
            parsed = payload["parse"]
            canonical = html.unescape(re.sub(r"<[^>]+>", "", str(parsed.get("displaytitle", title)))).strip()
            raw_html = str(parsed.get("text", ""))
            extractor = TextExtractor()
            extractor.feed(raw_html)
            content = extractor.text()[:16000]
            if not content:
                raise ValueError("empty wiki page")
            description = next((line for line in content.splitlines() if len(line) > 45), content[:180])[:240]
            topic = {
                "title": canonical or title,
                "description": description,
                "source_url": f"{WIKI_ORIGIN}/{quote((canonical or title).replace(' ', '_'))}",
                "content": content,
                "revision": str(parsed.get("revid", "")),
            }
            self.store.save_topic(topic)
            return topic
        except (OSError, ValueError, KeyError, HTTPError, URLError):
            stale = self.store.topic_any_age(title)
            if stale:
                return stale
            raise RuntimeError("暂时无法读取 BDSM Wiki 原词条，请稍后再试")

    def catalog(self) -> dict[str, Any]:
        if self._catalog is not None:
            return self._catalog
        with self.catalog_path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or not isinstance(payload.get("sections"), list):
            raise ValueError("invalid wiki catalog")
        self._catalog = payload
        return payload


class CampAI:
    def __init__(
        self,
        ai: AIProvider,
        memory: MemoryProvider,
        audience_ai: AIProvider | None = None,
    ) -> None:
        self.ai = ai
        self.audience_ai = audience_ai or ai
        self.memory = memory
        persona_path = os.environ.get("AI_PERSONA_FILE", "").strip()
        self.persona = ""
        if persona_path:
            try:
                self.persona = Path(persona_path).read_text(encoding="utf-8")[:20_000].strip()
            except OSError as exc:
                raise RuntimeError("AI_PERSONA_FILE cannot be read") from exc

    def _main_instructions(
        self,
        session: sqlite3.Row,
        topic: dict[str, Any],
        input_type: str,
        opening: bool,
        recalled_memory: str,
    ) -> str:
        if session["mode"] == "study":
            mode_instruction = (
                "以共同学习的形式围绕词条教用户，并和用户一起探索；"
                "保持你原有的人设与关系连贯，让整个过程持续带有浪漫氛围和性张力。"
            )
        else:
            mode_instruction = (
                "与用户一起进入围绕词条展开的纯文字情境，沉浸地回应用户；"
                "保持你原有的人设与关系连贯，让互动持续带有浪漫氛围和性张力。"
            )
        opening_instruction = "自然地开启这次共同学习或体验。" if opening else ""
        persona = f"<existing-ai-persona>\n{self.persona}\n</existing-ai-persona>" if self.persona else ""
        memory = f"<recalled-memory>\n{recalled_memory}\n</recalled-memory>" if recalled_memory else ""
        return f"""
{persona}
{memory}
{mode_instruction}
用户本轮的参与方式是“{INPUT_TYPE_LABELS[input_type]}”。
{opening_instruction}

<bdsmwiki-entry>
{topic['content'][:12000]}
</bdsmwiki-entry>
""".strip()

    @staticmethod
    def _audience_instructions(session: sqlite3.Row) -> str:
        count = "0到1" if session["audience_activity"] == "偶尔评论" else "1到2"
        return f"""
你只扮演 BDSM 夏令营里的虚构文字 AI 观众，不扮演主 AI，也不延续主 AI 的私人身份或记忆。
观众语气：{session['audience_style']}。观众活跃度：{session['audience_activity']}。生成 {count} 条现场反应。
action 使用简短英文动作且不含星号，comment 使用中文。
每条观众反应独占一行，严格使用：AUDIENCE|AI 观众名字|brief English action|中文评论
同时可给 0 到 3 个很短的用户回应灵感，每条独占一行，严格使用：SUGGESTION|回应灵感
不要输出 JSON、Markdown 或其他文字；字段内不要使用竖线。若不生成任何内容，只输出 NONE。
""".strip()

    @staticmethod
    def _audience_payload(raw: str) -> tuple[list[dict[str, str]], list[str]]:
        audience: list[dict[str, str]] = []
        suggestions: list[str] = []
        for line in str(raw or "").splitlines():
            clean = line.strip().strip("` ")
            if clean.startswith("AUDIENCE|") and len(audience) < 2:
                parts = clean.split("|", 3)
                if len(parts) != 4:
                    continue
                name = parts[1].strip()[:40] or "AI 观众"
                if not name.upper().startswith("AI"):
                    name = f"AI 观众·{name}"[:40]
                action = parts[2].strip().strip("*")[:240]
                comment = parts[3].strip()[:1200]
                if comment:
                    audience.append({"name": name, "action": action, "comment": comment})
            elif clean.startswith("SUGGESTION|") and len(suggestions) < 3:
                suggestion = clean.split("|", 1)[1].strip()[:180]
                if suggestion:
                    suggestions.append(suggestion)
        return audience, suggestions

    @staticmethod
    def _history(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        history: list[dict[str, str]] = []
        for item in messages[-30:]:
            role = item.get("role")
            if role == "user":
                label = INPUT_TYPE_LABELS.get(str(item.get("input_type")), "说话")
                history.append({"role": "user", "content": f"[{label}] {str(item.get('content', ''))[:3000]}"})
            elif role == "main_ai":
                history.append({"role": "assistant", "content": str(item.get("content", ""))[:10_000]})
        return history

    @staticmethod
    def _metadata(session: sqlite3.Row) -> dict[str, Any]:
        metadata = {
            "application": "bdsm-summer-camp",
            "topic": session["topic"],
            "mode": session["mode"],
            "visitor_id": session["visitor_id"],
        }
        return metadata

    def generate(
        self,
        session: sqlite3.Row,
        topic: dict[str, Any],
        messages: list[dict[str, Any]],
        input_type: str,
        content: str,
        opening: bool = False,
    ) -> dict[str, Any]:
        user_message = content[:3000]
        if opening:
            user_message = (
                f"今天选择的词条是“{session['topic']}”，"
                f"以“{'一起共学' if session['mode'] == 'study' else '文字体验'}”开始。"
            )
        recalled = ""
        if self.memory.enabled and not opening:
            try:
                recalled = self.memory.recall(
                    namespace=f"visitor:{session['visitor_id']}:main",
                    session_id=str(session["id"]),
                    query=user_message,
                    metadata=self._metadata(session),
                )
            except RuntimeError:
                logging.warning("memory recall failed session=%s", session["id"])
        main_messages = [
            {"role": "system", "content": self._main_instructions(session, topic, input_type, opening, recalled)},
            *self._history(messages),
            {"role": "user", "content": user_message},
        ]
        main_reply = self.ai.complete(
            main_messages,
            purpose="main",
            session_id=str(session["id"]),
        )[:10000]
        if not main_reply:
            raise ValueError("AI returned an empty reply")

        if self.memory.enabled and not opening:
            try:
                self.memory.remember(
                    namespace=f"visitor:{session['visitor_id']}:main",
                    session_id=str(session["id"]),
                    user_message=user_message,
                    assistant_message=main_reply,
                    metadata=self._metadata(session),
                )
            except RuntimeError:
                logging.warning("memory write failed session=%s", session["id"])

        audience: list[dict[str, str]] = []
        suggestions: list[str] = []
        if bool(session["audience_enabled"]):
            try:
                audience_raw = self.audience_ai.complete(
                    [
                        {"role": "system", "content": self._audience_instructions(session)},
                        {"role": "user", "content": f"用户本轮（{input_type}）：\n{content[:3000]}\n\n主 AI 回复：\n{main_reply}"},
                    ],
                    purpose="audience",
                    session_id=f"audience:{session['id']}",
                )
                audience, suggestions = self._audience_payload(audience_raw)
            except (RuntimeError, ValueError, TimeoutError):
                logging.warning("audience generation failed session=%s", session["id"])
        return {"main_reply": main_reply, "audience": audience, "suggestions": suggestions}

class App:
    def __init__(self) -> None:
        self.host = os.environ.get("CAMP_BIND_HOST", "127.0.0.1")
        self.port = int(os.environ.get("CAMP_PORT", "8765"))
        self.store = Store(Path(os.environ.get("CAMP_DB_PATH", "./data/camp.db")))
        self.wiki = WikiClient(self.store)
        self.ai_provider = build_ai_provider()
        self.audience_ai_provider = build_audience_ai_provider(self.ai_provider)
        self.memory_provider = build_memory_provider()
        self.camp_ai = CampAI(self.ai_provider, self.memory_provider, self.audience_ai_provider)
        self.allowed_origins = {
            value.strip().rstrip("/") for value in os.environ.get(
                "CAMP_ALLOWED_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000"
            ).split(",") if value.strip()
        }
        self.api_prefix = os.environ.get("CAMP_API_PREFIX", "").strip().rstrip("/")
        if self.api_prefix and not self.api_prefix.startswith("/"):
            raise RuntimeError("CAMP_API_PREFIX must start with '/'")
        self.rates: dict[str, deque[float]] = {}
        self.rate_lock = threading.Lock()
        self.last_rate_cleanup = 0.0

    def rate_allowed(self, visitor_id: str) -> bool:
        now = time.monotonic()
        with self.rate_lock:
            if now - self.last_rate_cleanup >= 300:
                cutoff = now - 60
                self.rates = {
                    key: bucket for key, bucket in self.rates.items()
                    if bucket and bucket[-1] >= cutoff
                }
                self.last_rate_cleanup = now
            bucket = self.rates.setdefault(visitor_id, deque())
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 12:
                return False
            bucket.append(now)
            return True

    def public_session(
        self,
        row: sqlite3.Row,
        include_messages: bool = True,
        topic: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if topic is None and include_messages:
            topic = self.wiki.topic(row["topic"])
        if topic is None:
            topic = self.store.topic_any_age(row["topic"])
        if topic is None:
            topic = {
                "description": "",
                "content": "",
                "source_url": f"{WIKI_ORIGIN}/{quote(row['topic'].replace(' ', '_'), safe='')}",
            }
        try:
            suggestions = json.loads(row["suggestions_json"])
        except (TypeError, ValueError):
            suggestions = []
        return {
            "id": row["id"], "topic": row["topic"], "mode": row["mode"],
            "ai_name": row["ai_name"],
            "audience_enabled": bool(row["audience_enabled"]),
            "audience_style": row["audience_style"],
            "audience_activity": row["audience_activity"],
            "topic_description": topic["description"],
            "topic_excerpt": topic["content"][:3200],
            "source_url": topic["source_url"],
            "messages": self.store.messages(row["id"]) if include_messages else [],
            "suggestions": suggestions,
            "updated_at": row["updated_at"],
        }


class Handler(BaseHTTPRequestHandler):
    server: "Server"
    server_version = "SummerCampStage"
    sys_version = ""

    def log_message(self, format_string: str, *args: Any) -> None:
        del format_string, args
        logging.info("request method=%s path=%s", self.command, urlsplit(self.path).path)

    def _cors(self) -> bool:
        origin = self.headers.get("Origin", "").rstrip("/")
        if not origin:
            return True
        return origin in self.server.app.allowed_origins

    def _json(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin in self.server.app.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": HTTPStatus(status).phrase.lower(), "message": message})

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 65536:
            self._error(HTTPStatus.BAD_REQUEST, "请求内容无效")
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError):
            self._error(HTTPStatus.BAD_REQUEST, "请求内容无效")
            return None
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "请求内容无效")
            return None
        return payload

    @staticmethod
    def _visitor(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if UUID_RE.fullmatch(text) else None

    def do_OPTIONS(self) -> None:
        if not self._cors():
            self._error(HTTPStatus.FORBIDDEN, "来源未获允许")
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._cors():
            self._error(HTTPStatus.FORBIDDEN, "来源未获允许")
            return
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query)
        api_path = self._api_path(path)
        if api_path == "/health":
            self._json(HTTPStatus.OK, {
                "status": "ok",
                "service": "bdsm-summer-camp",
                "version": APP_VERSION,
                "ai": self.server.app.ai_provider.health(),
                "audience_ai": self.server.app.audience_ai_provider.health(),
                "memory": self.server.app.memory_provider.health(),
            })
            return
        if api_path == "/api/catalog":
            try:
                self._json(HTTPStatus.OK, self.server.app.wiki.catalog())
            except (OSError, ValueError, json.JSONDecodeError):
                logging.exception("wiki catalog unavailable")
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "词条目录暂时无法读取")
            return
        if api_path == "/api/sessions":
            visitor = self._visitor(query.get("visitor_id", [""])[0])
            if not visitor:
                self._error(HTTPStatus.BAD_REQUEST, "访客标识无效")
                return
            sessions = [self.server.app.public_session(row, False) for row in self.server.app.store.recent_sessions(visitor)]
            self._json(HTTPStatus.OK, {"sessions": sessions})
            return
        match = re.fullmatch(r"/api/sessions/([0-9a-f-]{36})", api_path, re.I)
        if match:
            visitor = self._visitor(query.get("visitor_id", [""])[0])
            if not visitor:
                self._error(HTTPStatus.BAD_REQUEST, "访客标识无效")
                return
            row = self.server.app.store.get_session_row(match.group(1), visitor)
            if not row:
                self._error(HTTPStatus.NOT_FOUND, "没有找到这次体验")
                return
            try:
                self._json(HTTPStatus.OK, {"session": self.server.app.public_session(row)})
            except RuntimeError as exc:
                self._error(HTTPStatus.BAD_GATEWAY, str(exc))
            return
        self._error(HTTPStatus.NOT_FOUND, "没有找到这个页面")

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_POST(self) -> None:
        if not self._cors():
            self._error(HTTPStatus.FORBIDDEN, "来源未获允许")
            return
        path = self._api_path(urlsplit(self.path).path)
        body = self._body()
        if body is None:
            return
        if path == "/api/sessions":
            visitor = self._visitor(body.get("visitor_id"))
            topic = str(body.get("topic", "")).strip()[:160]
            mode = str(body.get("mode", ""))
            style = str(body.get("audience_style", ""))
            activity = str(body.get("audience_activity", ""))
            ai_name = re.sub(r"[\x00-\x1f\x7f]", "", str(body.get("ai_name", ""))).strip()
            enabled = body.get("audience_enabled")
            if not visitor or not topic or len(ai_name) > 40 or mode not in MODES or style not in AUDIENCE_STYLES or activity not in AUDIENCE_ACTIVITY or not isinstance(enabled, bool):
                self._error(HTTPStatus.BAD_REQUEST, "体验设置无效")
                return
            if not self.server.app.rate_allowed(visitor):
                self._error(HTTPStatus.TOO_MANY_REQUESTS, "操作太快了，请稍后再试")
                return
            if not self.server.app.ai_provider.configured:
                self._error(HTTPStatus.SERVICE_UNAVAILABLE, "AI 后端尚未配置，请把仓库交给你的 AI 完成接入")
                return
            values = {
                "visitor_id": visitor, "topic": topic, "mode": mode,
                "audience_enabled": enabled, "audience_style": style,
                "audience_activity": activity, "ai_name": ai_name,
            }
            try:
                topic_data = self.server.app.wiki.topic(topic)
            except RuntimeError as exc:
                self._error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            session_id = self.server.app.store.create_session(values)
            row = self.server.app.store.get_session_row(session_id, visitor)
            assert row is not None
            try:
                generated = self.server.app.camp_ai.generate(
                    row, topic_data, [], "ooc", "请开始这次夏令营学习或体验。",
                    opening=True,
                )
                self.server.app.store.add_message(session_id, "main_ai", "reply", ai_name or "AI", generated["main_reply"])
                for item in generated["audience"]:
                    self.server.app.store.add_message(session_id, "audience", "reply", item["name"], item["comment"], item["action"])
                self.server.app.store.save_suggestions(session_id, generated["suggestions"])
            except (RuntimeError, ValueError, TimeoutError):
                logging.warning("opening generation failed session=%s", session_id)
                self.server.app.store.delete_session(session_id)
                self._error(HTTPStatus.BAD_GATEWAY, "AI 暂时没有回应，请检查后端配置后再试")
                return
            refreshed = self.server.app.store.get_session_row(session_id, visitor)
            assert refreshed is not None
            self._json(HTTPStatus.CREATED, {"session": self.server.app.public_session(refreshed, topic=topic_data)})
            return

        match = re.fullmatch(r"/api/sessions/([0-9a-f-]{36})/messages", path, re.I)
        if match:
            visitor = self._visitor(body.get("visitor_id"))
            input_type = str(body.get("input_type", ""))
            content = str(body.get("content", "")).strip()
            if not visitor or input_type not in INPUT_TYPES or not content or len(content) > 3000:
                self._error(HTTPStatus.BAD_REQUEST, "消息内容无效")
                return
            if not self.server.app.rate_allowed(visitor):
                self._error(HTTPStatus.TOO_MANY_REQUESTS, "消息太快了，请稍后再试")
                return
            row = self.server.app.store.get_session_row(match.group(1), visitor)
            if not row:
                self._error(HTTPStatus.NOT_FOUND, "没有找到这次体验")
                return
            previous = self.server.app.store.messages(row["id"])
            try:
                topic_data = self.server.app.wiki.topic(row["topic"])
            except RuntimeError as exc:
                self._error(HTTPStatus.BAD_GATEWAY, str(exc))
                return
            try:
                generated = self.server.app.camp_ai.generate(
                    row, topic_data, previous, input_type, content,
                )
            except TimeoutError:
                self._error(HTTPStatus.GATEWAY_TIMEOUT, "AI 思考得有点久，请再试一次")
                return
            except (RuntimeError, ValueError):
                logging.warning("message generation failed session=%s", row["id"])
                self._error(HTTPStatus.BAD_GATEWAY, "AI 暂时没有回应，请稍后再试")
                return
            self.server.app.store.add_message(row["id"], "user", input_type, "你", content)
            self.server.app.store.add_message(row["id"], "main_ai", "reply", row["ai_name"] or "AI", generated["main_reply"])
            for item in generated["audience"]:
                self.server.app.store.add_message(row["id"], "audience", "reply", item["name"], item["comment"], item["action"])
            self.server.app.store.save_suggestions(row["id"], generated["suggestions"])
            refreshed = self.server.app.store.get_session_row(row["id"], visitor)
            assert refreshed is not None
            self._json(HTTPStatus.OK, {"session": self.server.app.public_session(refreshed, topic=topic_data)})
            return
        self._error(HTTPStatus.NOT_FOUND, "没有找到这个页面")

    def _api_path(self, path: str) -> str:
        prefix = self.server.app.api_prefix
        if prefix:
            if path == prefix:
                return "/"
            if path.startswith(prefix + "/"):
                return path[len(prefix):]
        return path


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], app: App) -> None:
        super().__init__(address, Handler)
        self.app = app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_dotenv()
    app = App()
    server = Server((app.host, app.port), app)
    logging.info("starting bdsm-summer-camp version=%s bind=%s:%s", APP_VERSION, app.host, app.port)
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
