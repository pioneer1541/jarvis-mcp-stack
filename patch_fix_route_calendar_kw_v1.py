import re

p = "app.py"
s = open(p, "r", encoding="utf-8").read()
orig = s

# 定位 _route_type 函数块并替换（用宽松匹配）
m = re.search(r"(?ms)^def _route_type\(user_text: str\) -> str:\n.*?\n(?=^def _summarise_daily_forecast|^def _calendar_range_from_text|\Z)", s)
if not m:
    raise RuntimeError("cannot find _route_type function block")

new_block = '''
def _route_type(user_text: str) -> str:
    t = (user_text or "").strip().lower()

    # Structured: holiday
    if ("public holiday" in t) or ("holiday" in t) or ("假日" in t) or ("假期" in t) or ("公众假期" in t) or ("公休" in t) or ("维州" in t and "假" in t):
        return "structured_holiday"

    # Structured: calendar (support 日程/安排/提醒/事件/会议)
    # Output wording uses "日程", but recognition keeps compatible keywords.
    if ("calendar" in t) or ("日程" in t) or ("行程" in t) or ("安排" in t) or ("提醒" in t) or ("事件" in t) or ("会议" in t):
        return "structured_calendar"

    # Structured: weather
    if ("weather" in t) or ("forecast" in t) or ("天气" in t) or ("预报" in t) or ("气温" in t) or ("下雨" in t) or ("温度" in t) or ("风" in t and "速" in t):
        return "structured_weather"

    # Structured: direct entity state query
    if _looks_like_entity_id(t):
        return "structured_state"

    return "open_domain"
'''.strip() + "\n\n"

s2 = s[:m.start()] + new_block + s[m.end():]
if s2 == orig:
    raise RuntimeError("no changes applied")

open(p, "w", encoding="utf-8").write(s2)
print("patched_ok=1")
