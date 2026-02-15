import re
import shutil
from datetime import datetime

APP = "app.py"

def backup_file(p):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = p + ".bak.news_v2_3." + ts
    shutil.copy2(p, bak)
    return bak

def _find_news_digest_defs(lines):
    # return list of dicts: {"def_idx": i, "decor_idx": j_or_None}
    defs = []
    pat_def = re.compile(r'^\s*(async\s+def|def)\s+news_digest\s*\(')
    pat_decor = re.compile(r'^\s*@mcp\.tool\b')
    for i, line in enumerate(lines):
        if pat_def.search(line):
            decor_idx = None
            # look back up to 8 lines for a decorator
            for j in range(max(0, i - 8), i):
                if pat_decor.search(lines[j]):
                    decor_idx = j
            defs.append({"def_idx": i, "decor_idx": decor_idx})
    return defs

def _patch_decorator_name(line, new_name):
    # Ensure @mcp.tool(...) has name="..."
    # Case A: already has name=... -> replace it
    if "name=" in line:
        line2 = re.sub(r'name\s*=\s*"[^"]*"', 'name="{0}"'.format(new_name), line)
        line2 = re.sub(r"name\s*=\s*'[^']*'", "name='{0}'".format(new_name), line2)
        return line2

    # Case B: no args: "@mcp.tool" -> "@mcp.tool(name="x")"
    if line.strip() == "@mcp.tool":
        return "@mcp.tool(name=\"{0}\")".format(new_name)

    # Case C: has (...) but no name=
    m = re.match(r'^(\s*@mcp\.tool)\((.*)\)\s*$', line.strip())
    if m:
        prefix = m.group(1)
        inner = m.group(2).strip()
        if inner == "":
            inner2 = 'name="{0}"'.format(new_name)
        else:
            inner2 = 'name="{0}", {1}'.format(new_name, inner)
        # preserve original leading spaces from original line
        lead = re.match(r'^(\s*)', line).group(1)
        return lead + prefix + "(" + inner2 + ")"
    # If format unknown, leave untouched
    return line

def _patch_def_signature(lines, def_idx):
    # Patch the *last* effective news_digest signature to accept prefer_lang/user_text/**kwargs
    # We edit from the "def news_digest(" line until the line that contains "):" (or ") -> ...:")
    start = def_idx
    end = def_idx
    while end < len(lines):
        if re.search(r'\)\s*(?:->\s*[^:]+)?\s*:\s*$', lines[end]):
            break
        end += 1
    if end >= len(lines):
        return False, "could not find end of function signature"

    sig_block = "".join(lines[start:end+1])

    # If already compatible, do nothing
    if ("prefer_lang" in sig_block) and ("user_text" in sig_block):
        # Still ensure **kwargs exists (optional)
        if "**kwargs" in sig_block:
            return False, "signature already compatible"
        # Add **kwargs if missing
        return _append_kwargs(lines, start, end), "added **kwargs only"

    changed = False

    # Determine indentation
    indent = re.match(r'^(\s*)', lines[start]).group(1)
    add_indent = indent + "    "

    # Single-line signature?
    if start == end:
        line = lines[start]
        # extract params inside (...)
        m = re.search(r'news_digest\s*\((.*)\)\s*(?:->\s*[^:]+)?\s*:\s*$', line)
        if not m:
            return False, "cannot parse one-line signature"
        params = m.group(1).strip()
        extra_parts = []
        if "prefer_lang" not in params:
            extra_parts.append('prefer_lang: str = "zh"')
        if "user_text" not in params:
            extra_parts.append('user_text: str = ""')
        extra_parts.append("**kwargs")

        if params == "":
            new_params = ", ".join(extra_parts)
        else:
            new_params = params + ", " + ", ".join(extra_parts)

        line2 = re.sub(r'news_digest\s*\(.*\)\s*(?:->\s*[^:]+)?\s*:\s*$',
                       'news_digest({0}):'.format(new_params),
                       line)
        lines[start] = line2
        changed = True
        return changed, "patched one-line signature"

    # Multi-line: insert new params before the closing line containing ")"
    insert_at = end
    # Find the line that actually contains the ")"
    # We will insert right before that line.
    # Also avoid trailing commas issues by inserting as new separate params lines with commas.
    extra_lines = []
    extra_lines.append(add_indent + 'prefer_lang: str = "zh",\n')
    extra_lines.append(add_indent + 'user_text: str = "",\n')
    extra_lines.append(add_indent + "**kwargs,\n")

    # If prefer_lang/user_text already present in block, avoid duplicates
    block = "".join(lines[start:end+1])
    if "prefer_lang" in block:
        extra_lines = [x for x in extra_lines if "prefer_lang" not in x]
    if "user_text" in block:
        extra_lines = [x for x in extra_lines if "user_text" not in x]
    if "**kwargs" in block:
        extra_lines = [x for x in extra_lines if "**kwargs" not in x]

    if not extra_lines:
        return False, "signature already compatible"

    lines[insert_at:insert_at] = extra_lines
    changed = True
    return changed, "patched multi-line signature"

def _append_kwargs(lines, start, end):
    indent = re.match(r'^(\s*)', lines[start]).group(1)
    add_indent = indent + "    "
    # insert before end line
    lines[end:end] = [add_indent + "**kwargs,\n"]
    return True

def main():
    with open(APP, "r", encoding="utf-8") as f:
        lines = f.readlines()

    bak = backup_file(APP)

    defs = _find_news_digest_defs(lines)
    if not defs:
        print("ERROR: no def news_digest(...) found")
        print("Backup:", bak)
        return

    # 1) Fix duplicate tool registrations: rename decorators for all but the last def
    if len(defs) > 1:
        for k, d in enumerate(defs[:-1], start=1):
            di = d.get("decor_idx")
            if di is not None:
                new_name = "news_digest_legacy_{0}".format(k)
                lines[di] = _patch_decorator_name(lines[di], new_name) + ("" if lines[di].endswith("\n") else "\n")

    # 2) Patch the *last* definition signature (the effective one)
    last_def_idx = defs[-1]["def_idx"]
    changed_sig, msg_sig = _patch_def_signature(lines, last_def_idx)

    with open(APP, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print("OK: defs_found={0}".format(len(defs)))
    print("Signature:", msg_sig)
    print("Backup:", bak)

if __name__ == "__main__":
    main()
