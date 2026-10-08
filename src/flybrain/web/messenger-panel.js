// Read-only evidence catalogue; reading a candidate never enables dynamics.
const host = document.querySelector('#messenger-catalog');
if (host) {
  fetch('/api/messengers').then(async response => {
    if (!response.ok) throw new Error('Messenger catalogue is unavailable');
    return response.json();
  }).then(catalog => {
    const entries = catalog.messengers || catalog.entries || [];
    host.replaceChildren();
    const heading = document.createElement('h3'); heading.textContent = 'Messenger evidence';
    const note = document.createElement('p'); note.className = 'mapping-note';
    note.textContent = 'Existing model fields and source-backed candidates. Candidate tags have no assigned kinetics and do not enable new dynamics.';
    const list = document.createElement('div'); list.className = 'messenger-evidence-list';
    for (const item of entries) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      const status = item.implementation_status === 'candidate_tag_only' ? 'candidate · tag only' : item.implementation_status.replaceAll('_',' ');
      summary.textContent = `${item.name} · ${status}`;
      const description = document.createElement('p'); description.textContent = item.limitations;
      details.append(summary, description);
      for (const evidence of item.evidence || []) {
        const link = document.createElement('a'); link.textContent = evidence.title;
        if (evidence.url.startsWith('https://')) link.href = evidence.url;
        link.target = '_blank'; link.rel = 'noopener noreferrer'; details.append(link);
      }
      list.append(details);
    }
    host.append(heading, note, list);
  }).catch(error => { host.textContent = error.message; });
}
