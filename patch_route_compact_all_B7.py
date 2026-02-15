#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# patch_route_compact_all_B7.py
# - Default: route_request returns minimal {ok, route_type, final}
# - Debug: ROUTE_RETURN_DATA=1 keeps extra fields (data/range/next/entity_id)
# - Only patches inside def route_request(...)

import io
import os
import re
import time

APP = "app.py"
MARKER = "# ROUTE_COMPACT_ALL_B7"

def _read(p):
    with io.open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()

def _write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.before_route_compact_all_B7_{1}".format(p, ts)
    with io.open(p, "r", encoding="utf-8", newline="") as fsrc:
        with io.open(bak, "w", encoding="utf-8", newline="") as fdst:
            fdst.write(fsrc.read())
    return bak

def _find_route_request_block(src):
    key = "def route_request("
    p0 = src.find(key)
    if p0 < 0:
        raise RuntimeError("Cannot find route_request() via 'def route_request('")

    # end: next decorator or next top-level def (col 0), whichever comes first
    candidates = []
    m1 = re.search(r"\n@[^ \t]", src[p0:])
    if m1:
        candidates.append(p0 + m1.start())
    m2 = re.search(r"\n(def|class)\s+[^ \t]", src[p0:])
    if m2:
        candidates.append(p0 + m2.start())

    if candidates:
        p1 = min(candidates)
    else:
        p1 = len(src)

    return p0, p1

def _ensure_return_data_flag(block):
    # if already has a _route_return_data assignment, do nothing
    if " _route_return_data " in block or "_route_return_data=" in block or "_route_return_data =" in block:
        return block, 0

    # insert right after def line
    p_def = block.find("def route_request(")
    if p_def < 0:
        return block, 0
    p_nl = block.find("\n", p_def)
    if p_nl < 0:
        return block, 0

    insert = (
        "    {0}\n"
        "    # ROUTE_RETURN_DATA=1 to include raw debug payload in route_request outputs\n"
        "    _route_return_data = str(os.environ.get(\"ROUTE_RETURN_DATA\") or \"\").strip().lower() in (\"1\",\"true\",\"yes\",\"y\")\n"
        "\n"
    ).format(MARKER)

    return block[:p_nl+1] + insert + block[p_nl+1:], 1

def _apply_replacements(block):
    changed = 0
    out = block

    # structured_weather: {"ok": True, "route_type": "structured_weather", "final": X, "data": Y}
    pat_weather = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"structured_weather"\s*,\s*"final"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"data"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\s*$'
    )
    def repl_weather(m):
        ind, v_final, v_data = m.group(1), m.group(2), m.group(3)
        return (
            ind + 'ret = {"ok": True, "route_type": "structured_weather", "final": ' + v_final + '}\n'
            + ind + 'if _route_return_data:\n'
            + ind + '    ret["data"] = ' + v_data + '\n'
            + ind + 'return ret'
        )
    out2, n2 = pat_weather.subn(repl_weather, out)
    out, changed = out2, changed + n2

    # structured_calendar: ... "final": X, "data": Y, "range": { ... }
    pat_cal = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"structured_calendar"\s*,\s*"final"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"data"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"range"\s*:\s*(\{[^\}]*\})\s*\}\s*$'
    )
    def repl_cal(m):
        ind, v_final, v_data, v_range = m.group(1), m.group(2), m.group(3), m.group(4)
        return (
            ind + 'ret = {"ok": True, "route_type": "structured_calendar", "final": ' + v_final + '}\n'
            + ind + 'if _route_return_data:\n'
            + ind + '    ret["data"] = ' + v_data + '\n'
            + ind + '    ret["range"] = ' + v_range + '\n'
            + ind + 'return ret'
        )
    out2, n2 = pat_cal.subn(repl_cal, out)
    out, changed = out2, changed + n2

    # structured_holiday: ... "final": X, "data": Y, "next": Z
    pat_hol = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"structured_holiday"\s*,\s*"final"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"data"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"next"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\s*$'
    )
    def repl_hol(m):
        ind, v_final, v_data, v_next = m.group(1), m.group(2), m.group(3), m.group(4)
        return (
            ind + 'ret = {"ok": True, "route_type": "structured_holiday", "final": ' + v_final + '}\n'
            + ind + 'if _route_return_data:\n'
            + ind + '    ret["data"] = ' + v_data + '\n'
            + ind + '    ret["next"] = ' + v_next + '\n'
            + ind + 'return ret'
        )
    out2, n2 = pat_hol.subn(repl_hol, out)
    out, changed = out2, changed + n2

    # structured_state: ... "final": X, "data": Y, "entity_id": Z
    pat_state = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"structured_state"\s*,\s*"final"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"data"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*"entity_id"\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\s*$'
    )
    def repl_state(m):
        ind, v_final, v_data, v_eid = m.group(1), m.group(2), m.group(3), m.group(4)
        return (
            ind + 'ret = {"ok": True, "route_type": "structured_state", "final": ' + v_final + '}\n'
            + ind + 'if _route_return_data:\n'
            + ind + '    ret["data"] = ' + v_data + '\n'
            + ind + '    ret["entity_id"] = ' + v_eid + '\n'
            + ind + 'return ret'
        )
    out2, n2 = pat_state.subn(repl_state, out)
    out, changed = out2, changed + n2

    return out, changed

def main():
    if not os.path.exists(APP):
        raise RuntimeError("app.py not found in current directory")

    src = _read(APP)
    if MARKER in src:
        print("Already patched:", MARKER)
        return

    p0, p1 = _find_route_request_block(src)
    block = src[p0:p1]

    block2, nflag = _ensure_return_data_flag(block)
    block3, nrep = _apply_replacements(block2)

    if (nflag + nrep) == 0:
        raise RuntimeError("No changes applied inside route_request(). Patterns not found; please paste the 4 return lines for weather/calendar/holiday/state.")

    bak = _backup(APP)
    out = src[:p0] + block3 + src[p1:]
    _write(APP, out)

    print("OK patched. backup=", bak, "flag_inserted=", nflag, "returns_patched=", nrep)

if __name__ == "__main__":
    main()
