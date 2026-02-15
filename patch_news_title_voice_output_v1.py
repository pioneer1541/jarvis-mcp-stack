import os
import time

TARGET = "app.py"

def _read_lines(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def _write_lines(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_title_voice_v1." + ts
    with open(p, "r", encoding="utf-8") as f:
        data = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(data)
    return bak

def _find_line(lines, start, predicate):
    for i in range(start, len(lines)):
        if predicate(lines[i]):
            return i
    return None

def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: cannot find " + TARGET + " under " + os.getcwd())

    lines = _read_lines(TARGET)
    bak = _backup(TARGET)

    # --------- (1) Patch: in news_digest(), output uses title_voice ----------
    i_news = _find_line(lines, 0, lambda s: s.startswith("def news_digest("))
    if i_news is None:
        raise SystemExit("ERROR: cannot find def news_digest(")

    # find loop: for i, it in enumerate(out_items, 1):
    i_loop = _find_line(lines, i_news, lambda s: ("for i, it in enumerate(out_items" in s))
    if i_loop is None:
        raise SystemExit("ERROR: cannot find 'for i, it in enumerate(out_items' inside news_digest")

    # within next ~25 lines find t = it.get("title") or ""
    i_t = None
    for i in range(i_loop, min(i_loop + 40, len(lines))):
        s = lines[i]
        ss = s.strip()
        if ss.startswith("t = it.get(") and ("\"title\"" in ss or "'title'" in ss) and ("title_voice" not in ss):
            i_t = i
            break
    if i_t is None:
        raise SystemExit("ERROR: cannot find title assignment line near out_items loop")

    indent = lines[i_t].split("t =")[0]
    lines[i_t] = indent + "t = it.get(\"title_voice\") or it.get(\"title\") or \"\"\n"

    # --------- (2) Patch: replace inner _ollama_translate_batch implementation ----------
    # find inner def _ollama_translate_batch within news_digest
    i_tr = None
    for i in range(i_news, len(lines)):
        if lines[i].startswith("    def _ollama_translate_batch("):
            i_tr = i
            break
        if i > i_news and lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_tr is None:
        raise SystemExit("ERROR: cannot find inner def _ollama_translate_batch in news_digest")

    # end marker: next inner def _kw_hit
    i_end = None
    for i in range(i_tr + 1, len(lines)):
        if lines[i].startswith("    def _kw_hit("):
            i_end = i
            break
        if lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_end is None:
        raise SystemExit("ERROR: cannot find end marker def _kw_hit after _ollama_translate_batch")

    new_block = []
    new_block.append("    def _ollama_translate_batch(titles: list) -> list:\n")
    new_block.append("        # Best-effort batch translation (titles only)\n")
    new_block.append("        if not titles:\n")
    new_block.append("            return []\n")
    new_block.append("\n")
    new_block.append("        # Prefer env OLLAMA_BASE_URL; but also try common docker/host fallbacks\n")
    new_block.append("        base_candidates = []\n")
    new_block.append("        try:\n")
    new_block.append("            env_b = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"\").strip()\n")
    new_block.append("        except Exception:\n")
    new_block.append("            env_b = \"\"\n")
    new_block.append("        if env_b:\n")
    new_block.append("            base_candidates.append(env_b)\n")
    new_block.append("        base_candidates.append(\"http://ollama:11434\")\n")
    new_block.append("        base_candidates.append(\"http://127.0.0.1:11434\")\n")
    new_block.append("        base_candidates.append(\"http://192.168.1.162:11434\")\n")
    new_block.append("\n")
    new_block.append("        model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    new_block.append("        url_path = \"/api/generate\"\n")
    new_block.append("\n")
    new_block.append("        in_lines = []\n")
    new_block.append("        i = 1\n")
    new_block.append("        for t in titles:\n")
    new_block.append("            s = str(t or \"\").strip()\n")
    new_block.append("            if not s:\n")
    new_block.append("                s = \"(empty)\"\n")
    new_block.append("            if len(s) > 140:\n")
    new_block.append("                s = s[:140].rstrip() + \"…\"\n")
    new_block.append("            in_lines.append(str(i) + \". \" + s)\n")
    new_block.append("            i += 1\n")
    new_block.append("\n")
    new_block.append("        prompt = (\n")
    new_block.append("            \"把下面每一行英文标题翻译成中文。\\n\"\n")
    new_block.append("            \"要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\\n\"\n")
    new_block.append("            \"保留专有名词/型号/人名的原文或常见译名。\\n\\n\"\n")
    new_block.append("            + \"\\n\".join(in_lines)\n")
    new_block.append("        )\n")
    new_block.append("\n")
    new_block.append("        payload = {\n")
    new_block.append("            \"model\": model,\n")
    new_block.append("            \"prompt\": prompt,\n")
    new_block.append("            \"stream\": False,\n")
    new_block.append("            \"keep_alive\": -1,\n")
    new_block.append("            \"options\": {\"temperature\": 0.0, \"num_ctx\": 2048},\n")
    new_block.append("        }\n")
    new_block.append("\n")
    new_block.append("        for base in base_candidates:\n")
    new_block.append("            try:\n")
    new_block.append("                b = str(base or \"\").strip().rstrip(\"/\")\n")
    new_block.append("                if not b:\n")
    new_block.append("                    continue\n")
    new_block.append("                url = b + url_path\n")
    new_block.append("                r = requests.post(url, json=payload, timeout=14)\n")
    new_block.append("                sc = int(getattr(r, \"status_code\", 0) or 0)\n")
    new_block.append("                if sc >= 400:\n")
    new_block.append("                    continue\n")
    new_block.append("                j = r.json() if hasattr(r, \"json\") else {}\n")
    new_block.append("                txt = str((j.get(\"response\") or \"\")).strip()\n")
    new_block.append("                if not txt:\n")
    new_block.append("                    continue\n")
    new_block.append("                out = [x.strip() for x in txt.splitlines() if x.strip()]\n")
    new_block.append("                cleaned = []\n")
    new_block.append("                for x in out:\n")
    new_block.append("                    x2 = re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", x).strip()\n")
    new_block.append("                    cleaned.append(x2)\n")
    new_block.append("                if cleaned:\n")
    new_block.append("                    return cleaned\n")
    new_block.append("            except Exception:\n")
    new_block.append("                continue\n")
    new_block.append("\n")
    new_block.append("        return []\n")
    new_block.append("\n")

    out = []
    out.extend(lines[:i_tr])
    out.extend(new_block)
    out.extend(lines[i_end:])

    _write_lines(TARGET, out)

    print("OK: patched " + TARGET)
    print("Backup: " + bak)
    print("Changed title output line: " + str(i_t + 1))
    print("Replaced _ollama_translate_batch lines: " + str(i_tr + 1) + " .. " + str(i_end))

if __name__ == "__main__":
    main()
