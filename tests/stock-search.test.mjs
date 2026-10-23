import test from 'node:test';
import assert from 'node:assert/strict';
import {createStockLookup,stockLabel} from '../app/static/stock-search.js';

const catalog=[
  {code:'600118',name:'中国卫星',market:'SH',asset_type:'stock',first_level:'国防军工',second_level:'航天装备'},
  {code:'512880',name:'证券ETF',market:'SH',asset_type:'etf',fund_category:'行业',fund_theme:'证券'},
];
function fixture({offline=false}={}){
  const stocks=[{id:1,code:'000988',name:'华工科技',market:'SZ',asset_type:'stock'}];
  const sectors=[{id:10,name:'国防军工',level:1},{id:11,name:'航天装备',parent_id:10,level:2}];
  const lookup=createStockLookup(stocks,sectors,async(path,options)=>{
    if(path.startsWith('/api/catalog')){
      if(offline)throw new Error('目录暂不可用');
      const q=new URL('http://localhost'+path).searchParams.get('q');
      return catalog.filter(s=>s.code.includes(q)||s.name.includes(q));
    }
    if(path==='/api/stocks'&&options.method==='POST')return {id:stocks.length+1,...options.body};
    throw new Error('Unexpected request: '+path);
  });
  return {stocks,lookup};
}

test('searches partial names and codes beyond previously recorded stocks',async()=>{
  const {lookup}=fixture();
  assert.equal((await lookup.search('卫星'))[0].code,'600118');
  assert.equal((await lookup.search('118'))[0].name,'中国卫星');
  assert.equal((await lookup.search('华工'))[0].id,1);
});

test('resolves a full name, code or selected label and preserves classification',async()=>{
  const {lookup}=fixture();
  for(const query of ['中国卫星','600118',stockLabel(catalog[0])]){
    const result=await lookup.resolve(query);
    assert.equal(result.code,'600118');
    assert.equal(result.sector_id,11);
  }
  const etf=await lookup.resolve('512880');
  assert.equal(etf.asset_type,'etf');
  assert.equal(etf.fund_theme,'证券');
});

test('saving a new security reuses its identity on subsequent saves',async()=>{
  const {lookup,stocks}=fixture();
  const candidate=await lookup.resolve('中国卫星');
  const saved=await lookup.save(candidate);
  assert.equal(saved.id,2);
  assert.equal(stocks[1].name,'中国卫星');
  assert.equal((await lookup.resolve('600118')).id,2);
  assert.equal((await lookup.save(candidate)).id,2);
  assert.equal(stocks.length,2);
});

test('manual securities outside the catalog preserve leading zeros and infer the market',async()=>{
  const {lookup}=fixture({offline:true});
  const stock=await lookup.resolve('自定义证券',{code:'001234',name:'自定义证券',market:'',asset_type:'stock'});
  assert.equal(stock.code,'001234');
  assert.equal(stock.market,'SZ');
  assert.equal((await lookup.save(stock)).name,'自定义证券');
  assert.equal((await lookup.resolve('北交证券',{code:'920001',name:'北交证券',market:'',asset_type:'stock'})).market,'BJ');
});

test('an edited name cannot silently reuse the previous selection',async()=>{
  const {lookup}=fixture();
  await lookup.resolve('华工科技');
  await assert.rejects(lookup.resolve('不存在的名称'),/名称和代码/);
  await assert.rejects(lookup.resolve('卫星'),/完整名称或代码/);
  await assert.rejects(lookup.resolve('未收录',{code:'',name:'未收录'}),/名称和代码/);
});

test('existing securities remain usable if the catalog request fails',async()=>{
  const {lookup}=fixture({offline:true});
  assert.equal((await lookup.resolve('000988')).id,1);
  assert.equal((await lookup.search('华工'))[0].id,1);
});

test('ambiguous names require an explicit code or suggestion selection',async()=>{
  const {lookup,stocks}=fixture();
  stocks.push({id:3,code:'600001',name:'华工科技',market:'SH',asset_type:'stock'});
  await assert.rejects(lookup.resolve('华工科技'),/多只/);
  assert.equal((await lookup.resolve(stockLabel(stocks[1]))).id,3);
});

test('search suggestions prefer the existing stock identity and manually maintained name',async()=>{
  const {lookup,stocks}=fixture();
  stocks.push({id:2,code:'600118',name:'中国卫星（自定义）',market:'SH',asset_type:'stock',sector_id:99});
  const results=await lookup.search('600118');
  assert.equal(results.length,1);
  assert.equal(results[0].id,2);
  assert.equal(results[0].sector_id,99);
  assert.equal((await lookup.resolve('中国卫星')).name,'中国卫星（自定义）');
});
