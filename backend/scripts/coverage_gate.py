"""Fail CI if any *core* module drops below the coverage floor.

    python scripts/coverage_gate.py coverage.json [--min 80]

Core modules are where a regression silently breaks the product's promises:
the rule engine, scoring, graph traversal and RBAC/auth. Each is checked
individually, so a well-tested module can't hide an untested one in an average.
"""

import argparse
import json
import sys
from pathlib import Path

CORE = {
    "app/verify/rules.py": "rule engine",
    "app/verify/scoring.py": "quality scoring",
    "app/verify/graphview.py": "rule-engine graph snapshot",
    "app/services/graph.py": "graph storage + traversal",
    "app/services/access.py": "RBAC",
    "app/services/auth_service.py": "auth (tokens, rotation)",
    "app/core/security.py": "auth (hashing, JWT)",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--min", type=float, default=80.0)
    args = ap.parse_args()
    report = json.loads(args.report.read_text())
    files = {k.replace("\\", "/"): v for k, v in report["files"].items()}
    failed = False
    print(f"{'module':<34} {'what':<28} {'cover':>6}")
    for path, what in CORE.items():
        if path not in files:
            print(f"{path:<34} {what:<28}  MISSING")
            failed = True
            continue
        pct = files[path]["summary"]["percent_covered"]
        ok = pct >= args.min
        failed |= not ok
        print(f"{path:<34} {what:<28} {pct:5.1f}% {'' if ok else f'< {args.min:.0f}% FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
