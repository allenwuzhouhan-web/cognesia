#!/usr/bin/env python3
"""Validate or prepare a separately frozen continuation; never run simulations."""
from pathlib import Path
import argparse
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from flybrain.transmission_campaign.continuation import prepare_continuation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--predecessor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--replay-result', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    result = prepare_continuation(args.root, args.predecessor, args.output, args.review, args.replay_result, apply=args.apply)
    if not args.apply:
        bridge = result['bridge']
        result = {'status': result['status'], 'output': result['output'],
            'original_started_at': bridge['original_started_at'], 'deadline': bridge['deadline'],
            'reusable_complete': sum(r['state'] == 'complete' for r in bridge['jobs']),
            'preserved_failed': sum(r['state'] == 'failed' for r in bridge['jobs']),
            'referenced_artifacts': len(bridge['referenced_artifacts']),
            'remaining_work': bridge['remaining_work'], 'worker_launched': False}
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
