"""Identity-preserving annotations for recorded receptor and side comparisons."""
import numpy as np
import pandas as pd


def analysis_annotations(neurons, assignments, center_um, scale_um):
    if not np.isfinite(scale_um) or scale_um <= 0:
        raise ValueError("Anatomy normalization must have a positive finite scale")
    columns, sources = {}, {}
    if assignments is not None:
        indices = assignments.neuron_index.to_numpy(dtype=int)
        if (len(np.unique(indices)) != len(indices) or
                np.any(indices < 0) or np.any(indices >= len(neurons))):
            raise ValueError("Eye assignments have invalid or duplicate neuron indices")
        if not np.array_equal(neurons.root_id.to_numpy()[indices], assignments.root_id.to_numpy()):
            raise ValueError("Eye assignments do not match the model neuron order")
        columns = dict(zip(indices, assignments.column_index.to_numpy(dtype=int)))
        sources = dict(zip(indices, assignments.assignment_source.astype(str)))
    receptors = []
    types = neurons.get("cell_type", pd.Series(None, index=neurons.index, dtype=object))
    sides = neurons.get("side", pd.Series(None, index=neurons.index, dtype=object))
    for index in np.flatnonzero(types.isin(["R1-6", "R7", "R8"]).to_numpy()):
        row = neurons.iloc[index]
        side = str(row.get("side")) if pd.notna(row.get("side")) else "unknown"
        column = columns.get(index, -1)
        receptors.append({"index": int(index), "root_id": str(int(row.root_id)),
                          "cell_type": str(row.cell_type), "side": side,
                          "column_index": int(column) if column >= 0 else None,
                          "assignment_source": sources.get(index, "unassigned")})
    orientation = {"source": "Median physical annotation position of optic neurons on each annotated side",
                   "meaning": "Left and right are the fly's anatomical sides, not the screen edges",
                   "positions": {}}
    for side in ("left", "right"):
        rows = neurons.loc[sides.eq(side) & neurons.super_class.eq("optic")]
        xyz = rows[["pos_x", "pos_y", "pos_z"]].to_numpy(dtype=float) * [.004, .004, .04]
        xyz = xyz[np.all(np.isfinite(xyz), axis=1)]
        if len(xyz):
            physical = np.median(xyz, axis=0)
            orientation["positions"][side] = {
                "position_um": physical.tolist(),
                "normalized": ((physical - np.asarray(center_um)) / scale_um).tolist(),
                "annotation_count": len(xyz)}
    return {"version": 1, "receptors": receptors, "orientation": orientation,
            "note": "Recorded model voltage and normalized optical input; not measured biological responses. Unassigned receptors retain voltage recordings but have no mapped optical column."}
