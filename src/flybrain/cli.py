"""CLI stages fail closed and leave an inspectable report."""
from pathlib import Path
import argparse
import json
import sys
from .report import write_report, record_error
from .memguard import MemoryGuard


def print_result(result, root, as_json=False):
    if as_json or ("gates" not in result and "gate" not in result):
        print(json.dumps(result, indent=2))
        return
    gates = result.get("gates", [result])
    for gate in gates:
        print(f"{gate['gate']}: {gate['status']}")
        if "equilibration" in gate:
            eq = gate["equilibration"]
            derivative = eq.get("max_abs_dvdt_mV_per_ms")
            derivative_text = f"{derivative:.6f}" if isinstance(derivative, (int, float)) else "non-finite"
            print(f"  Endpoint max |dV/dt|: {derivative_text} mV/ms (limit 0.001)")
            print(f"  Nonstationary neurons: {eq['unstable_neurons']:,}; clamp events: {eq['clamp_events']:,}")
        elif str(gate.get("gate", "")).startswith("V-NM-"):
            checks = gate.get("checks", [])
            if checks:
                print(f"  {sum(c['status'] == 'PASS' for c in checks)}/{len(checks)} checks passed")
                for check in checks:
                    if check["status"] != "PASS":
                        print(f"  {check['status']} {check['name']}: expected {check.get('expected')}; observed {check.get('observed')}")
            if gate.get("metrics"):
                print("  " + json.dumps(gate["metrics"]))
        elif "metrics" in gate:
            print(f"  Mean firing-rate correlation: {gate['metrics'].get('mean_rate_correlation')}")
        elif gate.get("checks"):
            print(f"  {sum(c['status'] == 'PASS' for c in gate['checks'])}/{len(gate['checks'])} checks passed")
            if str(gate.get("gate", "")).startswith("V-NM-"):
                for check in gate["checks"]:
                    if check["status"] == "FAIL":
                        print(f"  FAIL {check['name']}: expected {check.get('expected')}; observed {check.get('observed')}")
        for warning in gate.get("warnings", []):
            print(f"  Warning: {warning}")
    if result.get("stop_reason"):
        print(f"Stopped: {result['stop_reason']}")
    print(f"Full evidence: {root / 'REPORT.md'}")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # These independently configured services retain their own help/options.
    if argv and argv[0] in ('api', 'agent'):
        if argv[0] == 'api':
            from .public_api import main as service_main
        else:
            from .local_agent import main as service_main
        return service_main(argv[1:])
    parser = argparse.ArgumentParser(prog="flybrain")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--mem-limit-gb", type=float, default=40)
    parser.add_argument("--json", action="store_true", help="Print complete result JSON")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser('api', help='Authenticated public tool gateway (flybrain api --help)')
    sub.add_parser('agent', help='Dedicated local GPT-OSS-20B research console (flybrain agent --help)')
    f = sub.add_parser("fetch", help="Fetch and inspect real release files")
    f.add_argument("--core-only", action="store_true")
    f.add_argument("--synapses", action="store_true")
    b = sub.add_parser("build", help="Assemble the verified sparse network")
    b.add_argument("--mode", choices=("hybrid", "all_lif"), default="hybrid")
    v = sub.add_parser("validate", help="Run validation gates")
    v.add_argument("--gate", default="V-A")
    v.add_argument("--trials", type=int, default=10)
    v.add_argument("--duration-ms", type=float, default=1000)
    v.add_argument("--threads", type=int, default=16)
    v.add_argument("--integrator", choices=("exponential_euler", "exact_linear"), default="exponential_euler")
    run = sub.add_parser("run", help="Run a reference experiment or the hybrid dark control")
    run.add_argument("stimulus", choices=("reference", "dark"))
    run.add_argument("--duration-ms", type=float, default=None)
    run.add_argument("--seed", type=int)
    run.add_argument("--threads", type=int, default=16)
    run.add_argument("--integrator", choices=("exponential_euler", "exact_linear"), default="exponential_euler")
    sub.add_parser("report", help="Regenerate the evidence report")
    models = sub.add_parser('models', help='List, compile and validate versioned model providers')
    models_sub = models.add_subparsers(dest='models_command', required=True)
    models_sub.add_parser('list', help='List installed and available model providers')
    models_sub.add_parser('compile-paralimbo', help='Compile ParaLimbo from pinned local BANC and FlyWire assets')
    models_sub.add_parser('validate-paralimbo', help='Audit ParaLimbo construction and source fidelity')
    neuromod = sub.add_parser("neuromod", help="Build and validate the neuromodulation extension")
    neuromod_sub = neuromod.add_subparsers(dest="neuromod_command", required=True)
    neuromod_sub.add_parser("build", help="Build and validate the headless extension prerequisites")
    train_parser = sub.add_parser('train', help='Execute a YAML protocol on the actual modulated core')
    train_parser.add_argument('protocol', type=Path)
    capacity_parser = sub.add_parser('capacity', help='Measure a declared training/readout capacity pilot')
    capacity_parser.add_argument('--full', action='store_true', help='Use all enumerated source handles')
    replay_parser = sub.add_parser('replay', help='Verify a saved session by exact event-log replay')
    replay_parser.add_argument('events', type=Path)
    rt = sub.add_parser('rt', help='Live coupled-core observatory')
    rt_sub = rt.add_subparsers(dest='rt_command', required=True)
    serve_parser = rt_sub.add_parser('serve')
    serve_parser.add_argument('--core', action='store_true', help='Use the normative 13,300-neuron core')
    serve_parser.add_argument('--port', type=int, default=8795)
    serve_parser.add_argument('--seed', type=int, default=7)
    viewer = sub.add_parser("view", help="Open the interactive visual simulator")
    viewer.add_argument("--port", type=int, default=8794)
    viewer.add_argument("--open", action="store_true", help="Open in the default browser")
    viewer.add_argument('--no-watch', action='store_true', help='Disable automatic project updates')
    viewer.add_argument('--reload-child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    args.root = args.root.resolve()
    try:
        if args.command == "view":
            if not args.no_watch and not args.reload_child:
                from .live_server import supervise
                return supervise(args.root, port=args.port, open_browser=args.open, memory_limit_gb=args.mem_limit_gb)
            watcher = None
            if args.reload_child:
                from .live_reload import ProjectWatcher
                watcher = ProjectWatcher(args.root)
            from .visual_server import serve
            return serve(args.root, port=args.port, open_browser=args.open, memory_limit_gb=args.mem_limit_gb, watcher=watcher)
        if args.command == 'rt':
            from .rt.bridge import serve
            serve(args.root, port=args.port, seed=args.seed)
            return 0
        with MemoryGuard(args.mem_limit_gb):
            if args.command == 'models':
                if args.models_command == 'list':
                    from .model_registry import catalog
                    result = {'models': catalog(args.root)}
                elif args.models_command == 'compile-paralimbo':
                    from .paralimbo import compile_paralimbo
                    result = compile_paralimbo(args.root)
                else:
                    from .paralimbo import validate_paralimbo
                    result = validate_paralimbo(args.root)
                print(json.dumps(result, indent=2))
                if args.models_command == 'validate-paralimbo':
                    return 0 if result.get('status') == 'PASS' else 1
                return 1 if result.get('status') == 'FAIL' else 0
            elif args.command == 'train':
                from .rt.protocol import train
                result = train(args.root, args.protocol)
                print_result(result, args.root, args.json)
            elif args.command == 'capacity':
                from .rt.capacity import measure_capacity
                result = measure_capacity(args.root, full=args.full)
                print_result(result, args.root, args.json)
                write_report(args.root)
                return 0 if result.get('status') == 'PASS' else 1
            elif args.command == 'replay':
                from .rt.replay import replay_session
                result = replay_session(args.events, args.root)
                print_result(result, args.root, args.json)
                return 0 if result['status']=='PASS' else 1
            elif args.command == "neuromod":
                from .neuromod.pipeline import build_neuromod
                result = build_neuromod(args.root)
                print_result(result, args.root, args.json)
                write_report(args.root)
                return 0 if result.get("status") == "PASS" else 1
            elif args.command == "fetch":
                from .fetch import fetch
                fetch(args.root, neuropils=not args.core_only, synapses=args.synapses)
            elif args.command == "build":
                from .build import build_network
                result = build_network(args.root, mode=args.mode)
                print_result(result, args.root, args.json)
            elif args.command == "validate":
                if args.gate == "V-A":
                    from .validate_data import validate_data
                    result = validate_data(args.root)
                elif args.gate == "V-E":
                    from .validate_engine import validate_engine
                    result = validate_engine(args.root, trials=args.trials, duration_ms=args.duration_ms, threads=args.threads, integrator=args.integrator)
                elif args.gate in ("hybrid", "V-C", "V-D"):
                    from .validate_hybrid import validate_hybrid
                    result = validate_hybrid(args.root, threads=args.threads)
                elif args.gate == "V-NM-C":
                    from .neuromod.sources import build_sources
                    result = build_sources(args.root)
                elif args.gate == "V-NM-COMP":
                    from .neuromod.compartments import build_compartments
                    result = build_compartments(args.root)
                elif args.gate == "V-NM-CORE":
                    from .neuromod.core import validate_core_stationarity
                    result = validate_core_stationarity(args.root)
                elif args.gate == "V-NM-D":
                    from .neuromod.field import validate_field
                    result = validate_field(args.root)
                elif args.gate == "V-NM-ODOUR":
                    from .neuromod.odour import build_odours
                    result = build_odours(args.root)
                elif args.gate == "V-NM-ODSP":
                    from .neuromod.odour_validation import validate_odour_sparseness
                    result = validate_odour_sparseness(args.root)
                elif args.gate == "V-NM-A":
                    from .neuromod.receptors import validate_receptors
                    result = validate_receptors(args.root)
                elif args.gate == "V-NM-E":
                    from .neuromod.plasticity import validate_plasticity
                    result = validate_plasticity(args.root)
                elif args.gate == 'stability':
                    from .neuromod.stability import validate_stability
                    result = validate_stability(args.root, threads=args.threads)
                elif args.gate in ('V-NM-B', "V-NM-F'", 'V-NM-F', 'V-NM-G', 'V-NM-H', 'V-NM-J', 'V-NM-K', 'neuromod-runtime'):
                    from .rt.validation import validate_runtime
                    result = validate_runtime(args.root, gate=args.gate)
                else:
                    raise ValueError(f"Gate {args.gate} is not implemented at this stage")
                print_result(result, args.root, args.json)
                write_report(args.root)
                if "gates" in result and args.gate not in ("hybrid", "neuromod-runtime", "stability"):
                    selected = next((g for g in result["gates"] if g.get("gate") == args.gate), {})
                    return 0 if selected.get("status") == "PASS" else 1
                return 0 if result.get("stage4_status", result.get("status")) == "PASS" else 1
            elif args.command == "run":
                if args.stimulus == "reference":
                    from .run import run_reference
                    result = run_reference(args.root, duration_ms=1000 if args.duration_ms is None else args.duration_ms, seed=args.seed, threads=args.threads, integrator=args.integrator, mem_limit_gb=args.mem_limit_gb)
                else:
                    if args.seed is not None or args.integrator != "exponential_euler":
                        raise ValueError("Dark validation uses the configured seed and exponential-Euler protocol; reference-only overrides are not accepted")
                    if args.duration_ms is not None and args.duration_ms != 5000:
                        raise ValueError("The validated dark-control protocol requires 5000 ms, after 1000 ms equilibration")
                    from .validate_hybrid import validate_hybrid
                    result = validate_hybrid(args.root, threads=args.threads)
                print_result(result, args.root, args.json)
                if result.get("stage4_status") == "FAIL":
                    write_report(args.root)
                    return 1
            write_report(args.root)
        return 0
    except Exception as error:
        if args.command == 'view':
            print(f'Stopped viewer: {error}', file=sys.stderr)
            return 1
        record_error(args.root, args.command, error)
        print(f"Stopped {args.command}: {error}\nSee {args.root / 'REPORT.md'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
