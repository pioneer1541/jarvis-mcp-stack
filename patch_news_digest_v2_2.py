import re
import shutil
from datetime import datetime

APP = "app.py"

def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_v2_2." + ts
    shutil.copy2(p, bak)
    return bak

def patch_news_digest_signature(s):
    # Find def/async def news_digest(...) possibly with return type annotation
    # We avoid fragile anchors; we locate the function signature and edit only the parameter list.
    pat = re.compile(
        r"(^[ \t]*)(async[ \t]+def|def)[ \t]+news_digest[ \t]*\((?P<params>[\s\S]*?)\)[ \t]*(?:->[^:]+)?[ \t]*:",
        re.M
    )
    m = pat.search(s)
    if not m:
        return s, False, "news_digest definition not found"

    params = m.group("params")
    # If already compatible, do nothing
    if "prefer_lang" in params or "user_text" in params or "**kwargs" in params:
        return s, False, "news_digest already has prefer_lang/user_text/**kwargs"

    # Decide one-line vs multi-line
    indent = m.group(1)
    has_newline = ("\n" in params)

    if not has_newline:
        new_params = params.rstrip()
        if new_params.strip() == "":
            # empty param list
            new_params = "prefer_lang: str = 'zh', user_text: str = ''"
        else:
            new_params = new_params + ", prefer_lang: str = 'zh', user_text: str = ''"
        replacement = m.group(0).replace(params, new_params)
        s2 = s[:m.start()] + replacement + s[m.end():]
        return s2, True, "patched one-line signature"
    else:
        # Multi-line: append two new params lines before closing paren
        # Preserve indentation style (add 4 spaces after indent by default)
        add_indent = indent + "    "
        # Ensure params ends with newline
        p = params
        if not p.endswith("\n"):
            p = p + "\n"
        # Insert before trailing whitespace in params
        extra = add_indent + "prefer_lang: str = 'zh',\n" + add_indent + "user_text: str = '',\n"
        new_params = p + extra
        replacement = m.group(0).replace(params, new_params)
        s2 = s[:m.start()] + replacement + s[m.end():]
        return s2, True, "patched multi-line signature"

def main():
    with open(APP, "r", encoding="utf-8") as f:
        s = f.read()

    bak = backup_file(APP)

    s2, changed, msg = patch_news_digest_signature(s)

    if not changed:
        print("No change:", msg)
        print("Backup:", bak)
        return

    with open(APP, "w", encoding="utf-8") as f:
        f.write(s2)

    print("OK:", msg)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
