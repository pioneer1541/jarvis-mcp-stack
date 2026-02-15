import re

P = "app.py"
s = open(P, "r", encoding="utf-8").read()

MARK = "# --- MCP_TOOL_PREFIX_ALIASES_V1 ---"
if MARK in s:
    print("already patched")
    raise SystemExit(0)

# 在 if __name__ == "__main__": 之前插入
m = re.search(r'^\s*if\s+__name__\s*==\s*["\']__main__["\']\s*:\s*$', s, re.M)
if not m:
    raise SystemExit("cannot find __main__ block")

insert = r'''

{mark}
# Home Assistant MCP client may namespace tool names as "<entry>__<tool>".
# Provide prefixed aliases so HA can call tools successfully.
_MCP_TOOL_PREFIX = os.getenv("MCP_TOOL_PREFIX", "mcp-hello").strip()

def _mcp_prefixed_name(base_name: str) -> str:
    if not _MCP_TOOL_PREFIX:
        return base_name
    return _MCP_TOOL_PREFIX + "__" + base_name

# Alias: open_url_extract
@mcp.tool(
    name=_mcp_prefixed_name("open_url_extract"),
    description="Alias of open_url_extract for HA (prefixed tool name compatibility)."
)
def open_url_extract_prefixed(url: str, max_chars: int = 4000, timeout_sec: int = 10) -> dict:
    return open_url_extract(url=url, max_chars=max_chars, timeout_sec=timeout_sec)

# Alias: web_search
@mcp.tool(
    name=_mcp_prefixed_name("web_search"),
    description="Alias of web_search for HA (prefixed tool name compatibility)."
)
def web_search_prefixed(query: str, max_results: int = 5, timeout_sec: int = 15) -> dict:
    return web_search(query=query, max_results=max_results, timeout_sec=timeout_sec)

# Alias: tools_selfcheck (optional)
@mcp.tool(
    name=_mcp_prefixed_name("tools_selfcheck"),
    description="Alias of tools_selfcheck for HA (prefixed tool name compatibility)."
)
def tools_selfcheck_prefixed() -> dict:
    return tools_selfcheck()
'''.format(mark=MARK)

out = s[:m.start()] + insert + "\n" + s[m.start():]
open(P, "w", encoding="utf-8").write(out)
print("patched")
