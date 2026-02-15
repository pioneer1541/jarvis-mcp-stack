import re
import time

ADD = [
    "lawn", "ugliest lawn", "ugliest", "garden", "yard", "groundskeeper",
    "草坪", "花园", "最丑草坪"
]

def backup_path():
    ts = time.strftime("%Y%m%d_%H%M%S")
    return "app.py.bak.news_p2_mellife_blacklist_v1_" + ts

def main():
    path = "app.py"
    with open(path, "r", encoding="utf-8") as f:
        src = f.read()

    # 目标：在 news_digest 内的 FILTERS dict 里，定位 mel_life 的 blacklist 列表并追加关键词
    # 用 flags 参数，不使用 (?m)(?s)
    pat = r'("mel_life"\s*:\s*\{\s*"whitelist"\s*:\s*\[[^\]]*\]\s*,\s*"blacklist"\s*:\s*\[)([^\]]*)(\])'
    m = re.search(pat, src, flags=re.MULTILINE | re.DOTALL)
    if not m:
        raise SystemExit("FAILED: cannot locate mel_life blacklist block in FILTERS")

    head = m.group(1)
    body = m.group(2)
    tail = m.group(3)

    # 提取现有 blacklist 项
    existing = re.findall(r'"([^"]+)"', body)
    existing_set = set(existing)

    to_add = []
    for x in ADD:
        if x not in existing_set:
            to_add.append(x)

    if not to_add:
        print("NOOP: mel_life blacklist already contains all keywords.")
        return

    # 保持原来的一行风格：在 body 末尾追加 , "xxx"
    body2 = body
    body2_stripped = body2.strip()
    if body2_stripped == "":
        # 空列表
        body2 = ' "' + '", "'.join(to_add) + '"'
    else:
        # 非空列表：保证末尾有逗号分隔
        if body2.rstrip().endswith(","):
            body2 = body2 + ' "' + '", "'.join(to_add) + '"'
        else:
            body2 = body2 + ', "' + '", "'.join(to_add) + '"'

    new_block = head + body2 + tail
    out = src[:m.start()] + new_block + src[m.end():]

    bak = backup_path()
    with open(bak, "w", encoding="utf-8") as f:
        f.write(src)
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)

    print("OK: patched mel_life blacklist (P2).")
    print("Backup:", bak)
    print("Added:", to_add)

if __name__ == "__main__":
    main()
