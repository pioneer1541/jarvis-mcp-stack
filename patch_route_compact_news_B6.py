#!/usr/bin/env python3
# patch_route_compact_news_B6.py
# Goal:
# 1) Compact HA-facing news response: only {ok, route_type, final} (drop data/metadata)
# 2) prefer_lang: if user_text contains CJK, force zh (avoid HA language mismatch)

import re
import shutil
import sys
from datetime import datetime

APP = "app.py"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak." + ts
    shutil.copy2(p, bak)
    return bak

def main():
    try:
        src = read_text(APP)
    except Exception as e:
        raise RuntimeError("Cannot read {0}: {1}".format(APP, e))

    changed = 0
    out = src

    # --- (A) prefer_lang block: force zh when user_text contains CJK ---
    # Looks for the existing block:
    # lang = ...
    # if lang.startswith("zh"):
    #   prefer_lang = "zh"
    # elif lang.startswith("en"):
    #   prefer_lang = "en"
    # else:
    #   prefer_lang = "zh" if re.search(...) else "en"
    #
    # Replace with:
    # if CJK in user_text: prefer_lang="zh"
    # elif lang startswith zh: zh
    # elif lang startswith en: en
    # else: en
    pat_lang = re.compile(
        r'(?m)^(\s*)lang\s*=\s*str\(\s*language\s*or\s*""\s*\)\.strip\(\)\.lower\(\)\s*\n'
        r'\1if\s+lang\.startswith\("zh"\)\s*:\s*\n'
        r'\1\s+prefer_lang\s*=\s*"zh"\s*\n'
        r'\1elif\s+lang\.startswith\("en"\)\s*:\s*\n'
        r'\1\s+prefer_lang\s*=\s*"en"\s*\n'
        r'\1else\s*:\s*\n'
        r'\1\s+prefer_lang\s*=\s*"zh"\s*if\s*re\.search\([^\)]*\)\s*else\s*"en"\s*\n'
    )

    def repl_lang(m):
        ind = m.group(1)
        return (
            ind + 'lang = str(language or "").strip().lower()\n'
            + ind + '# prefer Chinese if user asked in Chinese (avoid HA language mismatch)\n'
            + ind + 'if re.search(r"[\\u4e00-\\u9fff]", user_text or ""):\n'
            + ind + '    prefer_lang = "zh"\n'
            + ind + 'elif lang.startswith("zh"):\n'
            + ind + '    prefer_lang = "zh"\n'
            + ind + 'elif lang.startswith("en"):\n'
            + ind + '    prefer_lang = "en"\n'
            + ind + 'else:\n'
            + ind + '    prefer_lang = "en"\n'
        )

    out2, n2 = pat_lang.subn(repl_lang, out)
    if n2 > 0:
        out = out2
        changed += n2

    # --- (B) compact news returns: drop "data": rrn ---
    # success return
    pat_ret_ok = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"semi_structured_news"\s*,\s*"final"\s*:\s*final\s*,\s*"data"\s*:\s*rrn\s*\}\s*$'
    )
    out2, n2 = pat_ret_ok.subn(r'\1return {"ok": True, "route_type": "semi_structured_news", "final": final}', out)
    if n2 > 0:
        out = out2
        changed += n2

    # failure return
    pat_ret_fail = re.compile(
        r'(?m)^(\s*)return\s+\{\s*"ok"\s*:\s*True\s*,\s*"route_type"\s*:\s*"semi_structured_news"\s*,\s*"final"\s*:\s*"新闻检索失败或暂无结果。"\s*,\s*"data"\s*:\s*rrn\s*\}\s*$'
    )
    out2, n2 = pat_ret_fail.subn(r'\1return {"ok": True, "route_type": "semi_structured_news", "final": "新闻检索失败或暂无结果。"}', out)
    if n2 > 0:
        out = out2
        changed += n2

    if changed == 0:
        raise RuntimeError("No changes applied. Patterns not found. Please paste the route_request() news block and prefer_lang block for adjustment.")

    bak = backup_file(APP)
    write_text(APP, out)

    print("OK: patched {0}, backup: {1}, changes: {2}".format(APP, bak, changed))

if __name__ == "__main__":
    main()
