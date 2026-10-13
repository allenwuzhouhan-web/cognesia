"""Checks and explicit research rebuild; never download missing research data."""
import argparse
import json
import sys

from . import MODEL_HASH, MODEL_ID, PUBLIC_NAME, archived_manifest, check_graph_inputs, check_rebuild_inputs


def main():
    parser = argparse.ArgumentParser(description="ParaLimbo 1: inspect bindings, check supplied data, or rebuild")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("identity", help="Show the public name and archived scientific identity")
    for command in ("check-inputs", "check-rebuild-inputs", "rebuild"):
        child = sub.add_parser(command)
        child.add_argument("--graph-root", required=True)
    args = parser.parse_args()
    try:
        if args.command == "identity":
            from flybrain.model_registry import stable_hash
            manifest = archived_manifest()
            if stable_hash({k:v for k,v in manifest.items() if k != "model_hash"}) != MODEL_HASH:
                raise ValueError("Bundled historical model manifest is corrupt")
            result = {"name": PUBLIC_NAME, "model_id": MODEL_ID, "model_hash": MODEL_HASH,
                      "distribution_version": "1.0.0", "compiled_graph_included": False}
        elif args.command == "check-inputs":
            result = check_graph_inputs(args.graph_root)
        else:
            result = check_rebuild_inputs(args.graph_root)
            if args.command == "rebuild":
                from flybrain.neural_baseline import build_candidate
                rebuilt = build_candidate(args.graph_root)
                result = {"status": "RESEARCH_REBUILD", "model_hash": rebuilt["model_hash"],
                          "matches_archived_model": rebuilt["model_hash"] == MODEL_HASH,
                          "note": "A different hash is a new compiled identity and does not inherit the published benchmark results."}
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print("ParaLimbo 1 input check failed: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
