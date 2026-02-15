#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import shutil
import time


APP_FILE = "app.py"


def _backup_path(src_path: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return src_path + ".bak.news_v2_5." + ts


def main():
    if not os.path.exists(APP_FILE):
        raise SystemExit("ERROR: app.py not found in current directory")

    with open(APP_FILE, "r", encoding="utf-8") as f:
        s = f.read()

    # 找到所有 def _news__build_query(
    defs = list(re.finditer(r"^def _news__build_query\s*\(", s, flags=re.M))
    if len(defs) < 2:
        print("No change: only found {0} def _news__build_query".format(len(defs)))
        return

    # 仅重命名“第二个”定义：def _news__build_query(terms, rules_zh, rules_en) -> str
    second = defs[1]
    start = second.start()

    # 从第二个 def 行开始往后截一小段，确保我们改的是“terms/rules”那个版本
    head = s[start:start + 400]
    # 弱校验：这个版本里一般会出现 terms / rules_zh / rules_en 字样
    if ("terms" not in head) or ("rules_zh" not in head) or ("rules_en" not in head):
        # 仍然继续，但打印提示，避免误改
        print("WARN: second _news__build_query signature check not strong; proceeding cautiously.")

    s2 = s[:start] + s[start:].replace(
        "def _news__build_query(",
        "def _news__build_query_rules(",
        1
    )

    # 修复 legacy 调用点：把 _news__build_query(terms, ...) 改成 _news__build_query_rules(terms, ...)
    s3 = s2.replace("_news__build_query(terms", "_news__build_query_rules(terms")

    if s3 == s:
        print("No change: content identical after attempted patch")
        return

    backup = _backup_path(APP_FILE)
    shutil.copy2(APP_FILE, backup)
    with open(APP_FILE, "w", encoding="utf-8") as f:
        f.write(s3)

    print("Backup:", backup)
    print("OK: renamed second _news__build_query -> _news__build_query_rules, and updated legacy callsites")


if __name__ == "__main__":
    main()
