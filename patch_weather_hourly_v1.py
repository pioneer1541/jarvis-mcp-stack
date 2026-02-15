#!/usr/bin/env python3
import io
import sys

def _find_block_by_def(lines, def_name):
    # Find "def <name>(" line
    def_line = None
    for i, ln in enumerate(lines):
        if ln.startswith("def " + def_name + "("):
            def_line = i
            break
    if def_line is None:
        return None

    # include nearest decorator line above if present
    start = def_line
    j = def_line - 1
    while j >= 0:
        if lines[j].lstrip().startswith("@mcp.tool"):
            start = j
            break
        if lines[j].startswith("def "):
            break
        j -= 1

    # end at next @mcp.tool or next top-level def (decorator usually exists)
    end = len(lines)
    for k in range(def_line + 1, len(lines)):
        if lines[k].lstrip().startswith("@mcp.tool"):
            end = k
            break
    return (start, end)

def _find_func_end(lines, start_idx):
    # start_idx points to "def ..." line; find next top-level "def " with no indent
    for i in range(start_idx + 1, len(lines)):
        if lines[i].startswith("def "):
            return i
    return len(lines)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 patch_weather_hourly_v1.py /path/to/app.py")
        return 2

    path = sys.argv[1]
    with io.open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 1) Replace ha_weather_forecast with guarded version
    blk = _find_block_by_def(lines, "ha_weather_forecast")
    if not blk:
        print("Cannot find ha_weather_forecast")
        return 3
    ws, we = blk

    new_weather_tool = [
        '@mcp.tool(description="(Structured) Get forecast for a HA weather entity using weather.get_forecasts service.")\n',
        'def ha_weather_forecast(entity_id: str, forecast_type: str = "daily", timeout_sec: int = 12) -> dict:\n',
        '    eid = str(entity_id or "").strip()\n',
        '    ftype = str(forecast_type or "daily").strip().lower()\n',
        '    if not eid:\n',
        '        return {"ok": False, "error": "empty_entity_id"}\n',
        '    if ftype not in ("daily", "hourly", "twice_daily"):\n',
        '        ftype = "daily"\n',
        '\n',
        '    # Guard: avoid HA 500 when entity is missing/unavailable\n',
        '    st = ha_get_state(eid, timeout_sec=6)\n',
        '    if not st.get("ok"):\n',
        '        return {"ok": False, "error": "entity_not_found", "entity_id": eid, "detail": st}\n',
        '    try:\n',
        '        st_data = st.get("data") or {}\n',
        '        st_state = str(st_data.get("state") or "").strip()\n',
        '    except Exception:\n',
        '        st_state = ""\n',
        '    if st_state in ("unavailable", "unknown"):\n',
        '        return {"ok": False, "error": "entity_unavailable", "entity_id": eid, "state": st_state}\n',
        '\n',
        '    body = {"entity_id": eid, "type": ftype}\n',
        '    r = ha_call_service("weather", "get_forecasts", service_data=body, return_response=True, timeout_sec=int(timeout_sec))\n',
        '    if not r.get("ok"):\n',
        '        return r\n',
        '\n',
        '    data = r.get("data") or {}\n',
        '    sr = data.get("service_response") or {}\n',
        '    ent = sr.get(eid) or {}\n',
        '    fc = ent.get("forecast") or []\n',
        '    if not isinstance(fc, list):\n',
        '        fc = []\n',
        '\n',
        '    return {\n',
        '        "ok": True,\n',
        '        "status_code": r.get("status_code"),\n',
        '        "entity_id": eid,\n',
        '        "forecast_type": ftype,\n',
        '        "count": len(fc),\n',
        '        "forecast": fc,\n',
        '    }\n',
        '\n',
    ]
    lines[ws:we] = new_weather_tool

    # 2) Insert helper: _summarise_hourly_next_hours after _summarise_weather_item
    # Find "def _summarise_weather_item(it):"
    idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("def _summarise_weather_item("):
            idx = i
            break
    if idx is None:
        print("Cannot find _summarise_weather_item")
        return 4

    end_idx = _find_func_end(lines, idx)
    helper = [
        '\n',
        'def _summarise_hourly_next_hours(fc_list, now_local, tzinfo, hours):\n',
        '    if not isinstance(fc_list, list) or len(fc_list) == 0:\n',
        '        return "无可用预报。"\n',
        '    try:\n',
        '        n = int(hours)\n',
        '    except Exception:\n',
        '        n = 6\n',
        '    if n < 1:\n',
        '        n = 1\n',
        '    if n > 12:\n',
        '        n = 12\n',
        '\n',
        '    out = []\n',
        '    for it in fc_list:\n',
        '        if not isinstance(it, dict):\n',
        '            continue\n',
        '        dt = _dt_from_iso(it.get("datetime"))\n',
        '        if dt is None:\n',
        '            continue\n',
        '        try:\n',
        '            if getattr(dt, "tzinfo", None) is None and tzinfo is not None:\n',
        '                dt = dt.replace(tzinfo=tzinfo)\n',
        '        except Exception:\n',
        '            pass\n',
        '        try:\n',
        '            if tzinfo is not None:\n',
        '                dt2 = dt.astimezone(tzinfo)\n',
        '            else:\n',
        '                dt2 = dt\n',
        '        except Exception:\n',
        '            dt2 = dt\n',
        '\n',
        '        # filter past hours (best-effort)\n',
        '        try:\n',
        '            if (now_local is not None) and hasattr(now_local, "tzinfo") and (dt2 < now_local):\n',
        '                continue\n',
        '        except Exception:\n',
        '            pass\n',
        '\n',
        '        tm = ""\n',
        '        try:\n',
        '            tm = dt2.strftime("%H:%M")\n',
        '        except Exception:\n',
        '            tm = str(dt2)\n',
        '\n',
        '        cond = str(it.get("condition") or "").strip()\n',
        '        temp = it.get("temperature")\n',
        '        part = tm\n',
        '        if cond:\n',
        '            part = part + " " + cond\n',
        '        if temp is not None:\n',
        '            part = part + " " + str(temp) + "°C"\n',
        '        out.append(part)\n',
        '        if len(out) >= n:\n',
        '            break\n',
        '\n',
        '    if len(out) == 0:\n',
        '        return "无可用预报。"\n',
        '    return "接下来" + str(len(out)) + "小时：" + "；".join(out) + "。"\n',
        '\n',
    ]
    # Insert helper right after _summarise_weather_item ends
    lines[end_idx:end_idx] = helper

    # 3) Patch route_request weather branch: use hourly entity for "today" single queries
    # Find the weather branch lines: if _is_weather_query(user_text):
    wif = None
    for i, ln in enumerate(lines):
        if ln.strip() == "if _is_weather_query(user_text):":
            wif = i
            break
    if wif is None:
        print("Cannot find weather branch in route_request")
        return 5

    # Find eid line and rr line within next ~60 lines
    eid_line = None
    rr_line = None
    for j in range(wif, min(wif + 80, len(lines))):
        if "eid = str(os.environ.get(\"HA_DEFAULT_WEATHER_ENTITY\")" in lines[j]:
            eid_line = j
        if "rr = ha_weather_forecast(eid, \"daily\")" in lines[j]:
            rr_line = j
            break
    if eid_line is None or rr_line is None:
        print("Cannot find expected eid/rr lines to patch in weather branch")
        return 6

    indent = lines[eid_line].split("e")[0]  # crude: preserves leading spaces before 'eid'
    new_block = [
        indent + 'eid_daily = str(os.environ.get("HA_DEFAULT_WEATHER_ENTITY") or "").strip()\n',
        indent + 'eid_hourly = str(os.environ.get("HA_DEFAULT_WEATHER_ENTITY_HOURLY") or "").strip()\n',
        indent + 'if not eid_daily:\n',
        indent + '    return {"ok": True, "route_type": "structured_weather", "final": "未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。", "error": "missing_default_weather_entity"}\n',
        indent + 'tzinfo = _tzinfo()\n',
        indent + 'now = _now_local()\n',
        indent + 'base_d = dt_date(now.year, now.month, now.day)\n',
        '\n',
        indent + 'q = _weather_range_from_text(user_text, now_local=now)\n',
        indent + '# Use hourly entity for "today" single-day queries if configured\n',
        indent + 'use_hourly = False\n',
        indent + 'if eid_hourly and (q.get("mode") != "range"):\n',
        indent + '    td0 = q.get("target_date")\n',
        indent + '    if not isinstance(td0, dt_date):\n',
        indent + '        off0 = _safe_int(q.get("offset"), 0)\n',
        indent + '        try:\n',
        indent + '            from datetime import timedelta\n',
        indent + '            td0 = base_d + timedelta(days=off0)\n',
        indent + '        except Exception:\n',
        indent + '            td0 = base_d\n',
        indent + '    if isinstance(td0, dt_date) and (td0 == base_d):\n',
        indent + '        use_hourly = True\n',
        '\n',
        indent + 'if use_hourly:\n',
        indent + '    rr_h = ha_weather_forecast(eid_hourly, "hourly")\n',
        indent + '    if rr_h.get("ok"):\n',
        indent + '        fc_h = rr_h.get("forecast") if isinstance(rr_h.get("forecast"), list) else []\n',
        indent + '        label_h = str((q.get("label") or "")).strip()\n',
        indent + '        summary_h = _summarise_hourly_next_hours(fc_h, now, tzinfo, 6)\n',
        indent + '        final_h = (label_h + "：" if label_h else "天气：") + summary_h\n',
        indent + '        ret_h = {"ok": True, "route_type": "structured_weather", "final": final_h}\n',
        indent + '        if _route_return_data:\n',
        indent + '            ret_h["data"] = rr_h\n',
        indent + '        return ret_h\n',
        '\n',
        indent + 'rr = ha_weather_forecast(eid_daily, "daily")\n',
    ]

    # Replace from eid_line to rr_line inclusive
    lines[eid_line:rr_line + 1] = new_block

    with io.open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("Patched:", path)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
