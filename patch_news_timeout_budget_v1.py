import os, sys, time, re
from datetime import datetime

TARGET="app.py"
MARK="NEWS_TIMEOUT_BUDGET_V1"

def read(p):
    with open(p,"r",encoding="utf-8") as f:
        return f.read()

def write(p,s):
    with open(p,"w",encoding="utf-8") as f:
        f.write(s)

def backup(p):
    ts=datetime.now().strftime("%Y%m%d_%H%M%S")
    b=p+".bak.news_budget_v1."+ts
    with open(p,"rb") as src, open(b,"wb") as dst:
        dst.write(src.read())
    return b

def main():
    if not os.path.exists(TARGET):
        print("ERROR not found", TARGET); sys.exit(1)

    src = read(TARGET)
    if MARK in src:
        print("OK already patched"); return

    lines = src.splitlines(True)

    # find def _translate_titles_chat inside news_digest
    i0=None
    for i,ln in enumerate(lines):
        if ln.startswith("    def _translate_titles_chat("):
            i0=i; break
    if i0 is None:
        print("ERROR cannot find _translate_titles_chat"); sys.exit(2)

    # find end of this def: next "    def " sibling
    i1=None
    for j in range(i0+1,len(lines)):
        if lines[j].startswith("    def ") and (not lines[j].startswith("    def _translate_titles_chat(")):
            i1=j; break
    if i1 is None:
        print("ERROR cannot find end of _translate_titles_chat"); sys.exit(3)

    block = []
    ap = block.append
    ap("    def _translate_titles_chat(titles: list) -> list:\n")
    ap("        \"\"\"Robust batch title translation with a hard time budget.\n")
    ap("        - Prefer one batch /api/chat.\n")
    ap("        - If output parsing is odd, try to split numbered blob.\n")
    ap("        - Do NOT do per-title fallback by default (too slow for HA tool timeout).\n")
    ap("        Budget is controlled by NEWS_TRANSLATE_BUDGET_SEC (default 8s).\n")
    ap("        \"\"\"\n")
    ap("        if not titles:\n")
    ap("            return []\n")
    ap("        t0 = time.time()\n")
    ap("        budget = float(os.environ.get(\"NEWS_TRANSLATE_BUDGET_SEC\") or \"8\")\n")
    ap("        base = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"http://192.168.1.162:11434\").strip().rstrip(\"/\")\n")
    ap("        model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    ap("        want_n = len(titles)\n")
    ap("\n")
    ap("        def _strip_num_prefix(s: str) -> str:\n")
    ap("            return re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", str(s or \"\").strip()).strip()\n")
    ap("\n")
    ap("        def _split_numbered_blob(s: str) -> list:\n")
    ap("            t = str(s or \"\").strip()\n")
    ap("            if not t:\n")
    ap("                return []\n")
    ap("            pat = re.compile(r\"(?:^|\\s)(\\d{1,2})\\s*[\\.|\\)|、]\\s+\")\n")
    ap("            ms = list(pat.finditer(t))\n")
    ap("            if not ms:\n")
    ap("                return []\n")
    ap("            parts = []\n")
    ap("            for idx, m in enumerate(ms):\n")
    ap("                c0 = m.start(0)\n")
    ap("                c1 = ms[idx+1].start(0) if (idx+1)<len(ms) else len(t)\n")
    ap("                seg = t[c0:c1].strip()\n")
    ap("                seg = _strip_num_prefix(seg)\n")
    ap("                if seg:\n")
    ap("                    parts.append(seg)\n")
    ap("            return parts\n")
    ap("\n")
    ap("        # build batch prompt\n")
    ap("        in_lines = []\n")
    ap("        k = 1\n")
    ap("        for tt in titles:\n")
    ap("            s = str(tt or \"\").strip() or \"(empty)\"\n")
    ap("            if len(s) > 180:\n")
    ap("                s = s[:180].rstrip() + \"…\"\n")
    ap("            in_lines.append(str(k) + \". \" + s)\n")
    ap("            k += 1\n")
    ap("\n")
    ap("        user_prompt = (\n")
    ap("            \"把下面每一行英文标题翻译成中文。\\n\"\n")
    ap("            \"要求：只输出对应的中文标题列表，每行一个。\\n\"\n")
    ap("            \"如果无法逐行输出，可以用 1) 2) 3) 的形式，但必须一一对应。\\n\\n\"\n")
    ap("            + \"\\n\".join(in_lines)\n")
    ap("        )\n")
    ap("\n")
    ap("        # dynamic timeout: never exceed budget\n")
    ap("        remain = max(1.0, budget - (time.time() - t0))\n")
    ap("        timeout_sec = min(12.0, remain)\n")
    ap("\n")
    ap("        payload = {\n")
    ap("            \"model\": model,\n")
    ap("            \"messages\": [\n")
    ap("                {\"role\": \"system\", \"content\": \"你是翻译器。只输出中文标题列表。\"},\n")
    ap("                {\"role\": \"user\", \"content\": user_prompt},\n")
    ap("            ],\n")
    ap("            \"stream\": False,\n")
    ap("        }\n")
    ap("\n")
    ap("        txt = \"\"\n")
    ap("        try:\n")
    ap("            r = requests.post(base + \"/api/chat\", json=payload, timeout=timeout_sec)\n")
    ap("            if int(getattr(r, \"status_code\", 0) or 0) < 400:\n")
    ap("                j = r.json() if hasattr(r, \"json\") else {}\n")
    ap("                msg = j.get(\"message\") if isinstance(j, dict) else None\n")
    ap("                if isinstance(msg, dict):\n")
    ap("                    txt = str(msg.get(\"content\") or \"\").strip()\n")
    ap("        except Exception:\n")
    ap("            txt = \"\"\n")
    ap("\n")
    ap("        cleaned = []\n")
    ap("        if txt:\n")
    ap("            out = [x.strip() for x in txt.splitlines() if x.strip()]\n")
    ap("            for x in out:\n")
    ap("                x2 = _strip_num_prefix(x)\n")
    ap("                if x2:\n")
    ap("                    cleaned.append(x2)\n")
    ap("            if len(cleaned) < want_n:\n")
    ap("                blob = _split_numbered_blob(txt)\n")
    ap("                if blob and (len(blob) > len(cleaned)):\n")
    ap("                    cleaned = blob\n")
    ap("\n")
    ap("        # ensure length; if不足，直接回退原文（避免逐条翻译导致 HA 超时）\n")
    ap("        out_list = []\n")
    ap("        for i in range(want_n):\n")
    ap("            v = str(cleaned[i] if i < len(cleaned) else \"\").strip()\n")
    ap("            if not v:\n")
    ap("                v = str(titles[i] or \"\").strip()\n")
    ap("            out_list.append(v)\n")
    ap("        return out_list\n")
    ap("\n")

    bak = backup(TARGET)
    new_src = "".join(lines[:i0]) + "".join(block) + "".join(lines[i1:])
    new_src = new_src.replace("def news_digest(", "def news_digest(")  # no-op, keep minimal
    new_src = new_src.replace(MARK, MARK)  # no-op

    # add marker once near the replaced block header
    new_src = new_src.replace("def _translate_titles_chat(titles: list) -> list:\n",
                              "def _translate_titles_chat(titles: list) -> list:\n        # "+MARK+"\n", 1)

    write(TARGET, new_src)
    print("OK patched", TARGET)
    print("Backup:", bak)

if __name__=="__main__":
    main()
