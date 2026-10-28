import test from 'node:test';
import assert from 'node:assert/strict';
import * as price from '../app/static/price-chart.js';

const p=(date,close,closed=false)=>({date,close,closed});
test('price stays visible outside holdings; entry and exit bound only the bold portion',()=>{
  const points=[p('01',10),p('02',11),p('03',12),p('04',9),p('05',10)];
  const paths=price.priceSegments(points,[{start:'02',end:'04'}]);
  assert.deepEqual(paths.map(s=>s.held),[false,true,true,false]);
  assert.equal(paths[0].from.close,10);
  assert.equal(paths.at(-1).to.close,10);
});
test('missing trading quotes break the line; verified holidays do not',()=>{
  const paths=price.priceSegments([p('01',10),p('02',null,true),p('03',11),p('04',null),p('05',12)],[]);
  assert.deepEqual(paths.map(s=>[s.from.date,s.to.date]),[['01','03']]);
  assert.deepEqual(price.priceIsolatedPoints([p('01',10),p('02',null),p('03',11)],[]).map(p=>p.date),['01','03']);
});
test('separate holding sessions do not bold the empty interval and same-day holdings get a dot',()=>{
  const intervals=[{start:'02',end:'02'},{start:'04',end:null}];
  assert.deepEqual(price.priceSegments([p('01',10),p('02',11),p('03',12),p('04',13),p('05',14)],intervals).map(s=>s.held),[false,false,false,true]);
  assert.equal(price.heldOn('02',intervals),true);
  assert.equal(price.heldOn('03',intervals),false);
});
test('boundaries retain real dates and combine an exit/reentry without inventing range endpoints',()=>{
  const intervals=[{start:'01',end:'03'},{start:'03',end:null}];
  assert.deepEqual(price.priceBoundaries(intervals,['02','03','04']),[{date:'03',label:'清仓 / 买入'}]);
  assert.deepEqual(price.priceBoundaries([{start:null,end:null}],['02']),[]);
  assert.equal(price.heldOn('02',[{start:null,end:null}]),true);
});
test('holding background is bounded by chart top, holding dates and the account profit curve',()=>{
  const totals=[{date:'01',value_cents:10},{date:'02',value_cents:20},{date:'03',value_cents:15},{date:'04',value_cents:30}];
  const areas=price.holdingAreas(totals,[{start:'02',end:'03'}],[500],i=>i*10,v=>100-v,5);
  assert.deepEqual(areas,[{pnl_cents:500,points:[[10,5],[20,5],[20,85],[10,80]]}]);
});
test('holding backgrounds respect gaps and clipped open sessions, and leave unknown or zero profit clear',()=>{
  const totals=[{date:'02',value_cents:20},{date:'03',value_cents:30},{date:'04',value_cents:null},{date:'05',value_cents:50,gap_before:true},{date:'06',value_cents:60}];
  const intervals=[{start:'01',end:null}];
  const areas=price.holdingAreas(totals,intervals,[-100],i=>i,v=>100-v,5);
  assert.deepEqual(areas.map(a=>a.points),[[[0,5],[1,5],[1,70],[0,80]],[[3,5],[4,5],[4,40],[3,50]]]);
  for(const pnl of [null,0,undefined])assert.deepEqual(price.holdingAreas(totals,intervals,[pnl],i=>i,v=>v,5),[]);
});
