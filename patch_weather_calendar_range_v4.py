#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Patch: add robust date/range parsing for structured_weather + structured_calendar,
and avoid 'date' UnboundLocalError by using dt_date alias consistently.

- Safe: makes a backup before modifying app.py
- Anchor-first: prefer replacing marked blocks; otherwise inserts helper defs
"""

import os
import re
import sys
import shutil


def _read_text(p: str) -> str:
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(p: str, s: str) -> None:
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _backup(p: str, tag: str) -> str:
    b = p + ".bak." + tag
    shutil.copy2(p, b)
    return b


def _replace_block_by_markers(s: str, start_mark: str, end_mark: str, new_block: str):
    i = s.find(start_mark)
    j = s.find(end_mark)
    if i < 0 or j < 0 or j <= i:
        return s, 0
    j2 = j + len(end_mark)
    out = s[:i] + new_block + s[j2:]
    return out, 1


def _ensure_import_aliases(s: str) -> str:
    # We want: from datetime import datetime, timedelta, date as dt_date
    if re.search(r"(?m)^from datetime import .*date as dt_date", s):
        return s

    m = re.search(r"(?m)^from datetime import ([^\n]+)\n", s)
    if m:
        body = m.group(1)

        if re.search(r"\bdate\b", body) and ("dt_date" not in body):
            body2 = re.sub(r"\bdate\b", "date as dt_date", body)
        else:
            body2 = body
            if "dt_date" not in body2:
                body2 = body2 + ", date as dt_date"

        new_line = "from datetime import " + body2 + "\n"
        return s[:m.start()] + new_line + s[m.end():]

    ins = "from datetime import datetime, timedelta, date as dt_date\n"
    m2 = re.search(r"(?m)^(import [^\n]+\n)+", s)
    if m2:
        return s[:m2.end()] + ins + s[m2.end():]
    return ins + s


HELPERS = r'''# --- RANGE_PARSE_HELPERS_V1 BEGIN ---
def _parse_ymd(s: str):
    ss = (s or "").strip()
    if len(ss) != 10:
        return None
    try:
        y = int(ss[0:4]); m = int(ss[5:7]); d = int(ss[8:10])
        return dt_date(y, m, d)
    except Exception:
        return None


def _cn_date_to_ymd(text: str, now_d):
    """
    Parse Chinese '1月26日' / '1月26号' into dt_date(year, month, day)
    If year missing, use now_d.year.
    """
    t = (text or "").strip()
    m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*(日|号)", t)
    if not m:
        return None
    try:
        mm = int(m.group(1)); dd = int(m.group(2))
        yy = int(getattr(now_d, "year", 1970) or 1970)
        return dt_date(yy, mm, dd)
    except Exception:
        return None


def _range_from_text(text: str, now_d):
    """
    Returns dict:
      mode: 'single' | 'range'
      label: '今天'/'明天'/'后天'/'' (optional)
      offset: int (for relative single)
      target_date: dt_date (for explicit single)
      start_date: dt_date (for range)
      end_date: dt_date (optional)
      days: int (for '未来N天' / '接下来N天')
    """
    t = (text or "").strip()
    out = {"mode": "single", "offset": 0, "label": ""}

    if re.search(r"(今天|今日)", t):
        out["label"] = "今天"
        out["offset"] = 0
    elif re.search(r"(明天|明日)", t):
        out["label"] = "明天"
        out["offset"] = 1
    elif re.search(r"(后天)", t):
        out["label"] = "后天"
        out["offset"] = 2

    m = re.search(r"(接下来|接下來|未来|未來)\s*(\d{1,2})\s*天", t)
    if m:
        out["mode"] = "range"
        try:
            out["days"] = int(m.group(2))
        except Exception:
            out["days"] = 3
        out["start_date"] = now_d
        out["label"] = ""
        return out

    m2 = re.search(r"(\d{4}-\d{2}-\d{2})", t)
    if m2:
        d = _parse_ymd(m2.group(1))
        if d is not None:
            out["target_date"] = d
            out["label"] = m2.group(1)
            out["offset"] = 0

    if "target_date" not in out:
        d2 = _cn_date_to_ymd(t, now_d)
        if d2 is not None:
            out["target_date"] = d2
            out["label"] = str(int(d2.month)) + "月" + str(int(d2.day)) + "日"
            out["offset"] = 0

    m3 = re.search(r"(\d{4}-\d{2}-\d{2})\s*(到|至|~|-)\s*(\d{4}-\d{2}-\d{2})", t)
    if m3:
        d1 = _parse_ymd(m3.group(1))
        d2 = _parse_ymd(m3.group(3))
        if (d1 is not None) and (d2 is not None):
            if d2 < d1:
                d1, d2 = d2, d1
            out = {"mode": "range", "start_date": d1, "end_date": d2, "label": m3.group(1) + "到" + m3.group(3)}
            return out

    return out
# --- RANGE_PARSE_HELPERS_V1 END ---
'''


def _indent_block(block: str, indent: str) -> str:
    out = []
    for ln in block.splitlines():
        if ln.strip() == "":
            out.append("")
        else:
            out.append(indent + ln)
    return "\n".join(out) + "\n"


WEATHER_ROUTE_BLOCK = r'''if rt == 'structured_weather':
    default_weather = (os.environ.get('HA_DEFAULT_WEATHER_ENTITY') or '').strip()
    if not default_weather:
        return {'ok': True, 'route_type': 'structured_weather', 'final': '未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。', 'error': 'missing_default_weather_entity'}

    # timezone
    try:
        try:
            from zoneinfo import ZoneInfo
        except Exception:
            ZoneInfo = None
        tzname = os.environ.get('TZ') or 'Australia/Melbourne'
        tzinfo = None
        if ZoneInfo is not None:
            try:
                tzinfo = ZoneInfo(tzname)
            except Exception:
                tzinfo = None
    except Exception:
        tzinfo = None

    now_dt = datetime.now(tzinfo) if tzinfo else datetime.now()
    now_d = dt_date(now_dt.year, now_dt.month, now_dt.day)

    q = _range_from_text(user_text, now_d)

    r = ha_weather_forecast(default_weather, 'daily', 12)
    if not r.get('ok'):
        return {'ok': True, 'route_type': 'structured_weather', 'final': '我现在联网查询失败了，请稍后再试。', 'data': r, 'error': 'weather_fetch_failed'}

    fc = r.get('forecast') if isinstance(r.get('forecast'), list) else []
    if not fc:
        return {'ok': True, 'route_type': 'structured_weather', 'final': '天气实体没有返回预报数据。', 'data': r, 'error': 'empty_forecast'}

    if q.get('mode') == 'range':
        start_d = q.get('start_date')
        if not isinstance(start_d, dt_date):
            start_d = now_d

        if isinstance(q.get('end_date'), dt_date):
            end_d = q.get('end_date')
            try:
                days_i = int((end_d - start_d).days) + 1
            except Exception:
                days_i = 1
        else:
            try:
                days_i = int(q.get('days'))
            except Exception:
                days_i = 3

        if days_i < 1:
            days_i = 1
        if days_i > 5:
            days_i = 5

        summary = _summarise_weather_range(fc, start_d, days_i, tzinfo)
        head = '（' + default_weather + '）'
        label = str(q.get('label') or '').strip()
        if label:
            final = head + label + '天气：' + summary
        else:
            final = head + '未来' + str(days_i) + '天天气：' + summary
        return {'ok': True, 'route_type': 'structured_weather', 'final': final, 'data': r}

    td = q.get('target_date')
    if isinstance(td, dt_date):
        target_d = td
    else:
        try:
            off = int(q.get('offset') or 0)
        except Exception:
            off = 0
        target_d = now_d + timedelta(days=off)

    it = _pick_daily_forecast_by_local_date(fc, target_d, tzinfo)
    summary = _summarise_weather_item(it)
    head = '（' + default_weather + '）'
    label = str(q.get('label') or '').strip()
    if label:
        final = head + label + '天气：' + summary
    else:
        final = head + '天气：' + summary
    return {'ok': True, 'route_type': 'structured_weather', 'final': final, 'data': r}
'''


CALENDAR_ROUTE_BLOCK = r'''if rt == 'structured_calendar':
    default_cal = (os.environ.get('HA_DEFAULT_CALENDAR_ENTITY') or '').strip()
    if not default_cal:
        return {'ok': True, 'route_type': 'structured_calendar', 'final': '未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY，或直接用 ha_calendar_events(entity_id,start,end) 调用。', 'error': 'missing_default_calendar_entity'}

    # timezone
    try:
        try:
            from zoneinfo import ZoneInfo
        except Exception:
            ZoneInfo = None
        tzname = os.environ.get('TZ') or 'Australia/Melbourne'
        tzinfo = None
        if ZoneInfo is not None:
            try:
                tzinfo = ZoneInfo(tzname)
            except Exception:
                tzinfo = None
    except Exception:
        tzinfo = None

    now_dt = datetime.now(tzinfo) if tzinfo else datetime.now()
    now_d = dt_date(now_dt.year, now_dt.month, now_dt.day)

    q = _range_from_text(user_text, now_d)

    if q.get('mode') == 'range':
        start_d = q.get('start_date')
        if not isinstance(start_d, dt_date):
            start_d = now_d

        if isinstance(q.get('end_date'), dt_date):
            end_d = q.get('end_date')
            end_excl = end_d + timedelta(days=1)
        else:
            try:
                days_i = int(q.get('days'))
            except Exception:
                days_i = 3
            if days_i < 1:
                days_i = 1
            if days_i > 14:
                days_i = 14
            end_excl = start_d + timedelta(days=days_i)

        start_iso = start_d.isoformat() + 'T00:00:00+11:00'
        end_iso = end_excl.isoformat() + 'T00:00:00+11:00'
    else:
        td = q.get('target_date')
        if isinstance(td, dt_date):
            day = td
        else:
            try:
                off = int(q.get('offset') or 0)
            except Exception:
                off = 0
            day = now_d + timedelta(days=off)

        start_iso = day.isoformat() + 'T00:00:00+11:00'
        end_iso = (day + timedelta(days=1)).isoformat() + 'T00:00:00+11:00'

    r = ha_calendar_events(default_cal, start_iso, end_iso, 12)
    if not r.get('ok'):
        return {'ok': True, 'route_type': 'structured_calendar', 'final': '我现在联网查询失败了，请稍后再试。', 'data': r, 'error': 'calendar_fetch_failed'}

    items = r.get('data') if isinstance(r.get('data'), list) else []
    final = _summarise_calendar_items(items, user_text)
    if (not final) or (not isinstance(final, str)):
        if items:
            final = '已获取日程（' + default_cal + '），共 ' + str(len(items)) + ' 条日程。'
        else:
            if re.search(r"(明天|明日)", user_text or ""):
                final = '明天没有日程。'
            elif re.search(r"(后天)", user_text or ""):
                final = '后天没有日程。'
            else:
                final = '今天没有日程。'

    out = {'ok': True, 'route_type': 'structured_calendar', 'final': final, 'data': r}
    out['range'] = {'start': start_iso, 'end': end_iso}
    return out
'''


def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found", file=sys.stderr)
        sys.exit(2)

    s = _read_text(p)
    backup = _backup(p, "weather_calendar_range_v4")

    s = _ensure_import_aliases(s)

    if "RANGE_PARSE_HELPERS_V1 BEGIN" not in s:
        ins_at = s.find("def _holiday_next_from_list")
        if ins_at > 0:
            s = s[:ins_at] + HELPERS + "\n" + s[ins_at:]
        else:
            s = HELPERS + "\n" + s

    # Replace marked blocks if present
    start_w = "# --- WEATHER_RANGE_V1 ROUTE BEGIN ---"
    end_w = "# --- WEATHER_RANGE_V1 ROUTE END ---"
    if (start_w in s) and (end_w in s):
        new_block = start_w + "\n" + WEATHER_ROUTE_BLOCK + "\n" + end_w
        s, ok_w = _replace_block_by_markers(s, start_w, end_w, new_block)
    else:
        ok_w = 0
        m = re.search(r"(?ms)^([ \t]*)if[ \t]+rt[ \t]*==[ \t]*['\"]structured_weather['\"]:[^\n]*\n(?:^[ \t]+.*\n)+", s)
        if m:
            indent = m.group(1)
            s = s[:m.start()] + _indent_block(WEATHER_ROUTE_BLOCK, indent) + s[m.end():]
            ok_w = 1

    start_c = "# --- CALENDAR_RANGE_V1 ROUTE BEGIN ---"
    end_c = "# --- CALENDAR_RANGE_V1 ROUTE END ---"
    if (start_c in s) and (end_c in s):
        new_block = start_c + "\n" + CALENDAR_ROUTE_BLOCK + "\n" + end_c
        s, ok_c = _replace_block_by_markers(s, start_c, end_c, new_block)
    else:
        ok_c = 0
        m2 = re.search(r"(?ms)^([ \t]*)if[ \t]+rt[ \t]*==[ \t]*['\"]structured_calendar['\"]:[^\n]*\n(?:^[ \t]+.*\n)+", s)
        if m2:
            indent = m2.group(1)
            s = s[:m2.start()] + _indent_block(CALENDAR_ROUTE_BLOCK, indent) + s[m2.end():]
            ok_c = 1

    _write_text(p, s)
    print("backup=" + backup)
    print("patched_weather=" + str(ok_w))
    print("patched_calendar=" + str(ok_c))


if __name__ == "__main__":
    main()
