import re
import time

ADD = [
    "lawn", "ugliest lawn", "ugliest", "garden", "yard", "groundskeeper",
    "草坪", "花园", "最丑草坪"
]

def backup_name():
    ts = time.strftime("%Y%m%d_%H%M%S")
    return "app.py.bak.news_p2_mellife_blacklist_v2_" + ts

def find_list_span(s, lb_idx):
    # lb_idx points to '['
    i = lb_idx
    depth = 0
    in_str = None
    esc = False
    while i < len(s):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == in_str:
                in_str = None
        else:
            if ch == '"' or ch == "'":
                in_str = ch
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return (lb_idx, i)
        i += 1
    return None

def main():
    path = "app.py"
    src = open(path, "r", encoding="utf-8").read()

    # 1) 找 FILTERS 块起点（限定范围，避免误改别处）
    m0 = re.search(r'\bFILTERS\s*=\s*\{', src, flags=re.MULTILINE)
    if not m0:
        raise SystemExit("FAILED: FILTERS = { not found")

    # 2) 从 FILTERS 起点往后找 mel_life 子块
    tail = src[m0.start():]
    m1 = re.search(r'["\']mel_life["\']\s*:\s*\{', tail, flags=re.MULTILINE)
    if not m1:
        raise SystemExit("FAILED: mel_life block not found after FILTERS")

    # 3) 从 mel_life 起点往后找 blacklist: [ ... ]
    sub = tail[m1.start():]
    m2 = re.search(r'["\']blacklist["\']\s*:\s*\[', sub, flags=re.MULTILINE)
    if not m2:
        raise SystemExit("FAILED: blacklist list not found in mel_life block")

    lb_global = (m0.start() + m1.start() + m2.start()) + m2.group(0).rfind("[")
    span = find_list_span(src, lb_global)
    if not span:
        raise SystemExit("FAILED: cannot find closing ']' for mel_life blacklist list")

    lb, rb = span
    body = src[lb+1:rb]

    # 4) 解析现有项（支持单双引号）
    existing = re.findall(r'["\']([^"\']+)["\']', body)
    ex_set = set(existing)

    to_add = []
    for x in ADD:
        if x not in ex_set:
            to_add.append(x)

    if not to_add:
        print("NOOP: mel_life blacklist already contains all keywords.")
        return

    # 5) 保持原格式：在列表末尾追加 , "xxx"
    body_stripped = body.strip()
    if body_stripped == "":
        body2 = ' "' + '", "'.join(to_add) + '" '
    else:
        # 确保末尾有逗号分隔
        if body.rstrip().endswith(","):
            body2 = body + ' "' + '", "'.join(to_add) + '"'
        else:
            body2 = body + ', "' + '", "'.join(to_add) + '"'

    out = src[:lb+1] + body2 + src[rb:]

    bak = backup_name()
    open(bak, "w", encoding="utf-8").write(src)
    open(path, "w", encoding="utf-8").write(out)

    print("OK: patched mel_life blacklist (P2 v2).")
    print("Backup:", bak)
    print("Added:", to_add)

if __name__ == "__main__":
    main()
