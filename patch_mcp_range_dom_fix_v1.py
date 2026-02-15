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

def _find_between(src, a, b):
    i = src.find(a)
    j = src.find(b)
    if i < 0 or j < 0 or j <= i:
        return None, None, None
    return i, j, src[i:j+len(b)]

def main():
    src = _read()
    i, j, blk = _find_between(src, HELPER_BEGIN, HELPER_END)
    if blk is None:
        raise RuntimeError("Cannot find CN_RANGE_EXT_V1 helper block markers.")

    if "CN_RANGE_EXT_V1_DOM_FIX" in blk:
        print("Already patched (CN_RANGE_EXT_V1_DOM_FIX). No change.")
        return

    # locate inside helper block: function _parse_cn_week_month_range and the t_norm line
    m_func = re.search(r"^def\s+_parse_cn_week_month_range\s*\(.*\)\s*:\s*$", blk, flags=re.M)
    if not m_func:
        raise RuntimeError("Cannot find def _parse_cn_week_month_range inside helper block.")

    # Find t_norm assignment line after function start
    sub = blk[m_func.end():]
    m_tnorm = re.search(r"^\s*t_norm\s*=\s*.+$", sub, flags=re.M)
    if not m_tnorm:
        raise RuntimeError("Cannot find t_norm line inside _parse_cn_week_month_range.")

    insert_pos = i + m_func.end() + m_tnorm.end()

    # Insert day-of-month parsing logic right after normalization.
    # This must run before "下个月" whole-month range logic, to avoid grabbing "下个月3号日程" as whole month.
    add = (
        "\n"
        "    # CN_RANGE_EXT_V1_DOM_FIX: day-of-month parsing\n"
        "    def _mk_date(y, m, d):\n"
        "        try:\n"
        "            from datetime import date as _date\n"
        "            return _date(int(y), int(m), int(d))\n"
        "        except Exception:\n"
        "            return None\n"
        "\n"
        "    # 下个月N号 / 下月N号\n"
        "    m_dom_next = re.search(r\"(?<!\\d)(\\d{1,2})(号|日)(?!\\d)\", t_norm)\n"
        "    if m_dom_next and ((\"下个月\" in t_norm) or (\"下月\" in t_norm)):\n"
        "        dn = m_dom_next.group(1)\n"
        "        d_first = _add_months_first_day(now_d, 1)\n"
        "        if d_first is not None:\n"
        "            d_target = _mk_date(d_first.year, d_first.month, int(dn))\n"
        "            if d_target is not None:\n"
        "                return {\"mode\":\"single\", \"target_date\": d_target, \"label\":\"下个月\" + str(dn) + \"号\"}\n"
        "\n"
        "    # 本月N号 / 这个月N号\n"
        "    if m_dom_next and ((\"这个月\" in t_norm) or (\"本月\" in t_norm)):\n"
        "        dn = m_dom_next.group(1)\n"
        "        d_target = _mk_date(now_d.year, now_d.month, int(dn))\n"
        "        if d_target is not None:\n"
        "            return {\"mode\":\"single\", \"target_date\": d_target, \"label\":\"本月\" + str(dn) + \"号\"}\n"
        "\n"
        "    # 仅 N号 / N日（无显式月份）：若 dn >= 今天几号 -> 本月；否则 -> 下个月\n"
        "    if m_dom_next and (\"月\" not in t_norm) and (\"周\" not in t_norm):\n"
        "        dn = int(m_dom_next.group(1))\n"
        "        if dn >= int(now_d.day):\n"
        "            d_target = _mk_date(now_d.year, now_d.month, dn)\n"
        "            if d_target is not None:\n"
        "                return {\"mode\":\"single\", \"target_date\": d_target, \"label\": str(dn) + \"号\"}\n"
        "        else:\n"
        "            d_first = _add_months_first_day(now_d, 1)\n"
        "            if d_first is not None:\n"
        "                d_target = _mk_date(d_first.year, d_first.month, dn)\n"
        "                if d_target is not None:\n"
        "                    return {\"mode\":\"single\", \"target_date\": d_target, \"label\": str(dn) + \"号\"}\n"
    )

    out = src[:insert_pos] + add + src[insert_pos:]

    # tag marker inside helper block so we don't patch twice
    out = out.replace(HELPER_BEGIN, HELPER_BEGIN + "\n# CN_RANGE_EXT_V1_DOM_FIX", 1)

    with io.open(APP + ".bak.dom_fix_v1", "w", encoding="utf-8") as f:
        f.write(src)

    _write(out)
    print("Patched OK. Backup:", APP + ".bak.dom_fix_v1")

if __name__ == "__main__":
    main()
