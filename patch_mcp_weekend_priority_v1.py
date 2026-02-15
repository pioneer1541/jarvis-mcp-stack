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

def main():
    src = _read()
    i = src.find(HELPER_BEGIN)
    j = src.find(HELPER_END)
    if i < 0 or j < 0 or j <= i:
        raise RuntimeError("Cannot find CN_RANGE_EXT_V1 helper markers.")
    blk = src[i:j+len(HELPER_END)]

    if "CN_RANGE_EXT_V1_WEEKEND_PRIORITY" in blk:
        print("Already patched (CN_RANGE_EXT_V1_WEEKEND_PRIORITY). No change.")
        return

    m_func = re.search(r"^def\s+_parse_cn_week_month_range\s*\(.*\)\s*:\s*$", blk, flags=re.M)
    if not m_func:
        raise RuntimeError("Cannot find def _parse_cn_week_month_range inside helper block.")

    sub = blk[m_func.end():]
    m_tnorm = re.search(r"^\s*t_norm\s*=\s*.+$", sub, flags=re.M)
    if not m_tnorm:
        raise RuntimeError("Cannot find t_norm line inside _parse_cn_week_month_range.")

    # Insert right after t_norm line (highest priority before week-range logic)
    insert_pos = i + m_func.end() + m_tnorm.end()

    add = (
        "\n"
        "    # CN_RANGE_EXT_V1_WEEKEND_PRIORITY: parse 周末 before whole-week rules\n"
        "    if \"周末\" in t_norm:\n"
        "        try:\n"
        "            from datetime import timedelta\n"
        "        except Exception:\n"
        "            timedelta = None\n"
        "        if timedelta is not None:\n"
        "            ws = _week_start_monday(now_d)\n"
        "            # 下周末 / 下星期周末\n"
        "            if (\"下周末\" in t_norm) or (\"下星期周末\" in t_norm) or (((\"下周\" in t_norm) or (\"下星期\" in t_norm)) and (\"周末\" in t_norm)):\n"
        "                ws2 = ws + timedelta(days=7)\n"
        "                sat = ws2 + timedelta(days=5)\n"
        "                sun = ws2 + timedelta(days=6)\n"
        "                return {\"mode\":\"range\",\"start_date\": sat, \"end_date\": sun, \"label\":\"下周末\"}\n"
        "            # 这个周末 / 这周末 / 本周末 / 周末：取“当前或即将到来的周末”\n"
        "            wd = int(now_d.weekday())\n"
        "            if wd == 5:\n"
        "                sat = now_d\n"
        "                sun = now_d + timedelta(days=1)\n"
        "            elif wd == 6:\n"
        "                sat = now_d - timedelta(days=1)\n"
        "                sun = now_d\n"
        "            else:\n"
        "                sat = now_d + timedelta(days=(5 - wd))\n"
        "                sun = sat + timedelta(days=1)\n"
        "            return {\"mode\":\"range\",\"start_date\": sat, \"end_date\": sun, \"label\":\"这个周末\"}\n"
        "\n"
    )

    out = src[:insert_pos] + add + src[insert_pos:]
    # add marker once in helper block header area
    out = out.replace(HELPER_BEGIN, HELPER_BEGIN + "\n# CN_RANGE_EXT_V1_WEEKEND_PRIORITY", 1)

    with io.open(APP + ".bak.weekend_priority_v1", "w", encoding="utf-8") as f:
        f.write(src)

    _write(out)
    print("Patched OK. Backup:", APP + ".bak.weekend_priority_v1")

if __name__ == "__main__":
    main()
