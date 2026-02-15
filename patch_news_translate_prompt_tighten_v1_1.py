import io
import os
import sys

NEW_SYS_MSG_LINES = [
    '        sys_msg = (',
    '            "你是中文新闻播报翻译助手。任务：把英文新闻标题和摘要翻译成自然、适合中文语音播报的中文。"',
    '            "要求：1) 只翻译原文含义，不得添加、推测、夸大或改写事实；不要引入原文没有的时间、地点、数字、结论。"',
    '            "2) 保留并准确翻译专有名词；如无常见译名可保留原文。"',
    '            "3) 简洁口语化，不要加链接、不要加免责声明、不要加额外解释。"',
    '            "4) 每条输出一行，严格保持条目数量一致。格式必须为："',
    '            "N) <中文标题> ||| <中文摘要> 。摘要可为空但分隔符必须保留。"',
    '        )',
]

def main():
    p = "app.py"
    if not os.path.exists(p):
        print("ERROR: app.py not found")
        sys.exit(1)

    with io.open(p, "r", encoding="utf-8") as f:
        lines = f.read().splitlines(True)

    # Find function block: def _news__translate_batch_to_zh(
    fn_i = -1
    for i, ln in enumerate(lines):
        if ln.startswith("def _news__translate_batch_to_zh("):
            fn_i = i
            break
    if fn_i < 0:
        print("ERROR: cannot find def _news__translate_batch_to_zh(")
        sys.exit(1)

    # Find sys_msg assignment inside function
    sys_i = -1
    for i in range(fn_i, min(fn_i + 350, len(lines))):
        if "sys_msg = (" in lines[i]:
            sys_i = i
            break
    if sys_i < 0:
        print("ERROR: cannot find sys_msg = ( inside _news__translate_batch_to_zh")
        sys.exit(1)

    # Replace until the closing line of that parenthesized block
    # We assume the sys_msg block ends at a line whose stripped content is ")"
    end_i = -1
    for j in range(sys_i + 1, min(sys_i + 80, len(lines))):
        if lines[j].strip() == ")":
            end_i = j
            break
    if end_i < 0:
        print("ERROR: cannot find end of sys_msg block (a line with only ')')")
        sys.exit(1)

    # Preserve original indentation style check (expect 8 spaces in our inserted block)
    # Replace with NEW_SYS_MSG_LINES + original line endings
    newline = "\n"
    if lines[0].endswith("\r\n"):
        newline = "\r\n"

    repl = [x + newline for x in NEW_SYS_MSG_LINES]

    new_lines = lines[:sys_i] + repl + lines[end_i + 1:]

    with io.open(p, "w", encoding="utf-8") as f:
        f.write("".join(new_lines))

    print("OK: tightened translation sys_msg prompt (no hallucination / no extra facts)")

if __name__ == "__main__":
    main()
