import {api} from './api.js';

const normalize=value=>String(value??'').trim().toLowerCase();
const identity=stock=>`${normalize(stock.market)}|${normalize(stock.code)}`;
export const stockLabel=stock=>`${stock.code} · ${stock.name} · ${stock.market||'其他'}`;
const exact=(stock,query)=>[stock.code,stock.name,stockLabel(stock)].some(value=>normalize(value)===normalize(query));
const inferMarket=code=>/^(4|8|92)/.test(code)?'BJ':/^[569]/.test(code)?'SH':'SZ';

export function createStockLookup(stocks,sectors,request=api){
  const local=query=>stocks.filter(s=>!query||normalize(stockLabel(s)).includes(normalize(query)));
  const unique=items=>[...new Map(items.map(s=>[identity(s),s])).values()];
  const existing=stock=>stocks.find(s=>identity(s)===identity(stock));
  const catalogPayload=stock=>{
    const parent=sectors.find(s=>s.level===1&&s.name===stock.first_level);
    const sector=sectors.find(s=>s.level===2&&s.parent_id===parent?.id&&s.name===stock.second_level);
    return {code:stock.code,name:stock.name,market:stock.market,asset_type:stock.asset_type||'stock',
      ...(sector?{sector_id:sector.id}:{}),fund_category:stock.fund_category||'',fund_theme:stock.fund_theme||''};
  };
  async function searchCatalog(q){
    if(!q)return [];
    // A selected suggestion contains a label; the catalog accepts a name or code.
    const term=q.includes(' · ')?q.split(' · ')[0]:q;
    return request('/api/catalog?q='+encodeURIComponent(term)).catch(()=>[]);
  }
  async function search(query){
    const q=String(query??'').trim();
    const saved=local(q),catalog=await searchCatalog(q);
    return unique([...catalog,...saved]).sort((a,b)=>Number(exact(b,q))-Number(exact(a,q))||Number(Boolean(b.id))-Number(Boolean(a.id)));
  }
  async function resolve(query,manual=null){
    const q=String(query??'').trim();
    const saved=local(q).filter(s=>exact(s,q));
    if(saved.length>1&&!manual)throw new Error('名称匹配多只证券，请输入代码或选择完整搜索结果');
    if(saved.length===1&&!manual)return saved[0];
    if(manual){
      const code=String(manual.code??'').trim(),name=String(manual.name??'').trim();
      if(!code||!name)throw new Error('请补填证券名称和代码');
      if(!/^[0-9A-Za-z._-]{1,20}$/.test(code))throw new Error('证券代码格式无效');
      if(name.length>80)throw new Error('证券名称不能超过80个字符');
      const stock={code,name,market:manual.market||inferMarket(code),asset_type:manual.asset_type||'stock'};
      return existing(stock)||stock;
    }
    // Match catalog names before merging so a custom local name remains usable
    // through both its saved name and the catalog's canonical name.
    const results=[...local(q),...await searchCatalog(q)],matches=unique(results.filter(s=>exact(s,q)));
    if(matches.length>1)throw new Error('名称匹配多只证券，请输入代码或选择完整搜索结果');
    if(matches.length===1)return existing(matches[0])||catalogPayload(matches[0]);
    if(results.length)throw new Error('请选择搜索结果，或输入完整名称或代码');
    throw new Error('未找到证券，请展开手动录入并补填证券名称和代码');
  }
  async function save(stock){
    const saved=existing(stock);
    if(saved)return saved;
    const created=await request('/api/stocks',{method:'POST',body:stock});
    stocks.push(created);
    return created;
  }
  return {search,resolve,save};
}
