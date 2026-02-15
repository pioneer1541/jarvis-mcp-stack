#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import shutil

TARGET = "app.py"


def _now_stamp():
    return time.strftime("%Y%m%d_%H%M%S", time.localtime())


def _backup_file(path):
    bak = path + ".bak.news_v2_5." + _now_stamp()
    shutil.copy2(path, bak)
    return bak


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)  # keep line endings


def _write(path, lines):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def main():
    if not os.path.exists(TARGET):
        raise SystemExit("ERROR: not found: " + TARGET)

    s = _read(TARGET)

    # 目标行（你报错位置）
    needle = "for r in (rules_zh or []) + (rules_en or []):"

    idx = -1
    for i, line in enumerate(s):
        if needle in line:
            idx = i
            break

    if idx < 0:
        # 兼容轻微变体（空格不同）
        for i, line in enumerate(s):
            if "for r in" in line and "rules_zh" in line and "rules_en" in line and "+ (rules_en" in line:
                idx = i
                break

    if idx < 0:
        raise SystemExit("ERROR: target loop not found in _news__build_query")

    indent = s[idx].split("for r in", 1)[0]

    # 如果已经修过就不重复插入
    lookback = "".join(s[max(0, idx - 20):idx])
    if "__coerce_list" not in lookback:
        helper = []
        helper.append(indent + "def __coerce_list(v):\n")
        helper.append(indent + "    if v is None:\n")
        helper.append(indent + "        return []\n")
        helper.append(indent + "    if isinstance(v, (list, tuple)):\n")
        helper.append(indent + "        return list(v)\n")
        helper.append(indent + "    if isinstance(v, str):\n")
        helper.append(indent + "        vv = v.strip()\n")
        helper.append(indent + "        if not vv:\n")
        helper.append(indent + "            return []\n")
        helper.append(indent + "        return [vv]\n")
        helper.append(indent + "    return [v]\n")
        helper.append("\n")

        s[idx:idx] = helper
        idx = idx + len(helper)

    # 替换原始 for 行为安全拼接
    old_line = s[idx]
    new_line = indent + "for r in (__coerce_list(rules_zh) + __coerce_list(rules_en)):\n"
    if old_line == new_line:
        print("No change: already patched.")
        return

    s[idx] = new_line

    bak = _backup_file(TARGET)
    _write(TARGET, s)

    print("OK: patched rules concat in _news__build_query")
    print("Backup:", bak)


if __name__ == "__main__":
    main()
