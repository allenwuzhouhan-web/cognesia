"""Procedural grayscale visual scenes in global azimuth/elevation degrees."""
from __future__ import annotations
import numpy as np
from .stimulation import available_threads

STIMULI = ('grating', 'flash', 'edge', 'looming', 'apparent_motion', 'dark')


def normalize_options(options=None, frame_rate=240., *, eye_spacing_deg=5.1,
                      point_radius_columns=.45, flash_onset_ms=100.):
    supplied = dict(options or {})
    out = {'stimulus': 'grating', 'duration_ms': 600., 'speed_deg_s': 90.,
           'direction_deg': 0., 'contrast': .8, 'mean_luminance': .5,
           'spatial_period_deg': 30., 'grating_waveform':'square', 'apparent_interval_ms':1000./240.*4,
           'apparent_separation_columns':1., 'threads': min(16, available_threads())}
    unknown = set(supplied) - set(out) - {'node_indices'}
    if unknown:
        raise ValueError('Unknown experiment options: '+', '.join(sorted(unknown)))
    out.update(supplied)
    if out['stimulus'] not in STIMULI:
        raise ValueError('Unknown stimulus')
    for key in ('duration_ms','speed_deg_s','direction_deg','contrast','mean_luminance','spatial_period_deg','apparent_interval_ms','apparent_separation_columns'):
        out[key] = float(out[key])
        if not np.isfinite(out[key]):
            raise ValueError(key+' must be finite')
    if not 300 <= out['duration_ms'] <= 10000 or out['duration_ms'] % 20:
        raise ValueError('duration_ms must be 300-10000 in increments of 20 ms')
    if not 0 <= out['speed_deg_s'] <= 720:
        raise ValueError('speed_deg_s must be in [0,720]')
    if not 0 <= out['contrast'] <= 1 or not 0 <= out['mean_luminance'] <= 1:
        raise ValueError('contrast and mean_luminance must be in [0,1]')
    if not 5 <= out['spatial_period_deg'] <= 180:
        raise ValueError('spatial_period_deg must be in [5,180]')
    if not 0 <= out['apparent_interval_ms'] <= 100:
        raise ValueError('apparent_interval_ms must be in [0,100]')
    if not 0 <= out['apparent_separation_columns'] <= 4 or out['apparent_separation_columns']%1:
        raise ValueError('apparent_separation_columns must be an integer in [0,4]')
    if out['grating_waveform'] not in ('square','sine'):
        raise ValueError('grating_waveform must be square or sine')
    out['apparent_interval_frames'] = int(np.floor(out['apparent_interval_ms']*frame_rate/1000.+.5))
    out['apparent_effective_interval_ms'] = out['apparent_interval_frames']*1000./frame_rate
    out['apparent_interval_quantization_ms'] = out['apparent_effective_interval_ms']-out['apparent_interval_ms']
    out['apparent_flash_duration_ms'] = 1000./frame_rate
    out['eye_spacing_deg'] = float(eye_spacing_deg)
    out['apparent_flash_onset_ms'] = float(flash_onset_ms)
    out['apparent_flash_radius_deg'] = float(point_radius_columns)*out['eye_spacing_deg']
    if not np.isfinite(out['eye_spacing_deg']) or out['eye_spacing_deg'] <= 0:
        raise ValueError('eye_spacing_deg must be finite and positive')
    if not np.isfinite(out['apparent_flash_radius_deg']) or out['apparent_flash_radius_deg'] <= 0:
        raise ValueError('point radius must be finite and positive')
    if not np.isfinite(out['apparent_flash_onset_ms']) or out['apparent_flash_onset_ms'] < 0:
        raise ValueError('flash onset must be finite and nonnegative')
    out['apparent_onset_frame'] = int(np.floor(out['apparent_flash_onset_ms']*frame_rate/1000.+.5))
    out['apparent_effective_onset_ms'] = out['apparent_onset_frame']*1000./frame_rate
    if isinstance(out['threads'], bool) or int(out['threads']) != out['threads'] or not 1 <= int(out['threads']) <= available_threads():
        raise ValueError(f'threads must be an integer in [1,{available_threads()}]')
    out['threads'] = int(out['threads'])
    out['direction_deg'] %= 360
    if out['stimulus'] == 'dark':
        out['mean_luminance'] = 0.
    return out


def luminance(azimuth_deg, elevation_deg, time_ms, options, *, baseline=False):
    """Return scene luminance in [0,1], before optical convolution."""
    az, el = np.broadcast_arrays(azimuth_deg, elevation_deg)
    mean = options['mean_luminance']
    if baseline:
        return np.full(az.shape, mean, dtype=float)
    kind = options['stimulus']
    amplitude = min(mean, 1-mean)*options['contrast']
    direction = np.deg2rad(options['direction_deg'])
    axis = np.cos(direction)*az + np.sin(direction)*el
    t = time_ms/1000.
    speed = options['speed_deg_s']
    if kind == 'dark':
        return np.zeros_like(az, dtype=float)
    if kind == 'grating':
        signal = np.sin(2*np.pi*(axis-speed*t)/options['spatial_period_deg'])
        if options.get('grating_waveform','sine') == 'square':
            signal = np.where(signal >= 0,1.,-1.)
    elif kind == 'flash':
        signal = 1. if .25*options['duration_ms'] <= time_ms < .75*options['duration_ms'] else -1.
    elif kind == 'edge':
        signal = np.where(axis <= speed*(t-options['duration_ms']/2000.), 1., -1.)
    elif kind == 'looming':
        # Expanding dark disk, angular radius rather than an asserted collision time.
        signal = np.where(np.hypot(az, el) <= 2+speed*t, -1., 1.)
    elif kind == 'apparent_motion':
        spacing = options['apparent_separation_columns']*options['eye_spacing_deg']
        dx,dy = .5*spacing*np.cos(direction), .5*spacing*np.sin(direction)
        radius = options['apparent_flash_radius_deg']
        frame = int(np.floor(time_ms/options['apparent_flash_duration_ms']+1e-9))
        first_frame = options['apparent_onset_frame']
        first = (frame == first_frame) & (np.hypot(az+dx,el+dy) <= radius)
        second = (frame == first_frame+options['apparent_interval_frames']) & (np.hypot(az-dx,el-dy) <= radius)
        signal = np.logical_or(first,second).astype(float)
    else:
        raise ValueError('Unknown stimulus')
    return np.broadcast_to(np.clip(mean+amplitude*signal, 0, 1), az.shape).copy()


def preview_frames(times_ms, options, width=96, height=48):
    az, el = np.meshgrid(np.linspace(-180,180,width,endpoint=False), np.linspace(90,-90,height))
    return np.stack([np.rint(255*luminance(az, el, t, options)).astype(np.uint8) for t in times_ms])
