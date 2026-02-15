import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

pat = re.compile(
    r"\n\s*# MCP_LANG_CLEAN_V3:.*?\n\s*except Exception:\n\s*pass\n",
    re.DOTALL
)
m = pat.search(s)
if not m:
    die("Cannot find MCP_LANG_CLEAN_V3 block to upgrade")

v4 = (
"\n    # MCP_LANG_CLEAN_V4: enforce answer language consistency (generic, zh-only output, no term mapping)\n"
"    try:\n"
"        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
"        if want_zh and isinstance(answer, str) and answer:\n"
"            x = answer\n"
"\n"
"            # 1) Remove urls\n"
"            x = re.sub(r\"https?://\\S+\", \"\", x)\n"
"\n"
"            # 2) Remove English month/day tokens\n"
"            x = re.sub(r\"\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\\b\", \"\", x, flags=re.I)\n"
"            x = re.sub(r\"\\b(?:mon|tue|tues|wed|thu|thur|fri|sat|sun)\\b\", \"\", x, flags=re.I)\n"
"\n"
"            # 3) Drop date-like numeric leftovers ANYWHERE, incl '11, 2025' / '11 2025' / '11-2025' / '2025-11'\n"
"            #    Do this BEFORE the final character whitelist, so commas/dots are still present for matching.\n"
"            x = re.sub(r\"\\b\\d{1,2}\\s*[,./\\-]\\s*\\d{4}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{1,2}\\s+\\d{4}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{4}\\s*[,./\\-]\\s*\\d{1,2}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{4}\\s+\\d{1,2}\\b\", \"\", x)\n"
"\n"
"            # 4) Remove remaining standalone English words (keep digits/punct/zh)\n"
"            #    This enforces zh-only voice output; if this is too aggressive later, we can relax it.\n"
"            x = re.sub(r\"\\b[A-Za-z]{2,}\\b\", \"\", x)\n"
"\n"
"            # 5) Keep Chinese, numbers, spaces, and common punctuation\n"
"            x = re.sub(r\"[^\\u4e00-\\u9fff0-9\\s，。！？；：、（）《》【】“”‘’…—\\-]\", \" \", x)\n"
"\n"
"            # 6) Cleanup spacing and punctuation gaps\n"
"            x = re.sub(r\"\\s{2,}\", \" \", x)\n"
"            x = re.sub(r\"\\s+([，。！？；：、])\", r\"\\1\", x)\n"
"            x = re.sub(r\"([，。！？；：、])\\s+\", r\"\\1\", x)\n"
"            x = x.strip()\n"
"\n"
"            answer = x\n"
"    except Exception:\n"
"        pass\n"
)

s = s[:m.start()] + v4 + s[m.end():]

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: upgraded to MCP_LANG_CLEAN_V4 (no term mapping)")
