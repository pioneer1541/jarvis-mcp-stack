import re

def main():
    path = "app.py"
    s = open(path, "r", encoding="utf-8").read()

    # Fix empty try blocks like:
    #   try:
    #   except Exception:
    # by inserting a 'pass'.
    # This prevents IndentationError and container restart loop.
    pat = re.compile(r'(?m)^([ \t]*)try:\s*\n\1except Exception:')
    new_s, n = pat.subn(r'\1try:\n\1    pass\n\1except Exception:', s)

    if n <= 0:
        raise RuntimeError("No empty 'try/except' pattern found. Patch not applied.")

    # backup
    open("app.py.bak.fix_restart_indent_v1", "w", encoding="utf-8").write(s)
    open(path, "w", encoding="utf-8").write(new_s)

    print("patched_ok=1")
    print("empty_try_fixed_count=" + str(n))
    print("backup=app.py.bak.fix_restart_indent_v1")

if __name__ == "__main__":
    main()
