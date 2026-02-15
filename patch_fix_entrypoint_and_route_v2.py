# coding: utf-8
import io, os, re, shutil

APP = "app.py"
MARK = "# --- MCP_ENTRYPOINT_AND_ROUTE_V1 ---"
PLACEHOLDER = "__MCP_MARK_PLACEHOLDER__"

ADD_TEMPLATE = r'''
__MCP_MARK_PLACEHOLDER__

# Notes:
# - Fix "Restarting (0)" by providing a long-running entrypoint.
# - Provide MCP tools: route_request + tools_selfcheck.
# - No f-strings (project rule).

def _safe_int(x, d):
    try:
        return int(x)
    except Exception:
        return d

def _tzinfo():
    tzname = os.environ.get("TZ") or "Australia/Melbourne"
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tzname)
    except Exception:
        return None

def _now_local():
    tz = _tzinfo()
    try:
        from datetime import datetime
        return datetime.now(tz) if tz else datetime.now()
    except Exception:
        from datetime import datetime
        return datetime.now()

def _dt_from_iso(s):
    try:
        from datetime import datetime
        t = str(s or "").strip()
        if not t:
            return None
        t = t.replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except Exception:
        return None

def _local_date_from_forecast_item(it, tzinfo):
    if not isinstance(it, dict):
        return None
    dt = _dt_from_iso(it.get("datetime"))
    if dt is None:
        return None
    try:
        if tzinfo is not None:
            return dt.astimezone(tzinfo).date()
        return dt.date()
    except Exception:
        try:
            return dt.date()
        except Exception:
            return None

def _summarise_weather_item(it):
    if not isinstance(it, dict):
        return "无可用预报。"
    cond = str(it.get("condition") or "").strip()
    tmax = it.get("temperature")
    tmin = it.get("templow")
    pr = it.get("precipitation")
    ws = it.get("wind_speed")

    parts = []
    if cond:
        parts.append("天气: " + cond)
    if (tmax is not None) or (tmin is not None):
        parts.append("最高/最低: " + str(tmax) + "°C / " + str(tmin) + "°C")
    if pr is not None:
        try:
            prf = float(pr)
        except Exception:
            prf = None
        if prf is not None:
            parts.append("预计" + ("无降雨" if prf == 0.0 else ("降雨 " + str(pr))))
    if ws is not None:
        parts.append("有风（约 " + str(ws) + "）")

    if not parts:
        return "无可用预报。"
    return "，".join(parts) + "。"

def _pick_daily_forecast_by_local_date(fc_list, target_date, tzinfo):
    if not isinstance(fc_list, list):
        return None
    for it in fc_list:
        d = _local_date_from_forecast_item(it, tzinfo)
        if d is None:
            continue
        if d == target_date:
            return it
    return None

def _summarise_weather_range(fc_list, start_date, days, tzinfo):
    if not isinstance(fc_list, list):
        return "无可用预报。"
    try:
        days_i = int(days)
    except Exception:
        days_i = 3
    if days_i < 1:
        days_i = 1
    if days_i > 7:
        days_i = 7

    out = []
    try:
        from datetime import timedelta
        for i in range(days_i):
            d = start_date + timedelta(days=i)
            it = _pick_daily_forecast_by_local_date(fc_list, d, tzinfo)
            if it is None:
                out.append(str(d) + ": 无预报")
            else:
                cond = str(it.get("condition") or "").strip()
                tmax = it.get("temperature")
                tmin = it.get("templow")
                out.append(str(d) + ": " + cond + " " + str(tmax) + "/" + str(tmin) + "°C")
    except Exception:
        return "无可用预报。"
    return "；".join(out) + "。"

def _is_weather_query(t):
    s = str(t or "")
    keys = ["天气", "温度", "降雨", "下雨", "气温", "风", "预报", "天氣"]
    for k in keys:
        if k in s:
            return True
    return False

def _is_calendar_query(t):
    s = str(t or "")
    keys = ["日程", "日历", "日曆", "安排", "行程", "提醒", "待办", "待辦", "event", "calendar"]
    for k in keys:
        if k in s:
            return True
    return False

def _is_holiday_query(t):
    s = str(t or "")
    keys = ["公众假期", "公眾假期", "法定假日", "假期", "假日", "holiday"]
    for k in keys:
        if k in s:
            return True
    return False

def _looks_like_entity_id(t):
    s = str(t or "").strip()
    if " " in s or "　" in s:
        return False
    if re.match(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$", s):
        return True
    return False

def _iso_day_start_end(d, tzinfo):
    from datetime import datetime, timedelta
    try:
        if tzinfo:
            start = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo)
        else:
            start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = start + timedelta(days=1)
        return start.isoformat(), end.isoformat()
    except Exception:
        start = datetime(d.year, d.month, d.day, 0, 0, 0)
        end = start + timedelta(days=1)
        return start.isoformat(), end.isoformat()

def _summarise_calendar_events(events):
    if (not isinstance(events, list)) or (len(events) == 0):
        return "没有日程。"
    parts = []
    lim = 6
    for it in events[:lim]:
        if not isinstance(it, dict):
            continue
        summ = str(it.get("summary") or "").strip()
        st = it.get("start") or {}
        if isinstance(st, dict) and st.get("date"):
            parts.append("全天 " + summ)
        else:
            dt = None
            if isinstance(st, dict):
                dt = st.get("dateTime") or st.get("datetime")
            if dt:
                parts.append(str(dt) + " " + summ)
            else:
                parts.append(summ)
    if len(events) > lim:
        parts.append("等共 " + str(len(events)) + " 条")
    return "；".join([p for p in parts if p]) + "。"

@mcp.tool(description="(Router) Classify user text into structured routes and return formatted answer. Prefer weather/calendar/holiday/state. This tool should NOT call web.")
def route_request(text: str) -> dict:
    user_text = str(text or "").strip()
    if not user_text:
        return {"ok": True, "route_type": "open_domain", "final": "", "hint": "empty text"}

    # entity_id state
    if _looks_like_entity_id(user_text):
        r = ha_get_state(user_text)
        if not r.get("ok"):
            return {"ok": True, "route_type": "structured_state", "final": "我现在联网查询失败了，请稍后再试。", "data": r}
        data = r.get("data") or {}
        st = str(data.get("state") or "").strip()
        return {"ok": True, "route_type": "structured_state", "final": "实体 " + user_text + " 状态: " + st + "。", "data": r, "entity_id": user_text}

    # holiday
    if _is_holiday_query(user_text):
        m = re.search(r"(20\d{2})", user_text)
        y = None
        if m:
            try:
                y = int(m.group(1))
            except Exception:
                y = None
        now = _now_local()
        if y is None:
            try:
                y = int(getattr(now, "year"))
            except Exception:
                y = 2026
        rr = holiday_vic(y)
        if not rr.get("ok"):
            return {"ok": True, "route_type": "structured_holiday", "final": "假期查询失败。", "data": rr}
        items = rr.get("holidays") or []
        return {"ok": True, "route_type": "structured_holiday", "final": "已获取维州公众假期（AU-VIC），年份 " + str(y) + "，共 " + str(len(items)) + " 天。", "data": rr}

    # weather
    if _is_weather_query(user_text):
        eid = str(os.environ.get("HA_DEFAULT_WEATHER_ENTITY") or "").strip()
        if not eid:
            return {"ok": True, "route_type": "structured_weather", "final": "未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。", "error": "missing_default_weather_entity"}
        tzinfo = _tzinfo()
        now = _now_local()
        base_d = dt_date(now.year, now.month, now.day)

        q = _weather_range_from_text(user_text, now_local=now)
        rr = ha_weather_forecast(eid, "daily")
        if not rr.get("ok"):
            return {"ok": True, "route_type": "structured_weather", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
        fc = rr.get("forecast") if isinstance(rr.get("forecast"), list) else []
        label = str((q.get("label") or "")).strip()

        if q.get("mode") == "range":
            start_d = q.get("start_date")
            if not isinstance(start_d, dt_date):
                start_d = base_d
            days_i = _safe_int(q.get("days"), 3)
            if days_i < 1:
                days_i = 1
            if days_i > 7:
                days_i = 7
            summary = _summarise_weather_range(fc, start_d, days_i, tzinfo)
            head = "（" + eid + "）"
            if label:
                final = head + label + "天气：" + summary
            else:
                final = head + "未来" + str(days_i) + "天天气：" + summary
            return {"ok": True, "route_type": "structured_weather", "final": final, "data": rr}

        off = _safe_int(q.get("offset"), 0)
        td = q.get("target_date")
        if not isinstance(td, dt_date):
            td = base_d
            try:
                from datetime import timedelta
                td = base_d + timedelta(days=off)
            except Exception:
                td = base_d

        it = _pick_daily_forecast_by_local_date(fc, td, tzinfo)
        head = "（" + eid + "）"
        if it is None:
            final = head + (label + "天气：无预报。" if label else "天气：无预报。")
        else:
            final = head + (label + "天气：" if label else "天气：") + _summarise_weather_item(it)
        return {"ok": True, "route_type": "structured_weather", "final": final, "data": rr}

    # calendar
    if _is_calendar_query(user_text):
        cal = str(os.environ.get("HA_DEFAULT_CALENDAR_ENTITY") or "").strip()
        if not cal:
            return {"ok": True, "route_type": "structured_calendar", "final": "未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY。", "error": "missing_default_calendar_entity"}
        tzinfo = _tzinfo()
        now = _now_local()
        base_d = dt_date(now.year, now.month, now.day)

        q = _calendar_range_from_text(user_text, now_local=now)
        mode = q.get("mode") or "single"
        label = str((q.get("label") or "")).strip()

        if mode == "range":
            start_d = q.get("start_date")
            end_d = q.get("end_date")
            if not isinstance(start_d, dt_date):
                start_d = base_d

            if isinstance(end_d, dt_date):
                try:
                    from datetime import timedelta
                    end_excl = end_d + timedelta(days=1)
                except Exception:
                    end_excl = end_d
                s_iso, _ = _iso_day_start_end(start_d, tzinfo)
                e_iso, _ = _iso_day_start_end(end_excl, tzinfo)
            else:
                days_i = _safe_int(q.get("days"), 3)
                if days_i < 1:
                    days_i = 1
                if days_i > 14:
                    days_i = 14
                try:
                    from datetime import timedelta
                    end_excl_d = start_d + timedelta(days=days_i)
                except Exception:
                    end_excl_d = start_d
                s_iso, _ = _iso_day_start_end(start_d, tzinfo)
                e_iso, _ = _iso_day_start_end(end_excl_d, tzinfo)

            rr = ha_calendar_events(cal, s_iso, e_iso)
            if not rr.get("ok"):
                return {"ok": True, "route_type": "structured_calendar", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
            ev = rr.get("data") if isinstance(rr.get("data"), list) else []
            head = (label + "有 " + str(len(ev)) + " 条日程：" if label else "共有 " + str(len(ev)) + " 条日程：")
            final = head + _summarise_calendar_events(ev)
            return {"ok": True, "route_type": "structured_calendar", "final": final, "data": rr, "range": {"start": s_iso, "end": e_iso}}

        td = q.get("target_date")
        if not isinstance(td, dt_date):
            off = _safe_int(q.get("offset"), 0)
            try:
                from datetime import timedelta
                td = base_d + timedelta(days=off)
            except Exception:
                td = base_d
        s_iso, e_iso = _iso_day_start_end(td, tzinfo)
        rr = ha_calendar_events(cal, s_iso, e_iso)
        if not rr.get("ok"):
            return {"ok": True, "route_type": "structured_calendar", "final": "我现在联网查询失败了，请稍后再试。", "data": rr}
        ev = rr.get("data") if isinstance(rr.get("data"), list) else []
        if len(ev) == 0:
            final = (label + "没有日程。" if label else "没有日程。")
        else:
            final = (label + "有 " + str(len(ev)) + " 条日程：" if label else "有 " + str(len(ev)) + " 条日程：") + _summarise_calendar_events(ev)
        return {"ok": True, "route_type": "structured_calendar", "final": final, "data": rr, "range": {"start": s_iso, "end": e_iso}}

    return {"ok": True, "route_type": "open_domain", "final": "", "hint": "Not a Structured request."}

@mcp.tool(description="(Debug) Return enabled tools and key env configuration for self-check.")
def tools_selfcheck() -> dict:
    out = {
        "ok": True,
        "service": "mcp-hello",
        "port": os.environ.get("PORT") or os.environ.get("MCP_PORT") or "19090",
        "TZ": os.environ.get("TZ") or "",
        "HA_BASE_URL": os.environ.get("HA_BASE_URL") or "",
        "HA_DEFAULT_WEATHER_ENTITY": os.environ.get("HA_DEFAULT_WEATHER_ENTITY") or "",
        "HA_DEFAULT_CALENDAR_ENTITY": os.environ.get("HA_DEFAULT_CALENDAR_ENTITY") or "",
        "note": "If container shows Restarting (0), app.py had no __main__/server entrypoint.",
    }
    return out

def _build_asgi_app_from_mcp():
    try:
        a = getattr(mcp, "app", None)
        if a is not None:
            return a
    except Exception:
        pass
    for nm in ["asgi_app", "get_asgi_app", "sse_app", "get_app", "create_app"]:
        try:
            fn = getattr(mcp, nm, None)
            if fn is None:
                continue
            if callable(fn):
                try:
                    return fn()
                except TypeError:
                    return fn
        except Exception:
            continue
    return None

if __name__ == "__main__":
    host = os.environ.get("HOST") or "0.0.0.0"
    port = _safe_int(os.environ.get("PORT") or os.environ.get("MCP_PORT") or "19090", 19090)

    try:
        runner = getattr(mcp, "run", None)
        if callable(runner):
            try:
                runner(host=host, port=port)
                raise SystemExit(0)
            except TypeError:
                runner()
                raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        pass

    asgi = _build_asgi_app_from_mcp()
    if asgi is None:
        raise RuntimeError("Cannot build ASGI app from FastMCP. FastMCP API mismatch.")
    import uvicorn
    uvicorn.run(asgi, host=host, port=port)
'''

def main():
    s = io.open(APP, "r", encoding="utf-8").read()
    if MARK in s:
        print("already_patched=1")
        return

    add = ADD_TEMPLATE.replace(PLACEHOLDER, MARK)

    bak = APP + ".bak.entrypoint_route_v2"
    shutil.copy2(APP, bak)

    out = s.rstrip() + "\n\n" + add.lstrip("\n")
    io.open(APP, "w", encoding="utf-8").write(out)
    print("patched_ok=1")
    print("backup=" + bak)

if __name__ == "__main__":
    main()
