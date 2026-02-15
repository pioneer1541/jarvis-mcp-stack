import time

APP = "app.py"

def main():
    src = open(APP, "r", encoding="utf-8").read().splitlines()

    i0 = None
    for i, line in enumerate(src):
        if '"au_politics": ["au_politics（澳洲政治）"' in line:
            i0 = i
            break
    if i0 is None:
        raise SystemExit("cannot find aliases_map au_politics line")

    # 备份
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.fix_alias_au_politics_v1_" + ts
    open(bak, "w", encoding="utf-8").write("\n".join(src) + "\n")

    # 修正为一行（不要拆行，避免引号问题）
    fixed = '        "au_politics": ["au_politics（澳洲政治）", "澳洲政治", "澳大利亚政治", "Australia politics", "australian politics", "AU politics", "Australian politics"],'
    src[i0] = fixed

    # 如果下一行是那条坏掉的续行（以 australian politics 开头），就删除
    if i0 + 1 < len(src):
        nxt = src[i0 + 1].lstrip()
        if nxt.startswith('australian politics", "AU politics", "Australian politics"]'):
            del src[i0 + 1]

    open(APP, "w", encoding="utf-8").write("\n".join(src) + "\n")

    print("OK patched:", APP)
    print("Backup:", bak)
    print("Fixed line:", i0 + 1)

if __name__ == "__main__":
    main()
