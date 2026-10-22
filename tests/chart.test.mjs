import test from 'node:test';
import assert from 'node:assert/strict';
import {makeLineSegments,assetParts,formatMoney} from '../app/static/charts.js';
import {makeDemo} from '../app/static/demo.js';
import * as charts from '../app/static/charts.js';

test('total segments respect gaps and use holding colors rather than profit direction',()=>{
  const points=[{date:'a',value_cents:0},{date:'b',value_cents:-100,daily_cents:-100},
    {date:'c',value_cents:null},{date:'d',value_cents:-50,gap_before:true,daily_cents:50},
    {date:'e',value_cents:0,daily_cents:50}];
  const assets=points.map(()=>({positions:[{stock_id:1,color:'#184BD8',market_value_cents:10000}]}));
  const segments=makeLineSegments(points,assets);
  assert.equal(segments.length,2);assert.equal(segments[0].color,'#184BD8');assert.equal(segments[1].color,'#184BD8');
  assert.equal(segments[1].from.date,'d');assert.equal(segments[1].to.date,'e');
});
test('multiple holding colors occupy their market value proportions without counting cash',()=>{
  const positions=[{stock_id:1,color:'#184BD8',market_value_cents:10000},{stock_id:2,color:'#F2DD87',market_value_cents:30000}];
  const colors=charts.holdingColorShares?.(positions);
  assert.deepEqual(colors?.map(c=>[c.color,c.share]),[['#184BD8',.25],['#F2DD87',.75]]);
  assert.deepEqual(charts.holdingColorShares?.([])?.map(c=>c.color),['#94A3B8']);
  assert.deepEqual(charts.holdingColorShares?.([...positions,{stock_id:3,market_value_cents:null}])?.map(c=>c.color),['#94A3B8']);
});
test('asset stack preserves total cash and holdings without using industry colors',()=>{
  const asset={total_assets_cents:150000,cash_cents:100000,daily_cents:100,positions:[
    {stock_id:1,color:'#184BD8',market_value_cents:10000},{stock_id:2,color:'#F2DD87',market_value_cents:40000}]};
  assert.deepEqual(charts.assetStack?.(asset)?.map(p=>p.value_cents),[100000,50000]);
  assert.deepEqual(charts.assetStack?.(asset)?.map(p=>p.color),['#DCE2ED','#D14343']);
  assert.deepEqual(charts.assetStack?.({...asset,positions:[]})?.map(p=>p.value_cents),[100000,50000]);
  assert.equal(charts.assetStack?.({total_assets_cents:null,cash_cents:null}),null);
});
test('asset columns use red for profit green for loss and gray for zero or unknown P&L',()=>{
  const base={total_assets_cents:200000,cash_cents:100000,positions:[{color:'#184BD8',market_value_cents:100000}]};
  for(const [daily,color] of [[100,'#D14343'],[-100,'#16845B'],[0,'#94A3B8'],[null,'#94A3B8']]){
    const parts=charts.assetStack({...base,daily_cents:daily});
    assert.equal(parts[0].color,'#DCE2ED');
    assert.equal(parts[1].color,color);
  }
  assert.equal(charts.assetStack({...base,daily_cents:-100,transfers:[{kind:'deposit',amount_cents:100000}]})[1].color,'#16845B');
});
test('mouse zoom anchors the pointed date and can return to the full range',()=>{
  const zoomed=charts.zoomWindow?.({start:20,end:39},.5,.5,100);
  assert.deepEqual(zoomed,{start:25,end:34});
  assert.deepEqual(charts.zoomWindow?.(zoomed,2,.5,100),{start:20,end:39});
  assert.deepEqual(charts.zoomWindow?.({start:0,end:99},.2,0,100),{start:0,end:19});
  assert.deepEqual(charts.zoomWindow?.({start:0,end:99},.2,1,100),{start:80,end:99});
  assert.deepEqual(charts.zoomWindow?.({start:25,end:34},100,.5,100),{start:0,end:99});
});
test('pan and zoom stay within loaded dates and handle one or no dates',()=>{
  assert.deepEqual(charts.panWindow?.({start:25,end:34},10,100),{start:35,end:44});
  assert.deepEqual(charts.panWindow?.({start:25,end:34},-100,100),{start:0,end:9});
  assert.deepEqual(charts.panWindow?.({start:25,end:34},100,100),{start:90,end:99});
  assert.deepEqual(charts.zoomWindow?.({start:0,end:1},.001,.5,100),{start:0,end:1});
  assert.deepEqual(charts.zoomWindow?.({start:0,end:0},.5,.5,1),{start:0,end:0});
  assert.deepEqual(charts.zoomWindow?.({start:0,end:-1},.5,.5,0),{start:0,end:-1});
});
test('asset stacks keep transfers as annotations',()=>{
  const a={total_assets_cents:1230000,cash_cents:430000,transfers:[{kind:'deposit',amount_cents:250000},{kind:'withdraw',amount_cents:50000}]};
  const p=assetParts(a);assert.equal(p.holdings_cents,800000);assert.equal(p.cash_cents+p.holdings_cents,1230000);assert.equal(p.transfers.length,2);
  assert.equal(assetParts({total_assets_cents:null,cash_cents:null}),null);
});
test('zero and integer cents display precisely',()=>{
  assert.equal(formatMoney(0),'0.00');assert.equal(formatMoney(30),'0.30');assert.equal(formatMoney(-12345),'-123.45');
});
test('demo uses one primary color across different secondary industries',()=>{
  const parents=[{level:1,name:'电子',color:'#184BD8'},{level:1,name:'通信',color:'#517AEC'}];
  const demo=makeDemo('2026-10-21',2,null,null,parents);
  const electronics=demo.series.filter(s=>s.first_level==='电子');
  assert.equal(electronics.length,2);
  assert.ok(electronics.every(s=>s.color==='#184BD8'));
  assert.equal(demo.series.find(s=>s.first_level==='通信').color,'#517AEC');
  assert.ok(demo.assets.every(a=>a.positions?.reduce((n,p)=>n+p.market_value_cents,0)===a.holdings_cents));
});
test('single day holdings and separate adjacent segments have visible markers',()=>{
  const a={date:'a',value_cents:0,gap_before:true},b={date:'b',value_cents:100,gap_before:true};
  const c={date:'c',value_cents:null},d={date:'d',value_cents:-20,gap_before:true},e={date:'e',value_cents:30};
  assert.deepEqual(charts.isolatedLinePoints?.([a,b,c,d,e]),[a,b]);
});
