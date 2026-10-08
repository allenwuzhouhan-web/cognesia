"""Evidence-backed figure snapshots and the research console's five-part paper.

Figures are rendered from recorded numeric samples. Their statistics are the text
model's input; no screenshot is presented as if a text-only model had seen pixels.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import threading
from xml.sax.saxutils import escape

import numpy as np

SECTIONS = (('abstract', 'Abstract'), ('methodology', 'Methodology'), ('data', 'Data'),
            ('analysis', 'Analysis'), ('futures', 'Futures'))
GROUPS = {'type': 'traces', 'region': 'region_traces', 'class': 'class_traces'}
PLOT_LOCK = threading.Lock()


def prose_fields(**descriptions):
    return {'type': 'object', 'properties': {key: {'type': 'string', 'maxLength': 3000, 'description': description}
                                           for key, description in descriptions.items()},
            'required': list(descriptions), 'additionalProperties': False}


REPORT_TOOL = {'type': 'function', 'function': {
    'name': 'cognesia_write_report',
    'description': 'Finish the study as a concise academic report. Supply plain prose, without Markdown headings. The app lays out the five sections and captured figures and makes a PDF.',
    'parameters': {'type': 'object', 'properties': {
        'title': {'type': 'string', 'maxLength': 180},
        **{key: {'type': 'string', 'maxLength': 6000, 'description': description} for key, description in (
            ('abstract', 'A short TLDR: question, what was actually done, principal observation, and its limit.'),
            ('data', 'Only returned observations, with units, source run IDs, sample counts and references such as Figure 1. Keep minimum, positive maximum and maximum absolute magnitude distinct. Explicitly say when no new experimental data were collected.'),
        )},
        'methodology': prose_fields(
            experimental_design='Describe the actual model, stimulus and all active co-interventions, duration, sampling and seeds. Use only recorded units. Explain how the outcome was computed.',
            experimental_units='Actual run and replicate counts, selected population and time samples. Distinguish historical recordings from newly executed experiments and model cells from independent bodies.',
            control='Describe the recorded baseline exactly, including which inputs differ between arms. A constant-luminance control does not receive the drifting grating. State unknown controls explicitly.'),
        'analysis': prose_fields(
            interpretation='What the observed data might suggest, alternatives and confounding. Separate observation from inference. A single recording cannot establish whether a response is reproducible; comparison of a mean with temporal SD is not a test of an effect.',
            limitations='Uncertainty, failed runs and validation gates. Temporal variability is not uncertainty across independent experiments. Descriptive trace statistics do not establish significance, equivalence, or absence of a response.'),
        'futures': prose_fields(
            next_experiments='Specific next experiments: condition/control, outcome to measure and a criterion for success. Do not put references here. Passing a stability gate requires evidence, not enabling it.',
            generalization='State what can currently generalize, what cannot, and what additional evidence is needed for other conditions, models or living organisms. Seeds test optical sampling variability, not biological replication.'),
        'evidence_ids': {'type': 'array', 'items': {'type': 'string'}, 'maxItems': 50,
                         'description': 'Tool-call IDs from the supplied evidence list. Empty only when no evidence was returned.'},
    }, 'required': ['title', *(key for key, _ in SECTIONS), 'evidence_ids'], 'additionalProperties': False}}}


def load_recording(root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', run_id):
        raise ValueError('Invalid recording identity')
    path = Path(root) / 'runs' / run_id / 'visual_summary.json'
    if not path.is_file():
        raise ValueError('Recording summary is unavailable')
    if path.stat().st_size > 128 * 1024 * 1024:
        raise ValueError('Recording summary exceeds the 128 MB figure limit')
    raw = path.read_bytes()
    summary = json.loads(raw)
    if not isinstance(summary, dict) or summary.get('id') != run_id:
        raise ValueError('Recording identity does not match its saved summary')
    return summary, hashlib.sha256(raw).hexdigest()


def recording_evidence(summary, source_hash):
    """A compact view that does not send megabytes of repeated traces to the LLM."""
    frames = summary.get('frames', {})
    times = frames.get('time_ms', [])
    metadata = summary.get('metadata', {})
    options = summary.get('stimulus', {})
    kind = options.get('stimulus', options.get('type'))
    fields = {'stimulus', 'type', 'duration_ms', 'contrast', 'mean_luminance'}
    fields.update({'grating': {'speed_deg_s', 'direction_deg', 'spatial_period_deg', 'grating_waveform'},
                   'edge': {'speed_deg_s', 'direction_deg'}, 'looming': {'speed_deg_s'},
                   'flash': set(), 'dark': set(),
                   'apparent_motion': {key for key in options if key.startswith('apparent_')} | {'direction_deg', 'eye_spacing_deg'}
                  }.get(kind, set(options)))
    stimulus = {key: value for key, value in options.items() if key in fields}
    chemistry = summary.get('chemistry', {})
    return {
        'run_id': summary['id'], 'label': summary.get('label'), 'source_sha256': source_hash,
        'source': 'Recorded simulation summary', 'biological_specimens_in_this_recording': 0,
        'model_id': summary.get('model_id', 'not recorded'),
        'model_hash': summary.get('model_hash', metadata.get('model_fingerprint')),
        'code_revision': metadata.get('git_hash'), 'code_had_local_changes': metadata.get('git_dirty'),
        'seed': metadata.get('seed'), 'random_input': metadata.get('random_input'),
        'neuron_count': summary.get('neuron_count'), 'simulation_scope': summary.get('simulation_scope'),
        'stimulus': stimulus, 'stats': summary.get('stats', {}),
        'units': {'mean_luminance': 'Normalized scene value in [0,1]; no calibrated cd/m2 or lux value is recorded',
                  'contrast': 'Fraction in [0,1]', 'voltage': 'Model membrane voltage in mV',
                  'chemical_levels': 'Arbitrary normalized units; not a physical concentration or dose'},
        'protocol': {'engine': metadata.get('engine'), 'integration_dt_ms': metadata.get('integration_dt_ms'),
                     'pre_equilibration_ms': metadata.get('pre_equilibration_ms'),
                     'baseline': metadata.get('baseline', 'Control details not recorded'),
                     'external_input': metadata.get('external_input'),
                     'electrodes': metadata.get('electrodes', options.get('electrodes', [])),
                     'electrode_baseline': metadata.get('electrode_baseline'),
                     'chemical_intervention': chemistry.get('chemical_intervention'),
                     'chemistry_enabled': chemistry.get('enabled'),
                     'paired_initialization': chemistry.get('paired_initialization'),
                     'session': metadata.get('session'),
                     'validation_status': metadata.get('original_validation_status')},
        'sampling': {'count': frames.get('count'), 'dt_ms': frames.get('dt_ms'),
                     'first_ms': times[0] if times else None, 'last_ms': times[-1] if times else None},
        'available_traces': {group: [t.get('name', t.get('label')) for t in summary.get(key, [])]
                             for group, key in GROUPS.items()},
        'warnings': summary.get('warnings', []), 'interpretation': summary.get('interpretation'),
    }


def capture_figure(summary, source_hash, *, group, trace, series):
    if group not in GROUPS or series not in ('raw', 'baseline', 'delta'):
        raise ValueError('Choose a known trace group and raw, baseline or delta series')
    candidates = [item for item in summary.get(GROUPS[group], [])
                  if item.get('name', item.get('label')) == trace]
    if len(candidates) != 1:
        raise ValueError('Trace name must match one available_traces entry from cognesia_report_data')
    selected = candidates[0]
    values = selected.get(series + '_mv', selected.get('values' if series == 'delta' else series))
    t = np.asarray(summary.get('frames', {}).get('time_ms', []), dtype=float)
    y = np.asarray(values, dtype=float)
    if t.ndim != 1 or y.shape != t.shape or not 2 <= t.size <= 1_000_000:
        raise ValueError('This trace needs 2 to 1,000,000 matching recorded samples')
    if not np.isfinite(t).all() or not np.isfinite(y).all() or np.any(np.diff(t) <= 0):
        raise ValueError('Trace samples must be finite and time must increase; invalid samples were not discarded')
    # Preserve each bucket's extrema when a long recording needs visual reduction.
    indices = np.arange(t.size)
    if t.size > 2000:
        chosen = {0, t.size - 1}
        for block in np.array_split(indices, 999):
            chosen.update((int(block[np.argmin(y[block])]), int(block[np.argmax(y[block])])))
        indices = np.asarray(sorted(chosen))
    identifier = hashlib.sha256(f'{source_hash}:{group}:{trace}:{series}'.encode()).hexdigest()[:24]
    label = f'{trace} - ' + {'raw': 'experiment voltage', 'baseline': 'matched control', 'delta': 'experiment minus matched control'}[series]
    # Figure and canvas objects avoid pyplot global state; serialize font/cache access.
    with PLOT_LOCK:
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        figure = Figure(figsize=(8.4, 3.8), dpi=150, facecolor='white', layout='constrained')
        FigureCanvasAgg(figure)
        ax = figure.subplots()
        ax.plot(t[indices], y[indices], color='#2b5e83', linewidth=1.35)
        ax.set(xlabel='Recorded time (ms)',
               ylabel='Voltage difference (mV)' if series == 'delta' else 'Membrane voltage (mV)', title=label)
        ax.grid(alpha=.18)
        ax.spines[['top', 'right']].set_visible(False)
        buffer = BytesIO()
        figure.savefig(buffer, format='png', dpi=150)
    return {
        'figure_id': identifier, 'run_id': summary['id'], 'title': label,
        'source_sha256': source_hash, 'group': group, 'trace': trace, 'series': series,
        'unit': 'mV', 'sample_count': int(t.size), 'plotted_samples': int(indices.size),
        'recorded_neurons': selected.get('n_recorded'), 'total_population_neurons': selected.get('n_total'),
        'weighting': selected.get('weighting', 'Arithmetic population mean'),
        'time_range_ms': [float(t[0]), float(t[-1])],
        'statistics': {'minimum_mv': float(y.min()), 'maximum_mv': float(y.max()),
                       'mean_mv': float(y.mean()), 'temporal_sd_mv': float(y.std()),
                       'maximum_at_ms': float(t[np.argmax(y)]),
                       'maximum_absolute_mv': float(np.abs(y).max()),
                       'maximum_absolute_at_ms': float(t[np.argmax(np.abs(y))]),
                       'net_change_mv': float(y[-1] - y[0]),
                       'integral_mv_s': float(np.trapezoid(y, t / 1000))},
        'warnings': summary.get('warnings', []),
        'control_definition': summary.get('metadata', {}).get('baseline', 'Control details not recorded'),
        'interpretation': 'Chart snapshot and statistics from the same recorded population-mean samples. Temporal SD is not uncertainty across independent experiments. GPT-OSS receives numeric evidence; it does not inspect pixels.',
        'png_base64': base64.b64encode(buffer.getvalue()).decode('ascii'),
    }


def validate_report(value, evidence_ids):
    from .api_tools import _validate
    _validate(value, REPORT_TOOL['function']['parameters'])
    if len(value['evidence_ids']) > 50 or set(value['evidence_ids']) - set(evidence_ids):
        raise ValueError('Report cites an unknown tool-call ID')
    if evidence_ids and not value['evidence_ids']:
        raise ValueError('Cite at least one supplied evidence ID')
    result = dict(value)
    for section in ('methodology', 'analysis', 'futures'):
        for field, text in value[section].items():
            if not text.strip():
                raise ValueError(f'Report {section}.{field} must contain prose')
        fields = REPORT_TOOL['function']['parameters']['properties'][section]['properties']
        result[section] = '\n\n'.join(value[section][field] for field in fields)
    for key in ('title', *(key for key, _ in SECTIONS)):
        text = result[key].strip()
        if not text:
            raise ValueError(f'Report {key} must contain prose')
        if any(identity in text for identity in evidence_ids):
            raise ValueError('Tool-call IDs belong only in evidence_ids. Section prose must discuss the experiment; Futures must contain next experiments and generalization.')
        if key in ('abstract', 'data', 'analysis'):
            unsupported = re.search(r'statistically\s+(?:in)?significant|(?:no|not\s+a)\s+(?:detectable|significant|robust)\s+(?:response|effect|signal)|did\s+not\s+(?:produce|show|yield)\b[^.!?]{0,60}\b(?:robust|reproducible|significant)\b', text, re.I)
            if unsupported:
                raise ValueError(f'Rewrite {key}: remove the phrase "{unsupported.group()}". The tools returned descriptive trace statistics, not a hypothesis test or detection threshold. State the values and that independent replication and a predefined inferential test would be needed. Comparing mean with temporal SD is not a test of an effect.')
        # Headings are generated by the renderer, never exposed as Markdown tokens.
        text = re.sub(r'(?m)^\s*#{1,6}\s*', '', text)
        text = re.sub(r'\*\*(.*?)\*\*', r'\1', text, flags=re.S)
        text = re.sub(r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'\1', text)
        text = re.sub(r'`([^`\n]+)`', r'\1', text)
        result[key] = text.translate(str.maketrans({'\u2010': '-', '\u2011': '-', '\u2012': '-',
            '\u2013': '-', '\u2014': ' - ', '\u2212': '-', '\u202f': ' ', '\u00a0': ' '}))
    return result


def study_scope(run):
    results = [e for e in run.get('events', []) if e['kind'] == 'tool_result'
               and isinstance(e.get('result'), dict) and not e['result'].get('call_failed') and not e['result'].get('error')]
    inputs = {e.get('call_id'): e.get('arguments', {}) for e in run.get('events', []) if e['kind'] == 'tool_start'}
    submitted = sum(e['name'] == 'cognesia_start' for e in results)
    recordings = {inputs.get(e.get('call_id'), {}).get('run_id', e['result'].get('run_id', e['result'].get('id'))) for e in results
                  if e['name'] in ('cognesia_report_data', 'cognesia_run_summary', 'cognesia_capture_figure')}
    recordings.discard(None)
    return f'Live organisms used in this software study: 0. Simulations submitted: {submitted}. Saved recordings inspected: {len(recordings)}. Neurons and time samples are not independent experimental bodies.'


def recorded_limitations(run):
    notes = []
    for event in run.get('events', []):
        result = event.get('result')
        if event['kind'] != 'tool_result' or not isinstance(result, dict):
            continue
        if event.get('name') in ('cognesia_report_data', 'cognesia_run_summary', 'cognesia_capture_figure'):
            notes.extend(w for w in result.get('warnings', []) if isinstance(w, str))
        if result.get('call_failed'):
            notes.append(f'Evidence call {event["name"]} failed: {result.get("error", "unavailable")}')
    for figure in run.get('figures', []):
        notes.extend(figure.get('warnings', []))
    return list(dict.fromkeys(notes))


def report_pdf(run, figures):
    """Render the same validated report displayed in the app, with real figures."""
    from matplotlib import get_data_path
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, KeepTogether

    with PLOT_LOCK:
        for name, filename in (('Cognesia', 'DejaVuSans.ttf'), ('CognesiaBold', 'DejaVuSans-Bold.ttf')):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(Path(get_data_path()) / 'fonts/ttf' / filename)))
    out = BytesIO()
    paper = run['report']
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=52, leftMargin=52,
                            topMargin=52, bottomMargin=48, title=paper['title'], author='Cognesia Research')
    body = ParagraphStyle('body', fontName='Cognesia', fontSize=10, leading=15,
                          textColor=colors.HexColor('#263545'), spaceAfter=9, alignment=TA_LEFT)
    small = ParagraphStyle('small', parent=body, fontSize=8, leading=12, textColor=colors.HexColor('#5b6877'))
    heading = ParagraphStyle('heading', parent=body, fontName='CognesiaBold', fontSize=17,
                             leading=22, spaceBefore=17, spaceAfter=9, keepWithNext=True)
    title = ParagraphStyle('title', parent=heading, fontSize=24, leading=30, spaceBefore=0, spaceAfter=12)
    def para(text, style=body):
        return Paragraph(escape(str(text)).replace('\n', '<br/>'), style)
    story = [para('COGNESIA  /  RESEARCH REPORT', small), para(paper['title'], title)]
    stamp = datetime.fromtimestamp(run.get('started_at', 0), timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    status = {'budget_reached': 'Research call limit reached', 'output_limit': 'Research conclusion reached its token limit',
              'completed': 'Completed report', 'cancelled': 'Study stopped'}.get(run.get('status'), 'Research report')
    story += [para(f'{stamp}  |  {status}', small)]
    for key, label in SECTIONS:
        story.append(para(label, heading))
        if key == 'methodology':
            story.append(para(study_scope(run), small))
        for block in paper[key].split('\n\n'):
            if block.strip():
                story.append(para(block))
        if key == 'data':
            for index, metadata in enumerate(run.get('figures', []), 1):
                png = figures[metadata['figure_id']]['png']
                caption = f'Figure {index}. {metadata["title"]}. Run {metadata["run_id"]}. {metadata["sample_count"]} recorded time samples; {metadata["plotted_samples"]} plotted. Source SHA-256: {metadata["source_sha256"]}.'
                story.append(KeepTogether([Image(BytesIO(png), width=doc.width, height=doc.width * 3.8 / 8.4), para(caption, small)]))
                stats = metadata['statistics']
                story.append(para(f'Mean: {stats["mean_mv"]:.6g} mV; range: {stats["minimum_mv"]:.6g} to {stats["maximum_mv"]:.6g} mV; temporal SD: {stats["temporal_sd_mv"]:.6g} mV; integral: {stats["integral_mv_s"]:.6g} mV s.', small))
            if paper['evidence_ids']:
                story.append(para('Evidence in the exported trace: ' + ', '.join(paper['evidence_ids']), small))
        if key == 'analysis':
            warnings = recorded_limitations(run)
            if warnings:
                story.append(para('Recorded limitations', small))
                story.extend(para(w, small) for w in warnings)
    def footer(canvas, _):
        canvas.saveState()
        canvas.setFont('Cognesia', 8)
        canvas.setFillColor(colors.HexColor('#6b7785'))
        canvas.drawString(52, 27, 'Cognesia | Generated research summary | Simulation evidence')
        canvas.drawRightString(A4[0] - 52, 27, str(doc.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
