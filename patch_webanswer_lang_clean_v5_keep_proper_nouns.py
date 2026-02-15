import sys
import re

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()
orig = s

# Replace the existing MCP_LANG_CLEAN_V4 block
pat = re.compile(
    r"\n\s*# MCP_LANG_CLEAN_V4:.*?\n\s*except Exception:\n\s*pass\n",
    re.DOTALL
)
m = pat.search(s)
if not m:
    die("Cannot find MCP_LANG_CLEAN_V4 block to upgrade")

v5 = (
"\n    # MCP_LANG_CLEAN_V5: zh output, keep English proper nouns, remove English stopwords (generic)\n"
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
"            x = re.sub(r\"\\b\\d{1,2}\\s*[,./\\-]\\s*\\d{4}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{1,2}\\s+\\d{4}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{4}\\s*[,./\\-]\\s*\\d{1,2}\\b\", \"\", x)\n"
"            x = re.sub(r\"\\b\\d{4}\\s+\\d{1,2}\\b\", \"\", x)\n"
"\n"
"            # 4) Remove English stopwords (keep English proper nouns/terms)\n"
"            #    Include on/off to avoid mixing control words in zh output.\n"
"            stop = [\n"
"                \"a\",\"an\",\"the\",\"and\",\"or\",\"but\",\"if\",\"then\",\"else\",\"for\",\"to\",\"of\",\"in\",\"on\",\"off\",\"at\",\"by\",\"with\",\"from\",\"as\",\n"
"                \"is\",\"are\",\"was\",\"were\",\"be\",\"been\",\"being\",\"it\",\"its\",\"they\",\"them\",\"their\",\"i\",\"we\",\"you\",\"your\",\"my\",\"our\",\n"
"                \"this\",\"that\",\"these\",\"those\",\"there\",\"here\",\"so\",\"not\",\"no\",\"yes\",\"ok\",\"okay\",\"also\",\"still\",\"just\",\"only\",\"all\",\"any\",\n"
"                \"can\",\"could\",\"should\",\"would\",\"will\",\"may\",\"might\",\"do\",\"does\",\"did\",\"done\",\"have\",\"has\",\"had\",\"into\",\"about\",\"than\",\n"
"                \"because\",\"while\",\"when\",\"where\",\"what\",\"who\",\"whom\",\"which\",\"how\",\"why\",\"up\",\"down\",\"over\",\"under\",\"again\",\"once\"\n"
"            ]\n"
"            stop_pat = r\"\\\\b(?:\" + \"|\".join([re.escape(w) for w in stop]) + r\")\\\\b\"\n"
"            x = re.sub(stop_pat, \"\", x, flags=re.I)\n"
"\n"
"            # 5) Keep: Chinese + English letters + numbers + spaces + punctuation\n"
"            x = re.sub(r\"[^\\u4e00-\\u9fffA-Za-z0-9\\s，。！？；：、（）《》【】“”‘’…—\\-\\.,!?;:\\(\\)\\[\\]]\", \" \", x)\n"
"\n"
"            # 6) Cleanup spacing and punctuation gaps\n"
"            x = re.sub(r\"\\s{2,}\", \" \", x)\n"
"            x = re.sub(r\"\\s+([，。！？；：、\\.,!?;:])\", r\"\\1\", x)\n"
"            x = re.sub(r\"([，。！？；：、\\.,!?;:])\\s+\", r\"\\1\", x)\n"
"            x = x.strip()\n"
"\n"
"            answer = x\n"
"    except Exception:\n"
"        pass\n"
)

s = s[:m.start()] + v5 + s[m.end():]

if s == orig:
    die("Patch produced no changes (unexpected).")

open(PATH, "w", encoding="utf-8").write(s)
print("OK: upgraded to MCP_LANG_CLEAN_V5 (keep proper nouns)")
