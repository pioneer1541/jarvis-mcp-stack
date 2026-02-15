import os
import time

PATH = os.environ.get("MCP_APP") or "./app.py"

DECORATOR = '@mcp.tool(description="Internet query tool (preferred). Uses 1x web_search + optional 1x open_url_extract internally; returns voice-friendly short answer only.")\n'

def read_lines(p):
    with open(p, "r", encoding="utf-8") as f:
        return f.read().splitlines(True)

def write_lines(p, lines):
    with open(p, "w", encoding="utf-8") as f:
        f.writelines(lines)

def backup(p, lines):
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = p + ".bak." + ts
    write_lines(bak, lines)
    return bak

def main():
    lines = read_lines(PATH)
    bak = backup(PATH, lines)

    out = []
    inserted = 0

    for i, line in enumerate(lines):
        # 如果已经有 web_answer 的 @mcp.tool（哪怕被注释），就不重复插
        if line.lstrip().startswith("def web_answer("):
            # check previous non-empty line in out
            j = len(out) - 1
            while j >= 0 and out[j].strip() == "":
                j -= 1
            if j >= 0 and "@mcp.tool" in out[j] and "web_answer" in out[j]:
                out.append(line)
            else:
                # 如果上一行是被注释的 @mcp.tool，就替换成未注释版本
                if j >= 0 and out[j].lstrip().startswith("#") and "@mcp.tool" in out[j]:
                    # remove the commented decorator line
                    out.pop()
                out.append(DECORATOR)
                out.append(line)
                inserted = 1
            continue

        out.append(line)

    write_lines(PATH, out)
    print("patched_path=" + PATH)
    print("backup_path=" + bak)
    print("inserted_web_answer_decorator=" + str(inserted))

if __name__ == "__main__":
    main()
