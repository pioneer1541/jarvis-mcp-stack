# Jarvis MCP Stack (Home Assistant + RAG Gateway)

## Goals
- Local-first, self-hostable home assistant brain: stable, short answers, low hallucination, actionable.
- One gateway for Home Assistant `conversation.process` and other clients.
- RAG-ready knowledge base (Qdrant) with repeatable ingestion + evaluation.

## What This Is
Two containers form the core:
- `mcp-hello`: MCP server exposing skills (RAG/search/news/calendar/music/control).
- `openai-mcp-gateway`: OpenAI-compatible HTTP gateway + `/invoke/*` helpers (including HA-style `/invoke/ha_assist_context`).

This repo also ships evaluation runners and ingestion scripts.

## Features
- Home Assistant Assist bridge: `/invoke/ha_assist_context` (simulates HA `conversation.process` path).
- RAG memory search via Qdrant + embeddings (Ollama).
- Anytype export sync into Qdrant (offline/headless workflow).
- News brief (Miniflux), optional web search (Brave/SearXNG), holiday/calendar helpers.
- Eval tooling: fixed question sets, timing, heuristic scoring, JSON + HTML reports, and an internal report host.

## Note About Generated Code
This project contains a significant amount of code generated or iteratively modified with OpenAI Codex.
Treat it as production-like code that still needs human review: security, safety, and correctness are your responsibility.

## Services / Ports
- `mcp-hello`: `:19090`
- `openai-mcp-gateway`: `:19100`
- `eval-report` (static report host): `:19110`
- Qdrant (external): default `:6333` (`/dashboard`)
- Ollama (external): default `:11434`

## Quick Start
1. Create env files (commit-safe templates are provided):
   - Copy `.env.news_miniflux.example` to `.env.news_miniflux`
   - Copy `secrets/.env.mcp.secrets.example` to `secrets/.env.mcp.secrets`
2. Start containers:
```bash
docker compose up -d --build
```
3. Open report host:
- `http://<server-ip>:19110/`

## Configuration Guide
This stack depends on external services, but most are optional. Configure via:
- `.env.news_miniflux` (non-secret settings and endpoints)
- `secrets/.env.mcp.secrets` (tokens/keys)

Common settings (examples in the `*.example` files):
- Home Assistant:
  - `HA_BASE_URL` (in `docker-compose.yml`)
  - `HA_TOKEN` (in `secrets/.env.mcp.secrets`)
- RAG:
  - `QDRANT_URL`, `QDRANT_COLLECTION`, `QDRANT_VECTOR_SIZE`
  - `OLLAMA_BASE_URL`, `EMBED_MODEL`
- News:
  - `MINIFLUX_BASE_URL`
  - `MINIFLUX_API_TOKEN` (in `secrets/.env.mcp.secrets`)
- Web search (optional):
  - `BRAVE_SEARCH_TOKEN` (optional)
  - `SEARXNG_URL` (optional)
- Anytype export sync (optional):
  - `ANYTYPE_API_BASE`, `ANYTYPE_SPACE_ID` (optional)
  - `ANYTYPE_API_KEY` (in `secrets/.env.mcp.secrets`)
  - `ANYTYPE_EXPORT_DIR`, `ANYTYPE_EXPORT_EXTS`

If a dependency is missing (e.g. no Qdrant/Miniflux), related routes will degrade, but the containers can still start.

## Eval
- Phase-complete eval (container tests + HA-style daily100):
```bash
make phase-eval
```
- Install git hooks (runs phase-eval on every `git push`):
```bash
make install-hooks
```
- Skip once:
```bash
SKIP_PHASE_EVAL=1 git push
```

## Secrets Policy
- Never commit `.env*` (except `*.example`)
- Never commit `secrets/.env.mcp.secrets` or `secrets/gmail/*`
