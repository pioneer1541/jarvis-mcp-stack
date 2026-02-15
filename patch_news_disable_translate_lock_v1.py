import os
import sys
from datetime import datetime

TARGET = "app.py"
MARK = "NEWS_DISABLE_TRANSLATE_LOCK_V1"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_disable_lock_v1." + ts
    with open(p, "rb") as src:
        with open(bak, "wb") as dst:
            dst.write(src.read())
    return bak

def main():
    if not os.path.exists(TARGET):
        print("ERROR: not found:", TARGET)
        sys.exit(1)

    src = read_text(TARGET)
    if MARK in src:
        print("OK: already patched (marker found).")
        return

    lines = src.splitlines(True)

    # Anchor: final_voice assignment (we force title_voice BEFORE this line)
    anchor = None
    for i, ln in enumerate(lines):
        if 'ret["final_voice"] = _news__format_voice_miniflux' in ln:
            anchor = i
            break

    if anchor is None:
        print('ERROR: anchor not found: ret["final_voice"] = _news__format_voice_miniflux')
        sys.exit(2)

    # Preserve indentation
    indent = ""
    for ch in lines[anchor]:
        if ch == " ":
            indent += " "
        else:
            break

    block = []
    ap = block.append
    ap(indent + "# " + MARK + "\n")
    ap(indent + "# Translation is DISABLED by default. Only enable if NEWS_TRANSLATE_DISABLE is explicitly set to 0/false/off.\n")
    ap(indent + "try:\n")
    ap(indent + "    _raw = os.environ.get(\"NEWS_TRANSLATE_DISABLE\")\n")
    ap(indent + "    if _raw is None:\n")
    ap(indent + "        _dis = \"1\"  # default disabled\n")
    ap(indent + "    else:\n")
    ap(indent + "        _dis = str(_raw).strip().lower()\n")
    ap(indent + "    _enabled = (_dis in [\"0\", \"false\", \"no\", \"off\"])\n")
    ap(indent + "    if not _enabled:\n")
    ap(indent + "        _its = ret.get(\"items\") or []\n")
    ap(indent + "        if isinstance(_its, list):\n")
    ap(indent + "            for _it in _its:\n")
    ap(indent + "                if isinstance(_it, dict):\n")
    ap(indent + "                    _t = str(_it.get(\"title\") or \"\").strip()\n")
    ap(indent + "                    if _t:\n")
    ap(indent + "                        _it[\"title_voice\"] = _t\n")
    ap(indent + "except Exception:\n")
    ap(indent + "    pass\n\n")

    bak = backup(TARGET)
    new_src = "".join(lines[:anchor] + block + lines[anchor:])
    write_text(TARGET, new_src)

    print("OK: patched", TARGET)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
