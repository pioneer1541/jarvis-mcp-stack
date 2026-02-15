import re
import sys

APP = "app.py"

def rfile(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def wfile(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def find_news_digest_block(src):
    # start: def news_digest(
    m0 = re.search(r'(?m)^def\s+news_digest\s*\(', src)
    if not m0:
        return None
    # end: next top-level def after news_digest, prefer legacy marker
    m1 = re.search(r'(?m)^def\s+news_digest_legacy_fn_1\s*\(|(?m)^def\s+_news__norm_host\s*\(', src[m0.end():])
    if not m1:
        return (m0.start(), len(src))
    return (m0.start(), m0.end() + m1.start())

def indent_of_line(line):
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

    if "TOPIC_BANS" in body and "dropped_topicban" in body:
        print("OK: already has TOPIC_BANS + dropped_topicban in news_digest block")
        return

    lines = body.splitlines(True)

    # Locate cfg line: cfg = FILTERS.get(key) ...
    cfg_i = None
    for i, ln in enumerate(lines):
        if "cfg = FILTERS.get(" in ln:
            cfg_i = i
            break
    if cfg_i is None:
        print("ERR: cannot find cfg = FILTERS.get(...) in news_digest")
        sys.exit(2)

    indent = indent_of_line(lines[cfg_i])

    # Insert TOPIC_BANS and helper (used inside _pick)
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

    # Ensure dropped_topicban init near dropped_blacklist init
    # Search for dropped_blacklist = 0 in block
    db_i = None
    for i, ln in enumerate(lines):
        if re.search(r'^\s*dropped_blacklist\s*=\s*0\b', ln):
            db_i = i
            break
    if db_i is None:
        # fallback: maybe tuple init exists, place it near dropped_whitelist init
        for i, ln in enumerate(lines):
            if re.search(r'^\s*dropped_whitelist\s*=\s*0\b', ln):
                db_i = i
                break
    if db_i is None:
        print("ERR: cannot find dropped_blacklist/whitelist init in news_digest")
        sys.exit(2)

    ind_db = indent_of_line(lines[db_i])
    # Insert if not already
    has_dt = any(re.search(r'^\s*dropped_topicban\s*=\s*0\b', x) for x in lines[max(0, db_i-3):min(len(lines), db_i+6)])
    if not has_dt:
        lines[db_i+1:db_i+1] = [ind_db + "dropped_topicban = 0\n"]

    # Patch _pick(): add nonlocal and topicban check
    # Find def _pick(
    pick_i = None
    for i, ln in enumerate(lines):
        if re.search(r'^\s*def\s+_pick\s*\(', ln):
            pick_i = i
            break
    if pick_i is None:
        print("ERR: cannot find def _pick(...) inside news_digest; your version may differ.")
        sys.exit(2)

    ind_pick_def = indent_of_line(lines[pick_i])
    ind_pick = ind_pick_def + "    "

    # Ensure nonlocal line includes dropped_topicban
    nonlocal_i = None
    for i in range(pick_i+1, min(pick_i+40, len(lines))):
        if re.search(r'^\s*nonlocal\b', lines[i]):
            nonlocal_i = i
            break
        # stop if we hit another def at same indent
        if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
            break

    if nonlocal_i is not None:
        if "dropped_topicban" not in lines[nonlocal_i]:
            # add to existing nonlocal list
            ln = lines[nonlocal_i].rstrip("\n")
            if ln.endswith(")"):
                # unlikely
                pass
            if ln.endswith("\\"):
                # do not handle continued line, just insert a new nonlocal line
                lines[nonlocal_i+1:nonlocal_i+1] = [ind_pick + "nonlocal dropped_topicban\n"]
            else:
                # append with comma
                lines[nonlocal_i] = ln + ", dropped_topicban\n"
    else:
        # insert a new nonlocal line right after def _pick line
        lines[pick_i+1:pick_i+1] = [ind_pick + "nonlocal dropped_topicban\n"]

    # Insert topicban check after blacklist drop block inside _pick
    # Find first dropped_blacklist increment in _pick, then find a following continue, insert after it
    inserted = False
    for i in range(pick_i+1, len(lines)):
        if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
            # reached next nested def at same level (rare), stop
            break
        if "dropped_blacklist" in lines[i] and "+=" in lines[i]:
            # search next 8 lines for 'continue'
            cont_i = None
            for j in range(i, min(i+10, len(lines))):
                if re.search(r'^\s*continue\b', lines[j].strip()):
                    cont_i = j
                    break
                if "continue" in lines[j]:
                    cont_i = j
                    break
            if cont_i is None:
                continue
            ind_if = indent_of_line(lines[i-1])  # usually the "if ..." line indent
            # Determine text variable used for blacklist, try to find _kw_hit(<var>, bl) nearby
            txt_var = "txt"
            for j in range(max(pick_i, i-8), min(i+8, len(lines))):
                m = re.search(r'_kw_hit\(\s*([^,]+)\s*,\s*bl\s*\)', lines[j])
                if m:
                    txt_var = m.group(1).strip()
                    break
            ins = []
            ins.append(ind_if + "if _kw_hit({0}, (TOPIC_BANS.get(key) or [])):\n".format(txt_var))
            ins.append(ind_if + "    dropped_topicban += 1\n")
            ins.append(ind_if + "    continue\n")
            lines[cont_i+1:cont_i+1] = ins
            inserted = True
            break

    if not inserted:
        # fallback: insert before whitelist drop block
        for i in range(pick_i+1, len(lines)):
            if re.search(r'^\s*def\s+\w+', lines[i]) and indent_of_line(lines[i]) == ind_pick_def:
                break
            if "dropped_whitelist" in lines[i] and "+=" in lines[i]:
                ind_if = indent_of_line(lines[i-1])
                txt_var = "txt"
                for j in range(max(pick_i, i-10), min(i+10, len(lines))):
                    m = re.search(r'_kw_hit\(\s*([^,]+)\s*,\s*wl\s*\)', lines[j])
                    if m:
                        txt_var = m.group(1).strip()
                        break
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

    # Add dropped_topicban into stats_detail dict
    # Find where stats_detail dict is built (line containing '"dropped_whitelist"' or dropped_whitelist)
    sd_i = None
    for i, ln in enumerate(lines):
        if "\"dropped_whitelist\"" in ln and "dropped_whitelist" in ln:
            sd_i = i
            break
    if sd_i is not None:
        ind_sd = indent_of_line(lines[sd_i])
        lines[sd_i+1:sd_i+1] = [ind_sd + "\"dropped_topicban\": dropped_topicban,\n"]
    else:
        # fallback: search dropped_blacklist entry
        for i, ln in enumerate(lines):
            if "\"dropped_blacklist\"" in ln and "dropped_blacklist" in ln:
                ind_sd = indent_of_line(ln)
                lines[i+1:i+1] = [ind_sd + "\"dropped_topicban\": dropped_topicban,\n"]
                break

    new_body = "".join(lines)
    wfile(APP, head + new_body + tail)
    print("OK: patched P2 topicban v2 (hooked into _pick + stats_detail).")

if __name__ == "__main__":
    main()
