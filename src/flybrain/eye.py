"""Auditable column assignment, spherical Gaussian optics and assumed transduction."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import sparse
from scipy.special import ndtri
from scipy.stats import qmc


@dataclass
class EyeMapping:
    columns: pd.DataFrame
    assignments: pd.DataFrame
    photoreceptor_indices: np.ndarray
    photoreceptor_columns: np.ndarray
    audit: dict


def column_directions(columns, spacing_deg=5.1, eye_center_deg=45.0):
    """Map source 120-degree axial coordinates via a spherical exponential map.

    A 5.1-degree step is exact at the eye center, not globally uniform spherical
    tessellation. Mean centering, global placement and left reflection are assumptions.
    """
    columns = columns.copy()
    vectors = np.empty((len(columns), 3))
    for side in ('left', 'right'):
        take = np.flatnonzero(columns.hemisphere.to_numpy() == side)
        if not len(take):
            continue
        p = columns.iloc[take].p.to_numpy(dtype=float)
        q = columns.iloc[take].q.to_numpy(dtype=float)
        p, q = p - p.mean(), q - q.mean()
        x = np.deg2rad(spacing_deg * np.sqrt(3) / 2 * (q-p))
        y = np.deg2rad(spacing_deg * .5 * (p+q))
        # Right source +q-p is posterior; left handedness is explicitly assumed.
        if side == 'left':
            x = -x
        theta = np.deg2rad(eye_center_deg * (1 if side == 'right' else -1))
        center = np.array([np.cos(theta), np.sin(theta), 0.])
        horizontal = np.array([-np.sin(theta), np.cos(theta), 0.])
        radial = np.hypot(x, y)
        vectors[take] = (np.cos(radial)[:, None] * center +
                         np.sinc(radial / np.pi)[:, None] *
                         (x[:, None] * horizontal + y[:, None] * np.array([0., 0., 1.])))
    columns['azimuth_deg'] = np.rad2deg(np.arctan2(vectors[:, 1], vectors[:, 0]))
    columns['elevation_deg'] = np.rad2deg(np.arcsin(np.clip(vectors[:, 2], -1, 1)))
    return columns


def _strongest_column(neuron, matrix, known, sides, allowed=None):
    start, stop = matrix.indptr[neuron:neuron+2]
    partners, weights = matrix.indices[start:stop], np.abs(matrix.data[start:stop])
    usable = (known[partners] >= 0) & (sides[partners] == sides[neuron])
    if allowed is not None:
        usable &= allowed[partners]
    if not usable.any():
        return -1, 'no_known_partner'
    partners, weights = partners[usable], weights[usable]
    winners = np.unique(known[partners[weights == weights.max()]])
    if len(winners) != 1:
        return -1, 'tied_columns'
    return int(winners[0]), 'strongest_synaptic_partner'


def build_eye_mapping(root, neurons=None, counts=None, *, spacing_deg=5.1,
                      eye_center_deg=45.0, persist=True):
    root = Path(root)
    neurons = pd.read_parquet(root/'build/neurons.parquet') if neurons is None else neurons
    counts = sparse.load_npz(root/'build/reference_counts.npz') if counts is None else counts
    export = pd.read_csv(root/'data/raw/codex/column_assignment.csv')
    if export.root_id.duplicated().any():
        raise ValueError('Column source has duplicate root IDs')
    table = neurons[['root_id', 'cell_type', 'side']].copy().reset_index(drop=True)
    table['neuron_index'] = np.arange(len(table))
    joined = export.merge(table, on='root_id', validate='one_to_one')
    conflict = joined['type'].ne(joined.cell_type) | joined.hemisphere.ne(joined.side)
    forbidden = np.zeros(len(table), dtype=bool)
    forbidden[joined.loc[conflict, 'neuron_index'].to_numpy(dtype=int)] = True
    valid = joined.loc[~conflict]
    anchors = valid[valid['type'].eq('Mi1')].copy()
    if anchors.duplicated(['hemisphere', 'column_id']).any():
        raise ValueError('Mi1 anchors do not uniquely identify columns')
    columns = anchors[['hemisphere', 'column_id', 'p', 'q', 'x', 'y', 'root_id']].sort_values(
        ['hemisphere', 'column_id']).reset_index(drop=True).rename(columns={'root_id':'anchor_root_id'})
    columns['column_index'] = np.arange(len(columns))
    columns = column_directions(columns, spacing_deg, eye_center_deg)
    lookup = {(r.hemisphere, r.column_id): r.column_index for r in columns.itertuples()}
    known = np.full(len(table), -1, dtype=np.int32)
    source = np.full(len(table), 'unassigned', dtype=object)
    source[forbidden] = 'excluded_source_conflict'
    sides = table.side.fillna('').to_numpy()
    types = table.cell_type.fillna('').to_numpy()
    outgoing = counts.tocsc().T.tocsr()  # rows are presynaptic, entries are targets
    incoming = counts.tocsr()
    for r in anchors.itertuples():
        known[r.neuron_index] = lookup[(r.hemisphere, r.column_id)]
        source[r.neuron_index] = 'Codex_Mi1_anchor'
    l1_predictions = {}
    for index in np.flatnonzero((types == 'L1') & ~forbidden):
        col, how = _strongest_column(index, outgoing, known, sides, types == 'Mi1')
        if col >= 0:
            known[index], source[index] = col, 'L1_to_Mi1_strongest_target'
            l1_predictions[index] = col
    # Verified source coordinates take precedence over inferred anatomy.
    disagreements = 0
    for r in valid.itertuples():
        col = lookup.get((r.hemisphere, r.column_id), -1)
        if col >= 0:
            disagreements += int(r.neuron_index in l1_predictions and l1_predictions[r.neuron_index] != col)
            known[r.neuron_index] = col
            source[r.neuron_index] = 'Codex_Mi1_anchor' if r.type == 'Mi1' else 'Codex_column_export'
    target_types = np.isin(types, ['L1','L2','L3','L4','L5','Mi4','Mi9','Tm1','Tm2','Tm3','Tm4','Tm9','Tm20',
                                 'T4a','T4b','T4c','T4d','T5a','T5b','T5c','T5d'])
    # Use total bilateral anatomical contact strengths, preserving source signs separately.
    undirected = abs(incoming) + abs(outgoing)
    rounds = []
    for _ in range(6):
        proposals = []
        for index in np.flatnonzero(target_types & (known < 0) & ~forbidden):
            col, how = _strongest_column(index, undirected, known, sides)
            if col >= 0:
                proposals.append((index, col))
        rounds.append(len(proposals))
        for index, col in proposals:
            known[index], source[index] = col, 'iterated_strongest_contact'
        if not proposals:
            break
    photo_mask = np.isin(types, ['R1-6', 'R7', 'R8'])
    lamina_targets = np.isin(types, ['L1','L2','L3'])
    medulla_targets = ~photo_mask & ~np.isin(types, ['L1','L2','L3','L4','L5'])
    for index in np.flatnonzero(photo_mask & ~forbidden):
        if types[index] == 'R1-6':
            allowed = lamina_targets
        elif known[index] >= 0:
            continue  # direct verified R7/R8 export is more specific than inference
        else:
            allowed = medulla_targets
        col, how = _strongest_column(index, outgoing, known, sides, allowed)
        known[index], source[index] = col, ('photoreceptor_'+how)
    table['column_index'], table['assignment_source'] = known, source
    mapped = np.flatnonzero(photo_mask & (known >= 0)).astype(np.int32)
    audit = {
        'status': 'EXPERIMENTAL_MAPPING', 'anchors': len(columns),
        'anchors_by_side': columns.hemisphere.value_counts().to_dict(),
        'source_conflict_count': int(forbidden.sum()),
        'source_conflict_root_ids': [str(x) for x in table.root_id[forbidden]],
        'unresolved_mi1_root_ids': [str(x) for x in table.root_id[(types == 'Mi1') & (known < 0)]],
        'l1_inference_source_disagreements': disagreements, 'iteration_new_assignments': rounds,
        'photoreceptors_total': int(photo_mask.sum()), 'photoreceptors_mapped': len(mapped),
        'photoreceptors_unassigned': int(np.count_nonzero(photo_mask & (known < 0))),
        'unassigned_photoreceptors_by_type': table.loc[photo_mask & (known < 0), 'cell_type'].value_counts().to_dict(),
        'all_unassigned_count': int(np.count_nonzero(known < 0)),
        'coordinate_units': 'source p,q are axial grid positions, not nanometers',
        'retinotopy_assumptions': [f'{spacing_deg:g} degree center spacing mapped to a sphere via a tangent exponential map',
            'each eye centered on its mean axial coordinate', 'left eye horizontal reflection',
            f'eye centers at +/-{eye_center_deg:g} degrees azimuth; center elevation zero'],
        'assignment_policy': 'Source conflicts excluded. Mi1 anchors; L1-to-Mi1 seed; unambiguous export preferred; '
            'missing columnar cells iterated by strongest bilateral contact; R1-6 strongest outgoing L1/L2/L3 target. '
            'Unknown R7/R8 use strongest outgoing known medulla partner. Ties between columns stay unresolved.',
        'synthetic_edges': 0,
    }
    result = EyeMapping(columns, table, mapped, known[mapped], audit)
    if persist:
        out = root/'build/visual'; out.mkdir(exist_ok=True, parents=True)
        columns.to_csv(out/'eye_columns.csv', index=False)
        table.to_parquet(out/'eye_assignments.parquet', index=False)
        table.loc[photo_mask & (known < 0)].to_csv(out/'unassigned_photoreceptors.csv', index=False)
        (out/'eye_audit.json').write_text(json.dumps(audit, indent=2)+'\n')
    return result


def optical_quadrature(columns, fwhm_deg=5.7, order=5):
    """Spherical tangent Gaussian expectation (Gauss-Hermite quadrature)."""
    az = np.deg2rad(columns.azimuth_deg.to_numpy())
    el = np.deg2rad(columns.elevation_deg.to_numpy())
    center = np.column_stack((np.cos(el)*np.cos(az), np.cos(el)*np.sin(az), np.sin(el)))
    horizontal = np.column_stack((-np.sin(az), np.cos(az), np.zeros(len(az))))
    vertical = np.cross(center, horizontal)
    nodes, weights = np.polynomial.hermite.hermgauss(order)
    sigma = np.deg2rad(fwhm_deg / (2*np.sqrt(2*np.log(2))))
    gx, gy = np.meshgrid(nodes*np.sqrt(2)*sigma, nodes*np.sqrt(2)*sigma)
    x, y = gx.ravel(), gy.ravel()
    r = np.hypot(x, y)
    rays = (np.cos(r)[None,:,None]*center[:,None,:] + np.sinc(r/np.pi)[None,:,None] *
            (x[None,:,None]*horizontal[:,None,:]+y[None,:,None]*vertical[:,None,:]))
    return (np.rad2deg(np.arctan2(rays[:,:,1], rays[:,:,0])),
            np.rad2deg(np.arcsin(np.clip(rays[:,:,2],-1,1))),
            np.outer(weights,weights).ravel()/np.pi)


def gaussian_ray_samples(columns, fwhm_deg=5.7, sample_count=4096, seed=783):
    """Deterministic scrambled-Sobol integration of the spherical tangent Gaussian.

    The seed fixes numerical integration points, not stochastic light or neural input.
    Samples nest across powers of two so finer reference calculations are comparable.
    """
    count = int(sample_count)
    if count != sample_count or count < 256 or count > 65536 or count & (count-1):
        raise ValueError('optics_samples must be a power of two from 256 through 65536')
    if not np.isfinite(fwhm_deg) or fwhm_deg <= 0:
        raise ValueError('Optical FWHM must be finite and positive')
    uniform = qmc.Sobol(d=2,scramble=True,seed=int(seed)).random_base2(count.bit_length()-1)
    sigma = np.deg2rad(fwhm_deg/(2*np.sqrt(2*np.log(2))))
    x,y = (ndtri(np.clip(uniform,np.finfo(float).eps,1-np.finfo(float).eps))*sigma).T
    radial = np.hypot(x,y)
    az = np.deg2rad(columns.azimuth_deg.to_numpy())
    el = np.deg2rad(columns.elevation_deg.to_numpy())
    center = np.column_stack((np.cos(el)*np.cos(az),np.cos(el)*np.sin(az),np.sin(el)))
    horizontal = np.column_stack((-np.sin(az),np.cos(az),np.zeros(len(az))))
    vertical = np.cross(center,horizontal)
    rays = (np.cos(radial)[None,:,None]*center[:,None,:] + np.sinc(radial/np.pi)[None,:,None]*
            (x[None,:,None]*horizontal[:,None,:]+y[None,:,None]*vertical[:,None,:]))
    return (np.rad2deg(np.arctan2(rays[:,:,1],rays[:,:,0])),
            np.rad2deg(np.arcsin(np.clip(rays[:,:,2],-1,1))))


class Phototransduction:
    """Assumed normalized-luminance adaptation followed by passive low-pass drive."""
    def __init__(self, n_columns, parameters, initial_luminance=0.):
        self.parameters = parameters
        self.adaptation = np.full(n_columns, initial_luminance, dtype=float)
        self.drive = np.full(n_columns, self._target(initial_luminance, initial_luminance), dtype=float)

    def _target(self, light, adaptation):
        p = self.parameters
        return p['maximum_drive_mv'] * light / (light + p['half_saturation'] + p['adaptation_strength']*adaptation)

    def step(self, luminance, dt_ms):
        light = np.asarray(luminance, dtype=float)
        if np.any(~np.isfinite(light)) or np.any((light < 0) | (light > 1)):
            raise ValueError('Luminance must be finite in [0,1]')
        p = self.parameters
        self.adaptation += (1-np.exp(-dt_ms/p['adaptation_tau_ms']))*(light-self.adaptation)
        target = self._target(light, self.adaptation)
        self.drive += (1-np.exp(-dt_ms/p['phototransduction_tau_ms']))*(target-self.drive)
        return self.drive.copy()
