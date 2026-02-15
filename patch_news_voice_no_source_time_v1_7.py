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

    # Locate _news__format_voice_miniflux
    fn_start = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__format_voice_miniflux("):
            fn_start = i
            break
    if fn_start < 0:
        print("ERROR: cannot find def _news__format_voice_miniflux(")
        sys.exit(1)

    # 1) Remove v1.6 injected meta_text block (marker comment)
    marker = "# Put source/time on the next line for smoother TTS (avoid in-title parentheses)"
    m_i = -1
    for i in range(fn_start, min(fn_start + 420, len(lines))):
        if marker in lines[i]:
            m_i = i
            break

    removed_meta = False
    if m_i >= 0:
        # Remove until the first blank line after the block
        end = -1
        for j in range(m_i, min(m_i + 80, len(lines))):
            if lines[j].strip() == "":
                end = j
                break
        if end < 0:
            print("ERROR: cannot find end of meta_text block")
            sys.exit(1)
        del lines[m_i:end + 1]
        removed_meta = True

    # 2) Replace snippet append logic to remove any meta_text references
    # Find the v1.6 snippet block starting with "if meta_text and sn:"
    if_i = -1
    for i in range(fn_start, min(fn_start + 460, len(lines))):
        if lines[i].lstrip().startswith("if meta_text and sn:"):
            if_i = i
            break

    replaced_snip = False
    if if_i >= 0:
        indent = lines[if_i].split("if")[0]
        # Remove 6 lines:
        # if meta_text and sn:
        #     out.append(...)
        # elif meta_text:
        #     out.append(...)
        # elif sn:
        #     out.append(...)
        del lines[if_i:if_i + 6]
        repl = []
        repl.append(indent + "if sn:\n")
        repl.append(indent + "    out.append(\"   \" + sn)\n")
        lines[if_i:if_i] = repl
        replaced_snip = True

    # 3) Safety: ensure title line doesn't include any leftover meta parentheses join
    # (Earlier v1.6 removed meta join. Nothing else needed.)

    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print("OK: v1.7 removed source/time from final_voice. removed_meta_block={0} replaced_snippet_block={1}".format(removed_meta, replaced_snip))

if __name__ == "__main__":
    main()
