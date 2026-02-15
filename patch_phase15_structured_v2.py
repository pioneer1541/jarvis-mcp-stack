import re
import sys

def replace_func(src: str, func_name: str, new_block: str) -> str:
    # Replace from decorator line before def, until next decorator/def/EOF
    # Works even if there are leading spaces.
    pat = (
        r"(?ms)"
        r"^[ \t]*@mcp\.tool[^\n]*\n"
        r"^[ \t]*def[ \t]+"
        + re.escape(func_name)
        + r"[ \t]*\([^\)]*\)[ \t]*->[ \t]*dict[ \t]*:\n"
        r"(?:^(?![ \t]*@mcp\.tool|[ \t]*def[ \t]+).*\n)*"
    )
    m = re.search(pat, src)
    if not m:
        raise RuntimeError("cannot find function block: " + func_name)
    return src[: m.start()] + new_block.rstrip() + "\n\n" + src[m.end():]

p = "app.py"
s = open(p, "r", encoding="utf-8").read()

# 1) ha_call_service with return_response
new_ha_call_service = '''
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
'''.strip()

# 2) ha_weather_forecast normalized schema + use ha_call_service(return_response=True)
new_ha_weather_forecast = '''
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
'''.strip()

# Apply replacements
s2 = s
s2 = replace_func(s2, "ha_call_service", new_ha_call_service)
s2 = replace_func(s2, "ha_weather_forecast", new_ha_weather_forecast)

# 3) tools_selfcheck: replace function body if found (more tolerant)
pat_ts = r"(?ms)^[ \t]*def[ \t]+tools_selfcheck\([^\)]*\)[ \t]*->[ \t]*dict[ \t]*:\n(?:^(?![ \t]*def[ \t]+).*\n)*"
m = re.search(pat_ts, s2)
if m:
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
    s2 = s2[: m.start()] + new_ts + "\n\n" + s2[m.end():]

open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
