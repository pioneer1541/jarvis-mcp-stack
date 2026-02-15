import io
import re

PATH = "app.py"

def read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

s = read_text(PATH)

old_block = (
    "    # derive prefer_lang from HA-provided language (e.g., zh-CN) when present\n"
    "    lang = str(language or \"\").strip().lower()\n"
    "    prefer_lang = \"zh\" if lang.startswith(\"zh\") else \"en\"\n"
    "    # fallback: if HA didn't pass language, infer from user text\n"
    "    if (not lang) and (\"_has_cjk\" in globals()):\n"
    "        try:\n"
    "            prefer_lang = \"zh\" if _has_cjk(user_text) else \"en\"\n"
    "        except Exception:\n"
    "            prefer_lang = \"zh\"\n"
)

new_block = (
    "    # derive prefer_lang from HA-provided language (e.g., zh-CN/en-US). Fallback: detect CJK in user_text.\n"
    "    lang = str(language or \"\").strip().lower()\n"
    "    if lang.startswith(\"zh\"):\n"
    "        prefer_lang = \"zh\"\n"
    "    elif lang.startswith(\"en\"):\n"
    "        prefer_lang = \"en\"\n"
    "    else:\n"
    "        prefer_lang = \"zh\" if re.search(r\"[\\u4e00-\\u9fff]\", user_text or \"\") else \"en\"\n"
)

if old_block not in s:
    raise SystemExit("Cannot find the inserted prefer_lang block in route_request. Aborting.")

s = s.replace(old_block, new_block, 1)

write_text(PATH, s)
print("OK: patched route_request prefer_lang fallback (regex CJK).")
