'use strict';
// Plain text DOM construction keeps model prose and evidence out of HTML parsing.
window.CognesiaReport = (() => {
  const sections = [['abstract','Abstract'], ['methodology','Methodology'], ['data','Data'], ['analysis','Analysis'], ['futures','Futures']];
  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }
  function render(run) {
    const paper = element('article', undefined, 'paper');
    paper.append(element('p', 'COGNESIA / RESEARCH REPORT', 'paper-eyebrow'), element('h1', run.report.title));
    paper.append(element('p', `${new Date(run.started_at * 1000).toLocaleString()} · Simulation study`, 'paper-meta'));
    for (const [key, label] of sections) {
      const section = element('section', undefined, 'paper-section');
      section.append(element('h3', label));
      if (key === 'methodology') section.append(element('p', run.report_scope, 'paper-note'));
      for (const paragraph of run.report[key].split(/\n\n+/)) if (paragraph.trim()) section.append(element('p', paragraph));
      if (key === 'data') {
        for (const [index, figure] of (run.figures || []).entries()) {
          const block = element('figure');
          const image = element('img');
          image.src = `/api/studies/${encodeURIComponent(run.id)}/figures/${encodeURIComponent(figure.figure_id)}.png`;
          image.alt = `${figure.title}; ${figure.sample_count} recorded samples from ${figure.run_id}`;
          block.append(image, element('figcaption', `Figure ${index + 1}. ${figure.title}. ${figure.sample_count} recorded time samples; ${figure.plotted_samples} plotted. Run ${figure.run_id}.`));
          const stats = figure.statistics;
          block.append(element('p', `Mean ${Number(stats.mean_mv).toPrecision(5)} mV · Range ${Number(stats.minimum_mv).toPrecision(5)} to ${Number(stats.maximum_mv).toPrecision(5)} mV · Temporal SD ${Number(stats.temporal_sd_mv).toPrecision(5)} mV`, 'paper-note'));
          const provenance = element('details');
          provenance.append(element('summary', 'Figure source'), element('p', `Summary SHA-256: ${figure.source_sha256}\n${figure.interpretation}`, 'paper-note'));
          block.append(provenance); section.append(block);
        }
        if (run.report.evidence_ids.length) section.append(element('p', `Evidence in the trace: ${run.report.evidence_ids.join(', ')}`, 'paper-note'));
      }
      if (key === 'analysis') {
        const warnings = run.recorded_warnings || [...new Set((run.figures || []).flatMap(figure => figure.warnings || []))];
        if (warnings.length) {
          const limits = element('details', undefined, 'paper-limitations');
          limits.append(element('summary', `Recorded limitations (${warnings.length})`));
          for (const warning of warnings) limits.append(element('p', warning, 'paper-note'));
          section.append(limits);
        }
      }
      paper.append(section);
    }
    return paper;
  }
  return {render};
})();
