import re

def is_blank_or_comment_stripped(s: str) -> bool:
    t = s.strip()
    if not t:
        return True
    if t.startswith("#"):
        return True
    return False

def main():
    path = "app.py"
    raw = open(path, "r", encoding="utf-8").read().splitlines(True)  # keep line endings

    # backup
    open("app.py.bak.fix_restart_indent_v3", "w", encoding="utf-8").write("".join(raw))

    try_re = re.compile(r'^([ \t]*)try:\s*(#.*)?$')
    except_re = re.compile(r'^([ \t]*)except\b')
    finally_re = re.compile(r'^([ \t]*)finally:\s*(#.*)?$')

    out = []
    i = 0
    fixed = 0

    while i < len(raw):
        line = raw[i]
        s = line.rstrip("\r\n")
        m = try_re.match(s)
        if not m:
            out.append(line)
            i += 1
            continue

        indent = m.group(1) or ""
        out.append(line)

        # look ahead to next non-empty/non-comment line
        j = i + 1
        while j < len(raw):
            sj = raw[j].rstrip("\r\n")
            if is_blank_or_comment_stripped(sj):
                out.append(raw[j])
                j += 1
                continue
            break

        if j < len(raw):
            nxt = raw[j].rstrip("\r\n")
            m_ex = except_re.match(nxt)
            m_fi = finally_re.match(nxt)
            if (m_ex and (m_ex.group(1) == indent)) or (m_fi and (m_fi.group(1) == indent)):
                # empty try block -> insert pass line (keep \n)
                out.append(indent + "    pass\n")
                fixed += 1

        i = j

    open(path, "w", encoding="utf-8").write("".join(out))
    print("patched_ok=1")
    print("empty_try_fixed_count=" + str(fixed))
    print("backup=app.py.bak.fix_restart_indent_v3")

if __name__ == "__main__":
    main()
