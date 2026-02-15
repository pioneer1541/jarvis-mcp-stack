#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re

APP = "app.py"

def backup(path):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.brave_rate_limit_{1}".format(path, ts)
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    return bak, src

def main():
    bak, src = backup(APP)
    lines = src.splitlines(True)

    # 1) insert throttle helper right before "def _do_get(p, h):" inside Brave backend
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == "def _do_get(p, h):":
            idx = i
            break
    if idx is None:
        print("ERROR: cannot find 'def _do_get(p, h):' block. Abort.")
        print("Backup:", bak)
        return

    # avoid double insert
    look = "".join(lines[max(0, idx-40):idx+5])
    if "_throttle()" not in look:
        indent = re.match(r"^(\s*)", lines[idx]).group(1)
        ins = []
        ins.append(indent + "# brave QPS throttle (avoid 429 when multiple searches happen quickly)\n")
        ins.append(indent + "try:\n")
        ins.append(indent + "    import time as _time\n")
        ins.append(indent + "    import threading as _threading\n")
        ins.append(indent + "    if not hasattr(_searxng_search, \"_brave_lock\"):\n")
        ins.append(indent + "        _searxng_search._brave_lock = _threading.Lock()\n")
        ins.append(indent + "        _searxng_search._brave_last_ts = 0.0\n")
        ins.append(indent + "    _min_interval = float(os.getenv(\"BRAVE_MIN_INTERVAL\", \"1.2\"))\n")
        ins.append(indent + "    if _min_interval < 0.2:\n")
        ins.append(indent + "        _min_interval = 0.2\n")
        ins.append(indent + "    def _throttle():\n")
        ins.append(indent + "        with _searxng_search._brave_lock:\n")
        ins.append(indent + "            now = _time.time()\n")
        ins.append(indent + "            last = float(getattr(_searxng_search, \"_brave_last_ts\", 0.0))\n")
        ins.append(indent + "            wait = _min_interval - (now - last)\n")
        ins.append(indent + "            if wait > 0:\n")
        ins.append(indent + "                # keep it bounded to avoid very long blocking\n")
        ins.append(indent + "                if wait > 3.0:\n")
        ins.append(indent + "                    wait = 3.0\n")
        ins.append(indent + "                _time.sleep(wait)\n")
        ins.append(indent + "            _searxng_search._brave_last_ts = _time.time()\n")
        ins.append(indent + "except Exception:\n")
        ins.append(indent + "    def _throttle():\n")
        ins.append(indent + "        return\n")
        ins.append("\n")
        lines[idx:idx] = ins

    # 2) modify _do_get to call _throttle() before requests.get
    # find the 'return requests.get(' line within the next 10 lines
    for j in range(idx, min(len(lines), idx + 40)):
        if "return requests.get(" in lines[j]:
            ind2 = re.match(r"^(\s*)", lines[j]).group(1)
            # already patched?
            if j > 0 and "_throttle()" in lines[j-1]:
                break
            lines[j:j] = [ind2 + "_throttle()\n"]
            break

    # 3) expand 429 wait upper bound (currently often clamps to 2.0)
    # Replace:
    #   if wait_s > 2.0:
    #       wait_s = 2.0
    # With env-based clamp.
    changed_429 = False
    for i, ln in enumerate(lines):
        if ln.strip() == "if wait_s > 2.0:" and i + 1 < len(lines) and lines[i+1].strip() == "wait_s = 2.0":
            indent = re.match(r"^(\s*)", ln).group(1)
            repl = []
            repl.append(indent + "max_wait_s = float(os.getenv(\"BRAVE_MAX_RETRY_AFTER\", \"6.0\"))\n")
            repl.append(indent + "if max_wait_s < 1.0:\n")
            repl.append(indent + "    max_wait_s = 1.0\n")
            repl.append(indent + "if max_wait_s > 10.0:\n")
            repl.append(indent + "    max_wait_s = 10.0\n")
            repl.append(indent + "if wait_s > max_wait_s:\n")
            repl.append(indent + "    wait_s = max_wait_s\n")
            lines[i:i+2] = repl
            changed_429 = True
            break

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("OK patched:", APP)
    print("Backup:", bak)
    if not changed_429:
        print("NOTE: did not find the exact 'wait_s > 2.0' clamp; throttle still applied.")

if __name__ == "__main__":
    main()
