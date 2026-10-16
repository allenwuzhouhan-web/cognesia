#!/usr/bin/env python3
"""Control the finite, local ParaLimbo transmission campaign."""
from pathlib import Path
import argparse
import json
import os
import sys

os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
os.environ.setdefault('OMP_NUM_THREADS', '1')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from flybrain.transmission_campaign import controller


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'start', 'status', 'pause', 'resume', 'stop', 'verify', '_worker'])
    parser.add_argument('--root', type=Path, default=controller.DEFAULT_ROOT)
    parser.add_argument('--output', type=Path, default=None)
    parser.add_argument('--predecessor', type=Path, help='Terminal predecessor; shares its storage and original deadline')
    args = parser.parse_args()
    args.output = args.output or controller.active_output()
    if args.command == 'prepare':
        result = controller.prepare(args.root, args.output, predecessor=args.predecessor)
    elif args.command in ('pause', 'resume', 'stop'):
        result = controller.request_control(args.command, args.output)
    else:
        result = getattr(controller, 'worker' if args.command == '_worker' else args.command)(args.output)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
