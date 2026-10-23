import {api,fileBase64,download} from './api.js';
import {$,$$,esc,money,parseMoney,icon,modal,toast,busy,confirmDialog} from './ui.js';
import {createStockLookup,stockLabel} from './stock-search.js';

export function createEditors(ctx){
  const stockOptions=(selected='',empty=true)=>`${empty?'<option value="">选择股票 / ETF</option>':''}${ctx.state.stocks.map(s=>`<option value="${s.id}" ${Number(selected)===s.id?'selected':''}>${esc(s.code)} · ${esc(s.name)}${s.asset_type==='etf'?' · ETF':''}</option>`).join('')}`;
  const field=(label,name,value='',type='text',extra='')=>`<div class="field"><label for="f-${name}">${label}</label><input id="f-${name}" name="${name}" type="${type}" value="${esc(value)}" ${extra}></div>`;
  const showError=(root,error)=>{const n=$('.form-error',root);if(n){n.textContent=error.message;n.classList.add('error-note');}else toast(error.message,'error');};
  const amountValue=value=>value==null?'':(value/100).toFixed(2);
  const ensureReal=()=>{if(ctx.state.demo){ctx.state.demo=false;ctx.refresh();}};

  async function dayEditor(date=ctx.state.today){
    ensureReal();
    let data;try{data=await api(`/api/days/${date}`);}catch(e){toast(e.message,'error');return;}
    const account=data.account||{};
    const initial=[...data.returns];
    for(const sid of data.expected_stock_ids||[])if(!initial.some(r=>r.stock_id===sid))initial.push({stock_id:sid,pnl_cents:null});
    if(!initial.length)initial.push({stock_id:'',pnl_cents:null});
    const m=modal('记录今天的投资表现',`${data.returns.some(r=>r.source==='market_close')?'<div class="soft-note">这一天来自行情自动还原；手工保存后将作为校准记录，后续自动计算会保护该日期。</div>':''}<div class="form-grid">${field('记录日期','date',date,'date')}<div class="field"><label>记录状态</label><select id="day-status"><option value="confirmed" ${data.status==='confirmed'||data.status==='draft'?'selected':''}>已核对，确认当日收益</option><option value="draft">先存草稿，稍后补齐</option><option value="skip" ${data.status==='skip'?'selected':''}>休市 / 明确无需记录</option></select></div></div>
      <div class="form-section"><div class="form-section-heading"><h3>个股当日收益 <small>元 · 已包含手续费影响</small></h3><button class="btn-text" id="add-return">${icon('plus')}添加股票</button></div><div id="return-rows"></div><div class="soft-note">请包含当天仍持有、以及当天已卖出的股票。收益为零请填写 0；留空表示待补录。收益金额不会从交易流水自动推算。</div></div>
      <div class="form-section"><div class="form-section-heading"><h3>收盘账户快照</h3><small>可暂时留空，后续补录</small></div><div class="form-grid">${field('账户总资产（元）','total',amountValue(account.total_assets_cents),'text','inputmode="decimal" placeholder="股票市值 + 账户现金"')}${field('现金余额（元）','cash',amountValue(account.cash_cents),'text','inputmode="decimal" placeholder="券商显示的现金余额"')}${field('账户其他收益（元）','other',amountValue(account.other_pnl_cents??0),'text','inputmode="decimal"')}${field('备注','note',data.note||'','text','placeholder="给今天留一条复盘笔记"')}</div><small class="muted" style="font-size:10px;display:block;margin-top:10px">其他收益用于单列利息等；若已包含在个股收益中，请勿重复填写。</small></div>
      <div class="form-section"><div class="form-section-heading"><h3>当天交易与转账 <small>${data.ledger.length} 笔</small></h3><button class="btn-text" id="day-add-ledger">${icon('plus')}记买卖 / 转账</button></div><div id="day-ledger-summary">${data.ledger.length?data.ledger.slice(0,6).map(l=>`<div class="tooltip-row"><span>${esc(l.summary)} ${esc(l.name||'')}</span><b>${money(l.cash_change_cents,{sign:true})} 元</b></div>`).join(''):'<small class="muted">没有交易也可以记录持仓收益。</small>'}</div></div>
      <div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="day-cancel">取消</button><button class="btn btn-primary" id="save-day">${icon('check')}保存记录</button></div>`,{drawer:true,subtitle:'每天几分钟，留下可追溯的投资记录'});
    const lookup=createStockLookup(ctx.state.stocks,ctx.state.sectors);
    let rowSequence=0;
    const append=(r={stock_id:'',pnl_cents:null})=>{
      const stock=ctx.state.stocks.find(s=>s.id===r.stock_id),listId=`day-stock-options-${++rowSequence}`;
      const row=document.createElement('div');row.className='return-entry';row.innerHTML=`<div class="return-row"><input class="return-stock" aria-label="股票名称或代码" role="combobox" aria-autocomplete="list" list="${listId}" autocomplete="off" placeholder="输入股票名称或代码" value="${esc(stock?stockLabel(stock):'')}"><input class="return-pnl" aria-label="当日收益金额" type="text" inputmode="decimal" placeholder="盈亏金额" value="${esc(amountValue(r.pnl_cents))}"><button class="icon-btn remove-return" aria-label="移除这条收益">${icon('close')}</button></div><datalist id="${listId}"></datalist><details class="manual-stock"><summary>未找到证券？手动录入</summary><div class="form-grid"><div class="field"><label>证券代码<input class="manual-code" aria-label="手动证券代码" placeholder="例如 002281" maxlength="20"></label></div><div class="field"><label>证券名称<input class="manual-name" aria-label="手动证券名称" placeholder="填写完整名称" maxlength="80"></label></div><div class="field"><label>市场<select class="manual-market" aria-label="手动证券市场"><option value="">按代码自动识别</option>${['SZ','SH','BJ','OTC'].map(v=>`<option>${v}</option>`).join('')}</select></label></div><div class="field"><label>证券类型<select class="manual-type" aria-label="手动证券类型"><option value="stock">股票</option><option value="etf">ETF</option><option value="product">资管产品</option></select></label></div></div></details>`;
      const input=$('.return-stock',row),list=$('datalist',row),manual=$('details',row);
      const renderOptions=results=>{list.innerHTML=results.slice(0,25).map(s=>`<option value="${esc(stockLabel(s))}"></option>`).join('');};
      renderOptions(ctx.state.stocks);
      let timer,revision=0;
      const search=()=>{
        const current=++revision;clearTimeout(timer);
        timer=setTimeout(async()=>{const results=await lookup.search(input.value);if(current===revision&&row.isConnected)renderOptions(results);},200);
      };
      input.oninput=()=>{manual.open=false;$('.manual-code',row).value='';$('.manual-name',row).value='';$('.manual-market',row).value='';$('.manual-type',row).value='stock';search();};input.onfocus=search;
      manual.ontoggle=()=>{if(manual.open){const q=input.value.trim();if(/^[0-9A-Za-z._-]+$/.test(q)){$('.manual-code',row).value||=q;}else if(q&&!q.includes(' · ')){$('.manual-name',row).value||=q;}}};
      $('.remove-return',row).onclick=()=>{clearTimeout(timer);revision++;row.remove();};$('#return-rows',m.root).append(row);
    };
    initial.forEach(append);$('#add-return',m.root).onclick=()=>append();$('#day-cancel',m.root).onclick=m.close;
    const collect=async(forceStatus=null)=>{
      const records=[],expected=[],pending=[],seen=new Set();
      const status=forceStatus||$('#day-status',m.root).value;
      const account={total_assets_cents:parseMoney($('#f-total',m.root).value,true),cash_cents:parseMoney($('#f-cash',m.root).value,true),other_pnl_cents:parseMoney($('#f-other',m.root).value||'0')};
      for(const row of $$('.return-entry',m.root)){
        const query=$('.return-stock',row).value.trim(),value=$('.return-pnl',row).value.trim();
        const details=$('details',row),manual=details.open?{code:$('.manual-code',row).value,name:$('.manual-name',row).value,market:$('.manual-market',row).value,asset_type:$('.manual-type',row).value}:null;
        if(!query&&!manual?.code&&!manual?.name){if(value)throw new Error('请先为收益输入股票名称或代码');continue;}
        const pnl=value?parseMoney(value):null;
        if(status==='confirmed'&&pnl===null)throw new Error('请补齐应录股票收益，包括明确为零的记录');
        let stock;try{stock=await lookup.resolve(query,manual);}catch(error){if(error.message.includes('名称和代码'))details.open=true;$('.return-stock',row).focus();throw error;}
        const key=stock.market+'|'+stock.code;
        if(seen.has(key))throw new Error('同一天同一股票只能有一条收益');
        seen.add(key);pending.push({stock,pnl});
      }
      for(const item of pending){const stock=await lookup.save(item.stock);expected.push(stock.id);if(item.pnl!==null)records.push({stock_id:stock.id,pnl_cents:item.pnl});}
      if(status!=='skip')for(const l of data.ledger)if(['buy','sell'].includes(l.kind)&&l.stock_id&&!expected.includes(l.stock_id))expected.push(l.stock_id);
      return {returns:records,expected_stock_ids:expected,status,note:$('#f-note',m.root).value,account};
    };
    $('#f-date',m.root).onchange=()=>{const next=$('#f-date',m.root).value;if(next){m.close();dayEditor(next);}};
    $('#save-day',m.root).onclick=async e=>{try{await busy(e.currentTarget,async()=>{const payload=await collect();await api(`/api/days/${$('#f-date',m.root).value}`,{method:'PUT',body:payload});});m.close();toast('记录已保存，图表已更新');await ctx.refresh();}catch(err){showError(m.root,err);}};
    $('#day-add-ledger',m.root).onclick=async()=>{
      try{await busy($('#day-add-ledger',m.root),async()=>{const p=await collect('draft');await api(`/api/days/${date}`,{method:'PUT',body:p});});m.close();toast('收益和资产已暂存为草稿');await ledgerEditor(null,date,()=>dayEditor(date));}
      catch(err){showError(m.root,err);}
    };
  }

  async function ledgerEditor(entry=null,date=ctx.state.today,afterSaved=null){
    ensureReal();const e=entry||{};
    const m=modal(entry?'编辑交易流水':'记录交易与转账',`<div class="form-grid">${field('日期','date',e.date||date,'date')}<div class="field"><label>流水类型</label><select id="ledger-kind">${[['buy','证券买入'],['sell','证券卖出'],['deposit','银行转证券'],['withdraw','证券转银行'],['other','其他资金事件']].map(([v,n])=>`<option value="${v}" ${e.kind===v?'selected':''}>${n}</option>`).join('')}</select></div><div class="field field-full trade-field"><label>股票 / ETF</label><select id="ledger-stock">${stockOptions(e.stock_id)}</select></div>${field('成交数量（股/份）','quantity',e.quantity?Math.abs(e.quantity):'','number','min="1" step="1" class="trade-control"')}${field('成交价格（元）','price',e.price_decimal||'','text','inputmode="decimal" class="trade-control"')}${field('手续费合计（元）','fees',amountValue(e.fees_cents||0),'text','inputmode="decimal" class="trade-control"')}${field('转账金额（元）','amount',amountValue(e.amount_cents),'text','inputmode="decimal" class="transfer-control"')}${field('其他资金发生额（可正负）','change',amountValue(e.cash_change_cents),'text','inputmode="decimal" class="other-control"')}${field('摘要 / 备注','note',e.note||e.summary||'')}</div><div class="soft-note">买卖和银证转账记录资金流向，不会再次计入已填写的日收益。买卖手续费请填佣金、印花税、过户费合计，不重复加净佣金。仅修改备注会保留原成交金额；修改股票、类型、数量或价格将按数量 × 价格重新计算。</div><div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="ledger-cancel">取消</button><button class="btn btn-primary" id="ledger-save">保存流水</button></div>`,{subtitle:entry?.import_row_id?'保留原导入来源，编辑会记录变更':'把交易与收益分开记录，避免重复计算'});
    const kind=$('#ledger-kind',m.root);
    const update=()=>{const trade=['buy','sell'].includes(kind.value),transfer=['deposit','withdraw'].includes(kind.value);$('.trade-field',m.root).classList.toggle('hidden',!trade);$$('.trade-control',m.root).forEach(n=>n.closest('.field').classList.toggle('hidden',!trade));$('.transfer-control',m.root).closest('.field').classList.toggle('hidden',!transfer);$('.other-control',m.root).closest('.field').classList.toggle('hidden',kind.value!=='other');};
    kind.onchange=update;update();$('#ledger-cancel',m.root).onclick=m.close;
    $('#ledger-save',m.root).onclick=async ev=>{
      try{await busy(ev.currentTarget,async()=>{const type=kind.value,trade=['buy','sell'].includes(type);const p={date:$('#f-date',m.root).value,kind:type,note:$('#f-note',m.root).value};
        if(trade){p.stock_id=Number($('#ledger-stock',m.root).value);p.quantity=Number($('#f-quantity',m.root).value);p.price_decimal=$('#f-price',m.root).value;p.fees_cents=parseMoney($('#f-fees',m.root).value||'0');}
        else if(type==='other')p.cash_change_cents=parseMoney($('#f-change',m.root).value);
        else p.amount_cents=parseMoney($('#f-amount',m.root).value);
        await api(entry?`/api/ledger/${entry.id}`:'/api/ledger',{method:entry?'PUT':'POST',body:p});});m.close();toast('流水已保存');await ctx.refresh();afterSaved?.();}
      catch(err){showError(m.root,err);}
    };
  }

  function batchEditor(){
    ensureReal();
    const m=modal('批量补录历史收益',`<p class="section-intro">从 Excel 复制三列：日期、证券代码、当日收益（元），直接粘贴在下方。每行一只股票的一天。</p><div class="field"><label>支持制表符或逗号分隔，可包含表头</label><textarea class="paste-input" id="batch-data" placeholder="2026-10-19&#9;002281&#9;350.00&#10;2026-10-19&#9;603893&#9;-120.50"></textarea></div><div class="soft-note">同日同股票会更新为本次填写值，不会叠加。金额是当天盈亏，不是成交金额或累计收益。</div><label class="check-label"><input type="checkbox" id="batch-confirm">我已包含这些日期的全部应录股票，同时确认当日收益。未勾选则保存为草稿，可逐日核对。</label><div class="form-error"></div><div id="batch-preview" class="mt16"></div><div class="modal-actions"><button class="btn btn-quiet" id="batch-check">检查格式</button><button class="btn btn-primary" id="batch-save">${icon('check')}保存补录</button></div>`,{wide:true});
    const parse=()=>{
      const lines=$('#batch-data',m.root).value.trim().split(/\r?\n/).filter(x=>x.trim());const rows=[];const seen=new Set();
      for(let i=0;i<lines.length;i++){
        const cells=lines[i].split(/\t|,|，/).map(x=>x.trim());if(i===0&&cells[0].includes('日期'))continue;
        if(cells.length!==3)throw new Error(`第${i+1}行需要日期、证券代码、当日收益三列`);
        let [date,code,value]=cells;date=date.replaceAll('/','-');if(/^\d{8}$/.test(date))date=`${date.slice(0,4)}-${date.slice(4,6)}-${date.slice(6)}`;
        if(!/^\d{4}-\d{2}-\d{2}$/.test(date))throw new Error(`第${i+1}行日期格式无效`);
        code=code.replace(/^'/,'').padStart(6,'0');const s=ctx.state.stocks.find(s=>s.code===code);if(!s)throw new Error(`第${i+1}行证券 ${code} 尚未添加，请先导入流水或添加股票`);
        const key=date+'|'+s.id;if(seen.has(key))throw new Error(`第${i+1}行与前面日期、股票重复`);seen.add(key);
        rows.push({date,stock_id:s.id,pnl_cents:parseMoney(value)});
      }if(!rows.length)throw new Error('请先粘贴收益数据');return rows;
    };
    const preview=()=>{const rows=parse();$('#batch-preview',m.root).innerHTML=`<div class="soft-note">检查通过：${rows.length}条收益，覆盖${new Set(rows.map(r=>r.date)).size}个日期，已录金额合计 ${money(rows.reduce((s,r)=>s+r.pnl_cents,0),{sign:true})} 元。实际日期有效性由保存时再次校验。</div>`;return rows;};
    $('#batch-check',m.root).onclick=()=>{try{preview();$('.form-error',m.root).textContent='';}catch(e){showError(m.root,e);}};
    $('#batch-save',m.root).onclick=async e=>{try{const rows=preview();await busy(e.currentTarget,()=>api('/api/returns/batch',{method:'POST',body:{rows,confirm:$('#batch-confirm',m.root).checked}}));m.close();toast(`已保存${rows.length}条历史收益`);await ctx.refresh();}catch(err){showError(m.root,err);}};
  }

  function stockEditor(stock=null){
    ensureReal();const s=stock||{};
    const parents=ctx.state.sectors.filter(s=>s.level===1);
    const options=()=>`<option value="">未分类</option>${parents.map(p=>`<optgroup label="${esc(p.name)}">${ctx.state.sectors.filter(c=>c.parent_id===p.id).map(c=>`<option value="${c.id}" ${s.sector_id===c.id?'selected':''}>${esc(c.name)}</option>`).join('')}</optgroup>`).join('')}`;
    const m=modal(stock?'修改股票归属':'添加股票或 ETF',`<div class="form-grid">${field('证券代码','code',s.code||'','text','placeholder="例如 002281"')}${field('证券名称','name',s.name||'')}<div class="field field-full"><div id="catalog-results" class="hidden"></div></div><div class="field"><label>资产类型</label><select id="stock-type">${[['stock','A股股票'],['etf','ETF'],['product','资管产品']].map(([v,n])=>`<option value="${v}" ${s.asset_type===v?'selected':''}>${n}</option>`).join('')}</select></div><div class="field"><label>市场</label><select id="stock-market">${['SZ','SH','BJ','OTC'].map(v=>`<option ${s.market===v?'selected':''}>${v}</option>`).join('')}</select></div><div class="field field-full" id="stock-sector-field"><label>二级行业（同时关联其一级行业）</label><select id="stock-sector">${options()}</select></div>${field('ETF 类别','fund-category',s.fund_category||'')}${field('ETF 指数 / 主题','fund-theme',s.fund_theme||'')}</div><div class="soft-note">行业参考大盘云图 2026-10-19 快照，允许你手动修正。修改后历史归属和颜色一起更新，收益金额不变。</div><div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="stock-cancel">取消</button><button class="btn btn-primary" id="stock-save">保存归属</button></div>`);
    const type=$('#stock-type',m.root);const update=()=>{$('#stock-sector-field',m.root).classList.toggle('hidden',type.value!=='stock');$('#f-fund-category',m.root).closest('.field').classList.toggle('hidden',type.value!=='etf');$('#f-fund-theme',m.root).closest('.field').classList.toggle('hidden',type.value!=='etf');};type.onchange=update;update();
    let timeout;$('#f-code',m.root).oninput=()=>{clearTimeout(timeout);const q=$('#f-code',m.root).value;timeout=setTimeout(async()=>{try{const results=await api('/api/catalog?q='+encodeURIComponent(q));const container=$('#catalog-results',m.root);if(!container)return;container.className=results.length?'catalog-results':'hidden';container.innerHTML=results.slice(0,7).map((r,i)=>`<button type="button" data-index="${i}">${esc(r.code)} · ${esc(r.name)}<small>${esc(r.first_level||'ETF / '+r.fund_category)} / ${esc(r.second_level||r.fund_theme||'')}</small></button>`).join('');$$('button',container).forEach(button=>button.onclick=()=>{const r=results[Number(button.dataset.index)];$('#f-code',m.root).value=r.code;$('#f-name',m.root).value=r.name;$('#stock-market',m.root).value=r.market;type.value=r.asset_type;$('#f-fund-category',m.root).value=r.fund_category||'';$('#f-fund-theme',m.root).value=r.fund_theme||'';const p=parents.find(p=>p.name===r.first_level);const c=ctx.state.sectors.find(c=>c.parent_id===p?.id&&c.name===r.second_level);$('#stock-sector',m.root).value=c?.id||'';container.className='hidden';update();});}catch{}},260);};
    $('#stock-cancel',m.root).onclick=m.close;$('#stock-save',m.root).onclick=async e=>{try{const payload={code:$('#f-code',m.root).value,name:$('#f-name',m.root).value,market:$('#stock-market',m.root).value,asset_type:type.value,sector_id:type.value==='stock'?Number($('#stock-sector',m.root).value)||null:null,fund_category:$('#f-fund-category',m.root).value,fund_theme:$('#f-fund-theme',m.root).value};await busy(e.currentTarget,()=>api(stock?`/api/stocks/${stock.id}`:'/api/stocks',{method:stock?'PUT':'POST',body:payload}));m.close();toast('股票归属已更新');await ctx.refresh();}catch(err){showError(m.root,err);}};
  }

  function sectorEditor(sector=null,parentId=null){
    ensureReal();const s=sector||{};const level=s.level||(parentId?2:1);
    const parents=ctx.state.sectors.filter(p=>p.level===1);
    const m=modal(sector?'调整行业名称与颜色':'新增行业',`<div class="form-grid">${field('行业名称','sector-name',s.name||'')}<div class="field"><label>行业层级</label><select id="sector-level" ${sector?'disabled':''}><option value="1" ${level===1?'selected':''}>一级行业 · 色系</option><option value="2" ${level===2?'selected':''}>二级行业 · 继承一级颜色</option></select></div><div class="field field-full" id="parent-field"><label>所属一级行业</label><select id="sector-parent">${parents.map(p=>`<option value="${p.id}" ${(s.parent_id||parentId)===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select></div><div class="field"><label>行业颜色</label><input type="color" id="sector-color" value="${esc(s.color||'#7967e8')}"></div><div class="field"><label>颜色值</label><input id="sector-hex" value="${esc(s.color||'#7967e8')}"></div></div><div class="soft-note">仅一级行业设置颜色，二级行业自动继承，不单独配色。关联一级行业可使用相近颜色；支持鹅黄、粉色和亮橙，行业色避开红、绿、黑。修改一级颜色会同步所有下属分类与股票。</div><div id="sector-preview" class="color-preview"></div><div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="sector-preview-btn">预览颜色</button><button class="btn btn-primary" id="sector-save">应用并保存</button></div>`);
    const levelInput=$('#sector-level',m.root),color=$('#sector-color',m.root),hex=$('#sector-hex',m.root);const update=()=>{const child=Number(levelInput.value)===2;$('#parent-field',m.root).classList.toggle('hidden',!child);color.closest('.field').classList.toggle('hidden',child);hex.closest('.field').classList.toggle('hidden',child);if(child){const p=parents.find(p=>p.id===Number($('#sector-parent',m.root).value));color.value=p?.color||'#7967e8';hex.value=color.value;}};levelInput.onchange=update;$('#sector-parent',m.root).onchange=update;update();color.oninput=()=>hex.value=color.value;hex.oninput=()=>{if(/^#[0-9a-f]{6}$/i.test(hex.value))color.value=hex.value;};
    const payload=()=>({name:$('#f-sector-name',m.root).value,level:Number(levelInput.value),parent_id:Number(levelInput.value)===2?Number($('#sector-parent',m.root).value):null,color:hex.value});
    let previewed=null;
    $('#sector-preview-btn',m.root).onclick=async()=>{try{const p=payload();if(sector){const result=await api(`/api/sectors/${sector.id}`,{method:'PUT',body:{...p,preview:true}});$('#sector-preview',m.root).innerHTML=(result.children.length?result.children:[result]).map(c=>`<span class="color-swatch"><i style="background:${esc(c.color)}"></i>${esc(c.name)}</span>`).join('');previewed=JSON.stringify(p);}else{$('#sector-preview',m.root).innerHTML=`<span class="color-swatch"><i style="background:${esc(color.value)}"></i>${esc(p.name||'新行业')}</span>`;}}catch(err){showError(m.root,err);}};
    $('#sector-save',m.root).onclick=async e=>{try{const p=payload();if(sector?.level===1&&p.color.toUpperCase()!==sector.color.toUpperCase()&&previewed!==JSON.stringify(p)){await $('#sector-preview-btn',m.root).onclick();toast('已预览一级行业统一颜色，再点击“应用并保存”即可同步');return;}await busy(e.currentTarget,()=>api(sector?`/api/sectors/${sector.id}`:'/api/sectors',{method:sector?'PUT':'POST',body:p}));m.close();toast('行业配色已保存');await ctx.refresh();}catch(err){showError(m.root,err);}};
  }

  async function importFile(existingName=null,file=null){
    ensureReal();try{
      toast('正在检查 Excel 和行业归属…');const payload=existingName?{existing_name:existingName}:{file_name:file.name,content_base64:await fileBase64(file)};
      const p=await api('/api/import/preview',{method:'POST',body:payload});
      const m=modal('导入预览',`${p.already_imported?'<div class="warning-note">这个文件已导入，程序将避免重复写入。</div>':''}${p.warnings.map(w=>`<div class="warning-note">${esc(w)}</div>`).join('')}<div class="preview-metrics"><div><strong>${p.record_count}</strong><span>实际流水记录</span></div><div><strong>${p.security_count}</strong><span>股票与其他证券</span></div><div><strong>${p.stock_count}</strong><span>A股股票</span></div></div><div class="section-intro">${esc(p.file_name)} · ${p.start} 至 ${p.end}<br>交易会导入流水，日收益需要另外填写。</div><div class="table-scroll"><table class="data-table"><thead><tr><th>日期</th><th>摘要</th><th>证券</th><th class="number">资金发生额</th></tr></thead><tbody>${p.sample.map(r=>`<tr><td>${r.date}</td><td>${esc(r.summary)}</td><td>${esc(r.name||'—')}</td><td class="number">${money(r.cash_change_cents,{sign:true})}</td></tr>`).join('')}</tbody></table></div>${p.unclassified.length?`<div class="soft-note">有 ${p.unclassified.length} 只股票待补行业，导入后可在“股票与行业”中设置。</div>`:''}${p.overlap_count?`<div class="warning-note">发现 ${p.overlap_count} 条疑似与已导入文件重叠。<label class="check-label"><input id="allow-overlap" type="checkbox">我已核实这些是应额外保留的流水，保留两份并继续导入。</label></div>`:''}${p.warnings.length?'<label class="check-label mt16"><input type="checkbox" id="ack-import">我已核对提示，按文件中的实际明细导入。</label>':''}<div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="import-cancel">取消</button><button class="btn btn-primary" id="import-commit" ${p.already_imported?'disabled':''}>确认导入 ${p.record_count} 条</button></div>`,{wide:true,subtitle:'先核对，再写入本地数据库'});
      $('#import-cancel',m.root).onclick=m.close;$('#import-commit',m.root).onclick=async e=>{try{if(p.warnings.length&&!$('#ack-import',m.root).checked)throw new Error('请先核对并勾选合计差异提示');if(p.overlap_count&&!$('#allow-overlap',m.root).checked)throw new Error('疑似重复的流水需要明确核实后再导入');const r=await busy(e.currentTarget,()=>api('/api/import/commit',{method:'POST',body:{token:p.preview_token,allow_overlap:$('#allow-overlap',m.root)?.checked||false}}));m.close();toast(`已导入 ${r.imported} 条流水，可以更新行情自动还原收益`);await ctx.refresh();}catch(err){showError(m.root,err);}};
    }catch(e){toast(e.message,'error');}
  }

  async function importDialog(){
    let files=[];try{files=await api('/api/import/available');}catch(e){toast(e.message,'error');}
    const m=modal('导入交易流水',`<p class="section-intro">支持普通资金流水明细 Excel。自动识别股票代码和大盘云图行业，原始字段完整保留。</p>${files.map((f,i)=>`<div class="available-file"><div class="file-info">${icon('folder')}<div><strong>${esc(f.name)}</strong><small>项目目录中的现有文件 · ${(f.size/1024).toFixed(1)} KB</small></div></div><button class="btn btn-sm btn-quiet" data-existing="${i}">预览</button></div>`).join('')}<label class="dropzone">${icon('upload')}<strong>选择其他 Excel 文件</strong><small>.xlsx · 最大 16 MB</small><input class="hidden" type="file" accept=".xlsx" id="import-file"></label>`);
    $$('[data-existing]',m.root).forEach(b=>b.onclick=()=>{const f=files[Number(b.dataset.existing)];m.close();importFile(f.name);});$('#import-file',m.root).onchange=e=>{const file=e.target.files[0];if(file){m.close();importFile(null,file);}};
  }

  async function backupNow(button=null){try{const action=()=>api('/api/backup',{method:'POST',body:{}});const result=button?await busy(button,action):await action();download(result.download_url);toast('已创建并下载完整数据库备份');if(ctx.state.page==='data')await ctx.refresh();}catch(e){toast(e.message,'error');}}

  async function restoreFile(file){
    try{const info=await api('/api/restore/preview',{method:'POST',body:{content_base64:await fileBase64(file)}});
      const m=modal('恢复备份前，请核对',`<div class="warning-note">恢复会用备份替换当前记录。程序会先自动备份当前数据库，便于找回。</div><div class="preview-metrics"><div><strong>${info.record_count}</strong><span>收益记录</span></div><div><strong>${info.ledger_count}</strong><span>交易流水</span></div><div><strong>${info.stock_count}</strong><span>证券</span></div></div><p class="section-intro">备份文件：${esc(file.name)}</p><label class="check-label"><input type="checkbox" id="restore-confirm">我确认使用这个备份恢复当前账户数据。</label><div class="form-error"></div><div class="modal-actions"><button class="btn btn-quiet" id="restore-cancel">取消</button><button class="btn btn-danger" id="restore-go">确认恢复</button></div>`);
      $('#restore-cancel',m.root).onclick=m.close;$('#restore-go',m.root).onclick=async e=>{try{if(!$('#restore-confirm',m.root).checked)throw new Error('请先勾选恢复确认');const result=await busy(e.currentTarget,()=>api('/api/restore/commit',{method:'POST',body:{token:info.preview_token,confirmed:true}}));m.close();toast('恢复完成，恢复前的数据也已自动备份');await ctx.refresh();}catch(err){showError(m.root,err);}};
    }catch(e){toast(e.message,'error');}
  }

  function deleteEntry(entry){confirmDialog('删除这条流水？','删除后会保留修改记录。收益记录独立保存，不会随交易流水删除。',async()=>{await api(`/api/ledger/${entry.id}`,{method:'DELETE',body:{}});toast('流水已删除');await ctx.refresh();},{danger:true,label:'删除流水'});}

  return {dayEditor,ledgerEditor,batchEditor,stockEditor,sectorEditor,importFile,importDialog,backupNow,restoreFile,deleteEntry};
}
