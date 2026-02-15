import time

PATH = "./app.py"

OLD = r"x = re.sub(r'^\s*\d+\s*(?:秒|分钟|小?时|天|周|月|年)前\s*[·\-–—|]\s*', '', x)"
NEW = r"x = re.sub(r'^\s*\d+\s*(?:秒|分钟|小?时|天|周|月|年)\s*(?:之前|以前|前)\s*[·\-–—|]\s*', '', x)"

def read_text(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read()

def write_text(p, t):
    with open(p, "w", encoding="utf-8") as f:
        f.write(t)

def main():
    src = read_text(PATH)

    if "def _mcp__strip_snippet_meta" not in src:
        raise SystemExit("not_found: _mcp__strip_snippet_meta")

    if OLD not in src:
        # 兜底：如果代码行格式略有差异，就提示手工 grep 定位
        raise SystemExit("not_found: expected OLD regex line (please grep in app.py)")

    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = PATH + ".bak.p1script." + ts
    write_text(bak, src)

    out = src.replace(OLD, NEW, 1)
    write_text(PATH, out)

    print("patched_path=" + PATH)
    print("backup_path=" + bak)

if __name__ == "__main__":
    main()
