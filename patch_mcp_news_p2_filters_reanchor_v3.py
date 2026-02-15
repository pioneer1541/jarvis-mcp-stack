#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import sys
import time

APP = "app.py"

def _read(path):
    with io.open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _leading_spaces(s):
    n = 0
    for ch in s:
        if ch == " ":
            n += 1
        elif ch == "\t":
            # avoid tabs; treat as 4
            n += 4
        else:
            break
    return n

def _find_def_block(lines, def_name):
    # Find "def <name>(" at top-level (ignores decorators)
    idx = None
    for i, ln in enumerate(lines):
        st = ln.lstrip()
        if st.startswith("def " + def_name + "(") or st.startswith("def " + def_name + " ("):
            # require top-level indent
            if _leading_spaces(ln) == 0:
                idx = i
                break
    if idx is None:
        raise RuntimeError("Cannot find def {0} at top-level".format(def_name))

    # find body indent
    body_indent = None
    j = idx + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "":
            j += 1
            continue
        if ln.lstrip().startswith("#"):
            j += 1
            continue
        body_indent = _leading_spaces(ln)
        break
    if body_indent is None:
        raise RuntimeError("Cannot detect body indent for {0}".format(def_name))

    # find end of block by indentation drop back to 0 with a def/class
    end = len(lines)
    k = idx + 1
    while k < len(lines):
        ln = lines[k]
        if ln.strip() == "":
            k += 1
            continue
        ind = _leading_spaces(ln)
        st = ln.lstrip()
        if ind == 0 and (st.startswith("def ") or st.startswith("class ")):
            end = k
            break
        k += 1

    return idx, end, body_indent

def _remove_filters_blocks(func_lines, body_indent):
    # remove any FILTERS blocks inside the function at the same body indent
    out = []
    i = 0
    removed = 0
    target_prefix = " " * body_indent + "FILTERS"
    begin_mark = "NEWS_FILTERS_P2_BEGIN"
    end_mark = "NEWS_FILTERS_P2_END"

    while i < len(func_lines):
        ln = func_lines[i]

        # marker-based removal
        if begin_mark in ln:
            removed += 1
            i += 1
            while i < len(func_lines) and (end_mark not in func_lines[i]):
                i += 1
            if i < len(func_lines):
                i += 1
            continue

        # direct "FILTERS = {"
        if ln.startswith(target_prefix) and ("=" in ln) and ("{" in ln):
            removed += 1
            # brace depth from this line onward
            depth = ln.count("{") - ln.count("}")
            i += 1
            while i < len(func_lines) and depth > 0:
                depth += func_lines[i].count("{") - func_lines[i].count("}")
                i += 1
            # also skip trailing blank line if present
            while i < len(func_lines) and func_lines[i].strip() == "":
                i += 1
            continue

        out.append(ln)
        i += 1

    return out, removed

def _find_aliases_map_end(func_lines, body_indent):
    # find aliases_map assignment and its closing "}" line at same indent
    pref = " " * body_indent
    start = None
    for i, ln in enumerate(func_lines):
        if ln.startswith(pref + "aliases_map") and ("=" in ln) and ("{" in ln):
            start = i
            break
    if start is None:
        # fallback: insert near start of function body (after docstring if any)
        return None

    depth = func_lines[start].count("{") - func_lines[start].count("}")
    j = start + 1
    while j < len(func_lines) and depth > 0:
        depth += func_lines[j].count("{") - func_lines[j].count("}")
        j += 1
    # j is first line after dict close
    return j

def _make_filters_block(body_indent):
    pref = " " * body_indent
    lines = []
    lines.append(pref + "# --- NEWS_FILTERS_P2_BEGIN ---\n")
    lines.append(pref + "FILTERS = {\n")
    lines.append(pref + "    \"world\": {\n")
    lines.append(pref + "        \"whitelist\": [],\n")
    lines.append(pref + "        \"blacklist\": [\"ufc\", \"mma\", \"boxing odds\", \"celebrity gossip\", \"porn\", \"onlyfans\"],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"cn_finance\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"财经\", \"经济\", \"金融\", \"股\", \"a股\", \"港股\", \"美股\", \"债\", \"基金\", \"利率\", \"通胀\", \"人民币\", \"央行\", \"证监\",\n")
    lines.append(pref + "            \"bank\", \"stocks\", \"market\", \"bond\", \"yields\", \"cpi\", \"gdp\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "        \"blacklist\": [\"ufc\", \"mma\", \"赛后\", \"足球\", \"篮球\", \"综艺\", \"八卦\", \"明星\", \"电影\", \"电视剧\"],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"au_politics\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"parliament\", \"senate\", \"house\", \"election\", \"labor\", \"coalition\", \"liberal\", \"greens\",\n")
    lines.append(pref + "            \"albanese\", \"dutton\", \"budget\", \"treasury\", \"immigration\", \"visa\", \"minister\", \"cabinet\",\n")
    lines.append(pref + "            \"议会\", \"选举\", \"工党\", \"自由党\", \"绿党\", \"预算\", \"内阁\", \"移民\", \"签证\"\n")
    lines.append(pref + "        ],\n")
    # P2: stricter topicban (sports + entertainment)
    lines.append(pref + "        \"blacklist\": [\n")
    lines.append(pref + "            \"ufc\", \"mma\", \"sport\", \"match preview\", \"odds\", \"celebrity\",\n")
    lines.append(pref + "            \"socceroos\", \"afl\", \"nrl\", \"cricket\", \"tennis\", \"rugby\", \"football\", \"match\", \"goal\", \"coach\", \"player\", \"scores\", \"highlights\",\n")
    lines.append(pref + "            \"premier league\", \"nba\", \"nfl\", \"triple j\", \"hottest 100\", \"hilltop\", \"billie\",\n")
    lines.append(pref + "            \"体育\", \"足球\", \"篮球\", \"网球\", \"板球\", \"比赛\", \"进球\", \"教练\", \"球员\", \"比分\", \"音乐\", \"演唱会\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"mel_life\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"melbourne\", \"victoria\", \"vic\", \"cbd\", \"ptv\", \"metro\", \"tram\", \"train\", \"bus\",\n")
    lines.append(pref + "            \"police\", \"fire\", \"ambulance\", \"road\", \"freeway\", \"yarra\", \"docklands\", \"st kilda\",\n")
    lines.append(pref + "            \"墨尔本\", \"维州\", \"本地\", \"民生\", \"交通\", \"电车\", \"火车\", \"警方\", \"火警\", \"道路\"\n")
    lines.append(pref + "        ],\n")
    # P2: lawn topicban
    lines.append(pref + "        \"blacklist\": [\n")
    lines.append(pref + "            \"ufc\", \"mma\", \"celebrity\", \"gossip\", \"crypto shill\",\n")
    lines.append(pref + "            \"lawn\", \"garden\", \"ugliest\", \"world's ugliest\", \"ugliest lawn\", \"yard\", \"groundskeeper\",\n")
    lines.append(pref + "            \"草坪\", \"花园\", \"最丑\", \"世界最丑\", \"最丑草坪\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"tech_internet\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"ai\", \"openai\", \"google\", \"microsoft\", \"meta\", \"apple\", \"amazon\", \"tiktok\", \"x.com\", \"twitter\", \"github\",\n")
    lines.append(pref + "            \"open source\", \"linux\", \"android\", \"ios\", \"cloud\", \"security\", \"privacy\", \"regulation\", \"chip\", \"semiconductor\",\n")
    lines.append(pref + "            \"人工智能\", \"开源\", \"网络安全\", \"隐私\", \"监管\", \"芯片\", \"半导体\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "        \"blacklist\": [\"ufc\", \"mma\", \"crime\", \"murder\", \"celebrity\", \"gossip\", \"lottery\", \"horoscope\"],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"tech_gadgets\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"review\", \"hands-on\", \"launch\", \"iphone\", \"ipad\", \"mac\", \"samsung\", \"pixel\", \"camera\", \"laptop\", \"headphones\",\n")
    lines.append(pref + "            \"oled\", \"cpu\", \"gpu\", \"benchmark\", \"评测\", \"上手\", \"新品\", \"发布\", \"开箱\", \"相机\", \"手机\", \"耳机\", \"笔记本\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "        \"blacklist\": [\"ufc\", \"mma\", \"crime\", \"celebrity\", \"gossip\"],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "    \"gaming\": {\n")
    lines.append(pref + "        \"whitelist\": [\n")
    lines.append(pref + "            \"game\", \"gaming\", \"steam\", \"playstation\", \"ps5\", \"xbox\", \"nintendo\", \"switch\", \"patch\", \"update\",\n")
    lines.append(pref + "            \"dlc\", \"release\", \"trailer\", \"esports\", \"游戏\", \"主机\", \"更新\", \"补丁\", \"发售\", \"预告\"\n")
    lines.append(pref + "        ],\n")
    lines.append(pref + "        \"blacklist\": [\"ufc\", \"mma\", \"boxing\", \"wwe\", \"football\", \"basketball\", \"cricket\", \"horse racing\"],\n")
    lines.append(pref + "    },\n")

    lines.append(pref + "}\n")
    lines.append(pref + "# --- NEWS_FILTERS_P2_END ---\n\n")
    return lines

def main():
    if not os.path.exists(APP):
        raise RuntimeError("app.py not found in current directory")

    src = _read(APP)
    lines = src.splitlines(True)

    s0, e0, body_indent = _find_def_block(lines, "news_digest")
    func = lines[s0:e0]

    func2, removed = _remove_filters_blocks(func, body_indent)

    insert_at = _find_aliases_map_end(func2, body_indent)
    if insert_at is None:
        # insert after function signature/docstring region: after first blank line following any docstring
        # Keep simple: insert right after the first non-empty line after def
        j = 1
        while j < len(func2) and func2[j].strip() == "":
            j += 1
        insert_at = j

    filters_block = _make_filters_block(body_indent)

    new_func = func2[:insert_at] + filters_block + func2[insert_at:]

    new_lines = lines[:s0] + new_func + lines[e0:]
    _write(APP, "".join(new_lines))

    print("OK: re-anchored FILTERS inside news_digest (P2). removed_old_filters_blocks={0} body_indent={1} insert_at={2}".format(removed, body_indent, insert_at))
    print("Next: run `python3 -m py_compile app.py` and then recreate container.")

if __name__ == "__main__":
    main()
