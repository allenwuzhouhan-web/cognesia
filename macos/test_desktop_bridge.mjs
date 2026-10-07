import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

// Exercise the actual injected scripts, including the early document-start
// case where WebKit has not created the HTML element yet.
const swift=readFileSync(new URL('./Sources/Cognesia.swift',import.meta.url),'utf8');
const bootstrap=swift.match(/let desktopBootstrap = """\n([\s\S]*?)\n\s*"""/)[1].replaceAll('\\(servicePort)','8794');
const dispatch=swift.match(/let script = "(!window\.dispatchEvent.+)"/)[1];
function page({hostname='127.0.0.1',port='8794',protocol='http:',hasRoot=true}={}){
  const classes=new Set(),messages=[],listeners=new Map();let observer=null;
  const root={classList:{add:value=>classes.add(value)}},document={documentElement:hasRoot?root:null};
  const window={webkit:{messageHandlers:{cognesiaDesktop:{postMessage:value=>messages.push(value)}}},addEventListener:(name,callback)=>listeners.set(name,callback)};
  const context={location:{hostname,port,protocol},window,document,MutationObserver:class{
    constructor(callback){this.callback=callback;observer=this;}observe(target,options){this.target=target;this.options=options;}disconnect(){this.disconnected=true;}
  }};
  vm.runInNewContext(bootstrap,context);
  return{classes,messages,listeners,window,document,root,observer};
}
test('trusted loopback desktop pages get mode before UI startup and forward command state',()=>{
  for(const hostname of ['127.0.0.1','localhost']){
    const p=page({hostname});assert.equal(p.window.__COGNESIA_DESKTOP__,true);assert.ok(p.classes.has('cognesia-desktop'));assert.equal(p.observer,null);
    assert.equal(Object.getOwnPropertyDescriptor(p.window,'__COGNESIA_DESKTOP__').writable,false);
    const state={ready:true,enabled:{run:true,pause:false,'stop-all':true,'toggle-notes':true},checked:{'toggle-notes':false}};p.listeners.get('cognesia-desktop-state')({detail:state});assert.equal(p.messages[0],state);assert.equal(p.messages[0].checked['toggle-notes'],false);
  }
});
test('document-start marking waits for the root and disconnects its observer',()=>{
  const p=page({hasRoot:false});assert.equal(p.window.__COGNESIA_DESKTOP__,true);assert.equal(p.classes.size,0);assert.equal(p.observer.target,p.document);
  p.observer.callback();assert.equal(p.observer.disconnected,undefined);
  p.document.documentElement=p.root;p.observer.callback();assert.ok(p.classes.has('cognesia-desktop'));assert.equal(p.observer.disconnected,true);
});
test('external origins and other local services never receive the desktop bridge',()=>{
  for(const options of [{hostname:'example.com'},{port:'8796'},{protocol:'https:'},{protocol:'file:',hostname:'',port:''}]){
    const p=page(options);assert.equal(p.window.__COGNESIA_DESKTOP__,undefined);assert.equal(p.classes.size,0);assert.equal(p.listeners.size,0);assert.equal(p.observer,null);
  }
});
test('native commands distinguish accepted handlers from absent handlers',()=>{
  for(const action of ['stop-all','toggle-notes','new-note'])for(const accepted of [false,true]){
    let received;
    const script=dispatch.replaceAll('\\(command.rawValue)',action);
    const result=vm.runInNewContext(script,{CustomEvent:class{constructor(type,options){this.type=type;Object.assign(this,options);}},window:{dispatchEvent(event){received=event;return !accepted;}}});
    assert.equal(result,accepted);assert.equal(received.type,'cognesia-desktop-command');assert.equal(received.detail.action,action);assert.equal(received.cancelable,true);
  }
});
test('startup errors are retained in a bounded diagnostic buffer',()=>{
  const p=page();
  for(let i=0;i<12;i++)p.listeners.get('error')({message:`failure-${i}`,filename:'http://127.0.0.1:8794/app.js?v=1',lineno:i,colno:1});
  assert.equal(p.window.__cognesiaDesktopErrors.length,8);assert.equal(p.window.__cognesiaDesktopErrors[0].message,'failure-4');
  assert.equal(p.window.__cognesiaDesktopErrors.at(-1).file,'http://127.0.0.1:8794/app.js');
  p.listeners.get('unhandledrejection')({reason:{message:'async failure'}});assert.equal(p.window.__cognesiaDesktopErrors.at(-1).message,'async failure');
});
for(const rafAvailable of [true,false])test(`diagnostics measure ${rafAvailable?'working':'stalled'} animation frames without changing rendering`,()=>{
  const begin=swift.match(/let begin = #"""\n([\s\S]*?)\n\s*"""#/)[1];
  const inspect=swift.match(/let inspect = #"""\n([\s\S]*?)\n\s*"""#/)[1];
  let now=0,nextID=0;const queue=new Map();
  const schedule=(fn,ms)=>{const id=++nextID;queue.set(id,{fn,at:now+ms});return id;};
  const context={window:{cognesiaRenderingDiagnostics:()=>({brain:{draws:7}})},document:{visibilityState:'visible',hidden:false,hasFocus:()=>true,readyState:'complete',querySelectorAll:()=>[],querySelector:()=>null},performance:{now:()=>now},innerWidth:1200,innerHeight:800,devicePixelRatio:2,
    requestAnimationFrame:fn=>schedule(fn,rafAvailable?16:Infinity),cancelAnimationFrame:id=>queue.delete(id),setTimeout:(fn,ms)=>schedule(fn,ms),clearTimeout:id=>queue.delete(id)};
  const sandbox=vm.createContext(context);vm.runInContext(begin,sandbox);
  while(queue.size){const [id,item]=[...queue].sort((a,b)=>a[1].at-b[1].at)[0];if(item.at>2200)break;queue.delete(id);now=item.at;item.fn();}
  now=2200;const result=vm.runInContext(inspect,sandbox);
  assert.equal(result.probe.raf,rafAvailable?125:0);assert.equal(result.probe.timers,100);assert.equal(result.probe.elapsedMs,2200);
  assert.equal(result.visibility,'visible');assert.equal(result.rendering.brain.draws,7);assert.equal(queue.size,0);assert.equal(context.window.__cognesiaRenderingProbe,undefined);
});
