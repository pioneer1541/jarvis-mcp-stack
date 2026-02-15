import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()

# find calendar branch start
m1 = re.search(r'(?m)^ {4}if rt == "structured_calendar":\s*$', s)
if not m1:
    raise RuntimeError("cannot find: if rt == \"structured_calendar\": (indent=4)")

# find next structured_state branch start (as end anchor)
m2 = re.search(r'(?m)^ {4}if rt == "structured_state":\s*$', s[m1.end():])
if not m2:
    raise RuntimeError("cannot find: if rt == \"structured_state\": after structured_calendar")

start = m1.start()
end = m1.end() + m2.start()  # end right before structured_state line

new_block = '''
    if rt == "structured_calendar":
        default_cal = os.getenv("HA_DEFAULT_CALENDAR_ENTITY", "") or ""
        if not default_cal:
            return {
                "ok": True,
                "route_type": rt,
                "final": "未配置默认日程实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。",
                "error": "missing_default_calendar_entity",
            }

        rng = _calendar_range_from_text(user_text)
        r = ha_calendar_events(default_cal, rng.get("start") or "", rng.get("end") or "", 12)
        if not r.get("ok"):
            return {"ok": True, "route_type": rt, "final": "无法获取日程。", "data": r, "entity_id": default_cal}

        items = r.get("data") or []
        if not isinstance(items, list):
            items = []

        # sort: timed events first (by start datetime), then all-day
        def _sort_key(ev: dict):
            try:
                st = ev.get("start") or {}
                if isinstance(st, dict) and st.get("dateTime"):
                    return (0, str(st.get("dateTime")))
                if isinstance(st, dict) and st.get("date"):
                    return (1, str(st.get("date")))
            except Exception:
                pass
            return (2, "")

        try:
            items = sorted([x for x in items if isinstance(x, dict)], key=_sort_key)
        except Exception:
            # if sort fails, keep original filtered list
            try:
                items = [x for x in items if isinstance(x, dict)]
            except Exception:
                items = []

        # Label: 今天/明天/日期
        label = ""
        try:
            start_date = str(rng.get("start") or "")[:10]
            now_d = _now_local().date()
            if start_date:
                y = int(start_date[0:4])
                mo = int(start_date[5:7])
                da = int(start_date[8:10])
                sd = date(y, mo, da)
                if sd == now_d:
                    label = "今天"
                elif sd == (now_d + timedelta(days=1)):
                    label = "明天"
                else:
                    label = start_date
        except Exception:
            label = ""

        n = len(items)
        if n == 0:
            final = (label + "没有日程。") if label else "没有日程。"
            return {"ok": True, "route_type": rt, "final": final, "data": r, "range": rng}

        def _fmt_time(ev: dict) -> str:
            try:
                st = ev.get("start") or {}
                if isinstance(st, dict) and ("dateTime" in st) and st.get("dateTime"):
                    dt = datetime.fromisoformat(str(st.get("dateTime")))
                    try:
                        dt = dt.astimezone(ZoneInfo(_tz_name()))
                    except Exception:
                        pass
                    return dt.strftime("%H:%M")
                if isinstance(st, dict) and ("date" in st) and st.get("date"):
                    return "全天"
            except Exception:
                pass
            return ""

        lines_out = []
        for ev in items[:3]:
            if not isinstance(ev, dict):
                continue
            t = _fmt_time(ev)
            title = str(ev.get("summary") or "").strip()
            loc = str(ev.get("location") or "").strip()
            if not title:
                title = "（未命名日程）"
            if loc:
                one = (t + " " + title + "（" + loc + "）").strip()
            else:
                one = (t + " " + title).strip()
            lines_out.append(one)

        prefix = (label + "有 " + str(n) + " 条日程：") if label else ("共有 " + str(n) + " 条日程：")
        final = prefix + "；".join(lines_out) + "。"
        if n > 3:
            final = final + "其余已省略。"

        return {"ok": True, "route_type": rt, "final": final, "data": r, "range": rng}

'''.lstrip("\n")

s2 = s[:start] + new_block + s[end:]
open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
