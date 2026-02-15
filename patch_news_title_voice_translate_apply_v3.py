import os
import re
import time

TARGET = "app.py"
MARK = "NEWS_TRANSLATE_TITLES_V3"

def _read_lines(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def _write_lines(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_tr_apply_v3." + ts
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

    # 1) find news_digest
    i_news = None
    for i, ln in enumerate(lines):
        if ln.startswith("def news_digest("):
            i_news = i
            break
    if i_news is None:
        raise SystemExit("ERROR: cannot find def news_digest(")

    # 2) find the output loop: for i, it in enumerate(<var>, 1):
    i_loop = None
    list_var = None
    loop_pat = re.compile(r'^\s{4}for\s+i\s*,\s*it\s+in\s+enumerate\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*1\s*\)\s*:\s*$')
    for i in range(i_news, len(lines)):
        m = loop_pat.match(lines[i])
        if m:
            i_loop = i
            list_var = m.group(1)
            break
        # safety: stop at next top-level def
        if i > i_news and lines[i].startswith("def ") and (not lines[i].startswith("def news_digest(")):
            break
    if i_loop is None or not list_var:
        raise SystemExit("ERROR: cannot find output loop 'for i, it in enumerate(X, 1):' in news_digest")

    # 3) insert translation apply block right before the loop
    ins = []
    ins.append("    # " + MARK + "\n")
    ins.append("    # If prefer_lang=zh and selected items are English, translate titles and write into title_voice.\n")
    ins.append("    try:\n")
    ins.append("        if prefer_lang == \"zh\" and isinstance(" + list_var + ", list) and " + list_var + ":\n")
    ins.append("            need = []\n")
    ins.append("            need_idx = []\n")
    ins.append("            for _idx, _it in enumerate(" + list_var + "):\n")
    ins.append("                _t0 = str((_it.get(\"title_voice\") or _it.get(\"title\") or \"\")).strip()\n")
    ins.append("                if _t0 and (not _has_cjk(_t0)):\n")
    ins.append("                    need.append(_t0)\n")
    ins.append("                    need_idx.append(_idx)\n")
    ins.append("            if need:\n")
    ins.append("                zh_list = _ollama_translate_batch(need)\n")
    ins.append("                if isinstance(zh_list, list) and zh_list:\n")
    ins.append("                    _n = min(len(zh_list), len(need_idx))\n")
    ins.append("                    for j in range(_n):\n")
    ins.append("                        _zt = str(zh_list[j] or \"\").strip()\n")
    ins.append("                        if _zt and _has_cjk(_zt):\n")
    ins.append("                            " + list_var + "[need_idx[j]][\"title_voice\"] = _zt\n")
    ins.append("    except Exception:\n")
    ins.append("        pass\n")
    ins.append("\n")

    out = []
    out.extend(lines[:i_loop])
    out.extend(ins)
    out.extend(lines[i_loop:])

    _write_lines(TARGET, out)

    print("OK: patched " + TARGET)
    print("Backup:", bak)
    print("Inserted marker before line:", i_loop + 1)
    print("Target list var:", list_var)

if __name__ == "__main__":
    main()
