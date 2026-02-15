import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# --- 1) Replace _summarise_daily_forecast to be more human ---
pat_fc = r"(?ms)^def _summarise_daily_forecast\(fc: list\) -> str:\n.*?\n(?=^def _calendar_range_from_text|\Z)"
m = re.search(pat_fc, s)
if not m:
    raise RuntimeError("cannot find _summarise_daily_forecast function")

new_fc = '''
def _summarise_daily_forecast(fc: list) -> str:
    if not isinstance(fc, list) or (len(fc) == 0):
        return "暂无可用的天气预报数据。"
    x = fc[0] if isinstance(fc[0], dict) else {}
    cond = str(x.get("condition") or "").strip()

    t_hi = x.get("temperature")
    t_lo = x.get("templow")
    rain = x.get("precipitation")
    wind = x.get("wind_speed")

    parts = []

    # condition (keep raw token, but in Chinese skeleton)
    if cond:
        parts.append("天气: " + cond)

    # temperature
    if (t_hi is not None) and (t_lo is not None):
        parts.append("最高/最低: " + str(t_hi) + "°C / " + str(t_lo) + "°C")
    elif t_hi is not None:
        parts.append("温度: " + str(t_hi) + "°C")

    # precipitation (human)
    if rain is not None:
        try:
            rv = float(rain)
            if rv <= 0.0:
                parts.append("预计无降雨")
            else:
                parts.append("预计降雨: " + str(rain))
        except Exception:
            parts.append("预计降雨: " + str(rain))

    # wind (human bands)
    if wind is not None:
        try:
            wv = float(wind)
            if wv < 10:
                parts.append("微风（约 " + str(wind) + "）")
            elif wv < 20:
                parts.append("有风（约 " + str(wind) + "）")
            else:
                parts.append("风较大（约 " + str(wind) + "）")
        except Exception:
            parts.append("风速: " + str(wind))

    if not parts:
        return "已获取天气预报。"
    return "，".join(parts) + "。"
'''.strip() + "\n\n"

s = s[:m.start()] + new_fc + s[m.end():]

# --- 2) Improve calendar ordering inside route_request structured_calendar branch ---
# We look for "for ev in items[:3]:" and add sort before it.
# Insert a sort block after items is normalized to list.
needle = r'(?ms)(items = r\.get\("data"\) or \[\]\n[ \t]*if not isinstance\(items, list\):\n[ \t]*    items = \[\]\n)'
m2 = re.search(needle, s)
if not m2:
    raise RuntimeError("cannot find calendar items normalization block to insert sort")

sort_block = m2.group(1) + r'''
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
        pass

'''
s = s[:m2.start()] + sort_block + s[m2.end():]

if s == orig:
    raise RuntimeError("no changes applied")

open(p, "w", encoding="utf-8").write(s)
print("patched_ok=1")
