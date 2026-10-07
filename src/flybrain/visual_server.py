"""Loopback-only local visual simulator. One bounded simulation job at a time."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote, parse_qs
from datetime import datetime, timezone
import json
import mimetypes
import re
import threading
import uuid
import numpy as np
import pandas as pd
import psutil
import time
import multiprocessing
import shutil
import queue
from contextlib import contextmanager, nullcontext

from .visual_assets import prepare_anatomy, export_visual_run
from .memguard import MemoryGuard

RUN_ID = re.compile(r"^[A-Za-z0-9_-]+$")
STATIC = Path(__file__).parent / "web"
CACHE_DIRECTORIES = ('build/visual/anatomy', 'build/visual/morphology/overview',
                     'build/visual/morphology/neurons')
ACTIVE_STATUSES = ('queued', 'running', 'preparing', 'paused', 'pause_requested', 'checkpointing', 'finalizing')
SESSION_OPTION_KEYS = frozenset({'timeline','interventions','from_checkpoint','live_chunk_ms','model_id',
    'research_selection','recording_selection','peripheral','modules','prepare_reference','reference_selection','branch_time_ms'})
REQUEST_OPTION_KEYS = frozenset({'stimulus','duration_ms','speed_deg_s','direction_deg','contrast','mean_luminance',
    'spatial_period_deg','grating_waveform','apparent_interval_ms','apparent_separation_columns','threads',
    'neural_overrides','visual_overrides','record_dt_ms','electrodes','neuromod'}) | SESSION_OPTION_KEYS


def checkpoint_request_options(options):
    """Convert trusted normalized checkpoint options back into request fields."""
    request = {key:value for key,value in options.items() if key in REQUEST_OPTION_KEYS}
    if 'electrodes' in request:
        fields = {'id','label','target','voltage_mv','frequency_hz','duty_percent','start_ms','end_ms','phase_deg'}
        request['electrodes'] = [{key:value for key,value in item.items() if key in fields}
                                 for item in request['electrodes']]
    return request


class SimulationCancelled(RuntimeError):
    pass


def clear_viewer_cache(root):
    """Remove only regenerable display directories, with all viewer writers stopped.

    The server checks its workers before calling this helper. Service managers
    may call it only after stopping their services. Raw sources, master morphology,
    eye mappings, validation evidence and every recorded run are excluded.
    """
    root=Path(root).resolve();targets=[]
    for name in CACHE_DIRECTORIES:
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root/'build/visual'):
            raise ValueError('Unsafe viewer-cache path: '+name)
        if path.exists() and not path.is_dir():
            raise ValueError('Viewer cache must be a directory: '+name)
        targets.append((name,path))
    removed=[];size=0
    for name,path in targets:
        if path.exists():
            # rglob does not traverse directory symlinks; rmtree unlinks links
            # instead of following their targets.
            size+=sum(p.lstat().st_size for p in path.rglob('*') if not p.is_dir())
            shutil.rmtree(path);removed.append(name)
    return {'status':'cleared','deleted':removed,'bytes_removed':size,
            'preserved':['data','config','validation evidence','master morphology','eye mappings','runs'],
            'cache_generation':uuid.uuid4().hex}


def _simulation_worker(root, options, memory_limit_gb, connection, commands=None):
    """A supervised child can be stopped even while native simulation code runs."""
    try:
        from .visual_experiment import run_visual_experiment
        force_frame=[False]
        def update(event):
            if event.get('kind') in ('command_result','session_status') and event.get('status')=='paused':force_frame[0]=True
            connection.send({'kind':'progress','event':event})
        last_frame = [0.]
        def frame(event):
            now = time.monotonic()
            if now - last_frame[0] >= .25 or event.get('final') or force_frame[0]:
                connection.send({'kind':'frame','event':event})
                last_frame[0] = now
                force_frame[0] = False
        def control():
            result = []
            if commands is not None:
                while True:
                    try:result.append(commands.get_nowait())
                    except queue.Empty:break
            return result
        with MemoryGuard(memory_limit_gb):
            if 'legacy_protocol' in options:
                from .legacy_protocol_session import run_legacy_protocol
                summary=run_legacy_protocol(Path(root),options['legacy_protocol'],progress=update,frame=frame,control=control)
            else:
                result=run_visual_experiment(Path(root),options,progress=update,frame=frame,control=control)
                update({'phase':'saving','message':'Preparing recorded activity for playback','progress':.97})
                summary=export_visual_run(Path(root),result)
        connection.send({'kind':'cancelled' if summary.get('partial') else 'complete','run_id':summary['id']})
    except Exception as error:
        if type(error).__name__ == 'ExperimentStopped':
            terminal={'kind':'cancelled','checkpoint_id':getattr(error,'checkpoint_id',None),'recording_id':getattr(error,'recording_id',None),'error':str(error)}
            if terminal['recording_id']:
                try:
                    from .partial_export import export_partial
                    partial=export_partial(Path(root),terminal['recording_id'],terminal['checkpoint_id'])
                    terminal['run_id']=partial['id'] if partial else None
                except Exception as recovery_error:terminal['partial_error']=str(recovery_error)
            connection.send(terminal)
        else:
            connection.send({'kind':'failed','error':f'{type(error).__name__}: {error}'})
    finally:
        connection.close()


class VisualState:
    def __init__(self, root, memory_limit_gb=40):
        self.root = Path(root).resolve()
        self.memory_limit_gb = memory_limit_gb
        self.anatomy = prepare_anatomy(self.root)
        from .model_registry import get_model_manifest
        from .inspect_data import atomic_write_json
        self.anatomy.update(model_id='flywire-783',model_hash=get_model_manifest(self.root,'flywire-783')['model_hash'])
        atomic_write_json(self.root/'build/visual/anatomy/metadata.json',self.anatomy)
        from .visual_setup import ensure_column_data
        ensure_column_data(self.root)
        self.jobs = {}
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flybrain-visual")
        self.processes = {}
        self.futures = {}
        self.commands = {}
        self.frames = {}
        self.frame_sequences = {}
        self.model_jobs = {}
        self.model_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='flybrain-models')
        self.cache_lock = threading.RLock()
        self.asset_cancel = threading.Event()
        self.cache_generation = uuid.uuid4().hex
        self.morphology_cancel = threading.Event()
        self.neurons = None
        self.wiring = None
        self.lab = None
        self.process = psutil.Process()
        self.process.cpu_percent()
        self.resource_children = {}
        self.previous_cpu_times = psutil.cpu_times()
        self.resource_sample = None
        self.resource_time = 0
        self.morphology_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='flybrain-morphology')
        self.morphology_job = None
        self.reload_draining = False
        self.active_requests = 0
        self.live_watcher = None
        self.instance_id = uuid.uuid4().hex
        self.loaded_backend_revision = None

    def _reload_busy_locked(self):
        return (any(job['status'] in ACTIVE_STATUSES for job in self.jobs.values())
                or any(job['status'] in ACTIVE_STATUSES for job in self.model_jobs.values())
                or bool(self.morphology_job and self.morphology_job['status'] in ACTIVE_STATUSES)
                or any(process.is_alive() for process in self.processes.values())
                or any(not future.done() for future in self.futures.values()))

    @contextmanager
    def request_operation(self):
        # Count rather than serialize requests: anatomy downloads can be large.
        # The same lock closes the race between admitting a run and restarting.
        with self.lock:
            if self.reload_draining:
                raise RuntimeError('Applying project changes; reconnecting shortly')
            self.active_requests += 1
        try:
            yield
        finally:
            with self.lock:
                self.active_requests -= 1

    def begin_reload(self):
        with self.lock:
            if self.active_requests or self._reload_busy_locked():
                return False
            self.reload_draining = True
            return True

    def live_reload_status(self):
        status = self.live_watcher.snapshot() if self.live_watcher else {'enabled': False}
        with self.lock:
            return {**status, 'instance_id': self.instance_id,
                    'busy': self._reload_busy_locked(),
                    'restart_pending': self.reload_draining or bool(self.live_watcher and
                        status['backend_revision'] != self.loaded_backend_revision)}

    def neuron_table(self):
        if self.neurons is None:
            self.neurons = pd.read_parquet(self.root / 'build/neurons.parquet')
        return self.neurons

    def region_neurons(self, key):
        from .neuromod.compartments import load_compartments
        from scipy import sparse
        if any(r['key'] == key and r.get('kind') == 'neuropil' for r in self.anatomy.get('regions', [])):
            from .visual_neuropils import load_neuropil_weights
            package = load_neuropil_weights(self.root)
            row = package['weights'].getrow(package['names'].index(key))
            return {'key': key, 'indices': row.indices.tolist(),
                    'definition': 'Neurons with released synapse endpoints in this neuropil; annotation anchors are not neuropil boundaries.'}
        mapping = load_compartments(self.root)
        if key not in mapping.names:
            raise ValueError('Unknown brain compartment')
        if not np.array_equal(mapping.model_root_ids, self.neuron_table().root_id.to_numpy()):
            raise ValueError('Region mapping differs from model neuron order')
        row = sparse.csr_matrix(mapping.membership).getrow(mapping.names.index(key))
        return {'key': key, 'indices': row.indices.tolist(),
                'definition': 'Assigned neurons; annotation anchors do not define a physical region boundary.'}

    def runs(self):
        records = []
        for path in sorted((self.root / "runs").glob("*/visual_summary.json"), reverse=True):
            try:
                item = json.loads(path.read_text())
                records.append({k: item[k] for k in ("id", "label", "stimulus", "frames", "stats")})
            except (OSError, ValueError, KeyError):
                continue
        return records

    def bootstrap(self):
        if self.lab is None:
            from .lab_settings import lab_configuration
            self.lab = lab_configuration(self.root, self.neuron_table())
        runs = self.runs()
        preferred = next((r["id"] for r in runs if r["stimulus"].get("type") != "dark"), runs[0]["id"] if runs else None)
        from .fetch import checksum
        asset_version='-'.join(checksum(STATIC/name)[:12] for name in ('app.js','index.html','style.css') if (STATIC/name).exists())
        return {**self.lab, "neuron_count": self.anatomy["neuron_count"], "anatomy": self.anatomy,
                "groups": self.anatomy["groups"], "runs": runs,
                "default_running":False,"simulation_scope":"complete released whole-brain model",
                "asset_version":asset_version,"cache_generation":self.cache_generation,
                "default_run_id": preferred,
                "validation": {"status": "experimental", "summary": "Experimental · stability check failed",
                    "detail": "The original hybrid model failed V-C: 39,945 clamp events in one-second dark equilibration. Visual runs continue explicitly for exploration and keep all warnings.",
                    "data_integrity": "PASS", "reference_engine": "PASS", "hybrid_stability": "FAIL",
                    "reference_rate_correlation": 0.9999959214},
                "simulation_limits": {**self.lab['simulation_limits'], "memory_limit_gb": self.memory_limit_gb}}

    @staticmethod
    def options(payload, root=None, n_neurons=138639):
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        if 'legacy_protocol' in payload:
            if set(payload)-{'legacy_protocol','model_id'} or payload.get('model_id','flywire-783')!='flywire-783':
                raise ValueError('Legacy protocols use their original verified FlyWire core and cannot be combined with a visual-session override')
            from .protocol_adapter import parse_protocol
            parsed=parse_protocol(payload['legacy_protocol'])
            return {'legacy_protocol':payload['legacy_protocol'] if isinstance(payload['legacy_protocol'],str) else parsed,'model_id':'flywire-783'}
        session_keys = SESSION_OPTION_KEYS
        allowed = REQUEST_OPTION_KEYS
        if set(payload) - allowed:
            raise ValueError(f"Unsupported options: {sorted(set(payload) - allowed)}")
        if payload.get('from_checkpoint'):
            from .experiment_session import read_checkpoint
            checkpoint=read_checkpoint(Path(root) if root else Path(__file__).resolve().parents[2],payload['from_checkpoint'])
            manifest=checkpoint[0] if isinstance(checkpoint,tuple) else checkpoint
            payload={**checkpoint_request_options(manifest.get('options',{})),**payload}
        from .stimulation import normalize_lab_options
        from .config import parameters
        from .visual_experiment import read_visual_parameters
        root = Path(root) if root else Path(__file__).resolve().parents[2]
        original={k:v for k,v in payload.items() if k!='neuromod' and k not in session_keys}
        normalized, _, _, _ = normalize_lab_options(original, parameters(root), read_visual_parameters(root), n_neurons)
        # Derived optical quantities are resolved again using the experiment's
        # saved configuration; only canonical request fields cross this boundary.
        canonical = {key: value for key, value in normalized.items() if key in allowed}
        canonical['electrodes'] = payload.get('electrodes', [])
        if 'neuromod' in payload:
            from .wholebrain_neuromod import normalize_neuromod_options
            canonical['neuromod']=normalize_neuromod_options(payload['neuromod'])
        if any(key in payload for key in session_keys):
            from .experiment_session import normalize_session_options
            canonical.update(normalize_session_options({key:payload[key] for key in session_keys if key in payload}))
        return canonical

    def start(self, payload):
        options = self.options(payload, self.root, self.anatomy['neuron_count'])
        with self.lock:
            if any(job["status"] in ACTIVE_STATUSES for job in self.jobs.values()):
                raise RuntimeError("A simulation is already running. Wait for it to finish.")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"id": job_id, "status": "queued", "progress": 0, "message": "Preparing the model", "run_id": None, "error": None, "cancel_requested": False, 'started_at': time.time(), 'model_id':options.get('model_id','flywire-783'), 'options':options}
        self.futures[job_id]=self.executor.submit(self._run, job_id, options)
        return dict(self.jobs[job_id])

    def _run(self, job_id, options):
        def update(event):
            phase = str(event.get("phase", "running"))
            progress = event.get("progress")
            if progress is None:
                start, span = {"preparing": (0.02, .08), "loading": (.02, .05), "preequilibration": (.1, .3), "paired_baseline": (.65, .3), "baseline": (.65, .3), "control": (.65, .3), "stimulus": (.4, .25), "saving": (.96, .03)}.get(phase, (.08, .03))
                fraction = event.get("simulated_ms", 0) / max(1, event.get("duration_ms", 1))
                progress = start + span * min(1, fraction)
            with self.lock:
                job = self.jobs[job_id]
                if job.get('cancel_requested'):
                    raise SimulationCancelled('Cancelled by the user')
                status = event.get('status')
                if status not in ACTIVE_STATUSES:
                    status = job['status'] if job['status'] in ('paused','pause_requested') else 'running'
                if event.get('checkpoint_id'):job['checkpoint_id']=event['checkpoint_id']
                if event.get('model_time_ms') is not None:job['model_time_ms']=event['model_time_ms']
                if event.get('kind') == 'command_result':
                    job['last_command'] = event
                    if event.get('action') == 'pause' and event.get('status') in ('paused','ok','applied'):
                        status = 'paused'
                    elif event.get('action') in ('resume','step'):
                        status = 'running'
                    if event.get('checkpoint_id'):
                        job['checkpoint_id'] = event['checkpoint_id']
                job.update(status=status, phase=phase, message=event.get("message", phase), progress=max(job["progress"], min(.99, float(progress))))
        process=None;reader=None
        try:
            update({"phase": "preparing", "message": "Loading real connectome and compound-eye mapping"})
            context=multiprocessing.get_context('spawn')
            reader,writer=context.Pipe(duplex=False)
            command_queue=context.Queue(maxsize=128)
            process=context.Process(target=_simulation_worker,args=(str(self.root),options,self.memory_limit_gb,writer,command_queue),daemon=True)
            with self.lock:
                if self.jobs[job_id].get('cancel_requested'):raise SimulationCancelled()
                self.processes[job_id]=process
                self.commands[job_id]=command_queue
                process.start()
                self.jobs[job_id]['pid']=process.pid
            writer.close();terminal=None
            while process.is_alive() or reader.poll():
                with self.lock:
                    cancelled=self.jobs[job_id].get('cancel_requested')
                if cancelled:raise SimulationCancelled()
                if reader.poll(.1):
                    try:message=reader.recv()
                    except EOFError:break
                    if message['kind']=='progress':update(message['event'])
                    elif message['kind']=='frame':
                        with self.lock:
                            seq=self.frame_sequences.get(job_id,0)+1
                            self.frame_sequences[job_id]=seq
                            self.frames[job_id]={**message['event'],'schema_version':1,'session_id':job_id,'sequence':seq}
                            self.jobs[job_id]['model_time_ms']=message['event'].get('model_time_ms')
                    else:terminal=message
            process.join(timeout=.5)
            if terminal is None:raise RuntimeError(f'Simulation process exited without finalized output (exit {process.exitcode})')
            if terminal['kind']=='failed':raise RuntimeError(terminal['error'])
            with self.lock:
                if self.jobs[job_id].get('cancel_requested'):raise SimulationCancelled()
                if terminal['kind']=='cancelled':
                    self.jobs[job_id].update(status='cancelled',message='Stopped with a recoverable checkpoint' if terminal.get('checkpoint_id') else 'Stopped; committed raw recording preserved',checkpoint_id=terminal.get('checkpoint_id'),recording_id=terminal.get('recording_id'),run_id=terminal.get('run_id'),partial_error=terminal.get('partial_error'))
                else:
                    self.jobs[job_id].update(status="complete",progress=1,message="Recorded simulation ready",run_id=terminal['run_id'])
        except SimulationCancelled:
            with self.lock:
                self.jobs[job_id].update(status='cancelled', message='Simulation cancelled; saved runs are preserved')
        except Exception as error:
            with self.lock:
                self.jobs[job_id].update(status="failed", message="Simulation stopped", error=f"{type(error).__name__}: {error}")
        finally:
            if process is not None:
                self._stop_process(process)
            if reader is not None:reader.close()
            with self.lock:
                if hasattr(self,'processes'):self.processes.pop(job_id,None)
                commands=getattr(self,'commands',{}).pop(job_id,None)
                if commands is not None:commands.close()

    def command(self, job_id, payload):
        if not isinstance(payload,dict) or payload.get('action') not in ('pause','resume','step','stop','checkpoint'):
            raise ValueError('Choose pause, resume, step, stop, or checkpoint')
        command={**payload,'request_id':payload.get('request_id',uuid.uuid4().hex)}
        with self.lock:
            job=self.jobs.get(job_id)
            if job is None:raise ValueError('Unknown simulation session')
            if job['status'] not in ACTIVE_STATUSES:raise RuntimeError('Session is no longer active')
            channel=self.commands.get(job_id)
            if channel is None:raise RuntimeError('Session is preparing; controls will be ready shortly')
            if command['action']=='pause':job['status']='pause_requested'
            if command['action']=='stop':job['message']='Saving recoverable state and stopping'
            try:channel.put_nowait(command)
            except queue.Full:raise RuntimeError('Session command queue is full; wait for acknowledgement')
        return {'status':'accepted','session_id':job_id,'request_id':command['request_id'],'action':command['action']}

    def start_model_job(self, action):
        if action not in ('acquire_banc','compile_fused'):raise ValueError('Unknown model operation')
        with self.lock:
            if any(item['status'] in ACTIVE_STATUSES for item in self.model_jobs.values()):
                raise RuntimeError('A model preparation is already active')
            job_id=uuid.uuid4().hex
            self.model_jobs[job_id]={'id':job_id,'status':'queued','action':action}
        def run():
            def progress(event):
                with self.lock:self.model_jobs[job_id].update(status='running',event=event)
            try:
                from .model_registry import acquire_banc,compile_fused_model
                result=acquire_banc(self.root,progress=progress) if action=='acquire_banc' else compile_fused_model(self.root)
                from .workbench_api import json_safe
                with self.lock:self.model_jobs[job_id].update(status='complete',result=json_safe(result))
            except Exception as error:
                with self.lock:self.model_jobs[job_id].update(status='failed',error=f'{type(error).__name__}: {error}')
        self.model_executor.submit(run)
        return dict(self.model_jobs[job_id])

    @staticmethod
    def _stop_process(process, timeout=1.):
        if process.pid is None:return
        if process.is_alive():process.terminate()
        process.join(timeout=timeout)
        if process.is_alive():process.kill();process.join(timeout=timeout)

    def cancel(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError('Unknown simulation job')
            job = self.jobs[job_id]
            process=self.processes.get(job_id)
            if job['status'] in ACTIVE_STATUSES or (process is not None and process.is_alive()):
                job.update(cancel_requested=True, message='Stopping at the next simulation checkpoint')
        if process is not None:self._stop_process(process)
        with self.lock:
            if job.get('cancel_requested') and (process is None or not process.is_alive()):
                job.update(status='cancelled',message='Simulation stopped; saved runs are preserved')
            return dict(job)

    def stop_all(self):
        self.asset_cancel.set();self.morphology_cancel.set()
        with self.lock:
            ids=[key for key,job in self.jobs.items() if job['status'] in ACTIVE_STATUSES or (
                key in self.processes and self.processes[key].is_alive())]
        jobs=[self.cancel(key) for key in ids]
        active=sum(job['status'] in ACTIVE_STATUSES for job in jobs)
        morphology_active=bool(self.morphology_job and self.morphology_job['status'] in ACTIVE_STATUSES)
        return {'status':'stopping' if active or morphology_active else 'stopped','jobs':jobs,'active_jobs':active,
                'morphology_status':self.morphology_job,'preparation_stopping':morphology_active,
                'scope':'all simulations managed by this whole-brain visualizer','recordings_preserved':True}

    @contextmanager
    def cache_operation(self):
        with self.cache_lock:
            yield

    def clear_cache(self):
        if not self.cache_lock.acquire(blocking=False):
            raise RuntimeError('Viewer assets are in use; stop preparation and retry')
        try:
            with self.lock:
                if any(job['status'] in ACTIVE_STATUSES for job in self.jobs.values()) or any(
                    process.is_alive() for process in getattr(self,'processes',{}).values()) or (
                    self.morphology_job and self.morphology_job['status'] in ACTIVE_STATUSES):
                    raise RuntimeError('Stop simulations and morphology preparation before clearing cache')
                result=clear_viewer_cache(self.root)
                self.cache_generation=result['cache_generation']
                self.anatomy=prepare_anatomy(self.root)
                self.neurons=None;self.wiring=None;self.lab=None
                self.asset_cancel.clear()
            return {**result,'regenerated':['build/visual/anatomy']}
        finally:self.cache_lock.release()

    def resources(self):
        with self.lock:
            now = time.monotonic()
            if self.resource_sample is None or now - self.resource_time >= .5:
                memory = psutil.virtual_memory()
                current = psutil.cpu_times()
                total_delta = sum(current) - sum(self.previous_cpu_times)
                idle_delta = current.idle - self.previous_cpu_times.idle
                idle_delta += getattr(current, 'iowait', 0) - getattr(self.previous_cpu_times, 'iowait', 0)
                cpu_percent = max(0, min(100, 100 * (1 - idle_delta / total_delta))) if total_delta > 0 else 0
                self.previous_cpu_times = current
                process_cpu=self.process.cpu_percent()
                process_rss=self.process.memory_info().rss
                # Keep psutil instances between samples: newly constructed child
                # instances report zero CPU on their first nonblocking sample.
                previous_children=getattr(self,'resource_children',{})
                children={}
                for current_child in self.process.children(recursive=True):
                    try:
                        previous=previous_children.get(current_child.pid)
                        child=previous if previous is not None and previous.is_running() else current_child
                        process_cpu+=child.cpu_percent()
                        process_rss+=child.memory_info().rss
                        children[child.pid]=child
                    except (psutil.NoSuchProcess,psutil.AccessDenied):
                        continue
                self.resource_children=children
                self.resource_sample = {'cpu_percent': cpu_percent, 'process_cpu_percent': process_cpu,
                    'rss_gb': process_rss / 1e9, 'process_scope':'viewer server and all worker descendants',
                    'worker_process_count':len(children),'memory_total_gb': memory.total / 1e9,
                    'memory_available_gb': memory.available / 1e9, 'memory_used_gb': (memory.total-memory.available)/1e9,
                    'logical_cpus': psutil.cpu_count(), 'physical_cpus': psutil.cpu_count(logical=False),
                    'memory_limit_gb': self.memory_limit_gb, 'sampled_at': time.time()}
                self.resource_time = now
            return {**self.resource_sample, 'active_job': next((dict(j) for j in self.jobs.values() if j['status'] in ACTIVE_STATUSES), None)}

    def start_morphology(self):
        with self.lock:
            if self.morphology_job and self.morphology_job['status'] in ACTIVE_STATUSES:
                return dict(self.morphology_job)
            self.morphology_job = {'status':'queued', 'message':'Preparing real FlyWire neuron branches'}
            self.morphology_cancel.clear();self.asset_cancel.clear()
        def run():
            from .morphology import prepare_morphology
            def update(event):
                with self.lock:
                    self.morphology_job.update({**event, 'status':'running'})
            try:
                prepare_morphology(self.root, progress=update,cancel=self.morphology_cancel)
                with self.lock:
                    self.morphology_job.update(status='complete', message='Whole-brain morphology ready')
            except InterruptedError as error:
                with self.lock:self.morphology_job.update(status='cancelled',message=str(error))
            except Exception as error:
                with self.lock:
                    self.morphology_job.update(status='failed', message=str(error))
        self.morphology_executor.submit(run)
        return dict(self.morphology_job)

    def neuron(self, index):
        self.neuron_table()
        if not 0 <= index < len(self.neurons):
            raise ValueError("Neuron index is outside the released model")
        row = self.neurons.iloc[index]
        result = {"index": index, "root_id": str(int(row.root_id))}
        for name in ("cell_type", "super_class", "side", "top_nt", "mode"):
            value = row.get(name)
            result[name] = None if pd.isna(value) else str(value)
        p = row[["pos_x", "pos_y", "pos_z"]].to_numpy(dtype=float)
        result["position_um"] = (p * [.004, .004, .04]).tolist() if np.all(np.isfinite(p)) else None
        result["codex_url"] = f"https://codex.flywire.ai/app/cell_details?root_id={result['root_id']}&data_version=783"
        return result


def make_handler(state):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, fmt, *args):
            if self.path.startswith(("/api/jobs/", "/api/live-reload")):
                return
            super().log_message(fmt, *args)

        def end_headers(self):
            self.send_header('Cache-Control','no-store, max-age=0')
            self.send_header('Pragma','no-cache')
            self.send_header('Expires','0')
            super().end_headers()

        def send_head(self):
            # Ignore conditional requests so a restarted server never serves
            # stale script/style content from a previous implementation.
            for name in ('If-Modified-Since','If-None-Match'):
                if name in self.headers:del self.headers[name]
            return super().send_head()

        def send_json(self, data, status=200):
            body = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path, download_name=None):
            if not path.is_file():
                self.send_json({"error": "File unavailable"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(path.stat().st_size))
            self.send_header("Cache-Control", "no-cache")
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            with path.open("rb") as f:
                for block in iter(lambda: f.read(1024 * 1024), b""):
                    self.wfile.write(block)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            exempt = path in ('/api/health', '/api/live-reload') or path.startswith('/ws/sessions/')
            operation = getattr(state, 'request_operation', nullcontext)
            try:
                with nullcontext() if exempt else operation():
                    return self.get_response()
            except RuntimeError as error:
                return self.send_json({'error': str(error)}, 503)

        def get_response(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == '/api/live-reload':
                    return self.send_json(state.live_reload_status())
                if path in ('/', '/index.html') and getattr(state, 'live_watcher', None):
                    # Capture the version before reading HTML. An edit during page
                    # load will then be noticed on the first client poll.
                    status = json.dumps(state.live_reload_status()).replace('<', '\\u003c')
                    html = (STATIC / 'index.html').read_text()
                    html = html.replace('<head>', '<head><script>window.__COGNESIA_LIVE_RELOAD__=' + status + ';</script>', 1)
                    body = html.encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path.startswith('/ws/sessions/'):
                    from .session_stream import serve_stream
                    return serve_stream(self,state,path.rsplit('/',1)[-1])
                if path.startswith('/api/workspace-sessions/'):
                    from .workspace_sessions import session_archive_path
                    parts=path.split('/')
                    if len(parts)!=5 or parts[4]!='download':
                        raise ValueError('Invalid saved-session path')
                    archive=session_archive_path(state.root,parts[3])
                    return self.send_file(archive,archive.name)
                if path == '/api/checkpoints':
                    from .workbench_api import checkpoint_catalog
                    return self.send_json({'checkpoints':checkpoint_catalog(state.root)})
                if path == '/api/models':
                    from .model_registry import catalog
                    return self.send_json(catalog(state.root))
                if path == '/api/peripheral':
                    from .peripheral import catalog
                    from .workbench_api import json_safe
                    from .workbench_api import inspection_neurons
                    query=parse_qs(urlparse(self.path).query)
                    return self.send_json(json_safe(catalog(inspection_neurons(state,query.get('model_id',['flywire-783'])[0]))))
                if path == '/api/model-eyes':
                    from .workbench_api import model_eye_map
                    query=parse_qs(urlparse(self.path).query)
                    return self.send_json(model_eye_map(state,query.get('model_id',['flywire-783'])[0]))
                if path.startswith('/api/model-anatomy/'):
                    from .model_anatomy import prepare_model_anatomy, model_anatomy_directory
                    parts=path.split('/')
                    if len(parts)!=5 or not RUN_ID.fullmatch(parts[3]) or parts[4] not in ('metadata.json','positions.bin','groups.bin','visible_indices.bin','identities.json','regions.json'):
                        raise ValueError('Invalid model anatomy path')
                    query=parse_qs(urlparse(self.path).query)
                    model_hash=query.get('model_hash',[None])[0]
                    with state.cache_operation():
                        metadata=prepare_model_anatomy(state.root,parts[3],model_hash)
                        return self.send_file(model_anatomy_directory(state.root,parts[3],metadata['model_hash'])/parts[4])
                if path.startswith('/api/models/jobs/'):
                    with state.lock:item=dict(state.model_jobs.get(path.rsplit('/',1)[-1]) or {})
                    return self.send_json(item or {'error':'Unknown model job'},200 if item else 404)
                if path.startswith('/api/models/'):
                    from .model_registry import get_model_manifest
                    return self.send_json(get_model_manifest(state.root,path.rsplit('/',1)[-1]))
                if path == '/api/sessions':
                    with state.lock:items=[dict(value) for value in state.jobs.values()]
                    return self.send_json({'sessions':items})
                if path.startswith('/api/sessions/'):
                    from .workbench_api import json_safe
                    parts=path.split('/');session_id=parts[3]
                    with state.lock:
                        job=state.jobs.get(session_id)
                        value=state.frames.get(session_id) if len(parts)==5 and parts[4]=='frame' else job
                        value=dict(value) if value is not None else None
                    return self.send_json(json_safe(value) if value is not None else {'error':'Session or frame unavailable'},200 if value is not None else 404)
                if path == "/api/health":
                    return self.send_json({"service": "flybrain-visual", "ready": True, "protocol": 2,
                                           'default_running':False})
                if path == "/api/bootstrap":
                    with state.cache_operation():return self.send_json(state.bootstrap())
                if path == '/api/resources':
                    return self.send_json(state.resources())
                if path.startswith('/api/regions/'):
                    return self.send_json(state.region_neurons(path.removeprefix('/api/regions/')))
                if path == '/api/morphology/status':
                    from .morphology import morphology_status
                    return self.send_json({**morphology_status(state.root), 'job': state.morphology_job})
                if path == '/api/morphology/overview':
                    from .morphology import build_overview
                    query = parse_qs(urlparse(self.path).query)
                    budget = int(query.get('budget', ['1000000'])[0])
                    if budget not in (100000,500000,1000000,2000000,5000000):
                        raise ValueError('Choose an advertised morphology segment budget')
                    with state.cache_operation():
                        return self.send_json(build_overview(state.root, segment_budget=budget,cancel=state.asset_cancel))
                if path.startswith('/api/morphology/assets/'):
                    directory = (state.root / 'build/visual/morphology').resolve()
                    asset = (directory / path.removeprefix('/api/morphology/assets/')).resolve()
                    if not asset.is_relative_to(directory) or asset.suffix not in ('.bin','.json'):
                        raise ValueError('Invalid morphology asset')
                    with state.cache_operation():return self.send_file(asset)
                if path.startswith('/api/morphology/'):
                    from .morphology import morphology_neuron
                    with state.cache_operation():return self.send_json(morphology_neuron(state.root, int(path.rsplit('/',1)[-1])))
                if path == "/api/runs":
                    return self.send_json({"runs": state.runs()})
                if path.startswith("/api/anatomy/"):
                    name = path.rsplit("/", 1)[-1]
                    if name not in {"positions.bin", "groups.bin", "visible_indices.bin", "metadata.json"}:
                        return self.send_json({"error": "Unknown anatomy asset"}, 404)
                    with state.cache_operation():return self.send_file(state.root / "build/visual/anatomy" / name)
                if path.startswith("/api/jobs/"):
                    with state.lock:
                        job = dict(state.jobs.get(path.rsplit("/", 1)[-1]) or {})
                    return self.send_json(job or {"error": "Unknown job"}, 200 if job else 404)
                if path.startswith("/api/neuron/"):
                    from .workbench_api import inspect_neuron
                    query=parse_qs(urlparse(self.path).query)
                    return self.send_json(inspect_neuron(state,int(path.rsplit('/',1)[-1]),query.get('model_id',['flywire-783'])[0],query.get('run_id',[None])[0]))
                if path.startswith("/api/runs/"):
                    parts = path.split("/")
                    if len(parts)==6 and RUN_ID.fullmatch(parts[3]) and parts[4]=='anatomy' and parts[5] in ('metadata.json','positions.bin','groups.bin','visible_indices.bin','identities.json','regions.json'):
                        return self.send_file(state.root/'runs'/parts[3]/'anatomy'/parts[5])
                    if len(parts) != 5 or not RUN_ID.fullmatch(parts[3]):
                        return self.send_json({"error": "Invalid run path"}, 400)
                    names={'summary.json':'visual_summary.json',**{name:name for name in (
                        'delta.bin','raw.bin','baseline.bin','stimulus.bin','eye_luminance.bin',
                        'chemistry.bin','chemistry_baseline.bin','chemistry_state.bin','chemistry_hormones.bin',
                        'chemistry_baseline_state.bin','chemistry_baseline_hormones.bin','chemistry_plasticity.bin','chemistry_baseline_plasticity.bin',
                        'enzyme_pools.bin','enzyme_baseline_pools.bin','enzyme_flux.bin','enzyme_baseline_flux.bin',
                        'chemistry_membership_indptr.bin','chemistry_membership_indices.bin','chemistry_membership_weights.bin')}}
                    name = names.get(parts[4])
                    if name is None:
                        return self.send_json({"error": "Unknown run asset"}, 404)
                    return self.send_file(state.root / "runs" / parts[3] / name)
                if path.startswith("/api/"):
                    return self.send_json({"error": "Unknown API endpoint"}, 404)
                if ".." in Path(path).parts:
                    return self.send_json({"error": "Invalid path"}, 400)
                return super().do_GET()
            except (ValueError, KeyError) as error:
                return self.send_json({"error": str(error)}, 400)
            except (BrokenPipeError, ConnectionResetError):
                return
            except OSError as error:
                return self.send_json({'error': f'Requested source data unavailable: {error}'}, 503)

        def do_POST(self):
            operation = getattr(state, 'request_operation', nullcontext)
            try:
                with operation():
                    return self.post_response()
            except RuntimeError as error:
                return self.send_json({'error': str(error)}, 503)

        def post_response(self):
            origin = self.headers.get("Origin")
            if origin and origin not in {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}:
                return self.send_json({"error": "Cross-origin requests are not allowed"}, 403)
            path = urlparse(self.path).path
            if path in ('/api/workspace-sessions','/api/analysis/interval','/api/connectivity','/api/protocols/import','/api/models/acquire-banc','/api/models/compile-fused','/api/selection/preview') or path == '/api/sessions' or path.startswith('/api/sessions/') or path.startswith('/api/checkpoints/'):
                try:
                    size=int(self.headers.get('Content-Length',0))
                    maximum=32*1024*1024 if path=='/api/analysis/interval' else 1024*1024
                    if not 0<size<=maximum:raise ValueError(f'Request body must be between 1 and {maximum} bytes')
                    payload=json.loads(self.rfile.read(size))
                    if path=='/api/workspace-sessions':
                        from .workspace_sessions import save_workspace_session
                        return self.send_json(save_workspace_session(state.root,payload),201)
                    if path=='/api/analysis/interval':
                        from .workbench_api import interval_analysis
                        return self.send_json(interval_analysis(payload))
                    if path=='/api/connectivity':
                        from .workbench_api import connectivity
                        return self.send_json(connectivity(state,payload))
                    if path=='/api/protocols/import':
                        from .protocol_adapter import import_protocol
                        from .workbench_api import inspection_neurons,json_safe
                        model_id=payload.get('model_id','flywire-783')
                        imported=import_protocol(payload.get('document'),neurons=inspection_neurons(state,model_id),
                            model_id=model_id,root=state.root,duration_ms=payload.get('duration_ms'),dt_ms=payload.get('dt_ms',.1))
                        return self.send_json(json_safe(imported))
                    if path in ('/api/models/acquire-banc','/api/models/compile-fused'):
                        return self.send_json(state.start_model_job('acquire_banc' if path.endswith('acquire-banc') else 'compile_fused'),202)
                    if path=='/api/selection/preview':
                        from .workbench_api import preview_experiment,json_safe
                        return self.send_json(json_safe(preview_experiment(state,payload)))
                    if path=='/api/sessions':return self.send_json(state.start(payload),202)
                    parts=path.split('/')
                    if len(parts)==5 and parts[2]=='sessions' and parts[4]=='commands':
                        return self.send_json(state.command(parts[3],payload),202)
                    if len(parts)==5 and parts[2]=='sessions' and parts[4]=='checkpoints':
                        return self.send_json(state.command(parts[3],{**payload,'action':'checkpoint'}),202)
                    if len(parts)==5 and parts[2]=='checkpoints' and parts[4]=='branches':
                        from .experiment_session import read_checkpoint
                        checkpoint=read_checkpoint(state.root,parts[3])
                        manifest=checkpoint[0] if isinstance(checkpoint,tuple) else checkpoint
                        context=checkpoint[1]['context'] if isinstance(checkpoint,tuple) else {}
                        inherited={key:value for key,value in context.get('session_options',{}).items() if key in ('model_id','modules','research_selection','recording_selection')}
                        canonical=checkpoint_request_options(manifest.get('options',{}))
                        return self.send_json({'from_checkpoint':parts[3],'options':{**canonical,**inherited,**payload,'from_checkpoint':parts[3]},
                                               'parent_protocol':context.get('session_options',{}).get('timeline'),
                                               'parent_interventions':context.get('resolved_interventions',[]),
                                               'parent_input_origin_ms':context.get('input_origin_ms',0.),
                                               'status':'draft','message':'Branch prepared. Run it from Simulate.'})
                    return self.send_json({'error':'Unknown session action'},404)
                except RuntimeError as error:return self.send_json({'error':str(error)},409)
                except (ValueError,TypeError,KeyError,OSError) as error:return self.send_json({'error':str(error)},400)
            if path in ('/api/stop-all','/api/cache/clear'):
                try:
                    value=state.stop_all() if path=='/api/stop-all' else state.clear_cache()
                    return self.send_json(value,202 if value['status']=='stopping' else 200)
                except RuntimeError as error:
                    return self.send_json({'error':str(error)},409)
                except (ValueError,OSError) as error:
                    return self.send_json({'error':str(error)},400)
            if path == '/api/morphology/prepare':
                return self.send_json(state.start_morphology(), 202)
            if path.startswith('/api/jobs/') and path.endswith('/cancel'):
                try:
                    return self.send_json(state.cancel(path.split('/')[3]))
                except ValueError as error:
                    return self.send_json({'error': str(error)}, 404)
            if path != "/api/simulate":
                return self.send_json({"error": "Unknown action"}, 404)
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 131072:
                    raise ValueError("Request body must be between 1 and 131072 bytes")
                payload = json.loads(self.rfile.read(size))
                return self.send_json(state.start(payload), 202)
            except RuntimeError as error:
                return self.send_json({"error": str(error)}, 409)
            except (ValueError, TypeError) as error:
                return self.send_json({"error": str(error)}, 400)
    return Handler


def serve(root, port=8794, open_browser=False, memory_limit_gb=40, watcher=None):
    state = VisualState(root, memory_limit_gb=memory_limit_gb)
    state.live_watcher = watcher
    if watcher:
        state.loaded_backend_revision = watcher.snapshot()['backend_revision']
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    stopped = threading.Event()
    restart = threading.Event()

    def watch_project():
        while not stopped.wait(.5):
            status = watcher.poll()
            if (not status['pending'] and not status['error']
                    and status['backend_revision'] != state.loaded_backend_revision
                    and state.begin_reload()):
                print('Applying cgnsa source/configuration changes; restarting idle viewer.', flush=True)
                restart.set()
                server.shutdown()
                return

    monitor = threading.Thread(target=watch_project, name='cognesia-live-reload', daemon=True) if watcher else None
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Flybrain visual simulator: {url}", flush=True)
    print("Experimental model: original stability validation remains failed. Ctrl+C stops the server.", flush=True)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    if monitor:
        monitor.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopped.set()
        if monitor:
            monitor.join(timeout=2)
        state.stop_all()
        server.server_close()
        state.executor.shutdown(wait=False, cancel_futures=True)
        state.morphology_executor.shutdown(wait=False, cancel_futures=True)
        state.model_executor.shutdown(wait=False,cancel_futures=True)
    return 75 if restart.is_set() else 0
