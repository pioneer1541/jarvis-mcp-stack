import re
import shutil
from datetime import datetime

APP = "app.py"

def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = "app.py.bak.fix_glued_retdef_{0}".format(ts)
    shutil.copyfile(APP, bak)

    with open(APP, "r", encoding="utf-8") as f:
        s = f.read()

    # Fix: "return retdef _news__norm_host" -> "return ret\n\ndef _news__norm_host"
    s2, n1 = re.subn(
        r'return\s+retdef\s+(_news__norm_host\s*\()',
        'return ret\n\ndef \\1',
        s,
        count=1
    )

    # More general safety: if any "return retdef def " pattern exists (rare)
    s2, n2 = re.subn(
        r'return\s+retdef\s+def\s+',
        'return ret\n\ndef ',
        s2
    )

    if (n1 + n2) == 0:
        print("WARN: no glued pattern found; no changes made.")
        print("Backup:", bak)
        return

    with open(APP, "w", encoding="utf-8") as f:
        f.write(s2)

    print("OK: fixed glued 'return retdef' line.")
    print("Backup:", bak)
    print("Applied:", {"fix_return_retdef_norm_host": n1, "fix_return_retdef_def": n2})

if __name__ == "__main__":
    main()
