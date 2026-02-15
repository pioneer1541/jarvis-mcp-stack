import io
import os
from datetime import datetime

APP = "app.py"

def _replace_block(src: str, start_mark: str, end_mark: str, new_block: str) -> str:
    a = src.find(start_mark)
    if a < 0:
        raise RuntimeError("cannot find start_mark: " + start_mark)
    b = src.find(end_mark, a)
    if b < 0:
        raise RuntimeError("cannot find end_mark: " + end_mark)
    return src[:a] + new_block + src[b:]

def main():
    with io.open(APP, "r", encoding="utf-8") as f:
        s = f.read()

    # 1) Replace _weather_range_from_text() entirely (fix offset handling + regex)
    start_mark = "def _weather_range_from_text(text: str, now_local: object = None) -> dict:\n"
    end_mark = "\ndef _pick_daily_forecast_by_local_date("
    new_weather_func = """def _weather_range_from_text(text: str, now_local: object = None) -> dict:
    \"""
    Parse weather time range intent from free text.

    Returns:
      {mode: "single", offset: int, label: str}
      {mode: "range", start_date: date, end_date: date, days: int, label: str}
    \"""
    t = str(text or "").strip()
    low = t.lower()

    now = now_local
    try:
        if now is None:
            now = _now_local()
    except Exception:
        now = _now_local()

    tz = getattr(now, "tzinfo", None)
    base_d = dt_date(now.year, now.month, now.day)

    # --- relative day ---
    if ("明天" in t) or ("tomorrow" in low):
        return {"mode": "single", "offset": 1, "label": "明天"}
    if ("后天" in t):
        return {"mode": "single", "offset": 2, "label": "后天"}
    if ("今天" in t) or ("today" in low) or ("今天天气" in t):
        return {"mode": "single", "offset": 0, "label": "今天"}

    # --- next N days ---
    m_nd = re.search(r"(接下来|接下來|未来|未來)\\s*(\\d{1,2})\\s*天", t)
    if m_nd:
        try:
            n = int(m_nd.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        if n > 5:
            n = 5
        return {"mode": "range", "start_date": base_d, "days": n, "label": "未来" + str(n) + "天"}

    m_nd2 = re.search(r"next\\s*(\\d{1,2})\\s*days", low)
    if m_nd2:
        try:
            n = int(m_nd2.group(1))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        if n > 5:
            n = 5
        return {"mode": "range", "start_date": base_d, "days": n, "label": "next " + str(n) + " days"}

    # --- explicit date / date range ---
    def _safe_date(y, m, d):
        try:
            return dt_date(int(y), int(m), int(d))
        except Exception:
            return None

    def _collect_dates(txt0: str):
        out = []
        # YYYY-MM-DD / YYYY/MM/DD / YYYY.MM.DD
        for m in re.finditer(r"(19\\d{2}|20\\d{2})\\s*[-/\\.]\\s*(\\d{1,2})\\s*[-/\\.]\\s*(\\d{1,2})", txt0):
            dd = _safe_date(m.group(1), m.group(2), m.group(3))
            if dd:
                out.append(dd)

        # DD-MM-YYYY
        for m in re.finditer(r"(\\d{1,2})\\s*[-/\\.]\\s*(\\d{1,2})\\s*[-/\\.]\\s*(19\\d{2}|20\\d{2})", txt0):
            dd = _safe_date(m.group(3), m.group(2), m.group(1))
            if dd:
                out.append(dd)

        # Chinese: (YYYY年)?M月D日
        for m in re.finditer(r"(?:(19\\d{2}|20\\d{2})\\s*年\\s*)?(\\d{1,2})\\s*月\\s*(\\d{1,2})\\s*[日号]?", txt0):
            yy = m.group(1) or str(base_d.year)
            dd = _safe_date(yy, m.group(2), m.group(3))
            if dd:
                out.append(dd)

        out2 = []
        seen = set()
        for d0 in sorted(out):
            if d0 not in seen:
                out2.append(d0)
                seen.add(d0)
        return out2

    ds = _collect_dates(t)

    range_words = ("到" in t) or ("至" in t) or ("~" in t) or ("-" in t)
    if range_words and len(ds) >= 2:
        start_d = ds[0]
        end_d = ds[1]
        if end_d < start_d:
            start_d, end_d = end_d, start_d
        days = (end_d - start_d).days + 1
        if days < 1:
            days = 1
        if days > 5:
            days = 5
            end_d = start_d + dt_timedelta(days=days - 1)
        return {"mode": "range", "start_date": start_d, "end_date": end_d, "days": days, "label": str(start_d) + "到" + str(end_d)}

    if len(ds) >= 1:
        td = ds[0]
        label = str(td)
        if td == base_d:
            label = "今天"
        return {"mode": "single", "target_date": td, "offset": 0, "label": label}

    return {"mode": "single", "offset": 0, "label": "今天"}
"""
    s = _replace_block(s, start_mark, end_mark, new_weather_func + end_mark)

    # 2) Remove duplicated old structured_weather hard-gate block (prevents future confusion)
    hard_start = "# Hard gate: Structured routes must NOT call web_answer/open_url."
    hard_end = 'if rt == "structured_holiday":'
    hs = s.find(hard_start)
    if hs >= 0:
        he = s.find(hard_end, hs)
        if he < 0:
            raise RuntimeError("cannot find end of hard gate block: " + hard_end)
        s = s[:hs] + hard_end + "\n" + s[he + len(hard_end) + 1:]

    # 3) Fix calendar regex in route_request (\\d -> \\d)
    s = s.replace(r're.search(r"(\\d{4})[\\-/](\\d{1,2})[\\-/](\\d{1,2})"', r're.search(r"(\d{4})[\-/](\d{1,2})[\-/](\d{1,2})"')
    s = s.replace(r're.search(r"(\\d{1,2})\\s*月\\s*(\\d{1,2})\\s*[日号]?"', r're.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?"')
    s = s.replace(r're.search(r"(接下来|接下來|未来|未來)\\s*(\\d{1,2})\\s*天"', r're.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天"')

    # 4) Make weather route's isinstance check robust (avoid any future shadowing)
    s = s.replace("isinstance(start_d, date)", "isinstance(start_d, dt_date)")
    s = s.replace("isinstance(end_d, date)", "isinstance(end_d, dt_date)")
    s = s.replace("isinstance(target_d, date)", "isinstance(target_d, dt_date)")

    with io.open(APP, "w", encoding="utf-8") as f:
        f.write(s)

    print("patched_ok=1")

if __name__ == "__main__":
    main()
