from pathlib import Path

p = Path("app.py")
s = p.read_text(encoding="utf-8")

# already patched?
if 'if rt == "structured_weather":' in s:
    print("already_has_structured_weather=1")
    raise SystemExit(0)

anchor = '    # Hard gate: Structured routes must NOT call web_answer/open_url\n'
pos_anchor = s.find(anchor)
if pos_anchor < 0:
    raise RuntimeError("cannot find anchor comment in route_request()")

pos_holiday = s.find('    if rt == "structured_holiday":', pos_anchor)
if pos_holiday < 0:
    raise RuntimeError("cannot find structured_holiday branch after anchor")

block = (
    '    if rt == "structured_weather":\n'
    '        default_weather = os.getenv("HA_DEFAULT_WEATHER_ENTITY", "") or ""\n'
    '        if not default_weather:\n'
    '            return {\n'
    '                "ok": True,\n'
    '                "route_type": rt,\n'
    '                "final": "未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY，或直接用 ha_weather_forecast(entity_id,type) 调用。",\n'
    '                "error": "missing_default_weather_entity",\n'
    '            }\n'
    '\n'
    '        r = ha_weather_forecast(default_weather, "daily", 12)\n'
    '        if not r.get("ok"):\n'
    '            return {"ok": True, "route_type": rt, "final": "无法获取天气预报。", "data": r, "entity_id": default_weather}\n'
    '\n'
    '        s2 = _summarise_daily_forecast(r.get("forecast") or [])\n'
    '        final = "（" + default_weather + "）" + s2\n'
    '        return {"ok": True, "route_type": rt, "final": final, "data": r}\n'
    '\n'
)

s2 = s[:pos_holiday] + block + s[pos_holiday:]
p.write_text(s2, encoding="utf-8")
print("patched_ok=1")
