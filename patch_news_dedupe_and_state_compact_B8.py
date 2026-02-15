#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import shutil
import time


def _read_text(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()


def _write_text(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.before_B8_" + ts
    shutil.copy2(p, bak)
    return bak


def _find_def_block(src, def_name):
    # Match: def name(...): OR def name(...)->...:
    m = re.search(r"^def\s+" + re.escape(def_name) + r"\s*\(.*?\)\s*(?:->\s*[^:]+)?\s*:\s*$",
                  src, flags=re.MULTILINE)
    if not m:
        return None
    start = m.start()
    # Find next top-level def/class/decorator at col 0
    tail = src[m.end():]
    m2 = re.search(r"^\s*(?:@|def|class)\s+", tail, flags=re.MULTILINE)
    if not m2:
        end = len(src)
    else:
        end = m.end() + m2.start()
    return (start, end)


def _patch_route_request_structured_state(src):
    blk = _find_def_block(src, "route_request")
    if not blk:
        raise RuntimeError("Cannot find route_request()")
    start, end = blk
    block = src[start:end]
    lines = block.splitlines(True)

    # Locate the entity_id branch
    idx_if = None
    for i, ln in enumerate(lines):
        if re.search(r"^\s*if\s+_looks_like_entity_id\(\s*user_text\s*\)\s*:\s*$", ln):
            idx_if = i
            break
    if idx_if is None:
        raise RuntimeError("Cannot find _looks_like_entity_id(user_text) branch in route_request()")

    # Determine indentation of that if-line
    if_line = lines[idx_if]
    if_indent = len(if_line) - len(if_line.lstrip(" "))
    indent_if = " " * if_indent
    indent_in = " " * (if_indent + 4)

    # We will rewrite the two returns inside that branch:
    # 1) failure return with "route_type": "structured_state"
    # 2) success return with "route_type": "structured_state"
    #
    # We do a small local edit only around those return lines.

    def _is_structured_state_return(ln):
        return ("return" in ln) and ('"route_type": "structured_state"' in ln or "'route_type': 'structured_state'" in ln)

    # Find failure return line (after "if not r.get('ok'):")
    idx_fail_return = None
    idx_ok_return = None
    for i in range(idx_if, min(len(lines), idx_if + 80)):
        if _is_structured_state_return(lines[i]):
            if idx_fail_return is None:
                idx_fail_return = i
            else:
                idx_ok_return = i
                break

    if idx_fail_return is None or idx_ok_return is None:
        # Maybe formatted across multiple lines. Try broader search inside branch.
        # We'll search for the two specific original patterns in the whole block text.
        pass

    # We will rebuild by replacing the single-line returns with guarded returns.
    # Insert a local flag right after "r = ha_get_state(user_text)" line if not already.
    # Find that line:
    idx_r = None
    for i in range(idx_if, min(len(lines), idx_if + 60)):
        if re.search(r"^\s*r\s*=\s*ha_get_state\(\s*user_text\s*\)\s*$", lines[i]):
            idx_r = i
            break
    if idx_r is None:
        raise RuntimeError("Cannot find 'r = ha_get_state(user_text)' in structured_state branch")

    # Check if we already have a local return-data flag in this branch
    has_flag = False
    for i in range(idx_r, min(len(lines), idx_r + 8)):
        if "ROUTE_RETURN_DATA" in lines[i]:
            has_flag = True
            break

    inject_flag_lines = []
    if not has_flag:
        inject_flag_lines.append(indent_in + "rd = str(os.environ.get(\"ROUTE_RETURN_DATA\") or \"0\").strip().lower() in (\"1\",\"true\",\"yes\",\"on\")\n")

    # Now rewrite returns.
    # Locate "if not r.get('ok'):" line
    idx_if_not_ok = None
    for i in range(idx_r, min(len(lines), idx_r + 25)):
        if re.search(r"^\s*if\s+not\s+r\.get\(\s*[\"']ok[\"']\s*\)\s*:\s*$", lines[i]):
            idx_if_not_ok = i
            break
    if idx_if_not_ok is None:
        raise RuntimeError("Cannot find 'if not r.get(\"ok\"):' in structured_state branch")

    # Locate the immediate return line under that if
    idx_fail_return = None
    for i in range(idx_if_not_ok + 1, min(len(lines), idx_if_not_ok + 8)):
        if re.search(r"^\s*return\s+\{", lines[i]):
            idx_fail_return = i
            break
    if idx_fail_return is None:
        raise RuntimeError("Cannot find failure return dict under 'if not r.get(\"ok\")'")

    # Locate success return (the one after st=..., return {...})
    idx_ok_return = None
    for i in range(idx_fail_return + 1, min(len(lines), idx_fail_return + 40)):
        if re.search(r"^\s*return\s+\{", lines[i]) and ("structured_state" in lines[i]):
            idx_ok_return = i
            break
    # If success return is not single-line, search any line that contains structured_state and return
    if idx_ok_return is None:
        for i in range(idx_fail_return + 1, min(len(lines), idx_fail_return + 60)):
            if ("structured_state" in lines[i]) and ("return" in lines[i]):
                idx_ok_return = i
                break
    if idx_ok_return is None:
        raise RuntimeError("Cannot find success return for structured_state")

    # Replace failure return line with guarded
    new_fail = []
    new_fail.append(indent_in + "if rd:\n")
    new_fail.append(indent_in + "    return {\"ok\": True, \"route_type\": \"structured_state\", \"final\": \"我现在联网查询失败了，请稍后再试。\", \"data\": r}\n")
    new_fail.append(indent_in + "return {\"ok\": True, \"route_type\": \"structured_state\", \"final\": \"我现在联网查询失败了，请稍后再试。\"}\n")

    # Replace success return line with guarded
    # Need to keep st calculation as-is; we only change return.
    new_ok = []
    new_ok.append(indent_in + "if rd:\n")
    new_ok.append(indent_in + "    return {\"ok\": True, \"route_type\": \"structured_state\", \"final\": \"实体 \" + user_text + \" 状态: \" + st + \"。\", \"data\": r, \"entity_id\": user_text}\n")
    new_ok.append(indent_in + "return {\"ok\": True, \"route_type\": \"structured_state\", \"final\": \"实体 \" + user_text + \" 状态: \" + st + \"。\"}\n")

    # Apply edits: inject flag after idx_r line, and replace returns.
    out = []
    for i, ln in enumerate(lines):
        out.append(ln)
        if (i == idx_r) and inject_flag_lines:
            out.extend(inject_flag_lines)

    # Now replace the old return lines by reconstructing with indices.
    # We will do it with a second pass over 'out' to avoid index drift.
    out2 = []
    # Need to map original indices to new indices; simplest: operate on the original 'lines' indices
    # by building a boolean replace table then re-emit from original 'out' is complicated.
    # We'll instead re-apply replacement on the original 'lines' (not 'out') and then re-add injected flag.
    #
    # So rebuild from original 'lines' with replacements, then inject flag.

    rebuilt = []
    for i, ln in enumerate(lines):
        if i == idx_fail_return:
            rebuilt.extend(new_fail)
            continue
        if i == idx_ok_return:
            rebuilt.extend(new_ok)
            continue
        rebuilt.append(ln)

    # Inject flag in rebuilt (same insertion point)
    if inject_flag_lines:
        rebuilt2 = []
        for i, ln in enumerate(rebuilt):
            rebuilt2.append(ln)
            # Find the same "r = ha_get_state(user_text)" line again in rebuilt
            if re.search(r"^\s*r\s*=\s*ha_get_state\(\s*user_text\s*\)\s*$", ln):
                rebuilt2.extend(inject_flag_lines)
        rebuilt = rebuilt2

    new_block = "".join(rebuilt)
    return src[:start] + new_block + src[end:]


def _ensure_news_dedupe_helper(src):
    # Insert helper near existing title cleaner
    if "def _news__dedupe_for_voice(" in src:
        return src  # already present

    # Anchor: after _news__strip_title_tail or after _clean_title
    m = re.search(r"^def\s+_news__strip_title_tail\([^)]*\)\s*(?:->\s*[^:]+)?\s*:\s*$",
                  src, flags=re.MULTILINE)
    if not m:
        m = re.search(r"^def\s+_clean_title\([^)]*\)\s*(?:->\s*[^:]+)?\s*:\s*$",
                      src, flags=re.MULTILINE)
    if not m:
        raise RuntimeError("Cannot find anchor function (_news__strip_title_tail or _clean_title) to insert dedupe helper")

    # Find end of that function by scanning forward until next top-level def at col 0
    tail = src[m.end():]
    m2 = re.search(r"^\s*def\s+", tail, flags=re.MULTILINE)
    if not m2:
        insert_pos = len(src)
    else:
        insert_pos = m.end() + m2.start()

    helper = []
    helper.append("\n")
    helper.append("def _news__norm_title_for_dedupe(s: str) -> str:\n")
    helper.append("    try:\n")
    helper.append("        s = (s or \"\").strip().lower()\n")
    helper.append("        if not s:\n")
    helper.append("            return \"\"\n")
    helper.append("        # remove common punctuation/spaces\n")
    helper.append("        s = re.sub(r\"[\\s\\t\\r\\n]+\", \"\", s)\n")
    helper.append("        s = re.sub(r\"[\\\"\\'`“”‘’（）()【】\\[\\]{}<>《》·,，。.!！?？:：;；/\\\\|]+\", \"\", s)\n")
    helper.append("        # strip tail words like video\n")
    helper.append("        s = re.sub(r\"(video)$\", \"\", s)\n")
    helper.append("        return s\n")
    helper.append("    except Exception:\n")
    helper.append("        return \"\"\n")
    helper.append("\n")
    helper.append("def _news__is_video_item(it: dict) -> bool:\n")
    helper.append("    try:\n")
    helper.append("        t = str(it.get(\"title\") or \"\").lower()\n")
    helper.append("        tv = str(it.get(\"title_voice\") or \"\").lower()\n")
    helper.append("        u = str(it.get(\"url\") or \"\").lower()\n")
    helper.append("        if (\"/video/\" in u) or (\"video\" in u):\n")
    helper.append("            return True\n")
    helper.append("        if (\"– video\" in t) or (\"- video\" in t) or (\"—video\" in t):\n")
    helper.append("            return True\n")
    helper.append("        if (\"视频\" in tv) or (\"视频\" in t):\n")
    helper.append("            return True\n")
    helper.append("        return False\n")
    helper.append("    except Exception:\n")
    helper.append("        return False\n")
    helper.append("\n")
    helper.append("def _news__dedupe_for_voice(items: list, limit: int) -> list:\n")
    helper.append("    \"\"\"Dedupe near-duplicate topics (often: same story as video + article).\"\"\"\n")
    helper.append("    if not isinstance(items, list):\n")
    helper.append("        return []\n")
    helper.append("    try:\n")
    helper.append("        lim = int(limit or 0)\n")
    helper.append("    except Exception:\n")
    helper.append("        lim = 0\n")
    helper.append("    if lim <= 0:\n")
    helper.append("        lim = 5\n")
    helper.append("    picked = []\n")
    helper.append("    picked_norm = []\n")
    helper.append("    for it in items:\n")
    helper.append("        try:\n")
    helper.append("            tv = str(it.get(\"title_voice\") or it.get(\"title\") or \"\").strip()\n")
    helper.append("        except Exception:\n")
    helper.append("            tv = \"\"\n")
    helper.append("        n = _news__norm_title_for_dedupe(tv)\n")
    helper.append("        if not n:\n")
    helper.append("            continue\n")
    helper.append("        dup_i = -1\n")
    helper.append("        for j, pn in enumerate(picked_norm):\n")
    helper.append("            if (n == pn) or (n in pn) or (pn in n):\n")
    helper.append("                dup_i = j\n")
    helper.append("                break\n")
    helper.append("        if dup_i < 0:\n")
    helper.append("            picked.append(it)\n")
    helper.append("            picked_norm.append(n)\n")
    helper.append("            continue\n")
    helper.append("        # duplicate found: prefer non-video; otherwise keep the longer/more specific title\n")
    helper.append("        cur_is_video = _news__is_video_item(it)\n")
    helper.append("        old_is_video = _news__is_video_item(picked[dup_i])\n")
    helper.append("        if old_is_video and (not cur_is_video):\n")
    helper.append("            picked[dup_i] = it\n")
    helper.append("            picked_norm[dup_i] = n\n")
    helper.append("            continue\n")
    helper.append("        if (not old_is_video) and cur_is_video:\n")
    helper.append("            continue\n")
    helper.append("        if len(n) > (len(picked_norm[dup_i]) + 4):\n")
    helper.append("            picked[dup_i] = it\n")
    helper.append("            picked_norm[dup_i] = n\n")
    helper.append("            continue\n")
    helper.append("    return picked[:lim]\n")
    helper.append("\n")

    return src[:insert_pos] + "".join(helper) + src[insert_pos:]


def _patch_news_digest_dedupe(src):
    blk = _find_def_block(src, "news_digest")
    if not blk:
        raise RuntimeError("Cannot find news_digest()")
    start, end = blk
    block = src[start:end]
    lines = block.splitlines(True)

    # 1) expand candidate list: replace out_items = picked[:lim_int]
    idx_out = None
    for i, ln in enumerate(lines):
        if "out_items = picked[:lim_int]" in ln.replace(" ", ""):
            idx_out = i
            break
    # More flexible match
    if idx_out is None:
        for i, ln in enumerate(lines):
            if re.search(r"^\s*out_items\s*=\s*picked\[\s*:\s*lim_int\s*\]\s*$", ln):
                idx_out = i
                break
    if idx_out is None:
        raise RuntimeError("Cannot find 'out_items = picked[:lim_int]' in news_digest()")

    indent = re.match(r"^(\s*)", lines[idx_out]).group(1)

    repl = []
    repl.append(indent + "# expand candidates a bit for dedupe (avoid same-topic video+article both being selected)\n")
    repl.append(indent + "try:\n")
    repl.append(indent + "    max_cand = int(os.environ.get(\"NEWS_DEDUPE_CAND_MAX\") or \"12\")\n")
    repl.append(indent + "except Exception:\n")
    repl.append(indent + "    max_cand = 12\n")
    repl.append(indent + "cand_n = lim_int * 2\n")
    repl.append(indent + "if cand_n < lim_int:\n")
    repl.append(indent + "    cand_n = lim_int\n")
    repl.append(indent + "if cand_n > max_cand:\n")
    repl.append(indent + "    cand_n = max_cand\n")
    repl.append(indent + "if cand_n > len(picked):\n")
    repl.append(indent + "    cand_n = len(picked)\n")
    repl.append(indent + "out_items = picked[:cand_n]\n")

    lines[idx_out:idx_out+1] = repl

    # 2) insert dedupe call before building lines = []
    idx_lines = None
    for i, ln in enumerate(lines):
        if re.search(r"^\s*lines\s*=\s*\[\]\s*$", ln):
            idx_lines = i
            break
    if idx_lines is None:
        raise RuntimeError("Cannot find 'lines = []' in news_digest()")

    ded = []
    ded.append("\n")
    ded.append(indent + "# dedupe similar topics (often: same story as video + article)\n")
    ded.append(indent + "try:\n")
    ded.append(indent + "    out_items = _news__dedupe_for_voice(out_items, lim_int)\n")
    ded.append(indent + "except Exception:\n")
    ded.append(indent + "    pass\n")
    ded.append("\n")

    lines[idx_lines:idx_lines] = ded

    new_block = "".join(lines)
    return src[:start] + new_block + src[end:]


def main():
    p = "app.py"
    if not os.path.exists(p):
        raise RuntimeError("app.py not found in current directory")

    src = _read_text(p)

    # ensure we have re imported (dedupe helper uses re)
    if "import re" not in src:
        # should not happen in your project, but be safe
        src = "import re\n" + src

    bak = _backup(p)

    src = _patch_route_request_structured_state(src)
    src = _ensure_news_dedupe_helper(src)
    src = _patch_news_digest_dedupe(src)

    _write_text(p, src)
    print("OK: B8 patched (state compact + news dedupe). backup:", bak)


if __name__ == "__main__":
    main()

