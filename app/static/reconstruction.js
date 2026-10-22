import {api} from './api.js';
import {$,$$,esc,money,parseMoney,icon,toast,modal,busy} from './ui.js';

export function createReconstruction(ctx){
  const state=ctx.state;let timer=null;
  const stop=()=>{clearTimeout(timer);timer=null;};
  function render(){
    const meta=state.autoMeta,opening=meta.opening;
    return `<section class="auto-hero card"><div class="auto-intro"><span class="auto-eyebrow">${icon('spark')}交易流水 × 历史收盘价</span><h2>让交易，自动长成收益曲线</h2><p>自动识别持仓，下载股票与 ETF 的不复权收盘价，还原收益和账户资产。你只需要核对例外。</p><div class="auto-steps"><span><i>1</i>读取已录交易</span><b>→</b><span><i>2</i>同步历史收盘价</span><b>→</b><span><i>3</i>核对后保存</span></div></div><div class="auto-cache"><strong>${Number(meta.cached_prices).toLocaleString()}</strong><span>条行情已缓存在本机</span><small>${opening.positions.length} 只证券 · 流水截至 ${esc(opening.ledger_end||'尚未导入')}</small></div></section>
      <section class="card auto-controls"><div class="auto-range"><div class="field"><label for="auto-start">还原开始日期</label><input type="date" id="auto-start" value="${esc(state.autoStart||meta.record_start)}"></div><span>—</span><div class="field"><label for="auto-end">还原结束日期</label><input type="date" id="auto-end" max="${meta.last_closed_date}" value="${esc(state.autoEnd||meta.default_end)}"></div><button class="btn btn-primary" id="auto-run" ${opening.positions.length?'':'disabled'}>${icon('spark')}获取行情并计算</button></div><div class="auto-options"><label class="check-label"><input type="checkbox" id="auto-force">重新获取已缓存行情（手工校准价格保留）</label><span>当日16:30后可更新收盘数据</span></div><div class="auto-tools"><button class="btn btn-quiet btn-sm" id="auto-opening">${icon('wallet')}核对期初持仓</button><button class="btn btn-quiet btn-sm" id="auto-price">${icon('pen')}校准收盘价</button><button class="btn btn-quiet btn-sm" id="auto-manual">手工批量补录</button></div>${!opening.positions.length?'<div class="soft-note">请先导入交易流水，或在交易流水页记录买卖，再使用自动还原。</div>':''}<p class="auto-caption">现金按已录流水结转，以原始资金余额核对；未记录的新交易不会自动出现在账户中。原有手工记录按日期保护。</p></section>
      <div id="auto-result" aria-live="polite"></div>
      <details class="card auto-help"><summary>收益与资产是怎样算出来的？</summary><p>个股收益 = 当天持仓市值 − 上天持仓市值 ＋ 卖出净收款 − 买入总支出 ＋ 相关红利及扣税。总资产 = 现金 ＋ 全部持仓市值。银证转入转出不算收益；未知资金事项与余额差额会单独提示，不会自动当作盈利。</p><p>行情成功后会留在本机。缺少价格时保留缺口，不用零替代。自动生成日期可以重新计算；手工编辑某一天后，该日期会受到保护。</p></details>`;
  }
  function bind(){
    stop();$('#auto-run').onclick=start;$('#auto-opening').onclick=openingDialog;$('#auto-price').onclick=priceDialog;
    $('#auto-manual').onclick=()=>ctx.editors.batchEditor();
    state.autoJob=state.autoMeta.last_job??null;paint();
    if(state.autoJob?.state==='running')schedule();
    return stop;
  }
  async function start(event){
    try{
      state.demo=false;state.autoStart=$('#auto-start').value;state.autoEnd=$('#auto-end').value;
      if(!state.autoStart||!state.autoEnd||state.autoStart>state.autoEnd)throw new Error('请检查起止日期');
      const job=await busy(event.currentTarget,()=>api('/api/reconstruction/start',{method:'POST',body:{start:state.autoStart,end:state.autoEnd,force:$('#auto-force').checked}}));
      state.autoJob=job;paint();schedule();
    }catch(e){toast(e.message,'error');}
  }
  function schedule(){stop();timer=setTimeout(poll,1100);}
  async function poll(){
    if(state.page!=='history'||!$('#auto-result'))return;
    try{state.autoJob=await api('/api/reconstruction/jobs/'+state.autoJob.id);paint();if(state.autoJob.state==='running')schedule();}
    catch(e){stop();state.autoJob={...state.autoJob,state:'error',stage:'连接中断，可重新计算或重新进入此页恢复任务',error:e.message};paint();toast(e.message,'error');}
  }
  function paint(){
    const target=$('#auto-result');if(!target)return;
    const job=state.autoJob,run=$('#auto-run');if(run)run.disabled=job?.state==='running';
    if(!job){target.innerHTML=`<section class="auto-welcome">${icon('trend')}<h3>把每天的计算，交给程序</h3><p>选择日期后开始。第一次需要下载历史行情，再次使用会复用本地缓存。</p></section>`;return;}
    const percentage=Math.round(job.completed/Math.max(job.total,1)*100);
    let html=`<section class="card auto-progress"><div><h3>${job.state==='running'?'<span class="spinner"></span> ':''}${esc(job.stage)}</h3><span>${job.completed} / ${job.total} 只证券与日历 · ${percentage}%</span></div><div class="progress-bar"><span style="width:${percentage}%"></span></div>${job.state==='error'?`<p class="error-note">${esc(job.error)}</p>`:''}${job.errors?.length?`<details class="auto-errors"><summary>${job.errors.length}只证券获取失败，可重试或校准价格</summary>${job.errors.map(e=>`<p>${esc(e.code)} ${esc(e.name)}：${esc(e.message)}</p>`).join('')}</details>`:''}</section>`;
    if(job.state==='ready'){
      const p=job.preview,s=p.summary;
      html+=`<section class="card auto-preview"><div class="card-header"><div><h2>还原结果，先看一眼</h2><p class="card-subtitle">${p.start} 至 ${p.end} · 计算结果尚未写入收益和资产</p></div><span class="badge ${s.complete_days===s.days?'confirmed':'draft'}">${s.complete_days===s.days?'价格数据完整':'部分日期待核对'}</span></div><div class="auto-metrics"><div><strong>${s.complete_days}<small> / ${s.days}天</small></strong><span>收益可完整还原</span></div><div><strong>${s.return_rows.toLocaleString()}</strong><span>个股日收益记录</span></div><div><strong>${s.asset_days}</strong><span>可生成资产快照的日期</span></div><div><strong>${s.protected_days}</strong><span>手工日期将原样保留</span></div></div>
      ${s.issue_count?`<div class="warning-note">发现 ${s.issue_count} 项需核对提示，其中 ${s.missing_prices} 项涉及缺少价格。缺价的日收益保留缺口，余额差额不计作盈利。</div>`:'<div class="soft-note">计算未发现缺价或余额异常。保存后可在投资总览查看曲线。</div>'}
      <details class="auto-issues" ${s.issue_count?'open':''}><summary>核对明细（${s.issue_count}项）</summary><div class="table-scroll"><table class="data-table"><thead><tr><th>日期</th><th>证券 / 事项</th><th>提示</th><th></th></tr></thead><tbody>${p.issues.slice(0,100).map(i=>`<tr><td class="nowrap">${esc(i.date)}</td><td>${esc(i.stock_name||i.summary||'资金核对')}</td><td>${esc(i.message)}${i.difference_cents!=null?` · 差额 ${money(i.difference_cents,{sign:true})}元`:''}</td><td>${i.type==='missing_price'?`<button class="btn-text" data-fix-price="${i.stock_id}" data-price-day="${esc(i.price_date)}">补充价格</button>`:''}</td></tr>`).join('')||'<tr><td colspan="4" class="table-empty">没有待核对提示。</td></tr>'}</tbody></table></div>${s.issue_count>100?'<p class="inline-message">显示前100项。先补齐价格或修正流水，再次计算会刷新提示。</p>':''}</details>
      <details class="auto-issues"><summary>查看最近日期的计算结果</summary><div class="table-scroll"><table class="data-table"><thead><tr><th>日期</th><th>当日收益</th><th>现金</th><th>持仓市值</th><th>总资产</th><th>状态</th></tr></thead><tbody>${p.days.slice(-20).reverse().map(d=>`<tr><td class="nowrap">${d.date}</td><td>${d.complete?money(d.pnl_cents,{sign:true}):'待补齐'}</td><td>${money(d.cash_cents)}</td><td>${money(d.holdings_cents)}</td><td>${money(d.total_assets_cents)}</td><td>${d.protected?'保留手工记录':d.complete?'可保存':'保留缺口'}</td></tr>`).join('')}</tbody></table></div></details>
      <div class="auto-save"><label class="check-label"><input type="checkbox" id="auto-confirm">我已核对提示，保存计算结果；已有手工日期保持原样。保存前自动备份。</label><button class="btn btn-primary" id="auto-apply" disabled>${icon('check')}保存并更新图表</button></div></section>`;
    }
    target.innerHTML=html;
    if($('#auto-confirm')){$('#auto-confirm').onchange=e=>$('#auto-apply').disabled=!e.target.checked;$('#auto-apply').onclick=apply;}
    $$('[data-fix-price]').forEach(button=>button.onclick=()=>priceDialog(Number(button.dataset.fixPrice),button.dataset.priceDay));
  }
  async function apply(event){
    try{
      const result=await busy(event.currentTarget,()=>api('/api/reconstruction/apply',{method:'POST',body:{token:state.autoJob.preview.preview_token,confirmed:true}}));
      stop();state.autoJob=null;state.autoMeta.last_job=null;state.start=state.autoStart;state.end=state.autoEnd;state.range=-1;
      toast(`已保存${result.saved_days}天、${result.saved_rows}条收益，保留${result.protected_days}个手工日期，更新前已备份`);
      await ctx.navigate('overview');
    }catch(e){toast(e.message,'error');}
  }
  async function openingDialog(){
    try{
      const meta=await api('/api/reconstruction/meta'),opening=meta.opening;
      const m=modal('核对流水起点的持仓与现金',`<p class="section-intro">以下是整份流水首笔交易前的持仓，不是所选还原区间的持仓。区间之前的交易会自动结转。来源为“首笔证券余额反推”的数量已有流水依据，可直接核对。</p><div class="field"><label for="opening-cash">流水起点现金（元） · ${esc(opening.cash_source)}</label><input id="opening-cash" inputmode="decimal" value="${opening.cash_cents==null?'':(opening.cash_cents/100).toFixed(2)}" placeholder="没有余额信息时填写；留空则尝试从流水反推"></div><div class="table-scroll mt16"><table class="data-table"><thead><tr><th>证券</th><th>首笔交易前数量</th><th>依据</th></tr></thead><tbody>${opening.positions.map(s=>`<tr><td>${esc(s.name)}<small class="code">${esc(s.code)}</small></td><td><input class="opening-qty" data-opening-id="${s.stock_id}" type="number" min="0" step="1" value="${s.quantity}" aria-label="${esc(s.name)}期初数量"></td><td>${esc(s.source)}</td></tr>`).join('')}</tbody></table></div><div class="form-error"></div><div class="modal-actions"><button class="btn btn-primary" id="save-opening">保存期初信息</button></div>`,{wide:true});
      $('#save-opening',m.root).onclick=async event=>{try{
        const positions=$$('[data-opening-id]',m.root).map(n=>({stock_id:Number(n.dataset.openingId),quantity:Number(n.value)}));
        if(positions.some(s=>!Number.isSafeInteger(s.quantity)||s.quantity<0))throw new Error('数量必须为非负整数');
        await busy(event.currentTarget,()=>api('/api/reconstruction/opening',{method:'PUT',body:{positions,cash_cents:parseMoney($('#opening-cash',m.root).value,true)}}));
        m.close();state.autoJob=null;toast('期初信息已保存，请重新计算');await ctx.refresh();
      }catch(e){$('.form-error',m.root).textContent=e.message;}};
    }catch(e){toast(e.message,'error');}
  }
  function priceDialog(stockId=null,day=null){
    const m=modal('校准某一天的收盘价',`<p class="section-intro">请填写当日不复权收盘价。手工校准会留在本机，重新下载行情也不会覆盖它；保存后重新计算即可。</p><div class="form-grid"><div class="field"><label for="price-stock">股票 / ETF</label><select id="price-stock">${state.stocks.map(s=>`<option value="${s.id}" ${s.id===stockId?'selected':''}>${esc(s.code)} · ${esc(s.name)}</option>`).join('')}</select></div><div class="field"><label for="price-date">日期</label><input type="date" id="price-date" max="${state.autoMeta.last_closed_date}" value="${esc(day||$('#auto-end')?.value||state.autoMeta.default_end)}"></div><div class="field"><label for="price-close">不复权收盘价（元）</label><input id="price-close" inputmode="decimal" placeholder="例如 10.235"></div></div><div class="form-error"></div><div class="modal-actions"><button class="btn btn-primary" id="save-price">保存价格</button></div>`);
    $('#save-price',m.root).onclick=async event=>{try{
      await busy(event.currentTarget,()=>api('/api/reconstruction/price',{method:'PUT',body:{stock_id:Number($('#price-stock',m.root).value),date:$('#price-date',m.root).value,close_decimal:$('#price-close',m.root).value}}));
      m.close();state.autoJob=null;toast('收盘价已保存，请重新计算');await ctx.refresh();
    }catch(e){$('.form-error',m.root).textContent=e.message;}};
  }
  return {render,bind,stop};
}
