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
    bak = p + ".bak.news_tr_chatfb_v2." + ts
    with open(p, "r", encoding="utf-8") as f:
        data = f.read()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(data)
    return bak

def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: cannot find " + TARGET + " under " + os.getcwd())

    lines = _read_lines(TARGET)
    bak = _backup(TARGET)

    # find news_digest
    i_news = None
    for i, ln in enumerate(lines):
        if ln.startswith("def news_digest("):
            i_news = i
            break
    if i_news is None:
        raise SystemExit("ERROR: cannot find def news_digest(")

    # find inner def _ollama_translate_batch
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
    new_block.append("        # Best-effort batch translation (titles only).\n")
    new_block.append("        # Try /api/generate first; fallback to /api/chat if generate returns empty.\n")
    new_block.append("        if not titles:\n")
    new_block.append("            return []\n")
    new_block.append("\n")
    new_block.append("        # base url candidates (env first)\n")
    new_block.append("        base_candidates = []\n")
    new_block.append("        try:\n")
    new_block.append("            env_b = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"\").strip()\n")
    new_block.append("        except Exception:\n")
    new_block.append("            env_b = \"\"\n")
    new_block.append("        if env_b:\n")
    new_block.append("            base_candidates.append(env_b)\n")
    new_block.append("        base_candidates.append(\"http://192.168.1.162:11434\")\n")
    new_block.append("        base_candidates.append(\"http://ollama:11434\")\n")
    new_block.append("        base_candidates.append(\"http://127.0.0.1:11434\")\n")
    new_block.append("\n")
    new_block.append("        model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    new_block.append("\n")
    new_block.append("        # numbered lines in, lines out\n")
    new_block.append("        in_lines = []\n")
    new_block.append("        i = 1\n")
    new_block.append("        for t in titles:\n")
    new_block.append("            s = str(t or \"\").strip()\n")
    new_block.append("            if not s:\n")
    new_block.append("                s = \"(empty)\"\n")
    new_block.append("            if len(s) > 180:\n")
    new_block.append("                s = s[:180].rstrip() + \"…\"\n")
    new_block.append("            in_lines.append(str(i) + \". \" + s)\n")
    new_block.append("            i += 1\n")
    new_block.append("\n")
    new_block.append("        user_prompt = (\n")
    new_block.append("            \"把下面每一行英文标题翻译成中文。\\n\"\n")
    new_block.append("            \"要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\\n\"\n")
    new_block.append("            \"保留专有名词/型号/人名的原文或常见译名。\\n\\n\"\n")
    new_block.append("            + \"\\n\".join(in_lines)\n")
    new_block.append("        )\n")
    new_block.append("\n")
    new_block.append("        def _clean_lines(txt: str) -> list:\n")
    new_block.append("            out = [x.strip() for x in str(txt or \"\").splitlines() if x.strip()]\n")
    new_block.append("            cleaned = []\n")
    new_block.append("            for x in out:\n")
    new_block.append("                x2 = re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", x).strip()\n")
    new_block.append("                if x2:\n")
    new_block.append("                    cleaned.append(x2)\n")
    new_block.append("            return cleaned\n")
    new_block.append("\n")
    new_block.append("        # try bases\n")
    new_block.append("        for base in base_candidates:\n")
    new_block.append("            try:\n")
    new_block.append("                b = str(base or \"\").strip().rstrip(\"/\")\n")
    new_block.append("                if not b:\n")
    new_block.append("                    continue\n")
    new_block.append("\n")
    new_block.append("                # 1) /api/generate\n")
    new_block.append("                gen_payload = {\n")
    new_block.append("                    \"model\": model,\n")
    new_block.append("                    \"prompt\": user_prompt,\n")
    new_block.append("                    \"stream\": False,\n")
    new_block.append("                    \"keep_alive\": -1,\n")
    new_block.append("                    \"options\": {\"temperature\": 0.0, \"num_ctx\": 2048, \"num_predict\": 256},\n")
    new_block.append("                }\n")
    new_block.append("                r = requests.post(b + \"/api/generate\", json=gen_payload, timeout=30)\n")
    new_block.append("                sc = int(getattr(r, \"status_code\", 0) or 0)\n")
    new_block.append("                if sc < 400:\n")
    new_block.append("                    j = r.json() if hasattr(r, \"json\") else {}\n")
    new_block.append("                    if isinstance(j, dict) and j.get(\"error\"):\n")
    new_block.append("                        pass\n")
    new_block.append("                    else:\n")
    new_block.append("                        txt = str((j.get(\"response\") or \"\")).strip()\n")
    new_block.append("                        cleaned = _clean_lines(txt)\n")
    new_block.append("                        if cleaned:\n")
    new_block.append("                            return cleaned\n")
    new_block.append("\n")
    new_block.append("                # 2) fallback /api/chat\n")
    new_block.append("                chat_payload = {\n")
    new_block.append("                    \"model\": model,\n")
    new_block.append("                    \"messages\": [\n")
    new_block.append("                        {\"role\": \"system\", \"content\": \"你是一个翻译器。只做中英文标题翻译。\"},\n")
    new_block.append("                        {\"role\": \"user\", \"content\": user_prompt},\n")
    new_block.append("                    ],\n")
    new_block.append("                    \"stream\": False,\n")
    new_block.append("                    \"keep_alive\": -1,\n")
    new_block.append("                    \"options\": {\"temperature\": 0.0, \"num_ctx\": 2048},\n")
    new_block.append("                }\n")
    new_block.append("                r2 = requests.post(b + \"/api/chat\", json=chat_payload, timeout=45)\n")
    new_block.append("                sc2 = int(getattr(r2, \"status_code\", 0) or 0)\n")
    new_block.append("                if sc2 >= 400:\n")
    new_block.append("                    continue\n")
    new_block.append("                j2 = r2.json() if hasattr(r2, \"json\") else {}\n")
    new_block.append("                if isinstance(j2, dict) and j2.get(\"error\"):\n")
    new_block.append("                    continue\n")
    new_block.append("                msg = j2.get(\"message\") if isinstance(j2, dict) else None\n")
    new_block.append("                content = \"\"\n")
    new_block.append("                if isinstance(msg, dict):\n")
    new_block.append("                    content = str((msg.get(\"content\") or \"\")).strip()\n")
    new_block.append("                cleaned2 = _clean_lines(content)\n")
    new_block.append("                if cleaned2:\n")
    new_block.append("                    return cleaned2\n")
    new_block.append("\n")
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
    print("Replaced _ollama_translate_batch lines: " + str(i_tr + 1) + " .. " + str(i_end))

if __name__ == "__main__":
    main()
