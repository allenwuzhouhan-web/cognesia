#!/usr/bin/env python3
"""Rebuild the publication figure from results.json (requires matplotlib)."""
from pathlib import Path
import hashlib
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
data = json.loads((HERE / 'results.json').read_text())
expected = data['public_results_sha256']
canonical = json.dumps({k: v for k, v in data.items() if k != 'public_results_sha256'}, sort_keys=True, separators=(',', ':'), allow_nan=False)
assert hashlib.sha256(canonical.encode()).hexdigest() == expected
groups = {group['model_id']: group for group in data['groups']}
models = ['banc-888', 'paralimbo-v0-1-0', 'paralimbo-visual-graded-v1', 'zero-response']
names = ['BANC', 'Original\nParaLimbo 0.1', 'ParaLimbo 1', 'Zero-response\nreference']
metrics = [
    ('flash_spatial_peak_rmse', 'Flash spatial peak', '3 positions'),
    ('flash_duration_peak_rmse', 'Flash duration peak', '3 durations'),
    ('motion_waveform_rmse', 'Motion waveform', '4 motion conditions'),
    ('direction_contrast_rmse', 'Direction contrast', '2 direction pairs'),
    ('speed_contrast_rmse', 'Speed contrast', '2 speed pairs'),
]
colors = ['#68717D', '#95A5A6', '#087E8B', '#D4D8DD']
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 11, 'svg.fonttype': 'none', 'svg.hashsalt': 'paralimbo-1', 'axes.spines.top': False, 'axes.spines.right': False, 'axes.spines.left': False})
fig, axes = plt.subplots(3, 2, figsize=(15, 13.9))
fig.patch.set_facecolor('white')
fig.subplots_adjust(left=.13, right=.98, top=.85, bottom=.145, wspace=.48, hspace=.90)
fig.text(.035, .965, 'ParaLimbo 1 vs BANC', fontsize=24, weight='bold', color='#17212B')
fig.text(.035, .932, '4 small numerical wins out of 5 related endpoints · original model ties all 5', fontsize=15, color='#17212B')
fig.text(.035, .901, '27 native requests · 1 recorded T4 cell · 9 conditions × 1 paired trial · biological validation PENDING', fontsize=12, color='#495461')
maximum = max(endpoint['score'] for group in data['groups'] for endpoint in group['endpoints'].values())
for ax, (metric, title, count) in zip(axes.flat, metrics):
    scores = [(data['zero_response_baseline'] if model == 'zero-response' else groups[model]['endpoints'])[metric]['score'] for model in models]
    ax.barh(np.arange(4), scores, color=colors, height=.60, zorder=3)
    ax.set_yticks(np.arange(4), names)
    ax.tick_params(axis='y', length=0, pad=9)
    ax.invert_yaxis()
    ax.set_xlim(0, maximum*1.32)
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.grid(axis='x', color='#E2E5E8', lw=.7, zorder=0)
    ax.spines['bottom'].set_color('#BCC3CC')
    ax.set_xlabel('Error (mV) · LOWER IS BETTER', labelpad=8)
    ax.set_title(title, loc='left', weight='bold', fontsize=14, pad=35)
    ax.text(0, 1.09, count, transform=ax.transAxes, fontsize=11, color='#495461')
    for y, value in enumerate(scores):
        ax.text(value + maximum*.014, y, f'{value:.6f}', va='center', fontsize=11, color='#17212B')
    comp = next(c for c in data['comparisons'] if c['model_id'] == 'paralimbo-visual-graded-v1' and c['metric'] == metric)
    pct = 100*comp['banc_minus_paralimbo_mv']/comp['banc_score']
    verdict = 'Lower error' if comp['verdict'] == 'PARALIMBO_LOWER_ERROR' else 'Within numerical tolerance'
    ax.text(0, -.34, f'ParaLimbo 1: {pct:.3f}% error reduction · {verdict}', transform=ax.transAxes, fontsize=11, color='#17212B')
    ax.text(0, -.46, f"Numerical separation rule: {comp['numerical_separation_mv']:.3f} mV", transform=ax.transAxes, fontsize=10, color='#495461')
notes = axes[2, 1]
notes.axis('off')
notes.text(0, 1.23, 'How to read these results', fontsize=15, weight='bold', transform=notes.transAxes, color='#17212B')
notes.text(0, 1.03,
    'Every panel uses the same zero-based error scale.\n\n'
    'BANC and Original ParaLimbo 0.1 predict zero\n'
    'evoked T4 response under these fixed inputs.\n\n'
    'Four improvements exceed the predeclared\n'
    'numerical separation: 0.14–0.61% lower error.\n\n'
    'One dataset and assumed cell correspondence.\n'
    'Retrospective; no statistical superiority claim.\n'
    'Broad biological superiority is unestablished.',
    va='top', linespacing=1.5, fontsize=11, color='#495461', transform=notes.transAxes)
fig.text(.035, .030, 'Experimental data: Gruntman, Romani & Reiser (2018) · dataset DOI 10.25378/janelia.5576101.v1 · CC BY-NC 4.0', fontsize=10, color='#495461')
fig.text(.035, .013, 'Changes: conversion, filtering, baseline subtraction, trial selection, scoring and plotting. Exact values: benchmark-scores.csv and results.json.', fontsize=10, color='#495461')
fig.savefig(HERE / 'benchmark-overview.svg', metadata={'Date': None, 'Description': 'Five related retrospective error endpoints. Lower is better in every panel. Biological validation pending.'})
fig.savefig(HERE / 'benchmark-overview.png', dpi=140, metadata={'Description': 'ParaLimbo 1 versus BANC. Five related endpoints; all lower is better. Biological validation pending.'})
print('Wrote benchmark-overview.svg and benchmark-overview.png')
