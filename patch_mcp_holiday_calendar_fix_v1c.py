import re

APP = "app.py"

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _find_func_block(src, func_name):
    key = "def " + func_name + "("
    s = src.find(key)
    if s < 0:
        return None
    m = re.search(r"\ndef\s+[A-Za-z0-9_]+\s*\(", src[s + 1:])
    if m:
        e = s + 1 + m.start() + 1
        return (s, e)
    return (s, len(src))

def _insert_before_func(src, target_func_name, insert_text):
    key = "def " + target_func_name + "("
    idx = src.find(key)
    if idx < 0:
        return None
    # include any decorators right above it
    dec_start = src.rfind("\n@", 0, idx)
    line_start = src.rfind("\n", 0, idx) + 1
    if dec_start >= 0 and dec_start > src.rfind("\n\n", 0, idx):
        ins_pos = dec_start + 1
    else:
        ins_pos = line_start
    return src[:ins_pos] + insert_text + src[ins_pos:]

def _replace_indented_block(lines, start_i):
    """
    Replace a python indented block starting at start_i (the 'if ...:' line).
    The block ends when we hit a non-empty line whose indent <= the start indent.
    Return (end_i, indent_str)
    """
    start_line = lines[start_i]
    start_indent = start_line[:len(start_line) - len(start_line.lstrip(" "))]
    start_indent_len = len(start_indent)

    i = start_i + 1
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "":
            i += 1
            continue
        if ln.lstrip().startswith("#"):
            i += 1
            continue
        cur_indent = ln[:len(ln) - len(ln.lstrip(" "))]
        if len(cur_indent) <= start_indent_len:
            break
        i += 1
    return i, start_indent

def main():
    src = _read(APP)

    # -------------------------------------------------
    # 1) Add ha_list_calendars tool (if missing)
    # -------------------------------------------------
    if "def ha_list_calendars(" not in src:
        insert_text = (
            "@mcp.tool(description=\"(Structured) List available HA calendars (entity_id + name).\")\n"
            "def ha_list_calendars(timeout_sec: int = 12) -> dict:\n"
            "    return _ha_request(\"GET\", \"/api/calendars\", timeout_sec=int(timeout_sec))\n\n\n"
        )
        new_src = _insert_before_func(src, "ha_calendar_events", insert_text)
        if new_src is None:
            raise RuntimeError("Cannot find def ha_calendar_events( to insert ha_list_calendars before it.")
        src = new_src

    # -------------------------------------------------
    # 2) Replace _holiday_next_from_list + add _holiday_prev_from_list
    # -------------------------------------------------
    blk = _find_func_block(src, "_holiday_next_from_list")
    if blk is None:
        raise RuntimeError("Cannot find function _holiday_next_from_list in app.py")

    new_block = (
        "def _holiday_next_from_list(items: list, today_ymd: str) -> dict:\n"
        "    \"\"\"Return the next holiday on/after today_ymd.\"\"\"\n"
        "    try:\n"
        "        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])\n"
        "        today = dt_date(y, mo, da)\n"
        "    except Exception:\n"
        "        return {\"ok\": False}\n"
        "\n"
        "    best = None\n"
        "    best_d = None\n"
        "    for x in items or []:\n"
        "        if not isinstance(x, dict):\n"
        "            continue\n"
        "        ds = str(x.get(\"date\") or \"\").strip()\n"
        "        nm = str(x.get(\"name\") or \"\").strip()\n"
        "        if len(ds) != 10:\n"
        "            continue\n"
        "        try:\n"
        "            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])\n"
        "            d = dt_date(yy, mm, dd)\n"
        "        except Exception:\n"
        "            continue\n"
        "        if d < today:\n"
        "            continue\n"
        "        if (best_d is None) or (d < best_d):\n"
        "            best_d = d\n"
        "            best = {\"date\": ds, \"name\": nm}\n"
        "\n"
        "    if not best or (best_d is None):\n"
        "        return {\"ok\": False}\n"
        "\n"
        "    try:\n"
        "        days = (best_d - today).days\n"
        "    except Exception:\n"
        "        days = None\n"
        "\n"
        "    out = {\"ok\": True, \"date\": best.get(\"date\"), \"name\": best.get(\"name\")}\n"
        "    if isinstance(days, int):\n"
        "        out[\"days\"] = days\n"
        "    return out\n"
        "\n"
        "def _holiday_prev_from_list(items: list, today_ymd: str) -> dict:\n"
        "    \"\"\"Return the most recent holiday on/before today_ymd.\"\"\"\n"
        "    try:\n"
        "        y = int(today_ymd[0:4]); mo = int(today_ymd[5:7]); da = int(today_ymd[8:10])\n"
        "        today = dt_date(y, mo, da)\n"
        "    except Exception:\n"
        "        return {\"ok\": False}\n"
        "\n"
        "    best = None\n"
        "    best_d = None\n"
        "    for x in items or []:\n"
        "        if not isinstance(x, dict):\n"
        "            continue\n"
        "        ds = str(x.get(\"date\") or \"\").strip()\n"
        "        nm = str(x.get(\"name\") or \"\").strip()\n"
        "        if len(ds) != 10:\n"
        "            continue\n"
        "        try:\n"
        "            yy = int(ds[0:4]); mm = int(ds[5:7]); dd = int(ds[8:10])\n"
        "            d = dt_date(yy, mm, dd)\n"
        "        except Exception:\n"
        "            continue\n"
        "        if d > today:\n"
        "            continue\n"
        "        if (best_d is None) or (d > best_d):\n"
        "            best_d = d\n"
        "            best = {\"date\": ds, \"name\": nm}\n"
        "\n"
        "    if not best or (best_d is None):\n"
        "        return {\"ok\": False}\n"
        "\n"
        "    try:\n"
        "        days_ago = (today - best_d).days\n"
        "    except Exception:\n"
        "        days_ago = None\n"
        "\n"
        "    out = {\"ok\": True, \"date\": best.get(\"date\"), \"name\": best.get(\"name\")}\n"
        "    if isinstance(days_ago, int):\n"
        "        out[\"days_ago\"] = days_ago\n"
        "    return out\n"
    )
    src = src[:blk[0]] + new_block + src[blk[1]:]

    # -------------------------------------------------
    # 3) Replace route_request holiday block by indentation parsing
    # -------------------------------------------------
    lines = src.splitlines(True)

    # find the first occurrence of the holiday if-line
    target_i = None
    for i, ln in enumerate(lines):
        if "if _is_holiday_query(user_text):" in ln:
            target_i = i
            break
    if target_i is None:
        raise RuntimeError("Cannot find line: if _is_holiday_query(user_text):")

    end_i, indent = _replace_indented_block(lines, target_i)

    rb = []
    rb.append(indent + "if _is_holiday_query(user_text):\n")
    rb.append(indent + "    m = re.search(r\"(20\\d{2})\", user_text)\n")
    rb.append(indent + "    y = None\n")
    rb.append(indent + "    if m:\n")
    rb.append(indent + "        try:\n")
    rb.append(indent + "            y = int(m.group(1))\n")
    rb.append(indent + "        except Exception:\n")
    rb.append(indent + "            y = None\n")
    rb.append(indent + "    now = _now_local()\n")
    rb.append(indent + "    if y is None:\n")
    rb.append(indent + "        try:\n")
    rb.append(indent + "            y = int(getattr(now, \"year\"))\n")
    rb.append(indent + "        except Exception:\n")
    rb.append(indent + "            y = 2026\n")
    rb.append(indent + "    rr = holiday_vic(y)\n")
    rb.append(indent + "    if not rr.get(\"ok\"):\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": \"假期查询失败。\", \"data\": rr}\n")
    rb.append(indent + "    items = rr.get(\"holidays\") or []\n")
    rb.append(indent + "    today_d = dt_date(now.year, now.month, now.day)\n")
    rb.append(indent + "    today_s = str(today_d)\n")
    rb.append("\n")
    rb.append(indent + "    t = str(user_text or \"\")\n")
    rb.append(indent + "    want_next = (\"下一个\" in t) or (\"下個\" in t) or (\"next\" in t.lower())\n")
    rb.append(indent + "    want_recent = (\"最近\" in t) or (\"上一个\" in t) or (\"上個\" in t) or (\"刚刚\" in t) or (\"剛剛\" in t)\n")
    rb.append("\n")
    rb.append(indent + "    if want_next:\n")
    rb.append(indent + "        nx = _holiday_next_from_list(items, today_s)\n")
    rb.append(indent + "        if not nx.get(\"ok\"):\n")
    rb.append(indent + "            final = \"未找到下一个维州公众假期。\"\n")
    rb.append(indent + "            return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr}\n")
    rb.append(indent + "        days = nx.get(\"days\")\n")
    rb.append(indent + "        if isinstance(days, int):\n")
    rb.append(indent + "            final = \"下一个维州公众假期：\" + str(nx.get(\"name\") or \"\") + \"（\" + str(nx.get(\"date\") or \"\") + \"，\" + str(days) + \" 天后）\"\n")
    rb.append(indent + "        else:\n")
    rb.append(indent + "            final = \"下一个维州公众假期：\" + str(nx.get(\"name\") or \"\") + \"（\" + str(nx.get(\"date\") or \"\") + \"）\"\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr, \"next\": nx}\n")
    rb.append("\n")
    rb.append(indent + "    if want_recent:\n")
    rb.append(indent + "        pv = _holiday_prev_from_list(items, today_s)\n")
    rb.append(indent + "        if not pv.get(\"ok\"):\n")
    rb.append(indent + "            final = \"未找到最近的维州公众假期。\"\n")
    rb.append(indent + "            return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr}\n")
    rb.append(indent + "        da = pv.get(\"days_ago\")\n")
    rb.append(indent + "        if isinstance(da, int):\n")
    rb.append(indent + "            final = \"最近的维州公众假期：\" + str(pv.get(\"name\") or \"\") + \"（\" + str(pv.get(\"date\") or \"\") + \"，\" + str(da) + \" 天前）\"\n")
    rb.append(indent + "        else:\n")
    rb.append(indent + "            final = \"最近的维州公众假期：\" + str(pv.get(\"name\") or \"\") + \"（\" + str(pv.get(\"date\") or \"\") + \"）\"\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": final, \"data\": rr, \"recent\": pv}\n")
    rb.append("\n")
    rb.append(indent + "    return {\"ok\": True, \"route_type\": \"structured_holiday\", \"final\": \"已获取维州公众假期（AU-VIC），年份 \" + str(y) + \"，共 \" + str(len(items)) + \" 天。\", \"data\": rr}\n")

    lines = lines[:target_i] + rb + lines[end_i:]
    src2 = "".join(lines)

    _write(APP, src2)
    print("OK: patched " + APP)

if __name__ == "__main__":
    main()
