#!/usr/bin/env python3
# coding: utf-8

import re
import sys
from datetime import datetime

APP = "app.py"


def _die(msg):
    print("ERROR:", msg)
    sys.exit(1)


def _read():
    with open(APP, "r", encoding="utf-8") as f:
        return f.read()


def _write(s):
    with open(APP, "w", encoding="utf-8") as f:
        f.write(s)


def _replace_between(s, start_mark, end_mark, new_block):
    si = s.find(start_mark)
    if si < 0:
        _die("cannot find start_mark: " + start_mark)
    ei = s.find(end_mark, si)
    if ei < 0:
        _die("cannot find end_mark: " + end_mark)
    return s[:si] + new_block + s[ei + len(end_mark):]


def _ensure_cn_to_int(s):
    # insert helper before _weather_range_from_text if not present
    if "def _cn_to_int(" in s:
        return s

    m = re.search(r"^def _weather_range_from_text\s*\(", s, flags=re.M)
    if not m:
        # fallback: insert before route_request
        m = re.search(r"^def route_request\s*\(", s, flags=re.M)
    if not m:
        _die("cannot find insertion point for _cn_to_int()")

    helper = (
        "def _cn_to_int(s: str):\n"
        "    \"\"\"Convert simple Chinese numerals to int. Supports 0-99-ish.\"\"\"\n"
        "    try:\n"
        "        t = str(s or \"\").strip()\n"
        "    except Exception:\n"
        "        return None\n"
        "    if not t:\n"
        "        return None\n"
        "    if re.match(r\"^[0-9]+$\", t):\n"
        "        try:\n"
        "            return int(t)\n"
        "        except Exception:\n"
        "            return None\n"
        "    t = t.replace(\"兩\", \"两\")\n"
        "    digit = {\"零\": 0, \"一\": 1, \"二\": 2, \"两\": 2, \"三\": 3, \"四\": 4, \"五\": 5, \"六\": 6, \"七\": 7, \"八\": 8, \"九\": 9}\n"
        "    if t == \"十\":\n"
        "        return 10\n"
        "    if \"十\" in t:\n"
        "        parts = t.split(\"十\")\n"
        "        left = parts[0]\n"
        "        right = parts[1] if len(parts) > 1 else \"\"\n"
        "        if left == \"\":\n"
        "            a = 1\n"
        "        else:\n"
        "            a = digit.get(left)\n"
        "        if a is None:\n"
        "            return None\n"
        "        if right == \"\":\n"
        "            b = 0\n"
        "        else:\n"
        "            b = digit.get(right)\n"
        "            if b is None:\n"
        "                return None\n"
        "        return a * 10 + b\n"
        "    if t in digit:\n"
        "        return digit[t]\n"
        "    return None\n"
        "\n"
    )

    return s[:m.start()] + helper + s[m.start():]


def _patch_ndays_regex_in_range_parsers(s):
    # make "未来N天/接下来N天" accept chinese numerals
    # weather parser
    s = re.sub(
        r"(re\.search\(\s*r\"\\\(接下来\\\|接下來\\\|未来\\\|未來\\\)\\s*\\\(\\d\\{1,2\\}\\\)\\s*天\"\,\s*t\s*\))",
        "re.search(r\"(接下来|接下來|未来|未來)\\s*([0-9]{1,2}|[一二两三四五六七八九十]{1,3})\\s*天\", t)",
        s,
    )

    # calendar parser
    s = re.sub(
        r"(re\.search\(\s*r\"\\\(接下来\\\|接下來\\\|未来\\\|未來\\\)\\s*\\\(\\d\\{1,2\\}\\\)\\s*天\"\,\s*t\s*\))",
        "re.search(r\"(接下来|接下來|未来|未來)\\s*([0-9]{1,2}|[一二两三四五六七八九十]{1,3})\\s*天\", t)",
        s,
    )

    # replace int(m.group(2)) to _cn_to_int(m.group(2)) where possible (do minimal, only in obvious blocks)
    s = s.replace(
        "n = int(m.group(2))",
        "n = _cn_to_int(m.group(2))\n        if n is None:\n            n = 3",
    )
    return s


def _remove_route_request_local_date_import(s):
    # remove any local import that contains "date" inside route_request to avoid UnboundLocalError
    # (keep module-level imports)
    pattern = re.compile(r"^\s+from datetime import .*date.*\n", re.M)
    return pattern.sub("", s)


def _remove_duplicate_structured_weather_block(s):
    # remove the later hard-gate structured_weather block (the one starting with: "# Hard gate: Structured routes..."
    # but only remove the structured_weather part, leave other hard-gates intact.
    m = re.search(r"^\s*# Hard gate: Structured routes must NOT call web_answer/open_url\s*$", s, flags=re.M)
    if not m:
        return s

    # find the structured_weather sub-block under this section
    # We remove: "if rt == \"structured_weather\": ... return {...}" block.
    pat = re.compile(
        r"(\n\s*# Hard gate: Structured routes must NOT call web_answer/open_url\s*\n)"
        r"(\s*if rt == \"structured_weather\":\n(?:\s+.*\n)*?)"
        r"(?=\s*if rt == \"structured_calendar\"|\s*if rt == \"structured_holiday\"|\s*if rt == \"structured_state\"|\Z)",
        re.M,
    )
    new_s, n = pat.subn(r"\1", s)
    return new_s


def _patch_weather_range_v1_block(s):
    start_mark = "# --- WEATHER_RANGE_V1 ROUTE BEGIN ---"
    end_mark = "# --- WEATHER_RANGE_V1 ROUTE END ---"
    if (start_mark not in s) or (end_mark not in s):
        _die("cannot find WEATHER_RANGE_V1 markers, your file may differ. Please grep for WEATHER_RANGE_V1.")

    new_block = (
        "# --- WEATHER_RANGE_V1 ROUTE BEGIN ---\n"
        "    if rt == 'structured_weather':\n"
        "        default_weather = (os.environ.get('HA_DEFAULT_WEATHER_ENTITY') or '').strip()\n"
        "        if not default_weather:\n"
        "            return {\n"
        "                'ok': True,\n"
        "                'route_type': 'structured_weather',\n"
        "                'final': '未配置默认天气实体。请设置环境变量 HA_DEFAULT_WEATHER_ENTITY。',\n"
        "                'error': 'missing_default_weather_entity',\n"
        "            }\n"
        "\n"
        "        try:\n"
        "            tzinfo = _now_local().tzinfo\n"
        "        except Exception:\n"
        "            tzinfo = None\n"
        "\n"
        "        q = _weather_range_from_text(user_text)\n"
        "\n"
        "        r = ha_weather_forecast(default_weather, 'daily', 12)\n"
        "        if not r.get('ok'):\n"
        "            return {\n"
        "                'ok': True,\n"
        "                'route_type': 'structured_weather',\n"
        "                'final': '我现在联网查询失败了，请稍后再试。',\n"
        "                'data': r,\n"
        "            }\n"
        "\n"
        "        fc = r.get('forecast') if isinstance(r.get('forecast'), list) else []\n"
        "        label = str((q.get('label') or '')).strip()\n"
        "\n"
        "        now = _now_local()\n"
        "        base_d = dt_date(now.year, now.month, now.day)\n"
        "\n"
        "        fc_map = {}\n"
        "        try:\n"
        "            for it0 in fc:\n"
        "                if not isinstance(it0, dict):\n"
        "                    continue\n"
        "                d0 = _local_date_from_iso(it0.get('datetime'), tzinfo)\n"
        "                if d0 is None:\n"
        "                    continue\n"
        "                if d0 not in fc_map:\n"
        "                    fc_map[d0] = it0\n"
        "        except Exception:\n"
        "            fc_map = {}\n"
        "\n"
        "        def _pick(d1):\n"
        "            try:\n"
        "                if d1 in fc_map:\n"
        "                    return fc_map.get(d1)\n"
        "            except Exception:\n"
        "                pass\n"
        "            try:\n"
        "                ix = (d1 - base_d).days\n"
        "                if isinstance(ix, int) and (ix >= 0) and (ix < len(fc)):\n"
        "                    return fc[ix]\n"
        "            except Exception:\n"
        "                pass\n"
        "            try:\n"
        "                return _pick_daily_forecast_by_local_date(fc, d1, tzinfo)\n"
        "            except Exception:\n"
        "                return None\n"
        "\n"
        "        if q.get('mode') == 'range':\n"
        "            start_d = q.get('start_date')\n"
        "            if not isinstance(start_d, dt_date):\n"
        "                start_d = base_d\n"
        "            days = q.get('days')\n"
        "            try:\n"
        "                days_i = int(days)\n"
        "            except Exception:\n"
        "                days_i = 3\n"
        "            if days_i < 1:\n"
        "                days_i = 1\n"
        "            if days_i > 5:\n"
        "                days_i = 5\n"
        "\n"
        "            parts = []\n"
        "            for i in range(0, days_i):\n"
        "                d1 = start_d + timedelta(days=i)\n"
        "                it1 = _pick(d1)\n"
        "                parts.append(str(d1) + '：' + _summarise_weather_item(it1))\n"
        "            summary = '；'.join(parts)\n"
        "\n"
        "            head = '（' + default_weather + '）'\n"
        "            if label:\n"
        "                final = head + label + '天气：' + summary\n"
        "            else:\n"
        "                final = head + '未来' + str(days_i) + '天天气：' + summary\n"
        "\n"
        "            return {'ok': True, 'route_type': 'structured_weather', 'final': final, 'data': r}\n"
        "\n"
        "        offset = q.get('offset')\n"
        "        try:\n"
        "            off = int(offset)\n"
        "        except Exception:\n"
        "            off = 0\n"
        "\n"
        "        target_d = q.get('target_date')\n"
        "        if isinstance(target_d, dt_date):\n"
        "            td = target_d\n"
        "        else:\n"
        "            td = base_d + timedelta(days=off)\n"
        "\n"
        "        it = _pick(td)\n"
        "        summary = _summarise_weather_item(it)\n"
        "        head = '（' + default_weather + '）'\n"
        "        if label:\n"
        "            final = head + label + '天气：' + summary\n"
        "        else:\n"
        "            final = head + '天气：' + summary\n"
        "\n"
        "        return {'ok': True, 'route_type': 'structured_weather', 'final': final, 'data': r}\n"
        "# --- WEATHER_RANGE_V1 ROUTE END ---"
    )

    return _replace_between(s, start_mark, end_mark, new_block)


def main():
    s = _read()

    s = _remove_route_request_local_date_import(s)
    s = _ensure_cn_to_int(s)
    s = _patch_ndays_regex_in_range_parsers(s)
    s = _remove_duplicate_structured_weather_block(s)
    s = _patch_weather_range_v1_block(s)

    _write(s)
    print("patched_ok=1")


if __name__ == "__main__":
    main()
