import re

def is_blank_or_comment(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s.startswith("#"):
        return True
    return False

def main():
    path = "app.py"
    lines = open(path, "r", encoding="utf-8").read().splitlines(True)  # keep \n
    out = []
    i = 0
    fixed = 0

    # backup
    open("app.py.bak.fix_restart_indent_v2", "w", encoding="utf-8").write("".join(lines))

    try_re = re.compile(r'^([ \t]*)try:\s*(#.*)?\n?$')
    except_re = re.compile(r'^([ \t]*)except\b')
    finally_re = re.compile(r'^([ \t]*)finally:\s*(#.*)?\n?$')

    while i < len(lines):
        line = lines[i]
        m = try_re.match(line)
        if not m:
            out.append(line)
            i += 1
            continue

        indent = m.group(1) or ""
        out.append(line)

        # look ahead to next non-empty/non-comment line
        j = i + 1
        while j < len(lines) and is_blank_or_comment(lines[j]):
            out.append(lines[j])
            j += 1

        if j < len(lines):
            nxt = lines[j]
            m_ex = except_re.match(nxt)
            m_fi = finally_re.match(nxt)
            if (m_ex and (m_ex.group(1) == indent)) or (m_fi and (m_fi.group(1) == indent)):
                # empty try block -> insert pass
                out.append(indent + "    pass\n")
                fixed += 1

        i = j  # continue from the next meaningful line (already copied blanks)

    open(path, "w", encoding="utf-8").write("".join(out))
    print("patched_ok=1")
    print("empty_try_fixed_count=" + str(fixed))
    print("backup=app.py.bak.fix_restart_indent_v2")

if __name__ == "__main__":
    main()
