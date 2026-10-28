import {api,setToken,download} from './api.js';
import {$,$$,esc,money,tone,icon,toast,modal,confirmDialog,busy} from './ui.js';
import {renderCharts} from './charts.js';
import {makeDemo} from './demo.js';
import {createEditors} from './editors.js';
import {createReconstruction} from './reconstruction.js';
import {loadPriceHistory} from './price-history-loader.js';

const state={page:'overview',demo:false,stocks:[],sectors:[],settings:{},today:'',dashboard:null,
  start:null,end:null,range:90,industryLevel:2,
  ledger:[],pageIndex:0,search:'',kind:'',industryTab:'stocks',selectedParent:null,chartCleanup:null};
let priceStockId=0,priceHistory=null,priceRequest=0;
const pages={overview:['投资总览','grid'],daily:['每日记录','pen'],history:['历史补录','clock'],ledger:['交易流水','list'],industry:['股票与行业','layers'],data:['数据管理','database']};
const ctx={state,refresh:()=>refresh(),navigate:page=>navigate(page)};
const editors=createEditors(ctx);
const automatic=createReconstruction({...ctx,editors});

function showFailure(error){$('#app').innerHTML=`<div class="app-failure"><h2>暂时没有连接到本地服务</h2><p>${esc(error.message)}</p><p>请双击“启动.cmd”，然后重新打开页面。已经保存的数据不会丢失。</p><button class="btn btn-primary mt16" id="retry">重新连接</button></div>`;$('#retry').onclick=()=>location.reload();}
function displayDate(d){return new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short',timeZone:'Asia/Shanghai'}).format(new Date(d+'T12:00:00+08:00'));}
async function bootstrap(){const boot=await api('/api/bootstrap');setToken(boot.token);state.stocks=boot.stocks;state.sectors=boot.sectors;state.settings=boot.settings;state.today=boot.today;state.dataDir=boot.data_dir;state.paletteGroups=boot.palette_groups||[];return boot;}
async function refresh(){
  try{await bootstrap();await loadPage();}catch(error){toast(error.message,'error');}
}
async function loadPage(){
  priceRequest++;priceHistory=null;
  if(state.page==='overview'||state.page==='daily'||state.page==='history'){
    const q=new URLSearchParams({industry_level:state.industryLevel});if(state.start)q.set('start',state.start);if(state.end)q.set('end',state.end);
    state.dashboard=state.demo?makeDemo(state.today,state.industryLevel,state.start,state.end,state.sectors):await api('/api/dashboard?'+q);
    if(!state.dashboard.history_candidates?.some(s=>s.id===priceStockId))priceStockId=0;
  }
  if(state.page==='history')state.autoMeta=await api('/api/reconstruction/meta');
  if(state.page==='ledger')state.ledger=await api('/api/ledger');
  if(state.page==='data'){[state.files,state.backups]=await Promise.all([api('/api/import/available'),api('/api/backups')]);}
  render();
}
async function navigate(page){if(page==='history')state.demo=false;state.page=page;state.search='';state.pageIndex=0;await loadPage();window.scrollTo({top:0,behavior:'smooth'});}
function topActions(){return `<div class="heading-actions"><button class="btn btn-secondary" data-action="import">${icon('upload')}导入流水</button><button class="btn btn-secondary" data-action="record">${icon('pen')}手工记录</button><button class="btn btn-primary" data-action="auto">${icon('spark')}更新行情</button></div>`;}
function render(){
  state.chartCleanup?.();state.chartCleanup=null;automatic.stop();
  const page=pages[state.page];
  $('#app').innerHTML=`<aside class="sidebar"><div class="brand"><img src="/mark.svg" alt=""><div><div class="brand-name">StockFold</div><small>投资复盘工作台</small></div></div><div class="nav-caption">我的投资旅程</div><nav class="nav-list" aria-label="主导航">${Object.entries(pages).map(([id,[name,symbol]])=>`<button class="nav-item ${state.page===id?'active':''}" data-nav="${id}">${icon(symbol)}<span>${name}</span>${state.page===id?'<i class="nav-dot"></i>':''}</button>`).join('')}</nav><div class="sidebar-bottom"><div class="journal-invite">${icon('spark')}<h4>给今天留下一笔记录</h4><p>收益与交易，慢慢积累成自己的复盘。</p><button data-action="record">开始记录 ${icon('arrow','sm')}</button></div><div class="local-status"><i></i>数据安全保存在本机<button class="icon-btn" data-action="shutdown" aria-label="退出本地服务">${icon('power')}</button></div></div></aside>
  <main class="main"><div class="topbar"><div class="breadcrumb"><button class="icon-btn mobile-menu" id="mobile-menu" aria-label="展开导航">${icon('menu')}</button><span>我的工作台</span>${icon('chevron')}<strong>${page[0]}</strong></div><div class="topbar-actions"><span class="today-pill">${icon('calendar')}${displayDate(state.today)}</span><span class="avatar">S</span></div></div>
  ${state.demo?`<div class="demo-banner">${icon('spark')}<span><strong>示例预览</strong> · 仅展示界面效果，不写入你的账户</span><button class="btn-text" data-action="demo">退出示例 ${icon('close')}</button></div>`:''}
  <header class="page-heading"><div><h1>${page[0]}</h1><p>${({overview:'收益的变化，资金的去向，都在这里。',daily:'记录当天的表现，让每次复盘都有依据。',history:'读取交易、同步行情，自动还原每一天的收益与资产。',ledger:'把每一笔交易和资金流向，清楚地留存。',industry:'用一级行业颜色，串起同类股票的收益。',data:'数据属于你，保存在本机，也可以随时带走。'})[state.page]}</p></div>${topActions()}</header>
  <div id="page-body">${({overview:renderOverview,daily:renderDaily,history:renderHistory,ledger:renderLedger,industry:renderIndustry,data:renderData})[state.page]()}</div>
  <footer class="footer-note"><span>${icon('shield')}本地存储 · 离线可用 · StockFold 1.1</span><span>金额单位：人民币元 <span style="margin:0 7px;color:#d1cbdc">/</span> 行业参考：大盘云图 2026-10-19</span></footer></main>`;
  bindGlobal();({overview:bindOverview,daily:bindDaily,history:bindHistory,ledger:bindLedger,industry:bindIndustry,data:bindData})[state.page]();
}
function renderFilters(){
  const d=state.dashboard;
  return `<div class="filterbar"><span class="range-label">${icon('calendar')}回看时间</span><div class="segmented">${[[30,'近30天'],[90,'近90天'],[0,'全部']].map(([n,label])=>`<button data-range="${n}" class="${state.range===n?'active':''}">${label}</button>`).join('')}</div><div class="date-range"><input type="date" id="range-start" aria-label="开始日期" value="${d.metadata.start}"><span>—</span><input type="date" id="range-end" aria-label="结束日期" value="${d.metadata.end}"></div><span class="filter-spacer"></span><button class="btn-text" data-action="demo">${icon(state.demo?'close':'eye')}${state.demo?'退出示例':'看看示例效果'}</button></div>`;
}
function renderOverview(){
  const d=state.dashboard,s=d.summary,c=d.coverage;
  const kpis=[
    {name:c.complete?'累计盈亏':'已录累计盈亏',value:c.has_returns?s.recorded_cumulative_cents:null,icon:'trend',tone:tone(s.recorded_cumulative_cents),foot:c.has_returns?(c.complete?'从记录起点持续累计':'历史待补齐，仅汇总已录金额'):'从第一条收益记录开始',currency:true},
    {name:'当前区间盈亏',value:c.has_returns?s.period_pnl_cents:null,icon:'spark',tone:tone(s.period_pnl_cents),foot:`${d.metadata.start.slice(5)} — ${d.metadata.end.slice(5)} · ${d.dates.length}天`,currency:true},
    {name:'账户总资产',value:s.latest_assets_cents,icon:'wallet',tone:'',foot:s.latest_asset_date?`${s.latest_asset_date} · 现金 ¥${money(s.latest_cash_cents)}`:'填写总资产与现金后显示',currency:true},
    {name:'收益记录',value:c.confirmed_count,icon:'calendar',tone:'',foot:`${s.stock_count}只证券 · ${s.import_count}条导入流水`,days:true},
  ];
  const lastDates=d.total_series.filter(p=>p.status==='confirmed').slice(-5).reverse();
  const periodStocks=new Set(d.series.filter(s=>s.period_pnl_cents!==0).map(s=>s.id));
  const visibleSectors=d.sectors.filter(g=>g.pnl_cents!==0).map(g=>{
    const members=g.stock_ids.map((id,i)=>({id,name:g.stock_names[i]})).filter(s=>periodStocks.has(s.id));
    return {...g,stock_ids:members.map(s=>s.id),stock_names:members.map(s=>s.name)};
  });
  const sectorMax=Math.max(1,...visibleSectors.map(s=>Math.abs(s.pnl_cents)));
  const skipCount=d.total_series.filter(p=>p.status==='skip').length;
  const progress=Math.round((c.confirmed_count+skipCount)/Math.max(d.dates.length,1)*100);
  return `<div class="kpi-grid">${kpis.map(k=>`<section class="kpi"><div class="kpi-top"><span>${k.name}</span><span class="kpi-symbol">${icon(k.icon)}</span></div><div class="kpi-value ${k.tone}">${k.currency?'<span class="currency">¥</span>':''}${k.days?`${k.value}<small class="muted" style="font-size:12px;margin-left:6px;font-weight:400">天已确认</small>`:money(k.value,{sign:k.name.includes('盈亏')})}</div><div class="kpi-bottom">${k.foot}</div></section>`).join('')}</div>
  ${renderFilters()}${!c.complete&&c.has_returns?`<div class="coverage-note">${icon('info')}历史仍有 ${c.missing_count} 个自然日期待确认或标记无需记录，收益曲线保留缺口。<button class="btn-text" data-action="history">去补录</button></div>`:''}
  <div class="overview-layout"><section class="card trend-card combined-trend"><div class="card-header"><div><div class="card-title"><h2>收益与资产</h2><small>双轴 · 同步缩放</small></div><p class="card-subtitle">收益线用持仓配色；资产柱红涨绿跌，现金为灰色</p></div><div class="chart-top-actions"><button class="chart-zoom-button" id="chart-zoom-out" aria-label="缩小图表" title="缩小">−</button><button class="chart-zoom-button" id="chart-zoom-in" aria-label="放大图表" title="放大">+</button><button class="chart-zoom-button chart-reset" id="chart-reset" aria-label="复位图表">复位</button></div></div><div class="chart-window" id="chart-window"></div><div class="chart-wrap combined-chart" id="portfolio-chart"></div><div class="stock-legend" id="holding-legend"></div><div class="asset-footnote">${icon('info')}滚轮缩放 · 拖动平移 · 双击复位；柱内虚线表示银证转入 / 转出</div></section>
  <section class="card sector-card industry-table-card"><div class="card-header"><div><h2>行业贡献</h2><p class="card-subtitle">当前区间 · 仅显示有盈亏的行业与证券</p></div><button class="icon-btn" id="sector-sort" aria-label="切换排序">${icon('down')}</button></div><div class="segmented"><button data-level="1" class="${state.industryLevel===1?'active':''}">一级行业</button><button data-level="2" class="${state.industryLevel===2?'active':''}">二级行业</button></div><div class="table-scroll"><table class="data-table industry-contribution-table"><thead><tr><th>行业 / 类别</th><th>所属分类</th><th class="number">证券数量</th><th>包含证券</th><th class="number">区间盈亏（元）</th><th>盈亏贡献</th></tr></thead><tbody>${visibleSectors.map(g=>`<tr><td><span class="sector-label"><i class="legend-dot" style="background:${esc(g.color)}"></i>${esc(g.name)}</span></td><td>${esc(g.parent_name||'—')}</td><td class="number">${g.stock_ids.length}</td><td class="industry-stock-names">${g.stock_names.map(n=>esc(n)).join('、')}</td><td class="number ${tone(g.pnl_cents)}">${money(g.pnl_cents,{sign:true})}</td><td class="industry-contribution-bar"><div class="sector-track" aria-label="${esc(g.name)}贡献 ${money(g.pnl_cents,{sign:true})}元"><i class="sector-fill" style="background:${esc(g.color)};width:${Math.abs(g.pnl_cents)/sectorMax*50}%;${g.pnl_cents>=0?'left:50%':'right:50%'}"></i></div></td></tr>`).join('')||'<tr><td class="table-empty" colspan="6">当前区间没有盈利或亏损的行业。</td></tr>'}</tbody></table></div><div class="side-note">贡献条以中线区分方向：盈利向右、亏损向左；条形保留行业配色，金额为当前筛选区间的盈亏。</div></section><section class="card gentle-card overview-journal"><h3>${icon('pen','sm')} 复盘，留一点时间给自己</h3><p>${c.has_returns?'曲线的每一步，都来自你留下的真实记录。补齐缺口，才能看清完整的旅程。':'先导入交易，再自动获取历史收盘价。没有交易的日子，也能还原持仓盈亏。'}</p><button class="btn-text" data-action="history">${c.has_returns?'继续补录历史':'开始补录收益'} ${icon('arrow')}</button><div class="progress-bar"><span style="width:${progress}%"></span></div><div class="progress-caption"><span>当前区间已确认 ${c.confirmed_count} 天</span><span>${progress}%</span></div></section></div>
  <section class="card records-card"><div class="card-header"><h3>最近收益记录</h3><button class="btn-text" data-nav="daily">查看全部 ${icon('arrow')}</button></div><div class="table-scroll"><table class="data-table"><thead><tr><th>日期</th><th>当日盈亏</th><th>已录累计盈亏</th><th>记录状态</th><th></th></tr></thead><tbody>${lastDates.length?lastDates.map(p=>`<tr><td>${p.date}</td><td class="${tone(p.daily_cents)} mono">${money(p.daily_cents,{sign:true})}</td><td class="mono">${money(p.value_cents,{sign:true})}</td><td><span class="badge confirmed">${icon('check','sm')}已确认</span></td><td style="text-align:right"><button class="btn-text" data-edit-day="${p.date}">查看记录 ${icon('chevron')}</button></td></tr>`).join(''):'<tr><td class="table-empty" colspan="5">还没有已确认的收益记录。可以先从今天开始，也可以补录过去。</td></tr>'}</tbody></table></div></section>`;
}
function bindGlobal(){
  $$('[data-nav]').forEach(b=>b.onclick=()=>navigate(b.dataset.nav).catch(e=>toast(e.message,'error')));
  $$('[data-action]').forEach(b=>b.onclick=()=>action(b.dataset.action,b));
  $('#mobile-menu').onclick=()=>$('.sidebar').classList.toggle('open');
}
async function action(name,button){
  try{if(name==='record')await editors.dayEditor();else if(name==='import')await editors.importDialog();else if(name==='history'||name==='auto')await navigate('history');
    else if(name==='demo'){state.demo=!state.demo;state.page='overview';await loadPage();}
    else if(name==='shutdown')confirmDialog('退出本地服务？','已经保存的记录会保留。下次双击“启动.cmd”即可继续使用。',async()=>{await api('/api/shutdown',{method:'POST',body:{}});state.chartCleanup?.();$('#app').innerHTML='<div class="boot-screen"><span class="boot-mark">S</span><h2>本次记录，已经妥善收好</h2><p>本地服务已退出。下次双击“启动.cmd”继续。</p></div>';});
  }catch(e){toast(e.message,'error');}
}
function bindFilters(){
  $$('[data-range]').forEach(b=>b.onclick=async()=>{state.range=Number(b.dataset.range);state.end=state.today;const d=new Date(state.today+'T12:00:00Z');d.setUTCDate(d.getUTCDate()-Math.max(state.range-1,0));state.start=state.range?d.toISOString().slice(0,10):state.settings.record_start;await loadPage();});
  const change=async()=>{const a=$('#range-start').value,b=$('#range-end').value;if(!a||!b)return;if(a>b){toast('结束日期不能早于开始日期','error');return;}state.start=a;state.end=b;state.range=-1;try{await loadPage();}catch(e){toast(e.message,'error');}};
  $('#range-start').onchange=change;$('#range-end').onchange=change;
}
function drawOnly(){state.chartCleanup?.();state.chartCleanup=renderCharts($('#page-body'),state.dashboard,{onEmpty:()=>navigate('history'),priceHistory});}
async function loadPrice(sync=false){
  const request=++priceRequest,sid=priceStockId,d=state.dashboard;
  const status=$('#price-status'),update=$('#price-sync');
  priceHistory=null;drawOnly();
  update.disabled=!sid||state.demo;
  if(!sid){status.textContent='选择曾经持有的股票，查看股价与账户收益对照。';return;}
  status.textContent=sync?'正在更新该股行情…':'正在读取本地行情…';update.disabled=true;
  try{
    const payload={stock_id:sid,start:d.metadata.start,end:d.metadata.end};
    const isCurrent=()=>request===priceRequest&&state.page==='overview';
    const result=state.demo?{data:d.price_histories[sid]}:await loadPriceHistory(api,payload,{
      force:sync,isCurrent,
      onCached:data=>{priceHistory=data;drawOnly();},
      onSyncing:()=>{status.textContent='正在补齐整个所选区间的行情（包括买入前、清仓后）…';}
    });
    if(!result)return;
    const {data,warning}=result;
    if(request!==priceRequest||state.page!=='overview')return;
    priceHistory=data;drawOnly();
    const count=data.points.filter(p=>p.close!=null).length;
    status.textContent=`${state.demo?'示例行情 · ':''}不复权日收盘价 · ${count} 条价格 · 粗线为持有期间，虚线标记持仓边界 · 区间盈利淡红、亏损淡绿，收益曲线下方不填色${data.uncertain?' · 持仓依据待核对':''}${count?'':' · 点击“更新该股行情”获取价格'}。`;
    if(warning)status.textContent+=` 全区间行情暂未补齐：${warning}。已保留缓存走势，可点击“更新该股行情”重试。`;
  }catch(error){if(request===priceRequest&&state.page==='overview')status.textContent=error.message;}
  finally{if(request===priceRequest&&state.page==='overview')update.disabled=state.demo;}
}
function bindOverview(){
  bindFilters();
  const chart=$('#portfolio-chart'),controls=document.createElement('div');controls.className='price-controls';
  const candidates=state.dashboard.history_candidates||[];
  controls.innerHTML=`<div class="price-selector-row"><label for="price-stock">股票走势对照</label><select id="price-stock"><option value="0">仅看账户收益</option>${candidates.map(s=>`<option value="${s.id}" ${s.id===priceStockId?'selected':''}>${esc(s.name)} · ${esc(s.code)}</option>`).join('')}</select><button class="btn btn-sm btn-secondary" id="price-sync">更新该股行情</button></div><p id="price-status" role="status"></p>`;
  chart.before(controls);
  $('#price-stock').onchange=e=>{priceStockId=Number(e.target.value);loadPrice();};
  $('#price-sync').onclick=()=>loadPrice(true);
  loadPrice();
  const other=state.dashboard.summary.other_pnl_cents;
  if(other) $('.sector-card .side-note').insertAdjacentHTML('beforebegin',`<div class="side-note">账户其他收益 <strong class="${tone(other)}">${money(other,{sign:true})} 元</strong><br>计入账户总收益，单列于行业贡献之外。</div>`);
  const checks=state.dashboard.reconciliation;
  if(checks.length){const r=checks.at(-1),labels={ok:'对账一致',difference:'存在资产差额',review:'需核对其他资金事件',incomplete:'资料不完整，暂无法核对'};$('#page-body').insertAdjacentHTML('beforeend',`<section class="card records-card"><div class="tools-row"><div><h3>账户资产核对</h3><p class="card-subtitle">${esc(r.start)} 至 ${esc(r.end)} · 银证转账独立核对</p></div><span class="badge ${r.status==='ok'?'confirmed':'draft'}">${labels[r.status]}</span></div><div class="panel-body" style="padding-top:0;font-size:12px;color:#9590a7">${r.difference_cents==null?'请补齐期间收益并确认资金记录，再比较资产变化。':`期末总资产 − 期初总资产 − 净转入 − 期间收益 = <strong>${money(r.difference_cents,{sign:true})} 元</strong>`}${r.other_entries?`<p style="font-size:11px;margin-top:7px">期间有 ${r.other_entries} 条其他流水，请检查是否影响对账；程序不会把差额自动计作收益。</p>`:''}</div></section>`);}
  $$('[data-edit-day]').forEach(b=>b.onclick=()=>{if(state.demo){toast('这是示例记录，录入时会切换回真实账户');editors.dayEditor();}else editors.dayEditor(b.dataset.editDay);});
  $$('[data-level]').forEach(b=>b.onclick=async()=>{state.industryLevel=Number(b.dataset.level);await loadPage();});
  $('#sector-sort').onclick=()=>{state.dashboard.sectors.reverse();render();};
}
function renderDaily(){
  const now=new Date(state.today+'T12:00:00Z'),year=now.getUTCFullYear(),month=now.getUTCMonth();const first=new Date(Date.UTC(year,month,1)),days=new Date(Date.UTC(year,month+1,0)).getUTCDate(),offset=(first.getUTCDay()+6)%7;
  const recorded=new Set(state.dashboard.total_series.filter(p=>p.status==='confirmed').map(p=>p.date));
  return `<div class="daily-layout"><section class="card calendar-card"><div class="calendar-head"><h3>${year}年 ${month+1}月</h3><button class="btn-text" data-action="record">今天 ${icon('arrow')}</button></div><div class="calendar-days">${['一','二','三','四','五','六','日'].map(d=>`<span class="calendar-week">${d}</span>`).join('')}${'<span></span>'.repeat(offset)}${Array.from({length:days},(_,i)=>{const date=`${year}-${String(month+1).padStart(2,'0')}-${String(i+1).padStart(2,'0')}`;return `<button class="calendar-day ${date===state.today?'selected':''} ${recorded.has(date)?'recorded':''}" data-day="${date}">${i+1}</button>`;}).join('')}</div><div class="soft-note" style="margin-bottom:0">点击日期记录收益与账户快照；圆点表示该日收益已确认。其他月份可通过日期输入直接打开。</div><div class="mini-form"><input type="date" id="jump-date" value="${state.today}"><button class="btn btn-sm btn-quiet" id="jump-day">打开记录</button></div></section><section class="card daily-help"><div class="empty-glyph">${icon('pen')}</div><h2>给当天的表现，留一个清晰的注脚</h2><p>浮动盈亏和已卖出股票的盈亏都可以记录。股票没交易的日子，也值得留下收益变化。</p><ul class="step-list"><li><i>1</i>填写每只股票的当日盈亏</li><li><i>2</i>补上总资产与现金余额</li><li><i>3</i>核对当天交易后，确认并保存</li></ul><button class="btn btn-primary" data-action="record">${icon('plus')}记录今天</button></section></div>`;
}
function bindDaily(){$$('[data-day]').forEach(b=>b.onclick=()=>editors.dayEditor(b.dataset.day));$('#jump-day').onclick=()=>editors.dayEditor($('#jump-date').value);}
function renderHistory(){return automatic.render();}
function bindHistory(){automatic.bind();}
const kindNames={buy:'买入',sell:'卖出',deposit:'银证转入',withdraw:'银证转出',other:'其他流水'};
function renderLedger(){
  const entries=state.ledger.filter(l=>(!state.kind||l.kind===state.kind)&&(!state.search||[l.code,l.name,l.summary,l.date].join(' ').toLowerCase().includes(state.search.toLowerCase())));
  const size=25,count=entries.length,page=Math.min(state.pageIndex,Math.max(0,Math.ceil(count/size)-1));state.pageIndex=page;
  return `<section class="card"><div class="tools-row"><div class="search-box">${icon('search')}<input id="ledger-search" placeholder="搜索股票、摘要或日期" value="${esc(state.search)}"></div><div style="display:flex;gap:9px;align-items:center"><span class="list-count">${count}条流水</span><select id="ledger-kind-filter" class="tool-select"><option value="">全部类型</option>${Object.entries(kindNames).map(([v,n])=>`<option value="${v}" ${v===state.kind?'selected':''}>${n}</option>`).join('')}</select><button class="btn btn-sm btn-quiet" id="ledger-add">${icon('plus')}记录交易</button></div></div><div class="table-scroll"><table class="data-table"><thead><tr><th>日期</th><th>证券</th><th>类型</th><th class="number">数量</th><th class="number">价格</th><th class="number">资金发生额</th><th class="number">费用</th><th></th></tr></thead><tbody>${entries.slice(page*size,(page+1)*size).map(l=>`<tr><td class="nowrap">${l.date}</td><td><span class="stock-name">${esc(l.name||l.summary)}</span><div class="code">${esc(l.code||'资金事件')}</div></td><td><span class="badge ${l.kind}">${kindNames[l.kind]}</span></td><td class="number">${l.quantity||'—'}</td><td class="number">${Number(l.price_decimal)?Number(l.price_decimal).toFixed(4):'—'}</td><td class="number">${money(l.cash_change_cents,{sign:true})}</td><td class="number">${money(l.fees_cents)}</td><td><div class="row-actions"><button class="icon-btn" data-edit-ledger="${l.id}" aria-label="编辑这条流水">${icon('pen')}</button><button class="icon-btn" data-delete-ledger="${l.id}" aria-label="删除这条流水">${icon('trash')}</button></div></td></tr>`).join('')||'<tr><td class="table-empty" colspan="8">这里还没有流水。可以导入现有 Excel，也可以手动记录一笔交易。</td></tr>'}</tbody></table></div><div class="pagination"><span>${page+1} / ${Math.max(1,Math.ceil(count/size))} 页</span><button class="btn btn-sm btn-quiet" id="prev-page" ${page===0?'disabled':''}>上一页</button><button class="btn btn-sm btn-quiet" id="next-page" ${(page+1)*size>=count?'disabled':''}>下一页</button></div></section><div class="soft-note">交易金额是资金流向，不等于盈利。导入来源和原始字段保存在本地数据库，编辑操作会记录变更。</div>`;
}
function bindLedger(){let t;$('#ledger-search').oninput=e=>{const value=e.target.value;clearTimeout(t);t=setTimeout(()=>{state.search=value;state.pageIndex=0;render();const n=$('#ledger-search');n.focus();n.setSelectionRange(value.length,value.length);},240);};$('#ledger-kind-filter').onchange=e=>{state.kind=e.target.value;state.pageIndex=0;render();};$('#ledger-add').onclick=()=>editors.ledgerEditor();$('#prev-page').onclick=()=>{state.pageIndex--;render();};$('#next-page').onclick=()=>{state.pageIndex++;render();};$$('[data-edit-ledger]').forEach(b=>b.onclick=()=>editors.ledgerEditor(state.ledger.find(l=>l.id===Number(b.dataset.editLedger))));$$('[data-delete-ledger]').forEach(b=>b.onclick=()=>editors.deleteEntry(state.ledger.find(l=>l.id===Number(b.dataset.deleteLedger))));}
function renderIndustry(){
  const parents=state.sectors.filter(s=>s.level===1);if(!state.selectedParent)state.selectedParent=parents[0]?.id;
  const parent=parents.find(p=>p.id===state.selectedParent)||parents[0],children=state.sectors.filter(s=>s.parent_id===parent?.id);
  const stocks=state.stocks.filter(s=>!state.search||[s.code,s.name,s.first_level,s.second_level].join(' ').includes(state.search));
  return `<div class="tabs-row"><button class="btn btn-sm btn-quiet" id="palette-overview">查看31色总览</button><button class="tab-btn ${state.industryTab==='stocks'?'active':''}" data-industry-tab="stocks">股票归属</button><button class="tab-btn ${state.industryTab==='colors'?'active':''}" data-industry-tab="colors">行业色系 · ${parents.length}个一级行业</button></div>${state.industryTab==='stocks'?`<section class="card"><div class="tools-row"><div class="search-box">${icon('search')}<input id="stock-search" placeholder="搜索股票或行业" value="${esc(state.search)}"></div><button class="btn btn-sm btn-quiet" id="stock-add">${icon('plus')}添加股票 / ETF</button></div><div class="table-scroll"><table class="data-table"><thead><tr><th>证券</th><th>一级行业 / 类别</th><th>二级行业 / 主题</th><th>曲线配色</th><th></th></tr></thead><tbody>${stocks.map(s=>`<tr><td><span class="stock-name">${esc(s.name)}</span><span class="type-tag">${s.asset_type==='etf'?'ETF':s.asset_type==='product'?'资管':''}</span><div class="code">${esc(s.code)} · ${esc(s.market)}</div></td><td>${esc(s.first_level||s.fund_category||'未分类')}</td><td>${esc(s.second_level||s.fund_theme||(s.asset_type==='product'?'行业不适用':'未分类'))}</td><td><span class="table-tag"><i class="legend-line" style="color:${esc(s.color)}"></i>${esc(s.color)}</span></td><td style="text-align:right"><button class="btn-text" data-edit-stock="${s.id}">调整归属 ${icon('chevron')}</button></td></tr>`).join('')||'<tr><td class="table-empty" colspan="5">导入流水后，股票及行业归属会显示在这里。也可以手动添加。</td></tr>'}</tbody></table></div></section>`:`<div class="industry-layout"><section class="card industry-tree">${parents.map(p=>`<button class="industry-parent ${p.id===parent?.id?'active':''}" data-parent="${p.id}"><i class="legend-dot" style="background:${esc(p.color)}"></i>${esc(p.name)}<small>${state.sectors.filter(c=>c.parent_id===p.id).length}</small></button>`).join('')}<button class="industry-parent" id="new-parent">${icon('plus','sm')}新增一级行业</button></section><section class="card industry-detail"><div class="industry-header"><h3><span class="color-square" style="background:${esc(parent?.color||'#7967e8')}"></span>${esc(parent?.name||'行业')}</h3><button class="btn btn-sm btn-quiet" id="edit-parent">${icon('pen')}调整色系</button></div><p class="section-intro">同一一级行业下所有股票使用同一种颜色；二级行业保留分类，自动继承颜色。</p><div class="industry-children">${children.map(c=>`<button class="industry-child" data-child="${c.id}" style="text-align:left"><strong style="font-weight:500">${esc(c.name)}</strong><div class="sample-line" style="color:${esc(c.color)}"></div><small>${esc(c.color)} · ${state.stocks.filter(s=>s.sector_id===c.id).length}只股票</small></button>`).join('')}</div><button class="btn btn-quiet btn-sm mt16" id="new-child">${icon('plus')}新增二级行业</button><div class="soft-note">31个一级行业按关联组配色，可点击“查看31色总览”集中比较。二级行业不单独配色；行业颜色避开红、绿、黑。</div></section></div>`}`;
}
function showPalette(){
  const parents=state.sectors.filter(s=>s.level===1),known=new Set();
  const groups=(state.paletteGroups||[]).map(group=>({name:group.name,industries:group.industries.map(item=>parents.find(p=>p.name===item.name)).filter(Boolean)}));
  for(const g of groups)for(const p of g.industries)known.add(p.id);
  const extras=parents.filter(p=>!known.has(p.id));if(extras.length)groups.push({name:'新增或重命名的行业',industries:extras});
  const m=modal('一级行业 · 31色总览',`<p class="section-intro">按你指定的关联组排列。同一一级行业下的个股虚线统一用色，二级分类继续保留；红绿用于涨跌，黑色不用于行业。</p><div class="palette-groups">${groups.filter(g=>g.industries.length).map(g=>`<section class="palette-group"><h3>${esc(g.name)}</h3><div class="palette-swatches">${g.industries.map(p=>`<button class="palette-swatch" data-palette-id="${p.id}" aria-label="${esc(p.name+' '+p.color)}"><i style="background:${esc(p.color)}"></i><span><strong>${esc(p.name)}</strong><code>${esc(p.color)}</code></span><em style="border-color:${esc(p.color)}"></em></button>`).join('')}</div></section>`).join('')}</div><div class="soft-note">相近行业通过明暗、饱和度区分；同色股票可通过图例、名称和悬停金额辨认。点击色卡可进入该一级行业进行调整。</div>`,{wide:true});
  $$('[data-palette-id]',m.root).forEach(button=>button.onclick=()=>{state.industryTab='colors';state.selectedParent=Number(button.dataset.paletteId);m.close();render();});
}
function bindIndustry(){
  $('#palette-overview').onclick=showPalette;$$('[data-industry-tab]').forEach(b=>b.onclick=()=>{state.industryTab=b.dataset.industryTab;render();});if(state.industryTab==='stocks'){$('#stock-add').onclick=()=>editors.stockEditor();let timer;$('#stock-search').oninput=e=>{const v=e.target.value;clearTimeout(timer);timer=setTimeout(()=>{state.search=v;render();$('#stock-search').focus();},200);};$$('[data-edit-stock]').forEach(b=>b.onclick=()=>editors.stockEditor(state.stocks.find(s=>s.id===Number(b.dataset.editStock))));}else{$$('[data-parent]').forEach(b=>b.onclick=()=>{state.selectedParent=Number(b.dataset.parent);render();});$('#edit-parent').onclick=()=>editors.sectorEditor(state.sectors.find(s=>s.id===state.selectedParent));$('#new-parent').onclick=()=>editors.sectorEditor();$('#new-child').onclick=()=>editors.sectorEditor(null,state.selectedParent);$$('[data-child]').forEach(b=>b.onclick=()=>editors.sectorEditor(state.sectors.find(s=>s.id===Number(b.dataset.child))));}}
function renderData(){return `<div class="two-col"><section class="info-panel"><h3>${icon('upload')}导入历史交易</h3><p>支持原始18列表格和已标注行业的20列表格。先检查明细与重复记录，再确认导入。</p>${(state.files||[]).map((f,i)=>`<div class="available-file"><div class="file-info">${icon('folder')}<div><strong>${esc(f.name)}</strong><small>${(f.size/1024).toFixed(1)} KB · 本地现有文件</small></div></div><button class="btn btn-sm btn-quiet" data-import-file="${i}">预览</button></div>`).join('')}<button class="btn btn-secondary mt16" data-action="import">${icon('upload')}选择其他 Excel</button></section><section class="info-panel"><h3>${icon('shield')}备份，让记录留得更久</h3><p>完整备份包含收益、交易、账户快照、行业配色和导入来源。恢复前会自动备份当前数据。</p><div style="display:flex;gap:10px;flex-wrap:wrap"><button class="btn btn-primary" id="backup-now">${icon('down')}创建并下载备份</button><label class="btn btn-secondary" style="cursor:pointer">${icon('clock')}从备份恢复<input type="file" id="restore-file" accept=".sqlite3,.db" class="hidden"></label></div><div class="backup-list">${(state.backups||[]).map(f=>`<div class="backup-line"><span>${esc(f.name)}<small style="display:block">${(f.bytes/1024).toFixed(1)} KB</small></span><a href="${esc(f.download_url)}" download>下载</a></div>`).join('')||'<small class="muted" style="font-size:10px">还没有备份，建议在每次大批量补录后保存一份。</small>'}</div></section><section class="info-panel"><h3>${icon('down')}导出你的记录</h3><p>JSON 包含完整业务数据，CSV 方便在 Excel 中查看每日收益。需要完整恢复时，请使用数据库备份。</p><button class="btn btn-secondary" id="export-json">完整数据 JSON</button> <button class="btn btn-quiet" id="export-csv">日收益 CSV</button></section><section class="info-panel"><h3>${icon('folder')}记录起点与存储位置</h3><p>改变记录起点会改变累计统计范围，日期筛选只改变展示窗口。原始记录不会被删除。</p><div class="data-path">${esc(state.dataDir||'')}</div><div class="mini-form"><span class="muted" style="font-size:11px">收益记录起点</span><input type="date" id="record-start" value="${esc(state.settings.record_start)}"><button class="btn btn-sm btn-quiet" id="save-start">保存</button></div></section></div>`;}
function bindData(){$$('[data-import-file]').forEach(b=>b.onclick=()=>editors.importFile(state.files[Number(b.dataset.importFile)].name));$('#backup-now').onclick=e=>editors.backupNow(e.currentTarget);$('#restore-file').onchange=e=>{if(e.target.files[0])editors.restoreFile(e.target.files[0]);};$('#export-json').onclick=()=>download('/api/export');$('#export-csv').onclick=()=>download('/api/export?format=csv');$('#save-start').onclick=async e=>{try{await busy(e.currentTarget,()=>api('/api/settings',{method:'PUT',body:{record_start:$('#record-start').value}}));toast('记录起点已保存');state.start=null;await refresh();}catch(err){toast(err.message,'error');}};}

bootstrap().then(loadPage).catch(showFailure);
