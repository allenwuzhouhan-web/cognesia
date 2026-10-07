import test from 'node:test';
import assert from 'node:assert/strict';
import {describeEyeColumn,describePeripheralMapping,filterSensoryEntries} from '../src/flybrain/web/sensory-maps.js';

test('optical maps preserve exact identities, column zero, and measured versus modeled provenance',()=>{
  const root='720575940635780000',receptors=[{column_index:0,root_id:root,cell_type:'R7'},{column_index:2,root_id:'2'}];
  const column=describeEyeColumn({column_index:0,column_id:'modeled-0',hemisphere:'left',p:0,q:1,azimuth_deg:0,elevation_deg:10,anchor_root_id:root,assignment_source:'ASSUMPTION: position-ranked optical column'},9,receptors);
  assert.equal(column.columnIndex,0);assert.equal(column.anchor,root);assert.deepEqual(column.receptors,[receptors[0]]);
  assert.equal(column.status,'Modeled column');assert.equal(column.coordinate,'p 0, q 1');assert.equal(column.angles,'0.0° azimuth · 10.0° elevation');
  assert.equal(describeEyeColumn({assignment_source:'curated_cross_specimen_column'},0).status,'Cross-specimen mapping');
  assert.equal(describeEyeColumn({azimuth_deg:null,elevation_deg:''},0).angles,'Viewing angles unavailable');
  assert.equal(describeEyeColumn(undefined,0),null);
});
test('peripheral maps never invent neural targets for absent organ mappings',()=>{
  const unmapped=describePeripheralMapping({id:'heart',label:'Heart',status:'modeled_physiology_only'});
  assert.equal(unmapped.status,'No neural mapping');assert.equal(unmapped.mapped,false);assert.deepEqual(unmapped.input,[]);assert.equal(unmapped.nerve,'Not annotated');
  const annotated=describePeripheralMapping({id:'leg-left',label:'Left leg',side:'left',nerve:'prothoracic_nerve',input_indices:[0,12],output_indices:[3]});
  assert.equal(annotated.status,'Annotated neural interface');assert.deepEqual(annotated.input,[0,12]);assert.deepEqual(annotated.output,[3]);
  assert.equal(describePeripheralMapping({...annotated,input_indices:[0],status:'annotated_and_explicitly_modeled_links'}).status,'Annotation + modeled links');
});
test('map search finds exact receptor IDs, organ names and source nerve names without numeric coercion',()=>{
  const entries=[{id:'eye-0',side:'left',receptors:[{root_id:'720575940635780000',cell_type:'R7'}]},
    describePeripheralMapping({id:'leg-left',label:'Front leg',side:'left',nerve:'prothoracic_nerve'})];
  assert.deepEqual(filterSensoryEntries(entries,'  LEFT R7 ').map(x=>x.id),['eye-0']);
  assert.deepEqual(filterSensoryEntries(entries,'720575940635780000').map(x=>x.id),['eye-0']);
  assert.deepEqual(filterSensoryEntries(entries,'leg prothoracic').map(x=>x.id),['leg-left']);
  assert.deepEqual(filterSensoryEntries(entries,'right'),[]);
});
