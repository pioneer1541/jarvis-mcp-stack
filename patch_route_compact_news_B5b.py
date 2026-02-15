#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import time

MARKER = "# ROUTE_COMPACT_NEWS_B5b"

def _read(p):
    with io.open(p, "r", encoding="utf-8", newline="") as f:
        return f.read()

def _write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(s)

def _backup(p):
    ts = time.strftime("%Y%m%d_%H%M%S")
    bak = "{0}.bak.before_route_compact_news_B5b_{1}".format(p, ts)
    with io.open(p, "r", encoding="utf-8", newline="") as fsrc:
        with io.open(bak, "w", encoding="utf-8", newline="") as fdst:
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

    # 1) locate route_request by a loose anchor (robust to CRLF / spaces)
    key = "def route_request("
    p0 = src.find(key)
    if p0 < 0:
        raise RuntimeError("Cannot find route_request() via 'def route_request('")

    # find end of that def line (support \n or \r\n)
    nl1 = src.find("\n", p0)
    if nl1 < 0:
        raise RuntimeError("Cannot find newline after route_request() def line")

    insert_flag = (
        "\n"
        "    {0}\n"
        "    # ROUTE_RETURN_DATA=1 to include raw debug payload in route_request outputs\n"
        "    _route_return_data = str(os.environ.get(\"ROUTE_RETURN_DATA\") or \"\").strip().lower() in (\"1\",\"true\",\"yes\",\"y\")\n"
        "\n"
    ).format(MARKER)

    src = src[:nl1+1] + insert_flag + src[nl1+1:]

    # 2) compact returns for news branches (default: no data)
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

    missing = []
    if old1 not in src:
        missing.append("#1 ok-return")
    if old2 not in src:
        missing.append("#2 fail-return")
    if old3 not in src:
        missing.append("#3 legacy-return")
    if missing:
        raise RuntimeError("Cannot find target return lines: {0}".format(", ".join(missing)))

    src = src.replace(old1, new1, 1)
    src = src.replace(old2, new2, 1)
    src = src.replace(old3, new3, 1)

    _write(path, src)
    print("OK patched. backup=", bak)

if __name__ == "__main__":
    main()
