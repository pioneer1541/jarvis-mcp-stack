#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import time

MARKER = "# ROUTE_COMPACT_NEWS_B5"

def _read(p):
    with io.open(p, "r", encoding="utf-8") as f:
        return f.read()

def _write(p, s):
    with io.open(p, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.before_route_compact_news_B5_{1}".format(p, ts)
    with io.open(p, "r", encoding="utf-8") as fsrc:
        with io.open(bak, "w", encoding="utf-8") as fdst:
            fdst.write(fsrc.read())
    return bak

def main():
    path = "app.py"
    if not os.path.exists(path):
        raise RuntimeError("app.py not found in current directory")

    src = _read(path)
    if MARKER in src:
        print("Already patched:", MARKER)
        return

    bak = _backup(path)

    # 1) Insert _route_return_data flag inside route_request() after empty-text guard
    anchor = "def route_request(text: str) -> dict:\n"
    p0 = src.find(anchor)
    if p0 < 0:
        raise RuntimeError("Cannot find route_request()")

    # find the empty guard "if not user_text:"
    p1 = src.find("    if not user_text:\n", p0)
    if p1 < 0:
        raise RuntimeError("Cannot find 'if not user_text' guard in route_request()")

    # find end of that guard block: the first blank line after it
    p2 = src.find("\n\n", p1)
    if p2 < 0:
        raise RuntimeError("Cannot find end of empty-text guard block")

    insert_flag = (
        "\n"
        "    {0}\n"
        "    # ROUTE_RETURN_DATA=1 to include raw debug payload in route_request outputs\n"
        "    _route_return_data = str(os.environ.get(\"ROUTE_RETURN_DATA\") or \"\").strip().lower() in (\"1\",\"true\",\"yes\",\"y\")\n"
        "\n"
    ).format(MARKER)

    src = src[:p2+2] + insert_flag + src[p2+2:]

    # 2) Replace 3 return lines in the news branches to be compact by default
    old1 = "            return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final, \"data\": rrn}"
    new1 = (
        "            ret = {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final}\n"
        "            if _route_return_data:\n"
        "                ret[\"data\"] = rrn\n"
        "            return ret"
    )

    old2 = "        return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": \"新闻检索失败或暂无结果。\", \"data\": rrn}"
    new2 = (
        "        ret = {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": \"新闻检索失败或暂无结果。\"}\n"
        "        if _route_return_data:\n"
        "            ret[\"data\"] = rrn\n"
        "        return ret"
    )

    old3 = "        return {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final, \"data\": data}"
    new3 = (
        "        ret = {\"ok\": True, \"route_type\": \"semi_structured_news\", \"final\": final}\n"
        "        if _route_return_data:\n"
        "            ret[\"data\"] = data\n"
        "        return ret"
    )

    if old1 not in src:
        raise RuntimeError("Cannot find target return line #1 (news ok return)")
    if old2 not in src:
        raise RuntimeError("Cannot find target return line #2 (news fail return)")
    if old3 not in src:
        raise RuntimeError("Cannot find target return line #3 (legacy news return)")

    src = src.replace(old1, new1, 1)
    src = src.replace(old2, new2, 1)
    src = src.replace(old3, new3, 1)

    _write(path, src)
    print("OK patched. backup=", bak)

if __name__ == "__main__":
    main()
