import io
import os
import sys
import re
from datetime import datetime

TARGET_FILE = "app.py"

def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def make_backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_translate_v1." + ts
    with open(path, "rb") as src:
        with open(bak, "wb") as dst:
            dst.write(src.read())
    return bak

def patch():
    if not os.path.exists(TARGET_FILE):
        print("ERROR: not found:", TARGET_FILE)
        sys.exit(1)

    src = read_text(TARGET_FILE)
    lines = src.splitlines(True)

    # Locate the nested function inside news_digest:
    #     def _translate_titles_chat(titles: list) -> list:
    start_idx = None
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("def _translate_titles_chat(") and ln.startswith("    def _translate_titles_chat("):
            start_idx = i
            break

    if start_idx is None:
        print("ERROR: cannot find 'def _translate_titles_chat(' block")
        sys.exit(2)

    indent = re.match(r"^(\s*)", lines[start_idx]).group(1)

    # End at next sibling def (same indent) - currently _mf_req
    end_idx = None
    for j in range(start_idx + 1, len(lines)):
        if lines[j].startswith(indent + "def ") and (j > start_idx):
            end_idx = j
            break

    if end_idx is None:
        print("ERROR: cannot find end of _translate_titles_chat block")
        sys.exit(3)

    new_block = []
    ap = new_block.append

    ap(indent + "def _translate_titles_chat(titles: list) -> list:\n")
    ap(indent + "    \"\"\"Robust batch title translation.\n")
    ap(indent + "    - Accept multiline output\n")
    ap(indent + "    - Accept single-line numbered blob (e.g. '1) ... 2) ... 3) ...')\n")
    ap(indent + "    - If still not enough, fallback to per-title chat\n")
    ap(indent + "    \"\"\"\n")
    ap(indent + "    if not titles:\n")
    ap(indent + "        return []\n")
    ap(indent + "    base = str(os.environ.get(\"OLLAMA_BASE_URL\") or \"http://192.168.1.162:11434\").strip().rstrip(\"/\")\n")
    ap(indent + "    model = str(os.environ.get(\"NEWS_TRANSLATE_MODEL\") or os.environ.get(\"OLLAMA_TRANSLATE_MODEL\") or \"qwen3:1.7b\").strip() or \"qwen3:1.7b\"\n")
    ap(indent + "    want_n = len(titles)\n")
    ap(indent + "\n")
    ap(indent + "    def _strip_num_prefix(s: str) -> str:\n")
    ap(indent + "        return re.sub(r\"^\\s*\\d+\\s*[\\.|\\)|、]\\s*\", \"\", str(s or \"\").strip()).strip()\n")
    ap(indent + "\n")
    ap(indent + "    def _split_numbered_blob(s: str) -> list:\n")
    ap(indent + "        t = str(s or \"\").strip()\n")
    ap(indent + "        if not t:\n")
    ap(indent + "            return []\n")
    ap(indent + "        # Find positions of numbered markers like '1) ' '2. ' '3、'\n")
    ap(indent + "        pat = re.compile(r\"(?:^|\\s)(\\d{1,2})\\s*[\\.|\\)|、]\\s+\")\n")
    ap(indent + "        ms = list(pat.finditer(t))\n")
    ap(indent + "        if not ms:\n")
    ap(indent + "            return []\n")
    ap(indent + "        parts = []\n")
    ap(indent + "        for idx, m in enumerate(ms):\n")
    ap(indent + "            st = m.start(1)  # number start\n")
    ap(indent + "            # content starts at marker start\n")
    ap(indent + "            c0 = m.start(0)\n")
    ap(indent + "            c1 = ms[idx + 1].start(0) if (idx + 1) < len(ms) else len(t)\n")
    ap(indent + "            seg = t[c0:c1].strip()\n")
    ap(indent + "            seg = _strip_num_prefix(seg)\n")
    ap(indent + "            if seg:\n")
    ap(indent + "                parts.append(seg)\n")
    ap(indent + "        return parts\n")
    ap(indent + "\n")
    ap(indent + "    def _translate_one(title_en: str) -> str:\n")
    ap(indent + "        te = str(title_en or \"\").strip()\n")
    ap(indent + "        if not te:\n")
    ap(indent + "            return \"\"\n")
    ap(indent + "        payload = {\n")
    ap(indent + "            \"model\": model,\n")
    ap(indent + "            \"messages\": [\n")
    ap(indent + "                {\"role\": \"system\", \"content\": \"你是翻译器。只输出中文。\"},\n")
    ap(indent + "                {\"role\": \"user\", \"content\": \"把下面标题翻译成中文，只输出译文：\\n\" + te},\n")
    ap(indent + "            ],\n")
    ap(indent + "            \"stream\": False,\n")
    ap(indent + "        }\n")
    ap(indent + "        try:\n")
    ap(indent + "            rr = requests.post(base + \"/api/chat\", json=payload, timeout=45)\n")
    ap(indent + "            if int(getattr(rr, \"status_code\", 0) or 0) >= 400:\n")
    ap(indent + "                return \"\"\n")
    ap(indent + "            jj = rr.json() if hasattr(rr, \"json\") else {}\n")
    ap(indent + "            msg = jj.get(\"message\") if isinstance(jj, dict) else None\n")
    ap(indent + "            out = \"\"\n")
    ap(indent + "            if isinstance(msg, dict):\n")
    ap(indent + "                out = str(msg.get(\"content\") or \"\").strip()\n")
    ap(indent + "            return out\n")
    ap(indent + "        except Exception:\n")
    ap(indent + "            return \"\"\n")
    ap(indent + "\n")
    ap(indent + "    # batch prompt\n")
    ap(indent + "    in_lines = []\n")
    ap(indent + "    k = 1\n")
    ap(indent + "    for t in titles:\n")
    ap(indent + "        s = str(t or \"\").strip()\n")
    ap(indent + "        if not s:\n")
    ap(indent + "            s = \"(empty)\"\n")
    ap(indent + "        if len(s) > 180:\n")
    ap(indent + "            s = s[:180].rstrip() + \"…\"\n")
    ap(indent + "        in_lines.append(str(k) + \". \" + s)\n")
    ap(indent + "        k += 1\n")
    ap(indent + "\n")
    ap(indent + "    user_prompt = (\n")
    ap(indent + "        \"把下面每一行英文标题翻译成中文。\\n\"\n")
    ap(indent + "        \"要求：只输出对应的中文标题列表，每行一个，不要加解释，不要加序号，不要加任何多余文字。\\n\"\n")
    ap(indent + "        \"如果模型无法逐行输出，可以用 1) 2) 3) 的形式，但必须能一一对应。\\n\\n\"\n")
    ap(indent + "        + \"\\n\".join(in_lines)\n")
    ap(indent + "    )\n")
    ap(indent + "\n")
    ap(indent + "    payload = {\n")
    ap(indent + "        \"model\": model,\n")
    ap(indent + "        \"messages\": [\n")
    ap(indent + "            {\"role\": \"system\", \"content\": \"你是翻译器。只输出中文标题列表。\"},\n")
    ap(indent + "            {\"role\": \"user\", \"content\": user_prompt},\n")
    ap(indent + "        ],\n")
    ap(indent + "        \"stream\": False,\n")
    ap(indent + "    }\n")
    ap(indent + "\n")
    ap(indent + "    txt = \"\"\n")
    ap(indent + "    try:\n")
    ap(indent + "        r = requests.post(base + \"/api/chat\", json=payload, timeout=45)\n")
    ap(indent + "        if int(getattr(r, \"status_code\", 0) or 0) < 400:\n")
    ap(indent + "            j = r.json() if hasattr(r, \"json\") else {}\n")
    ap(indent + "            msg = j.get(\"message\") if isinstance(j, dict) else None\n")
    ap(indent + "            if isinstance(msg, dict):\n")
    ap(indent + "                txt = str(msg.get(\"content\") or \"\").strip()\n")
    ap(indent + "    except Exception:\n")
    ap(indent + "        txt = \"\"\n")
    ap(indent + "\n")
    ap(indent + "    cleaned = []\n")
    ap(indent + "    if txt:\n")
    ap(indent + "        # 1) normal multiline\n")
    ap(indent + "        out = [x.strip() for x in txt.splitlines() if x.strip()]\n")
    ap(indent + "        for x in out:\n")
    ap(indent + "            x2 = _strip_num_prefix(x)\n")
    ap(indent + "            if x2:\n")
    ap(indent + "                cleaned.append(x2)\n")
    ap(indent + "        # 2) single-line numbered blob\n")
    ap(indent + "        if len(cleaned) < want_n:\n")
    ap(indent + "            blob_parts = _split_numbered_blob(txt)\n")
    ap(indent + "            if blob_parts and (len(blob_parts) > len(cleaned)):\n")
    ap(indent + "                cleaned = blob_parts\n")
    ap(indent + "\n")
    ap(indent + "    # 3) ensure length: fallback translate per-title for missing\n")
    ap(indent + "    out_list = []\n")
    ap(indent + "    for i in range(want_n):\n")
    ap(indent + "        v = \"\"\n")
    ap(indent + "        if i < len(cleaned):\n")
    ap(indent + "            v = str(cleaned[i] or \"\").strip()\n")
    ap(indent + "        if not v:\n")
    ap(indent + "            v = _translate_one(str(titles[i] or \"\").strip())\n")
    ap(indent + "        if not v:\n")
    ap(indent + "            v = str(titles[i] or \"\").strip()\n")
    ap(indent + "        out_list.append(v)\n")
    ap(indent + "    return out_list\n")

    bak = make_backup(TARGET_FILE)
    new_lines = lines[:start_idx] + new_block + lines[end_idx:]
    new_src = "".join(new_lines)
    write_text(TARGET_FILE, new_src)

    print("OK: patched", TARGET_FILE)
    print("Backup:", bak)
    print("Replaced lines:", start_idx + 1, "to", end_idx)

if __name__ == "__main__":
    patch()
