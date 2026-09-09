#!/usr/bin/env python3
"""启动前导入 Wiki 词条缓存到 SQLite。优先读本地文件，找不到则从网络下载。"""
import json, sqlite3, os, time, ssl, urllib.request
from pathlib import Path

db_path = os.environ.get("CAMP_DB_PATH", "./data/camp.db")
local_cache = Path("/app/server/wiki_cache.json")
cache_url = "https://aka.doubaocdn.com/s/X6QVAl7AcU"

cache = None
if local_cache.exists():
    try:
        with open(local_cache, encoding="utf-8") as f:
            cache = json.load(f)
        print(f"[prestart] Loaded local cache: {len(cache)} topics")
    except Exception as e:
        print(f"[prestart] Local cache read failed: {e}")

if cache is None:
    print(f"[prestart] Local file not found, downloading from {cache_url} ...")
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(cache_url, headers={"User-Agent": "BDSMCache/1.0"})
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            cache = json.loads(r.read().decode("utf-8"))
        print(f"[prestart] Downloaded cache: {len(cache)} topics")
    except Exception as e:
        print(f"[prestart] Download failed: {e}")

if cache:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE IF NOT EXISTS wiki_cache (
        title TEXT PRIMARY KEY, description TEXT NOT NULL,
        source_url TEXT NOT NULL, content TEXT NOT NULL,
        revision TEXT NOT NULL DEFAULT '', fetched_at INTEGER NOT NULL
    )""")
    now = int(time.time())
    for title, topic in cache.items():
        conn.execute("""INSERT OR REPLACE INTO wiki_cache
            (title, description, source_url, content, revision, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (topic["title"], topic["description"], topic["source_url"],
             topic["content"], topic.get("revision", ""), now))
    conn.commit()
    conn.close()
    print(f"[prestart] Imported {len(cache)} topics into {db_path}")
else:
    print("[prestart] No cache available, skip")
