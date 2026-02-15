import os
import time

TARGET = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def _write(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def _backup(src):
    ts = time.strftime("%Y%m%d_%H%M%S")
    dst = src + ".bak.news_tr_titles_v1." + ts
    with open(src, "r", encoding="utf-8") as fsrc:
        data = fsrc.read()
    with open(dst, "w", encoding="utf-8") as fdst:
        fdst.write(data)
    return dst

def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: cannot find " + TARGET + " in " + os.getcwd())

    lines = _read(TARGET)
    bak = _backup(TARGET)

    # 1) find news_digest
    i_news = None
    for i, ln in enumerate(lines):
        if ln.startswith("def news_digest("):
            i_news = i
            break
    if i_news is None:
        raise SystemExit("ERROR: cannot find def news_digest(")

    # 2) find inner def _ollama_translate_batch within news_digest
    i_tr = None
    for i in range(i_news, len(lines)):
        if lines[i].startswith("    def _ollama_translate_batch("):
            i_tr = i
            break
        # stop if next top-level def reached (safety)
        if i > i_news and lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_tr is None:
        raise SystemExit("ERROR: cannot find inner def _ollama_translate_batch in news_digest")

    # 3) find end at next inner def _kw_hit
    i_end = None
    for i in range(i_tr + 1, len(lines)):
        if lines[i].startswith("    def _kw_hit("):
            i_end = i
            break
        # stop if we accidentally escape news_digest
        if lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_end is None:
        raise SystemExit("ERROR: cannot find end marker def _kw_hit after _ollama_translate_batch")

    # 4) replacement block
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
    new_block.append("        # docker service name (most common in compose networks)\n")
    new_block.append("        base_candidates.append(\"http://ollama:11434\")\n")
    new_block.append("        # local loopback\n")
    new_block.append("        base_candidates.append(\"http://127.0.0.1:11434\")\n")
    new_block.append("        # known LAN IP fallback\n")
    new_block.append("        base_candidates.append(\"http://192.168.1.162:11434\")\n")
    new_block.append("\n")
    new_block.append("        model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    new_block.append("        url_path = \"/api/generate\"\n")
    new_block.append("\n")
    new_block.append("        # numbered lines in, lines out\n")
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
    new_block.append("        # Try each base url until one succeeds\n")
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

    # 5) apply
    out_lines = []
    out_lines.extend(lines[:i_tr])
    out_lines.extend(new_block)
    out_lines.extend(lines[i_end:])

    _write(TARGET, out_lines)

    print("OK: patched " + TARGET)
    print("Backup: " + bak)
    print("Replaced lines: " + str(i_tr + 1) + " .. " + str(i_end))

if __name__ == "__main__":
    main()
