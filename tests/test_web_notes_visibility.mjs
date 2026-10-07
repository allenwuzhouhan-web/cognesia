import test from 'node:test';
import assert from 'node:assert/strict';
import {createNotesVisibility,NOTES_VISIBILITY_KEY} from '../src/flybrain/web/workspace-notes.js';
import {initializeDesktopWorkspace} from '../src/flybrain/web/desktop-workspace.js';

test('Notes visibility survives reopening without touching the existing note document',()=>{
  const original='{"notes":[{"text":"Keep my actual observation"}]}',saved=new Map([['existing-notes',original]]),changes=[];
  const storage={getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)};
  const first=createNotesVisibility({storage,onChange:value=>changes.push(value)});
  assert.equal(first.isVisible(),true);first.setVisible(false);assert.equal(saved.get(NOTES_VISIBILITY_KEY),'false');
  const reopened=createNotesVisibility({storage});assert.equal(reopened.isVisible(),false);reopened.setVisible(true);assert.equal(saved.get(NOTES_VISIBILITY_KEY),'true');
  assert.equal(createNotesVisibility({storage}).isVisible(),true);assert.equal(saved.get('existing-notes'),original);assert.deepEqual(changes,[true,false]);
});
test('Notes stays usable when preference storage is unavailable and unchanged visibility causes no extra resize',()=>{
  const changes=[],storage={getItem(){throw Error('unavailable');},setItem(){throw Error('unavailable');}};
  const state=createNotesVisibility({storage,onChange:value=>changes.push(value)});
  state.setVisible(true);state.toggleVisible();state.setVisible(false);state.toggleVisible();assert.deepEqual(changes,[true,false,true]);assert.equal(state.isVisible(),true);
});
test('desktop keyboard toggle and New Note share checked state without starting simulation',async()=>{
  const previous=Object.fromEntries(['window','document','MutationObserver'].map(key=>[key,globalThis[key]]));
  const windowTarget=new EventTarget(),documentTarget=new EventTarget();documentTarget.querySelector=()=>null;
  globalThis.window=windowTarget;globalThis.document=documentTarget;globalThis.MutationObserver=class{observe(){}disconnect(){}};
  let controller,visible=true,notes=0,runs=0;const published=[],messages=[];
  windowTarget.addEventListener('cognesia-desktop-state',event=>published.push(event.detail));
  const press=(key,{shift=false,ctrl=false}={})=>{const event=new Event('keydown',{cancelable:true});Object.assign(event,{key,metaKey:!ctrl,ctrlKey:ctrl,shiftKey:shift,altKey:false});documentTarget.dispatchEvent(event);return event;};
  try{
    controller=initializeDesktopWorkspace({actions:{'toggle-notes':()=>{visible=!visible;controller.refresh();},'new-note':()=>{visible=true;notes++;controller.refresh();},'save-session':()=>{},run:()=>runs++},executionButtons:{run:{disabled:true}},isReady:()=>true,getChecked:()=>({'toggle-notes':visible}),onStatus:message=>messages.push(message)});
    assert.equal(published.at(-1).checked['toggle-notes'],true);
    assert.equal(press('N',{shift:true}).defaultPrevented,true);await Promise.resolve();assert.equal(visible,false);assert.equal(published.at(-1).checked['toggle-notes'],false);
    assert.equal(press('n').defaultPrevented,true);await Promise.resolve();assert.equal(visible,true);assert.equal(notes,1);assert.equal(published.at(-1).checked['toggle-notes'],true);
    press('N',{shift:true,ctrl:true});await Promise.resolve();assert.equal(visible,false);assert.equal(runs,0);assert.deepEqual(messages,[]);
    assert.equal(press('s',{shift:true}).defaultPrevented,false);
  }finally{controller?.dispose();for(const[key,value]of Object.entries(previous))if(value===undefined)delete globalThis[key];else globalThis[key]=value;}
});
