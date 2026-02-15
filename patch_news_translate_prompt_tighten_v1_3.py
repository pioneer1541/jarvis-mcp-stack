import io
import os
import sys

NEW_SYS_MSG_LINES = [
    '        sys_msg = (',
    '            "你是中文新闻播报翻译助手。你必须逐条逐句翻译我给你的 TITLE 和 SNIP 字段。"',
    '            "硬性规则："',
    '            "1) TITLE 的中文只能来自 TITLE；SNIP 的中文只能来自 SNIP。不得把 TITLE 的信息补到 SNIP，也不得把 SNIP 的信息补到 TITLE。"',
    '            "2) 只翻译，不得添加、推测、夸大、总结、改写事实；不得引入原文没有的时间、地点、数字、因果、结论。"',
    '            "3) 若 SNIP 出现截断迹象（例如包含 \\"...\\"、\\"…\\"、\\"po...\\" 等），表示内容不完整：必须保持不完整，只翻译已给出的片段，禁止补全/扩写/发挥。"',
    '            "4) 保留数字/日期/专有名词；如无常见译名可保留原文。不要为了顺口而改变含义。"',
    '            "5) 每条输出一行，严格保持条目数量一致。输出格式必须为："',
    '            "N) <TITLE的中文翻译> ||| <SNIP的中文翻译> 。SNIP 可为空但分隔符必须保留。"',
    '            "6) 除了上述格式，不得输出任何多余内容。"',
    '        )',
]

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    fn_i = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__translate_batch_to_zh("):
            fn_i = i
            break
    if fn_i < 0:
        print("ERROR: cannot find def _news__translate_batch_to_zh(")
        sys.exit(1)

    sys_i = -1
    for i in range(fn_i, min(fn_i + 350, len(lines))):
        if "sys_msg = (" in lines[i]:
            sys_i = i
            break
    if sys_i < 0:
        print("ERROR: cannot find sys_msg = ( inside _news__translate_batch_to_zh")
        sys.exit(1)

    end_i = -1
    for j in range(sys_i + 1, min(sys_i + 80, len(lines))):
        if lines[j].strip() == ")":
            end_i = j
            break
    if end_i < 0:
        print("ERROR: cannot find end of sys_msg block (a line with only ')')")
        sys.exit(1)

    newline = "\n"
    if lines[0].endswith("\r\n"):
        newline = "\r\n"
    repl = [x + newline for x in NEW_SYS_MSG_LINES]

    new_lines = lines[:sys_i] + repl + lines[end_i + 1:]
    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(new_lines))

    print("OK: tightened translation sys_msg prompt v1.3 (no expansion on truncated snippets)")

if __name__ == "__main__":
    main()
