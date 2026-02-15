#!/usr/bin/env python3
import io
import os
import sys

def _find_def_block(lines, def_name):
    # returns (start_idx, end_idx) for block including @mcp.tool decorator line above def
    def_line = None
    for i, ln in enumerate(lines):
        if ln.startswith("def " + def_name + "("):
            def_line = i
            break
    if def_line is None:
        return None

    start = def_line
    # include the nearest decorator line above
    j = def_line - 1
    while j >= 0:
        if lines[j].lstrip().startswith("@mcp.tool"):
            start = j
            break
        if lines[j].startswith("def "):
            break
        j -= 1

    # end at next @mcp.tool decorator or next def at same level
    end = len(lines)
    for k in range(def_line + 1, len(lines)):
        if lines[k].lstrip().startswith("@mcp.tool"):
            end = k
            break
    return (start, end)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 patch_guard_v1.py /path/to/app.py")
        return 2
    path = sys.argv[1]
    with io.open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # --- replace ha_weather_forecast ---
    blk = _find_def_block(lines, "ha_weather_forecast")
    if not blk:
        print("Cannot find ha_weather_forecast")
        return 3
    ws, we = blk
    new_weather = [
        '@mcp.tool(description="(Structured/Internal) Get forecast for a HA weather entity. Prefer using route_request.")\n',
        "def ha_weather_forecast(entity_id: str, forecast_type: str = \"daily\", timeout_sec: int = 12) -> dict:\n",
        "    eid = str(entity_id or \"\").strip()\n",
        "    ftype = str(forecast_type or \"daily\").strip().lower()\n",
        "    if not eid:\n",
        "        return {\"ok\": False, \"error\": \"empty_entity_id\"}\n",
        "    if ftype not in (\"daily\", \"hourly\", \"twice_daily\"):\n",
        "        ftype = \"daily\"\n",
        "\n",
        "    # Guard: avoid HA 500 when entity is missing/unavailable\n",
        "    st = ha_get_state(eid, timeout_sec=6)\n",
        "    if not st.get(\"ok\"):\n",
        "        return {\"ok\": False, \"error\": \"entity_not_found\", \"entity_id\": eid, \"detail\": st}\n",
        "    try:\n",
        "        st_data = st.get(\"data\") or {}\n",
        "        st_state = str(st_data.get(\"state\") or \"\")\n",
        "    except Exception:\n",
        "        st_state = \"\"\n",
        "    if st_state in (\"unavailable\", \"unknown\"):\n",
        "        return {\"ok\": False, \"error\": \"entity_unavailable\", \"entity_id\": eid, \"state\": st_state}\n",
        "\n",
        "    body = {\"entity_id\": eid, \"type\": ftype}\n",
        "    r = ha_call_service(\"weather\", \"get_forecasts\", service_data=body, return_response=True, timeout_sec=int(timeout_sec))\n",
        "    if not r.get(\"ok\"):\n",
        "        return r\n",
        "\n",
        "    data = r.get(\"data\") or {}\n",
        "    sr = data.get(\"service_response\") or {}\n",
        "    ent = sr.get(eid) or {}\n",
        "    fc = ent.get(\"forecast\") or []\n",
        "    if not isinstance(fc, list):\n",
        "        fc = []\n",
        "\n",
        "    return {\n",
        "        \"ok\": True,\n",
        "        \"status_code\": r.get(\"status_code\"),\n",
        "        \"entity_id\": eid,\n",
        "        \"forecast_type\": ftype,\n",
        "        \"count\": len(fc),\n",
        "        \"forecast\": fc,\n",
        "    }\n",
        "\n",
    ]
    lines[ws:we] = new_weather

    # --- replace ha_calendar_events ---
    blk = _find_def_block(lines, "ha_calendar_events")
    if not blk:
        print("Cannot find ha_calendar_events")
        return 4
    cs, ce = blk
    new_cal = [
        '@mcp.tool(description="(Structured/Internal) List events for a HA calendar entity. Prefer using route_request.")\n',
        "def ha_calendar_events(entity_id: str, start: str, end: str, timeout_sec: int = 12) -> dict:\n",
        "    eid = str(entity_id or \"\").strip()\n",
        "    if not eid:\n",
        "        return {\"ok\": False, \"error\": \"empty_entity_id\"}\n",
        "\n",
        "    def _norm_iso(x: str) -> str:\n",
        "        t = str(x or \"\").strip()\n",
        "        if t.endswith(\"Z\"):\n",
        "            t = t[:-1] + \"+00:00\"\n",
        "        return t\n",
        "\n",
        "    s = _norm_iso(start)\n",
        "    e = _norm_iso(end)\n",
        "    if (not s) or (not e):\n",
        "        return {\"ok\": False, \"error\": \"empty_start_or_end\", \"hint\": \"Provide start/end ISO strings.\"}\n",
        "\n",
        "    # Guard: validate ISO and range\n",
        "    try:\n",
        "        from datetime import datetime as _dt\n",
        "        ds = _dt.fromisoformat(s)\n",
        "        de = _dt.fromisoformat(e)\n",
        "        if de <= ds:\n",
        "            return {\"ok\": False, \"error\": \"invalid_time_range\", \"start\": s, \"end\": e}\n",
        "    except Exception:\n",
        "        return {\"ok\": False, \"error\": \"invalid_iso_datetime\", \"start\": s, \"end\": e}\n",
        "\n",
        "    path = \"/api/calendars/\" + eid + \"?start=\" + requests.utils.quote(s) + \"&end=\" + requests.utils.quote(e)\n",
        "    return _ha_request(\"GET\", path, timeout_sec=int(timeout_sec))\n",
        "\n",
    ]
    lines[cs:ce] = new_cal

    with io.open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("Patched:", path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
