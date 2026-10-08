import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/flybrain/web/agent.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../src/flybrain/web/agent.html', import.meta.url), 'utf8');
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.listeners={}; this.attrs={}; this.value=''; this.classes=new Set(); this.classList={add:v=>this.classes.add(v),remove:v=>this.classes.delete(v),toggle:(v,on)=>on?this.classes.add(v):this.classes.delete(v)}; }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children=children; }
  addEventListener(event,handler) { this.listeners[event]=handler; }
  setAttribute(key,value) { this.attrs[key]=value; }
  click() { if (!this.disabled) return this.listeners.click?.(); }
  focus() { this.focused=true; }
}
async function setup() {
  const elements = new Map([...html.matchAll(/id="([^"]+)"/g)].map(match=>[match[1],new Element()]));
  elements.get('call-limit').value='unlimited';
  const old = {id:'old',prompt:'Previous study',status:'completed',started_at:1,calls_used:2,max_calls:2,events:[],report:{title:'Old report'}};
  let server = {csrf:'test',connected:true,model_id:'gpt-oss-20b',model_url:'local',viewer_url:'viewer',mode:'owner',
    run:{id:'live',prompt:'Running study',status:'running',started_at:2,calls_used:1,max_calls:2,events:[],report:null},
    history:[{id:'live',title:'Running study',status:'running',started_at:2},{id:'old',title:'Previous study',status:'completed',started_at:1}]};
  const links=[],requests=[],blobs=[];
  const document = {getElementById:id=>elements.get(id),querySelectorAll:()=>[],createTextNode:text=>({textContent:text}),
    createElement:tag=>{const el=new Element(tag);if(tag==='a'){el.click=()=>links.push({href:el.href,download:el.download});}return el;}};
  const listeners={};
  const window = {addEventListener:(event,fn)=>listeners[event]=fn,dispatchEvent:event=>listeners[event.type]?.(event),scrollTo(){},CognesiaReport:{render:run=>new Element(run.id)}};
  const context={document,window,Event:class{constructor(type){this.type=type;}},Date,Blob,URL:{createObjectURL:blob=>{blobs.push(blob);return 'blob:trace';},revokeObjectURL(){}},setTimeout(){},
    fetch:async(path,options)=>{requests.push({path,options});let result=server;
      if(path==='/api/history/old')result=old;
      if(path==='/api/run'){server={...server,run:{...server.run,...JSON.parse(options.body),id:'new',status:'running'}};result=server.run;}
      return {ok:true,json:async()=>structuredClone(result)};}};
  vm.createContext(context);vm.runInContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  return {elements,context,links,requests,blobs,server,refresh:()=>vm.runInContext('refresh()',context),open:id=>vm.runInContext(`openChat('${id}')`,context)};
}

test('past chat selection survives polling and exports that chat while a new study runs', async()=>{
  const p=await setup();
  await p.open('old');
  assert.equal(p.elements.get('saved-prompt-text').textContent,'Previous study');
  assert.equal(p.elements.get('answer').children[0].tag,'old');
  await p.refresh();
  assert.equal(p.elements.get('answer').children[0].tag,'old');
  assert.equal(p.elements.get('stop').textContent,'Stop running study');
  p.elements.get('download-pdf').click();
  assert.equal(p.links.at(-1).href,'/api/report/old.pdf');
  p.elements.get('export').click();
  assert.equal(JSON.parse(await p.blobs[0].text()).study.id,'old');
  assert.ok(p.elements.get('history-list').children[1].children[0].attrs['aria-current']==='true');
});

test('new chat keeps a draft while polling and never starts a second concurrent study', async()=>{
  const p=await setup();
  p.elements.get('new-chat').click();
  p.elements.get('prompt').value='Next study';
  await p.refresh();
  assert.equal(p.elements.get('study-editor').hidden,false);
  assert.equal(p.elements.get('prompt').value,'Next study');
  assert.equal(p.elements.get('start').disabled,true);
  p.server.run.status='completed';await p.refresh();
  assert.equal(p.elements.get('start').disabled,false);
  p.elements.get('max-calls').value='2';p.elements.get('max-tokens').value='2048';
  await p.elements.get('start').click();
  assert.equal(p.elements.get('saved-prompt-text').textContent,'Next study');
  assert.equal(p.elements.get('study-editor').hidden,true);
  assert.equal(p.requests.filter(r=>r.path==='/api/run').length,1);
  assert.equal(JSON.parse(p.requests.find(r=>r.path==='/api/run').options.body).max_calls,null);
  assert.equal(p.elements.get('calls-used').children[1].textContent,'/ ∞');
});

test('custom limits above 50 are sent exactly and invalid values never start a study', async()=>{
  const p=await setup();p.server.run.status='completed';await p.refresh();
  p.elements.get('new-chat').click();p.elements.get('prompt').value='A bounded study';
  p.elements.get('call-limit').value='custom';p.elements.get('call-limit').listeners.change();
  assert.equal(p.elements.get('max-calls-field').hidden,false);
  p.elements.get('max-calls').value='0';await p.elements.get('start').click();
  assert.equal(p.requests.filter(r=>r.path==='/api/run').length,0);
  assert.match(p.elements.get('error-banner').textContent,/positive whole number/);
  p.elements.get('max-calls').value='250';await p.elements.get('start').click();
  assert.equal(JSON.parse(p.requests.find(r=>r.path==='/api/run').options.body).max_calls,250);
  assert.equal(p.elements.get('calls-used').children[1].textContent,'/ 250');
});
