#!/usr/bin/env python3
# patch_mcp_news_p2_fillguard_v1.py
# Goal:
#  1) Reverse-alias map category input (e.g., "Victoria") -> internal key (e.g., "mel_life")
#  2) Remove/guard the final "fill from all_items without filters" fallback
#  3) (Optional) include dropped_topicban in stats_detail for easier debugging

import io
import os
import sys


def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()


def write_text(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def find_line_idx(lines, needle):
    for i, ln in enumerate(lines):
        if needle in ln:
            return i
    return -1


def get_indent(s):
    return s[: len(s) - len(s.lstrip(" "))]


def main():
    path = "app.py"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        path = sys.argv[1].strip()

    src = read_text(path)
    lines = src.splitlines(True)

    # ---------------------------
    # P2-2: reverse-alias mapping
    # Insert after: key = (category or "").strip()
    # ---------------------------
    key_line = -1
    for i, ln in enumerate(lines):
        if "key = (category or \"\").strip()" in ln or "key = (category or '').strip()" in ln:
            key_line = i
            break

    if key_line < 0:
        print("ERR: cannot find key assignment line")
        sys.exit(2)

    # Avoid double-insert if already present
    marker = "NEWS_P2_REVERSE_ALIAS"
    already = False
    for j in range(max(0, key_line - 5), min(len(lines), key_line + 20)):
        if marker in lines[j]:
            already = True
            break

    if not already:
        ind = get_indent(lines[key_line])
        insert = []
        insert.append(ind + "# --- " + marker + " BEGIN ---\n")
        insert.append(ind + "category_input = key\n")
        insert.append(ind + "try:\n")
        insert.append(ind + "    # If user passes a display name like 'Victoria', map it back to internal key like 'mel_life'\n")
        insert.append(ind + "    if key and (key not in aliases_map):\n")
        insert.append(ind + "        for _k, _als in (aliases_map or {}).items():\n")
        insert.append(ind + "            for _a in (_als or []):\n")
        insert.append(ind + "                try:\n")
        insert.append(ind + "                    if (key == _a) or (str(_a) in str(key)) or (str(key) in str(_a)):\n")
        insert.append(ind + "                        key = _k\n")
        insert.append(ind + "                        raise StopIteration()\n")
        insert.append(ind + "                except StopIteration:\n")
        insert.append(ind + "                    raise\n")
        insert.append(ind + "                except Exception:\n")
        insert.append(ind + "                    continue\n")
        insert.append(ind + "except StopIteration:\n")
        insert.append(ind + "    pass\n")
        insert.append(ind + "except Exception:\n")
        insert.append(ind + "    pass\n")
        insert.append(ind + "# --- " + marker + " END ---\n")

        lines[key_line + 1 : key_line + 1] = insert

    # ---------------------------
    # P2-1: guard the final unconditional fill block
    # Replace:
    #   if len(picked) < lim_int:
    #       for it in all_items:
    #           ...
    #           picked.append(it)
    #
    # with:
    #   if len(picked) < lim_int:
    #       # Only fill with items that still pass blacklist/topicban/anchor
    #       # For strict or ban-configured categories, do NOT backfill with unfiltered items.
    # ---------------------------
    # Find the LAST occurrence of "if len(picked) < lim_int:" before "out_items = picked[:lim_int]"
    out_items_line = find_line_idx(lines, "out_items = picked[:lim_int]")
    if out_items_line < 0:
        print("ERR: cannot find out_items assignment line")
        sys.exit(2)

    target_if = -1
    for i in range(out_items_line - 1, -1, -1):
        if "if len(picked) < lim_int" in lines[i]:
            # ensure it's the unconditional fill one by checking next few lines includes "for it in all_items"
            look = "".join(lines[i : min(len(lines), i + 25)])
            if "for it in all_items" in look:
                target_if = i
                break

    if target_if < 0:
        print("ERR: cannot find unconditional fill block")
        sys.exit(2)

    base_ind = get_indent(lines[target_if])
    # Determine block end by indentation
    j = target_if + 1
    while j < len(lines):
        ln = lines[j]
        if ln.strip() == "":
            j += 1
            continue
        ind = get_indent(ln)
        if len(ind) <= len(base_ind):
            break
        j += 1
    old_block = lines[target_if:j]

    # Build new guarded block
    nb = []
    nb.append(base_ind + "if len(picked) < lim_int:\n")
    nb.append(base_ind + "    # P2: Do NOT backfill with unfiltered items (prevents banned topics leaking back)\n")
    nb.append(base_ind + "    has_bans = bool(bl) or bool((TOPIC_BANS.get(key) or []))\n")
    nb.append(base_ind + "    is_strict = False\n")
    nb.append(base_ind + "    try:\n")
    nb.append(base_ind + "        is_strict = (key in STRICT_WHITELIST_CATS)\n")
    nb.append(base_ind + "    except Exception:\n")
    nb.append(base_ind + "        is_strict = False\n")
    nb.append(base_ind + "    if (not is_strict) and (not has_bans):\n")
    nb.append(base_ind + "        # benign categories only: allow soft backfill but still avoid duplicates\n")
    nb.append(base_ind + "        for it in all_items:\n")
    nb.append(base_ind + "            if len(picked) >= lim_int:\n")
    nb.append(base_ind + "                break\n")
    nb.append(base_ind + "            nt = _norm_title(it.get(\"title\") or \"\")\n")
    nb.append(base_ind + "            if nt and nt in seen:\n")
    nb.append(base_ind + "                continue\n")
    nb.append(base_ind + "            seen.add(nt)\n")
    nb.append(base_ind + "            picked.append(it)\n")
    nb.append(base_ind + "    else:\n")
    nb.append(base_ind + "        # strict or ban-configured categories: only backfill with items that still pass filters\n")
    nb.append(base_ind + "        for it in all_items:\n")
    nb.append(base_ind + "            if len(picked) >= lim_int:\n")
    nb.append(base_ind + "                break\n")
    nb.append(base_ind + "            if (not _passes_blacklist(it)):\n")
    nb.append(base_ind + "                continue\n")
    nb.append(base_ind + "            if (not _passes_topicban(it)):\n")
    nb.append(base_ind + "                continue\n")
    nb.append(base_ind + "            if (not _passes_anchor_topic(it, False)):\n")
    nb.append(base_ind + "                continue\n")
    nb.append(base_ind + "            nt = _norm_title(it.get(\"title\") or \"\")\n")
    nb.append(base_ind + "            if nt and nt in seen:\n")
    nb.append(base_ind + "                continue\n")
    nb.append(base_ind + "            seen.add(nt)\n")
    nb.append(base_ind + "            picked.append(it)\n")

    lines[target_if:j] = nb

    # ---------------------------
    # Optional: add dropped_topicban into stats_detail (so you don't miss it)
    # Find stats_detail dict line and append.
    # ---------------------------
    for i, ln in enumerate(lines):
        if "\"stats_detail\": {\"dropped_blacklist\"" in ln and "dropped_topicban" not in ln:
            # naive but safe-ish one-line dict in your file
            # We'll rewrite that line only.
            # Original: "stats_detail": {"dropped_blacklist": ..., "dropped_whitelist": ..., ...},
            # New add: "dropped_topicban": dropped_topicban,
            lines[i] = ln.replace(
                "\"relax_used\": relax_used}",
                "\"relax_used\": relax_used, \"dropped_topicban\": dropped_topicban}"
            )
            break

    out = "".join(lines)
    write_text(path, out)
    print("OK: patched " + path)


if __name__ == "__main__":
    main()
