from __future__ import annotations

import os
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".codex" / "config.toml"

REQUIRED_ENV = {
    "firecrawl": ["FIRECRAWL_API_KEY"],
    "perplexity": ["PERPLEXITY_API_KEY"],
    "yandex_search": ["YANDEX_SEARCH_API_KEY", "YANDEX_FOLDER_ID"],
    "brave_search": ["BRAVE_API_KEY"],
    "exa": ["EXA_API_KEY"],
    "tavily": ["TAVILY_API_KEY"],
    "serpapi": ["SERPAPI_API_KEY"],
}


def present(name: str) -> bool:
    value = os.environ.get(name, "").strip()
    return bool(value) and not (value.startswith("${") and value.endswith("}"))


def main() -> int:
    if not CONFIG.exists():
        print(f"ERROR: missing MCP config: {CONFIG}")
        return 1

    config = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    servers = config.get("mcp_servers", {})
    errors: list[str] = []
    warnings: list[str] = []

    for server, names in REQUIRED_ENV.items():
        if server not in servers:
            errors.append(f"missing server config: {server}")
            continue
        missing = [name for name in names if not present(name)]
        if missing:
            warnings.append(f"{server}: missing env {', '.join(missing)}")
        else:
            print(f"OK: {server}")

    if errors:
        print("MCP CONFIG FAILED")
        for error in errors:
            print("ERROR:", error)
        return 1

    if warnings:
        print("MCP CONFIG PRESENT, KEYS NEEDED")
        for warning in warnings:
            print("WARN:", warning)
        return 2

    print("MCP RESEARCH STACK READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
