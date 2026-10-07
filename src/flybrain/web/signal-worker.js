import { analyzeSignal, describeFourierFit } from "./signals.js";

self.onmessage = ({ data }) => {
  try {
    const analysis = analyzeSignal(data.timeMs, data.values, data.options);
    const fit = data.harmonics == null ? null : describeFourierFit(analysis, data.values, data.harmonics, data.unit);
    self.postMessage({ id: data.id, analysis, fit });
  } catch (error) { self.postMessage({ id: data.id, error: error.message }); }
};
