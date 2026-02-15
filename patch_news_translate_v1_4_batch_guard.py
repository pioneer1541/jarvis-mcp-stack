import io
import os
import sys

NEW_FUNC = r'''
def _news__translate_batch_to_zh(pairs: list, model: str = "", base_url: str = "", timeout_sec: int = 12) -> list:
    """
    pairs: [{"title": "...", "snippet": "..."}]
    returns: [{"title": "...", "snippet": "..."}] (Chinese, same length as input; may contain empty strings on failure)

    v1.4: reduce cross-item contamination for small models
      - chunking (default 2 items per request)
      - temperature=0.0
      - contamination guard: if translated text contains brand keywords not present in source, drop snippet (keep title if safe)
    """
    out = []
    try:
        if not isinstance(pairs, list) or (len(pairs) == 0):
            return out

        import json
        import urllib.request

        bu = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://192.168.1.162:11434").strip()
        if not bu:
            bu = "http://192.168.1.162:11434"
        mdl = (model or os.environ.get("NEWS_TRANSLATE_MODEL") or os.environ.get("OLLAMA_TRANSLATE_MODEL") or "qwen3:1.7b").strip()
        if not mdl:
            mdl = "qwen3:1.7b"

        try:
            bs = int(os.environ.get("NEWS_TRANSLATE_BATCH_SIZE") or "2")
        except Exception:
            bs = 2
        if bs < 1:
            bs = 1
        if bs > 4:
            bs = 4  # keep small to avoid mixing

        # simple brand/entity map for contamination guard (EN token -> CN keywords)
        brand_map = {
            "samsung": ["三星"],
            "google": ["谷歌", "Google"],
            "apple": ["苹果", "Apple"],
            "poco": ["Poco"],
            "infinix": ["Infinix"],
            "anbernic": ["Anbernic"],
            "nintendo": ["任天堂", "Nintendo"],
            "wii": ["Wii"],
            "verge": ["The Verge", "Verge"],
            "engadget": ["Engadget"],
            "gsmarena": ["GSMArena"],
            "switch": ["Switch"],
            "iran": ["伊朗"],
            "israel": ["以色列"],
            "russia": ["俄罗斯"],
            "ukraine": ["乌克兰"],
            "france": ["法国"],
            "texas": ["德州", "得克萨斯"],
            "minnesota": ["明尼苏达"],
        }

        def _call_ollama(chunk_pairs: list) -> list:
            # Build prompt
            sys_msg = (
                "你是中文新闻播报翻译助手。你必须逐条逐句翻译我给你的 TITLE 和 SNIP 字段。"
                "硬性规则："
                "1) TITLE 的中文只能来自 TITLE；SNIP 的中文只能来自 SNIP。不得把 TITLE 的信息补到 SNIP，也不得把 SNIP 的信息补到 TITLE。"
                "2) 只翻译，不得添加、推测、夸大、总结、改写事实；不得引入原文没有的时间、地点、数字、因果、结论。"
                "3) 若 SNIP 出现截断迹象（例如包含 '...'、'…'、'po...' 等），表示内容不完整：必须保持不完整，只翻译已给出的片段，禁止补全/扩写/发挥。"
                "4) 各条目彼此独立，禁止把其他条目的信息带入当前条目。"
                "5) 每条输出一行，严格保持条目数量一致。输出格式必须为："
                "N) <TITLE的中文翻译> ||| <SNIP的中文翻译> 。SNIP 可为空但分隔符必须保留。"
                "6) 除了上述格式，不得输出任何多余内容。"
            )

            lines = []
            i = 1
            for p in chunk_pairs:
                if not isinstance(p, dict):
                    p = {}
                t = str(p.get("title") or "").strip()
                s = str(p.get("snippet") or "").strip()
                if len(t) > 220:
                    t = t[:220].rstrip()
                if len(s) > 300:
                    s = s[:300].rstrip()
                lines.append("{0})".format(i))
                lines.append("TITLE: {0}".format(t))
                lines.append("SNIP: {0}".format(s))
                lines.append("")
                i += 1
            user_msg = "请翻译以下条目：\n" + "\n".join(lines)

            payload = {
                "model": mdl,
                "stream": False,
                "messages": [
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": user_msg},
                ],
                "options": {
                    "temperature": 0.0
                },
            }

            url = bu.rstrip("/") + "/api/chat"
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            try:
                with urllib.request.urlopen(req, timeout=float(timeout_sec)) as resp:
                    raw = resp.read().decode("utf-8", "ignore")
            except Exception:
                return [{"title": "", "snippet": ""} for _ in chunk_pairs]

            try:
                obj = json.loads(raw)
            except Exception:
                obj = {}

            content = ""
            try:
                content = str(((obj.get("message") or {}).get("content")) or "").strip()
            except Exception:
                content = ""

            parsed = []
            if content:
                for ln in content.splitlines():
                    x = (ln or "").strip()
                    if x:
                        parsed.append(x)

            got = {}
            for x in parsed:
                m = None
                try:
                    import re
                    m = re.match(r"^\s*(\d{1,2})\s*[)\）]\s*(.*)$", x)
                except Exception:
                    m = None
                if not m:
                    continue
                try:
                    n = int(m.group(1))
                except Exception:
                    continue
                rest = (m.group(2) or "").strip()
                title_zh = rest
                snip_zh = ""
                if "|||" in rest:
                    parts = rest.split("|||", 1)
                    title_zh = (parts[0] or "").strip()
                    snip_zh = (parts[1] or "").strip()
                got[n] = {"title": title_zh, "snippet": snip_zh}

            res = []
            for idx in range(1, len(chunk_pairs) + 1):
                it = got.get(idx) or {"title": "", "snippet": ""}
                res.append({"title": (it.get("title") or "").strip(), "snippet": (it.get("snippet") or "").strip()})
            return res

        def _is_contaminated(src_title: str, src_snip: str, zh_title: str, zh_snip: str) -> bool:
            src = (str(src_title or "") + " " + str(src_snip or "")).lower()
            zh = (str(zh_title or "") + " " + str(zh_snip or ""))
            allowed_cn = set()
            for en, cn_list in brand_map.items():
                if en in src:
                    for w in cn_list:
                        allowed_cn.add(w)

            # if any CN keyword appears but its EN token not in source => suspicious
            for en, cn_list in brand_map.items():
                if en in src:
                    continue
                for w in cn_list:
                    if w and (w in zh):
                        return True
            return False

        # chunk loop
        n = len(pairs)
        i = 0
        while i < n:
            chunk = pairs[i:i + bs]
            tr = _call_ollama(chunk)

            # apply guard per item
            for p, rr in zip(chunk, tr):
                st = str((p or {}).get("title") or "")
                ss = str((p or {}).get("snippet") or "")
                zt = str((rr or {}).get("title") or "").strip()
                zs = str((rr or {}).get("snippet") or "").strip()

                if _is_contaminated(st, ss, zt, zs):
                    # keep title if it doesn't look contaminated alone; drop snippet
                    if _is_contaminated(st, ss, zt, ""):
                        zt = ""
                    zs = ""
                out.append({"title": zt, "snippet": zs})

            i += bs

        # ensure length match
        if len(out) < n:
            for _ in range(n - len(out)):
                out.append({"title": "", "snippet": ""})
        if len(out) > n:
            out = out[:n]

        return out
    except Exception:
        for _ in (pairs or []):
            out.append({"title": "", "snippet": ""})
        return out
'''.lstrip("\n")

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # find function start
    start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__translate_batch_to_zh("):
            start = i
            break
    if start < 0:
        print("ERROR: cannot find def _news__translate_batch_to_zh(")
        sys.exit(1)

    # find function end (next top-level def)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("def ") and (not lines[j].startswith("def _news__translate_batch_to_zh(")):
            end = j
            break

    new_block = [NEW_FUNC + ("\n" if not NEW_FUNC.endswith("\n") else "")]
    new_lines = lines[:start] + new_block + lines[end:]

    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(new_lines))

    print("OK: replaced _news__translate_batch_to_zh with v1.4 (chunking + contamination guard)")

if __name__ == "__main__":
    main()
