import re
import sys

def _find_def_start(text, func_name):
    m = re.search(r"(?m)^[ \t]*def[ \t]+" + re.escape(func_name) + r"\b.*:\s*$", text)
    if not m:
        return None
    return m.start()

def _find_block_start(text, def_start):
    # If the line immediately above def_start is an @mcp.tool decorator, include it.
    # Walk upwards to include consecutive decorator lines.
    pre = text[:def_start]
    lines = pre.splitlines(True)
    if not lines:
        return def_start
    i = len(lines) - 1

    # Skip blank lines right before def
    while i >= 0 and lines[i].strip() == "":
        i -= 1

    # Include consecutive decorators (e.g., @mcp.tool)
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
    # End at next top-level def or next @mcp.tool (at any indent level)
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

# Apply patches
s2 = s
s2 = replace_function(s2, "ha_call_service", new_ha_call_service)
s2 = replace_function(s2, "ha_weather_forecast", new_ha_weather_forecast)

open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
