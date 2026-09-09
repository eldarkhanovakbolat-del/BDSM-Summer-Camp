#!/usr/bin/env python3
"""夏令营记忆协议 <-> Ombre Brain MCP 适配器"""
import json
import os
import ssl
import sys
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

OMBRE_URL = os.environ.get("OMBRE_MCP_URL", "https://ombre.zeabur.app/mcp")
OMBRE_TOKEN = os.environ.get("OMBRE_MCP_TOKEN", "")
ADAPTER_HOST = os.environ.get("ADAPTER_HOST", "127.0.0.1")
ADAPTER_PORT = int(os.environ.get("ADAPTER_PORT", "8766"))
MEMORY_TAG = os.environ.get("MEMORY_TAG", "夏令营对话")

_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


def mcp_tool(name, arguments):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if OMBRE_TOKEN:
        headers["Authorization"] = f"Bearer {OMBRE_TOKEN}"
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(OMBRE_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120, context=_SSL_CTX) as resp:
        body = resp.read().decode()
    if body.startswith("data:"):
        lines = [l for l in body.splitlines() if l.startswith("data:")]
        if lines:
            body = lines[-1][5:].strip()
    result = json.loads(body)
    if "error" in result:
        raise RuntimeError(f"MCP error: {result['error']}")
    content = result.get("result", {}).get("content", [])
    texts = [c.get("text", "") for c in content if c.get("type") == "text"]
    return "\n".join(texts)


class Handler(BaseHTTPRequestHandler):
    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            data = self._read_json()
            if self.path == "/recall":
                query = data.get("query", "")
                parts = []
                try:
                    core = mcp_tool("breath", {})
                    if core.strip():
                        parts.append("【核心记忆】\n" + core)
                except Exception as e:
                    print(f"[adapter] breath failed: {e}", file=sys.stderr, flush=True)
                if query.strip():
                    try:
                        relevant = mcp_tool("breath_search", {"query": query, "max_results": 10, "mode": "automatic"})
                        if relevant.strip():
                            parts.append("【相关记忆】\n" + relevant)
                    except Exception as e:
                        print(f"[adapter] breath_search failed: {e}", file=sys.stderr, flush=True)
                self._send_json(200, {"text": "\n\n".join(parts)})
            elif self.path == "/remember":
                user_msg = data.get("user_message", "")
                ai_msg = data.get("assistant_message", "")
                meta = data.get("metadata", {})
                content = f"[夏令营对话/{meta.get('mode','')}/{meta.get('topic','')}]\n用户：{user_msg}\nAI：{ai_msg}"
                try:
                    result = mcp_tool("hold", {"content": content, "tags": MEMORY_TAG, "importance": 5})
                    self._send_json(200, {"ok": True, "result": result})
                except Exception as e:
                    print(f"[adapter] hold failed: {e}", file=sys.stderr, flush=True)
                    self._send_json(200, {"ok": False, "error": str(e)})
            else:
                self._send_json(404, {"error": "not found"})
        except Exception as e:
            print(f"[adapter] handler error: {e}", file=sys.stderr, flush=True)
            self._send_json(500, {"error": str(e)})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Memory adapter on {ADAPTER_HOST}:{ADAPTER_PORT} -> {OMBRE_URL}", flush=True)
    server = HTTPServer((ADAPTER_HOST, ADAPTER_PORT), Handler)
    server.serve_forever()
