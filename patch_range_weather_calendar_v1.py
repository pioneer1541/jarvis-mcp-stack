#!/usr/bin/env python3
# patch_range_weather_calendar_v1.py
import io
import os
import re
import shutil

APP = "app.py"
BAK = "app.py.bak.range_v1"


def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _find_route_request_block(lines):
    # find "def route_request(" at top-level
    start = None
    for i, ln in enumerate(lines):
        if re.match(r"^def[ \t]+route_request[ \t]*\(", ln):
            start = i
            break
    if start is None:
        raise RuntimeError("cannot find: def route_request(...):")

    # block ends when next top-level "def " or "@mcp.tool" (or EOF)
    end = None
    for j in range(start + 1, len(lines)):
        if re.match(r"^(def[ \t]+|@mcp\.tool)", lines[j]):
            end = j
            break
    if end is None:
        end = len(lines)
    return start, end


def _replace_branch(route_lines, branch_name, new_branch_lines):
    """
    Replace a branch that starts with:
      (if|elif) rt == "<branch_name>":
    Ends right before next (elif|if) rt == "...." at same indent.
    """
    # locate branch header
    hdr_idx = None
    hdr_indent = None
    hdr_pat = re.compile(r'^([ \t]*)(if|elif)[ \t]+rt[ \t]*==[ \t]*"' + re.escape(branch_name) + r'":[ \t]*$')
    for i, ln in enumerate(route_lines):
        m = hdr_pat.match(ln)
        if m:
            hdr_idx = i
            hdr_indent = m.group(1)
            break
    if hdr_idx is None:
        raise RuntimeError("cannot find branch: rt == \"" + branch_name + "\"")

    # find end (next if/elif rt == "...") with same indent
    end_idx = None
    next_pat = re.compile(r'^' + re.escape(hdr_indent) + r'(if|elif)[ \t]+rt[ \t]*==[ \t]*"[^"]+"\:[ \t]*$')
    for j in range(hdr_idx + 1, len(route_lines)):
        if next_pat.match(route_lines[j]):
            end_idx = j
            break
    if end_idx is None:
        # allow until end of function block
        end_idx = len(route_lines)

    # ensure new branch lines have correct indent (they should already)
    out = []
    out.extend(route_lines[:hdr_idx])
    out.extend(new_branch_lines)
    out.extend(route_lines[end_idx:])
    return out


def main():
    if not os.path.exists(APP):
        raise RuntimeError("missing " + APP)

    src = _read(APP)
    lines = src.splitlines(True)

    rs, re_ = _find_route_request_block(lines)
    route_lines = lines[rs:re_]

    # detect indent used inside route_request (first indent level)
    # e.g. function body indent is 4 spaces
    body_indent = "    "
    for ln in route_lines[1:]:
        if ln.strip():
            m = re.match(r"^([ \t]+)", ln)
            if m:
                body_indent = m.group(1)
            break

    # ---- new structured_weather branch ----
    bw = []
    bw.append(body_indent + 'if rt == "structured_weather":\n')
    bw.append(body_indent + "    try:\n")
    bw.append(body_indent + "        from datetime import datetime, date, timedelta\n")
    bw.append(body_indent + "        try:\n")
    bw.append(body_indent + "            from zoneinfo import ZoneInfo\n")
    bw.append(body_indent + "        except Exception:\n")
    bw.append(body_indent + "            ZoneInfo = None\n")
    bw.append(body_indent + "        txt = _ug_clean_unicode(user_text or \"\")\n")
    bw.append(body_indent + "        eid = (os.environ.get(\"HA_DEFAULT_WEATHER_ENTITY\") or \"\").strip()\n")
    bw.append(body_indent + "        if not eid:\n")
    bw.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": \"未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。\", \"error\": \"missing_default_weather_entity\"}\n")
    bw.append(body_indent + "        rr = ha_weather_forecast(eid, \"daily\")\n")
    bw.append(body_indent + "        if not rr.get(\"ok\"):\n")
    bw.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": \"我现在联网查询失败了，请稍后再试。\", \"data\": rr, \"error\": \"weather_fetch_failed\"}\n")
    bw.append(body_indent + "        fc = rr.get(\"forecast\")\n")
    bw.append(body_indent + "        if (not isinstance(fc, list)) or (len(fc) == 0):\n")
    bw.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": \"天气实体没有返回预报数据。\", \"data\": rr, \"error\": \"empty_forecast\"}\n")
    bw.append(body_indent + "        tzname = os.environ.get(\"TZ\") or \"Australia/Melbourne\"\n")
    bw.append(body_indent + "        tzinfo = None\n")
    bw.append(body_indent + "        if ZoneInfo is not None:\n")
    bw.append(body_indent + "            try:\n")
    bw.append(body_indent + "                tzinfo = ZoneInfo(tzname)\n")
    bw.append(body_indent + "            except Exception:\n")
    bw.append(body_indent + "                tzinfo = None\n")
    bw.append(body_indent + "        now_dt = datetime.now(tzinfo) if tzinfo else datetime.now()\n")
    bw.append(body_indent + "        today = now_dt.date()\n")

    bw.append(body_indent + "        def _dt_to_local_date(dt_str):\n")
    bw.append(body_indent + "            try:\n")
    bw.append(body_indent + "                s = str(dt_str or \"\").strip()\n")
    bw.append(body_indent + "                if not s:\n")
    bw.append(body_indent + "                    return None\n")
    bw.append(body_indent + "                s = s.replace(\"Z\", \"+00:00\")\n")
    bw.append(body_indent + "                dtx = datetime.fromisoformat(s)\n")
    bw.append(body_indent + "                if tzinfo and getattr(dtx, \"tzinfo\", None):\n")
    bw.append(body_indent + "                    dtx = dtx.astimezone(tzinfo)\n")
    bw.append(body_indent + "                elif tzinfo and getattr(dtx, \"tzinfo\", None) is None:\n")
    bw.append(body_indent + "                    dtx = dtx.replace(tzinfo=tzinfo)\n")
    bw.append(body_indent + "                return dtx.date()\n")
    bw.append(body_indent + "            except Exception:\n")
    bw.append(body_indent + "                return None\n")

    bw.append(body_indent + "        base_fc_date = _dt_to_local_date((fc[0] or {}).get(\"datetime\")) or today\n")

    # parse date/range/n-days
    bw.append(body_indent + "        def _parse_ymd(s0):\n")
    bw.append(body_indent + "            m = re.search(r\"(\\d{4})[\\-\\/\\.](\\d{1,2})[\\-\\/\\.](\\d{1,2})\", s0)\n")
    bw.append(body_indent + "            if not m:\n")
    bw.append(body_indent + "                return None\n")
    bw.append(body_indent + "            try:\n")
    bw.append(body_indent + "                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))\n")
    bw.append(body_indent + "            except Exception:\n")
    bw.append(body_indent + "                return None\n")

    bw.append(body_indent + "        def _parse_md(s0):\n")
    bw.append(body_indent + "            m = re.search(r\"(\\d{1,2})月(\\d{1,2})日\", s0)\n")
    bw.append(body_indent + "            if not m:\n")
    bw.append(body_indent + "                return None\n")
    bw.append(body_indent + "            try:\n")
    bw.append(body_indent + "                return date(int(now_dt.year), int(m.group(1)), int(m.group(2)))\n")
    bw.append(body_indent + "            except Exception:\n")
    bw.append(body_indent + "                return None\n")

    bw.append(body_indent + "        def _parse_range(s0):\n")
    bw.append(body_indent + "            # YYYY-MM-DD 到 YYYY-MM-DD\n")
    bw.append(body_indent + "            m = re.search(r\"(\\d{4}[\\-\\/\\.]\\d{1,2}[\\-\\/\\.]\\d{1,2}).{0,6}(到|至|\\-|~|—).{0,6}(\\d{4}[\\-\\/\\.]\\d{1,2}[\\-\\/\\.]\\d{1,2})\", s0)\n")
    bw.append(body_indent + "            if not m:\n")
    bw.append(body_indent + "                return None\n")
    bw.append(body_indent + "            d1 = _parse_ymd(m.group(1))\n")
    bw.append(body_indent + "            d2 = _parse_ymd(m.group(3))\n")
    bw.append(body_indent + "            if (d1 is None) or (d2 is None):\n")
    bw.append(body_indent + "                return None\n")
    bw.append(body_indent + "            if d2 < d1:\n")
    bw.append(body_indent + "                d1, d2 = d2, d1\n")
    bw.append(body_indent + "            return (d1, d2)\n")

    bw.append(body_indent + "        def _parse_ndays(s0):\n")
    bw.append(body_indent + "            m = re.search(r\"(接下来|接下來|未来|未來)\\s*(\\d{1,2})\\s*天\", s0)\n")
    bw.append(body_indent + "            if m:\n")
    bw.append(body_indent + "                try:\n")
    bw.append(body_indent + "                    n = int(m.group(2))\n")
    bw.append(body_indent + "                    if n < 1:\n")
    bw.append(body_indent + "                        n = 1\n")
    bw.append(body_indent + "                    if n > 14:\n")
    bw.append(body_indent + "                        n = 14\n")
    bw.append(body_indent + "                    return n\n")
    bw.append(body_indent + "                except Exception:\n")
    bw.append(body_indent + "                    return None\n")
    bw.append(body_indent + "            # “未来几天/接下来几天”默认 3\n")
    bw.append(body_indent + "            if re.search(r\"(未来|未來|接下来|接下來)几天\", s0):\n")
    bw.append(body_indent + "                return 3\n")
    bw.append(body_indent + "            return None\n")

    bw.append(body_indent + "        rng = _parse_range(txt)\n")
    bw.append(body_indent + "        start_date = None\n")
    bw.append(body_indent + "        days = 1\n")
    bw.append(body_indent + "        label = \"今天\"\n")

    bw.append(body_indent + "        if rng is not None:\n")
    bw.append(body_indent + "            start_date = rng[0]\n")
    bw.append(body_indent + "            days = int((rng[1] - rng[0]).days) + 1\n")
    bw.append(body_indent + "            label = str(rng[0]) + \" 到 \" + str(rng[1])\n")
    bw.append(body_indent + "        else:\n")
    bw.append(body_indent + "            nd = _parse_ndays(txt)\n")
    bw.append(body_indent + "            if nd is not None:\n")
    bw.append(body_indent + "                start_date = base_fc_date\n")
    bw.append(body_indent + "                days = nd\n")
    bw.append(body_indent + "                label = \"未来\" + str(nd) + \"天\"\n")
    bw.append(body_indent + "            else:\n")
    bw.append(body_indent + "                if (\"后天\" in txt) or (\"後天\" in txt):\n")
    bw.append(body_indent + "                    start_date = base_fc_date + timedelta(days=2)\n")
    bw.append(body_indent + "                    label = \"后天\"\n")
    bw.append(body_indent + "                elif \"明天\" in txt:\n")
    bw.append(body_indent + "                    start_date = base_fc_date + timedelta(days=1)\n")
    bw.append(body_indent + "                    label = \"明天\"\n")
    bw.append(body_indent + "                elif \"今天\" in txt or \"今天天气\" in txt:\n")
    bw.append(body_indent + "                    start_date = base_fc_date\n")
    bw.append(body_indent + "                    label = \"今天\"\n")
    bw.append(body_indent + "                else:\n")
    bw.append(body_indent + "                    d0 = _parse_ymd(txt) or _parse_md(txt)\n")
    bw.append(body_indent + "                    if d0 is not None:\n")
    bw.append(body_indent + "                        start_date = d0\n")
    bw.append(body_indent + "                        label = str(d0)\n")
    bw.append(body_indent + "                    else:\n")
    bw.append(body_indent + "                        start_date = base_fc_date\n")
    bw.append(body_indent + "                        label = \"今天\"\n")

    bw.append(body_indent + "        # map to forecast index (forecast list is ordered)\n")
    bw.append(body_indent + "        start_idx = int((start_date - base_fc_date).days)\n")
    bw.append(body_indent + "        note = \"\"\n")
    bw.append(body_indent + "        if start_idx < 0:\n")
    bw.append(body_indent + "            start_idx = 0\n")
    bw.append(body_indent + "            note = \"（注意：该日期早于可用预报范围，已返回最早可用预报）\"\n")
    bw.append(body_indent + "        if start_idx >= len(fc):\n")
    bw.append(body_indent + "            # out of range\n")
    bw.append(body_indent + "            avail_end = base_fc_date + timedelta(days=len(fc) - 1)\n")
    bw.append(body_indent + "            final = \"（\" + eid + \"）目前仅提供 \" + str(base_fc_date) + \" 到 \" + str(avail_end) + \" 的预报。\"\n")
    bw.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": final, \"data\": rr, \"range\": {\"start\": str(base_fc_date), \"end\": str(avail_end)}}\n")

    bw.append(body_indent + "        end_idx = start_idx + int(days)\n")
    bw.append(body_indent + "        if end_idx > len(fc):\n")
    bw.append(body_indent + "            end_idx = len(fc)\n")
    bw.append(body_indent + "            if days > 1:\n")
    bw.append(body_indent + "                note = \"（注意：可用预报天数不足，已返回可用范围内的预报）\"\n")

    bw.append(body_indent + "        sel = fc[start_idx:end_idx]\n")
    bw.append(body_indent + "        def _fmt_one(item, prefix):\n")
    bw.append(body_indent + "            cond = str((item or {}).get(\"condition\") or \"\")\n")
    bw.append(body_indent + "            tmax = (item or {}).get(\"temperature\")\n")
    bw.append(body_indent + "            tmin = (item or {}).get(\"templow\")\n")
    bw.append(body_indent + "            precip = (item or {}).get(\"precipitation\")\n")
    bw.append(body_indent + "            wind = (item or {}).get(\"wind_speed\")\n")
    bw.append(body_indent + "            parts = []\n")
    bw.append(body_indent + "            if cond:\n")
    bw.append(body_indent + "                parts.append(\"天气: \" + cond)\n")
    bw.append(body_indent + "            if (tmax is not None) and (tmin is not None):\n")
    bw.append(body_indent + "                try:\n")
    bw.append(body_indent + "                    parts.append(\"最高/最低: \" + str(round(float(tmax), 1)) + \"°C / \" + str(round(float(tmin), 1)) + \"°C\")\n")
    bw.append(body_indent + "                except Exception:\n")
    bw.append(body_indent + "                    parts.append(\"最高/最低: \" + str(tmax) + \" / \" + str(tmin))\n")
    bw.append(body_indent + "            if precip is not None:\n")
    bw.append(body_indent + "                parts.append(\"降雨: \" + str(precip))\n")
    bw.append(body_indent + "            if wind is not None:\n")
    bw.append(body_indent + "                parts.append(\"风速: \" + str(wind))\n")
    bw.append(body_indent + "            return prefix + \"，\".join(parts)\n")

    bw.append(body_indent + "        if len(sel) == 1:\n")
    bw.append(body_indent + "            summary = _fmt_one(sel[0], \"\")\n")
    bw.append(body_indent + "            final = \"（\" + eid + \"）\" + label + \"天气：\" + summary + (\" \" + note if note else \"\")\n")
    bw.append(body_indent + "        else:\n")
    bw.append(body_indent + "            out_list = []\n")
    bw.append(body_indent + "            for k, it in enumerate(sel):\n")
    bw.append(body_indent + "                d1 = base_fc_date + timedelta(days=start_idx + k)\n")
    bw.append(body_indent + "                prefix = str(d1.month) + \"/\" + str(d1.day) + \" \"\n")
    bw.append(body_indent + "                out_list.append(_fmt_one(it, prefix))\n")
    bw.append(body_indent + "            final = \"（\" + eid + \"）\" + label + \"天气：\" + \"；\".join(out_list) + (\" \" + note if note else \"\")\n")

    bw.append(body_indent + "        return {\"ok\": True, \"route_type\": rt, \"final\": final, \"data\": rr, \"query\": {\"start\": str(start_date), \"days\": int(days)}}\n")
    bw.append(body_indent + "    except Exception as e:\n")
    bw.append(body_indent + "        return {\"ok\": True, \"route_type\": rt, \"final\": \"天气解析失败。\", \"error\": \"weather_parse_failed\", \"message\": str(e)}\n")

    # ---- new structured_calendar branch ----
    bc = []
    bc.append(body_indent + 'elif rt == "structured_calendar":\n')
    bc.append(body_indent + "    try:\n")
    bc.append(body_indent + "        from datetime import datetime, date, timedelta\n")
    bc.append(body_indent + "        try:\n")
    bc.append(body_indent + "            from zoneinfo import ZoneInfo\n")
    bc.append(body_indent + "        except Exception:\n")
    bc.append(body_indent + "            ZoneInfo = None\n")
    bc.append(body_indent + "        txt = _ug_clean_unicode(user_text or \"\")\n")
    bc.append(body_indent + "        cal = (os.environ.get(\"HA_DEFAULT_CALENDAR_ENTITY\") or \"\").strip()\n")
    bc.append(body_indent + "        if not cal:\n")
    bc.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": \"未配置默认日历实体。请设置环境变量 HA_DEFAULT_CALENDAR_ENTITY。\", \"error\": \"missing_default_calendar_entity\"}\n")
    bc.append(body_indent + "        tzname = os.environ.get(\"TZ\") or \"Australia/Melbourne\"\n")
    bc.append(body_indent + "        tzinfo = None\n")
    bc.append(body_indent + "        if ZoneInfo is not None:\n")
    bc.append(body_indent + "            try:\n")
    bc.append(body_indent + "                tzinfo = ZoneInfo(tzname)\n")
    bc.append(body_indent + "            except Exception:\n")
    bc.append(body_indent + "                tzinfo = None\n")
    bc.append(body_indent + "        now_dt = datetime.now(tzinfo) if tzinfo else datetime.now()\n")
    bc.append(body_indent + "        today = now_dt.date()\n")

    bc.append(body_indent + "        def _parse_ymd(s0):\n")
    bc.append(body_indent + "            m = re.search(r\"(\\d{4})[\\-\\/\\.](\\d{1,2})[\\-\\/\\.](\\d{1,2})\", s0)\n")
    bc.append(body_indent + "            if not m:\n")
    bc.append(body_indent + "                return None\n")
    bc.append(body_indent + "            try:\n")
    bc.append(body_indent + "                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))\n")
    bc.append(body_indent + "            except Exception:\n")
    bc.append(body_indent + "                return None\n")

    bc.append(body_indent + "        def _parse_md(s0):\n")
    bc.append(body_indent + "            m = re.search(r\"(\\d{1,2})月(\\d{1,2})日\", s0)\n")
    bc.append(body_indent + "            if not m:\n")
    bc.append(body_indent + "                return None\n")
    bc.append(body_indent + "            try:\n")
    bc.append(body_indent + "                return date(int(now_dt.year), int(m.group(1)), int(m.group(2)))\n")
    bc.append(body_indent + "            except Exception:\n")
    bc.append(body_indent + "                return None\n")

    bc.append(body_indent + "        def _parse_range(s0):\n")
    bc.append(body_indent + "            m = re.search(r\"(\\d{4}[\\-\\/\\.]\\d{1,2}[\\-\\/\\.]\\d{1,2}).{0,6}(到|至|\\-|~|—).{0,6}(\\d{4}[\\-\\/\\.]\\d{1,2}[\\-\\/\\.]\\d{1,2})\", s0)\n")
    bc.append(body_indent + "            if not m:\n")
    bc.append(body_indent + "                return None\n")
    bc.append(body_indent + "            d1 = _parse_ymd(m.group(1))\n")
    bc.append(body_indent + "            d2 = _parse_ymd(m.group(3))\n")
    bc.append(body_indent + "            if (d1 is None) or (d2 is None):\n")
    bc.append(body_indent + "                return None\n")
    bc.append(body_indent + "            if d2 < d1:\n")
    bc.append(body_indent + "                d1, d2 = d2, d1\n")
    bc.append(body_indent + "            return (d1, d2)\n")

    bc.append(body_indent + "        def _parse_ndays(s0):\n")
    bc.append(body_indent + "            m = re.search(r\"(接下来|接下來|未来|未來)\\s*(\\d{1,2})\\s*天\", s0)\n")
    bc.append(body_indent + "            if m:\n")
    bc.append(body_indent + "                try:\n")
    bc.append(body_indent + "                    n = int(m.group(2))\n")
    bc.append(body_indent + "                    if n < 1:\n")
    bc.append(body_indent + "                        n = 1\n")
    bc.append(body_indent + "                    if n > 31:\n")
    bc.append(body_indent + "                        n = 31\n")
    bc.append(body_indent + "                    return n\n")
    bc.append(body_indent + "                except Exception:\n")
    bc.append(body_indent + "                    return None\n")
    bc.append(body_indent + "            if re.search(r\"(未来|未來|接下来|接下來)几天\", s0):\n")
    bc.append(body_indent + "                return 3\n")
    bc.append(body_indent + "            return None\n")

    bc.append(body_indent + "        label = \"今天\"\n")
    bc.append(body_indent + "        start_date = today\n")
    bc.append(body_indent + "        end_excl = today + timedelta(days=1)\n")

    bc.append(body_indent + "        rng = _parse_range(txt)\n")
    bc.append(body_indent + "        if rng is not None:\n")
    bc.append(body_indent + "            start_date = rng[0]\n")
    bc.append(body_indent + "            end_excl = rng[1] + timedelta(days=1)\n")
    bc.append(body_indent + "            label = str(rng[0]) + \" 到 \" + str(rng[1])\n")
    bc.append(body_indent + "        else:\n")
    bc.append(body_indent + "            nd = _parse_ndays(txt)\n")
    bc.append(body_indent + "            if nd is not None:\n")
    bc.append(body_indent + "                start_date = today\n")
    bc.append(body_indent + "                end_excl = today + timedelta(days=int(nd))\n")
    bc.append(body_indent + "                label = \"未来\" + str(nd) + \"天\"\n")
    bc.append(body_indent + "            else:\n")
    bc.append(body_indent + "                if (\"后天\" in txt) or (\"後天\" in txt):\n")
    bc.append(body_indent + "                    start_date = today + timedelta(days=2)\n")
    bc.append(body_indent + "                    end_excl = start_date + timedelta(days=1)\n")
    bc.append(body_indent + "                    label = \"后天\"\n")
    bc.append(body_indent + "                elif \"明天\" in txt:\n")
    bc.append(body_indent + "                    start_date = today + timedelta(days=1)\n")
    bc.append(body_indent + "                    end_excl = start_date + timedelta(days=1)\n")
    bc.append(body_indent + "                    label = \"明天\"\n")
    bc.append(body_indent + "                elif \"今天\" in txt:\n")
    bc.append(body_indent + "                    start_date = today\n")
    bc.append(body_indent + "                    end_excl = today + timedelta(days=1)\n")
    bc.append(body_indent + "                    label = \"今天\"\n")
    bc.append(body_indent + "                else:\n")
    bc.append(body_indent + "                    d0 = _parse_ymd(txt) or _parse_md(txt)\n")
    bc.append(body_indent + "                    if d0 is not None:\n")
    bc.append(body_indent + "                        start_date = d0\n")
    bc.append(body_indent + "                        end_excl = d0 + timedelta(days=1)\n")
    bc.append(body_indent + "                        label = str(d0)\n")

    bc.append(body_indent + "        sdt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=tzinfo) if tzinfo else datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)\n")
    bc.append(body_indent + "        edt = datetime(end_excl.year, end_excl.month, end_excl.day, 0, 0, 0, tzinfo=tzinfo) if tzinfo else datetime(end_excl.year, end_excl.month, end_excl.day, 0, 0, 0)\n")
    bc.append(body_indent + "        s_iso = sdt.isoformat()\n")
    bc.append(body_indent + "        e_iso = edt.isoformat()\n")
    bc.append(body_indent + "        r = ha_calendar_events(cal, s_iso, e_iso)\n")
    bc.append(body_indent + "        if not r.get(\"ok\"):\n")
    bc.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": \"我现在联网查询失败了，请稍后再试。\", \"data\": r, \"error\": \"calendar_fetch_failed\"}\n")
    bc.append(body_indent + "        items = r.get(\"data\")\n")
    bc.append(body_indent + "        if not isinstance(items, list):\n")
    bc.append(body_indent + "            items = []\n")
    bc.append(body_indent + "        if len(items) == 0:\n")
    bc.append(body_indent + "            final = label + \"没有日程。\"\n")
    bc.append(body_indent + "            return {\"ok\": True, \"route_type\": rt, \"final\": final, \"data\": r, \"range\": {\"start\": s_iso, \"end\": e_iso}}\n")

    bc.append(body_indent + "        multi_day = (end_excl - start_date).days > 1\n")
    bc.append(body_indent + "        out = []\n")
    bc.append(body_indent + "        for ev in items:\n")
    bc.append(body_indent + "            try:\n")
    bc.append(body_indent + "                summ = str((ev or {}).get(\"summary\") or \"\")\n")
    bc.append(body_indent + "                st = (ev or {}).get(\"start\") or {}\n")
    bc.append(body_indent + "                when = \"\"\n")
    bc.append(body_indent + "                day_prefix = \"\"\n")
    bc.append(body_indent + "                if isinstance(st, dict) and st.get(\"date\"):\n")
    bc.append(body_indent + "                    when = \"全天\"\n")
    bc.append(body_indent + "                    if multi_day:\n")
    bc.append(body_indent + "                        day_prefix = str(st.get(\"date\")) + \" \"\n")
    bc.append(body_indent + "                elif isinstance(st, dict) and st.get(\"dateTime\"):\n")
    bc.append(body_indent + "                    s1 = str(st.get(\"dateTime\") or \"\").replace(\"Z\", \"+00:00\")\n")
    bc.append(body_indent + "                    dt1 = datetime.fromisoformat(s1)\n")
    bc.append(body_indent + "                    if tzinfo and getattr(dt1, \"tzinfo\", None):\n")
    bc.append(body_indent + "                        dt1 = dt1.astimezone(tzinfo)\n")
    bc.append(body_indent + "                    if multi_day:\n")
    bc.append(body_indent + "                        day_prefix = str(dt1.date()) + \" \"\n")
    bc.append(body_indent + "                    when = dt1.strftime(\"%H:%M\")\n")
    bc.append(body_indent + "                piece = day_prefix + when + \" \" + summ\n")
    bc.append(body_indent + "                out.append(piece.strip())\n")
    bc.append(body_indent + "            except Exception:\n")
    bc.append(body_indent + "                continue\n")

    bc.append(body_indent + "        final = label + \"有 \" + str(len(out)) + \" 条日程：\" + \"；\".join(out)\n")
    bc.append(body_indent + "        return {\"ok\": True, \"route_type\": rt, \"final\": final, \"data\": r, \"range\": {\"start\": s_iso, \"end\": e_iso}}\n")
    bc.append(body_indent + "    except Exception as e:\n")
    bc.append(body_indent + "        return {\"ok\": True, \"route_type\": rt, \"final\": \"日历解析失败。\", \"error\": \"calendar_parse_failed\", \"message\": str(e)}\n")

    # apply replacements
    route_lines2 = _replace_branch(route_lines, "structured_weather", bw)
    route_lines3 = _replace_branch(route_lines2, "structured_calendar", bc)

    # write back
    new_lines = []
    new_lines.extend(lines[:rs])
    new_lines.extend(route_lines3)
    new_lines.extend(lines[re_:])

    if not os.path.exists(BAK):
        shutil.copyfile(APP, BAK)

    _write(APP, "".join(new_lines))
    print("patched_ok=1")
    print("backup=" + BAK)


if __name__ == "__main__":
    main()
