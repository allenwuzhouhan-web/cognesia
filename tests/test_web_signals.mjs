import test from 'node:test';
import assert from 'node:assert/strict';
import { analyzeSignal, reconstructSeries, reconstructSignal } from '../src/flybrain/web/signals.js';

const times = (n, dt = 2, origin = 0) => Float64Array.from({ length: n }, (_, j) => origin + dt * j);
const values = (n, f) => Float64Array.from({ length: n }, (_, j) => f(j));
const close = (a, b, epsilon = 1e-10) => assert.ok(Math.abs(a-b) < epsilon, `${a} should equal ${b}`);
const vectorClose = (a, b, epsilon = 1e-10) => {
  assert.equal(a.length, b.length);
  for (let j = 0; j < a.length; j++) close(a[j], b[j], epsilon);
};

test('DC, metadata, and zero-harmonic reconstruction retain a negative mean', () => {
  const a = analyzeSignal(times(64, 2, 123), values(64, () => -52));
  close(a.mean, -52); close(a.amplitudes[0], 52);
  close(a.phases[0], Math.PI);
  close(a.sampleIntervalMs, 2); close(a.sampleRateHz, 500);
  close(a.nyquistHz, 250); close(a.resolutionHz, 500 / 64);
  close(a.timeOriginMs, 123); close(a.periodMs, 128); close(a.recordSpanMs, 126);
  vectorClose(reconstructSeries(a, 0), values(64, () => -52));
});

test('on-bin cosine amplitude and phase use relative window time', () => {
  const n = 128, phase = 0.63, amplitude = 3.5, k = 7;
  const x = values(n, j => amplitude * Math.cos(2 * Math.PI * k * j/n + phase));
  const a = analyzeSignal(times(n, 0.5, 741), x);
  close(a.amplitudes[k], amplitude); close(a.phases[k], phase);
  close(a.frequenciesHz[k], k * 2000/n);
  vectorClose(reconstructSeries(a, k), x);
});

test('sine phase sign and two-tone first-K selection are correct', () => {
  const n = 90;
  const low = values(n, j => 4 + 2 * Math.sin(2 * Math.PI * 3*j/n));
  const x = values(n, j => low[j] + 9 * Math.cos(2 * Math.PI * 11*j/n));
  const a = analyzeSignal(times(n), x);
  close(a.amplitudes[3], 2); close(a.phases[3], -Math.PI/2);
  close(a.amplitudes[11], 9);
  vectorClose(reconstructSeries(a, 3), low); // Not the three largest components.
  vectorClose(reconstructSeries(a), x);
});

test('even-N Nyquist is never doubled and reconstructs exactly once', () => {
  const n = 80, x = values(n, j => 2 + 7 * (j % 2 ? -1 : 1));
  const a = analyzeSignal(times(n), x);
  close(a.amplitudes[n/2], 7);
  close(a.frequenciesHz[n/2], a.nyquistHz);
  vectorClose(reconstructSeries(a, n/2), x);
});

test('odd-N highest bin is doubled and is below Nyquist', () => {
  const n = 31, k = 15, x = values(n, j => 1 + 3 * Math.cos(2*Math.PI*k*j/n + 0.2));
  const a = analyzeSignal(times(n), x);
  close(a.amplitudes[k], 3); close(a.phases[k], .2);
  assert.ok(a.frequenciesHz[k] < a.nyquistHz);
  vectorClose(reconstructSeries(a, k), x);
});

test('periodic Hann amplitude is coherent-gain corrected; reconstruction retains original DC', () => {
  const n = 120, x = values(n, j => -52 + 6 * Math.cos(2*Math.PI*9*j/n + .4));
  const a = analyzeSignal(times(n), x, { demean: true, window: 'hann' });
  close(a.coherentGain, .5); close(a.amplitudes[9], 6); close(a.phases[9], .4);
  close(a.amplitudes[0], 0);
  close(a.seriesReal[0], -52);
  vectorClose(reconstructSeries(a, 9), x);
  vectorClose(reconstructSeries(a, 0), values(n, () => -52));
});

test('Hann spectrum matches a direct windowed DFT for odd/even N including DC/Nyquist', () => {
  for (const n of [2, 3, 17, 32]) {
    const x = values(n, j => 2 + Math.sin(j*.73) + Math.cos(j*2.14));
    for (const demean of [true, false]) {
      const a = analyzeSignal(times(n), x, { demean, window: 'hann' });
      for (let k = 0; k <= Math.floor(n/2); k++) {
        let re = 0, im = 0;
        for (let j = 0; j < n; j++) {
          const v = (x[j] - (demean ? a.mean : 0)) * (.5 - .5*Math.cos(2*Math.PI*j/n));
          re += v*Math.cos(2*Math.PI*k*j/n)/(n*.5);
          im -= v*Math.sin(2*Math.PI*k*j/n)/(n*.5);
        }
        close(a.real[k], re); close(a.imag[k], im);
        close(a.amplitudes[k], Math.hypot(re, im) * (k === 0 || n%2 === 0 && k === n/2 ? 1 : 2));
      }
      vectorClose(reconstructSeries(a), x);
    }
  }
});

test('full arbitrary-N reconstruction, no padding, and bounded harmonic counts', () => {
  for (const n of [2, 3, 37, 100, 257]) {
    const x = values(n, j => -13 + Math.sin(j*j*.15) + Math.cos(j*.717));
    const a = analyzeSignal(times(n, 1000/240, 313.25), x);
    assert.equal(a.n, n); assert.equal(a.real.length, Math.floor(n/2)+1);
    close(a.resolutionHz, 240/n);
    vectorClose(reconstructSeries(a, n), x);
    vectorClose(reconstructSignal(times(n), x, n), x);
    vectorClose(reconstructSeries(a, -2), values(n, () => a.mean));
  }
});

test('invalid sampling and non-original coefficients produce meaningful errors', () => {
  assert.throws(() => analyzeSignal([0], [1]), /at least two/);
  assert.throws(() => analyzeSignal([0, 1], [1]), /same number/);
  assert.throws(() => analyzeSignal([0, 1], [NaN, 1]), /finite/);
  assert.throws(() => analyzeSignal([0, Infinity], [1, 2]), /finite/);
  assert.throws(() => analyzeSignal([0, 0], [1, 2]), /increasing/);
  assert.throws(() => analyzeSignal([1, 0], [1, 2]), /increasing/);
  assert.throws(() => analyzeSignal([0, 1, 2.1], [1, 2, 3]), /uniformly/);
  assert.throws(() => analyzeSignal([0, 1], ['1', 2]), /finite/);
  assert.throws(() => analyzeSignal([0, 1], [1, 2], { window: 'fake' }), /window/);
  const a = analyzeSignal([0, 1], [1, 2]);
  assert.throws(() => reconstructSeries({ ...a, seriesWindow: 'hann' }, 1), /unwindowed/);
  assert.throws(() => reconstructSeries(a, .5), /whole number/);
});
