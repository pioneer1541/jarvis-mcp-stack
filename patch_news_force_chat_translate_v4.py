import os
import re
import time

TARGET = "app.py"
MARK = "NEWS_FORCE_CHAT_TRANSLATE_V4"

def _read_lines(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def _write_lines(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_force_chat_v4." + ts
    with open(p, "r", encoding="utf-8") as f:
        data = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(data)
    return bak

def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: cannot find " + TARGET + " under " + os.getcwd())

    lines = _read_lines(TARGET)
    src = "".join(lines)
    if MARK in src:
        print("SKIP: marker already present:", MARK)
        return

    bak = _backup(TARGET)

    # 1) locate def news_digest(
    i_news = None
    for i, ln in enumerate(lines):
        if ln.startswith("def news_digest("):
            i_news = i
            break
    if i_news is None:
        raise SystemExit("ERROR: cannot find def news_digest(")

    # 2) locate token guard block: "if not token.strip():"
    i_guard = None
    for i in range(i_news, len(lines)):
        if lines[i].startswith("    if not token.strip()"):
            i_guard = i
            break
        if i > i_news and lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_guard is None:
        raise SystemExit("ERROR: cannot find 'if not token.strip()' inside news_digest")

    # 3) find end of that guard block (dedent back to 4 spaces)
    #    We look for first line AFTER i_guard that starts with exactly 4 spaces but is not empty/comment,
    #    and is not inside the guard's return dict block.
    i_insert_helper = None
    for i in range(i_guard + 1, len(lines)):
        ln = lines[i]
        if ln.startswith("def ") and (not ln.startswith("def news_digest(")):
            break
        if ln.startswith("    ") and (not ln.startswith("        ")):
            # dedented back to 4 spaces
            i_insert_helper = i
            break
    if i_insert_helper is None:
        raise SystemExit("ERROR: cannot determine insertion point after token guard block")

    helper = []
    helper.append("    # " + MARK + "\n")
    helper.append("    def _translate_titles_chat(titles: list) -> list:\n")
    helper.append("        if not titles:\n")
    helper.append("            return []\n")
    helper.append("        base = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"http://192.168.1.162:11434\").strip().rstrip(\"/\")\n")
    helper.append("        model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    helper.append("        in_lines = []\n")
    helper.append("        k = 1\n")
    helper.append("        for t in titles:\n")
    helper.append("            s = str(t or \"\").strip()\n")
    helper.append("            if not s:\n")
    helper.append("                s = \"(empty)\"\n")
    helper.append("            if len(s) > 180:\n")
    helper.append("                s = s[:180].rstrip() + \"…\"\n")
    helper.append("            in_lines.append(str(k) + \". \" + s)\n")
    helper.append("            k += 1\n")
    helper.append("        user_prompt = (\n")
    helper.append("            \"把下面每一行英文标题翻译成中文。\\n\"\n")
    helper.append("            \"要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\\n\"\n")
    helper.append("            \"保留专有名词/型号/人名的原文或常见译名。\\n\\n\"\n")
    helper.append("            + \"\\n\".join(in_lines)\n")
    helper.append("        )\n")
    helper.append("        payload = {\n")
    helper.append("            \"model\": model,\n")
    helper.append("            \"messages\": [\n")
    helper.append("                {\"role\": \"system\", \"content\": \"你是翻译器。只输出中文标题列表，每行一个。\"},\n")
    helper.append("                {\"role\": \"user\", \"content\": user_prompt},\n")
    helper.append("            ],\n")
    helper.append("            \"stream\": False,\n")
    helper.append("        }\n")
    helper.append("        try:\n")
    helper.append("            r = requests.post(base + \"/api/chat\", json=payload, timeout=45)\n")
    helper.append("            if int(getattr(r, \"status_code\", 0) or 0) >= 400:\n")
    helper.append("                return []\n")
    helper.append("            j = r.json() if hasattr(r, \"json\") else {}\n")
    helper.append("            msg = j.get(\"message\") if isinstance(j, dict) else None\n")
    helper.append("            txt = \"\"\n")
    helper.append("            if isinstance(msg, dict):\n")
    helper.append("                txt = str(msg.get(\"content\") or \"\").strip()\n")
    helper.append("            if not txt:\n")
    helper.append("                return []\n")
    helper.append("            out = [x.strip() for x in txt.splitlines() if x.strip()]\n")
    helper.append("            cleaned = []\n")
    helper.append("            for x in out:\n")
    helper.append("                x2 = re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", x).strip()\n")
    helper.append("                if x2:\n")
    helper.append("                    cleaned.append(x2)\n")
    helper.append("            return cleaned\n")
    helper.append("        except Exception:\n")
    helper.append("            return []\n")
    helper.append("\n")

    out = []
    out.extend(lines[:i_insert_helper])
    out.extend(helper)
    out.extend(lines[i_insert_helper:])

    lines = out

    # 4) ensure output uses title_voice first (replace within out_items loop)
    # Find: for i, it in enumerate(out_items, 1):
    i_loop = None
    list_var = None
    loop_pat = re.compile(r'^\s{4}for\s+i\s*,\s*it\s+in\s+enumerate\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*1\s*\)\s*:\s*$')
    for i in range(i_news, len(lines)):
        m = loop_pat.match(lines[i])
        if m:
            i_loop = i
            list_var = m.group(1)
            break
        if i > i_news and lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_loop is None or not list_var:
        raise SystemExit("ERROR: cannot find output loop 'for i, it in enumerate(X, 1):' in news_digest")

    # Insert translate-apply block right before the loop (unless already present)
    src2 = "".join(lines)
    if "NEWS_APPLY_TITLE_VOICE_CHAT_V4" not in src2:
        apply_block = []
        apply_block.append("    # NEWS_APPLY_TITLE_VOICE_CHAT_V4\n")
        apply_block.append("    try:\n")
        apply_block.append("        if prefer_lang == \"zh\" and isinstance(" + list_var + ", list) and " + list_var + ":\n")
        apply_block.append("            need = []\n")
        apply_block.append("            need_idx = []\n")
        apply_block.append("            for _idx, _it in enumerate(" + list_var + "):\n")
        apply_block.append("                _t0 = str((_it.get(\"title_voice\") or _it.get(\"title\") or \"\")).strip()\n")
        apply_block.append("                if _t0 and (not _has_cjk(_t0)):\n")
        apply_block.append("                    need.append(_t0)\n")
        apply_block.append("                    need_idx.append(_idx)\n")
        apply_block.append("            if need:\n")
        apply_block.append("                zh_list = _translate_titles_chat(need)\n")
        apply_block.append("                if isinstance(zh_list, list) and zh_list:\n")
        apply_block.append("                    n = min(len(zh_list), len(need_idx))\n")
        apply_block.append("                    for j in range(n):\n")
        apply_block.append("                        zt = str(zh_list[j] or \"\").strip()\n")
        apply_block.append("                        if zt and _has_cjk(zt):\n")
        apply_block.append("                            " + list_var + "[need_idx[j]][\"title_voice\"] = zt\n")
        apply_block.append("    except Exception:\n")
        apply_block.append("        pass\n")
        apply_block.append("\n")

        out3 = []
        out3.extend(lines[:i_loop])
        out3.extend(apply_block)
        out3.extend(lines[i_loop:])
        lines = out3

    # Replace title selection line inside the loop to prefer title_voice
    # Look within next 50 lines after loop for "t = it.get("title")"
    i_t = None
    for i in range(i_loop, min(i_loop + 60, len(lines))):
        s = lines[i].strip()
        if s.startswith("t = it.get(") and ("title_voice" not in s) and ("\"title\"" in s or "'title'" in s):
            i_t = i
            break
    if i_t is not None:
        indent = lines[i_t].split("t =")[0]
        lines[i_t] = indent + "t = it.get(\"title_voice\") or it.get(\"title\") or \"\"\n"

    _write_lines(TARGET, lines)

    print("OK: patched " + TARGET)
    print("Backup:", bak)
    print("Inserted helper at line:", i_insert_helper + 1)
    print("Applied translate-writeback before output loop. list_var:", list_var)

if __name__ == "__main__":
    main()
