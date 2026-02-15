import io
import os
import sys

def _insert_helper(lines):
    # Insert helper before def _news__format_voice_miniflux if not already present
    helper_sig = "def _news__voice_clip_snippet("
    if any(helper_sig in ln for ln in lines):
        return lines, False

    target = "def _news__format_voice_miniflux("
    idx = -1
    for i, ln in enumerate(lines):
        if ln.startswith(target):
            idx = i
            break
    if idx < 0:
        return lines, False

    helper = []
    helper.append("\n")
    helper.append("def _news__voice_clip_snippet(sn: str, prefer: str = \"zh\", max_len: int = 90) -> str:\n")
    helper.append("    \"\"\"Make snippet TTS-friendly.\n")
    helper.append("    - Drop obviously truncated snippets (ending with ... / … / po...)\n")
    helper.append("    - Avoid reading pure English when prefer zh\n")
    helper.append("    - Prefer cutting at sentence punctuation; avoid ellipsis\n")
    helper.append("    \"\"\"\n")
    helper.append("    try:\n")
    helper.append("        s = (sn or \"\").strip()\n")
    helper.append("        if not s:\n")
    helper.append("            return \"\"\n")
    helper.append("        p = (prefer or \"zh\").strip().lower()\n")
    helper.append("        if p not in [\"zh\", \"en\"]:\n")
    helper.append("            p = \"zh\"\n")
    helper.append("\n")
    helper.append("        tail = s[-12:]\n")
    helper.append("        low_tail = tail.lower()\n")
    helper.append("        if (\"...\" in tail) or (\"…\" in tail) or low_tail.endswith(\"po...\"):\n")
    helper.append("            return \"\"\n")
    helper.append("\n")
    helper.append("        # If prefer zh and snippet has no CJK, do not read it (avoid CN TTS spelling English)\n")
    helper.append("        try:\n")
    helper.append("            if (p == \"zh\") and (not _has_cjk(s)):\n")
    helper.append("                return \"\"\n")
    helper.append("        except Exception:\n")
    helper.append("            pass\n")
    helper.append("\n")
    helper.append("        # Normalize whitespace\n")
    helper.append("        s = \" \".join(s.split())\n")
    helper.append("\n")
    helper.append("        try:\n")
    helper.append("            ml = int(max_len)\n")
    helper.append("        except Exception:\n")
    helper.append("            ml = 90\n")
    helper.append("        if ml < 40:\n")
    helper.append("            ml = 40\n")
    helper.append("\n")
    helper.append("        if len(s) <= ml:\n")
    helper.append("            return s\n")
    helper.append("\n")
    helper.append("        cut = s[:ml]\n")
    helper.append("        # Prefer last sentence-ending punctuation within cut\n")
    helper.append("        seps = [\"。\", \"！\", \"？\", \".\", \"!\", \"?\"]\n")
    helper.append("        best = -1\n")
    helper.append("        for ch in seps:\n")
    helper.append("            pos = cut.rfind(ch)\n")
    helper.append("            if pos > best:\n")
    helper.append("                best = pos\n")
    helper.append("        if best >= 20:\n")
    helper.append("            cut = cut[:best+1].strip()\n")
    helper.append("            return cut\n")
    helper.append("\n")
    helper.append("        # Otherwise try comma/semicolon-ish boundary\n")
    helper.append("        seps2 = [\"，\", \",\", \"；\", \";\", \":\", \"：\"]\n")
    helper.append("        best2 = -1\n")
    helper.append("        for ch in seps2:\n")
    helper.append("            pos = cut.rfind(ch)\n")
    helper.append("            if pos > best2:\n")
    helper.append("                best2 = pos\n")
    helper.append("        if best2 >= 25:\n")
    helper.append("            cut = cut[:best2].strip()\n")
    helper.append("        else:\n")
    helper.append("            # English word boundary\n")
    helper.append("            sp = cut.rfind(\" \")\n")
    helper.append("            if sp >= 25:\n")
    helper.append("                cut = cut[:sp].strip()\n")
    helper.append("        if not cut:\n")
    helper.append("            return \"\"\n")
    helper.append("        # End with a full stop for TTS\n")
    helper.append("        if not (cut.endswith(\"。\") or cut.endswith(\"！\") or cut.endswith(\"？\") or cut.endswith(\".\") or cut.endswith(\"!\") or cut.endswith(\"?\")):\n")
    helper.append("            cut = cut + \"。\"\n")
    helper.append("        return cut\n")
    helper.append("    except Exception:\n")
    helper.append("        return \"\"\n")
    helper.append("\n")

    new_lines = lines[:idx] + helper + lines[idx:]
    return new_lines, True

def _patch_snippet_fallback(lines):
    # 1) In _news__format_voice_miniflux: when EN item + prefer zh, if cached snippet is empty, force sn=""
    changed = False
    for i in range(len(lines) - 1):
        if "if hit:" in lines[i] and "t2 =" in lines[i+1]:
            # Look ahead a bit for "if s2:" line
            for j in range(i, min(i + 35, len(lines))):
                if "if s2:" in lines[j]:
                    indent = lines[j].split("if s2:")[0]
                    # Replace 'if s2:' block with explicit empty handling
                    # We assume next line is "sn = s2"
                    k = j
                    # remove the next one line if it is sn = s2
                    next_is_sn = (k + 1 < len(lines)) and ("sn = s2" in lines[k+1])
                    repl = []
                    repl.append(indent + "if s2 is not None:\n")
                    repl.append(indent + "    if s2:\n")
                    repl.append(indent + "        sn = s2\n")
                    repl.append(indent + "    else:\n")
                    repl.append(indent + "        # avoid leaking English snippet into zh TTS when translation is intentionally empty\n")
                    repl.append(indent + "        sn = \"\"\n")
                    # apply replacement
                    lines[k] = repl[0]
                    if next_is_sn:
                        lines[k+1] = repl[1]
                        # insert remaining lines after k+1
                        ins = repl[2:]
                        lines[k+2:k+2] = ins
                    else:
                        # insert after k
                        lines[k+1:k+1] = repl[1:]
                    changed = True
                    break
            if changed:
                break

    # 2) Replace the old "tighten snippet for TTS" (ellipsis cut) with helper call
    for i in range(len(lines)):
        if "# tighten snippet for TTS" in lines[i]:
            # Replace the next few lines that do len(sn)>90 truncation
            # Find next line that starts with "if len(sn) >"
            j = i + 1
            while j < len(lines) and j < i + 8:
                if "if len(sn) >" in lines[j]:
                    # Remove up to 2 lines (if + sn=...)
                    # Insert helper call
                    indent = lines[j].split("if")[0]
                    # Best-effort remove this if-block (2 lines)
                    del lines[j:j+2]
                    lines.insert(j, indent + "sn = _news__voice_clip_snippet(sn, prefer, 90)\n")
                    changed = True
                    break
                j += 1
            break

    return lines, changed

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # Ensure we are in the news voice block: helper relies on _has_cjk existing later, so safe.
    lines, c1 = _insert_helper(lines)
    lines, c2 = _patch_snippet_fallback(lines)

    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print("OK: v1.5 snippet voice smoothing applied. inserted_helper={0} patched_logic={1}".format(c1, c2))

if __name__ == "__main__":
    main()
