import re

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _replace_indented_block(lines, start_i):
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
    lines = src.splitlines(True)

    # find weather block
    target_i = None
    for i, ln in enumerate(lines):
        if "if _is_weather_query(user_text):" in ln:
            target_i = i
            break
    if target_i is None:
        raise RuntimeError("Cannot find line: if _is_weather_query(user_text):")

    end_i, indent = _replace_indented_block(lines, target_i)

    rb = []
    rb.append(indent + "if _is_weather_query(user_text):\n")
    rb.append(indent + "    eid = str(os.environ.get(\"HA_DEFAULT_WEATHER_ENTITY\") or \"\").strip()\n")
    rb.append(indent + "    if not eid:\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_weather\", \"final\": \"未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。\", \"error\": \"missing_default_weather_entity\"}\n")
    rb.append(indent + "    tzinfo = _tzinfo()\n")
    rb.append(indent + "    now = _now_local()\n")
    rb.append(indent + "    base_d = dt_date(now.year, now.month, now.day)\n")
    rb.append("\n")
    rb.append(indent + "    q = _weather_range_from_text(user_text, now_local=now)\n")
    rb.append(indent + "    rr = ha_weather_forecast(eid, \"daily\")\n")
    rb.append(indent + "    if not rr.get(\"ok\"):\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_weather\", \"final\": \"我现在联网查询失败了，请稍后再试。\", \"data\": rr}\n")
    rb.append(indent + "    fc = rr.get(\"forecast\") if isinstance(rr.get(\"forecast\"), list) else []\n")
    rb.append(indent + "    label = str((q.get(\"label\") or \"\")).strip()\n")
    rb.append("\n")
    rb.append(indent + "    # compute available local-date bounds from forecast list\n")
    rb.append(indent + "    avail = []\n")
    rb.append(indent + "    if isinstance(fc, list):\n")
    rb.append(indent + "        for it in fc:\n")
    rb.append(indent + "            d = _local_date_from_forecast_item(it, tzinfo)\n")
    rb.append(indent + "            if d is None:\n")
    rb.append(indent + "                continue\n")
    rb.append(indent + "            if d not in avail:\n")
    rb.append(indent + "                avail.append(d)\n")
    rb.append(indent + "    try:\n")
    rb.append(indent + "        avail = sorted(avail)\n")
    rb.append(indent + "    except Exception:\n")
    rb.append(indent + "        pass\n")
    rb.append(indent + "    min_d = avail[0] if isinstance(avail, list) and len(avail) > 0 else None\n")
    rb.append(indent + "    max_d = avail[-1] if isinstance(avail, list) and len(avail) > 0 else None\n")
    rb.append("\n")
    rb.append(indent + "    head = \"（\" + eid + \"）\"\n")
    rb.append("\n")
    rb.append(indent + "    if q.get(\"mode\") == \"range\":\n")
    rb.append(indent + "        start_d = q.get(\"start_date\")\n")
    rb.append(indent + "        if not isinstance(start_d, dt_date):\n")
    rb.append(indent + "            start_d = base_d\n")
    rb.append(indent + "        days_req = _safe_int(q.get(\"days\"), 3)\n")
    rb.append(indent + "        if days_req < 1:\n")
    rb.append(indent + "            days_req = 1\n")
    rb.append(indent + "        days_i = days_req\n")
    rb.append(indent + "        if days_i > 6:\n")
    rb.append(indent + "            days_i = 6\n")
    rb.append("\n")
    rb.append(indent + "        note = \"\"\n")
    rb.append(indent + "        # note for user-requested truncation (plugin capability)\n")
    rb.append(indent + "        if days_req != days_i:\n")
    rb.append(indent + "            note = \"（注意：该天气插件仅提供当天及未来5天，共6天预报）\"\n")
    rb.append("\n")
    rb.append(indent + "        # if actual forecast max date is earlier, clip again and override note\n")
    rb.append(indent + "        if isinstance(max_d, dt_date):\n")
    rb.append(indent + "            try:\n")
    rb.append(indent + "                from datetime import timedelta\n")
    rb.append(indent + "                end_req = start_d + timedelta(days=days_i - 1)\n")
    rb.append(indent + "            except Exception:\n")
    rb.append(indent + "                end_req = None\n")
    rb.append(indent + "            if isinstance(end_req, dt_date) and end_req > max_d:\n")
    rb.append(indent + "                note = \"（注意：该天气插件仅提供到 \" + str(max_d) + \" 的预报）\"\n")
    rb.append(indent + "                try:\n")
    rb.append(indent + "                    days_i2 = (max_d - start_d).days + 1\n")
    rb.append(indent + "                except Exception:\n")
    rb.append(indent + "                    days_i2 = days_i\n")
    rb.append(indent + "                if isinstance(days_i2, int) and days_i2 >= 1:\n")
    rb.append(indent + "                    days_i = days_i2\n")
    rb.append("\n")
    rb.append(indent + "        # display label correction when user asked for >6 days\n")
    rb.append(indent + "        label_show = label\n")
    rb.append(indent + "        if label_show and (\"接下来\" in label_show) and (days_req != days_i):\n")
    rb.append(indent + "            # keep simple: rebuild the label\n")
    rb.append(indent + "            if \"天气\" in label_show:\n")
    rb.append(indent + "                label_show = \"接下来\" + str(days_i) + \"天天气\"\n")
    rb.append(indent + "            else:\n")
    rb.append(indent + "                label_show = \"接下来\" + str(days_i) + \"天\"\n")
    rb.append("\n")
    rb.append(indent + "        summary = _summarise_weather_range(fc, start_d, days_i, tzinfo)\n")
    rb.append(indent + "        if label_show:\n")
    rb.append(indent + "            final = head + label_show + \"：\" + summary + note\n")
    rb.append(indent + "        else:\n")
    rb.append(indent + "            final = head + \"未来\" + str(days_i) + \"天天气：\" + summary + note\n")
    rb.append(indent + "        return {\"ok\": True, \"route_type\": \"structured_weather\", \"final\": final, \"data\": rr}\n")
    rb.append("\n")
    rb.append(indent + "    off = _safe_int(q.get(\"offset\"), 0)\n")
    rb.append(indent + "    td = q.get(\"target_date\")\n")
    rb.append(indent + "    if not isinstance(td, dt_date):\n")
    rb.append(indent + "        td = base_d\n")
    rb.append(indent + "        try:\n")
    rb.append(indent + "            from datetime import timedelta\n")
    rb.append(indent + "            td = base_d + timedelta(days=off)\n")
    rb.append(indent + "        except Exception:\n")
    rb.append(indent + "            td = base_d\n")
    rb.append("\n")
    rb.append(indent + "    it = _pick_daily_forecast_by_local_date(fc, td, tzinfo)\n")
    rb.append(indent + "    if it is None:\n")
    rb.append(indent + "        if isinstance(min_d, dt_date) and isinstance(max_d, dt_date):\n")
    rb.append(indent + "            final = head + (label + \"：无预报。\" if label else \"天气：无预报。\") + \"（可用范围：\" + str(min_d) + \" 到 \" + str(max_d) + \"）\"\n")
    rb.append(indent + "        else:\n")
    rb.append(indent + "            final = head + (label + \"：无预报。\" if label else \"天气：无预报。\") + \"（该天气插件通常仅提供当天及未来5天）\"\n")
    rb.append(indent + "    else:\n")
    rb.append(indent + "        final = head + (label + \"：\" if label else \"天气：\") + _summarise_weather_item(it)\n")
    rb.append(indent + "    return {\"ok\": True, \"route_type\": \"structured_weather\", \"final\": final, \"data\": rr}\n")

    lines = lines[:target_i] + rb + lines[end_i:]
    _write(APP, "".join(lines))
    print("OK: patched " + APP)

if __name__ == "__main__":
    main()
