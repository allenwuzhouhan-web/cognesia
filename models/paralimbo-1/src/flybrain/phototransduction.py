"""Explicit initial conditions for normalized-luminance phototransduction.

The legacy dark-start convention remains available. A constant-background
initialization sets *both* adaptation and filtered drive to their equilibrium;
neural equilibrium is a separate operation.
"""
from __future__ import annotations

import numpy as np


class Phototransduction:
    """Assumed luminance adaptation followed by a passive low-pass drive."""

    def __init__(self, n_columns, parameters, initial_luminance=0.):
        self.parameters = parameters
        light = np.asarray(initial_luminance, dtype=float)
        if light.ndim > 1 or (light.ndim == 1 and light.shape != (n_columns,)):
            raise ValueError('Initial luminance must be scalar or one value per column')
        self._validate_light(light)
        self.adaptation = np.broadcast_to(light, (n_columns,)).copy()
        self.drive = np.asarray(self._target(self.adaptation, self.adaptation)).copy()

    @staticmethod
    def _validate_light(light):
        if np.any(~np.isfinite(light)) or np.any((light < 0) | (light > 1)):
            raise ValueError('Luminance must be finite in [0,1]')

    def _target(self, light, adaptation):
        p = self.parameters
        return p['maximum_drive_mv'] * light / (light + p['half_saturation'] + p['adaptation_strength'] * adaptation)

    def step(self, luminance, dt_ms):
        light = np.asarray(luminance, dtype=float)
        self._validate_light(light)
        if not np.isfinite(dt_ms) or dt_ms <= 0:
            raise ValueError('Phototransduction step must be finite and positive')
        p = self.parameters
        self.adaptation += (1-np.exp(-dt_ms/p['adaptation_tau_ms']))*(light-self.adaptation)
        target = self._target(light, self.adaptation)
        self.drive += (1-np.exp(-dt_ms/p['phototransduction_tau_ms']))*(target-self.drive)
        return self.drive.copy()

    def residuals(self, luminance):
        light = np.asarray(luminance, dtype=float)
        self._validate_light(light)
        p = self.parameters
        return {'adaptation_per_ms': (light-self.adaptation)/p['adaptation_tau_ms'],
                'drive_mv_per_ms': (self._target(light,self.adaptation)-self.drive)/p['phototransduction_tau_ms']}
