import re
import sys

APP = "app.py"

def _read(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)

def main():
    src = _read(APP)

    # Guard: must be Miniflux-filtering version (has FILTERS + dropped_whitelist etc)
    if ("FILTERS" not in src) or ("dropped_whitelist" not in src) or ("news_digest" not in src):
        print("ERR: app.py does not look like the Miniflux-filtering version (FILTERS/dropped_whitelist not found). Abort.")
        sys.exit(2)

    # Avoid double patch
    if "TOPIC_BANS = {" in src and "dropped_topicban" in src:
        print("OK: already patched (topicban).")
        return

    lines = src.splitlines(True)

    # 1) Find inside news_digest(): where wl/bl are defined, insert TOPIC_BANS + _passes_topicban
    #    We insert right after the line: bl = cfg.get("blacklist") or []
    bl_idx = None
    for i, ln in enumerate(lines):
        if "bl = cfg.get(\"blacklist\")" in ln and "or []" in ln:
            bl_idx = i
            break
    if bl_idx is None:
        print("ERR: cannot find bl = cfg.get(\"blacklist\") or []")
        sys.exit(2)

    m = re.match(r"^(\s*)", lines[bl_idx])
    indent = m.group(1) if m else ""

    insert1 = []
    insert1.append("\n")
    insert1.append(indent + "# --- NEWS_TOPICBAN_P2 BEGIN ---\n")
    insert1.append(indent + "TOPIC_BANS = {\n")
    insert1.append(indent + "    \"au_politics\": [\n")
    insert1.append(indent + "        # sports noise\n")
    insert1.append(indent + "        \"socceroos\", \"afl\", \"nrl\", \"a-league\", \"aleague\", \"a league\",\n")
    insert1.append(indent + "        \"match\", \"goal\", \"fixture\", \"kickoff\", \"coach\", \"striker\", \"midfielder\",\n")
    insert1.append(indent + "        \"st pauli\", \"bundesliga\", \"premier league\", \"champions league\", \"uefa\",\n")
    insert1.append(indent + "        \"injury\", \"transfer\", \"scores\", \"highlights\",\n")
    insert1.append(indent + "    ],\n")
    insert1.append(indent + "    \"mel_life\": [\n")
    insert1.append(indent + "        # lawn / garden fluff\n")
    insert1.append(indent + "        \"ugliest lawn\", \"lawn\", \"garden\", \"grass\", \"yard\", \"groundskeeper\", \"watering\", \"mowing\",\n")
    insert1.append(indent + "        \"草坪\", \"花园\", \"花園\", \"最丑\", \"最醜\",\n")
    insert1.append(indent + "    ],\n")
    insert1.append(indent + "}\n")
    insert1.append("\n")
    insert1.append(indent + "def _passes_topicban(it: dict) -> bool:\n")
    insert1.append(indent + "    bans = TOPIC_BANS.get(key) or []\n")
    insert1.append(indent + "    if not bans:\n")
    insert1.append(indent + "        return True\n")
    insert1.append(indent + "    txt = \"{0} {1} {2}\".format(it.get(\"title\") or \"\", it.get(\"snippet\") or \"\", it.get(\"source\") or \"\")\n")
    insert1.append(indent + "    return (not _kw_hit(txt, bans))\n")
    insert1.append(indent + "# --- NEWS_TOPICBAN_P2 END ---\n")
    insert1.append("\n")

    # Insert after bl line
    lines[bl_idx+1:bl_idx+1] = insert1

    # 2) Add dropped_topicban counter near dropped_blacklist init
    #    Find first occurrence of dropped_blacklist assignment line.
    src2 = "".join(lines)
    lines2 = src2.splitlines(True)

    init_idx = None
    for i, ln in enumerate(lines2):
        if "dropped_blacklist" in ln and "=" in ln and "dropped_whitelist" in ln:
            init_idx = i
            break
        if re.search(r"\bdropped_blacklist\s*=\s*\d+", ln):
            init_idx = i
            break
    if init_idx is None:
        print("ERR: cannot find dropped_* counter init")
        sys.exit(2)

    # If there is a tuple init, just append a new line after it; else patch numeric init.
    m2 = re.match(r"^(\s*)", lines2[init_idx])
    indent2 = m2.group(1) if m2 else ""
    if "dropped_topicban" not in lines2[init_idx]:
        # add a separate init line
        lines2[init_idx+1:init_idx+1] = [indent2 + "dropped_topicban = 0\n"]

    # 3) In filtering loop: add topicban check right after blacklist check (or before whitelist)
    src3 = "".join(lines2)
    lines3 = src3.splitlines(True)

    # Find the first place where it does: if not _passes_blacklist(...): dropped_blacklist += 1; continue
    # Then insert topicban check immediately after that block.
    insert_done = False
    for i in range(0, len(lines3) - 2):
        if "_passes_blacklist" in lines3[i] and "continue" in lines3[i+1:i+4].__str__():
            # Look for a "continue" within next 3 lines
            j = None
            for k in range(i, min(i+6, len(lines3))):
                if "continue" in lines3[k]:
                    j = k
                    break
            if j is None:
                continue

            # After that continue line, insert topicban check (same indent as the blacklist if)
            indent3 = re.match(r"^(\s*)", lines3[i]).group(1)
            ins = []
            ins.append(indent3 + "if not _passes_topicban(it):\n")
            ins.append(indent3 + "    dropped_topicban += 1\n")
            ins.append(indent3 + "    continue\n")
            lines3[j+1:j+1] = ins
            insert_done = True
            break

    if not insert_done:
        # fallback: insert before whitelist check
        for i in range(0, len(lines3) - 1):
            if "_passes_whitelist" in lines3[i]:
                indent3 = re.match(r"^(\s*)", lines3[i]).group(1)
                ins = []
                ins.append(indent3 + "if not _passes_topicban(it):\n")
                ins.append(indent3 + "    dropped_topicban += 1\n")
                ins.append(indent3 + "    continue\n")
                lines3[i:i] = ins
                insert_done = True
                break

    if not insert_done:
        print("ERR: cannot find where to insert topicban check in filtering loop")
        sys.exit(2)

    # 4) Add dropped_topicban into stats_detail dict (near dropped_whitelist etc)
    src4 = "".join(lines3)
    lines4 = src4.splitlines(True)

    # find stats_detail assignment block by key 'dropped_blacklist'
    sd_idx = None
    for i, ln in enumerate(lines4):
        if "\"dropped_blacklist\"" in ln and "dropped_blacklist" in ln:
            sd_idx = i
            break
    if sd_idx is not None:
        # insert after dropped_whitelist line if possible, else after dropped_blacklist
        ins_at = sd_idx + 1
        for i in range(sd_idx, min(sd_idx + 20, len(lines4))):
            if "\"dropped_whitelist\"" in lines4[i]:
                ins_at = i + 1
                break
        indent4 = re.match(r"^(\s*)", lines4[sd_idx]).group(1)
        lines4[ins_at:ins_at] = [indent4 + "\"dropped_topicban\": dropped_topicban,\n"]
    else:
        print("WARN: stats_detail dict not found; skipped adding dropped_topicban to stats_detail")

    _write(APP, "".join(lines4))
    print("OK: patched P2 topicban (au_politics sports + mel_life lawn).")

if __name__ == "__main__":
    main()
