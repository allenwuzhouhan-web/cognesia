import {NOTES_STORAGE_KEY,emptyNotesState,validateNotesState,validateAnchor,normalizedSelection,createNote,updateNote,removeNote,mergeNotesStates,anchorLabel} from './notes-model.js';

const make=(tag,cls,text)=>{const element=document.createElement(tag);if(cls)element.className=cls;if(text!=null)element.textContent=text;return element;};
const button=(text,label)=>{const element=make('button','',text);element.type='button';if(label)element.setAttribute('aria-label',label);return element;};
export const NOTES_VISIBILITY_KEY='cognesia.workspace.notes-visible.v1';
/** Visibility preferences never change the separate note/document storage. */
export function createNotesVisibility({storage,onChange=()=>{}}={}){
  let visible=true;try{storage??=globalThis.localStorage;visible=storage.getItem(NOTES_VISIBILITY_KEY)!=='false';}catch{}
  onChange(visible);
  return{isVisible:()=>visible,setVisible(value){value=!!value;if(value===visible)return visible;visible=value;try{storage.setItem(NOTES_VISIBILITY_KEY,String(visible));}catch{}onChange(visible);return visible;},toggleVisible(){return this.setVisible(!visible);}};
}
export function initializeWorkspaceNotes({host,getContext=()=>({}),onSaveSession,onStatus=()=>{},onNavigate=async()=>{},onVisibilityChange=()=>{}}){
  if(!host)throw Error('Notes need a workspace panel.');
  let state=emptyNotesState(),selected=null,overlay=null,drag=null,highlight=null,highlightTimer=null,disposed=false,saving=null,lastSaved=null,lastStorage=null,recoveryRaw=null,storageError=null,deleted=null;
  try{lastStorage=localStorage.getItem(NOTES_STORAGE_KEY);if(lastStorage)state=validateNotesState(JSON.parse(lastStorage));}catch(error){recoveryRaw=lastStorage;storageError=`Saved notes could not be opened: ${error.message} They have not been overwritten.`;}
  const element=make('section','workspace-notes');element.setAttribute('aria-label','Workspace notes');
  element.innerHTML='<header class="notes-heading"><div><span class="notes-eyebrow">RESEARCH WORKSPACE</span><h2>Notes</h2></div><div class="notes-heading-actions"><span class="notes-count"></span><button type="button" data-hide-notes aria-label="Hide Notes" title="Hide Notes (⌘⇧N)">×</button></div></header><label class="notes-title-label">Session title<input class="notes-session-title" type="text" autocomplete="off" aria-label="Session title"></label><div class="notes-actions"><button type="button" data-new-note>＋ New note</button><button type="button" data-save-session>Save session</button></div><p class="notes-help">Drag an area to link a note to its recording and time.</p><p class="notes-status" role="status" aria-live="polite"></p><div class="notes-list" aria-label="Saved area notes"></div><div class="notes-editor" hidden><div class="notes-editor-heading"><h3>Edit note</h3><button type="button" data-close-editor aria-label="Close note editor">×</button></div><p class="notes-editor-anchor"></p><label>Note text<textarea class="notes-text" rows="7" placeholder="What did you observe?" aria-label="Note text" spellcheck="true"></textarea></label><div class="notes-editor-actions"><button type="button" data-show-anchor>Show linked area</button><button type="button" data-delete-note>Delete note</button></div><small>Text saves locally as you type.</small></div><div class="notes-undo" hidden><span>Note deleted.</span><button type="button" data-undo>Undo</button></div><details class="notes-saved-summary" hidden><summary>Last saved session</summary><p class="notes-saved-id"></p><pre></pre><a hidden download>Download session</a></details><p class="notes-engine-status" aria-label="Current engine status"></p><footer class="notes-local-note">Saved locally. Save session includes linked notes and recordings.</footer>';
  host.append(element);
  const q=selector=>element.querySelector(selector),list=q('.notes-list'),title=q('.notes-session-title'),editor=q('.notes-editor'),text=q('.notes-text'),status=q('.notes-status');
  q('[data-new-note]').title='Select an area for a note (⌘N)';q('[data-save-session]').title='Save a compact session archive (⌘S)';
  const reopen=button('Notes','Show Notes');reopen.className='notes-reopen';reopen.title='Show Notes (⌘⇧N)';reopen.hidden=true;
  if(!host.id)host.id='workspace-notes-rail';reopen.setAttribute('aria-controls',host.id);document.body.append(reopen);
  const visibility=createNotesVisibility({onChange:visible=>{
    const restoreFocus=!visible&&host.contains(document.activeElement);
    if(!visible){cancelSelection(null);clearHighlight();}
    host.hidden=!visible;reopen.hidden=visible;reopen.setAttribute('aria-expanded',String(visible));
    onVisibilityChange(visible);window.dispatchEvent(new Event('resize'));
    if(restoreFocus)reopen.focus();
  }});
  function setVisible(value){if(disposed)return false;return visibility.setVisible(value);}
  function toggleVisible(){return setVisible(!visibility.isVisible());}
  reopen.addEventListener('click',()=>{setVisible(true);title.focus();});q('[data-hide-notes]').addEventListener('click',()=>setVisible(false));
  title.value=state.session_title;
  function report(message,error=false,notify=true){status.textContent=message;status.classList.toggle('error',error);if(notify)onStatus(message);}
  function persist(){
    if(disposed)return false;
    try{
      if(recoveryRaw){localStorage.setItem(`${NOTES_STORAGE_KEY}.recovery.${Date.now()}`,recoveryRaw);recoveryRaw=null;}
      const external=localStorage.getItem(NOTES_STORAGE_KEY);
      if(external&&external!==lastStorage){const incoming=validateNotesState(JSON.parse(external));const currentTitle=state.session_title;state=mergeNotesStates(state,incoming);state.session_title=currentTitle;}
      const serialized=JSON.stringify(state);
      if(lastStorage)localStorage.setItem(`${NOTES_STORAGE_KEY}.backup`,lastStorage);
      localStorage.setItem(NOTES_STORAGE_KEY,serialized);lastStorage=serialized;storageError=null;
      report('Saved locally.',false,false);return true;
    }catch(error){storageError=`Browser storage unavailable: ${error.message} Your notes remain open; use Save session to preserve them on disk.`;report(storageError,true);return false;}
  }
  function renderList(){
    q('.notes-count').textContent=String(state.notes.length);
    const children=[];
    for(const note of [...state.notes].reverse()){
      const row=make('article',`notes-item${selected===note.id?' selected':''}`),open=button(note.text||'Untitled note','Edit note'),link=button('↗','Show linked area');
      open.className='notes-item-text';open.addEventListener('click',()=>edit(note.id));link.className='notes-item-link';link.title=anchorLabel(note.anchor);link.addEventListener('click',()=>replay(note));
      const meta=make('small','notes-item-meta',anchorLabel(note.anchor));row.append(open,link,meta);children.push(row);
    }
    if(!children.length)children.push(make('p','notes-empty','No notes yet. Use New note, then drag over an area to link your observation.'));
    list.replaceChildren(...children);
  }
  function edit(id){
    const note=state.notes.find(n=>n.id===id);if(!note)return;
    selected=id;editor.hidden=false;text.value=note.text;q('.notes-editor-anchor').textContent=anchorLabel(note.anchor);renderList();
    editor.scrollIntoView({block:'nearest'});text.focus();text.setSelectionRange(text.value.length,text.value.length);
  }
  function chooseTarget(x,y){
    if(overlay)overlay.style.pointerEvents='none';
    const hit=document.elementFromPoint(x,y);
    if(overlay)overlay.style.pointerEvents='';
    if(!hit||element.contains(hit))return null;
    const target=hit.closest('.analysis-card,.seq-curve-card')||hit.closest('#whole-fly-panel')||hit.closest('.brain-stage')||hit.closest('.dock-panel-shell,[data-panel-id]')||hit.closest('[id]')||document.body;
    if(target.matches('.brain-stage')&&!target.id)target.id='brain-stage';
    const shell=target.closest('[data-panel-id]');
    const panelId=shell?.dataset.panelId||(target.matches('.analysis-card,.seq-curve-card')?'analysis':target.matches('.brain-stage')?'brain':target.id==='whole-fly-panel'?'fly':target.id||'workspace');
    const panelTitle=target.matches('.brain-stage')?'Brain':target.id==='whole-fly-panel'?'Fly body':target.querySelector('h2,h3,.seq-curve-heading strong')?.textContent||shell?.querySelector('.dock-panel-heading span')?.textContent||({analysis:'Signal comparison'}[panelId])||panelId;
    return{target,panelId,panelTitle};
  }
  function cancelSelection(message='Area selection cancelled.'){
    if(drag&&overlay?.hasPointerCapture(drag.id))overlay.releasePointerCapture(drag.id);
    drag=null;overlay?.remove();overlay=null;if(message)report(message);
  }
  function paintSelection(x,y){
    if(!drag||!overlay)return;
    const b=drag.target.getBoundingClientRect(),left=Math.max(b.left,Math.min(drag.start.x,x)),right=Math.min(b.right,Math.max(drag.start.x,x)),top=Math.max(b.top,Math.min(drag.start.y,y)),bottom=Math.min(b.bottom,Math.max(drag.start.y,y));
    Object.assign(overlay.querySelector('.notes-area-box').style,{left:`${left}px`,top:`${top}px`,width:`${Math.max(0,right-left)}px`,height:`${Math.max(0,bottom-top)}px`});
  }
  function newNote(){
    if(disposed)return;setVisible(true);cancelSelection(null);clearHighlight();
    overlay=make('div','notes-area-overlay');overlay.tabIndex=-1;overlay.setAttribute('role','region');overlay.setAttribute('aria-label','Select an area for your note');
    const instruction=make('div','notes-area-instruction','Drag over an area to add a note · Esc to cancel'),cancel=button('Cancel');cancel.addEventListener('click',()=>cancelSelection());instruction.append(cancel);
    overlay.append(instruction,make('div','notes-area-box'));document.body.append(overlay);overlay.focus();report('Drag over the area you want to annotate.');
    overlay.addEventListener('pointerdown',event=>{
      if(event.button!==0||instruction.contains(event.target))return;
      const chosen=chooseTarget(event.clientX,event.clientY);if(!chosen){report('Choose an area outside the Notes panel.');return;}
      event.preventDefault();event.stopPropagation();drag={...chosen,id:event.pointerId,start:{x:event.clientX,y:event.clientY}};overlay.setPointerCapture(event.pointerId);paintSelection(event.clientX,event.clientY);
    });
    overlay.addEventListener('pointermove',event=>{if(drag?.id===event.pointerId){event.preventDefault();paintSelection(event.clientX,event.clientY);}});
    overlay.addEventListener('pointerup',event=>{
      if(!drag||drag.id!==event.pointerId)return;event.preventDefault();event.stopPropagation();
      const chosen=drag,bounds=chosen.target.getBoundingClientRect();
      try{
        if(Math.abs(event.clientX-chosen.start.x)<5||Math.abs(event.clientY-chosen.start.y)<5)throw Error('Drag an area at least 5 pixels wide and high.');
        const context=getContext({panelId:chosen.panelId,elementId:chosen.target.id||null})||{};
        const a=chosen.target.querySelector('.analysis-range-start'),b=chosen.target.querySelector('.analysis-range-end');
        const domInterval=a?.value!==''&&b?.value!==''&&a&&b?[Number(a.value),Number(b.value)]:chosen.target.dataset.intervalStartMs!=null&&chosen.target.dataset.intervalEndMs!=null?[Number(chosen.target.dataset.intervalStartMs),Number(chosen.target.dataset.intervalEndMs)]:null;
        const sourceElements=[chosen.target,...chosen.target.querySelectorAll('[data-signal-id],[data-run-id]')];
        const signalIds=context.signalIds||context.signals?.map(s=>s.id)||sourceElements.map(n=>n.dataset.signalId).filter(Boolean);
        const chart=chosen.target.matches('.analysis-card,.seq-curve-card'),chartRuns=[...new Set([...sourceElements.map(item=>item.dataset.runId),...[...chosen.target.querySelectorAll('.analysis-run')].map(item=>item.title)].filter(id=>typeof id==='string'&&/^[A-Za-z0-9_-]+$/.test(id)))];
        const contextRun=context.runId||context.run_id||null,linkedRun=chart?(chartRuns.length===1?chartRuns[0]:null):contextRun;
        const matchingContext=!chart||(chartRuns.length===1&&linkedRun===contextRun);
        const anchor=validateAnchor({panel_id:chosen.panelId,panel_title:chosen.panelTitle,element_id:chosen.target.id||null,
          rect:normalizedSelection(chosen.start,{x:event.clientX,y:event.clientY},bounds),run_id:linkedRun,run_ids:chart?chartRuns:linkedRun?[linkedRun]:[],
          model_id:matchingContext?(context.modelId||context.model_id||null):null,model_hash:matchingContext?(context.modelHash||context.model_hash||context.metadata?.model_hash||null):null,
          time_ms:matchingContext?(context.timeMs??context.time_ms??context.time??null):null,signal_ids:signalIds,
          interval_ms:domInterval?.every(Number.isFinite)?domInterval:context.intervalMs||context.interval_ms||null});
        const note=createNote(anchor);state.notes.push(note);cancelSelection(null);persist();edit(note.id);
      }catch(error){if(overlay?.hasPointerCapture(event.pointerId))overlay.releasePointerCapture(event.pointerId);drag=null;report(error.message,true);}
    });
    overlay.addEventListener('pointercancel',()=>cancelSelection());
    overlay.addEventListener('wheel',event=>event.preventDefault(),{passive:false});
  }
  function clearHighlight(){clearTimeout(highlightTimer);highlightTimer=null;highlight?.remove();highlight=null;}
  async function replay(note){
    cancelSelection(null);clearHighlight();
    try{
      await onNavigate(structuredClone(note.anchor));if(disposed)return;
      const context=getContext()||{};
      if(note.anchor.run_id&&context.runId&&note.anchor.run_id!==context.runId)throw Error('Load the linked recording to replay this note area.');
      if(note.anchor.model_hash&&context.modelHash&&note.anchor.model_hash!==context.modelHash)throw Error('The current model version differs from this note. Its original link is preserved.');
      const anchor=note.anchor,target=anchor.element_id?document.getElementById(anchor.element_id):anchor.panel_id==='workspace'?document.body:[...document.querySelectorAll('[data-panel-id]')].find(n=>n.dataset.panelId===anchor.panel_id);
      if(!target)throw Error('The linked panel or chart is no longer open. The note and its source links are preserved.');
      target.scrollIntoView({block:'nearest',inline:'nearest'});
      await new Promise(resolve=>requestAnimationFrame(resolve));
      const b=target.getBoundingClientRect();if(!b.width||!b.height)throw Error('Open the linked panel to view this saved area.');
      highlight=make('div','notes-anchor-highlight');highlight.setAttribute('aria-label','Linked note area');
      Object.assign(highlight.style,{left:`${b.left+anchor.rect.x*b.width}px`,top:`${b.top+anchor.rect.y*b.height}px`,width:`${anchor.rect.width*b.width}px`,height:`${anchor.rect.height*b.height}px`});
      document.body.append(highlight);highlightTimer=setTimeout(clearHighlight,6500);report(`Linked area: ${anchorLabel(anchor)}`);
    }catch(error){report(error.message,true);}
  }
  async function saveSession(){
    if(saving)return saving;
    if(!onSaveSession){report('Session saving is unavailable in this workspace.',true);return null;}
    persist();const snapshot=exportState(),serialized=JSON.stringify(snapshot);q('[data-save-session]').disabled=true;report('Saving session and linked notes…');
    saving=(async()=>{
      // Yield once so even a synchronous save callback failure resets the lock.
      await Promise.resolve();
      try{
        const result=await onSaveSession(snapshot);if(disposed)return result;lastSaved=result;
        const panel=q('.notes-saved-summary');panel.hidden=false;panel.open=true;
        q('.notes-saved-id').textContent=result?.session_id?`Session ${result.session_id}`:'Session saved';
        panel.querySelector('pre').textContent=typeof result?.summary==='string'?result.summary:JSON.stringify(result?.summary||{},null,2);
        const link=panel.querySelector('a');link.hidden=true;
        if(result?.download_url){const url=new URL(result.download_url,location.href);if(url.origin===location.origin){link.href=url.href;link.textContent='Download saved session';link.hidden=false;}}
        report(JSON.stringify(state)===serialized?'Session saved on this computer.':'Session saved. Newer note edits remain local; save again to include them.');return result;
      }catch(error){if(!disposed)report(`Session could not be saved: ${error.message}. Notes remain in this panel.`,true);return null;}
      finally{saving=null;if(!disposed)q('[data-save-session]').disabled=false;}
    })();return saving;
  }
  function exportState(){return validateNotesState(state);}
  function restoreState(value){
    const incoming=validateNotesState(value);state=mergeNotesStates(state,incoming);selected=null;editor.hidden=true;title.value=state.session_title;persist();renderList();return exportState();
  }
  function refresh(){if(disposed)return;const value=String(getContext()?.status||'Engine stopped'),line=q('.notes-engine-status');if(line.textContent!==value)line.textContent=value;line.title=value;}
  function keydown(event){if(event.key==='Escape'&&overlay){event.preventDefault();event.stopPropagation();cancelSelection();}}
  function storage(event){if(event.key===NOTES_STORAGE_KEY&&event.newValue!==lastStorage)report('Notes changed in another window. Your current draft is preserved; the next edit merges both copies.');}
  function clearOnViewportChange(){clearHighlight();}
  title.addEventListener('input',()=>{state.session_title=title.value;persist();});
  text.addEventListener('input',()=>{if(selected){state=updateNote(state,selected,text.value);persist();renderList();}});
  q('[data-new-note]').addEventListener('click',newNote);q('[data-save-session]').addEventListener('click',saveSession);
  q('[data-close-editor]').addEventListener('click',()=>{editor.hidden=true;selected=null;renderList();});
  q('[data-show-anchor]').addEventListener('click',()=>{const note=state.notes.find(n=>n.id===selected);if(note)replay(note);});
  q('[data-delete-note]').addEventListener('click',()=>{deleted=state.notes.find(n=>n.id===selected);state=removeNote(state,selected);selected=null;editor.hidden=true;q('.notes-undo').hidden=false;persist();renderList();});
  q('[data-undo]').addEventListener('click',()=>{if(!deleted)return;state.notes.push(deleted);const id=deleted.id;deleted=null;q('.notes-undo').hidden=true;persist();edit(id);});
  window.addEventListener('keydown',keydown,true);window.addEventListener('storage',storage);window.addEventListener('resize',clearOnViewportChange);window.addEventListener('scroll',clearOnViewportChange,true);
  function dispose(){if(disposed)return;cancelSelection(null);clearHighlight();disposed=true;window.removeEventListener('keydown',keydown,true);window.removeEventListener('storage',storage);window.removeEventListener('resize',clearOnViewportChange);window.removeEventListener('scroll',clearOnViewportChange,true);element.remove();reopen.remove();}
  renderList();refresh();if(storageError)report(storageError,true);return{element,newNote,saveSession,exportState,restoreState,refresh,dispose,setVisible,toggleVisible,isVisible:visibility.isVisible};
}
