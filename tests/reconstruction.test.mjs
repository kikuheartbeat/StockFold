import test from 'node:test';
import assert from 'node:assert/strict';
import {createReconstruction} from '../app/static/reconstruction.js';

function fixture(lastJob){
  const elements=new Map();
  for(const selector of ['#auto-run','#auto-opening','#auto-price','#auto-manual','#auto-result','#toast-stack'])elements.set(selector,{disabled:false,innerHTML:'',append(){}});
  globalThis.document={querySelector:s=>elements.get(s)||null,querySelectorAll:()=>[],createElement:()=>({classList:{add(){}},remove(){}})};
  const state={page:'history',autoMeta:{last_job:lastJob,opening:{positions:[{}]}},autoJob:{id:'lost',state:'running',completed:0,total:1}};
  return {state,elements,module:createReconstruction({state,editors:{}})};
}

test('server restart clears a missing job and allows another run',()=>{
  const f=fixture(null);f.module.bind();
  assert.equal(f.state.autoJob,null);
  assert.equal(f.elements.get('#auto-run').disabled,false);
  f.module.stop();
});

test('poll failure leaves a recoverable job and enabled retry',async()=>{
  const oldSet=globalThis.setTimeout,oldClear=globalThis.clearTimeout,oldFetch=globalThis.fetch;
  let callback;
  globalThis.setTimeout=(fn,ms)=>{if(ms===1100)callback=fn;return 1;};
  globalThis.clearTimeout=()=>{};
  globalThis.fetch=async()=>{throw new Error('Connection lost');};
  try{
    const f=fixture({id:'running',state:'running',completed:0,total:1});f.module.bind();
    await callback();
    assert.equal(f.state.autoJob.state,'error');
    assert.equal(f.elements.get('#auto-run').disabled,false);
    f.module.stop();
  }finally{globalThis.setTimeout=oldSet;globalThis.clearTimeout=oldClear;globalThis.fetch=oldFetch;}
});
