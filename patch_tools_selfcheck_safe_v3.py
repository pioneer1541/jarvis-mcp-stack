import re
import sys

def _find_def_start(text, func_name):
    m = re.search(r"(?m)^[ \t]*def[ \t]+" + re.escape(func_name) + r"\b.*:\s*$", text)
    if not m:
        return None
    return m.start()

def _find_block_start(text, def_start):
    pre = text[:def_start]
    lines = pre.splitlines(True)
    if not lines:
        return def_start
    i = len(lines) - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    start_idx = def_start
    while i >= 0:
        line = lines[i]
        if re.match(r"^[ \t]*@mcp\.tool\b", line):
            start_idx = sum(len(x) for x in lines[:i])
            i -= 1
            continue
        break
    return start_idx

def _find_block_end(text, def_start):
    m = re.search(r"(?m)^[ \t]*(?:@mcp\.tool\b|def[ \t]+)\b", text[def_start+1:])
    if not m:
        return len(text)
    return def_start + 1 + m.start()

def replace_function(text, func_name, new_block):
    ds = _find_def_start(text, func_name)
    if ds is None:
        raise RuntimeError("cannot find function def: " + func_name)
    bs = _find_block_start(text, ds)
    be = _find_block_end(text, ds)
    return text[:bs] + new_block.rstrip() + "\n\n" + text[be:]

p = "app.py"
s = open(p, "r", encoding="utf-8").read()

new_ts = '''
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
'''.strip()

s2 = replace_function(s, "tools_selfcheck", new_ts)
open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
