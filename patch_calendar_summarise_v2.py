import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# Find start: the line that checks structured_calendar
m_start = re.search(r"(?m)^([ \t]*)(if|elif)[ \t]+rt[ \t]*==[ \t]*['\"]structured_calendar['\"][ \t]*:[ \t]*$", s)
if not m_start:
    raise RuntimeError("cannot find structured_calendar branch")

indent = m_start.group(1)
start_idx = m_start.start()

# Find end: next structured_state branch after start
m_end = re.search(r"(?m)^" + re.escape(indent) + r"(if|elif)[ \t]+rt[ \t]*==[ \t]*['\"]structured_state['\"][ \t]*:[ \t]*$", s[m_start.end():])
if not m_end:
    # fallback: allow different indent for next branch
    m_end2 = re.search(r"(?m)^[ \t]*(if|elif)[ \t]+rt[ \t]*==[ \t]*['\"]structured_state['\"][ \t]*:[ \t]*$", s[m_start.end():])
    if not m_end2:
        raise RuntimeError("cannot find structured_state branch after structured_calendar")
    end_idx = m_start.end() + m_end2.start()
    indent_state = re.match(r"(?m)^([ \t]*)", s[end_idx:]).group(1)
else:
    end_idx = m_start.end() + m_end.start()
    indent_state = indent

# Build new structured_calendar block with the SAME indent
block = r'''
{indent}(if rt == "structured_calendar"):
{indent}    default_cal = os.getenv("HA_DEFAULT_CALENDAR_ENTITY", "") or ""
{indent}    if not default_cal:
{indent}        return {{
{indent}            "ok": True,
{indent}            "route_type": rt,
{indent}            "final": "未配置默认日程实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。",
{indent}            "error": "missing_default_calendar_entity",
{indent}        }}

{indent}    rng = _calendar_range_from_text(user_text)
{indent}    r = ha_calendar_events(default_cal, rng.get("start") or "", rng.get("end") or "", 12)
{indent}    if not r.get("ok"):
{indent}        return {{"ok": True, "route_type": rt, "final": "无法获取日程。", "data": r, "entity_id": default_cal}}

{indent}    items = r.get("data") or []
{indent}    if not isinstance(items, list):
{indent}        items = []

{indent}    # Label: 今天/明天/日期
{indent}    label = ""
{indent}    try:
{indent}        start_date = str(rng.get("start") or "")[:10]
{indent}        now_d = _now_local().date()
{indent}        if start_date:
{indent}            y = int(start_date[0:4]); mo = int(start_date[5:7]); da = int(start_date[8:10])
{indent}            sd = date(y, mo, da)
{indent}            if sd == now_d:
{indent}                label = "今天"
{indent}            elif sd == (now_d + timedelta(days=1)):
{indent}                label = "明天"
{indent}            else:
{indent}                label = start_date
{indent}    except Exception:
{indent}        label = ""

{indent}    n = len(items)

{indent}    if n == 0:
{indent}        final = (label + "没有日程。") if label else "没有日程。"
{indent}        return {{"ok": True, "route_type": rt, "final": final, "data": r, "range": rng}}

{indent}    def _fmt_time(ev: dict) -> str:
{indent}        try:
{indent}            st = ev.get("start") or {{}}
{indent}            if isinstance(st, dict) and ("dateTime" in st) and st.get("dateTime"):
{indent}                dt = datetime.fromisoformat(str(st.get("dateTime")))
{indent}                try:
{indent}                    dt = dt.astimezone(ZoneInfo(_tz_name()))
{indent}                except Exception:
{indent}                    pass
{indent}                return dt.strftime("%H:%M")
{indent}            if isinstance(st, dict) and ("date" in st) and st.get("date"):
{indent}                return "全天"
{indent}        except Exception:
{indent}            pass
{indent}        return ""

{indent}    lines = []
{indent}    for ev in items[:3]:
{indent}        if not isinstance(ev, dict):
{indent}            continue
{indent}        t = _fmt_time(ev)
{indent}        title = str(ev.get("summary") or "").strip()
{indent}        loc = str(ev.get("location") or "").strip()
{indent}        if not title:
{indent}            title = "（未命名日程）"
{indent}        if loc:
{indent}            one = (t + " " + title + "（" + loc + "）").strip()
{indent}        else:
{indent}            one = (t + " " + title).strip()
{indent}        lines.append(one)

{indent}    if label:
{indent}        prefix = label + "有 " + str(n) + " 条日程："
{indent}    else:
{indent}        prefix = "共有 " + str(n) + " 条日程："

{indent}    final = prefix + "；".join(lines) + "。"
{indent}    if n > 3:
{indent}        final = final + "其余已省略。"

{indent}    return {{"ok": True, "route_type": rt, "final": final, "data": r, "range": rng}}
'''.strip("\n").format(indent=indent)

# Replace: from start_idx up to end_idx (exclude structured_state line)
s2 = s[:start_idx] + block + "\n\n" + s[end_idx:]

if s2 == orig:
    raise RuntimeError("no changes applied")

open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
