import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyNotesState,normalizedSelection,validateAnchor,validateNotesState,createNote,updateNote,removeNote,mergeNotesStates,anchorLabel} from '../src/flybrain/web/notes-model.js';
const anchor={panel_id:'brain',panel_title:'Brain',element_id:'brain-stage',rect:{x:.2,y:.1,width:.3,height:.4},run_id:'run-1',model_id:'flywire-783',model_hash:'saved-source',time_ms:123.25,signal_ids:['neuron:9007199254740993:raw'],interval_ms:[20,80]};
const stamp='2026-10-01T12:00:00.000Z';
const withNote=(text='Original')=>({...emptyNotesState(),notes:[createNote(anchor,{id:'n1',now:stamp,text})]});

test('dragging in either direction produces a bounded region independent of viewport size',()=>{
  const bounds={left:100,top:40,width:400,height:200};
  assert.deepEqual(normalizedSelection({x:340,y:160},{x:180,y:80},bounds),{x:.2,y:.2,width:.39999999999999997,height:.39999999999999997});
  assert.deepEqual(normalizedSelection({x:90,y:30},{x:700,y:400},bounds),{x:0,y:0,width:1,height:1});
  const r=normalizedSelection({x:180,y:80},{x:340,y:160},bounds);
  assert.equal(r.x*800,160);assert.equal(r.y*400,80); // replay scales with resized panel
  assert.throws(()=>normalizedSelection({x:0,y:0},{x:1,y:1},{left:0,top:0,width:0,height:10}),/visible panel/);
  assert.throws(()=>normalizedSelection({x:0,y:0},{x:0,y:10},bounds),/rectangle/);
});

test('notes preserve exact whitespace, punctuation, Unicode, and source identities',()=>{
  const text='  First observation\n\nα→β 🧠\t"quoted" <b>literal</b>\n';
  const state=withNote(text);state.session_title='  My session — 001  ';
  const restored=validateNotesState(JSON.parse(JSON.stringify(state)));
  assert.equal(restored.notes[0].text,text);assert.equal(restored.session_title,state.session_title);
  assert.equal(restored.notes[0].anchor.signal_ids[0],'neuron:9007199254740993:raw');
  assert.equal(restored.notes[0].anchor.model_hash,'saved-source');assert.equal(restored.notes[0].anchor.time_ms,123.25);
  restored.notes[0].anchor.rect.x=0;assert.equal(state.notes[0].anchor.rect.x,.2);
});

test('editing and deletion leave other notes and earlier exported snapshots unchanged',()=>{
  const original=withNote(),note2=createNote({...anchor,panel_id:'analysis'},{id:'n2',now:stamp,text:'Second'});
  original.notes.push(note2);const saved=validateNotesState(original);
  const edited=updateNote(original,'n1','\n Exact new text  ','2026-10-01T12:01:00Z');
  assert.equal(edited.notes[0].text,'\n Exact new text  ');assert.equal(saved.notes[0].text,'Original');
  assert.equal(edited.notes[1].text,'Second');assert.equal(edited.notes[0].created_at,stamp);
  assert.deepEqual(removeNote(edited,'n1').notes.map(n=>n.id),['n2']);assert.equal(edited.notes.length,2);
  assert.throws(()=>updateNote(edited,'missing','x'),/no longer exists/);
});

test('importing or merging another tab preserves both conflicting authored texts',()=>{
  const current=withNote('Draft from this window'),incoming=withNote('Draft from the other window');incoming.session_title='Imported title';
  const merged=mergeNotesStates(current,incoming,()=> 'conflict-copy');
  assert.deepEqual(merged.notes.map(n=>n.text),['Draft from this window','Draft from the other window']);
  assert.deepEqual(merged.notes.map(n=>n.id),['n1','conflict-copy']);assert.equal(merged.session_title,'Imported title');
  const repeated=mergeNotesStates(merged,incoming,()=>{throw Error('Should not duplicate an existing conflict');});
  assert.equal(repeated.notes.length,2);assert.equal(current.notes.length,1);
});

test('matching identities deduplicate without losing newer timestamps or distinct anchors',()=>{
  const original=withNote(),later=updateNote(original,'n1','Original','2026-10-01T14:00:00+01:00');
  const merged=mergeNotesStates(original,later);assert.equal(merged.notes.length,1);assert.equal(merged.notes[0].updated_at,'2026-10-01T14:00:00+01:00');
  later.notes[0].anchor.time_ms=456;
  assert.equal(mergeNotesStates(original,later,()=> 'moved-link').notes.length,2);
});

test('invalid imported states fail without silently truncating or overwriting data',()=>{
  const source=withNote('Do not lose this');
  assert.throws(()=>validateNotesState({...source,schema_version:99}),/version/);
  assert.throws(()=>validateNotesState({...source,notes:[source.notes[0],source.notes[0]]}),/unique/);
  assert.throws(()=>validateNotesState({...source,notes:[{...source.notes[0],text:null}]}),/text/);
  assert.throws(()=>validateAnchor({...anchor,rect:{x:.8,y:.1,width:.4,height:.2}}),/inside/);
  assert.throws(()=>validateAnchor({...anchor,time_ms:NaN}),/finite/);
  assert.throws(()=>mergeNotesStates(source,withNote('Different'),()=> 'n1'),/conflicting/);
  assert.equal(source.notes[0].text,'Do not lose this');
});

test('optional sources remain explicitly absent, while interval links normalize direction',()=>{
  const minimal=validateAnchor({panel_id:'parameters',rect:{x:0,y:0,width:1,height:1},interval_ms:[30,10]});
  assert.equal(minimal.run_id,null);assert.equal(minimal.model_hash,null);assert.equal(minimal.time_ms,null);
  assert.deepEqual(minimal.interval_ms,[10,30]);assert.deepEqual(minimal.signal_ids,[]);
  assert.match(anchorLabel(anchor),/Brain · Run run-1/);assert.match(anchorLabel(minimal),/Workspace/);
});

test('mixed-run charts retain every recording without inventing a shared model or time',()=>{
  const a=validateAnchor({...anchor,run_id:null,run_ids:['run-a','run-b','run-a'],model_id:null,model_hash:null,time_ms:null});
  assert.deepEqual(a.run_ids,['run-a','run-b']);assert.equal(a.run_id,null);assert.equal(a.model_hash,null);assert.equal(a.time_ms,null);
  assert.match(anchorLabel(a),/2 linked recordings/);
  const state=withNote();state.notes[0].anchor=a;
  assert.deepEqual(validateNotesState(JSON.parse(JSON.stringify(state))).notes[0].anchor.run_ids,['run-a','run-b']);
});
