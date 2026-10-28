import test from 'node:test';
import assert from 'node:assert/strict';
import {loadPriceHistory} from '../app/static/price-history-loader.js';

const payload={stock_id:1,start:'2026-01-05',end:'2026-01-12'};
test('selection shows cached quotes then fetches the entire selected range past liquidation',async()=>{
  const cached={needs_sync:true,points:[{date:'2026-01-08',close:10}]};
  const complete={needs_sync:false,points:[...cached.points,{date:'2026-01-12',close:11}]};
  const calls=[],shown=[];
  const api=async(path,options)=>{calls.push([path,options]);return options?complete:cached;};
  const result=await loadPriceHistory(api,payload,{onCached:data=>shown.push(data)});
  assert.deepEqual(shown,[cached]);
  assert.equal(calls.length,2);
  assert.equal(calls[0][0],'/api/stock-history?stock_id=1&start=2026-01-05&end=2026-01-12');
  assert.deepEqual(calls[1],['/api/stock-history/sync',{method:'POST',body:payload}]);
  assert.equal(result.data.points.at(-1).date,'2026-01-12');
});
test('covered cached range stays offline unless an explicit refresh is requested',async()=>{
  for(const force of [false,true]){
    const calls=[];const api=async(path,options)=>{calls.push(path);return {needs_sync:false,points:[]};};
    await loadPriceHistory(api,payload,{force});
    assert.equal(calls.length,force?2:1);
  }
});
test('network failure preserves cached chart and explains that the rest could not be loaded',async()=>{
  const cached={needs_sync:true,points:[{date:'2026-01-08',close:10}]};
  const api=async(path,options)=>{if(options)throw new Error('行情连接失败');return cached;};
  const result=await loadPriceHistory(api,payload);
  assert.equal(result.data,cached);assert.equal(result.warning,'行情连接失败');
});
test('stale selections do not start a sync or replace a newer chart',async()=>{
  let current=true,release;const shown=[],calls=[];
  const api=async(path,options)=>{calls.push(path);if(!options)return await new Promise(resolve=>release=resolve);return {};};
  const pending=loadPriceHistory(api,payload,{isCurrent:()=>current,onCached:data=>shown.push(data)});
  current=false;release({needs_sync:true,points:[]});
  assert.equal(await pending,null);assert.equal(calls.length,1);assert.deepEqual(shown,[]);
});
test('a late sync response is discarded after switching to another stock',async()=>{
  let current=true,release;const cached={needs_sync:true,points:[]};
  const api=async(path,options)=>options?await new Promise(resolve=>release=resolve):cached;
  const pending=loadPriceHistory(api,payload,{isCurrent:()=>current});
  await Promise.resolve();await Promise.resolve();
  assert.equal(typeof release,'function');current=false;release({points:[{date:'2026-01-12',close:11}]});
  assert.equal(await pending,null);
});
