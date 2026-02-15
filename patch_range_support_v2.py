#!/usr/bin/env python3
# coding: utf-8

import io
import os
import re
import shutil
from datetime import datetime

APP = "app.py"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    b = p + ".bak." + ts
    shutil.copy2(p, b)
    return b

def replace_func_block(src, func_name, new_block):
    # Replace a top-level "def func_name(...):" block until next top-level def.
    pat = re.compile(r"(?m)^def[ \t]+" + re.escape(func_name) + r"\b[^\n]*\n")
    m = pat.search(src)
    if not m:
        return src, False

    start = m.start()
    # find next top-level def after this one
    m2 = re.compile(r"(?m)^def[ \t]+\w+\b[^\n]*\n").search(src, m.end())
    end = m2.start() if m2 else len(src)

    out = src[:start] + new_block.rstrip() + "\n\n" + src[end:]
    return out, True

def insert_after_anchor(src, anchor_pat, insert_text):
    m = re.search(anchor_pat, src, flags=re.M)
    if not m:
        return src, False
    idx = m.end()
    return src[:idx] + "\n\n" + insert_text.rstrip() + "\n\n" + src[idx:], True

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found in current directory")

    s = read_text(APP)
    bak = backup_file(APP)
    changed = 0

    # 1) Remove function-local "from datetime import ... date ..." to avoid UnboundLocalError shadowing
    #    Do NOT touch the top-level import lines.
    #    Only remove lines that are indented (inside a function).
    before = s
    s = re.sub(r"(?m)^[ \t]+from datetime import[^\n]*\bdate\b[^\n]*\n", "", s)
    if s != before:
        changed += 1

    # 2) Ensure dt_date alias exists if code uses it
    if ("dt_date(" in s) and (not re.search(r"(?m)^\s*dt_date\s*=", s)) and (not re.search(r"(?m)from datetime import .*date as dt_date", s)):
        # insert after the first top-level "from datetime import" line
        s2, ok = insert_after_anchor(s, r"(?m)^from datetime import[^\n]*\n", "dt_date = date")
        if ok:
            s = s2
            changed += 1

    # 3) Replace / add _weather_range_from_text
    new_weather = r'''
def _weather_range_from_text(text, now_local=None):
    """
    Parse weather time intent from Chinese text.
    Returns:
      - mode: "single" or "range"
      - label: "今天/明天/后天/未来N天/..." (optional)
      - offset: int (single relative days)
      - target_date: date object (single absolute date)
      - start_date: date object (range start)
      - days: int (range length)
    """
    t = (text or "").strip()

    # get local now
    if now_local is None:
        try:
            now_local = _now_local()
        except Exception:
            now_local = datetime.now()

    base_d = dt_date(now_local.year, now_local.month, now_local.day)

    out = {"mode": "single", "label": "", "offset": 0, "target_date": None, "start_date": None, "days": None}

    # helpers
    def _to_int(x, default_v):
        try:
            return int(x)
        except Exception:
            return default_v

    def _parse_ymd(s):
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
        if m:
            y = _to_int(m.group(1), base_d.year)
            mm = _to_int(m.group(2), base_d.month)
            dd = _to_int(m.group(3), base_d.day)
            try:
                return dt_date(y, mm, dd)
            except Exception:
                return None
        return None

    def _parse_md(s):
        # 1月26日 / 1月26号 / 1/26
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)?", s)
        if not m:
            m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
        if m:
            mm = _to_int(m.group(1), base_d.month)
            dd = _to_int(m.group(2), base_d.day)
            y = base_d.year
            try:
                d0 = dt_date(y, mm, dd)
            except Exception:
                return None
            # If the date already passed "a while ago", assume next year.
            try:
                if d0 < base_d and (base_d - d0).days > 30:
                    d0 = dt_date(y + 1, mm, dd)
            except Exception:
                pass
            return d0
        return None

    # range: 接下来N天 / 未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t)
    if m:
        days = _to_int(m.group(2), 3)
        if days < 1:
            days = 1
        if days > 5:
            days = 5
        out["mode"] = "range"
        out["label"] = "未来" + str(days) + "天"
        out["start_date"] = base_d
        out["days"] = days
        return out

    # explicit date range: A 到 B / A- B / A～B / 从A到B
    # try parse two dates
    if ("到" in t) or ("至" in t) or ("-" in t) or ("～" in t) or ("—" in t):
        parts = re.split(r"(?:到|至|—|–|－|〜|～|-)", t)
        if len(parts) >= 2:
            a = parts[0].strip()
            b = parts[1].strip()
            da = _parse_ymd(a) or _parse_md(a)
            db = _parse_ymd(b) or _parse_md(b)
            if da and db:
                # normalize order
                if db < da:
                    da, db = db, da
                span = (db - da).days + 1
                if span < 1:
                    span = 1
                if span > 5:
                    span = 5
                out["mode"] = "range"
                out["label"] = ""
                out["start_date"] = da
                out["days"] = span
                return out

    # single: 明天/后天/大后天/今天
    if "大后天" in t:
        out["label"] = "大后天"
        out["offset"] = 3
        return out
    if "后天" in t:
        out["label"] = "后天"
        out["offset"] = 2
        return out
    if "明天" in t:
        out["label"] = "明天"
        out["offset"] = 1
        return out
    if ("今天" in t) or ("今天天" in t) or ("今日" in t):
        out["label"] = "今天"
        out["offset"] = 0
        return out

    # single: explicit date
    d1 = _parse_ymd(t) or _parse_md(t)
    if d1:
        out["target_date"] = d1
        out["label"] = str(d1)
        out["offset"] = 0
        return out

    return out
'''.lstrip("\n")

    s, ok = replace_func_block(s, "_weather_range_from_text", new_weather)
    if ok:
        changed += 1
    else:
        # insert before route_request if function doesn't exist
        s2, ok2 = insert_after_anchor(s, r"(?m)^def route_request\b[^\n]*\n", new_weather)
        if ok2:
            s = s2
            changed += 1

    # 4) Replace / add _calendar_range_from_text
    new_cal = r'''
def _calendar_range_from_text(text, now_local=None):
    """
    Parse calendar time intent from Chinese text.
    Returns dict:
      - start: ISO string (with local timezone offset if possible)
      - end: ISO string
      - label: "今天/明天/未来N天/2026-01-26/..."
      - days: int
    """
    t = (text or "").strip()

    if now_local is None:
        try:
            now_local = _now_local()
        except Exception:
            now_local = datetime.now()

    base_d = dt_date(now_local.year, now_local.month, now_local.day)
    tzinfo = getattr(now_local, "tzinfo", None)

    def _to_int(x, default_v):
        try:
            return int(x)
        except Exception:
            return default_v

    def _parse_ymd(s):
        m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", s)
        if m:
            y = _to_int(m.group(1), base_d.year)
            mm = _to_int(m.group(2), base_d.month)
            dd = _to_int(m.group(3), base_d.day)
            try:
                return dt_date(y, mm, dd)
            except Exception:
                return None
        return None

    def _parse_md(s):
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)?", s)
        if not m:
            m = re.search(r"\b(\d{1,2})/(\d{1,2})\b", s)
        if m:
            mm = _to_int(m.group(1), base_d.month)
            dd = _to_int(m.group(2), base_d.day)
            y = base_d.year
            try:
                d0 = dt_date(y, mm, dd)
            except Exception:
                return None
            try:
                if d0 < base_d and (base_d - d0).days > 30:
                    d0 = dt_date(y + 1, mm, dd)
            except Exception:
                pass
            return d0
        return None

    def _iso_day_start(d):
        dt0 = datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=tzinfo) if tzinfo else datetime(d.year, d.month, d.day, 0, 0, 0)
        return dt0.isoformat()

    def _iso_day_end_exclusive(d):
        # next day 00:00
        d2 = d + timedelta(days=1)
        dt1 = datetime(d2.year, d2.month, d2.day, 0, 0, 0, tzinfo=tzinfo) if tzinfo else datetime(d2.year, d2.month, d2.day, 0, 0, 0)
        return dt1.isoformat()

    # default: today
    start_d = base_d
    days = 1
    label = "今天"

    # 接下来N天/未来N天
    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t)
    if m:
        days = _to_int(m.group(2), 3)
        if days < 1:
            days = 1
        if days > 14:
            days = 14
        start_d = base_d
        label = "未来" + str(days) + "天"
        return {"start": _iso_day_start(start_d), "end": _iso_day_end_exclusive(start_d + timedelta(days=days-1)), "label": label, "days": days}

    # explicit date range
    if ("到" in t) or ("至" in t) or ("-" in t) or ("～" in t) or ("—" in t):
        parts = re.split(r"(?:到|至|—|–|－|〜|～|-)", t)
        if len(parts) >= 2:
            da = (_parse_ymd(parts[0].strip()) or _parse_md(parts[0].strip()))
            db = (_parse_ymd(parts[1].strip()) or _parse_md(parts[1].strip()))
            if da and db:
                if db < da:
                    da, db = db, da
                span = (db - da).days + 1
                if span < 1:
                    span = 1
                if span > 14:
                    span = 14
                label = str(da) + " 到 " + str(db)
                return {"start": _iso_day_start(da), "end": _iso_day_end_exclusive(da + timedelta(days=span-1)), "label": label, "days": span}

    # relative single day
    if "明天" in t:
        start_d = base_d + timedelta(days=1)
        label = "明天"
        return {"start": _iso_day_start(start_d), "end": _iso_day_end_exclusive(start_d), "label": label, "days": 1}
    if "后天" in t:
        start_d = base_d + timedelta(days=2)
        label = "后天"
        return {"start": _iso_day_start(start_d), "end": _iso_day_end_exclusive(start_d), "label": label, "days": 1}
    if ("今天" in t) or ("今日" in t):
        start_d = base_d
        label = "今天"
        return {"start": _iso_day_start(start_d), "end": _iso_day_end_exclusive(start_d), "label": label, "days": 1}

    # explicit single date
    d1 = _parse_ymd(t) or _parse_md(t)
    if d1:
        label = str(d1)
        return {"start": _iso_day_start(d1), "end": _iso_day_end_exclusive(d1), "label": label, "days": 1}

    return {"start": _iso_day_start(start_d), "end": _iso_day_end_exclusive(start_d), "label": label, "days": days}
'''.lstrip("\n")

    s, ok = replace_func_block(s, "_calendar_range_from_text", new_cal)
    if ok:
        changed += 1
    else:
        # insert before route_request if doesn't exist
        s2, ok2 = insert_after_anchor(s, r"(?m)^def route_request\b[^\n]*\n", new_cal)
        if ok2:
            s = s2
            changed += 1

    # 5) Fix isinstance(..., date) inside route_request weather-range area if present
    # (use dt_date to avoid any future shadowing risk)
    before = s
    s = re.sub(r"isinstance\(([^,]+),\s*date\)", r"isinstance(\1, dt_date)", s)
    if s != before:
        changed += 1

    write_text(APP, s)
    print("backup:", bak)
    print("patched_changed_steps:", changed)

if __name__ == "__main__":
    main()
