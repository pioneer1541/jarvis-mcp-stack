import os
import sys
import re
from datetime import datetime

TARGET = "app.py"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_title_voice_sync_v1." + ts
    with open(p, "rb") as src:
        with open(bak, "wb") as dst:
            dst.write(src.read())
    return bak

def main():
    if not os.path.exists(TARGET):
        print("ERROR: not found:", TARGET)
        sys.exit(1)

    src = read_text(TARGET)
    lines = src.splitlines(True)

    # anchor: the line that sets final_voice using _news__format_voice_miniflux
    anchor_idx = None
    for i, ln in enumerate(lines):
        if 'ret["final_voice"] = _news__format_voice_miniflux' in ln:
            anchor_idx = i
            break

    if anchor_idx is None:
        print('ERROR: anchor not found: ret["final_voice"] = _news__format_voice_miniflux')
        sys.exit(2)

    # avoid double patch
    for j in range(anchor_idx, min(anchor_idx + 80, len(lines))):
        if "NEWS_SYNC_TITLE_VOICE_FROM_FINAL_VOICE" in lines[j]:
            print("OK: already patched (marker found).")
            sys.exit(0)

    indent = re.match(r"^(\s*)", lines[anchor_idx]).group(1)

    block = []
    ap = block.append

    ap("\n")
    ap(indent + "# NEWS_SYNC_TITLE_VOICE_FROM_FINAL_VOICE\n")
    ap(indent + "try:\n")
    ap(indent + "    _fv = str(ret.get(\"final_voice\") or \"\").strip()\n")
    ap(indent + "    _its = ret.get(\"items\")\n")
    ap(indent + "    if _fv and isinstance(_its, list) and _its:\n")
    ap(indent + "        _tlist = []\n")
    ap(indent + "        for _ln in [x.strip() for x in _fv.splitlines() if str(x or \"\").strip()]:\n")
    ap(indent + "            _m = re.match(r\"^\\s*\\d+\\)\\s*(.+?)\\s*$\", _ln)\n")
    ap(indent + "            if _m:\n")
    ap(indent + "                _t = str(_m.group(1) or \"\").strip()\n")
    ap(indent + "                if _t:\n")
    ap(indent + "                    _tlist.append(_t)\n")
    ap(indent + "        _n = min(len(_tlist), len(_its))\n")
    ap(indent + "        for _i in range(_n):\n")
    ap(indent + "            try:\n")
    ap(indent + "                if isinstance(_its[_i], dict) and _tlist[_i]:\n")
    ap(indent + "                    _its[_i][\"title_voice\"] = _tlist[_i]\n")
    ap(indent + "            except Exception:\n")
    ap(indent + "                pass\n")
    ap(indent + "except Exception:\n")
    ap(indent + "    pass\n")

    bak = backup(TARGET)
    new_lines = lines[:anchor_idx + 1] + block + lines[anchor_idx + 1:]
    write_text(TARGET, "".join(new_lines))

    print("OK: patched", TARGET)
    print("Backup:", bak)
    print("Inserted after line:", anchor_idx + 1)

if __name__ == "__main__":
    main()
