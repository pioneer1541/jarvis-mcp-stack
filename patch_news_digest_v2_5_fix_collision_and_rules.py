import re
from datetime import datetime

APP = "app.py"

def backup(path: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_v2_5." + ts
    with open(path, "r", encoding="utf-8") as f:
        s = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(s)
    return bak

def main():
    with open(APP, "r", encoding="utf-8") as f:
        s = f.read()

    # 1) Rename the "new" _news__build_query(terms, rules_zh, rules_en) to avoid overriding legacy one
    #    Match by presence of terms + rules_zh + rules_en in signature.
    pat_def = re.compile(
        r'(^def\s+)_news__build_query(\s*\(\s*[^)]*?\bterms\b[^)]*?\brules_zh\b[^)]*?\brules_en\b[^)]*?\)\s*:)',
        re.MULTILINE
    )
    m = pat_def.search(s)
    if not m:
        raise SystemExit("ERROR: cannot find the v3 _news__build_query(terms, rules_zh, rules_en) definition")

    # Only rename if not already renamed
    if "_news_v3__build_query" not in s[m.start():m.start()+200]:
        s = pat_def.sub(r"\1_news_v3__build_query\2", s, count=1)

    # 2) Update calls that pass `terms` to use _news_v3__build_query(...)
    #    Avoid touching legacy calls that use (category, user_text, lang)
    s = re.sub(r"\b_news__build_query\s*\(\s*terms\b", "_news_v3__build_query(terms", s)

    # 3) Inside _news_v3__build_query: make rules entries tolerant of dict OR str
    #    Replace the specific loop block that assumes dict .get("domain")
    #    We keep indentation via a capture group.
    pat_loop = re.compile(
        r'(?m)^(\s*)for\s+r\s+in\s+\(__coerce_list\(rules_zh\)\s*\+\s*__coerce_list\(rules_en\)\)\s*:\s*\n'
        r'\1\s+dom\s*=\s*\(r\.get\("domain"\)\s*or\s*""\)\.strip\(\)\s*\n'
        r'\1\s+if\s+dom\s*:\s*\n'
        r'\1\s+sites\.append\("site:"\s*\+\s*dom\)\s*\n'
    )
    repl_loop = (
        r'\1for r in (__coerce_list(rules_zh) + __coerce_list(rules_en)):\n'
        r'\1    dom = ""\n'
        r'\1    if isinstance(r, dict):\n'
        r'\1        dom = (r.get("domain") or "").strip()\n'
        r'\1    elif isinstance(r, str):\n'
        r'\1        dom = r.strip()\n'
        r'\1    else:\n'
        r'\1        dom = str(r).strip()\n'
        r'\1    if dom:\n'
        r'\1        sites.append("site:" + dom)\n'
    )
    s2, n = pat_loop.subn(repl_loop, s, count=1)
    if n == 0:
        # If the exact block doesn't match, fail loudly to avoid silent partial patch.
        raise SystemExit("ERROR: cannot find expected loop block inside _news_v3__build_query to patch")
    s = s2

    bak = backup(APP)
    with open(APP, "w", encoding="utf-8") as f:
        f.write(s)

    print("Backup:", bak)
    print("OK: renamed v3 _news__build_query -> _news_v3__build_query and patched rules handling")

if __name__ == "__main__":
    main()
