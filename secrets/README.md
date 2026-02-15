# Secrets

This folder holds local-only credentials and tokens.

By default, this repo ignores real secrets under `secrets/` via `.gitignore`, but keeps:
- `secrets/README.md`
- `secrets/*.example`

Currently used:
- `secrets/.env.mcp.secrets`: runtime secrets for docker compose (HA token, API tokens, etc.)
  - Template: `secrets/.env.mcp.secrets.example`

Also present (local-only, do not commit):
- `secrets/gmail/*`
