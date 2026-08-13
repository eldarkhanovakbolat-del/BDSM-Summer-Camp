from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from server.app import load_dotenv  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check BDSM Summer Camp repository and private setup.")
    parser.add_argument(
        "--repository",
        action="store_true",
        help="Only check distributable repository files; do not require a configured model.",
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    load_dotenv(ROOT / ".env")

    errors: list[str] = []
    warnings: list[str] = []
    passed: list[str] = []

    required = [
        "README.md",
        "AI_SETUP.md",
        "AGENTS.md",
        "LICENSE",
        "server/app.py",
        "server/providers/ai.py",
        "server/providers/memory.py",
        "server/wiki_catalog.json",
        "app/ExperienceApp.tsx",
    ]
    missing = [name for name in required if not (ROOT / name).is_file()]
    if missing:
        errors.append("缺少仓库文件：" + ", ".join(missing))
    else:
        passed.append("公开仓库必需文件完整")

    try:
        catalog = json.loads((ROOT / "server/wiki_catalog.json").read_text(encoding="utf-8"))
        counts = {section["id"]: section["unique_count"] for section in catalog["sections"]}
        if counts != {"bdsm101": 25, "theory": 85, "disciplines": 268}:
            errors.append(f"词条目录数量异常：{counts}")
        elif any(
            not str(topic.get("source_url", "")).startswith("https://www.bdsmwiki.info/")
            for section in catalog["sections"]
            for topic in section["topics"]
        ):
            errors.append("词条目录中存在非 BDSM Wiki 来源")
        else:
            passed.append("BDSM Wiki 三栏目录与来源有效")
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        errors.append(f"词条目录无法读取：{type(exc).__name__}")

    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".env", "data/", "*.db", "*.log"):
        if pattern not in ignored:
            errors.append(f".gitignore 未排除 {pattern}")
    if not any(message.startswith(".gitignore") for message in errors):
        passed.append("秘密配置、数据库与日志默认不进入 Git")

    for name in (
        "AI_EXTRA_HEADERS_JSON",
        "AI_EXTRA_BODY_JSON",
        "AUDIENCE_AI_EXTRA_HEADERS_JSON",
        "AUDIENCE_AI_EXTRA_BODY_JSON",
    ):
        try:
            value = json.loads(os.environ.get(name, "{}") or "{}")
            if not isinstance(value, dict):
                errors.append(f"{name} 必须是 JSON 对象")
        except json.JSONDecodeError:
            errors.append(f"{name} 不是有效 JSON")

    if not args.repository:
        base_url = os.environ.get("AI_BASE_URL", "").strip()
        model = os.environ.get("AI_MODEL", "").strip()
        if not model:
            errors.append("尚未填写 AI_MODEL")
        if not base_url or urlsplit(base_url).scheme not in {"http", "https"}:
            errors.append("AI_BASE_URL 必须是 http 或 https 地址")
        if model and base_url:
            passed.append("AI 后端基础配置已填写")

        audience_configured = any(
            os.environ.get(name, "").strip()
            for name in (
                "AUDIENCE_AI_PROVIDER",
                "AUDIENCE_AI_BASE_URL",
                "AUDIENCE_AI_API_KEY",
                "AUDIENCE_AI_MODEL",
            )
        )
        if audience_configured:
            audience_url = os.environ.get("AUDIENCE_AI_BASE_URL", "").strip() or base_url
            audience_model = os.environ.get("AUDIENCE_AI_MODEL", "").strip() or model
            if urlsplit(audience_url).scheme not in {"http", "https"}:
                errors.append("AUDIENCE_AI_BASE_URL 必须是 http 或 https 地址")
            if not audience_model:
                errors.append("独立观众端点需要 AUDIENCE_AI_MODEL 或可继承的 AI_MODEL")
            if audience_model and urlsplit(audience_url).scheme in {"http", "https"}:
                passed.append("独立文字观众 AI 配置已填写")

        if not os.environ.get("AI_API_KEY", "").strip():
            warnings.append("AI_API_KEY 为空；仅无鉴权的本地网关可以这样使用")

        memory = os.environ.get("MEMORY_PROVIDER", "off").strip().lower()
        if memory in {"", "off", "none", "disabled"}:
            passed.append("长期记忆已明确关闭，本地会话仍会保存")
        elif memory == "http":
            memory_url = os.environ.get("MEMORY_BASE_URL", "").strip()
            if urlsplit(memory_url).scheme not in {"http", "https"}:
                errors.append("MEMORY_BASE_URL 必须是 http 或 https 地址")
            else:
                passed.append("HTTP 长期记忆配置已启用")
        else:
            errors.append(f"未知 MEMORY_PROVIDER：{memory}")

        persona = os.environ.get("AI_PERSONA_FILE", "").strip()
        if persona and not Path(persona).expanduser().is_file():
            errors.append("AI_PERSONA_FILE 指向的文件不存在")

    for message in passed:
        print(f"[OK] {message}")
    for message in warnings:
        print(f"[WARN] {message}")
    for message in errors:
        print(f"[ERROR] {message}")
    if errors:
        print(f"\n检查未通过：{len(errors)} 个问题。")
        return 1
    print("\n仓库检查通过。" if args.repository else "\n配置检查通过，可以进行真实会话测试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
