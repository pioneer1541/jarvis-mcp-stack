import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()

ws_start = s.find("def web_search(")
if ws_start < 0:
    die("Cannot find def web_search(")
ws_end = s.find("def open_url_extract(", ws_start)
if ws_end < 0:
    die("Cannot find end of web_search (def open_url_extract)")

ws = s[ws_start:ws_end]
if "\"best_title\":" in ws and "\"best_title\": (evidence.get(\"best_title\")" in ws:
    print("No change: best_title already returned by web_search")
    sys.exit(0)

anchor = "        \"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),\n"
if anchor not in ws:
    die("Cannot locate web_search return best_url line")

ws2 = ws.replace(
    anchor,
    anchor + "        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),\n",
    1
)

out = s[:ws_start] + ws2 + s[ws_end:]
open(PATH, "w", encoding="utf-8").write(out)
print("OK: web_search now returns best_title")
