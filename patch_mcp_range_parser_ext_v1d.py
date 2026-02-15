import io
import re

APP = "app.py"

HELPER_BEGIN = "# --- CN_RANGE_EXT_V1 HELPERS BEGIN ---"
HELPER_END = "# --- CN_RANGE_EXT_V1 HELPERS END ---"

def _read():
    with io.open(APP, "r", encoding="utf-8") as f:
        return f.read()

def _write(s):
    with io.open(APP, "w", encoding="utf-8") as f:
        f.write(s)

def _find_def_header(src, func_name):
    # Match:
    #   def func(...):
    #   def func(...) -> dict:
    pat = r"^def\s+" + re.escape(func_name) + r"\s*\(.*\)\s*(?:->\s*[^:]+)?\s*:\s*$"
    m = re.search(pat, src, flags=re.M)
    return m

def _insert_helpers(src):
    if HELPER_BEGIN in src:
        return src, False

    m = re.search(r"^# --- WEATHER_RANGE_V1 HELPERS BEGIN ---\s*$", src, flags=re.M)
    if not m:
        raise RuntimeError("Cannot find marker: # --- WEATHER_RANGE_V1 HELPERS BEGIN ---")

    insert_pos = m.end()

    block = "\n" + HELPER_BEGIN + "\n" + (
        "# Extended CN range parsing (week / weekend / month)\n"
        "def _cn_wd_to_idx(s: str):\n"
        "    t = str(s or \"\")\n"
        "    t = t.replace(\"星期\", \"周\")\n"
        "    if \"周天\" in t:\n"
        "        return 6\n"
        "    if \"周日\" in t:\n"
        "        return 6\n"
        "    m = re.search(r\"周([一二三四五六日天])\", t)\n"
        "    if not m:\n"
        "        return None\n"
        "    c = m.group(1)\n"
        "    mp = {\"一\":0, \"二\":1, \"三\":2, \"四\":3, \"五\":4, \"六\":5, \"日\":6, \"天\":6}\n"
        "    return mp.get(c)\n"
        "\n"
        "def _week_start_monday(d):\n"
        "    try:\n"
        "        from datetime import timedelta\n"
        "        wd = int(d.weekday())\n"
        "        return d - timedelta(days=wd)\n"
        "    except Exception:\n"
        "        return d\n"
        "\n"
        "def _month_first_day(y, m):\n"
        "    from datetime import date as _date\n"
        "    return _date(int(y), int(m), 1)\n"
        "\n"
        "def _add_months_first_day(d, add_months):\n"
        "    try:\n"
        "        y = int(d.year)\n"
        "        mo = int(d.month)\n"
        "        mo2 = mo + int(add_months)\n"
        "        while mo2 > 12:\n"
        "            mo2 -= 12\n"
        "            y += 1\n"
        "        while mo2 < 1:\n"
        "            mo2 += 12\n"
        "            y -= 1\n"
        "        return _month_first_day(y, mo2)\n"
        "    except Exception:\n"
        "        return None\n"
        "\n"
        "def _end_of_month(d_first):\n"
        "    try:\n"
        "        from datetime import timedelta\n"
        "        next_first = _add_months_first_day(d_first, 1)\n"
        "        return next_first - timedelta(days=1)\n"
        "    except Exception:\n"
        "        return None\n"
        "\n"
        "def _parse_cn_week_month_range(text: str, now_d):\n"
        "    t = str(text or \"\").strip()\n"
        "    if not t:\n"
        "        return None\n"
        "    try:\n"
        "        from datetime import timedelta\n"
        "    except Exception:\n"
        "        timedelta = None\n"
        "\n"
        "    t_norm = t.replace(\"这个星期\", \"这周\").replace(\"这个周\", \"这周\").replace(\"星期\", \"周\")\n"
        "\n"
        "    # Month: next month first day / this month first day\n"
        "    if (\"下个月\" in t_norm) or (\"下月\" in t_norm):\n"
        "        if (\"第一天\" in t_norm) or (\"1号\" in t_norm) or (\"1日\" in t_norm):\n"
        "            d1 = _add_months_first_day(now_d, 1)\n"
        "            if d1 is not None:\n"
        "                return {\"mode\":\"single\",\"target_date\": d1, \"label\":\"下个月第一天\"}\n"
        "        if (\"日程\" in t_norm) or (\"日历\" in t_norm) or (\"日曆\" in t_norm) or (\"安排\" in t_norm) or (\"行程\" in t_norm) or (\"calendar\" in t_norm) or (\"event\" in t_norm):\n"
        "            d_first = _add_months_first_day(now_d, 1)\n"
        "            d_last = _end_of_month(d_first) if d_first is not None else None\n"
        "            if (d_first is not None) and (d_last is not None):\n"
        "                return {\"mode\":\"range\",\"start_date\": d_first, \"end_date\": d_last, \"label\":\"下个月\"}\n"
        "\n"
        "    if (\"这个月\" in t_norm) or (\"本月\" in t_norm):\n"
        "        if (\"第一天\" in t_norm) or (\"1号\" in t_norm) or (\"1日\" in t_norm):\n"
        "            d1 = _add_months_first_day(now_d, 0)\n"
        "            if d1 is not None:\n"
        "                return {\"mode\":\"single\",\"target_date\": d1, \"label\":\"本月第一天\"}\n"
        "        if (\"日程\" in t_norm) or (\"日历\" in t_norm) or (\"日曆\" in t_norm) or (\"安排\" in t_norm) or (\"行程\" in t_norm) or (\"calendar\" in t_norm) or (\"event\" in t_norm):\n"
        "            d_first = _add_months_first_day(now_d, 0)\n"
        "            d_last = _end_of_month(d_first) if d_first is not None else None\n"
        "            if (d_first is not None) and (d_last is not None):\n"
        "                return {\"mode\":\"range\",\"start_date\": d_first, \"end_date\": d_last, \"label\":\"本月\"}\n"
        "\n"
        "    # Weekday: 下周三 / 这周三 / 本周三 / 周三\n"
        "    m = re.search(r\"(下周|下星期|这周|本周|周)([一二三四五六日天])\", t_norm)\n"
        "    if m:\n"
        "        prefix = m.group(1)\n"
        "        target_wd = _cn_wd_to_idx(\"周\" + m.group(2))\n"
        "        if (target_wd is not None) and (timedelta is not None):\n"
        "            ws = _week_start_monday(now_d)\n"
        "            if (prefix == \"下周\") or (prefix == \"下星期\"):\n"
        "                ws = ws + timedelta(days=7)\n"
        "            if prefix == \"周\":\n"
        "                cand = ws + timedelta(days=int(target_wd))\n"
        "                if cand < now_d:\n"
        "                    ws = ws + timedelta(days=7)\n"
        "            d_target = ws + timedelta(days=int(target_wd))\n"
        "            return {\"mode\":\"single\",\"target_date\": d_target, \"label\": prefix + m.group(2)}\n"
        "\n"
        "    # Whole week: 下周 / 本周 / 这周\n"
        "    if (\"下周\" in t_norm) or (\"下星期\" in t_norm) or (\"这周\" in t_norm) or (\"本周\" in t_norm):\n"
        "        if timedelta is None:\n"
        "            return None\n"
        "        ws = _week_start_monday(now_d)\n"
        "        if (\"下周\" in t_norm) or (\"下星期\" in t_norm):\n"
        "            ws = ws + timedelta(days=7)\n"
        "            label = \"下周\"\n"
        "        else:\n"
        "            label = \"本周\"\n"
        "        we = ws + timedelta(days=6)\n"
        "        return {\"mode\":\"range\",\"start_date\": ws, \"end_date\": we, \"label\": label}\n"
        "\n"
        "    # Weekend: 这个周末 / 周末 / 下周末\n"
        "    if \"周末\" in t_norm:\n"
        "        if timedelta is None:\n"
        "            return None\n"
        "        ws = _week_start_monday(now_d)\n"
        "        if (\"下周末\" in t_norm) or (\"下星期周末\" in t_norm) or ((\"下周\" in t_norm or \"下星期\" in t_norm) and (\"周末\" in t_norm)):\n"
        "            ws2 = ws + timedelta(days=7)\n"
        "            sat = ws2 + timedelta(days=5)\n"
        "            sun = ws2 + timedelta(days=6)\n"
        "            return {\"mode\":\"range\",\"start_date\": sat, \"end_date\": sun, \"label\":\"下周末\"}\n"
        "        wd = int(now_d.weekday())\n"
        "        if wd == 5:\n"
        "            sat = now_d\n"
        "            sun = now_d + timedelta(days=1)\n"
        "        elif wd == 6:\n"
        "            sat = now_d - timedelta(days=1)\n"
        "            sun = now_d\n"
        "        else:\n"
        "            sat = now_d + timedelta(days=(5 - wd))\n"
        "            sun = sat + timedelta(days=1)\n"
        "        return {\"mode\":\"range\",\"start_date\": sat, \"end_date\": sun, \"label\":\"这个周末\"}\n"
        "\n"
        "    return None\n"
    ) + "\n" + HELPER_END + "\n"

    out = src[:insert_pos] + block + src[insert_pos:]
    return out, True

def _inject_weather(src):
    mh = _find_def_header(src, "_weather_range_from_text")
    if not mh:
        raise RuntimeError("Cannot find _weather_range_from_text (signature may differ).")

    sub = src[mh.start():]
    m2 = re.search(r"^\s*t2\s*=\s*re\.sub\([^\n]+\)\s*$", sub, flags=re.M)
    if not m2:
        raise RuntimeError("Cannot find t2 normalization inside _weather_range_from_text")

    anchor_end = mh.start() + m2.end()

    if "CN_RANGE_EXT_V1 APPLY WEATHER" in sub[:m2.end() + 400]:
        return src, False

    block = (
        "\n\n    # CN_RANGE_EXT_V1 APPLY WEATHER\n"
        "    try:\n"
        "        from datetime import datetime as _dt\n"
        "        if (now_local is not None) and hasattr(now_local, \"year\"):\n"
        "            from datetime import date as _date\n"
        "            now_d = _date(int(getattr(now_local, \"year\")), int(getattr(now_local, \"month\")), int(getattr(now_local, \"day\")))\n"
        "        else:\n"
        "            now_d = _dt.now().date()\n"
        "    except Exception:\n"
        "        now_d = None\n"
        "\n"
        "    if now_d is not None:\n"
        "        ext = _parse_cn_week_month_range(t2, now_d)\n"
        "        if isinstance(ext, dict):\n"
        "            if ext.get(\"mode\") == \"range\":\n"
        "                sd = ext.get(\"start_date\")\n"
        "                ed = ext.get(\"end_date\")\n"
        "                if (sd is not None) and (ed is not None):\n"
        "                    try:\n"
        "                        days = (ed - sd).days + 1\n"
        "                        if days < 1:\n"
        "                            days = 1\n"
        "                    except Exception:\n"
        "                        days = 1\n"
        "                    return {\"mode\":\"range\", \"start_date\": sd, \"days\": int(days), \"label\": str(ext.get(\"label\") or \"\")}\n"
        "            return ext\n"
    )

    out = src[:anchor_end] + block + src[anchor_end:]
    return out, True

def _inject_calendar(src):
    mh = _find_def_header(src, "_calendar_range_from_text")
    if not mh:
        raise RuntimeError("Cannot find _calendar_range_from_text (signature may differ).")

    sub = src[mh.start():]
    m2 = re.search(r"^\s*t2\s*=\s*re\.sub\([^\n]+\)\s*$", sub, flags=re.M)
    if not m2:
        raise RuntimeError("Cannot find t2 normalization inside _calendar_range_from_text")

    anchor_end = mh.start() + m2.end()

    if "CN_RANGE_EXT_V1 APPLY CALENDAR" in sub[:m2.end() + 400]:
        return src, False

    block = (
        "\n\n    # CN_RANGE_EXT_V1 APPLY CALENDAR\n"
        "    try:\n"
        "        from datetime import datetime as _dt\n"
        "        if (now_local is not None) and hasattr(now_local, \"year\"):\n"
        "            from datetime import date as _date\n"
        "            now_d = _date(int(getattr(now_local, \"year\")), int(getattr(now_local, \"month\")), int(getattr(now_local, \"day\")))\n"
        "        else:\n"
        "            now_d = _dt.now().date()\n"
        "    except Exception:\n"
        "        now_d = None\n"
        "\n"
        "    if now_d is not None:\n"
        "        ext = _parse_cn_week_month_range(t2, now_d)\n"
        "        if isinstance(ext, dict):\n"
        "            return ext\n"
    )

    out = src[:anchor_end] + block + src[anchor_end:]
    return out, True

def main():
    src = _read()

    src2, ch1 = _insert_helpers(src)
    src3, ch2 = _inject_weather(src2)
    src4, ch3 = _inject_calendar(src3)

    if not (ch1 or ch2 or ch3):
        print("No change needed.")
        return

    with io.open(APP + ".bak.cn_range_ext_v1d", "w", encoding="utf-8") as f:
        f.write(src)

    _write(src4)
    print("Patched OK. Backup: " + APP + ".bak.cn_range_ext_v1d")

if __name__ == "__main__":
    main()
