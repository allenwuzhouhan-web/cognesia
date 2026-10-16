"""Outcome-independent stimulation coverage and bounded causal controls."""
from __future__ import annotations

import hashlib
import numpy as np

from .budget import digest

DESCENDING_ROOTS = ('720575941566493282', '720575941433155799',
                   '720575941491012809', '720575941499708745',
                   '720575941491065653', '720575941614906387')


def site_inventory(neurons, *, count=64):
    """Include registered targets, then round-robin anatomical/mode strata.

    SHA order avoids table-order preference without random/outcome access. Fine
    region labels, electrical mode and side define coverage; omissions explicit.
    """
    if len(neurons) < count or not neurons.root_id.is_unique:
        raise ValueError('Enough unique full-graph neurons required')
    columns = ('root_region', 'region', 'side', 'cell_type')
    table = neurons.copy()
    for name in columns:
        if name not in table:
            table[name] = '<unknown>'
        table[name] = table[name].fillna('<unknown>').astype(str)
    groups, by_root = {}, {}
    for index, row in enumerate(table.itertuples()):
        root = str(row.root_id)
        stratum = (row.region, row.root_region, 'graded' if row.is_graded else 'spiking', row.side)
        item = {'root_id': root, 'index': index, 'region': row.region, 'root_region': row.root_region,
                'mode': stratum[2], 'side': row.side, 'cell_type': row.cell_type,
                'stratum': list(stratum)}
        by_root[root] = item
        groups.setdefault(stratum, []).append(root)
    for values in groups.values():
        values.sort(key=lambda r: hashlib.sha256(('transmission-v1/' + r).encode()).hexdigest())
    missing = [root for root in DESCENDING_ROOTS if root not in by_root]
    if missing:
        raise ValueError('Registered descending target absent: ' + ', '.join(missing))
    chosen = list(DESCENDING_ROOTS)
    # Coarse region/mode groups alternate before finer strata to ensure both
    # electrical modes and all available anatomical divisions receive coverage.
    coarse = {}
    for stratum in sorted(groups):
        coarse.setdefault((stratum[0], stratum[2]), []).append(stratum)
    ordered = []
    for offset in range(max(map(len, coarse.values()))):
        for key in sorted(coarse):
            if offset < len(coarse[key]):
                ordered.append(coarse[key][offset])
    cursor = {stratum: 0 for stratum in groups}
    while len(chosen) < count:
        for stratum in ordered:
            values = groups[stratum]
            while cursor[stratum] < len(values) and values[cursor[stratum]] in chosen:
                cursor[stratum] += 1
            if cursor[stratum] < len(values):
                chosen.append(values[cursor[stratum]])
                cursor[stratum] += 1
            if len(chosen) == count:
                break
    covered = {tuple(by_root[r]['stratum']) for r in chosen}
    result = {'selection': 'registered_descending_then_region_mode_round_robin_sha256_v1',
              'population': len(neurons), 'sites': [by_root[r] for r in chosen],
              'strata_total': len(groups), 'strata_covered': len(covered),
              'omitted_strata': [list(s) for s in sorted(set(groups) - covered)],
              'omitted_neurons': len(neurons) - count,
              'limitation': '64 stimulation sites sample the complete simulated graph; coverage is not exhaustive.'}
    result['identity'] = digest(result)
    return result


def causal_targets(network, inventory):
    """One downstream rescue per site selected solely by signed anatomy."""
    # Both registry partitions are target-by-source; the engine transposes the
    # spiking partition only inside its scheduler.
    outgoing = (network['graded'] + network['spiking']).transpose().tocsr()
    roots = network['neurons'].root_id.astype(str).tolist()
    result = {}
    for site in inventory['sites']:
        row = outgoing.getrow(site['index'])
        edges = [(int(j), float(w)) for j, w in zip(row.indices, row.data) if j != site['index'] and w != 0]
        edges.sort(key=lambda pair: (-abs(pair[1]), roots[pair[0]]))
        result[site['root_id']] = {'rescue_root_id': roots[edges[0][0]] if edges else None,
                                  'signed_synapses': edges[0][1] if edges else None,
                                  'outgoing_target_count': len(edges),
                                  'selection': 'largest_absolute_direct_connection_then_root_id'}
    return result
