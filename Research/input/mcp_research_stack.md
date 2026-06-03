# MCP research stack

Project-scoped MCP config lives in `.codex/config.toml`. It is intentionally scoped
to this research project so other Codex workspaces do not inherit a large research
toolset.

## Enabled servers

### firecrawl
- Purpose: scrape official sites, PDFs, contact pages, staff pages and hidden pages.
- Package: `firecrawl-mcp`
- Required env: `FIRECRAWL_API_KEY`
- Use for: evidence extraction and source capture.

### perplexity
- Purpose: broad discovery and fast lead generation with citations.
- Package: `@perplexity-ai/mcp-server`
- Required env: `PERPLEXITY_API_KEY`
- Use for: finding candidate companies, LPR names and possible source URLs.
- Rule: never treat Perplexity's answer as final contact evidence; follow links and
  verify contacts on source pages.

### yandex_search
- Purpose: Russian-language web search, especially older PDFs, event pages,
  registry-like pages and Russian name/email/phone queries.
- Server: official Yandex Search MCP remote endpoint via `mcp-remote`.
- Required env: `YANDEX_SEARCH_API_KEY`, `YANDEX_FOLDER_ID`
- Use for: Russian SERP coverage and Cyrillic queries.

### brave_search
- Purpose: independent web/news/search fallback.
- Package: `@brave/brave-search-mcp-server`
- Required env: `BRAVE_API_KEY`
- Use for: broad web search when Perplexity/Yandex miss sources.

### exa
- Purpose: company research and semantic web search.
- Package: `exa-mcp-server`
- Required env: `EXA_API_KEY`
- Use for: discovering similar high-fit companies and company/source trails.

### tavily
- Purpose: search/extract/map/crawl fallback.
- Package: `tavily-mcp`
- Required env: `TAVILY_API_KEY`
- Use for: alternate search/extraction when Firecrawl or Exa coverage is weak.

### serpapi
- Purpose: structured SERP fallback across search engines.
- Server: hosted SerpApi MCP via `mcp-remote`.
- Required env: `SERPAPI_API_KEY`
- Use for: Google/Bing-style SERP checks, exact person/email/phone queries and
  source diversification.

## Required shell exports

Add only the keys you actually have:

```bash
export FIRECRAWL_API_KEY="..."
export PERPLEXITY_API_KEY="..."
export YANDEX_SEARCH_API_KEY="..."
export YANDEX_FOLDER_ID="..."
export BRAVE_API_KEY="..."
export EXA_API_KEY="..."
export TAVILY_API_KEY="..."
export SERPAPI_API_KEY="..."
```

## Pre-run checks

```bash
codex mcp list
python3 scripts/check_mcp_research_stack.py
```

`codex mcp list` confirms the servers are registered. The Python check confirms
whether the required environment variables are present in the current shell.

## Source-quality rule
MCP search tools are allowed to find leads quickly. Final workbook evidence must
still follow the project rules: official source or strong public corroboration,
direct person-level contacts only, no generic inboxes, no guessed emails, no generic
phones without named extensions.
