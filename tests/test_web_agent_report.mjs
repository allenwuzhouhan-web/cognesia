import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../src/flybrain/web/agent-report.js', import.meta.url), 'utf8');
class Element {
  constructor(tag){this.tag=tag;this.children=[];this.textContent='';}
  append(...nodes){this.children.push(...nodes);}
  set innerHTML(value){throw new Error('Model text must not be parsed as HTML');}
}
test('paper renders exactly the five sections and treats model HTML as text', () => {
  const context = {window:{},document:{createElement:tag=>new Element(tag)},Date};
  vm.runInNewContext(source,context);
  const malicious='<img src=x onerror=alert(1)>';
  const paper = context.window.CognesiaReport.render({id:'study-1',started_at:0,report_scope:'0 live organisms',
    report:{title:malicious,abstract:malicious,methodology:'Methods',data:'Observations',analysis:'Interpretation',futures:'Next steps',evidence_ids:['call-1']},
    figures:[{figure_id:'abc123',title:'T4a',sample_count:3,plotted_samples:3,run_id:'run-1',source_sha256:'hash',interpretation:'Numeric evidence',warnings:['Gate failed'],statistics:{mean_mv:1,minimum_mv:0,maximum_mv:2,temporal_sd_mv:.5}}]});
  const nodes=[]; const visit=node=>{nodes.push(node);for(const child of node.children)visit(child);};visit(paper);
  assert.deepEqual(nodes.filter(n=>n.tag==='h3').map(n=>n.textContent),['Abstract','Methodology','Data','Analysis','Futures']);
  assert.equal(nodes.find(n=>n.tag==='h1').textContent,malicious);
  assert.equal(nodes.filter(n=>n.tag==='img').length,1);
  assert.equal(nodes.find(n=>n.tag==='img').src,'/api/studies/study-1/figures/abc123.png');
  assert.ok(nodes.some(n=>n.textContent==='Gate failed'));
});
