import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# ---- 1) Ensure imports we need ----
# We need: timedelta, date and ZoneInfo
# Replace: from datetime import datetime
# With:    from datetime import datetime, timedelta, date
s = re.sub(r"(?m)^from datetime import datetime\s*$", "from datetime import datetime, timedelta, date", s)

# Add zoneinfo import if missing
if re.search(r"(?m)^from zoneinfo import ZoneInfo\s*$", s) is None:
    # insert after typing import line
    m = re.search(r"(?m)^from typing import Any, Dict, List, Optional\s*$", s)
    if m:
        insert_pos = m.end()
        s = s[:insert_pos] + "\n\nfrom zoneinfo import ZoneInfo" + s[insert_pos:]
    else:
        # fallback: after first import block
        s = "from zoneinfo import ZoneInfo\n" + s

# ---- 2) Insert Router tool block after holiday_vic() block ----
if "def route_request(" not in s:
    anchor = re.search(r"(?ms)@mcp\.tool\(description=\"\(Structured\) Public holidays for Victoria, Australia\.[^\n]*\ndef holiday_vic\([^\)]*\)\s*->\s*dict:\n.*?\n(?=^[ \t]*# ----|^[ \t]*@mcp\.tool|^\Z)", s)
    if not anchor:
        raise RuntimeError("Cannot find holiday_vic block to anchor insertion.")

    insert_at = anchor.end()

    router_block = r'''

# ---- Router: route user requests by information shape (Structured / Retrieval / Open-domain) ----
def _tz_name() -> str:
    tz = os.getenv("TZ", "") or "Australia/Melbourne"
    return tz

def _now_local() -> datetime:
    try:
        return datetime.now(ZoneInfo(_tz_name()))
    except Exception:
        return datetime.now()

def _iso_local(d: datetime) -> str:
    try:
        if d.tzinfo is None:
            d = d.replace(tzinfo=ZoneInfo(_tz_name()))
    except Exception:
        pass
    try:
        return d.isoformat()
    except Exception:
        # very defensive
        return str(d)

def _extract_year(text: str, default_year: int) -> int:
    t = text or ""
    m = re.search(r"(19|20)\d{2}", t)
    if not m:
        return int(default_year)
    try:
        y = int(m.group(0))
        return y
    except Exception:
        return int(default_year)

def _looks_like_entity_id(text: str) -> bool:
    # simple HA entity_id: domain.object_id
    t = (text or "").strip()
    if not t:
        return False
    return re.match(r"^[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+$", t) is not None

def _route_type(user_text: str) -> str:
    t = (user_text or "").strip().lower()

    # Structured: holiday
    if ("public holiday" in t) or ("holiday" in t) or ("假日" in t) or ("假期" in t) or ("公众假期" in t) or ("公休" in t) or ("维州" in t and "假" in t):
        return "structured_holiday"

    # Structured: calendar
    if ("calendar" in t) or ("日程" in t) or ("会议" in t) or ("安排" in t) or ("下一个" in t and "会" in t) or ("今天" in t and ("安排" in t or "日程" in t)):
        return "structured_calendar"

    # Structured: weather
    if ("weather" in t) or ("forecast" in t) or ("天气" in t) or ("预报" in t) or ("气温" in t) or ("下雨" in t) or ("温度" in t) or ("风" in t and "速" in t):
        return "structured_weather"

    # Structured: direct entity state query
    if _looks_like_entity_id(t):
        return "structured_state"

    return "open_domain"

def _summarise_daily_forecast(fc: list) -> str:
    if not isinstance(fc, list) or (len(fc) == 0):
        return "暂无可用的天气预报数据。"
    x = fc[0] if isinstance(fc[0], dict) else {}
    cond = str(x.get("condition") or "")
    t_hi = x.get("temperature")
    t_lo = x.get("templow")
    rain = x.get("precipitation")
    wind = x.get("wind_speed")
    parts = []
    if cond:
        parts.append("天气: " + cond)
    if (t_hi is not None) and (t_lo is not None):
        parts.append("最高/最低: " + str(t_hi) + "°C / " + str(t_lo) + "°C")
    elif t_hi is not None:
        parts.append("温度: " + str(t_hi) + "°C")
    if rain is not None:
        parts.append("降雨: " + str(rain))
    if wind is not None:
        parts.append("风速: " + str(wind))
    if not parts:
        return "已获取天气预报。"
    return "，".join(parts) + "。"

def _calendar_range_from_text(t: str) -> dict:
    # minimal: today/tomorrow/this week
    now = _now_local()
    text = (t or "").lower()

    # default: today
    start = datetime(now.year, now.month, now.day, 0, 0, 0, tzinfo=now.tzinfo)
    end = start + timedelta(days=1)

    if ("tomorrow" in text) or ("明天" in text):
        start = start + timedelta(days=1)
        end = start + timedelta(days=1)
    elif ("next week" in text) or ("下周" in text):
        # next Monday -> Monday+7
        # weekday: Monday=0
        wd = start.weekday()
        start = start - timedelta(days=wd) + timedelta(days=7)
        end = start + timedelta(days=7)
    elif ("this week" in text) or ("本周" in text) or ("这周" in text):
        wd = start.weekday()
        start = start - timedelta(days=wd)
        end = start + timedelta(days=7)

    return {"start": _iso_local(start), "end": _iso_local(end)}

@mcp.tool(description="(Router) Route user request by info shape. For Structured (weather/calendar/holiday/state), returns structured result without using web.")
def route_request(text: str) -> dict:
    user_text = (text or "").strip()
    if not user_text:
        return {"ok": False, "error": "empty_text"}

    rt = _route_type(user_text)

    # Hard gate: Structured routes must NOT call web_answer/open_url
    if rt == "structured_holiday":
        y = _extract_year(user_text, int(_now_local().year))
        r = holiday_vic(y)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取维州公众假期。", "data": r}
        final = "已获取维州公众假期（AU-VIC），年份 " + str(r.get("year")) + "，共 " + str(len(r.get("holidays") or [])) + " 天。"
        return {"ok": True, "route_type": rt, "final": final, "data": r}

    if rt == "structured_weather":
        default_eid = os.getenv("HA_DEFAULT_WEATHER_ENTITY", "") or "weather.forecast_home"
        r = ha_weather_forecast(default_eid, "daily", 12)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取天气预报。", "data": r, "entity_id": default_eid}
        summary = _summarise_daily_forecast(r.get("forecast") or [])
        final = "（" + default_eid + "）" + summary
        return {"ok": True, "route_type": rt, "final": final, "data": r}

    if rt == "structured_calendar":
        default_cal = os.getenv("HA_DEFAULT_CALENDAR_ENTITY", "") or ""
        if not default_cal:
            return {
                "ok": True,
                "route_type": rt,
                "final": "未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。",
                "error": "missing_default_calendar_entity",
            }
        rng = _calendar_range_from_text(user_text)
        r = ha_calendar_events(default_cal, rng.get("start") or "", rng.get("end") or "", 12)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取日历事件。", "data": r, "entity_id": default_cal}
        # Minimal summarise
        items = r.get("data") or []
        try:
            n = len(items) if isinstance(items, list) else 0
        except Exception:
            n = 0
        final = "已获取日历事件（" + default_cal + "），区间 " + str(rng.get("start")) + " ~ " + str(rng.get("end")) + "，共 " + str(n) + " 条。"
        return {"ok": True, "route_type": rt, "final": final, "data": r, "range": rng}

    if rt == "structured_state":
        r = ha_get_state(user_text, 10)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取实体状态。", "data": r, "entity_id": user_text}
        st = ""
        try:
            st = str((r.get("data") or {}).get("state") or "")
        except Exception:
            st = ""
        final = "实体 " + user_text + " 状态: " + (st or "unknown") + "。"
        return {"ok": True, "route_type": rt, "final": final, "data": r, "entity_id": user_text}

    # open-domain: do NOT call web_answer here; return hint for upper layer
    return {
        "ok": True,
        "route_type": "open_domain",
        "final": "",
        "hint": "Not a Structured request. Use web_answer (or other retrieval) at the next step if needed.",
    }

'''
    s = s[:insert_at] + router_block + s[insert_at:]

# ---- 3) Update tools_selfcheck fallback list to include route_request ----
# Only touch the fallback list inside tools_selfcheck if present.
if "route_request" not in s:
    s = re.sub(
        r'(?ms)("holiday_vic",\s*\]\s*)',
        '"holiday_vic",\n            "route_request",\n        ]',
        s,
        count=1,
    )

if s == orig:
    raise RuntimeError("No changes applied. Patch may already be present.")

open(p, "w", encoding="utf-8").write(s)
print("patched_ok=1")
