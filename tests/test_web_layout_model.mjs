import test from 'node:test';
import assert from 'node:assert/strict';
import {panelIds,validateLayout,splitPanel,removePanel,swapPanels,defaultPanelLayout,migrateLegacyLayout,minimumLayoutSize,overviewPanelGroups,editingPanelGroups,upgradeOverviewPresets,canRestoreChart,editingGeometry,normalizeEditingSizes,overviewViewportHeight,createOverviewMeasureScheduler,EDITING_DEFAULTS,OVERVIEW_REVISION} from '../src/flybrain/web/layout-model.js';
test('split, move, swap and close preserve unique panels and leave prior draft unchanged',()=>{
  const original=defaultPanelLayout(['input','brain','readout']);const moved=splitPanel(original,'input','readout','bottom');
  assert.deepEqual(panelIds(original),['input','brain','readout']);assert.deepEqual(panelIds(moved),['input','readout','brain']);assert.equal(new Set(panelIds(moved)).size,3);
  const swapped=swapPanels(moved,'brain','input');assert.deepEqual(panelIds(swapped),['brain','readout','input']);
  const closed=removePanel(swapped,'readout');assert.deepEqual(panelIds(closed),['brain','input']);assert.deepEqual(panelIds(validateLayout(closed)),['brain','input']);
});
test('closing split sides collapses the parent and supports a single-panel layout',()=>{
  const tree=defaultPanelLayout(['a','b']);assert.deepEqual(removePanel(tree,'a'),{type:'panel',id:'b'});assert.equal(removePanel({type:'panel',id:'b'},'b'),null);
});
test('invalid saved layouts are rejected and split ratios are bounded',()=>{
  assert.throws(()=>validateLayout({type:'split',axis:'horizontal',ratio:.5,first:{type:'panel',id:'a'},second:{type:'panel',id:'a'}}),/duplicate/);
  assert.throws(()=>validateLayout({type:'panel',id:'unknown'},new Set(['known'])),/unknown/);
  assert.throws(()=>validateLayout({type:'split',axis:'diagonal',ratio:.5}),/invalid/);
  const tree=defaultPanelLayout(['a','b']);tree.ratio=100;assert.equal(validateLayout(tree).ratio,.9);
  assert.throws(()=>splitPanel(tree,'missing','c'),/destination/);
});
test('legacy width migration retains all existing panels and approximate proportions',()=>{
  const migrated=migrateLegacyLayout({version:1,widths:{wide:{input:200,readout:300}}},['input','brain','readout','fly']);
  assert.deepEqual(panelIds(migrated),['input','brain','readout','fly']);assert.equal(migrated.first.first.ratio,200/840);assert.equal(migrated.first.ratio,840/1140);
});
test('nested splits retain usable minimum pane sizes',()=>{const tree=splitPanel(defaultPanelLayout(['a','b']),'b','c','bottom');assert.deepEqual(minimumLayoutSize(tree),{width:487,height:527});});
test('editing layout keeps full-height settings left, brain with its fly inset above the sequence',()=>{
  const ids=['inputs','brain','readouts','fly','analysis','chart-1','eeg-2'];
  assert.deepEqual(overviewPanelGroups(ids),{primary:['inputs','brain','fly','analysis'],secondary:['readouts','chart-1','eeg-2']});
  const tree=validateLayout(defaultPanelLayout(ids),new Set(ids));
  assert.deepEqual(panelIds(tree),['inputs','brain','fly','analysis','readouts','chart-1','eeg-2']);
  assert.equal(tree.first.axis,'horizontal');assert.deepEqual(tree.first.first,{type:'panel',id:'inputs'});
  assert.deepEqual(panelIds(tree.first.second.first),['brain','fly']);assert.deepEqual(tree.first.second.second,{type:'panel',id:'analysis'});assert.equal(tree.first.second.ratio,1-EDITING_DEFAULTS.timelineFraction);
});
test('Default migration preserves old arrangement, saved chart state and named layouts',()=>{
  const ids=['inputs','brain','readouts','fly','analysis'],state={cards:[{id:'captured',data:[1,2,3]}]};
  const oldDefault={tree:defaultPanelLayout(['inputs','chart-1','analysis']),height:1600,panels:[{id:'chart-1',kind:'chart',state}]};
  const named={tree:{type:'panel',id:'brain'},height:700,panels:[]};
  const saved={version:2,activeName:'Research',presets:{Default:oldDefault,Research:named}};
  const upgraded=upgradeOverviewPresets(saved,ids);
  assert.equal(upgraded.activeName,'Default');assert.equal(upgraded.editing_revision,OVERVIEW_REVISION);assert.deepEqual(upgraded.presets.Research,named);
  assert.deepEqual(upgraded.presets['Previous Research'],{...named,mode:'custom'});
  assert.deepEqual(upgraded.presets['Previous Default'],{...oldDefault,mode:'custom'});
  assert.deepEqual(upgraded.presets.Default.panels[0].state,state);assert.equal(upgraded.presets.Default.mode,'editing');assert.equal(upgraded.presets.Default.overview_revision,OVERVIEW_REVISION);
  assert.deepEqual(panelIds(upgraded.presets.Default.tree),['inputs','brain','fly','analysis','readouts','chart-1']);
  assert.deepEqual(saved.presets.Default,oldDefault);assert.equal(saved.presets['Previous Default'],undefined);
  assert.deepEqual(upgradeOverviewPresets(upgraded,ids),upgraded);
});
test('new overview and legacy-width migration include all core panels',()=>{
  const ids=['inputs','brain','readouts','fly','analysis'];
  const fresh=upgradeOverviewPresets(null,ids);
  assert.equal(fresh.activeName,'Default');assert.equal(fresh.presets.Default.mode,'editing');
  assert.deepEqual(panelIds(migrateLegacyLayout({version:1,widths:{wide:{input:100,readout:120}}},ids)),['inputs','brain','fly','analysis','readouts']);
});
test('saved chart references wait for their own recording rather than loading another run',()=>{
  const card={signals:[{id:'trace:motor',runId:'recording-a'}]};
  assert.equal(canRestoreChart(card,null),false);assert.equal(canRestoreChart(card,'recording-b'),false);assert.equal(canRestoreChart(card,'recording-a'),true);
  assert.equal(canRestoreChart({signals:[{id:'imported',timeMs:[0,1],values:[2,3]}]},null),true);
  assert.equal(canRestoreChart({signals:[{id:'a',runId:'a'},{id:'b',runId:'b'}]},'a'),false);
});
test('editing geometry gives the brain remaining space and exact bounded track sums',()=>{
  const sizes=editingGeometry(1146,642);
  assert.equal(sizes.leftWidth,320);assert.equal(sizes.rightWidth,0);assert.equal(sizes.brainWidth,818);
  assert.equal(sizes.leftWidth+sizes.brainWidth+sizes.divider,1146);
  assert.equal(sizes.topHeight+sizes.timelineHeight+sizes.divider,642);
  assert.equal(sizes.timelineHeight,(642-8)*.52);assert.ok(sizes.timelineHeight>sizes.topHeight);
});
test('fly remains addressable but is an inset, without a separate editing column',()=>{
  assert.deepEqual(editingPanelGroups(['inputs','brain','fly','analysis']),{panels:['inputs','brain','analysis'],inset:'fly'});
  assert.deepEqual(editingPanelGroups(['inputs','brain','analysis']),{panels:['inputs','brain','analysis'],inset:null});
  assert.deepEqual(editingGeometry(1146,642,{rightWidth:180}),editingGeometry(1146,642,{rightWidth:600}));
  const tree=defaultPanelLayout(['inputs','brain','fly','analysis']);assert.equal(panelIds(tree).filter(id=>id==='fly').length,1);
});
test('narrow viewports clamp rendered tracks without destroying saved panel preferences',()=>{
  const saved={leftWidth:400,rightWidth:420,timelineFraction:.6},before=structuredClone(saved);
  for(const width of [0,400,720,800,1146]){const size=editingGeometry(width,532,saved);assert.ok(size.brainWidth>=0);assert.ok(size.rightWidth>=0);assert.ok(size.leftWidth>=0);assert.ok(Math.abs(size.leftWidth+size.brainWidth+size.divider-width)<1e-9);assert.ok(size.topHeight>=220);assert.ok(size.timelineHeight>=180);}
  const narrow=editingGeometry(800,532,saved),wide=editingGeometry(1600,900,saved);
  assert.equal(narrow.brainWidth,392);assert.equal(wide.leftWidth,400);assert.equal(wide.rightWidth,0);assert.deepEqual(saved,before);
  assert.deepEqual(normalizeEditingSizes({leftWidth:Infinity,rightWidth:-5,timelineFraction:3}),{leftWidth:320,rightWidth:180,timelineFraction:.72});
});
test('revision two backs up the previous two-row Default without changing its tree or named presets',()=>{
  const row=(a,b)=>({type:'split',axis:'horizontal',ratio:.5,first:{type:'panel',id:a},second:{type:'panel',id:b}});
  const old={tree:{type:'split',axis:'vertical',ratio:.5,first:row('fly','brain'),second:row('inputs','analysis')},mode:'overview',overview_revision:1,panels:[],height:1000};
  const priorBackup={tree:{type:'panel',id:'brain'},mode:'custom'};
  const saved={version:2,activeName:'Default',presets:{Default:old,'Previous Default':priorBackup,Research:{...old}}};
  const upgraded=upgradeOverviewPresets(saved,['inputs','brain','fly','analysis','readouts']);
  assert.deepEqual(upgraded.presets['Previous Default 2'],old);assert.deepEqual(upgraded.presets['Previous Default'],priorBackup);assert.deepEqual(upgraded.presets.Research,saved.presets.Research);
  assert.equal(upgraded.presets.Default.overview_revision,OVERVIEW_REVISION);assert.equal(upgraded.presets.Default.mode,'editing');assert.deepEqual(upgraded.presets.Default.editing,EDITING_DEFAULTS);assert.deepEqual(upgradeOverviewPresets(upgraded,['inputs','brain','fly','analysis','readouts']),upgraded);
});
test('first editing activation upgrades an already-refreshed Default and preserves active custom chart states',()=>{
  const ids=['inputs','brain','fly','analysis','readouts'],state=[{signals:[{id:'a',runId:'saved-run'}]}];
  const active={mode:'custom',tree:defaultPanelLayout(['brain','chart-2','fly']),panels:[{id:'chart-2',kind:'chart',state}],height:1400};
  const saved={version:2,activeName:'Research',presets:{Default:{mode:'editing',overview_revision:OVERVIEW_REVISION,tree:defaultPanelLayout(ids),panels:[]},Research:active,'Previous Research':{tree:{type:'panel',id:'brain'}}}};
  const before=structuredClone(saved),upgraded=upgradeOverviewPresets(saved,ids);
  assert.equal(upgraded.activeName,'Default');assert.equal(upgraded.editing_revision,OVERVIEW_REVISION);
  assert.deepEqual(upgraded.presets.Research,active);assert.deepEqual(upgraded.presets['Previous Research 2'],active);assert.deepEqual(saved,before);
  assert.deepEqual(panelIds(upgraded.presets.Default.tree),['inputs','brain','fly','analysis','readouts','chart-2']);assert.deepEqual(upgraded.presets.Default.panels[0].state,state);
  // A subsequent deliberate custom choice must survive every later startup.
  upgraded.activeName='Research';assert.deepEqual(upgradeOverviewPresets(upgraded,ids),upgraded);
  upgraded.activeName='Default';upgraded.presets.Default.mode='custom';assert.deepEqual(upgradeOverviewPresets(upgraded,ids),upgraded);
});
test('migration backs up a custom Default even if its preset already declares revision two',()=>{
  const ids=['inputs','brain','fly','analysis'],old={mode:'custom',overview_revision:OVERVIEW_REVISION,tree:defaultPanelLayout(['brain','fly']),panels:[]};
  const result=upgradeOverviewPresets({version:2,activeName:'Default',presets:{Default:old}},ids);
  assert.deepEqual(result.presets['Previous Default'],old);assert.equal(result.presets.Default.mode,'editing');assert.deepEqual(panelIds(result.presets.Default.tree),ids);
});
test('roomy default fits a complete chart row while explicit shrinking survives viewport changes',()=>{
  assert.equal(editingGeometry(1200,740).timelineHeight,390);
  assert.equal(editingGeometry(1200,898).timelineHeight,462.8);
  const resized={timelineFraction:.3,timelineUserSized:true};
  assert.equal(editingGeometry(1200,898,resized).timelineHeight,267);
  assert.equal(editingGeometry(1200,740,resized).timelineHeight,219.6);
  assert.equal(normalizeEditingSizes(resized).timelineUserSized,true);
  assert.equal(editingGeometry(1200,740,{...resized,timelineUserSized:false}).timelineHeight,390);
  assert.ok(editingGeometry(1200,532).topHeight>=220);
});
test('native viewport height uses real remaining space without the browser chrome subtraction',()=>{
  assert.equal(overviewViewportHeight({innerHeight:924,visualHeight:924,documentTop:8}),898);
  assert.equal(overviewViewportHeight({innerHeight:924,visualHeight:700,documentTop:8}),674);
  assert.equal(overviewViewportHeight({innerHeight:924,documentTop:140}),766);
  assert.equal(overviewViewportHeight({innerHeight:400,documentTop:150}),532);
  assert.equal(overviewViewportHeight({innerHeight:1800,documentTop:8}),1200);
});
test('only recognizable old automatic Default sizing migrates; explicit and named preferences stay intact',()=>{
  const ids=['inputs','brain','fly','analysis'],old={mode:'editing',overview_revision:OVERVIEW_REVISION,tree:defaultPanelLayout(ids),editing:{leftWidth:260,rightWidth:300,timelineFraction:.34},panels:[]};
  const saved={version:2,editing_revision:OVERVIEW_REVISION,activeName:'Research',presets:{Default:old,Research:structuredClone(old)}};
  const result=upgradeOverviewPresets(saved,ids);
  assert.equal(result.activeName,'Research');assert.deepEqual(result.presets.Research,old);assert.deepEqual(result.presets.Default.editing,EDITING_DEFAULTS);
  assert.deepEqual(result.presets['Previous Default before chart sizing'].editing,old.editing);
  assert.equal(saved.presets.Default.editing.timelineFraction,.34);assert.deepEqual(upgradeOverviewPresets(result,ids),result);
  for(const editing of [{...old.editing,timelineFraction:.27},{...old.editing,timelineUserSized:true},{...old.editing,leftWidth:340}]){
    const custom=upgradeOverviewPresets({...saved,presets:{Default:{...old,editing}}},ids);
    assert.equal(custom.presets.Default.editing.timelineFraction,editing.timelineFraction);assert.equal(custom.presets.Default.editing.timelineUserSized,true);
  }
});
test('stylesheet and viewport triggers measure synchronously even when animation frames are deferred',()=>{
  const frames=new Map();let id=0,measurements=0,scheduler;
  scheduler=createOverviewMeasureScheduler({measure(){measurements++;scheduler.refresh();},requestFrame(callback){frames.set(++id,callback);return id;},cancelFrame(key){frames.delete(key);}});
  scheduler.refresh({type:'load'});assert.equal(measurements,1);assert.equal(frames.size,1);
  scheduler.refresh({type:'resize'});assert.equal(measurements,2);assert.equal(frames.size,1);
  scheduler.refresh({workspaceLayoutResize:true});assert.equal(measurements,2);
  scheduler.queue();scheduler.queue();assert.equal(measurements,2);assert.equal(frames.size,1);
  const callback=frames.values().next().value;frames.clear();callback();assert.equal(measurements,3);assert.equal(frames.size,0);
  scheduler.queue();assert.equal(frames.size,1);scheduler.dispose();assert.equal(frames.size,0);scheduler.refresh();scheduler.queue();assert.equal(measurements,3);
});
