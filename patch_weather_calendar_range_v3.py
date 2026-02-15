#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import shutil
from datetime import datetime

APP = "app.py"


def _backup(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.range_v3." + ts
    shutil.copy2(path, bak)
    return bak


def _read(path: str) -> str:
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path: str, s: str) -> None:
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(s)


def _replace_top_level_def(s: str, def_name: str, new_block: str) -> str:
    # Replace: def <name>(...) at column 0 until next top-level def/class
    pat = r"(?m)^def\s+" + re.escape(def_name) + r"\s*\(.*?\):\s*\n"
    m = re.search(pat, s)
    if not m:
        raise RuntimeError("cannot find def " + def_name + "()")

    start = m.start()
    # find next top-level def/class after this def
    m2 = re.search(r"(?m)^(def|class)\s+\w+\s*\(", s[m.end():])
    if m2:
        end = m.end() + m2.start()
    else:
        end = len(s)

    return s[:start] + new_block.rstrip() + "\n\n" + s[end:]


def _patch_route_request_date_shadow(s: str) -> str:
    # Avoid: "from datetime import datetime, date, timedelta" inside route_request
    # This can create a local name `date` and cause UnboundLocalError.
    s2 = s

    # only patch the exact import form if present
    s2 = s2.replace(
        "from datetime import datetime, date, timedelta",
        "from datetime import datetime, timedelta\n                from datetime import date as dt_date",
    )
    return s2


def main() -> None:
    if not os.path.exists(APP):
        raise RuntimeError("cannot find " + APP)

    src = _read(APP)
    bak = _backup(APP)

    # --- New helper: weather range parser (returns explicit target_date or range) ---
    new_weather = r'''
def _weather_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse weather time range from Chinese text.
    Return dict:
      - mode: "single" | "range"
      - label: str
      - target_date: datetime.date | None
      - start_date: datetime.date | None
      - end_date: datetime.date | None
      - days: int | None
      - offset: int (kept for compatibility)
    Notes:
      - For "明天/后天", target_date is computed as today + offset (NOT today).
      - For "接下来N天/未来N天/未来几天", returns range with days capped to 5 by caller if desired.
    """
    out = {
        "mode": "single",
        "label": "",
        "target_date": None,
        "start_date": None,
        "end_date": None,
        "days": None,
        "offset": 0,
    }

    def _get_today():
        try:
            if now_local is not None:
                d = now_local.date()
                return d
        except Exception:
            pass
        try:
            return _now_local().date()
        except Exception:
            from datetime import datetime as _dt
            return _dt.now().date()

    def _safe_date(y, m, d):
        try:
            from datetime import date as _date
            return _date(int(y), int(m), int(d))
        except Exception:
            return None

    def _parse_ymd(s):
        ss = str(s or "").strip()
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", ss)
        if not m:
            return None
        return _safe_date(m.group(1), m.group(2), m.group(3))

    def _parse_md(s, year):
        ss = str(s or "").strip()
        m = re.match(r"^(\d{1,2})月(\d{1,2})日?$", ss)
        if not m:
            return None
        return _safe_date(year, m.group(1), m.group(2))

    txt = _ug_clean_unicode(text or "")
    txt = txt.strip()

    today = _get_today()
    year = int(getattr(today, "year", datetime.now().year))

    # 1) range: 接下来N天 / 未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", txt)
    if m:
        out["mode"] = "range"
        out["label"] = m.group(1) + m.group(2) + "天"
        out["start_date"] = today
        try:
            out["days"] = int(m.group(2))
        except Exception:
            out["days"] = 3
        return out

    # range: 未来几天 / 接下来几天
    if re.search(r"(接下来|接下來|未来|未來)\s*几\s*天", txt):
        out["mode"] = "range"
        out["label"] = "未来几天"
        out["start_date"] = today
        out["days"] = 3
        return out

    # 2) explicit date range: A 到 B
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)\s*(到|至|\-)\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)", txt)
    if m:
        a = m.group(1)
        b = m.group(3)
        da = _parse_ymd(a) or _parse_md(a, year)
        db = _parse_ymd(b) or _parse_md(b, year)
        if da and db:
            out["mode"] = "range"
            out["label"] = a + "到" + b
            out["start_date"] = da
            out["end_date"] = db
            try:
                out["days"] = int((db - da).days) + 1
            except Exception:
                out["days"] = None
        return out

    # 3) explicit single date
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)", txt)
    if m:
        d = _parse_ymd(m.group(1)) or _parse_md(m.group(1), year)
        if d:
            out["mode"] = "single"
            out["label"] = m.group(1)
            out["target_date"] = d
        return out

    # 4) relative
    if "后天" in txt:
        out["label"] = "后天"
        out["offset"] = 2
        try:
            out["target_date"] = today + timedelta(days=2)
        except Exception:
            out["target_date"] = None
        return out
    if "明天" in txt:
        out["label"] = "明天"
        out["offset"] = 1
        try:
            out["target_date"] = today + timedelta(days=1)
        except Exception:
            out["target_date"] = None
        return out
    if ("今天" in txt) or ("今日" in txt):
        out["label"] = "今天"
        out["offset"] = 0
        out["target_date"] = today
        return out

    # default: today
    out["offset"] = 0
    out["target_date"] = today
    return out
'''.strip("\n")

    # --- New helper: calendar range parser ---
    new_calendar = r'''
def _calendar_range_from_text(text: str, now_local: object = None) -> dict:
    """
    Parse calendar range from Chinese text.
    Return:
      - start: datetime (tz-aware if possible)
      - end: datetime
      - label: str
    Supports:
      - 今天/明天/后天
      - 接下来N天/未来N天/未来几天
      - YYYY-MM-DD
      - YYYY-MM-DD 到 YYYY-MM-DD
      - 1月26日
      - 1月26日 到 1月27日
    """
    txt = _ug_clean_unicode(text or "").strip()

    def _now():
        try:
            return _now_local()
        except Exception:
            from datetime import datetime as _dt
            return _dt.now()

    now = _now()
    tz = getattr(now, "tzinfo", None)

    def _d(y, m, d):
        try:
            return dt_date(int(y), int(m), int(d))
        except Exception:
            return None

    def _parse_ymd(s):
        ss = str(s or "").strip()
        m = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", ss)
        if not m:
            return None
        return _d(m.group(1), m.group(2), m.group(3))

    def _parse_md(s, year):
        ss = str(s or "").strip()
        m = re.match(r"^(\d{1,2})月(\d{1,2})日?$", ss)
        if not m:
            return None
        return _d(year, m.group(1), m.group(2))

    base = dt_date(now.year, now.month, now.day)

    def _to_dt(dd):
        from datetime import datetime as _dt
        if tz:
            return _dt(dd.year, dd.month, dd.day, 0, 0, 0, tzinfo=tz)
        return _dt(dd.year, dd.month, dd.day, 0, 0, 0)

    # Range: 接下来N天 / 未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", txt)
    if m:
        try:
            n = int(m.group(2))
        except Exception:
            n = 3
        if n < 1:
            n = 1
        if n > 30:
            n = 30
        start_d = base
        end_d = base + timedelta(days=n)
        return {"start": _to_dt(start_d), "end": _to_dt(end_d), "label": m.group(1) + str(n) + "天"}

    if re.search(r"(接下来|接下來|未来|未來)\s*几\s*天", txt):
        start_d = base
        end_d = base + timedelta(days=3)
        return {"start": _to_dt(start_d), "end": _to_dt(end_d), "label": "未来3天"}

    # explicit date range
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)\s*(到|至|\-)\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)", txt)
    if m:
        a = m.group(1)
        b = m.group(3)
        year = int(now.year)
        da = _parse_ymd(a) or _parse_md(a, year)
        db = _parse_ymd(b) or _parse_md(b, year)
        if da and db:
            start = _to_dt(da)
            end = _to_dt(db + timedelta(days=1))
            return {"start": start, "end": end, "label": a + "到" + b}

    # explicit single date
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日?)", txt)
    if m:
        year = int(now.year)
        dd = _parse_ymd(m.group(1)) or _parse_md(m.group(1), year)
        if dd:
            start = _to_dt(dd)
            end = _to_dt(dd + timedelta(days=1))
            return {"start": start, "end": end, "label": m.group(1)}

    # relative
    if "后天" in txt:
        dd = base + timedelta(days=2)
        return {"start": _to_dt(dd), "end": _to_dt(dd + timedelta(days=1)), "label": "后天"}
    if "明天" in txt:
        dd = base + timedelta(days=1)
        return {"start": _to_dt(dd), "end": _to_dt(dd + timedelta(days=1)), "label": "明天"}
    # default today
    return {"start": _to_dt(base), "end": _to_dt(base + timedelta(days=1)), "label": "今天"}
'''.strip("\n")

    # apply patches
    out = src
    out = _patch_route_request_date_shadow(out)
    out = _replace_top_level_def(out, "_weather_range_from_text", new_weather)
    out = _replace_top_level_def(out, "_calendar_range_from_text", new_calendar)

    if out == src:
        raise RuntimeError("no changes applied; abort")

    _write(APP, out)

    print("patched_ok=1")
    print("backup=" + bak)


if __name__ == "__main__":
    main()
