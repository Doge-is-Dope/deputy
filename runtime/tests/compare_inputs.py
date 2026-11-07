"""Compare what the scripted models were asked in two recorded test runs (tests/recording.py):

    CU_RECORD_INPUTS=/tmp/before uv run pytest tests/unit -q   # on the old version
    CU_RECORD_INPUTS=/tmp/after uv run pytest tests/unit -q    # on the new one
    uv run python tests/compare_inputs.py /tmp/before /tmp/after

Prints each test whose models were asked anything differently, with the first lines that differ, and exits 1 if
any did."""

import difflib
import json
import sys
from pathlib import Path

SHOWN = 40  # diff lines shown per test


def main(before: Path, after: Path) -> int:
    old = {path.name: path for path in before.glob("*.json")}
    new = {path.name: path for path in after.glob("*.json")}
    differ = 0
    for name in sorted(old.keys() | new.keys()):
        if name not in new or name not in old:
            print(f"{'only before' if name in old else 'only after'}: {name}")
            continue
        a, b = (json.dumps(json.loads(p.read_text()), indent=1, ensure_ascii=False).splitlines() for p in (old[name], new[name]))
        if a == b:
            continue
        differ += 1
        print(f"differs: {name}")
        for line in list(difflib.unified_diff(a, b, lineterm="", n=2))[:SHOWN]:
            print(f"  {line[:200]}")
    print(f"{len(old.keys() & new.keys())} tests in both, {differ} differ")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
