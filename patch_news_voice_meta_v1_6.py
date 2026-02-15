import io
import os
import sys

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # locate function
    fn_start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__format_voice_miniflux("):
            fn_start = i
            break
    if fn_start < 0:
        print("ERROR: cannot find def _news__format_voice_miniflux(")
        sys.exit(1)

    # find the block that appends meta into title: line = line + "（" + " | ".join(meta) + "）"
    meta_line_i = -1
    for i in range(fn_start, min(fn_start + 320, len(lines))):
        if '" | ".join(meta)' in lines[i] and ("line = line + " in lines[i]):
            meta_line_i = i
            break
    if meta_line_i < 0:
        print("ERROR: cannot find old meta join line in _news__format_voice_miniflux")
        sys.exit(1)

    # We will remove the whole meta-building block:
    # meta = []
    # if src: ...
    # if pa: ...
    # if meta: line = line + ...
    #
    # Then we will inject new logic after out.append(line) to put meta in the second line.
    #
    # Find meta block start (line containing 'meta = []')
    meta_block_start = -1
    for i in range(meta_line_i, max(fn_start, meta_line_i - 20), -1):
        if "meta = []" in lines[i]:
            meta_block_start = i
            break
    if meta_block_start < 0:
        print("ERROR: cannot find meta = [] block start")
        sys.exit(1)

    # Find meta block end: the meta join line is inside, end at that line
    meta_block_end = meta_line_i

    # Remove meta block
    del lines[meta_block_start:meta_block_end + 1]

    # Now inject new meta-to-snippet logic after out.append(line)
    # Find out.append(line) after the title line is constructed
    out_append_i = -1
    for i in range(fn_start, min(fn_start + 340, len(lines))):
        if "out.append(line)" in lines[i]:
            out_append_i = i
            break
    if out_append_i < 0:
        print("ERROR: cannot find out.append(line) in _news__format_voice_miniflux")
        sys.exit(1)

    indent = lines[out_append_i].split("out.append(line)")[0]

    inject = []
    inject.append(indent + "# Put source/time on the next line for smoother TTS (avoid in-title parentheses)\n")
    inject.append(indent + "meta_text = \"\"\n")
    inject.append(indent + "if src or pa:\n")
    inject.append(indent + "    if prefer == \"zh\":\n")
    inject.append(indent + "        if src and pa:\n")
    inject.append(indent + "            meta_text = \"来自{0}（{1}）。\".format(src, pa)\n")
    inject.append(indent + "        elif src:\n")
    inject.append(indent + "            meta_text = \"来自{0}。\".format(src)\n")
    inject.append(indent + "        elif pa:\n")
    inject.append(indent + "            meta_text = \"{0}。\".format(pa)\n")
    inject.append(indent + "    else:\n")
    inject.append(indent + "        if src and pa:\n")
    inject.append(indent + "            meta_text = \"From {0} ({1}). \".format(src, pa)\n")
    inject.append(indent + "        elif src:\n")
    inject.append(indent + "            meta_text = \"From {0}. \".format(src)\n")
    inject.append(indent + "        elif pa:\n")
    inject.append(indent + "            meta_text = \"{0}. \".format(pa)\n")
    inject.append("\n")

    # Insert right after out.append(line)
    lines[out_append_i + 1:out_append_i + 1] = inject

    # Now adjust the snippet output block:
    # currently it does:
    # if sn:
    #    out.append("   " + sn)
    #
    # We change it to:
    # if meta_text and sn: out.append("   " + meta_text + sn)
    # elif meta_text: out.append("   " + meta_text)
    # elif sn: out.append("   " + sn)
    #
    # Find the first 'if sn:' after injection
    if_sn_i = -1
    for i in range(out_append_i, min(fn_start + 380, len(lines))):
        if lines[i].lstrip().startswith("if sn:"):
            if_sn_i = i
            break
    if if_sn_i < 0:
        print("ERROR: cannot find if sn: block to patch")
        sys.exit(1)

    # Expect the next line to be out.append("   " + sn)
    # Replace this if-block with the new 3-branch logic (keep indentation)
    if_indent = lines[if_sn_i].split("if sn:")[0]

    # Remove old 2 lines: if sn: + out.append
    del lines[if_sn_i:if_sn_i + 2]

    repl = []
    repl.append(if_indent + "if meta_text and sn:\n")
    repl.append(if_indent + "    out.append(\"   \" + meta_text + sn)\n")
    repl.append(if_indent + "elif meta_text:\n")
    repl.append(if_indent + "    out.append(\"   \" + meta_text.strip())\n")
    repl.append(if_indent + "elif sn:\n")
    repl.append(if_indent + "    out.append(\"   \" + sn)\n")
    lines[if_sn_i:if_sn_i] = repl

    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print("OK: v1.6 moved source/time out of title line; meta rendered as natural sentence on next line")

if __name__ == "__main__":
    main()
