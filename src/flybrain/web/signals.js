/* Fourier analysis of finite, uniformly sampled recorded signals.
 * Coefficients use exp(-i 2πkj/N)/N and phases refer to the first sample.
 * No padding, resampling, extrapolation, or power-spectral-density conversion.
 */

export const MAX_SIGNAL_SAMPLES = 8192;
const TAU = 2 * Math.PI;

function validateSignal(timeMs, values) {
  const n = values?.length;
  if (!Number.isInteger(n) || !Number.isInteger(timeMs?.length))
    throw new Error("Signal times and values must be numeric sample arrays.");
  if (timeMs.length !== n)
    throw new Error("Signal times and values must have the same number of samples.");
  if (n < 2) throw new Error("Fourier analysis needs at least two recorded samples.");
  if (n > MAX_SIGNAL_SAMPLES)
    throw new Error(`Fourier analysis supports at most ${MAX_SIGNAL_SAMPLES} samples per window.`);
  for (let i = 0; i < n; i++) {
    if (!Number.isFinite(timeMs[i]) || !Number.isFinite(values[i]))
      throw new Error("Signal times and values must contain only finite numbers.");
    if (i && timeMs[i] <= timeMs[i - 1])
      throw new Error("Recorded sample times must be strictly increasing.");
  }
  const dt = (timeMs[n - 1] - timeMs[0]) / (n - 1);
  // Accept floating-point representation error, not actual irregular sampling.
  const tolerance = Math.max(
    dt * 1e-6,
    8 * Number.EPSILON * Math.max(1, Math.abs(timeMs[0]), Math.abs(timeMs[n - 1])),
  );
  for (let i = 1; i < n; i++) {
    if (Math.abs(timeMs[i] - timeMs[i - 1] - dt) > tolerance)
      throw new Error("Fourier analysis requires uniformly spaced recorded samples; this window has irregular timing.");
  }
  return { n, dt };
}

function sampleMean(values) {
  let sum = 0, correction = 0;
  for (const value of values) {
    const adjusted = value - correction;
    const next = sum + adjusted;
    correction = next - sum - adjusted;
    sum = next;
  }
  return sum / values.length;
}

function realDFT(values, mean) {
  const n = values.length;
  const bins = Math.floor(n / 2) + 1;
  const real = new Float64Array(bins);
  const imag = new Float64Array(bins);
  real[0] = mean;
  // The bounded, real-only DFT accepts arbitrary N. Trigonometric recurrence
  // avoids millions of transcendental calls; re-anchoring limits roundoff drift.
  for (let k = 1; k < bins; k++) {
    if (n % 2 === 0 && k === n / 2) {
      let sum = 0;
      for (let j = 0; j < n; j++) sum += (j % 2 ? -1 : 1) * values[j];
      real[k] = sum / n;
      continue;
    }
    const step = TAU * k / n;
    const dc = Math.cos(step), ds = Math.sin(step);
    let c = 1, s = 0, re = 0, im = 0;
    for (let j = 0; j < n; j++) {
      if (j && j % 128 === 0) {
        c = Math.cos(step * j);
        s = Math.sin(step * j);
      }
      re += values[j] * c;
      im -= values[j] * s;
      const next = c * dc - s * ds;
      s = s * dc + c * ds;
      c = next;
    }
    real[k] = re / n;
    imag[k] = im / n;
  }
  return { real, imag };
}

function fullCoefficient(real, imag, n, k, demean) {
  const index = (k + n) % n;
  if (index === 0 && demean) return [0, 0];
  if (index <= Math.floor(n / 2)) return [real[index], imag[index]];
  return [real[n - index], -imag[n - index]];
}

/**
 * One-sided amplitude spectrum in the original signal units, phases in radians.
 * Hann means the periodic N-sample Hann window, with coherent-gain correction.
 * The separate seriesReal/seriesImag always preserve unwindowed original data.
 */
export function analyzeSignal(timeMs, values, { demean = false, window = "none" } = {}) {
  const { n, dt } = validateSignal(timeMs, values);
  if (typeof demean !== "boolean") throw new Error("Remove mean must be true or false.");
  if (!["none", "hann"].includes(window))
    throw new Error("Spectrum window must be 'none' or 'hann'.");
  const mean = sampleMean(values);
  const series = realDFT(values, mean);
  const real = new Float64Array(series.real);
  const imag = new Float64Array(series.imag);
  const coherentGain = window === "hann" ? 0.5 : 1;
  if (window === "hann") {
    // Multiplication by 0.5-0.5*cos(2πj/N) is exactly this circular convolution.
    // This uses the N-point DFT as recorded, including odd-N conjugate symmetry.
    for (let k = 0; k < real.length; k++) {
      const center = fullCoefficient(series.real, series.imag, n, k, demean);
      const left = fullCoefficient(series.real, series.imag, n, k - 1, demean);
      const right = fullCoefficient(series.real, series.imag, n, k + 1, demean);
      real[k] = (0.5 * center[0] - 0.25 * (left[0] + right[0])) / coherentGain;
      imag[k] = (0.5 * center[1] - 0.25 * (left[1] + right[1])) / coherentGain;
    }
  } else if (demean) {
    real[0] = 0;
    imag[0] = 0;
  }
  imag[0] = 0;
  if (n % 2 === 0) imag[n / 2] = 0;
  const sampleRateHz = 1000 / dt;
  const resolutionHz = sampleRateHz / n;
  const frequenciesHz = new Float64Array(real.length);
  const amplitudes = new Float64Array(real.length);
  const phases = new Float64Array(real.length);
  for (let k = 0; k < real.length; k++) {
    const factor = k === 0 || (n % 2 === 0 && k === n / 2) ? 1 : 2;
    frequenciesHz[k] = k * resolutionHz;
    amplitudes[k] = factor * Math.hypot(real[k], imag[k]);
    phases[k] = Math.atan2(imag[k], real[k]);
  }
  return {
    n, sampleIntervalMs: dt, sampleRateHz, nyquistHz: sampleRateHz / 2,
    resolutionHz, frequencyResolutionHz: resolutionHz,
    mean, timeOriginMs: timeMs[0], recordSpanMs: timeMs[n - 1] - timeMs[0],
    periodMs: n * dt, frequenciesHz, amplitudes, phases, real, imag,
    demean, window, coherentGain, phaseUnit: "radians",
    amplitudeNormalization: "One-sided amplitude in original signal units; not PSD",
    seriesReal: series.real, seriesImag: series.imag,
    seriesWindow: "none", seriesDemean: false, coefficientNormalization: "1/N",
  };
}

/** Reconstruct DC plus harmonics 1..K at the original relative sample positions. */
export function reconstructSeries(analysis, harmonics = Math.floor(analysis?.n / 2)) {
  const n = analysis?.n;
  if (!Number.isInteger(n) || n < 2 || n > MAX_SIGNAL_SAMPLES
      || analysis?.seriesWindow !== "none" || analysis?.seriesDemean !== false
      || analysis?.coefficientNormalization !== "1/N")
    throw new Error("Reconstruction requires original unwindowed Fourier-series coefficients.");
  const real = analysis.seriesReal, imag = analysis.seriesImag;
  const bins = Math.floor(n / 2) + 1;
  if (real?.length !== bins || imag?.length !== bins
      || !Array.from(real).every(Number.isFinite) || !Array.from(imag).every(Number.isFinite))
    throw new Error("Original Fourier-series coefficients are missing or invalid.");
  if (!Number.isFinite(harmonics) || !Number.isInteger(harmonics))
    throw new Error("The number of reconstruction harmonics must be a whole number.");
  const count = Math.max(0, Math.min(bins - 1, harmonics));
  const result = new Float64Array(n).fill(real[0]);
  for (let k = 1; k <= count; k++) {
    if (n % 2 === 0 && k === n / 2) {
      for (let j = 0; j < n; j++) result[j] += real[k] * (j % 2 ? -1 : 1);
      continue;
    }
    const step = TAU * k / n;
    const dc = Math.cos(step), ds = Math.sin(step);
    let c = 1, s = 0;
    for (let j = 0; j < n; j++) {
      if (j && j % 128 === 0) {
        c = Math.cos(step * j);
        s = Math.sin(step * j);
      }
      result[j] += 2 * (real[k] * c - imag[k] * s);
      const next = c * dc - s * ds;
      s = s * dc + c * ds;
      c = next;
    }
  }
  return result;
}

export function reconstructSignal(timeMs, values, harmonics) {
  return reconstructSeries(analyzeSignal(timeMs, values), harmonics);
}

/** Snap an inclusive interval to the nearest recorded samples; never resample. */
export function selectSignalInterval(timeMs, values, interval = null) {
  if (!timeMs?.length || timeMs.length !== values?.length)
    throw new Error("The signal's sample times and values do not match.");
  for (let i = 0; i < timeMs.length; i++) {
    if (!Number.isFinite(timeMs[i]) || (i && timeMs[i] <= timeMs[i - 1]))
      throw new Error("Recorded sample times must be finite and strictly increasing.");
  }
  const nearest = (value) => {
    let lo = 0, hi = timeMs.length - 1;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (timeMs[mid] < value) lo = mid + 1; else hi = mid; }
    return lo && Math.abs(timeMs[lo - 1] - value) < Math.abs(timeMs[lo] - value) ? lo - 1 : lo;
  };
  let startIndex = 0, endIndex = timeMs.length - 1;
  if (interval) {
    if (interval.length !== 2 || !interval.every(Number.isFinite)) throw new Error("Choose finite start and end times.");
    const [start, end] = [...interval].sort((a, b) => a - b);
    if (end < timeMs[0] || start > timeMs.at(-1)) throw new Error("The selected interval is outside this recording.");
    startIndex = nearest(start); endIndex = nearest(end);
  }
  if (endIndex <= startIndex) throw new Error("Select at least two distinct recorded samples.");
  return { timeMs: Float64Array.from(timeMs.slice(startIndex, endIndex + 1)),
    values: Float64Array.from(values.slice(startIndex, endIndex + 1)), startIndex, endIndex,
    startMs: timeMs[startIndex], endMs: timeMs[endIndex] };
}

export function formatFourierEquation(mean, terms, timeOriginMs) {
  const number=value=>Number(value.toPrecision(8)).toString();
  const shown=terms.filter(term=>term.amplitude>Math.max(1,Math.abs(mean))*1e-12);
  return `y(t) ≈ ${number(mean)}` + shown.slice(0,64).map(term=>
    ` + ${number(term.amplitude)} cos(2π·${number(term.frequencyHz)}·(t − ${number(timeOriginMs/1000)}) ${term.phaseRadians<0?"−":"+"} ${number(Math.abs(term.phaseRadians))})`).join("")
    + (shown.length>64?` + [${shown.length-64} further terms; export JSON for every coefficient]`:"");
}

/** Normalize the large-window server result to the same seconds-based equation as the worker. */
export function serverFourierResult(data, unit="a.u.") {
  const n=data.sample_count??data.time_ms?.length;
  if(!Number.isInteger(n)||n<2||data.reconstruction?.length!==n||data.residuals?.length!==n||!data.frequencies_hz||!data.amplitudes)
    throw new Error("The analysis service returned incomplete Fourier samples.");
  const terms=(data.coefficients||[]).map(c=>({harmonic:c.k,frequencyHz:c.frequency_hz,amplitude:Math.hypot(c.cos,c.sin),phaseRadians:Math.atan2(-c.sin,c.cos),nyquist:n%2===0&&c.k===n/2,cos:c.cos,sin:c.sin}));
  return {analysis:{n,sampleIntervalMs:data.sample_interval_ms,nyquistHz:data.nyquist_hz,resolutionHz:data.resolution_hz,
    periodMs:data.period_ms,timeOriginMs:data.time_origin_ms,frequenciesHz:data.frequencies_hz,amplitudes:data.amplitudes},
    fit:{fitted:data.reconstruction,residual:data.residuals,rmse:data.rmse,rSquared:data.r_squared??(data.rmse<1e-10?1:0),
      equation:formatFourierEquation(data.dc,terms,data.time_origin_ms),terms,mean:data.dc,timeOriginMs:data.time_origin_ms,
      periodMs:data.period_ms,startMs:data.range?.start_ms??data.time_ms[0],endMs:data.range?.end_ms??data.time_ms.at(-1),
      harmonics:data.harmonics,sampleCount:n,unit,timeUnit:"seconds"}};
}

/** Equation and residual use original, unwindowed coefficients, never the display spectrum. */
export function describeFourierFit(analysis, original, harmonics, unit = "a.u.") {
  const fitted = reconstructSeries(analysis, harmonics);
  if (original?.length !== fitted.length || !Array.from(original).every(Number.isFinite))
    throw new Error("Fit samples must match the original analysis.");
  const count = Math.max(0, Math.min(Math.floor(analysis.n / 2), harmonics));
  const terms = [];
  for (let k = 1; k <= count; k++) {
    const nyquist = analysis.n % 2 === 0 && k === analysis.n / 2;
    const re = analysis.seriesReal[k], im = analysis.seriesImag[k];
    terms.push({ harmonic: k, frequencyHz: k * analysis.resolutionHz,
      amplitude: (nyquist ? 1 : 2) * Math.hypot(re, im), phaseRadians: Math.atan2(im, re), nyquist });
  }
  const residual = Float64Array.from(original, (value, i) => value - fitted[i]);
  let sse = 0, total = 0, maxAbsoluteError = 0;
  for (let i = 0; i < original.length; i++) {
    sse += residual[i] ** 2; total += (original[i] - analysis.mean) ** 2;
    maxAbsoluteError = Math.max(maxAbsoluteError, Math.abs(residual[i]));
  }
  const equation = formatFourierEquation(analysis.mean,terms,analysis.timeOriginMs);
  return { fitted, residual, rmse: Math.sqrt(sse / original.length),
    rSquared: total > 0 ? 1 - sse / total : (sse < 1e-20 ? 1 : 0), maxAbsoluteError,
    equation, unit, timeUnit: "seconds", timeOriginMs: analysis.timeOriginMs,
    periodMs: analysis.periodMs, startMs: analysis.timeOriginMs,
    endMs: analysis.timeOriginMs + analysis.recordSpanMs,
    mean: analysis.mean, harmonics: count, terms, sampleCount: original.length,
    interpretation: "Finite-interval periodic Fourier approximation, not an inferred biological governing equation." };
}
