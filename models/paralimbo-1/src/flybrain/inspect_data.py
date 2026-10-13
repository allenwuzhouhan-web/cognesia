"""Schema discovery independent of the release-specific validation code."""
from pathlib import Path
import json
import os
import tempfile


def atomic_write_json(path: Path, data) -> None:
    """Keep the previous complete evidence file if serialization/write fails."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, allow_nan=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            temporary = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def stat_signature(path: Path) -> dict:
    """Cheap freshness evidence; the SHA-256 remains the content identity."""
    info = Path(path).stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns,
            "ctime_ns": info.st_ctime_ns, "inode": info.st_ino}


def inspect_table(path: Path) -> dict:
    import pandas as pd
    import pyarrow.parquet as parquet
    import pyarrow as pa
    from .memguard import check_memory

    check_memory()
    path = Path(path)
    if path.suffix == ".parquet":
        f = parquet.ParquetFile(path)
        batch = next(f.iter_batches(batch_size=3))
        frame = batch.to_pandas()
        rows, schema = f.metadata.num_rows, str(f.schema_arrow)
    elif path.suffix == ".feather":
        with pa.memory_map(str(path), "r") as source:
            f = pa.ipc.open_file(source)
            rows = 0
            for i in range(f.num_record_batches):
                check_memory()
                rows += f.get_batch(i).num_rows
            frame = f.get_batch(0).slice(0, 3).to_pandas()
            schema = str(f.schema)
    else:
        whole = pd.read_csv(path, sep="\t" if path.suffix == ".tsv" else ",", low_memory=False)
        rows = len(whole)
        frame = whole.head(3)
        schema = {str(k): str(v) for k, v in whole.dtypes.items()}
    result = {"file": path.name, "rows": rows, "schema": schema,
              "dtypes": {str(k): str(v) for k, v in frame.dtypes.items()},
              "first_three_rows": json.loads(frame.to_json(orient="records"))}
    check_memory()
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == "__main__":
    import sys
    reports = {}
    for p in sys.argv[1:]:
        reports[Path(p).name] = inspect_table(Path(p))
        atomic_write_json(Path("build/schema_inspection.json"), reports)
