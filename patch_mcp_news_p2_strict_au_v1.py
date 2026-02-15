#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import time

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    b = "app.py.bak.news_p2_strict_au_v1_" + ts
    with open(p, "r", encoding="utf-8") as f:
        data = f.read()
    with open(b, "w", encoding="utf-8") as f:
        f.write(data)
    return b

def _find_func(src, name):
    needle = "\ndef " + name + "("
    i = src.find(needle)
    if i < 0 and src.startswith("def " + name + "("):
        return 0
    if i < 0:
        return -1
    return i + 1

def _find_next_def(src, start_idx, names):
    # find the earliest next "\ndef <name>(" after start_idx
    best = -1
    for nm in names:
        j = src.find("\ndef " + nm + "(", start_idx)
        if j >= 0 and (best < 0 or j < best):
            best = j
    return best

def _line_start(src, idx):
    j = src.rfind("\n", 0, idx)
    return 0 if j < 0 else j + 1

def _line_end(src, idx):
    j = src.find("\n", idx)
    return len(src) if j < 0 else j

def _indent_of_line(line):
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4
        else:
            break
    return n

def _find_block_by_line_prefix(lines, start_ln, end_ln, prefix):
    for i in range(start_ln, end_ln):
        if lines[i].lstrip().startswith(prefix):
            return i
    return -1

def _find_block_end_by_indent(lines, start_i, base_indent):
    # find first line after start_i whose indent <= base_indent and not blank/comment
    i = start_i + 1
    while i < len(lines):
        s = lines[i]
        if s.strip() == "":
            i += 1
            continue
        if s.lstrip().startswith("#"):
            i += 1
            continue
        ind = _indent_of_line(s)
        if ind <= base_indent:
            return i
        i += 1
    return len(lines)

def _replace_slice(lines, a, b, new_lines):
    return lines[:a] + new_lines + lines[b:]

def main():
    if not os.path.exists(APP):
        raise SystemExit("app.py not found in current dir")

    src = _read(APP)

    i0 = _find_func(src, "news_digest")
    if i0 < 0:
        raise SystemExit("Cannot find function news_digest")

    i1 = _find_next_def(src, i0 + 1, ["news_digest_legacy_fn_1", "_news__norm_host"])
    if i1 < 0:
        raise SystemExit("Cannot find end of news_digest block")

    block = src[i0:i1]
    head = src[:i0]
    tail = src[i1:]

    lines = block.splitlines(True)

    # 1) Fix aliases_map (strict, only category-title aliases)
    a0 = _find_block_by_line_prefix(lines, 0, len(lines), "aliases_map")
    if a0 < 0:
        raise SystemExit("aliases_map not found inside news_digest")

    # find def _match_cat_id line to terminate replacement
    a1 = _find_block_by_line_prefix(lines, a0 + 1, len(lines), "def _match_cat_id")
    if a1 < 0:
        raise SystemExit("def _match_cat_id not found after aliases_map")

    base_indent = _indent_of_line(lines[a0])
    ind = " " * base_indent

    aliases_new = []
    aliases_new.append(ind + "aliases_map = {\n")
    aliases_new.append(ind + "    # NOTE: aliases_map is ONLY for matching Miniflux category TITLES.\n")
    aliases_new.append(ind + "    # Do NOT put generic keywords here (e.g. 'Australia', 'AU', 'Victoria', '澳').\n")
    aliases_new.append(ind + "    # Keep it strict to avoid matching the wrong Miniflux category.\n")
    aliases_new.append(ind + "    \"world\": [\"world（世界新闻）\", \"世界新闻\", \"World\", \"Global\", \"International\"],\n")
    aliases_new.append(ind + "    \"cn_finance\": [\"cn_finance（中国财经）\", \"中国财经\", \"财经\", \"China finance\", \"CN Finance\"],\n")
    aliases_new.append(ind + "    \"au_politics\": [\"au_politics（澳洲政治）\", \"澳洲政治\", \"澳大利亚政治\", \"Australian politics\", \"AU politics\"],\n")
    aliases_new.append(ind + "    \"mel_life\": [\"mel_life（墨尔本民生）\", \"墨尔本本地\", \"墨尔本民生\", \"Melbourne local\", \"Victoria local\", \"The Guardian - Victoria\", \"Victoria\"],\n")
    aliases_new.append(ind + "    \"tech_internet\": [\"tech_internet（互联网科技）\", \"互联网科技\", \"Tech internet\", \"Tech\"],\n")
    aliases_new.append(ind + "    \"tech_gadgets\": [\"tech_gadgets（数码评测）\", \"数码新品\", \"数码评测\", \"Gadgets\", \"Reviews\"],\n")
    aliases_new.append(ind + "    \"gaming\": [\"gaming（游戏）\", \"游戏\", \"Gaming\"],\n")
    aliases_new.append(ind + "}\n")
    aliases_new.append("\n")

    lines = _replace_slice(lines, a0, a1, aliases_new)

    # 2) Make au_politics strict: no relax-fill
    # Find the relax block "if len(picked) < lim_int:" and patch it to skip relax for strict categories
    # We'll do a conservative search for that exact line and replace that whole block by indent scanning.
    relax_i = -1
    for k in range(0, len(lines)):
        if lines[k].lstrip().startswith("if len(picked) < lim_int:"):
            relax_i = k
            break
    if relax_i < 0:
        raise SystemExit("Cannot find relax block (if len(picked) < lim_int:)")

    relax_indent = _indent_of_line(lines[relax_i])
    relax_end = _find_block_end_by_indent(lines, relax_i, relax_indent)

    ind2 = " " * relax_indent
    new_relax = []
    new_relax.append(ind2 + "STRICT_NO_RELAX = {\"au_politics\"}\n")
    new_relax.append(ind2 + "if len(picked) < lim_int:\n")
    new_relax.append(ind2 + "    # For strict categories (e.g. au_politics), do NOT relax whitelist/anchor just to fill.\n")
    new_relax.append(ind2 + "    if key in STRICT_NO_RELAX:\n")
    new_relax.append(ind2 + "        relax_used = 0\n")
    new_relax.append(ind2 + "    else:\n")
    new_relax.append(ind2 + "        # Relax whitelist to fill remaining slots\n")
    new_relax.append(ind2 + "        relax_used = 1\n")
    new_relax.append(ind2 + "        _pick(zh_items, False, lim_int - len(picked), picked, seen)\n")
    new_relax.append(ind2 + "        if len(picked) < lim_int:\n")
    new_relax.append(ind2 + "            _pick(en_items, False, lim_int - len(picked), picked, seen)\n")

    lines = _replace_slice(lines, relax_i, relax_end, new_relax)

    # 3) Strengthen au_politics blacklist: add music/entertainment
    # Replace only the au_politics FILTERS entry inside the function block.
    # Find line that starts with '"au_politics": {' within FILTERS dict.
    f0 = -1
    for k in range(0, len(lines)):
        if "\"au_politics\"" in lines[k] and "whitelist" in lines[k] and "blacklist" in lines[k]:
            f0 = k
            break

    # If the dict is multi-line, fallback: find a line whose lstrip starts with '"au_politics": {'
    if f0 < 0:
        for k in range(0, len(lines)):
            if lines[k].lstrip().startswith("\"au_politics\": {"):
                f0 = k
                break

    if f0 >= 0:
        f_indent = _indent_of_line(lines[f0])
        # find the end of this dict item by scanning until a line that starts with the same indent and endswith "},"
        k = f0 + 1
        while k < len(lines):
            if _indent_of_line(lines[k]) == f_indent and lines[k].lstrip().startswith("\"") and k > f0:
                break
            # stop when we hit closing of FILTERS "}"
            if lines[k].strip().startswith("}"):
                break
            k += 1
        f1 = k

        indf = " " * f_indent
        au_entry = []
        au_entry.append(indf + "\"au_politics\": {\"whitelist\": [\n")
        au_entry.append(indf + "    \"parliament\", \"senate\", \"house\", \"election\", \"vote\", \"labor\", \"coalition\", \"liberal\", \"greens\",\n")
        au_entry.append(indf + "    \"albanese\", \"dutton\", \"budget\", \"treasury\", \"immigration\", \"visa\", \"minister\", \"cabinet\",\n")
        au_entry.append(indf + "    \"议会\", \"选举\", \"投票\", \"工党\", \"自由党\", \"绿党\", \"预算\", \"内阁\", \"移民\", \"签证\"\n")
        au_entry.append(indf + "], \"blacklist\": [\n")
        au_entry.append(indf + "    # sports\n")
        au_entry.append(indf + "    \"ufc\", \"mma\", \"sport\", \"match preview\", \"odds\", \"socceroos\", \"afl\", \"nrl\", \"cricket\", \"tennis\", \"rugby\",\n")
        au_entry.append(indf + "    \"football\", \"match\", \"goal\", \"coach\", \"player\", \"scores\", \"highlights\", \"premier league\", \"nba\", \"nfl\",\n")
        au_entry.append(indf + "    \"体育\", \"足球\", \"篮球\", \"网球\", \"板球\", \"比赛\", \"进球\", \"教练\", \"球员\", \"比分\",\n")
        au_entry.append(indf + "    # music / entertainment\n")
        au_entry.append(indf + "    \"triple j\", \"hottest 100\", \"hilltop hoods\", \"billie eilish\", \"live:\", \"music\", \"album\", \"song\",\n")
        au_entry.append(indf + "    \"concert\", \"festival\", \"chart\", \"awards\", \"celebrity\", \"gossip\",\n")
        au_entry.append(indf + "    \"音乐\", \"歌曲\", \"专辑\", \"演唱会\", \"音乐节\", \"榜单\", \"颁奖\", \"明星\", \"八卦\"\n")
        au_entry.append(indf + "]},\n")

        lines = _replace_slice(lines, f0, f1, au_entry)

    new_block = "".join(lines)
    new_src = head + new_block + tail

    bak = _backup(APP)
    _write(APP, new_src)

    print("OK patched P2 strict au_politics.")
    print("Backup:", bak)

if __name__ == "__main__":
    main()
