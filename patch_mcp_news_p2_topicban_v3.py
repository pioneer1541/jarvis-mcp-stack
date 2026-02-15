import re
import sys

APP = "app.py"

def rfile(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def wfile(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def find_news_digest_block(src: str):
    m0 = re.search(r'^\s*def\s+news_digest\s*\(', src, flags=re.MULTILINE)
    if not m0:
        return None
    start = m0.start()

    # find the next top-level def after this one
    # scan from m0.end() to end, find a line starting with "def " (no indent)
    m1 = re.search(r'^(def\s+\w+\s*\()', src[m0.end():], flags=re.MULTILINE)
    if not m1:
        end = len(src)
    else:
        end = m0.end() + m1.start()
    return (start, end)

def indent_of_line(line: str) -> str:
    m = re.match(r'^(\s*)', line)
    return m.group(1) if m else ""

def main():
    src = rfile(APP)
    blk = find_news_digest_block(src)
    if not blk:
        print("ERR: cannot locate def news_digest(")
        sys.exit(2)

    a, b = blk
    head = src[:a]
    body = src[a:b]
    tail = src[b:]

    # idempotent
    if "NEWS_TOPICBAN_P2 BEGIN" in body and "dropped_topicban" in body:
        print("OK: already patched (P2 topicban present).")
        return

    lines = body.splitlines(True)

    # 1) insert TOPIC_BANS near cfg = FILTERS.get(...)
    cfg_i = None
    for i, ln in enumerate(lines):
        if "cfg = FILTERS.get(" in ln:
            cfg_i = i
            break
    if cfg_i is None:
        print("ERR: cannot find cfg = FILTERS.get(...) in news_digest")
        sys.exit(2)

    indent = indent_of_line(lines[cfg_i])

    insert_topic = []
    insert_topic.append(indent + "# --- NEWS_TOPICBAN_P2 BEGIN ---\n")
    insert_topic.append(indent + "TOPIC_BANS = {\n")
    insert_topic.append(indent + "    \"au_politics\": [\n")
    insert_topic.append(indent + "        \"socceroos\", \"st pauli\", \"afl\", \"nrl\", \"a-league\", \"aleague\", \"a league\",\n")
    insert_topic.append(indent + "        \"premier league\", \"bundesliga\", \"uefa\", \"champions league\",\n")
    insert_topic.append(indent + "        \"goal\", \"fixture\", \"kickoff\", \"striker\", \"midfielder\", \"transfer\", \"scores\", \"highlights\",\n")
    insert_topic.append(indent + "    ],\n")
    insert_topic.append(indent + "    \"mel_life\": [\n")
    insert_topic.append(indent + "        \"ugliest lawn\", \"lawn\", \"garden\", \"grass\", \"yard\", \"groundskeeper\", \"watering\", \"mowing\",\n")
    insert_topic.append(indent + "        \"草坪\", \"花园\", \"花園\", \"最丑\", \"最醜\",\n")
    insert_topic.append(indent + "    ],\n")
    insert_topic.append(indent + "}\n")
    insert_topic.append(indent + "# --- NEWS_TOPICBAN_P2 END ---\n")
    insert_topic.append("\n")

    lines[cfg_i:cfg_i] = insert_topic

    # 2) ensure dropped_topicban init (place after dropped_blacklist init if found)
    db_i = None
    for i, ln in enumerate(lines):
        if re.search(r'^\s*dropped_blacklist\s*=\s*0\b', ln):
            db_i = i
            break
    if db_i is None:
        for i, ln in enumerate(lines):
            if re.search(r'^\s*dropped_whitelist\s*=\s*0\b', ln):
                db_i = i
                break
    if db_i is None:
        print("ERR: cannot find dropped_blacklist/whitelist init in news_digest")
        sys.exit(2)

    ind_db = indent_of_line(lines[db_i])
    if not any(re.search(r'^\s*dropped_topicban\s*=\s*0\b', x) for x in lines[max(0, db_i-3):min(len(lines), db_i+8)]):
        lines[db_i+1:db_i+1] = [ind_db + "dropped_topicban = 0\n"]

    # 3) patch _pick(): add nonlocal + topicban check
    pick_i = None
    for i, ln in enumerate(lines):
        if re.search(r'^\s*def\s+_pick\s*\(', ln):
            pick_i = i
            break
    if pick_i is None:
        print("ERR: cannot find def _pick(...) inside news_digest")
        sys.exit(2)

    ind_pick_def = indent_of_line(lines[pick_i])
    ind_pick = ind_pick_def + "    "

    # ensure nonlocal includes dropped_topicban
    nonlocal_i = None
    for i in range(pick_i+1, min(pick_i+50, len(lines))):
        if re.search(r'^\s*nonlocal\b', lines[i]):
            nonlocal_i = i
            break
        if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
            break

    if nonlocal_i is not None:
        if "dropped_topicban" not in lines[nonlocal_i]:
            ln0 = lines[nonlocal_i].rstrip("\n")
            lines[nonlocal_i] = ln0 + ", dropped_topicban\n"
    else:
        lines[pick_i+1:pick_i+1] = [ind_pick + "nonlocal dropped_topicban\n"]

    # insert topicban check after blacklist drop+continue (preferred)
    inserted = False
    for i in range(pick_i+1, len(lines)):
        if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
            break
        if "dropped_blacklist" in lines[i] and "+=" in lines[i]:
            cont_i = None
            for j in range(i, min(i+12, len(lines))):
                if lines[j].lstrip().startswith("continue"):
                    cont_i = j
                    break
            if cont_i is None:
                continue

            # try detect txt var used in _kw_hit(txt, bl)
            txt_var = "txt"
            for j in range(max(pick_i, i-12), min(i+12, len(lines))):
                m = re.search(r'_kw_hit\(\s*([^,]+)\s*,\s*bl\s*\)', lines[j])
                if m:
                    txt_var = m.group(1).strip()
                    break

            ind_if = indent_of_line(lines[i-1])
            ins = []
            ins.append(ind_if + "if _kw_hit({0}, (TOPIC_BANS.get(key) or [])):\n".format(txt_var))
            ins.append(ind_if + "    dropped_topicban += 1\n")
            ins.append(ind_if + "    continue\n")
            lines[cont_i+1:cont_i+1] = ins
            inserted = True
            break

    # fallback: insert before whitelist block
    if not inserted:
        for i in range(pick_i+1, len(lines)):
            if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
                break
            if "dropped_whitelist" in lines[i] and "+=" in lines[i]:
                txt_var = "txt"
                for j in range(max(pick_i, i-12), min(i+12, len(lines))):
                    m = re.search(r'_kw_hit\(\s*([^,]+)\s*,\s*wl\s*\)', lines[j])
                    if m:
                        txt_var = m.group(1).strip()
                        break
                ind_if = indent_of_line(lines[i-1])
                ins = []
                ins.append(ind_if + "if _kw_hit({0}, (TOPIC_BANS.get(key) or [])):\n".format(txt_var))
                ins.append(ind_if + "    dropped_topicban += 1\n")
                ins.append(ind_if + "    continue\n")
                lines[i:i] = ins
                inserted = True
                break

    if not inserted:
        print("ERR: cannot insert topicban check into _pick()")
        sys.exit(2)

    # 4) add dropped_topicban into stats_detail dict
    sd_i = None
    for i, ln in enumerate(lines):
        if "\"dropped_whitelist\"" in ln and "dropped_whitelist" in ln:
            sd_i = i
            break
    if sd_i is not None:
        ind_sd = indent_of_line(lines[sd_i])
        lines[sd_i+1:sd_i+1] = [ind_sd + "\"dropped_topicban\": dropped_topicban,\n"]
    else:
        for i, ln in enumerate(lines):
            if "\"dropped_blacklist\"" in ln and "dropped_blacklist" in ln:
                ind_sd = indent_of_line(ln)
                lines[i+1:i+1] = [ind_sd + "\"dropped_topicban\": dropped_topicban,\n"]
                break

    new_body = "".join(lines)
    wfile(APP, head + new_body + tail)
    print("OK: patched P2 topicban v3 (no inline flags; hooked into _pick + stats_detail).")

if __name__ == "__main__":
    main()
