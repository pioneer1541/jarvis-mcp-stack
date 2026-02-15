#!/usr/bin/env python3
# patch_default_prefer_lang_B10.py
# هدف: 让 route_request 默认 prefer_lang="zh"（除非用户明确要求英文）
# 并让 route_request 接受 prefer_lang 参数，避免 unexpected keyword
# 同时尽量稳健：用块级扫描定位函数边界，避免脆弱锚点

import sys
import os
import re
import shutil
from datetime import datetime

def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def _write(path, s):
    with open(path, "w", encoding="utf-8") as f:
        f.write(s)

def _backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path + ".bak.B10_" + ts
    shutil.copy2(path, bak)
    return bak

def _find_def_block(lines, func_name):
    # 返回 (def_line_idx, block_start_idx, block_end_excl_idx)
    # block_start_idx 会把紧邻的 decorator 一并包含进去（如果有）
    def_pat = re.compile(r"^def\s+" + re.escape(func_name) + r"\s*\(")
    def_idx = -1
    for i, ln in enumerate(lines):
        if def_pat.match(ln):
            def_idx = i
    if def_idx < 0:
        return None

    # 向上吞 decorator
    start = def_idx
    j = def_idx - 1
    while j >= 0:
        s = lines[j].lstrip()
        if s.startswith("@"):
            start = j
            j -= 1
            continue
        break

    # 计算函数体缩进
    def_line = lines[def_idx]
    base_indent = len(def_line) - len(def_line.lstrip())

    # 向下找 block end：遇到 <= base_indent 的非空行，说明函数结束
    end = def_idx + 1
    for k in range(def_idx + 1, len(lines)):
        ln = lines[k]
        if not ln.strip():
            end = k + 1
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind <= base_indent and (not ln.lstrip().startswith("#")):
            end = k
            break
        end = k + 1

    return (def_idx, start, end)

def _patch_route_request(src):
    lines = src.splitlines(True)
    blk = _find_def_block(lines, "route_request")
    if not blk:
        raise RuntimeError("Cannot find route_request()")

    def_idx, start, end = blk
    block = lines[start:end]
    block_text = "".join(block)

    # 1) 修改 def 签名：确保包含 language 和 prefer_lang（保持兼容）
    # 支持带返回标注 -> dict:
    def_line_idx_in_block = def_idx - start
    old_def_line = block[def_line_idx_in_block]

    # 取出 def route_request(...) 这一行并替换
    # 尽量不破坏 decorator；只改 def 行
    new_def_line = None
    m = re.match(r"^(\s*)def\s+route_request\s*\((.*)\)\s*(->\s*[^:]+)?\s*:\s*$", old_def_line)
    if m:
        indent = m.group(1)
        params = m.group(2)

        # 如果已经有 prefer_lang 就不重复加
        has_lang = ("language" in params)
        has_pl = ("prefer_lang" in params)

        # 基于已有参数做最小增量
        # 如果没有 language，则加 language；如果没有 prefer_lang，则加 prefer_lang
        # 注意保持简单：不做复杂解析，直接按逗号追加
        p = params.strip()
        if p.endswith(","):
            p = p[:-1].rstrip()

        add = []
        if not has_lang:
            add.append("language: str = None")
        if not has_pl:
            add.append("prefer_lang: str = None")

        if add:
            if p:
                p = p + ", " + ", ".join(add)
            else:
                p = ", ".join(add)

        new_def_line = indent + "def route_request(" + p + ") -> dict:\n"
    else:
        # 兜底：直接强制替换为标准签名（保持 0 缩进）
        new_def_line = "def route_request(text: str, language: str = None, prefer_lang: str = None) -> dict:\n"

    block[def_line_idx_in_block] = new_def_line

    # 2) 在 user_text 空校验后插入 prefer_lang 推导逻辑（默认 zh，除非用户明确要英文）
    block_text2 = "".join(block)
    block_lines = block_text2.splitlines(True)

    # 找到 "if not user_text" 这一段末尾位置
    # 逻辑：定位 if not user_text: 后面紧跟的 return 块结束，然后插入
    ins_at = None
    for i in range(len(block_lines)):
        if re.match(r"^\s*if\s+not\s+user_text\s*:\s*$", block_lines[i]):
            # 向下跳过 return 块（直到遇到空行或下一个同级缩进语句）
            base_ind = len(block_lines[i]) - len(block_lines[i].lstrip())
            j = i + 1
            last = j
            while j < len(block_lines):
                ln = block_lines[j]
                if not ln.strip():
                    last = j + 1
                    j += 1
                    continue
                ind = len(ln) - len(ln.lstrip())
                if ind <= base_ind:
                    break
                last = j + 1
                j += 1
            ins_at = last
            break

    if ins_at is None:
        raise RuntimeError("Cannot locate user_text empty-check block in route_request()")

    # 生成插入片段（缩进按函数体一级缩进推断）
    # 取 def 行缩进 + 4 spaces 作为 body indent（保守）
    def_indent = re.match(r"^(\s*)def\s+route_request", block_lines[def_line_idx_in_block]).group(1)
    body_indent = def_indent + "    "

    inject = []
    inject.append("\n")
    inject.append(body_indent + "# prefer_lang: default to zh unless user explicitly asks for English\n")
    inject.append(body_indent + "pl_raw = (prefer_lang if isinstance(prefer_lang, str) else \"\")\n")
    inject.append(body_indent + "pl_raw = pl_raw.strip().lower()\n")
    inject.append(body_indent + "if not pl_raw:\n")
    inject.append(body_indent + "    # env override (optional)\n")
    inject.append(body_indent + "    env_pl = os.environ.get(\"DEFAULT_PREFER_LANG\") or os.environ.get(\"PREFER_LANG\") or \"\"\n")
    inject.append(body_indent + "    pl_raw = str(env_pl).strip().lower()\n")
    inject.append(body_indent + "if not pl_raw:\n")
    inject.append(body_indent + "    # language hint from HA (optional); still default to zh if unknown\n")
    inject.append(body_indent + "    lg = str(language or \"\").strip().lower()\n")
    inject.append(body_indent + "    if lg.startswith(\"en\"):\n")
    inject.append(body_indent + "        pl_raw = \"en\"\n")
    inject.append(body_indent + "    elif lg.startswith(\"zh\"):\n")
    inject.append(body_indent + "        pl_raw = \"zh\"\n")
    inject.append(body_indent + "    else:\n")
    inject.append(body_indent + "        pl_raw = \"zh\"\n")
    inject.append(body_indent + "# explicit user override\n")
    inject.append(body_indent + "ut_low = user_text.lower()\n")
    inject.append(body_indent + "if (\"英文\" in user_text) or (\"english\" in ut_low) or (\"用英文\" in user_text) or (\"原文\" in user_text):\n")
    inject.append(body_indent + "    pl_raw = \"en\"\n")
    inject.append(body_indent + "if (\"中文\" in user_text) or (\"汉语\" in user_text) or (\"用中文\" in user_text):\n")
    inject.append(body_indent + "    pl_raw = \"zh\"\n")
    inject.append(body_indent + "prefer_lang = (\"en\" if pl_raw.startswith(\"en\") else \"zh\")\n")

    # 如果已经注入过，则不重复注入
    already = False
    for ln in block_lines:
        if "DEFAULT_PREFER_LANG" in ln and "prefer_lang" in ln and "explicit user override" in block_text2:
            already = True
            break

    if not already:
        block_lines = block_lines[:ins_at] + inject + block_lines[ins_at:]

    patched_block = "".join(block_lines)
    lines[start:end] = [patched_block]
    return "".join(lines)

def _patch_news_digest_default(src):
    # news_digest 已有 prefer_lang 默认值，但为了稳健，补一段：如果 prefer_lang 非法 -> 走 env -> zh
    lines = src.splitlines(True)
    blk = _find_def_block(lines, "news_digest")
    if not blk:
        # 如果没有 news_digest（只有 legacy），则跳过
        return src

    def_idx, start, end = blk
    block = "".join(lines[start:end])

    # 在函数开头（docstring 后面）插入 prefer_lang 归一化
    # 简化：找第一处 token/base_url 前插
    if "DEFAULT_PREFER_LANG" in block:
        return src

    insert_pat = re.compile(r"^\s*base_url\s*=\s*", re.MULTILINE)
    m = insert_pat.search(block)
    if not m:
        return src

    ins_pos = m.start()
    head = block[:ins_pos]
    tail = block[ins_pos:]

    # 推断缩进（base_url 行的缩进）
    base_line_start = block.rfind("\n", 0, ins_pos) + 1
    base_indent = ""
    j = base_line_start
    while j < len(block) and block[j] in (" ", "\t"):
        base_indent += block[j]
        j += 1

    inject = ""
    inject += base_indent + "# normalise prefer_lang (default zh)\n"
    inject += base_indent + "pl = str(prefer_lang or \"\").strip().lower()\n"
    inject += base_indent + "if not pl:\n"
    inject += base_indent + "    pl = str(os.environ.get(\"DEFAULT_PREFER_LANG\") or os.environ.get(\"PREFER_LANG\") or \"zh\").strip().lower()\n"
    inject += base_indent + "prefer_lang = (\"en\" if pl.startswith(\"en\") else \"zh\")\n\n"

    block2 = head + inject + tail
    lines[start:end] = [block2]
    return "".join(lines)

def main():
    path = "app.py"
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        path = sys.argv[1].strip()

    if not os.path.exists(path):
        raise RuntimeError("File not found: " + path)

    src = _read(path)
    bak = _backup(path)

    out = src
    out = _patch_route_request(out)
    out = _patch_news_digest_default(out)

    _write(path, out)
    print("OK: patched " + path)
    print("Backup: " + bak)

if __name__ == "__main__":
    main()

