import re

APP = "app.py"

def find_top_def_range(src: str, def_name: str):
    # find "def <def_name>(" at top-level (col 0)
    m0 = re.search(r'(?m)^def\s+' + re.escape(def_name) + r'\s*\(', src)
    if not m0:
        return None
    # find next top-level def after m0
    m1 = re.search(r'(?m)^def\s+\w+\s*\(', src[m0.end():])
    if not m1:
        return (m0.start(), len(src))
    return (m0.start(), m0.end() + m1.start())

def replace_nested_func_by_indent(block: str, nested_name: str):
    lines = block.splitlines(True)

    start_i = None
    indent = None

    pat = re.compile(r'^(\s*)def\s+' + re.escape(nested_name) + r'\s*\(')
    for i, ln in enumerate(lines):
        m = pat.match(ln)
        if m:
            start_i = i
            indent = m.group(1)
            break

    if start_i is None:
        return None, None  # not found

    # end at next "def " with same indent
    end_i = len(lines)
    for j in range(start_i + 1, len(lines)):
        ln = lines[j]
        if ln.strip() == "":
            continue
        if ln.startswith(indent) and ln[len(indent):].startswith("def "):
            end_i = j
            break

    new_func = []
    new_func.append(indent + "def _news__norm_kw(s: str) -> str:\n")
    new_func.append(indent + "    s2 = _ug_clean_unicode(s or \"\")\n")
    new_func.append(indent + "    s2 = s2.lower()\n")
    new_func.append(indent + "    try:\n")
    new_func.append(indent + "        s2 = re.sub(r\"\\s+\", \" \", s2).strip()\n")
    new_func.append(indent + "    except Exception:\n")
    new_func.append(indent + "        s2 = (s2 or \"\").strip()\n")
    new_func.append(indent + "    return s2\n\n")

    new_func.append(indent + "def _kw_hit(text_s: str, kws: list) -> bool:\n")
    new_func.append(indent + "    if not text_s:\n")
    new_func.append(indent + "        return False\n")
    new_func.append(indent + "    t0 = _news__norm_kw(text_s)\n")
    new_func.append(indent + "    if not t0:\n")
    new_func.append(indent + "        return False\n")
    new_func.append(indent + "    for k in (kws or []):\n")
    new_func.append(indent + "        kk = _news__norm_kw(k or \"\")\n")
    new_func.append(indent + "        if not kk:\n")
    new_func.append(indent + "            continue\n")
    new_func.append(indent + "        if kk in t0:\n")
    new_func.append(indent + "            return True\n")
    new_func.append(indent + "    return False\n")

    out = lines[:start_i] + new_func + lines[end_i:]
    return "".join(out), (start_i, end_i)

def main():
    with open(APP, "r", encoding="utf-8") as f:
        src = f.read()

    rng = find_top_def_range(src, "news_digest")
    if not rng:
        raise SystemExit("Cannot find top-level def news_digest(")

    a, b = rng
    block = src[a:b]

    # replace nested _kw_hit inside news_digest block
    replaced, span = replace_nested_func_by_indent(block, "_kw_hit")
    if replaced is None:
        raise SystemExit("Cannot find nested def _kw_hit( inside news_digest block")

    new_src = src[:a] + replaced + src[b:]

    with open(APP, "w", encoding="utf-8") as f:
        f.write(new_src)

    print("OK: patched _kw_hit normalization for blacklist/whitelist matching (P2 kw_norm_v1).")

if __name__ == "__main__":
    main()
