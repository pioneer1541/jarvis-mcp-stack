import re
import sys

def _must(pattern, text, label):
    if not re.search(pattern, text, flags=re.M | re.S):
        sys.stderr.write("ERROR: cannot find block: " + label + "\n")
        return False
    return True

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# ---- 1) ha_call_service: add return_response support ----
pat_call = r"""
^[ \t]*@mcp\.tool\(description="\(\Structured\) Call a Home Assistant service via HA REST API\."\)[ \t]*\r?\n
^[ \t]*def[ \t]+ha_call_service\([\s\S]*?\r?\n
^[ \t]*return[ \t]+_ha_request\([^\r\n]*\)[ \t]*\r?\n
""".strip()

rep_call = """
@mcp.tool(description="(Structured) Call a Home Assistant service via HA REST API.")
def ha_call_service(domain: str, service: str, service_data: Optional[dict] = None, return_response: bool = False, timeout_sec: int = 10) -> dict:
    d = str(domain or "").strip()
    s = str(service or "").strip()
    if (not d) or (not s):
        return {"ok": False, "error": "empty_domain_or_service"}
    body = service_data if isinstance(service_data, dict) else {}
    path = "/api/services/" + d + "/" + s
    if bool(return_response):
        path = path + "?return_response"
    return _ha_request("POST", path, json_body=body, timeout_sec=int(timeout_sec))

""".lstrip()

ok1 = _must(pat_call, s, "ha_call_service")
if ok1:
    s = re.sub(pat_call, rep_call, s, flags=re.M | re.S)

# ---- 2) ha_weather_forecast: normalize output schema + use ha_call_service ----
pat_w = r"""
^[ \t]*@mcp\.tool\(description="\(\Structured\) Get forecast for a HA weather entity using weather\.get_forecasts service\."\)[ \t]*\r?\n
^[ \t]*def[ \t]+ha_weather_forecast\([\s\S]*?\r?\n
^[ \t]*return[ \t]+_ha_request\([^\r\n]*get_forecasts[^\r\n]*\)[ \t]*\r?\n
""".strip()

rep_w = """
@mcp.tool(description="(Structured) Get forecast for a HA weather entity using weather.get_forecasts service.")
def ha_weather_forecast(entity_id: str, forecast_type: str = "daily", timeout_sec: int = 12) -> dict:
    eid = str(entity_id or "").strip()
    ftype = str(forecast_type or "daily").strip().lower()
    if not eid:
        return {"ok": False, "error": "empty_entity_id"}
    if ftype not in ("daily", "hourly", "twice_daily"):
        ftype = "daily"

    body = {"entity_id": eid, "type": ftype}
    r = ha_call_service("weather", "get_forecasts", service_data=body, return_response=True, timeout_sec=int(timeout_sec))
    if not r.get("ok"):
        return r

    data = r.get("data") or {}
    sr = data.get("service_response") or {}
    ent = sr.get(eid) or {}
    fc = ent.get("forecast") or []
    if not isinstance(fc, list):
        fc = []

    return {
        "ok": True,
        "status_code": r.get("status_code"),
        "entity_id": eid,
        "forecast_type": ftype,
        "count": len(fc),
        "forecast": fc,
    }

""".lstrip()

ok2 = _must(pat_w, s, "ha_weather_forecast")
if ok2:
    s = re.sub(pat_w, rep_w, s, flags=re.M | re.S)

# ---- 3) tools_selfcheck: dynamic enumerate tools if possible, else fallback ----
# We patch by replacing the function body if we can find 'def tools_selfcheck'
pat_ts = r"^[ \t]*def[ \t]+tools_selfcheck\([\s\S]*?\n(?=^[ \t]*def[ \t]+|^\Z)"
m = re.search(pat_ts, s, flags=re.M | re.S)
if m:
    rep_ts = """
def tools_selfcheck() -> dict:
    tools = []
    try:
        # Try common FastMCP internals across versions
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

""".lstrip()
    s = s[:m.start()] + rep_ts + "\n" + s[m.end():]
else:
    sys.stderr.write("WARN: tools_selfcheck() not found; skipped patch for it.\n")

if s == orig:
    sys.stderr.write("No changes applied. Please check patterns.\n")
    sys.exit(2)

open(p, "w", encoding="utf-8").write(s)
print("patched_ok=1")
