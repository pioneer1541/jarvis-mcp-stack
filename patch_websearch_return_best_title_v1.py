import sys

PATH = "app.py"

def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)

s = open(PATH, "r", encoding="utf-8", errors="replace").read()

anchor = "\"best_url\": (evidence.get(\"best_url\") if isinstance(evidence, dict) else None),"
if anchor not in s:
    die("Cannot locate web_search return best_url line")

# If already present, do nothing
if "\"best_title\"" in s[s.find("def web_search("):s.find("def web_answer(")]:
    print("No change: best_title already present in web_search return dict")
    sys.exit(0)

s = s.replace(
    anchor,
    anchor + "\n        \"best_title\": (evidence.get(\"best_title\") if isinstance(evidence, dict) else None),",
    1
)

open(PATH, "w", encoding="utf-8").write(s)
print("OK: added best_title to web_search return dict")
