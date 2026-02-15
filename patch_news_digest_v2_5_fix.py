#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
import time


APP_PATH = "app.py"


def _backup(path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.news_v2_5." + ts
    shutil.copy2(path, bak)
    return bak


def _split_decorator_def_same_line(lines):
    """
    Fix:
      @mcp.tool(... )def news_digest(...):
    into two lines.
    """
    out = []
    changed = False
    for ln in lines:
        if ("@mcp.tool" in ln) and ("def news_digest" in ln):
            i = ln.find("def news_digest")
            if i > 0:
                left = ln[:i].rstrip()
                right = ln[i:].lstrip()
                out.append(left + "\n")
                out.append(right if right.endswith("\n") else (right + "\n"))
                changed = True
                continue
        out.append(ln)
    return out, changed


def _normalize_site_domain(s):
    x = (s or "").strip()
    if not x:
        return ""
    x = re.sub(r"^https?://", "", x)
    x = x.split("/")[0].strip()
    return x


def _patch_news_site_filter(src: str) -> (str, bool):
    """
    Replace whole function def _news__site_filter(terms, domains) block
    with a safer version that strips paths for site: operator.
    """
    pat = r"(?m)^def _news__site_filter\(\s*terms\s*,\s*domains\s*\)\s*:\s*\n"
    m = re.search(pat, src)
    if not m:
        return src, False

    start = m.start()

    # find end of this function by next top-level "def " or EOF
    m2 = re.search(r"(?m)^\s*def\s+\w+\s*\(", src[m.end():])
    if m2:
        end = m.end() + m2.start()
    else:
        end = len(src)

    new_block = (
        "def _news__site_filter(terms, domains):\n"
        "    # Build a safe site:(domain) filter. NOTE: 'site:' generally only supports domains,\n"
        "    # so we strip paths like 'abc.net.au/chinese' -> 'abc.net.au'.\n"
        "    ds = []\n"
        "    for d in (domains or []):\n"
        "        dom = _normalize_site_domain(str(d or \"\"))\n"
        "        if not dom:\n"
        "            continue\n"
        "        if dom not in ds:\n"
        "            ds.append(dom)\n"
        "    if not ds:\n"
        "        return terms\n"
        "    filt = \"(\" + \" OR \".join([\"site:\" + d for d in ds]) + \")\"\n"
        "    if not terms:\n"
        "        return filt\n"
        "    return terms + \" \" + filt\n"
        "\n"
    )

    # ensure helper exists (only inject once)
    if "def _normalize_site_domain(" not in src:
        helper = (
            "\n"
            "def _normalize_site_domain(s):\n"
            "    x = (s or \"\").strip()\n"
            "    if not x:\n"
            "        return \"\"\n"
            "    x = re.sub(r\"^https?://\", \"\", x)\n"
            "    x = x.split(\"/\")[0].strip()\n"
            "    return x\n"
            "\n"
        )
        # insert helper right before _news__site_filter
        patched = src[:start] + helper + new_block + src[end:]
    else:
        patched = src[:start] + new_block + src[end:]

    return patched, True


def _ensure_news_digest_signature(lines):
    """
    Ensure:
      def news_digest(... prefer_lang="zh", user_text="", **kwargs) -> dict:
    without breaking return annotation styles.
    """
    changed = False

    # collect all occurrences
    idxs = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*def\s+news_digest\s*\(", ln):
            idxs.append(i)

    if not idxs:
        return lines, False

    # keep the LAST one as canonical (usually newest patch), rename others to legacy
    canonical_i = idxs[-1]
    legacy_n = 1
    for i in idxs[:-1]:
        # rename def name
        m = re.match(r"^(\s*)def\s+news_digest(\s*\()", lines[i])
        if m:
            indent = m.group(1)
            lines[i] = re.sub(r"^(\s*)def\s+news_digest(\s*\()",
                              indent + "def news_digest_legacy_" + str(legacy_n) + "\\2",
                              lines[i])
            legacy_n += 1
            changed = True

    # patch canonical signature line
    ln = lines[canonical_i]

    # extract indentation
    m = re.match(r"^(\s*)def\s+news_digest\s*\(", ln)
    if not m:
        return lines, changed

    indent = m.group(1)

    # keep return annotation if present
    ret = ""
    if ")->" in ln.replace(" ", ""):
        # rare: def ...)->dict:
        pass

    # If prefer_lang already present, still ensure **kwargs exists
    has_prefer = ("prefer_lang" in ln)
    has_user_text = ("user_text" in ln)
    has_kwargs = ("**kwargs" in ln)

    if has_prefer and has_user_text and has_kwargs:
        return lines, changed

    # Build a clean one-line signature (avoid f-string)
    # Keep any existing return annotation (-> dict) if present on the same line
    ann = ""
    m_ann = re.search(r"\)\s*->\s*[^:]+:\s*$", ln)
    if m_ann:
        ann = ln[m_ann.start():].rstrip("\n")
    else:
        ann = ") -> dict:"

    new_sig = (
        indent
        + 'def news_digest(category: str = "world", limit: int = 5, time_range: str = "day", '
        + 'prefer_lang: str = "zh", user_text: str = "", **kwargs'
        + ann
        + "\n"
    )
    lines[canonical_i] = new_sig
    changed = True
    return lines, changed


def _ensure_mcp_tool_name(lines):
    """
    Ensure the decorator immediately above canonical def news_digest uses name="news_digest"
    (or add it if absent), and rename others to legacy_* to avoid tool collision.
    """
    # find canonical def index (last def news_digest)
    def_idxs = [i for i, ln in enumerate(lines) if re.match(r"^\s*def\s+news_digest\s*\(", ln)]
    if not def_idxs:
        return lines, False
    canonical_i = def_idxs[-1]

    # find decorator block above canonical def
    i = canonical_i - 1
    deco_idxs = []
    while i >= 0 and lines[i].lstrip().startswith("@"):
        deco_idxs.append(i)
        i -= 1
    deco_idxs = list(reversed(deco_idxs))

    changed = False

    # adjust decorators in that block
    for di in deco_idxs:
        if "@mcp.tool" in lines[di]:
            ln = lines[di]
            # if name= exists, set to news_digest; else inject name="news_digest",
            if "name=" in ln:
                ln2 = re.sub(r'name\s*=\s*"[^"]+"', 'name="news_digest"', ln)
            else:
                # insert name= after '('
                ln2 = re.sub(r"@mcp\.tool\s*\(", '@mcp.tool(name="news_digest", ', ln)
            if ln2 != ln:
                lines[di] = ln2
                changed = True
            break

    # rename other @mcp.tool(...) with name="news_digest" elsewhere (avoid collision)
    legacy_k = 1
    for j, ln in enumerate(lines):
        if j in deco_idxs:
            continue
        if "@mcp.tool" in ln and 'name="news_digest"' in ln:
            lines[j] = ln.replace('name="news_digest"', 'name="news_digest_legacy_' + str(legacy_k) + '"')
            legacy_k += 1
            changed = True

    return lines, changed


def main():
    if not os.path.exists(APP_PATH):
        raise SystemExit("ERROR: app.py not found in current directory")

    with open(APP_PATH, "r", encoding="utf-8") as f:
        src = f.read()

    bak = _backup(APP_PATH)
    print("Backup:", bak)

    # 1) fix decorator+def same line
    lines = src.splitlines(True)
    lines, ch1 = _split_decorator_def_same_line(lines)

    # 2) ensure signature + dedupe def news_digest
    lines, ch2 = _ensure_news_digest_signature(lines)

    # 3) ensure tool name news_digest (and avoid collisions)
    lines, ch3 = _ensure_mcp_tool_name(lines)

    src2 = "".join(lines)

    # 4) patch site_filter
    src3, ch4 = _patch_news_site_filter(src2)

    changed = ch1 or ch2 or ch3 or ch4
    if not changed:
        print("No changes needed.")
        return

    with open(APP_PATH, "w", encoding="utf-8") as f:
        f.write(src3)

    print("Patched:", APP_PATH)
    print("Changed flags:", {"split_deco_def": ch1, "sig": ch2, "tool_name": ch3, "site_filter": ch4})


if __name__ == "__main__":
    main()

