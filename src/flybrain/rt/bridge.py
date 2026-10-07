"""Local asynchronous transport; the simulation thread exclusively owns the engine.

The browser receives measured snapshots only. A slow simulation slows model time;
frames may be dropped without blocking integration or inventing missing samples.
"""
from __future__ import annotations

import asyncio
import base64
import re
from concurrent.futures import Future
import copy
from dataclasses import dataclass
import io
import json
from pathlib import Path
import queue
import threading
import time
import zipfile
import yaml
from urllib.parse import urlsplit

import numpy as np

FRAME_SCHEMA = 1
HEADER_FLOATS = 6
SUMMARY_FIELDS = ("valence", "kc_active_fraction", "voltage_min_mV", "voltage_max_mV", "voltage_out_of_bounds", "spikes", "total_absolute_weight_change")
ARRAY_FIELDS = ("kc_rates_hz", "dan_rates_hz", "mbon_rates_hz", "concentrations_au", "weights_relative", "weight_heatmap", "atlas_rates_hz", "atlas_voltage_mV")


def binary_frame(snapshot, frame_counter):
    """Little-endian float32 wire data with absent measurements encoded as NaN."""
    parts, layout, offset = [], [], 0
    for name in SUMMARY_FIELDS:
        value = snapshot.get(name)
        values = np.array([np.nan if value is None else value], dtype='<f4')
        parts.append(values)
        layout.append({"name": name, "offset": offset, "length": 1})
        offset += 1
    for name in ARRAY_FIELDS:
        values = np.asarray(snapshot.get(name, []), dtype='<f4').reshape(-1)
        parts.append(values)
        layout.append({"name": name, "offset": offset, "length": len(values)})
        offset += len(values)
    payload = np.concatenate(parts)
    header = np.array([FRAME_SCHEMA, snapshot.get('t_sim_ms', 0.), snapshot.get('dt_ms', .1),
                       snapshot.get('rtf', snapshot.get('real_time_factor', np.nan)), frame_counter, len(payload)], dtype='<f4')
    return header.tobytes() + payload.tobytes(), layout


@dataclass
class Command:
    name: str
    args: tuple
    result: Future


class EngineWorker:
    """One writer; HTTP/WebSocket handlers only read published immutable copies."""
    def __init__(self, root, *, seed=7, runtime_factory=None, autostart=True):
        self.root, self.seed = Path(root), seed
        self.runtime_factory = runtime_factory
        self.autostart = autostart
        self.commands = queue.Queue(maxsize=256)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.latest = {"status": "starting", "t_sim_ms": 0., "paused": not autostart,
                       "message": "Loading the verified 13,300-neuron core"}
        self.static = {}
        self.thread = threading.Thread(target=self._run, name='flybrain-engine', daemon=True)
        self.sequence = 0

    def start(self):
        self.thread.start()
        return self

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.latest)

    def metadata(self):
        with self.lock:
            return copy.deepcopy(self.static)

    def submit(self, name, *args):
        future = Future()
        if self.stop_event.is_set() or self.snapshot().get('status') == 'error':
            future.set_exception(RuntimeError(self.snapshot().get('error', 'Engine stopped')))
            return future
        try:
            self.commands.put_nowait(Command(name, args, future))
        except queue.Full:
            future.set_exception(RuntimeError('Engine command queue is full'))
        return future

    def _publish(self, runtime, *, paused, rtf):
        snapshot = runtime.snapshot()
        if hasattr(self, 'atlas_sample_indices'):
            selected = self.atlas_sample_indices
            snapshot['atlas_rates_hz'] = runtime.rates_hz[selected].tolist()
            snapshot['atlas_voltage_mV'] = runtime.engine.v[selected].tolist()
        if hasattr(runtime, 'plasticity'):
            snapshot['total_absolute_weight_change'] = runtime.plasticity.total_absolute_weight_change
        snapshot.update({"paused": paused, "real_time_factor": rtf, "status": "paused" if paused else "running"})
        self.sequence += 1
        snapshot['sample_sequence'] = self.sequence
        with self.lock:
            self.latest = copy.deepcopy(snapshot)

    def _metadata(self, runtime):
        metadata = runtime.metadata()
        if not hasattr(runtime, 'rates_hz'):
            return metadata
        count = len(runtime.rates_hz)
        self.atlas_sample_indices = np.linspace(0, count-1, min(1200, count), dtype=np.int32)
        metadata['atlas']['sample_indices'] = self.atlas_sample_indices.tolist()
        metadata['atlas']['sample_policy'] = '1200 fixed evenly spaced core indices; unsampled activity remains unknown'
        metadata['forgetting'] = {'tau_forget_ms': runtime.plasticity.parameters.tau_forget_ms,
                                  'beta': runtime.plasticity.parameters.beta, 'provenance': 'ASSUMPTION'}
        from scipy.spatial import ConvexHull, QhullError
        positions = runtime.neurons[['soma_x', 'soma_y']].to_numpy(float)
        valid = np.isfinite(positions).all(axis=1)
        hulls = []
        for k, name in enumerate(runtime.mapping.names):
            points = positions[valid & runtime.mapping.membership[k, runtime.core.model_indices]]
            points = np.unique(points, axis=0)
            if len(points) < 3:
                continue
            try:
                hull = ConvexHull(points)
            except QhullError:
                continue
            hulls.append({'compartment': name, 'xy': points[hull.vertices].tolist()})
        metadata['atlas']['schematic_hulls'] = hulls
        metadata['atlas']['hull_scope'] = 'Convex extents of assigned neurons with released soma coordinates; schematic membership, not anatomical volume or release geometry'
        return metadata

    @staticmethod
    def _advance(runtime, runner, scheduled, duration_ms):
        """Manual steps and free running use identical simulation-time boundaries."""
        target = runtime.t_sim_ms + duration_ms
        while True:
            while scheduled and scheduled[0][0] <= runtime.t_sim_ms:
                _, key, value = scheduled.pop(0)
                runtime.control(key, value)
            if runtime.t_sim_ms >= target:
                return
            end = min(target, scheduled[0][0]) if scheduled else target
            span = int(end-runtime.t_sim_ms)
            if runner is not None and not runner.done:
                runner.advance(span)
            else:
                runtime.advance(span)

    def _weights(self, runtime, options):
        compartment = str(options.get('compartment', 'all'))
        cell_type = str(options.get('kc_type', 'all'))
        offset, limit = int(options.get('offset', 0)), int(options.get('limit', 200))
        names = list(runtime.mapping.names[:15])
        if offset < 0 or not 1 <= limit <= 2000 or (compartment != 'all' and compartment not in names) or (cell_type != 'all' and cell_type not in runtime.kc_types):
            raise ValueError('Weight query needs a valid MB compartment/KC subtype, nonnegative offset and 1–2000 edges')
        kernel = runtime.plasticity
        pres = runtime.kc_indices[kernel.pre_index]
        selected = np.ones(len(pres), bool)
        if compartment != 'all': selected &= kernel.compartment_index == names.index(compartment)
        if cell_type != 'all': selected &= runtime.cells[pres] == cell_type
        indices = np.flatnonzero(selected)
        chosen = indices[offset:offset+limit]
        posts = runtime.engine.csc_indices[runtime.plastic_csc[chosen]]
        rows = []
        for edge, post in zip(chosen, posts, strict=True):
            pre = pres[edge]
            baseline, weight = float(kernel.w0[edge]), float(kernel.weights[edge])
            rows.append({'edge_index': int(edge), 'pre_root_id': str(runtime.neurons.iloc[pre].root_id),
                         'post_root_id': str(runtime.neurons.iloc[post].root_id), 'kc_type': str(runtime.cells[pre]),
                         'mbon_type': str(runtime.cells[post]), 'compartment': names[kernel.compartment_index[edge]],
                         'baseline': baseline, 'weight': weight, 'change': weight-baseline,
                         'relative': weight/baseline if baseline else None})
        return {'t_sim_ms': runtime.t_sim_ms, 'config_hash': runtime.config_hash, 'matching_edges': len(indices),
                'offset': offset, 'returned_edges': len(rows), 'limit': limit, 'rows': rows,
                'weight_unit': 'synapse-count equivalent; actual indexed core KC→MBON edges'}

    def _export_session(self, runtime, path=None, *, reason='download'):
        """Seal a replayable endpoint before any interactive reset closes its files."""
        session = getattr(runtime, 'session_dir', None)
        if session is not None:
            blocks = []
            duration = int(runtime.t_sim_ms)
            for event in runtime.events:
                if event['control_id'] in {'pause', 'step', 'reset'}:
                    continue  # Transport actions do not change the model state.
                blocks.append({'kind': 'control', 't_ms': int(event['t_sim_ms']), 'dur_ms': 0,
                               'control_id': event['control_id'], 'value': event['value']})
            if duration:
                blocks.append({'kind': 'rest', 't_ms': 0, 'dur_ms': duration})
            executable_duration = max([duration]+[b['t_ms']+b['dur_ms'] for b in blocks])
            document = {'name': 'recorded_interactive_controls', 'seed': runtime.seed,
                        'recorded_duration_ms': duration, 'executable_duration_ms': executable_duration,
                        'replay_authority': 'events.jsonl plus session.yaml preserve the exact endpoint and event order',
                        'blocks': blocks}
            # Preserve a supplied experimental design separately; this file also
            # captures live controls added during its execution.
            protocol = session/'protocol.yaml'
            if protocol.exists() and not (session/'requested_protocol.yaml').exists():
                (session/'requested_protocol.yaml').write_text(protocol.read_text())
            protocol.write_text(yaml.safe_dump(document, sort_keys=False))
        destination = session.with_suffix('.zip') if session else (path if path is not None else self.root/'runs/session.zip')
        archive = Path(runtime.export(destination))
        if session is not None:
            record = {'id': session.name, 'archive': str(archive.relative_to(self.root)),
                      'duration_ms': runtime.t_sim_ms, 'seed': runtime.seed,
                      'config_hash': runtime.config_hash, 'reason': reason}
            index = self.root/'runs/neuromod/session_index.json'
            previous = json.loads(index.read_text()) if index.exists() else []
            previous = [x for x in previous if x['id'] != record['id']]+[record]
            temporary = index.with_suffix('.tmp')
            temporary.write_text(json.dumps(previous, indent=2))
            temporary.replace(index)
        return archive

    def _seal_before_reset(self, runtime, reason):
        if runtime.t_sim_ms > 0 or getattr(runtime, 'events', []):
            self._export_session(runtime, reason=reason)

    def _raster(self, runtime, options):
        """Read only a bounded actual spike window while this thread owns files."""
        duration = float(options.get('duration_ms', 1000.))
        end = float(options.get('end_ms', runtime.t_sim_ms))
        limit = int(options.get('max_points', 20000))
        if not np.isfinite(duration) or not 0 < duration <= 5000 or not np.isfinite(end) or not 0 <= end <= runtime.t_sim_ms or not 1 <= limit <= 20000:
            raise ValueError('Raster window must be 0–5000 ms within recorded time and 1–20000 points')
        cell_type = str(options.get('cell_type', 'all'))
        if cell_type != 'all' and cell_type not in runtime.kc_types:
            raise ValueError('Raster drilldown requires an actual KC subtype')
        selected = runtime.kc_indices if cell_type == 'all' else np.flatnonzero(runtime.cells == cell_type)
        start = max(0., end-duration)
        for handle in runtime._spike_files:
            handle.flush()
        step_path, index_path = runtime.session_dir/'spike_steps.i64', runtime.session_dir/'spike_indices.i32'
        steps_count, index_count = step_path.stat().st_size//8, index_path.stat().st_size//4
        if steps_count != index_count:
            raise RuntimeError('Recorded spike indices and steps have different lengths')
        indices, times = np.empty(0, np.int32), np.empty(0, float)
        total = 0
        if steps_count:
            steps = np.memmap(step_path, mode='r', dtype=np.int64)
            spike_indices = np.memmap(index_path, mode='r', dtype=np.int32)
            lo, hi = np.searchsorted(steps, [start/runtime.engine.dt, end/runtime.engine.dt], side='left')
            selected_mask = np.zeros(len(runtime.neurons), bool)
            selected_mask[selected] = True
            matches = np.flatnonzero(selected_mask[spike_indices[lo:hi]])
            total = len(matches)
            kept = matches[-limit:]+lo
            indices = np.asarray(spike_indices[kept]).copy()
            times = np.asarray(steps[kept], float)*runtime.engine.dt
            del steps, spike_indices
        return {'source': 'actual recorded core spike log', 'cell_type': cell_type,
                'window_start_ms': start, 'window_end_ms': end, 'neuron_indices': selected.tolist(),
                'root_ids': [str(x) for x in runtime.neurons.iloc[selected].root_id],
                'spike_indices': indices.tolist(), 'spike_times_ms': times.tolist(),
                'matching_spikes': total, 'retained_spikes': len(indices), 'omitted_spikes': total-len(indices),
                'selection': 'most recent points when capped; no synthetic points or interpolation',
                'config_hash': runtime.config_hash}

    def _run(self):
        runtime = None
        try:
            if self.runtime_factory is None:
                from .engine_rt import CoreRuntime
                factory = CoreRuntime
            else:
                factory = self.runtime_factory
            runtime = factory(self.root, seed=self.seed)
            runtime.warmup()
            with self.lock:
                self.static = copy.deepcopy(self._metadata(runtime))
            paused, rtf, runner = not self.autostart, None, None
            scheduled = []
            last_print = time.perf_counter()
            self._publish(runtime, paused=paused, rtf=rtf)
            while not self.stop_event.is_set():
                changed = False
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if command.result.cancelled():
                        continue
                    try:
                        if command.name == 'control':
                            control_id, value = command.args
                            if control_id == 'dan.pulse':
                                duration = value.get('duration_ms', 500)
                                if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not np.isfinite(duration) or duration != int(duration) or duration <= 0 or duration > 60000:
                                    raise ValueError('Pulse duration must be 1–60000 simulation ms')
                                duration = int(duration)
                                runtime.control('dan_drive', value.get('drive', 1.))
                                scheduled[:] = [event for event in scheduled if event[1] != 'dan_drive']
                                scheduled.append((runtime.t_sim_ms+duration, 'dan_drive', 0.))
                                scheduled.sort()
                                outcome = {'ends_at_ms': runtime.t_sim_ms+duration}
                                changed = True
                                if not command.result.cancelled(): command.result.set_result(outcome)
                                continue
                            # Transport actions are logged through the engine too.
                            if control_id == 'reset':
                                self._seal_before_reset(runtime, 'interactive reset')
                                runtime.reset(int(value))
                                runner = None
                                scheduled.clear()
                            outcome = runtime.control(control_id, value)
                            if control_id == 'pause':
                                paused = bool(value)
                            if control_id == 'step':
                                paused = True
                                self._advance(runtime, runner, scheduled, 1)
                            changed = True
                        elif command.name == 'protocol':
                            from .protocol import ProtocolRunner, compile_protocol
                            compile_protocol(command.args[0])  # Reject invalid YAML before sealing/resetting.
                            self._seal_before_reset(runtime, 'protocol replacement')
                            runner = ProtocolRunner(runtime, command.args[0])
                            scheduled.clear()
                            paused = False
                            outcome = {"loaded": True}
                            changed = True
                        elif command.name == 'export':
                            outcome = self._export_session(runtime, *command.args)
                        elif command.name == 'raster':
                            outcome = self._raster(runtime, command.args[0])
                        elif command.name == 'weights':
                            outcome = self._weights(runtime, command.args[0])
                        else:
                            raise ValueError('Unknown bridge command')
                        if not command.result.cancelled(): command.result.set_result(outcome)
                    except Exception as exc:
                        if not command.result.cancelled(): command.result.set_exception(exc)
                if paused:
                    if changed:
                        self._publish(runtime, paused=True, rtf=rtf)
                    self.stop_event.wait(.01)
                    continue
                started = time.perf_counter()
                step_ms = 20
                self._advance(runtime, runner, scheduled, step_ms)
                elapsed = time.perf_counter()-started
                rtf = step_ms/1000/elapsed if elapsed > 0 else None
                self._publish(runtime, paused=False, rtf=rtf)
                if time.perf_counter()-last_print >= 5:
                    print(f"flybrain core t={runtime.t_sim_ms/1000:.3f}s measured={runtime.snapshot()['rtf']:.3f}x real time", flush=True)
                    last_print = time.perf_counter()
                # Fixed lag: no speculative frames or altered dt if work overruns.
                self.stop_event.wait(max(0., step_ms/1000-elapsed))
        except Exception as exc:
            with self.lock:
                self.latest = self.latest | {"status": "error", "paused": True,
                                            "error": f"{type(exc).__name__}: {exc}"}
            while True:
                try:
                    command = self.commands.get_nowait()
                except queue.Empty:
                    break
                if not command.result.cancelled(): command.result.set_exception(RuntimeError(self.latest['error']))
        finally:
            if runtime is not None:
                runtime.close()

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=5.)


def _evidence(root):
    """Check saved provenance before displaying a saved gate as current."""
    from ..neuromod.report import _verify_artifacts, _propagate_dependency_status
    from ..report import _current_result
    build = Path(root)/'build'
    def read(name, default):
        path = build/name
        return json.loads(path.read_text()) if path.exists() else default
    manifest = read('downloads.json', {}).get('files', {})
    failures, errors = read('integrity_failures.json', {}), read('stage_errors.json', [])
    records = {}
    for path in sorted((Path(root)/'build').glob('validation_neuromod*.json')):
        try:
            data = json.loads(path.read_text())
            entries = data if isinstance(data, list) else data.get('gates', [data])
            for entry in entries:
                record = _verify_artifacts(_current_result(entry, Path(root), manifest, failures, errors, []), Path(root))
                records[record.get('gate', path.name)] = (record, path.name)
        except (OSError, ValueError, KeyError):
            continue
    _propagate_dependency_status(records)
    reference = Path(root)/'build/validation_neuromod_plasticity.json'
    fixture = json.loads(reference.read_text()) if reference.exists() else None
    variant_path = build/'validation_hybrid_variant.json'
    variant = None
    if variant_path.exists():
        entry = json.loads(variant_path.read_text())
        variant = _verify_artifacts(_current_result(entry, Path(root), manifest, failures, errors, []), Path(root))
        # Nested run artifacts inherit the verified parent's source/code/config
        # status; they may never retain PASS under a stale parent.
        for run in variant.get('defaults', []):
            issues = []
            from ..fetch import checksum
            for name, digest in run.get('artifact_hashes', {}).items():
                if not (build/name).exists() or checksum(build/name) != digest:
                    issues.append('Variant run artifact changed: '+name)
            if issues:
                variant['status'] = 'NOT-RUN'
                variant.setdefault('stale_evidence_reasons', []).extend(issues)
    field_reference = None
    field_path = build/'neuromod_field_references.json'
    config_path = Path(root)/'config/neuromod.yaml'
    if records.get('V-NM-D', ({},))[0].get('status') == 'PASS' and field_path.exists() and config_path.exists():
        field_reference = json.loads(field_path.read_text())
        parameters = yaml.safe_load(config_path.read_text())['parameters']
        for row in field_reference['fixtures']:
            row['tau_clear_ms'] = parameters['tau_clear_ms_'+row['species']]['value']
            row['source_gain'] = parameters['source_gain_'+row['species']]['value']
    return {"gates": [v[0] for v in records.values()], "reference": fixture,
            "field_reference": field_reference, "stability_variant": variant}


def create_app(root, *, seed=7, runtime_factory=None, autostart=True):
    from aiohttp import web
    root = Path(root).resolve()
    @web.middleware
    async def same_origin(request, handler):
        if request.path.startswith('/api/') or request.path == '/ws':
            origin = request.headers.get('Origin')
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in {'http', 'https'} or parsed.netloc != request.host or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}:
                    raise web.HTTPForbidden(text='Only same-origin localhost requests are accepted')
        return await handler(request)
    app = web.Application(client_max_size=8*1024*1024, middlewares=[same_origin])
    worker = EngineWorker(root, seed=seed, runtime_factory=runtime_factory, autostart=autostart)
    evidence = None

    async def startup(app):
        nonlocal evidence
        evidence = await asyncio.to_thread(_evidence, root)
        worker.start()

    async def cleanup(app):
        await asyncio.to_thread(worker.close)

    async def asset(request):
        name = request.match_info.get('name', 'console.html')
        if name not in {'console.html', 'console.js', 'console.css'}:
            raise web.HTTPNotFound()
        return web.FileResponse(root/'console'/name)

    async def status(request):
        return web.json_response(worker.snapshot())

    async def metadata(request):
        return web.json_response(worker.metadata())

    async def evidence_route(request):
        return web.json_response(await asyncio.to_thread(_evidence, root))

    async def archives(request):
        index = root/'runs/neuromod/session_index.json'
        records = json.loads(index.read_text()) if index.exists() else []
        return web.json_response(records)

    async def archive_download(request):
        index = root/'runs/neuromod/session_index.json'
        records = json.loads(index.read_text()) if index.exists() else []
        record = next((x for x in records if x['id'] == request.match_info['id']), None)
        if record is None: raise web.HTTPNotFound()
        destination = (root/record['archive']).resolve()
        if not destination.is_relative_to(root/'runs') or not destination.is_file(): raise web.HTTPNotFound()
        return web.FileResponse(destination, headers={'Content-Disposition': 'attachment; filename="'+destination.name+'"'})

    async def save_presentation_export(request):
        """Persist browser-measured CSV/PNG artifacts; never touches the engine."""
        try:
            body = await request.json()
            name, kind = body['filename'], body['content_type']
            if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(csv|png)', name):
                raise ValueError('Export filename must be a simple CSV or PNG name')
            if kind == 'text/csv' and name.endswith('.csv'):
                data = body['text'].encode('utf-8')
            elif kind == 'image/png' and name.endswith('.png'):
                data = base64.b64decode(body['base64'], validate=True)
                if not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    raise ValueError('PNG signature is missing')
            else:
                raise ValueError('Only CSV text and PNG figures are accepted')
            if not data or len(data) > 6*1024*1024:
                raise ValueError('Export must contain 1 byte to 6 MiB')
            directory = root/'runs/exports'
            directory.mkdir(parents=True, exist_ok=True)
            saved = directory/(str(time.time_ns())+'-'+name)
            saved.write_bytes(data)
            metadata = {'source': 'Browser-selected measured samples or rendered figure; no numerical recomputation',
                        'content_type': kind, 'bytes': len(data), 'context': body.get('context', {})}
            saved.with_suffix(saved.suffix+'.json').write_text(json.dumps(metadata, indent=2, allow_nan=False))
            return web.json_response({'filename': saved.name, 'bytes': len(data),
                                      'path': str(saved), 'url': '/api/exports/'+saved.name})
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def presentation_export(request):
        name = request.match_info['name']
        if not re.fullmatch(r'[0-9]+-[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(csv|png)', name):
            raise web.HTTPNotFound()
        path = root/'runs/exports'/name
        if not path.is_file(): raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Disposition': 'attachment; filename="'+name+'"'})

    async def raster(request):
        try:
            future = worker.submit('weights' if request.path.endswith('/weights') else 'raster', dict(request.query))
            result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=30)
            return web.json_response(result)
        except (ValueError, TypeError, RuntimeError, asyncio.TimeoutError) as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def command(request):
        try:
            body = await request.json()
            if request.path == '/api/control':
                control_id = body['control_id']
                if not isinstance(control_id, str) or len(control_id) > 120:
                    raise ValueError('Invalid control identifier')
                future = worker.submit('control', control_id, body['value'])
            else:
                if not isinstance(body['yaml'], str) or len(body['yaml'].encode('utf-8')) > 256*1024:
                    raise ValueError('Protocol YAML must be text')
                future = worker.submit('protocol', body['yaml'])
            outcome = await asyncio.wait_for(asyncio.wrap_future(future), timeout=30)
            return web.json_response({'ok': True, 'result': outcome})
        except (KeyError, ValueError, TypeError, RuntimeError, asyncio.TimeoutError) as exc:
            return web.json_response({'ok': False, 'error': str(exc)}, status=400)

    async def export(request):
        try:
            destination = root/'runs'/'live-session-export.zip'
            result = await asyncio.wait_for(asyncio.wrap_future(worker.submit('export', destination)), timeout=30)
            destination = Path(result) if isinstance(result, (str, Path)) else destination
            if destination.is_file() and destination.suffix == '.zip':
                return web.FileResponse(destination, headers={'Content-Disposition': 'attachment; filename="flybrain-session.zip"'})
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in sorted(destination.rglob('*')):
                    if path.is_file(): archive.write(path, path.relative_to(destination))
            return web.Response(body=data.getvalue(), content_type='application/zip',
                                headers={'Content-Disposition': 'attachment; filename="flybrain-session.zip"'})
        except Exception as exc:
            return web.json_response({'error': str(exc)}, status=400)

    async def socket(request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=1024)
        await ws.prepare(request)
        previous_layout, previous_sequence, counter = None, None, 0
        last_status = 0.
        last_control_signature = None
        async def receive():
            async for _ in ws:
                pass
        receiver = asyncio.create_task(receive())
        try:
            while not ws.closed:
                snapshot = worker.snapshot()
                sequence = snapshot.get('sample_sequence', -1)
                if sequence != previous_sequence:
                    payload, layout = binary_frame(snapshot, counter)
                    if layout != previous_layout:
                        await ws.send_json({'kind': 'schema', 'version': FRAME_SCHEMA,
                                            'header_floats': HEADER_FLOATS, 'layout': layout})
                        previous_layout = layout
                    signature = json.dumps({key: snapshot.get(key) for key in ('controls', 'paused', 'status', 'seed', 'config_hash')}, sort_keys=True)
                    if time.monotonic()-last_status >= .5 or signature != last_control_signature:
                        compact = {k: v for k,v in snapshot.items() if k not in ARRAY_FIELDS}
                        await ws.send_json({'kind': 'status', 'snapshot': compact})
                        last_status = time.monotonic()
                        last_control_signature = signature
                    await ws.send_bytes(payload)
                    previous_sequence = sequence
                    counter += 1
                await asyncio.sleep(1/30)
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            receiver.cancel()
            await ws.close()
        return ws

    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get('/', asset)
    app.router.add_get('/{name:console\\.(html|js|css)}', asset)
    app.router.add_get('/api/status', status)
    app.router.add_get('/api/metadata', metadata)
    app.router.add_get('/api/evidence', evidence_route)
    app.router.add_get('/api/raster', raster)
    app.router.add_get('/api/weights', raster)
    app.router.add_post('/api/exports', save_presentation_export)
    app.router.add_get('/api/exports/{name}', presentation_export)
    app.router.add_get('/api/sessions', archives)
    app.router.add_get('/api/sessions/{id}', archive_download)
    app.router.add_post('/api/control', command)
    app.router.add_post('/api/protocol', command)
    app.router.add_get('/api/session', export)
    app.router.add_get('/ws', socket)
    return app


def serve(root, *, host='127.0.0.1', port=8795, seed=7, autostart=True):
    from aiohttp import web
    if host not in {'127.0.0.1', 'localhost', '::1'}:
        raise ValueError('Console transport is restricted to localhost')
    web.run_app(create_app(root, seed=seed, autostart=autostart), host=host, port=port)
