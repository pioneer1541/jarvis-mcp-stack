import re

P = "app.py"
lines = open(P, "r", encoding="utf-8").read().splitlines(True)

# 1) 找到函数 _ug_extract_readable_text
start = None
for i, ln in enumerate(lines):
    if re.match(r"^\s*def\s+_ug_extract_readable_text\s*\(", ln):
        start = i
        break
if start is None:
    raise SystemExit("cannot find def _ug_extract_readable_text(...) in app.py")

# 2) 估算该函数的结束位置：遇到下一个顶层 def / class / if __name__ 就结束
end = len(lines)
for j in range(start + 1, len(lines)):
    if re.match(r"^(def|class)\s+\w+", lines[j]) or re.match(r"^if\s+__name__\s*==\s*['\"]__main__['\"]\s*:", lines[j]):
        end = j
        break

block = "".join(lines[start:end])
if "_ug_clean_unicode" in block:
    print("patch already applied (found _ug_clean_unicode)")
    raise SystemExit(0)

# 3) 取函数体缩进（默认 4 空格兜底）
body_indent = "    "
for k in range(start + 1, end):
    m = re.match(r"^(\s+)\S", lines[k])
    if m:
        body_indent = m.group(1)
        break

# 4) 找到 "return out" 行，插在它前面
ret_line = None
for k in range(start + 1, end):
    if re.match(r"^\s*return\s+out\s*$", lines[k].strip()):
        ret_line = k
        break
if ret_line is None:
    # 兜底：插在函数末尾
    ret_line = end

inject = []
inject.append("\n")
inject.append(body_indent + "import unicodedata as _ud\n")
inject.append(body_indent + "import re as _re\n")
inject.append("\n")
inject.append(body_indent + "def _ug_clean_unicode(x: str) -> str:\n")
inject.append(body_indent + "    if not x:\n")
inject.append(body_indent + "        return \"\"\n")
inject.append(body_indent + "    x = _ud.normalize(\"NFKC\", x)\n")
inject.append(body_indent + "    # Drop format chars (zero-width, etc.)\n")
inject.append(body_indent + "    x = \"\".join(ch for ch in x if _ud.category(ch) != \"Cf\")\n")
inject.append(body_indent + "    # Replace weird spaces\n")
inject.append(body_indent + "    for cp in [0x00A0, 0x202F, 0x2007, 0x2009, 0x200A]:\n")
inject.append(body_indent + "        x = x.replace(chr(cp), \" \")\n")
inject.append(body_indent + "    x = x.replace(chr(0xFEFF), \"\")\n")
inject.append(body_indent + "    x = _re.sub(r\"\\s+\", \" \", x).strip()\n")
inject.append(body_indent + "    return x\n")
inject.append("\n")
inject.append(body_indent + "out = _ug_clean_unicode(out)\n")
inject.append("\n")

# 插入
lines[ret_line:ret_line] = inject

open(P, "w", encoding="utf-8").write("".join(lines))
print("patched: unicode cleanup + whitespace collapse before return out in _ug_extract_readable_text")
