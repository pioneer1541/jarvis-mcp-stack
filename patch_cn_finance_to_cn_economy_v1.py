import os
import sys
from datetime import datetime

TARGET = "app.py"
MARK = "PATCH_CN_FINANCE_TO_CN_ECONOMY_V1"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.cn_economy_v1." + ts
    with open(p, "rb") as src, open(bak, "wb") as dst:
        dst.write(src.read())
    return bak

def main():
    if not os.path.exists(TARGET):
        print("ERROR: not found:", TARGET)
        return 1

    s = read_text(TARGET)
    if MARK in s:
        print("OK: already patched (marker found).")
        return 0

    # Replace exact token occurrences.
    # We avoid touching longer identifiers by using a conservative approach:
    # Replace "cn_finance" only when it appears as a quoted string or dict key-ish context.
    # Still do a broad replace because category keys are typically string literals.
    before = s

    # Common patterns: "cn_finance" / 'cn_finance'
    s = s.replace('"cn_finance"', '"cn_economy"')
    s = s.replace("'cn_finance'", "'cn_economy'")

    # Also handle cases like cn_finance: in YAML-ish strings inside docs or maps
    # but keep it conservative by targeting word boundary-ish contexts.
    s = s.replace("cn_finance:", "cn_economy:")

    # Marker header
    if s != before:
        s = "# " + MARK + "\n" + s
        bak = backup(TARGET)
        write_text(TARGET, s)
        print("OK: patched app.py")
        print("Backup:", bak)
        return 0

    print("WARN: no occurrences found to replace.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
