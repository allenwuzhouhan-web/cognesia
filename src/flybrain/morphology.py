"""Source FlyWire v783 neurites, streamed into a bounded-memory geometry store.

Skeletons are reconstructed/healed neurites, with no certified axon/dendrite
labels. Coordinates in both upstream formats are nanometres, not voxel indices.
The archive is never materialized as a pandas table or loaded wholly into RAM.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import fcntl
import hashlib
import json
import threading
import time
import urllib.request

import numpy as np
import pyarrow.parquet as pq

from .inspect_data import atomic_write_json

ARCHIVE_NAME = "sk_lod1_783_healed_ds2.parquet"
ARCHIVE_URL = f"https://zenodo.org/records/10877326/files/{ARCHIVE_NAME}?download=1"
ARCHIVE_SIZE = 5_355_543_468
ARCHIVE_MD5 = "a4c104776f33ec539ef859064c4de3df"
SKELETON_URL = "https://flyem.mrc-lmb.cam.ac.uk/flyconnectome/flywire_skeletons_783"
SOURCE_RECORD = "https://zenodo.org/records/10877326"
FORMAT_VERSION = 1
ASSET_PREFIX = "/api/morphology/assets/"
_locks = {}
_locks_guard = threading.Lock()


def _directory(root):
    return Path(root) / "build/visual/morphology"


def _roots(root):
    values = pq.read_table(Path(root) / "build/neurons.parquet", columns=["root_id"])
    return values.column(0).to_numpy().astype(np.int64, copy=False)


def _root_digest(roots):
    return hashlib.sha256(roots.astype("<i8").tobytes()).hexdigest()


def _read(path, fallback=None):
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def _provenance():
    return {"source_url": SOURCE_RECORD, "archive_url": ARCHIVE_URL,
            "archive_checksum": "md5:" + ARCHIVE_MD5, "materialization": 783,
            "coordinate_units": "um", "source_coordinate_units": "nm",
            "representation": "Source reconstructed and healed neurites; no certified axon/dendrite labels",
            "voltage_model": "One recorded membrane voltage per neuron, shared across its branches"}


def morphology_status(root):
    """Nonblocking persistent build progress and exact model-neuron coverage."""
    directory = _directory(root)
    manifest = _read(directory / "manifest.json")
    if manifest.get("status") == "ready":
        roots = _roots(root)
        if manifest.get("root_order_sha256") == _root_digest(roots):
            return manifest
        return {**_provenance(), "status": "not_prepared", "progress": 0.,
                "message": "Model neuron order changed; prepare morphology before displaying source branches",
                "requires_prepare": True, "model_neuron_count": len(roots),
                "covered_neuron_count": 0, "all_model_neurons_covered": False,
                "root_order_sha256": _root_digest(roots)}
    state = _read(directory / "status.json")
    if not state:
        state = {"status": "not_prepared", "progress": 0., "message": "Source morphology has not been prepared"}
    partial = Path(root) / "data/raw/morphology" / (ARCHIVE_NAME + ".part")
    if partial.exists():
        state.update(downloaded_bytes=partial.stat().st_size, archive_bytes=ARCHIVE_SIZE)
    parts = partial.with_suffix(".parts")
    if parts.exists():
        state.update(downloaded_bytes=sum(path.stat().st_size for path in parts.glob("*.part")), archive_bytes=ARCHIVE_SIZE)
    return {**_provenance(), **state}


def _notify(root, callback, **state):
    state = {**_provenance(), "updated_at": time.time(), **state}
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / "status.json", state)
    if callback:
        callback(state)
    return state


def _cancelled(cancel):
    if cancel is not None and (cancel() if callable(cancel) else cancel.is_set()):
        raise InterruptedError("Morphology preparation cancelled; downloaded bytes retained")


def _checksum(path, algorithm="md5"):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parallel_archive(root, partial, progress, cancel, workers=32):
    """Independent exact byte ranges; each part resumes, then the whole MD5 verifies."""
    parts = partial.with_suffix(".parts")
    parts.mkdir(parents=True, exist_ok=True)
    span = (ARCHIVE_SIZE + workers - 1) // workers
    if partial.exists() and partial.stat().st_size < ARCHIVE_SIZE:
        # Preserve the earlier serial prefix without downloading it again.
        with partial.open("rb") as stream:
            for index in range(workers):
                existing = parts / f"{index:03d}.part"
                block = stream.read(span)
                if not block:
                    break
                if not existing.exists() or existing.stat().st_size < len(block):
                    existing.write_bytes(block)
        partial.unlink()
    last = [0.]
    report_lock = threading.Lock()
    def transfer(index):
        start, end = index * span, min(ARCHIVE_SIZE, (index + 1) * span) - 1
        path = parts / f"{index:03d}.part"
        for attempt in range(8):
            _cancelled(cancel)
            have = path.stat().st_size if path.exists() else 0
            if have == end-start+1:
                return
            if have > end-start+1:
                raise ValueError("Source range part is larger than its assigned byte range")
            request = urllib.request.Request(ARCHIVE_URL, headers={"Range": f"bytes={start+have}-{end}"})
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    expected = f"bytes {start+have}-{end}/{ARCHIVE_SIZE}"
                    if response.status != 206 or response.headers.get("Content-Range") != expected:
                        raise ValueError(f"Source range mismatch: expected {expected}")
                    with path.open("ab") as stream:
                        while block := response.read(1024 * 1024):
                            _cancelled(cancel)
                            if have + len(block) > end-start+1:
                                raise ValueError("Source sent more bytes than the requested range")
                            stream.write(block)
                            have += len(block)
                            with report_lock:
                                if time.monotonic()-last[0] > 2:
                                    downloaded = sum(item.stat().st_size for item in parts.glob("*.part"))
                                    _notify(root, progress, status="downloading", progress=.35 * downloaded / ARCHIVE_SIZE,
                                            message=f"Downloading official skeleton archive ({workers} source byte ranges)",
                                            downloaded_bytes=downloaded, archive_bytes=ARCHIVE_SIZE)
                                    last[0] = time.monotonic()
                if have == end-start+1:
                    return
            except InterruptedError:
                raise
            except (OSError, TimeoutError):
                if attempt == 7:
                    raise
                time.sleep(min(2 ** attempt, 20))
        raise OSError(f"Incomplete source archive range {index}")
    if not partial.exists() or partial.stat().st_size != ARCHIVE_SIZE:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(transfer, range(workers)))
        with partial.open("wb") as stream:
            for index in range(workers):
                _cancelled(cancel)
                with (parts / f"{index:03d}.part").open("rb") as source:
                    for block in iter(lambda: source.read(8*1024*1024), b""):
                        stream.write(block)


def _download_archive(root, progress=None, cancel=None):
    directory = Path(root) / "data/raw/morphology"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ARCHIVE_NAME
    receipt = directory / (ARCHIVE_NAME + ".verified.json")
    if target.exists():
        previous = _read(receipt)
        stat = target.stat()
        if previous == {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "md5": ARCHIVE_MD5}:
            return target
        _notify(root, progress, status="verifying", progress=.36, message="Verifying source archive checksum")
        if stat.st_size == ARCHIVE_SIZE and _checksum(target) == ARCHIVE_MD5:
            atomic_write_json(receipt, {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "md5": ARCHIVE_MD5})
            return target
        raise ValueError("Existing morphology archive does not match the published checksum")
    partial = directory / (ARCHIVE_NAME + ".part")
    _parallel_archive(root, partial, progress, cancel)
    _cancelled(cancel)
    _notify(root, progress, status="verifying", progress=.36, message="Verifying source archive checksum")
    if partial.stat().st_size != ARCHIVE_SIZE or _checksum(partial) != ARCHIVE_MD5:
        raise ValueError("Downloaded morphology archive failed published MD5 verification")
    partial.replace(target)
    stat = target.stat()
    atomic_write_json(receipt, {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "md5": ARCHIVE_MD5})
    for path in partial.with_suffix(".parts").glob("*.part"):
        path.unlink()
    return target


def _model_indices(neurons, sorted_roots, order):
    locations = np.searchsorted(sorted_roots, neurons)
    valid = locations < len(sorted_roots)
    valid[valid] &= sorted_roots[locations[valid]] == neurons[valid]
    result = np.full(len(neurons), -1, dtype=np.int64)
    result[valid] = order[locations[valid]]
    return result


def _mapped(path, dtype, shape, mode="r+"):
    if np.prod(shape) == 0:
        if mode.startswith("w"):
            Path(path).touch()
        return np.empty(shape, dtype=dtype)
    return np.memmap(path, dtype=dtype, mode=mode, shape=shape)


def _import_parquet(root, source, progress=None, cancel=None, batch_size=262144):
    """Two Arrow passes, then per-neuron edge reconstruction; arbitrary row order."""
    roots = _roots(root)
    if len(np.unique(roots)) != len(roots):
        raise ValueError("Model root IDs must be unique")
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    order = np.argsort(roots)
    sorted_roots = roots[order]
    counts = np.zeros(len(roots), dtype=np.int64)
    source = Path(source)
    parquet = pq.ParquetFile(source)
    total_rows = parquet.metadata.num_rows
    seen = 0
    for batch in parquet.iter_batches(batch_size=batch_size, columns=["neuron"]):
        _cancelled(cancel)
        indices = _model_indices(batch.column(0).to_numpy(), sorted_roots, order)
        counts += np.bincount(indices[indices >= 0], minlength=len(roots))
        seen += batch.num_rows
        _notify(root, progress, status="indexing", progress=.38 + .10 * seen / max(1, total_rows),
                message="Indexing exact model-root coverage", rows_indexed=seen, source_rows=total_rows)
    offsets = np.concatenate(([0], np.cumsum(counts)))
    total = int(offsets[-1])
    if total == 0:
        raise ValueError("Source morphology contains none of the model root IDs")
    np.save(directory / "root_ids.npy", roots.astype("<i8"))
    np.save(directory / "vertex_offsets.npy", offsets.astype("<i8"))
    vertices = _mapped(directory / "vertices.bin", "<f4", (total, 3), "w+")
    radius = _mapped(directory / "radius.bin", "<f4", (total,), "w+")
    node_ids = _mapped(directory / "node_ids.tmp", "<i4", (total,), "w+")
    parent_ids = _mapped(directory / "parent_ids.tmp", "<i8", (total,), "w+")
    written = np.zeros(len(roots), dtype=np.int64)
    seen = 0
    fields = ["neuron", "node_id", "parent_id", "x", "y", "z", "radius"]
    for batch in parquet.iter_batches(batch_size=batch_size, columns=fields):
        _cancelled(cancel)
        arrays = {name: batch.column(i).to_numpy() for i, name in enumerate(fields)}
        indices = _model_indices(arrays["neuron"], sorted_roots, order)
        valid_rows = np.flatnonzero(indices >= 0)
        permutation = valid_rows[np.argsort(indices[valid_rows], kind="stable")]
        grouped = indices[permutation]
        boundaries = np.r_[0, np.flatnonzero(np.diff(grouped)) + 1, len(grouped)]
        for begin, end in zip(boundaries[:-1], boundaries[1:]):
            if begin == end:
                continue
            index = grouped[begin]
            rows = permutation[begin:end]
            start = offsets[index] + written[index]
            stop = start + len(rows)
            for component, name in enumerate(("x", "y", "z")):
                values = arrays[name][rows]
                if not np.all(np.isfinite(values)):
                    raise ValueError("Source skeleton has non-finite coordinates")
                vertices[start:stop, component] = values * .001
            radius[start:stop] = arrays["radius"][rows] * .001
            if not np.all(np.isfinite(radius[start:stop])) or np.any(radius[start:stop] < 0):
                raise ValueError("Source skeleton has invalid radii")
            node_ids[start:stop] = arrays["node_id"][rows]
            parent_ids[start:stop] = arrays["parent_id"][rows]
            written[index] += len(rows)
        seen += batch.num_rows
        if seen % (batch_size * 8) == 0 or seen == total_rows:
            for array in (vertices, radius, node_ids, parent_ids):
                array.flush()
            _notify(root, progress, status="importing", progress=.48 + .25 * seen / max(1, total_rows),
                    message="Streaming source nodes into packed geometry", rows_imported=seen, source_rows=total_rows)
    if not np.array_equal(written, counts):
        raise ValueError("Morphology node counts changed between source passes")
    edge_offsets = [0]
    missing_parents = 0
    with (directory / "edges.bin").open("wb") as edge_stream:
        for index in range(len(roots)):
            _cancelled(cancel)
            start, stop = offsets[index:index + 2]
            ids = np.asarray(node_ids[start:stop])
            parents = np.asarray(parent_ids[start:stop])
            sorting = np.argsort(ids)
            sorted_ids = ids[sorting]
            if len(ids) and np.any(np.diff(sorted_ids) == 0):
                raise ValueError(f"Duplicate source node IDs for root {roots[index]}")
            child = np.flatnonzero(parents >= 0)
            parent_locations = np.searchsorted(sorted_ids, parents[child])
            valid = parent_locations < len(ids)
            valid[valid] &= sorted_ids[parent_locations[valid]] == parents[child[valid]]
            missing_parents += int(np.count_nonzero(~valid))
            child = child[valid]
            parent = sorting[parent_locations[valid]]
            edges = np.column_stack((child, parent)).astype("<u4")
            if np.any(child == parent):
                raise ValueError(f"Self-parent source edge for root {roots[index]}")
            edges.tofile(edge_stream)
            edge_offsets.append(edge_offsets[-1] + len(edges))
            if index % 2000 == 0:
                _notify(root, progress, status="connecting", progress=.73 + .22 * index / max(1, len(roots)),
                        message="Reconstructing source parent edges", neurons_processed=index, model_neuron_count=len(roots))
    for array in (vertices, radius, node_ids, parent_ids):
        array.flush()
    del vertices, radius, node_ids, parent_ids
    (directory / "node_ids.tmp").unlink()
    (directory / "parent_ids.tmp").unlink()
    np.save(directory / "edge_offsets.npy", np.asarray(edge_offsets, dtype="<i8"))
    edge_counts = np.diff(edge_offsets)
    missing = np.flatnonzero(counts == 0)
    missing_ids = [str(int(roots[i])) for i in missing]
    atomic_write_json(directory / "missing_roots.json", {"indices": missing.tolist(), "root_ids": missing_ids})
    manifest = {**_provenance(), "format_version": FORMAT_VERSION, "status": "ready", "progress": 1.,
                "message": "Packed source morphology is ready", "model_neuron_count": len(roots),
                "covered_neuron_count": int(np.count_nonzero(counts)),
                "neurons_with_edges": int(np.count_nonzero(edge_counts)), "missing_neuron_count": len(missing),
                "all_model_neurons_covered": len(missing) == 0, "source_rows": total_rows,
                "vertex_count": total, "edge_count": int(edge_offsets[-1]),
                "unresolved_parent_count": missing_parents, "source_topology_complete": missing_parents == 0,
                "root_order_sha256": _root_digest(roots),
                "missing_roots_url": ASSET_PREFIX + "missing_roots.json", "built_at": time.time()}
    atomic_write_json(directory / "manifest.json", manifest)
    return manifest


def prepare_morphology(root, progress=None, cancel=None):
    """Download, verify and build once. Call from the server's background worker."""
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "prepare.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ready = _read(directory / "manifest.json")
        if ready.get("status") == "ready" and ready.get("root_order_sha256") == _root_digest(_roots(root)):
            return ready
        try:
            source = _download_archive(root, progress, cancel)
            result = _import_parquet(root, source, progress, cancel)
            _notify(root, progress, **{key: value for key, value in result.items() if key not in _provenance()})
            return result
        except Exception as error:
            _notify(root, progress, status="cancelled" if isinstance(error, InterruptedError) else "failed",
                    progress=0., message=str(error))
            raise


def parse_skeleton_binary(data):
    """Decode the public Neuroglancer source without inventing or extending edges."""
    if len(data) < 8:
        raise ValueError("Truncated source skeleton header")
    nv, ne = (int(value) for value in np.frombuffer(data, dtype="<u4", count=2))
    minimum = 8 + 12 * nv + 8 * ne
    if len(data) not in (minimum, minimum + 4 * nv):
        raise ValueError("Source skeleton length does not match its header")
    vertices = np.frombuffer(data, dtype="<f4", count=nv * 3, offset=8).reshape(nv, 3).copy()
    edges = np.frombuffer(data, dtype="<u4", count=ne * 2, offset=8 + nv * 12).reshape(ne, 2).copy()
    if not np.all(np.isfinite(vertices)) or (edges.size and int(edges.max()) >= nv):
        raise ValueError("Invalid source skeleton vertices or edge indices")
    radii = (np.frombuffer(data, dtype="<f4", count=nv, offset=minimum).copy()
             if len(data) > minimum else np.zeros(nv, dtype="<f4"))
    if not np.all(np.isfinite(radii)) or np.any(radii < 0):
        raise ValueError("Invalid source skeleton radii")
    return vertices * .001, edges, radii * .001


def _neuron_asset_metadata(index, root_id, vertices, edges, radius, source):
    prefix = ASSET_PREFIX + f"neurons/{index}/"
    return {**_provenance(), "status": "ready", "neuron_index": index, "root_id": str(int(root_id)),
            "vertex_count": len(vertices), "edge_count": len(edges), "source_url": source,
            "vertices_url": prefix + "vertices.bin", "edges_url": prefix + "edges.bin",
            "radius_url": prefix + "radius.bin", "vertex_dtype": "float32", "edge_dtype": "uint32",
            "radius_dtype": "float32", "radius_units": "um"}


def morphology_neuron(root, index):
    """Full source branches for one model neuron; public endpoint fallback is immediate."""
    roots = _roots(root)
    index = int(index)
    if index < 0 or index >= len(roots):
        raise ValueError("Neuron index is outside the model")
    directory = _directory(root)
    out = directory / "neurons" / str(index)
    with _locks_guard:
        lock = _locks.setdefault(str(out.resolve()), threading.Lock())
    with lock:
        previous = _read(out / "metadata.json")
        if previous.get("root_id") == str(int(roots[index])) and all((out / name).exists() for name in ("vertices.bin", "edges.bin", "radius.bin")):
            return previous
        manifest = _read(directory / "manifest.json")
        vertices = edges = radii = None
        source = f"{SKELETON_URL}/{roots[index]}"
        if manifest.get("status") == "ready" and manifest.get("root_order_sha256") == _root_digest(roots):
            vo = np.load(directory / "vertex_offsets.npy", mmap_mode="r")
            eo = np.load(directory / "edge_offsets.npy", mmap_mode="r")
            a, b = vo[index:index + 2]
            c, d = eo[index:index + 2]
            if b > a:
                vertices = np.memmap(directory / "vertices.bin", dtype="<f4", mode="r", offset=int(a) * 12, shape=(int(b-a), 3))
                edges = _mapped(directory / "edges.bin", "<u4", (int(eo[-1]), 2), "r")[c:d]
                radii = np.memmap(directory / "radius.bin", dtype="<f4", mode="r", offset=int(a) * 4, shape=(int(b-a),))
                source = ARCHIVE_URL
        if vertices is None:
            with urllib.request.urlopen(source, timeout=45) as response:
                data = response.read(128 * 1024 * 1024 + 1)
            if len(data) > 128 * 1024 * 1024:
                raise ValueError("Source skeleton exceeds the per-neuron download limit")
            vertices, edges, radii = parse_skeleton_binary(data)
        out.mkdir(parents=True, exist_ok=True)
        for filename, array in (("vertices.bin", vertices), ("edges.bin", edges), ("radius.bin", radii)):
            temporary = out / (filename + ".tmp")
            array.tofile(temporary)
            temporary.replace(out / filename)
        metadata = _neuron_asset_metadata(index, roots[index], vertices, edges, radii, source)
        atomic_write_json(out / "metadata.json", metadata)
        return metadata


def _allocation(counts, budget):
    """Fair deterministic sampling: every real neuron contributes before more edges."""
    counts = np.asarray(counts, dtype=np.int64)
    desired = min(int(budget), int(counts.sum()))
    allocation = np.zeros(len(counts), dtype=np.int64)
    eligible = np.flatnonzero(counts > 0)
    if desired < len(eligible):
        chosen = eligible[np.linspace(0, len(eligible)-1, desired, dtype=np.int64)] if desired else []
        allocation[chosen] = 1
        return allocation
    allocation[eligible] = 1
    remaining = desired - len(eligible)
    capacity = counts - allocation
    if remaining and capacity.sum():
        fractional = remaining * capacity.astype(np.float64) / capacity.sum()
        extra = np.floor(fractional).astype(np.int64)
        allocation += extra
        left = desired - int(allocation.sum())
        candidates = np.flatnonzero(allocation < counts)
        chosen = candidates[np.argsort(-(fractional[candidates] - extra[candidates]), kind="stable")[:left]]
        allocation[chosen] += 1
    return allocation


def _partial_overview(root, budget, cancel=None):
    """Honest temporary coverage from previously fetched real single-neuron assets."""
    directory = _directory(root)
    roots = _roots(root)
    entries = []
    counts = np.zeros(len(roots), dtype=np.int64)
    fingerprint = hashlib.sha256(_root_digest(roots).encode())
    for path in sorted((directory / "neurons").glob("*/metadata.json")):
        entry = _read(path)
        index = entry.get("neuron_index", -1)
        if (0 <= index < len(roots) and entry.get("root_id") == str(int(roots[index]))
                and entry.get("status") == "ready" and entry.get("edge_count", 0)):
            entries.append((index, path.parent, entry))
            counts[index] = entry["edge_count"]
            fingerprint.update(f"{index}:{path.stat().st_mtime_ns}:{entry['edge_count']}".encode())
    if not entries:
        return {**morphology_status(root), "segment_budget": budget, "represented_neuron_count": 0,
                "model_neuron_count": len(roots), "all_model_neurons_represented": False}
    allocation = _allocation(counts, budget)
    count = int(allocation.sum())
    out = directory / "overview" / str(budget) / "partial"
    out.mkdir(parents=True, exist_ok=True)
    cached = _read(out / "metadata.json")
    if (cached.get("source_cache_digest") == fingerprint.hexdigest()
            and (out / "positions.bin").exists() and (out / "owners.bin").exists()):
        return cached
    positions = _mapped(out / "positions.bin.tmp", "<f4", (count, 2, 3), "w+")
    owners = _mapped(out / "owners.bin.tmp", "<u4", (count,), "w+")
    offset = 0
    for index, path, entry in entries:
        _cancelled(cancel)
        number = allocation[index]
        if not number:
            continue
        vertices = _mapped(path / "vertices.bin", "<f4", (entry["vertex_count"], 3), "r")
        edges = _mapped(path / "edges.bin", "<u4", (entry["edge_count"], 2), "r")
        selected = np.linspace(0, entry["edge_count"]-1, number, dtype=np.int64)
        positions[offset:offset+number] = vertices[edges[selected]]
        owners[offset:offset+number] = index
        offset += number
    for array in (positions, owners):
        if isinstance(array, np.memmap):
            array.flush()
    del positions, owners
    for filename in ("positions.bin", "owners.bin"):
        (out / (filename + ".tmp")).replace(out / filename)
    prefix = ASSET_PREFIX + f"overview/{budget}/partial/"
    metadata = {**_provenance(), "status": "partial", "segment_budget": budget, "segment_count": count,
                "message": "Partial source-neuron coverage while whole-brain morphology prepares",
                "represented_neuron_count": int(np.count_nonzero(allocation)), "model_neuron_count": len(roots),
                "all_model_neurons_represented": False, "positions_url": prefix + "positions.bin",
                "owners_url": prefix + "owners.bin", "positions_shape": [count, 2, 3], "owners_shape": [count],
                "positions_dtype": "float32", "owners_dtype": "uint32",
                "root_order_sha256": _root_digest(roots), "source_cache_digest": fingerprint.hexdigest(),
                "sampling": "Actual source edges from the available cached neurons only"}
    atomic_write_json(out / "metadata.json", metadata)
    return metadata


def build_overview(root, segment_budget=1_000_000, progress=None, cancel=None):
    """Sample only source edges, keeping each segment's exact model-neuron owner."""
    budget = int(segment_budget)
    if budget < 1 or budget > 5_000_000:
        raise ValueError("Morphology segment budget must be between 1 and 5000000")
    directory = _directory(root)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"overview-{budget}.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _build_overview(root, budget, progress, cancel)


def _build_overview(root, budget, progress=None, cancel=None):
    directory = _directory(root)
    manifest = _read(directory / "manifest.json")
    if manifest.get("status") != "ready":
        return _partial_overview(root, budget, cancel)
    if manifest.get("root_order_sha256") != _root_digest(_roots(root)):
        return {**morphology_status(root), "segment_budget": budget,
                "represented_neuron_count": 0, "all_model_neurons_represented": False}
    out = directory / "overview" / str(budget)
    cached = _read(out / "metadata.json")
    if cached.get("root_order_sha256") == manifest["root_order_sha256"] and cached.get("source_built_at") == manifest["built_at"]:
        return cached
    out.mkdir(parents=True, exist_ok=True)
    vo = np.load(directory / "vertex_offsets.npy", mmap_mode="r")
    eo = np.load(directory / "edge_offsets.npy", mmap_mode="r")
    allocation = _allocation(np.diff(eo), budget)
    count = int(allocation.sum())
    vertices = _mapped(directory / "vertices.bin", "<f4", (int(vo[-1]), 3), "r")
    edges = _mapped(directory / "edges.bin", "<u4", (int(eo[-1]), 2), "r")
    positions = _mapped(out / "positions.bin.tmp", "<f4", (count, 2, 3), "w+")
    owners = _mapped(out / "owners.bin.tmp", "<u4", (count,), "w+")
    offset = 0
    for index in np.flatnonzero(allocation):
        _cancelled(cancel)
        number = allocation[index]
        selected = np.linspace(eo[index], eo[index+1]-1, number, dtype=np.int64)
        pairs = edges[selected].astype(np.int64) + vo[index]
        positions[offset:offset+number] = vertices[pairs]
        owners[offset:offset+number] = index
        offset += number
    for array in (positions, owners):
        if isinstance(array, np.memmap):
            array.flush()
    del positions, owners
    for filename in ("positions.bin", "owners.bin"):
        (out / (filename + ".tmp")).replace(out / filename)
    prefix = ASSET_PREFIX + f"overview/{budget}/"
    represented = int(np.count_nonzero(allocation))
    metadata = {**_provenance(), "status": "ready", "segment_budget": budget, "segment_count": count,
                "represented_neuron_count": represented, "model_neuron_count": manifest["model_neuron_count"],
                "all_model_neurons_represented": represented == manifest["model_neuron_count"],
                "positions_url": prefix + "positions.bin", "owners_url": prefix + "owners.bin",
                "positions_shape": [count, 2, 3], "owners_shape": [count],
                "positions_dtype": "float32", "owners_dtype": "uint32",
                "sampling": "Actual source edge samples; at least one per neuron with edges when budget permits; no invented branches",
                "root_order_sha256": manifest["root_order_sha256"], "source_built_at": manifest["built_at"]}
    atomic_write_json(out / "metadata.json", metadata)
    if progress:
        progress(metadata)
    return metadata
