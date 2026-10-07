/** Source-backed sensory maps. Optical columns and neural ports keep their source identities. */
const asArray = value => Array.isArray(value) ? value : [];
const text = value => value === null || value === undefined ? '' : String(value);
const display = value => text(value).replaceAll('_', ' ');
const knownNumber = value => value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value));

export function describeEyeColumn(column, index, receptors = []) {
  if (!column) return null;
  const columnIndex = column.column_index ?? index;
  const assigned = asArray(receptors).filter(item => item.column_index === columnIndex);
  const source = text(column.assignment_source);
  const status = /assumption|position-ranked|modeled/i.test(source) ? 'Modeled column'
    : /cross.specimen|homology|transfer/i.test(source) ? 'Cross-specimen mapping'
      : source ? 'Source column' : 'Source geometry; optical angles assumed';
  return {index, columnIndex, id: text(column.column_id ?? columnIndex),
    side: display(column.hemisphere || column.side || 'unassigned'), status, source,
    coordinate: knownNumber(column.p) && knownNumber(column.q) ? `p ${column.p}, q ${column.q}` : 'Coordinates unavailable',
    angles: knownNumber(column.azimuth_deg) && knownNumber(column.elevation_deg)
      ? `${Number(column.azimuth_deg).toFixed(1)}° azimuth · ${Number(column.elevation_deg).toFixed(1)}° elevation` : 'Viewing angles unavailable',
    anchor: text(column.anchor_root_id), receptors: assigned};
}

export function describePeripheralMapping(module) {
  const input = asArray(module.input_indices), output = asArray(module.output_indices);
  const mapped = input.length + output.length > 0;
  return {id: text(module.id), label: display(module.name || module.label || module.id),
    side: display(module.side || 'unassigned'), system: display(module.system || module.kind || 'Other'),
    nerve: display(module.nerve || 'Not annotated'), subdivision: display(module.subdivision || ''),
    input, output, mapped, status: !mapped ? 'No neural mapping'
      : /modeled_links/.test(module.status || '') ? 'Annotation + modeled links' : 'Annotated neural interface',
    source: module.source || module.sources || '', assumptions: asArray(module.assumptions)};
}

export function filterSensoryEntries(entries, query) {
  const terms = text(query).trim().toLowerCase().split(/\s+/).filter(Boolean);
  return entries.filter(item => {
    const haystack = [item.id,item.label,item.side,item.system,item.nerve,item.subdivision,item.status,item.anchor,item.source,
      ...asArray(item.receptors).map(r => `${r.cell_type || ''} ${r.root_id || ''} ${r.entity_id || ''}`)].map(text).join(' ').toLowerCase();
    return terms.every(term => haystack.includes(term));
  });
}

function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = content;
  if (className) element.className = className;
  return element;
}

/** Call refresh after changing model/recording, refreshSelection after a canvas selection. */
export function initializeSensoryMaps({host, eyePanel, requestJSON, getModelId,
  getEyeColumns = () => [], getReceptors = () => [], getSelectedEyeColumn = () => null,
  getEyeModelId = getModelId, getEyeAudit = () => null, onSelectEyeColumn, onSelectModule}) {
  let modules = [], loadedModel = null, pendingModel = null, loadError = '', generation = 0;
  let mode = 'eye', selectedModule = '', disposed = false;
  let previousColumns = null, previousReceptors = null, eyeEntries = [];
  host.classList.add('sensory-maps');
  const heading = node('div', undefined, 'sensory-map-heading');
  const tabs = node('div', undefined, 'sensory-map-tabs');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Sensory map');
  const eyeTab = node('button', 'Compound eyes'), bodyTab = node('button', 'Body & senses');
  for (const tab of [eyeTab,bodyTab]) {tab.type='button';tabs.append(tab);}
  const modelLabel = node('small', '', 'sensory-map-model');heading.append(tabs,modelLabel);
  const eyeHost = node('div', undefined, 'sensory-eye-host');if(eyePanel)eyeHost.append(eyePanel);
  const search = node('input');search.type='search';search.className='sensory-map-search';search.setAttribute('aria-label','Find a sensory map entry');
  const side = node('select');side.setAttribute('aria-label','Filter by side');
  for(const [value,label] of [['','All sides'],['left','Left'],['right','Right'],['center','Center'],['unassigned','Unassigned']]) {const option=node('option',label);option.value=value;side.append(option);}
  const filter = node('div', undefined, 'sensory-map-filter');filter.append(search,side);
  const count = node('p', '', 'sensory-map-count');count.setAttribute('role','status');
  const picker = node('select');picker.size=6;picker.className='sensory-map-picker';picker.setAttribute('aria-label','Mapped sensory entries');
  const details = node('section', undefined, 'sensory-map-details');details.setAttribute('aria-label','Selected mapping');
  host.append(heading,eyeHost,filter,count,picker,details);

  function entries() {
    if(mode!=='eye')return modules.map(describePeripheralMapping);
    const columns=getEyeColumns(),receptors=getReceptors();
    if(columns!==previousColumns||receptors!==previousReceptors) {
      previousColumns=columns;previousReceptors=receptors;
      const byColumn=new Map();
      for(const receptor of asArray(receptors)) {
        if(!byColumn.has(receptor.column_index))byColumn.set(receptor.column_index,[]);
        byColumn.get(receptor.column_index).push(receptor);
      }
      eyeEntries=asArray(columns).map((column,index)=>{
        const result=describeEyeColumn(column,index,byColumn.get(column.column_index??index)||[]);
        return {...result,label:`${display(result.side)} eye · ${result.id}`};
      });
    }
    return eyeEntries;
  }
  function addFact(list,label,value) {list.append(node('dt',label),node('dd',value));}
  function addSource(parent,source) {
    if(!source)return;
    for(const value of asArray(source).length?source:[source]) {
      const address=typeof value==='string'?value:value.url;
      if(typeof address==='string'&&/^https?:\/\//i.test(address)) {
        const link=node('a','Source ↗');link.href=address;link.target='_blank';link.rel='noopener noreferrer';parent.append(link);
      } else parent.append(node('p',typeof value==='string'?value:JSON.stringify(value),'sensory-map-note'));
    }
  }
  function renderDetails() {
    details.replaceChildren();
    const selected=mode==='eye'?entries().find(item=>item.index===getSelectedEyeColumn()):entries().find(item=>item.id===selectedModule);
    if(!selected){details.append(node('p',mode==='eye'?'Select a column in the eye map or list.':'Select an organ to inspect its neural connections.','sensory-map-note'));return;}
    const top=node('div',undefined,'sensory-detail-heading');top.append(node('strong',selected.label),node('span',selected.status,'sensory-map-status'));details.append(top);
    const list=node('dl');details.append(list);
    if(mode==='eye') {
      addFact(list,'Column',selected.id);addFact(list,'Grid',selected.coordinate);addFact(list,'Optical axis',selected.angles);
      if(selected.anchor)addFact(list,'Anchor root ID',selected.anchor);
      addFact(list,'Receptors',selected.receptors.length?`${selected.receptors.length} assigned`:'No receptor mapping loaded');
      if(selected.source)details.append(node('p',selected.source,'sensory-map-note'));
      if(selected.receptors.length) {
        const receptorDetails=node('details'),summary=node('summary',`Receptor identifiers (${selected.receptors.length})`);
        const table=node('div',undefined,'sensory-receptor-list');
        for(const receptor of selected.receptors) {
          const item=node('div');item.append(node('strong',receptor.cell_type||'Photoreceptor'),node('code',text(receptor.entity_id||receptor.root_id||`index ${receptor.index}`)));table.append(item);
        }
        receptorDetails.append(summary,table);details.append(receptorDetails);
      }
    } else {
      addFact(list,'Side',selected.side);addFact(list,'Nerve',selected.nerve);
      if(selected.subdivision)addFact(list,'Target',selected.subdivision);
      const connections=node('div',undefined,'sensory-connection-map');
      connections.append(node('span',`${selected.input.length.toLocaleString()} sensory → brain`),node('span',`${selected.output.length.toLocaleString()} brain → body`));details.append(connections);
      details.append(node('p',selected.mapped?'Neural interfaces from annotation; organ dynamics are modeled.':'No neural targets are assigned to this organ in the selected model.','sensory-map-note'));
      const identifiers=node('details');identifiers.append(node('summary','Mapping identifiers'));
      const idList=node('dl');addFact(idList,'Module ID',selected.id);addFact(idList,'Sensory indices',selected.input.join(', ')||'None');addFact(idList,'Motor / organ indices',selected.output.join(', ')||'None');identifiers.append(idList);details.append(identifiers);
      addSource(details,selected.source);
      if(selected.assumptions.length){const notes=node('details');notes.append(node('summary','Model assumptions'));for(const value of selected.assumptions)notes.append(node('p',value,'sensory-map-note'));details.append(notes);}
    }
  }
  function render() {
    if(disposed)return;
    eyeTab.setAttribute('aria-pressed',String(mode==='eye'));bodyTab.setAttribute('aria-pressed',String(mode==='body'));
    eyeHost.hidden=mode!=='eye';search.placeholder=mode==='eye'?'Find column or receptor ID…':'Find organ, nerve or body part…';
    const model=mode==='eye'?getEyeModelId?.():getModelId?.();modelLabel.textContent=model||'No map loaded';
    const all=entries(), filtered=filterSensoryEntries(all,search.value).filter(item=>!side.value||item.side.toLowerCase()===side.value);
    picker.replaceChildren();
    for(const item of filtered) {
      const option=node('option',mode==='eye'?item.label:`${item.label} · ${item.input.length+item.output.length} neurons`);
      option.value=mode==='eye'?String(item.index):item.id;picker.append(option);
    }
    const selected=mode==='eye'?getSelectedEyeColumn():selectedModule;picker.value=selected===null?'':String(selected);picker.disabled=!filtered.length;
    count.textContent=mode==='body'&&pendingModel?'Loading neural interfaces…':mode==='body'&&loadError?loadError
      : all.length?`${filtered.length.toLocaleString()} / ${all.length.toLocaleString()} ${mode==='eye'?'columns':'anatomical interfaces'}`
        : mode==='eye'?'No optical map is loaded for this model.':'No annotated organ interfaces are available for this model.';
    const audit=mode==='eye'?getEyeAudit():null;
    if(audit&&Number.isFinite(audit.photoreceptors_unassigned)) {
      const mapped=Number.isFinite(audit.photoreceptors_mapped)?`${audit.photoreceptors_mapped.toLocaleString()} mapped, `:'';
      count.textContent+=` · ${mapped}${audit.photoreceptors_unassigned.toLocaleString()} unmapped receptors`;
    }
    renderDetails();
  }
  function changeMode(next) {mode=next;search.value='';side.value='';render();window.dispatchEvent(new Event('resize'));}
  eyeTab.addEventListener('click',()=>changeMode('eye'));bodyTab.addEventListener('click',()=>changeMode('body'));
  search.addEventListener('input',render);side.addEventListener('change',render);
  picker.addEventListener('change',()=>{
    if(!picker.value)return;
    if(mode==='eye')onSelectEyeColumn?.(Number(picker.value));
    else {selectedModule=picker.value;onSelectModule?.(modules.find(item=>item.id===selectedModule));}
    renderDetails();
  });
  async function refresh() {
    render();const model=getModelId?.();
    if(!model||model===loadedModel||model===pendingModel||disposed)return;
    const ticket=++generation;pendingModel=model;loadedModel=null;modules=[];selectedModule='';loadError='';render();
    try {
      const response=await requestJSON(`/api/peripheral?model_id=${encodeURIComponent(model)}`);
      if(disposed||ticket!==generation)return;
      modules=Array.isArray(response)?response:asArray(response.modules||response.organs);loadedModel=model;
    } catch(error) {if(ticket===generation)loadError=`Mapping unavailable: ${error.message||error}`;}
    finally {if(ticket===generation){pendingModel=null;render();}}
  }
  function refreshSelection() {
    if(disposed)return;
    if(mode==='eye')picker.value=getSelectedEyeColumn()===null?'':String(getSelectedEyeColumn());
    renderDetails();
  }
  refresh();
  return {refresh,refreshSelection,showEyes(){changeMode('eye');},showBody(){changeMode('body');},
    destroy(){disposed=true;++generation;},element:host};
}
