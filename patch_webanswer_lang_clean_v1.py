import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# Find a safe insertion point inside web_answer:
# After answer is assigned from best_snippet or extracted content, before return dict.
# We anchor to the line that sets answer_head or to 'answer = (best_snippet or "")' depending on baseline.
candidates = [
    "    answer = _mcp__clamp_text(answer, max_chars=800)\n",
    "    answer = _mcp__clamp_text(answer, max_chars=900)\n",
    "    answer = _mcp__clamp_text(answer, max_chars=700)\n",
]
pos = -1
for c in candidates:
    pos = s.find(c)
    if pos >= 0:
        pos = pos + len(c)
        break

if pos < 0:
    # fallback: locate return { in web_answer and insert right before it (still safe)
    wa_start = s.find("def web_answer(")
    if wa_start < 0:
        die("Cannot find def web_answer")
    ret = s.find("\n    return {", wa_start)
    if ret < 0:
        die("Cannot find return dict in web_answer")
    pos = ret

inject = (
"\n    # MCP_LANG_CLEAN_V1: enforce answer language consistency (generic)\n"
"    try:\n"
"        want_zh = True if str(language or \"\").strip().lower().startswith(\"zh\") else False\n"
"        if want_zh and isinstance(answer, str) and answer:\n"
"            # Remove urls\n"
"            answer = re.sub(r\"https?://\\S+\", \"\", answer)\n"
"            # Remove standalone english month/day tokens like 'Mar 11, 2025'\n"
"            answer = re.sub(r\"\\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)\\b\", \"\", answer, flags=re.I)\n"
"            answer = re.sub(r\"\\b(?:mon|tue|tues|wed|thu|thur|fri|sat|sun)\\b\", \"\", answer, flags=re.I)\n"
"            # Keep Chinese, numbers, whitespace, and common Chinese punctuation\n"
"            answer = re.sub(r\"[^\\u4e00-\\u9fff0-9\\s，。！？；：、（）《》【】“”‘’…—\\-]\", \"\", answer)\n"
"            # Normalize spaces\n"
"            answer = re.sub(r\"\\s{2,}\", \" \", answer).strip()\n"
"    except Exception:\n"
"        pass\n"
)

s = s[:pos] + inject + s[pos:]

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: inserted MCP_LANG_CLEAN_V1 into web_answer")
