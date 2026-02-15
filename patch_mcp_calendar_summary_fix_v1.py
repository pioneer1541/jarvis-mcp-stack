import re

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _find_func_block(src, func_name):
    key = "def " + func_name + "("
    s = src.find(key)
    if s < 0:
        return None
    m = re.search(r"\n(?=def\s+[A-Za-z0-9_]+\s*\()", src[s+1:])
    if m:
        e = s + 1 + m.start()
        return (s, e)
    return (s, len(src))

def main():
    src = _read(APP)
    blk = _find_func_block(src, "_summarise_calendar_events")
    if blk is None:
        raise RuntimeError("Cannot find function _summarise_calendar_events in app.py")

    new_block = (
        "def _summarise_calendar_events(events):\n"
        "    if (not isinstance(events, list)) or (len(events) == 0):\n"
        "        return \"没有日程。\"\n"
        "    parts = []\n"
        "    lim = 6\n"
        "    for it in events[:lim]:\n"
        "        if not isinstance(it, dict):\n"
        "            continue\n"
        "        summ = str(it.get(\"summary\") or \"\").strip()\n"
        "        st = it.get(\"start\") or {}\n"
        "        if isinstance(st, dict) and st.get(\"date\"):\n"
        "            ds = str(st.get(\"date\") or \"\").strip()\n"
        "            if ds:\n"
        "                parts.append(ds + \" 全天 \" + summ)\n"
        "            else:\n"
        "                parts.append(\"全天 \" + summ)\n"
        "        else:\n"
        "            dt = None\n"
        "            if isinstance(st, dict):\n"
        "                dt = st.get(\"dateTime\") or st.get(\"datetime\")\n"
        "            if dt:\n"
        "                dts = str(dt)\n"
        "                # Best-effort format: YYYY-MM-DD HH:MM\n"
        "                if len(dts) >= 16 and \"T\" in dts:\n"
        "                    d = dts[:10]\n"
        "                    tm = dts[11:16]\n"
        "                    parts.append(d + \" \" + tm + \" \" + summ)\n"
        "                else:\n"
        "                    parts.append(dts + \" \" + summ)\n"
        "            else:\n"
        "                parts.append(summ)\n"
        "    if len(events) > lim:\n"
        "        parts.append(\"等共 \" + str(len(events)) + \" 条\")\n"
        "    return \"；\".join([p for p in parts if p]) + \"。\"\n"
    )

    out = src[:blk[0]] + new_block + src[blk[1]:]
    _write(APP, out)
    print("OK: patched " + APP)

if __name__ == "__main__":
    main()
