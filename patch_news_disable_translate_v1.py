import os
import sys
from datetime import datetime

TARGET = "app.py"
MARK = "NEWS_DISABLE_TRANSLATE_V1"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_disable_translate_v1." + ts
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

    # Insert block right before: "if want_zh:"
    insert_at = None
    for i, ln in enumerate(lines):
        if ln.startswith("    if want_zh:"):
            insert_at = i
            break

    if insert_at is None:
        print("ERROR: cannot find anchor line: '    if want_zh:'")
        sys.exit(2)

    block = []
    ap = block.append
    ap("    # " + MARK + "\n")
    ap("    # If set, skip EN->ZH translation and output English titles directly (faster + avoid HA tool timeout)\n")
    ap("    try:\n")
    ap("        _dis = str(os.environ.get(\"NEWS_TRANSLATE_DISABLE\") or \"\").strip().lower()\n")
    ap("        if _dis in [\"1\", \"true\", \"yes\", \"on\"]:\n")
    ap("            want_zh = False\n")
    ap("    except Exception:\n")
    ap("        pass\n\n")

    bak = backup(TARGET)
    new_src = "".join(lines[:insert_at] + block + lines[insert_at:])
    write_text(TARGET, new_src)

    print("OK: patched", TARGET)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
