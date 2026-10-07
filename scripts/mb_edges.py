#!/usr/bin/env python3
"""Re-run all eleven released mushroom-body motif counts and V-NM-C."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys

from flybrain.neuromod.sources import build_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):
        result = build_sources(args.root)
    print(json.dumps({key: result.get(key) for key in ("status", "motifs", "failed_checks", "warning_checks")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
