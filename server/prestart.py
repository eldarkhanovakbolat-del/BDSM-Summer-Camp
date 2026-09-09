#!/usr/bin/env python3
"""启动前把本地词条缓存导入 SQLite，避免服务器联网拉取 Wiki。"""
import json, sqlite3, os, time
from pathlib import Path

db_path = os.environ.get("CAMP_DB_PATH", "./data/camp.db")
cache_file = Path(__file__).with_name("wiki_cache.json")

if cache_file.exists():
    with open(cache_file, encoding="utf-8") as f:
        cache = json.load(f)
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
    print(f"Pre-loaded {len(cache)} wiki topics")
else:
    print("No wiki_cache.json found, skip")
