"""Provider-qualified vision: curated cross-specimen columns or explicit models."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from .eye import EyeMapping, column_directions


def build_model_eye_mapping(root,network,spacing_deg=5.1,eye_center_deg=45.):
    table = network["neurons"].reset_index(drop=True)
    native = table.get("native_cell_class",table.cell_class).fillna("")
    photos = native.eq("photoreceptor_neuron").to_numpy() & table.is_graded.to_numpy(bool)
    if not photos.any():
        photos = table.cell_type.fillna("").isin(["R1-6","R7","R8"]).to_numpy() & table.is_graded.to_numpy(bool)
    assignment = table[["root_id","cell_type","side"]].copy()
    assignment["neuron_index"] = np.arange(len(table),dtype=np.int32)
    assignment["column_index"] = -1; assignment["assignment_source"] = "unassigned"
    columns=[]; shared={}; transfer=0
    legacy_path = Path(root)/"build/visual/eye_assignments.parquet"
    column_path = Path(root)/"build/visual/eye_columns.csv"
    if legacy_path.exists() and column_path.exists() and "fafb_match" in table:
        legacy = pd.read_parquet(legacy_path).set_index("root_id")
        legacy_columns = column_directions(pd.read_csv(column_path),spacing_deg,eye_center_deg).set_index("column_index")
        matches = table.fafb_match.fillna("")
        checked = table.status.fillna("").str.contains(r"(?:^|,)FAFB_MATCH_MANUALLY_CHECKED(?:,|$)",regex=True)&matches.str.fullmatch(r"\d+")&~matches.duplicated(keep=False)
        for i in np.flatnonzero(photos & checked.to_numpy()):
            donor = int(matches.iloc[i])
            if donor not in legacy.index: continue
            old = int(legacy.at[donor,"column_index"])
            if old not in legacy_columns.index or old < 0: continue
            row = legacy_columns.loc[old]
            if str(row.hemisphere) != str(table.side.iloc[i]): continue
            if old not in shared:
                shared[old] = len(columns)
                entry = row.to_dict(); entry["column_index"] = len(columns)
                entry["assignment_source"] = "curated_cross_specimen_column"; columns.append(entry)
            assignment.at[i,"column_index"] = shared[old]
            assignment.at[i,"assignment_source"] = "curated_FAFB_homology; source optical column is an inferred cross-specimen transfer"
            transfer += 1
    modeled=0
    for side in ("left","right"):
        indices = np.flatnonzero(photos & table.side.eq(side).to_numpy() & assignment.column_index.lt(0).to_numpy())
        # Deterministic position-ranked axial grid, explicitly not measured
        # ommatidial orientation or an anatomical registration between animals.
        indices = sorted(indices,key=lambda i:(float(table.pos_z.iloc[i]) if np.isfinite(table.pos_z.iloc[i]) else 0.,float(table.pos_x.iloc[i]) if np.isfinite(table.pos_x.iloc[i]) else 0.,int(table.root_id.iloc[i])))
        width = max(1,int(np.ceil(np.sqrt(len(indices)))))
        for ordinal,i in enumerate(indices):
            p,q = ordinal%width, ordinal//width
            entry = {"hemisphere":side,"column_id":"modeled-"+str(ordinal),"p":p,"q":q,"x":p,"y":q,
                     "anchor_root_id":str(table.root_id.iloc[i]),"column_index":len(columns),"assignment_source":"ASSUMPTION: position-ranked optical column"}
            assignment.at[i,"column_index"] = len(columns)
            assignment.at[i,"assignment_source"] = "ASSUMPTION: position-ranked optical column; not verified retinotopy"
            columns.append(entry); modeled += 1
    frame = pd.DataFrame(columns,columns=["hemisphere","column_id","p","q","x","y","anchor_root_id","column_index","assignment_source","azimuth_deg","elevation_deg"])
    if len(frame):
        modeled_mask = frame.assignment_source.ne("curated_cross_specimen_column")
        generated = column_directions(frame.loc[modeled_mask],spacing_deg,eye_center_deg)
        frame.loc[modeled_mask,["azimuth_deg","elevation_deg"]] = generated[["azimuth_deg","elevation_deg"]]
    else:
        frame["azimuth_deg"] = []; frame["elevation_deg"] = []
    mapped = np.flatnonzero(photos & assignment.column_index.ge(0).to_numpy()).astype(np.int32)
    missing = int(photos.sum()-len(mapped))
    audit = {"status":"MODELED_PROVIDER_OPTICS","source_model_hash":network.get("manifest",{}).get("model_hash"),
             "photoreceptors_total":int(photos.sum()),"photoreceptors_mapped":len(mapped),"photoreceptors_unassigned":missing,
             "curated_transferred_photoreceptors":transfer,"modeled_photoreceptors":modeled,"anchors":len(frame),
             "anchors_by_side":frame.hemisphere.value_counts().to_dict(),"all_unassigned_count":int(assignment.column_index.lt(0).sum()),
             "unassigned_photoreceptors_by_type":table.loc[photos & assignment.column_index.lt(0).to_numpy(),"cell_type"].value_counts().to_dict(),
             "synthetic_edges":0,"retinotopy_assumptions":["Only annotated photoreceptors receive optical input.",
                 "Unique curator-checked FAFB matches can transfer source columns as cross-specimen inference.",
                 "Remaining known-side receptors use a deterministic position-ranked axial grid and assumed spherical orientation.",
                 "Unknown sides receive no optical input. This adapter does not establish measured retinotopy or visual selectivity."],
             "assignment_policy":"curated homology first; explicitly modeled known-side columns otherwise"}
    return EyeMapping(frame,assignment,mapped,assignment.column_index.to_numpy(np.int32)[mapped],audit)
