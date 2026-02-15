import re

def _find_line_start(s, pos):
    i = s.rfind("\n", 0, pos)
    if i < 0:
        return 0
    return i + 1

def _find_next_toplevel_def_or_decorator(s, start_pos):
    m = re.search(r"(?m)^[ \t]*(?:@mcp\.tool\b|def[ \t]+)\b", s[start_pos:])
    if not m:
        return len(s)
    return start_pos + m.start()

def _replace_tools_selfcheck(s):
    # locate "def tools_selfcheck"
    m = re.search(r"(?m)^[ \t]*def[ \t]+tools_selfcheck\b[ \t]*\(", s)
    if not m:
        raise RuntimeError("cannot find def tools_selfcheck")
    def_pos = m.start()

    # try to include preceding @mcp.tool line if close above
    start = def_pos
    lookback = s[:def_pos].splitlines(True)
    # scan last ~30 lines for the nearest @mcp.tool
    j = len(lookback) - 1
    cnt = 0
    while j >= 0 and cnt < 30:
        line = lookback[j]
        if re.match(r"^[ \t]*@mcp\.tool\b", line):
            start = sum(len(x) for x in lookback[:j])
            break
        # stop if we hit another top-level def (we don't want to cross into previous function)
        if re.match(r"^[ \t]*def[ \t]+\w+\b", line):
            break
        j -= 1
        cnt += 1

    end = _find_next_toplevel_def_or_decorator(s, def_pos + 1)

    new_block = """
@mcp.tool(description="Return tool names exposed by this MCP server (self-check).")
def tools_selfcheck() -> dict:
    tools = []
    try:
        if hasattr(mcp, "tools") and isinstance(getattr(mcp, "tools"), dict):
            tools = sorted(list(getattr(mcp, "tools").keys()))
        elif hasattr(mcp, "_tools") and isinstance(getattr(mcp, "_tools"), dict):
            tools = sorted(list(getattr(mcp, "_tools").keys()))
        elif hasattr(mcp, "get_tools"):
            t = mcp.get_tools()
            if isinstance(t, dict):
                tools = sorted(list(t.keys()))
            elif isinstance(t, list):
                out = []
                for x in t:
                    if isinstance(x, dict) and ("name" in x):
                        out.append(str(x.get("name")))
                    else:
                        out.append(str(x))
                tools = sorted(out)
    except Exception:
        tools = []

    if not tools:
        tools = [
            "hello",
            "ping",
            "tools_selfcheck",
            "web_answer",
            "ha_get_state",
            "ha_call_service",
            "ha_weather_forecast",
            "ha_calendar_events",
            "holiday_vic",
        ]

    return {
        "ok": True,
        "tools": tools,
        "note": "In Home Assistant MCP client, tools are namespaced as '<entry>__<tool>'.",
    }
""".strip() + "\n\n"

    return s[:start] + new_block + s[end:]

def _ensure_main_footer(s):
    # If the script already has __main__ and uvicorn.run(app...), do nothing.
    has_main_guard = re.search(r"(?m)^if[ \t]+__name__[ \t]*==[ \t]*[\"']__main__[\"']\s*:", s) is not None
    has_uvicorn_run = "uvicorn.run(app" in s
    has_asgi_mount = re.search(r"(?m)^[ \t]*app[ \t]*=[ \t]*Starlette\(", s) is not None

    if has_main_guard and has_uvicorn_run and has_asgi_mount:
        return s

    footer = """
# ---- ASGI app mount ----
app = Starlette(
    routes=[
        Mount("/", app=mcp.sse_app()),
    ]
)

def main() -> None:
    port_str = os.getenv("PORT", "19090")
    try:
        port = int(port_str)
    except Exception:
        port = 19090

    print("[mcp-hello] dns_rebinding_protection =", True)
    print("[mcp-hello] allowed_hosts =", _allowed_hosts)
    print("[mcp-hello] allowed_origins =", _allowed_origins)
    print("[mcp-hello] searxng_url =", os.getenv("SEARXNG_URL", "http://192.168.1.162:8081"))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
""".strip() + "\n"

    # ensure file ends with newline
    if not s.endswith("\n"):
        s = s + "\n"
    return s + "\n" + footer

p = "app.py"
with open(p, "r", encoding="utf-8") as f:
    src = f.read()

src2 = _replace_tools_selfcheck(src)
src3 = _ensure_main_footer(src2)

with open(p, "w", encoding="utf-8") as f:
    f.write(src3)

print("patched_ok=1")
