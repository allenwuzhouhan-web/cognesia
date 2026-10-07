/** Exact authored text plus source-linked, normalized workspace annotations. */
export const NOTES_VERSION=1;
export const NOTES_STORAGE_KEY='cognesia.workspace.notes.v1';
const copy=value=>structuredClone(value);
const finite=value=>typeof value==='number'&&Number.isFinite(value);
const clamp=value=>Math.max(0,Math.min(1,value));
const stringOrNull=value=>value==null?null:String(value);
export function emptyNotesState(){return{schema_version:NOTES_VERSION,session_title:'Untitled session',notes:[]};}
export function normalizedSelection(start,end,bounds){
  if(![start?.x,start?.y,end?.x,end?.y,bounds?.left,bounds?.top,bounds?.width,bounds?.height].every(finite)||bounds.width<=0||bounds.height<=0)throw Error('Select an area inside a visible panel.');
  const x1=clamp((start.x-bounds.left)/bounds.width),x2=clamp((end.x-bounds.left)/bounds.width);
  const y1=clamp((start.y-bounds.top)/bounds.height),y2=clamp((end.y-bounds.top)/bounds.height);
  const rect={x:Math.min(x1,x2),y:Math.min(y1,y2),width:Math.abs(x2-x1),height:Math.abs(y2-y1)};
  if(rect.width<=0||rect.height<=0)throw Error('Drag a rectangle with both width and height.');
  return rect;
}
export function validateAnchor(anchor){
  if(!anchor||typeof anchor.panel_id!=='string'||!anchor.panel_id)throw Error('Note has no stable panel identity.');
  const rect=anchor.rect;
  if(!rect||![rect.x,rect.y,rect.width,rect.height].every(finite)||rect.x<0||rect.y<0||rect.width<=0||rect.height<=0||rect.x+rect.width>1+1e-9||rect.y+rect.height>1+1e-9)throw Error('Note region must fit inside its linked panel.');
  if(anchor.time_ms!=null&&(!finite(anchor.time_ms)||anchor.time_ms<0))throw Error('Note time must be a finite model time.');
  const interval=anchor.interval_ms;
  if(interval!=null&&(!Array.isArray(interval)||interval.length!==2||!interval.every(finite)))throw Error('Note interval must contain two finite times.');
  if(anchor.run_ids!=null&&(!Array.isArray(anchor.run_ids)||anchor.run_ids.some(id=>typeof id!=='string')))throw Error('Note recording links must be strings.');
  if(anchor.signal_ids!=null&&(!Array.isArray(anchor.signal_ids)||anchor.signal_ids.some(id=>typeof id!=='string')))throw Error('Note signal links must be strings.');
  return{panel_id:anchor.panel_id,panel_title:typeof anchor.panel_title==='string'?anchor.panel_title:anchor.panel_id,
    element_id:stringOrNull(anchor.element_id),rect:{...rect},run_id:stringOrNull(anchor.run_id),run_ids:[...new Set(anchor.run_ids||(anchor.run_id?[String(anchor.run_id)]:[]))],model_id:stringOrNull(anchor.model_id),
    model_hash:stringOrNull(anchor.model_hash),time_ms:anchor.time_ms??null,signal_ids:[...new Set(anchor.signal_ids||[])],
    interval_ms:interval?[...interval].sort((a,b)=>a-b):null};
}
export function validateNotesState(value){
  if(value?.schema_version!==NOTES_VERSION)throw Error('Unsupported notes version. Existing saved notes were preserved.');
  if(typeof value.session_title!=='string'||!Array.isArray(value.notes))throw Error('Notes document is incomplete.');
  const seen=new Set();
  return{schema_version:NOTES_VERSION,session_title:value.session_title,notes:value.notes.map(note=>{
    if(!note||typeof note.id!=='string'||!note.id||seen.has(note.id))throw Error('Note identities must be present and unique.');
    if(typeof note.text!=='string'||typeof note.created_at!=='string'||typeof note.updated_at!=='string'||!Number.isFinite(Date.parse(note.created_at))||!Number.isFinite(Date.parse(note.updated_at)))throw Error('Note text or timestamps are invalid.');
    seen.add(note.id);return{id:note.id,text:note.text,created_at:note.created_at,updated_at:note.updated_at,anchor:validateAnchor(note.anchor)};
  })};
}
export function createNote(anchor,{id=globalThis.crypto.randomUUID(),now=new Date().toISOString(),text=''}={}){
  return validateNotesState({schema_version:NOTES_VERSION,session_title:'',notes:[{id,text,created_at:now,updated_at:now,anchor}]}).notes[0];
}
export function updateNote(state,id,text,now=new Date().toISOString()){
  if(typeof text!=='string')throw Error('Note text must be a string.');
  if(!state.notes.some(note=>note.id===id))throw Error('The selected note no longer exists.');
  return validateNotesState({...state,notes:state.notes.map(note=>note.id===id?{...note,text,updated_at:now}:note)});
}
export function removeNote(state,id){return validateNotesState({...state,notes:state.notes.filter(note=>note.id!==id)});}
/** Imports preserve both different texts if two documents reuse the same ID. */
export function mergeNotesStates(current,incoming,idFactory=()=>globalThis.crypto.randomUUID()){
  const a=validateNotesState(current),b=validateNotesState(incoming),notes=a.notes.map(copy),lookup=new Map(notes.map(n=>[n.id,n]));
  for(const note of b.notes){const previous=lookup.get(note.id);if(!previous){const added=copy(note);notes.push(added);lookup.set(added.id,added);continue;}
    if(previous.text===note.text&&JSON.stringify(previous.anchor)===JSON.stringify(note.anchor)){if(Date.parse(note.updated_at)>Date.parse(previous.updated_at))Object.assign(previous,copy(note));continue;}
    const duplicate=notes.some(n=>n.text===note.text&&JSON.stringify(n.anchor)===JSON.stringify(note.anchor)&&n.created_at===note.created_at);
    if(duplicate)continue;
    let id=idFactory();if(!id||lookup.has(id))throw Error('Could not preserve conflicting note identities.');
    const preserved={...copy(note),id};notes.push(preserved);lookup.set(id,preserved);
  }
  return{schema_version:NOTES_VERSION,session_title:b.session_title,notes};
}
export function anchorLabel(anchor){
  const source=anchor.run_id?`Run ${anchor.run_id}`:anchor.run_ids?.length?`${anchor.run_ids.length} linked recordings`:'Workspace';
  return`${anchor.panel_title||anchor.panel_id} · ${source}${anchor.time_ms==null?'':` · ${anchor.time_ms.toLocaleString(undefined,{maximumFractionDigits:3})} ms`}`;
}
