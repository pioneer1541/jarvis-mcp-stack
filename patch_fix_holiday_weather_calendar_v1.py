#!/usr/bin/env python3
# coding: utf-8

import os
import re
import time


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path, s):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)


def _backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak." + ts
    with open(bak, "w", encoding="utf-8") as f:
        f.write(_read(path))
    return bak


def _find_def_block(s, func_name):
    # Find a top-level "def func_name(...):" block, return (start, end) slice indices.
    # End is next top-level "def " or EOF.
    m = re.search(r"(?m)^(def[ \t]+%s[ \t]*\([^)]*\)[ \t]*:[ \t]*\n)" % re.escape(func_name), s)
    if not m:
        return None
    start = m.start(1)
    # next top-level def
    m2 = re.search(r"(?m)^def[ \t]+\w+[ \t]*\([^)]*\)[ \t]*:[ \t]*\n", s[m.end(1):])
    if not m2:
        end = len(s)
    else:
        end = m.end(1) + m2.start(0)
    return (start, end)


def _replace_def_block(s, func_name, new_block):
    rng = _find_def_block(s, func_name)
    if not rng:
        return (s, False)
    a, b = rng
    return (s[:a] + new_block.rstrip() + "\n\n" + s[b:].lstrip(), True)


def _insert_before_route_request(s, code_block):
    # Insert before first top-level def route_request(
    m = re.search(r"(?m)^def[ \t]+route_request[ \t]*\(", s)
    if not m:
        return (s, False)
    idx = m.start(0)
    return (s[:idx] + code_block.rstrip() + "\n\n" + s[idx:], True)


def _fix_empty_try_in_holiday_next(s):
    # Fix the exact pattern user showed:
    #   try:
    #   except Exception:
    #       return {"ok": False}
    # We'll remove the empty try/except entirely.
    pat = r"(?ms)^([ \t]*def[ \t]+_holiday_next_from_list\([^\n]*\):\n)(.*?)(\n[ \t]*try:\n[ \t]*except[ \t]+Exception:\n[ \t]*return[ \t]+\{[^\n]*\}\n)(.*)$"
    m = re.search(pat, s)
    if not m:
        return (s, False)
    head = m.group(1)
    body_before = m.group(2)
    body_after = m.group(4)
    # remove the empty try/except chunk
    out = head + body_before + "\n" + body_after
    return (out, True)


def _strip_local_date_import_in_route_request(s):
    # Remove "from datetime import ... date ..." inside route_request to prevent UnboundLocalError.
    # We do a conservative approach: only inside route_request block.
    m = re.search(r"(?m)^def[ \t]+route_request[ \t]*\(", s)
    if not m:
        return (s, False)
    start = m.start(0)
    # end at next top-level def
    m2 = re.search(r"(?m)^def[ \t]+\w+[ \t]*\(", s[m.end(0):])
    end = len(s) if not m2 else (m.end(0) + m2.start(0))
    block = s[start:end]

    changed = False

    # remove any line like: from datetime import datetime, date, timedelta
    def _rm(line):
        nonlocal changed
        changed = True
        return ""

    block2 = re.sub(r"(?m)^[ \t]*from[ \t]+datetime[ \t]+import[^\n]*\bdate\b[^\n]*\n", _rm, block)

    if not changed:
        return (s, False)
    return (s[:start] + block2 + s[end:], True)


NEW_WEATHER_RANGE_FUNC = r'''
def _weather_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse user text into a weather query:
      - single day: today/tomorrow/day after tomorrow/explicit date
      - range: next N days / explicit date range
    Return dict:
      {"mode":"single","offset":int,"label":str}
      {"mode":"single","target_date": datetime.date, "label":str}
      {"mode":"range","start_date": datetime.date, "days":int, "label":str}
    """
    out = {"mode": "single", "offset": 0, "label": ""}
    t = str(text or "").strip()

    # Normalize spaces
    t2 = re.sub(r"\s+", " ", t)

    # Date range: YYYY-MM-DD 到 YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|\-)\s*(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            from datetime import date as _date
            s1 = m.group(1)
            s2 = m.group(3)
            d1 = _dt.fromisoformat(s1).date()
            d2 = _dt.fromisoformat(s2).date()
            if d2 >= d1:
                days = (d2 - d1).days + 1
                if days < 1:
                    days = 1
                out = {"mode": "range", "start_date": d1, "days": int(days), "label": s1 + "到" + s2}
                return out
        except Exception:
            pass

    # Single explicit: YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(m.group(1)).date()
            out = {"mode": "single", "target_date": d, "label": m.group(1)}
            return out
        except Exception:
            pass

    # "1月26日" (assume current year)
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", t2)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            from datetime import date as _date
            if now_local is not None and hasattr(now_local, "year"):
                yy = int(getattr(now_local, "year"))
            else:
                from datetime import datetime as _dt
                yy = int(_dt.now().year)
            d = _date(yy, mm, dd)
            out = {"mode": "single", "target_date": d, "label": str(mm) + "月" + str(dd) + "日"}
            return out
        except Exception:
            pass

    # Next N days: 接下来N天 / 未来N天 / 接下來N天 / 未來N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t2)
    if m:
        try:
            n = int(m.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        out = {"mode": "range", "days": int(n), "label": m.group(1) + str(n) + "天"}
        return out

    # Relative days
    if ("大后天" in t2) or ("大後天" in t2):
        return {"mode": "single", "offset": 3, "label": "大后天"}
    if ("后天" in t2) or ("後天" in t2):
        return {"mode": "single", "offset": 2, "label": "后天"}
    if ("明天" in t2):
        return {"mode": "single", "offset": 1, "label": "明天"}
    if ("今天" in t2) or ("今日" in t2):
        return {"mode": "single", "offset": 0, "label": "今天"}

    return out
'''.strip()


NEW_CAL_RANGE_FUNC = r'''
def _calendar_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse user text into calendar query range.
    Return:
      {"mode":"single","offset":int,"label":str}
      {"mode":"single","target_date": date, "label":str}
      {"mode":"range","start_date": date, "days":int, "label":str}
      {"mode":"range","start_date": date, "end_date": date, "label":str}
    """
    out = {"mode": "single", "offset": 0, "label": ""}
    t = str(text or "").strip()
    t2 = re.sub(r"\s+", " ", t)

    # YYYY-MM-DD 到 YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|\-)\s*(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d1 = _dt.fromisoformat(m.group(1)).date()
            d2 = _dt.fromisoformat(m.group(3)).date()
            if d2 >= d1:
                return {"mode": "range", "start_date": d1, "end_date": d2, "label": m.group(1) + "到" + m.group(3)}
        except Exception:
            pass

    # YYYY-MM-DD
    m = re.search(r"(\d{4}-\d{2}-\d{2})", t2)
    if m:
        try:
            from datetime import datetime as _dt
            d = _dt.fromisoformat(m.group(1)).date()
            return {"mode": "single", "target_date": d, "label": m.group(1)}
        except Exception:
            pass

    # 1月26日
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", t2)
    if m:
        try:
            mm = int(m.group(1))
            dd = int(m.group(2))
            from datetime import date as _date
            if now_local is not None and hasattr(now_local, "year"):
                yy = int(getattr(now_local, "year"))
            else:
                from datetime import datetime as _dt
                yy = int(_dt.now().year)
            d = _date(yy, mm, dd)
            return {"mode": "single", "target_date": d, "label": str(mm) + "月" + str(dd) + "日"}
        except Exception:
            pass

    # 接下来N天/未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t2)
    if m:
        try:
            n = int(m.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        return {"mode": "range", "days": int(n), "label": m.group(1) + str(n) + "天"}

    if ("大后天" in t2) or ("大後天" in t2):
        return {"mode": "single", "offset": 3, "label": "大后天"}
    if ("后天" in t2) or ("後天" in t2):
        return {"mode": "single", "offset": 2, "label": "后天"}
    if ("明天" in t2):
        return {"mode": "single", "offset": 1, "label": "明天"}
    if ("今天" in t2) or ("今日" in t2):
        return {"mode": "single", "offset": 0, "label": "今天"}

    return out
'''.strip()


def main():
    path = "app.py"
    if not os.path.exists(path):
        raise RuntimeError("app.py not found in current dir")

    bak = _backup(path)
    s = _read(path)

    changed_any = False

    s2, ok = _fix_empty_try_in_holiday_next(s)
    if ok:
        s = s2
        changed_any = True

    s2, ok = _strip_local_date_import_in_route_request(s)
    if ok:
        s = s2
        changed_any = True

    # Replace or insert parsers
    s2, ok = _replace_def_block(s, "_weather_range_from_text", NEW_WEATHER_RANGE_FUNC)
    if ok:
        s = s2
        changed_any = True
    else:
        s2, ok2 = _insert_before_route_request(s, NEW_WEATHER_RANGE_FUNC)
        if ok2:
            s = s2
            changed_any = True

    s2, ok = _replace_def_block(s, "_calendar_range_from_text", NEW_CAL_RANGE_FUNC)
    if ok:
        s = s2
        changed_any = True
    else:
        s2, ok2 = _insert_before_route_request(s, NEW_CAL_RANGE_FUNC)
        if ok2:
            s = s2
            changed_any = True

    if not changed_any:
        print("No changes applied. Backup:", bak)
        return

    _write(path, s)
    print("Patched OK. Backup:", bak)


if __name__ == "__main__":
    main()
