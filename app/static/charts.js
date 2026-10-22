import {esc,money,icon} from './ui.js';
const UP='#D14343',DOWN='#16845B',FLAT='#94A3B8',CASH='#DCE2ED';
const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
export function formatMoney(cents){return money(cents);}
export function holdingColorShares(positions=[]){
  if(!positions.length||positions.some(p=>!Number.isFinite(p.market_value_cents)||p.market_value_cents<0))return [{color:FLAT,share:1}];
  const held=positions.filter(p=>p.market_value_cents>0),total=held.reduce((n,p)=>n+p.market_value_cents,0);
  return total?held.map(p=>({...p,share:p.market_value_cents/total})):[{color:FLAT,share:1}];
}
export function makeLineSegments(points,assets=[]){
  const segments=[];
  for(let i=1;i<points.length;i++){
    const from=points[i-1],to=points[i];
    if(from.value_cents==null||to.value_cents==null||to.gap_before)continue;
    const colors=holdingColorShares(assets[i]?.positions);
    segments.push({from,to,color:colors[0].color,colors});
  }return segments;
}
export function assetParts(asset){
  if(asset.total_assets_cents==null||asset.cash_cents==null)return null;
  return {...asset,holdings_cents:asset.total_assets_cents-asset.cash_cents};
}
export function assetStack(asset){
  const a=assetParts(asset);if(!a)return null;
  const color=Number.isFinite(a.daily_cents)?a.daily_cents>0?UP:a.daily_cents<0?DOWN:FLAT:FLAT;
  return [{kind:'cash',color:CASH,name:'现金',value_cents:a.cash_cents},
    {kind:'holdings',color,name:'持仓市值',value_cents:a.holdings_cents}];
}
export function zoomWindow(view,factor,anchor,total){
  if(total<=1)return {start:0,end:total-1};
  const count=view.end-view.start+1,next=clamp(Math.round(count*factor),2,total),a=clamp(anchor,0,1);
  const start=clamp(Math.round(view.start+a*(count-1)-a*(next-1)),0,total-next);
  return {start,end:start+next-1};
}
export function panWindow(view,shift,total){
  if(total<=1)return {start:0,end:total-1};
  const count=view.end-view.start+1,start=clamp(view.start+Math.round(shift),0,total-count);
  return {start,end:start+count-1};
}
export function isolatedLinePoints(points){
  return points.filter((p,i)=>p.value_cents!=null&&
    (i===0||points[i-1].value_cents==null||p.gap_before)&&
    (i===points.length-1||points[i+1].value_cents==null||points[i+1].gap_before));
}
const NS='http://www.w3.org/2000/svg';let chartId=0;
function node(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,String(v));if(text!==undefined)n.textContent=text;return n;}
function add(svg,tag,attrs,text){const n=node(tag,attrs,text);svg.append(n);return n;}
function tickMoney(cents){if(Math.abs(cents)>=1e6)return (cents/1e6).toFixed(1)+'万';return (cents/100).toLocaleString('zh-CN',{maximumFractionDigits:0});}

export function renderCharts(container,dashboard,ui={}){
  const host=container.querySelector('#portfolio-chart');if(!host)return()=>{};
  const full=dashboard.dates,buttons={inside:container.querySelector('#chart-zoom-in'),outside:container.querySelector('#chart-zoom-out'),reset:container.querySelector('#chart-reset')};
  let view={start:0,end:full.length-1},geometry=null,drag=null,timer;
  const uid='portfolio-'+(++chartId);
  function render(){
    const dates=full.slice(view.start,view.end+1),totals=dashboard.total_series.slice(view.start,view.end+1),assets=dashboard.assets.slice(view.start,view.end+1);
    host.replaceChildren();
    const width=Math.max(host.clientWidth,340),height=380,left=64,right=68,top=34,bottom=height-38,plotWidth=width-left-right,count=dates.length;
    const svg=node('svg',{viewBox:`0 0 ${width} ${height}`,class:'chart-svg',role:'img','aria-label':'累计收益与账户资产构成合并图，支持滚轮缩放、拖动平移和双击复位'});host.append(svg);
    const defs=add(svg,'defs'),clip=add(defs,'clipPath',{id:uid+'-clip'});add(clip,'rect',{x:left,y:top,width:plotWidth,height:bottom-top});
    const known=totals.map(p=>p.value_cents).filter(v=>v!=null),baseMin=Math.min(0,...known),baseMax=Math.max(100,...known),padding=(baseMax-baseMin)*.1;
    const min=baseMin-padding,max=baseMax+padding,maxAsset=Math.max(100,...assets.map(a=>a.total_assets_cents||0))*1.08;
    const x=i=>left+(count<=1?.5:i/(count-1))*plotWidth,y=v=>top+(max-v)/(max-min)*(bottom-top),ay=v=>bottom-v/maxAsset*(bottom-top);
    for(let i=0;i<=4;i++){
      const ratio=i/4,gy=bottom-ratio*(bottom-top);
      add(svg,'line',{x1:left,y1:gy,x2:width-right,y2:gy,class:'axis-grid'});
      add(svg,'text',{x:left-10,y:gy+3,'text-anchor':'end'},tickMoney(min+ratio*(max-min)));
      add(svg,'text',{x:width-right+10,y:gy+3,'text-anchor':'start',class:'asset-axis-label'},tickMoney(ratio*maxAsset));
    }
    add(svg,'text',{x:left,y:15,class:'axis-title'},'累计收益 / 元');add(svg,'text',{x:width-right,y:15,'text-anchor':'end',class:'axis-title'},'总资产 / 元');
    if(min<=0&&max>=0)add(svg,'line',{x1:left,y1:y(0),x2:width-right,y2:y(0),class:'zero-grid'});
    for(const i of new Set([0,Math.floor((count-1)/4),Math.floor((count-1)/2),Math.floor((count-1)*3/4),count-1]))if(dates[i])add(svg,'text',{x:x(i),y:height-12,'text-anchor':'middle',class:'date-label'},dates[i].slice(5).replace('-','/'));
    const plot=add(svg,'g',{'clip-path':`url(#${uid}-clip)`}),barWidth=Math.min(24,Math.max(1,plotWidth/Math.max(count,1)*.58));
    assets.forEach((a,i)=>{
      const parts=assetStack(a);let accumulated=0;
      for(const part of parts||[]){
        if(part.value_cents<=0)continue;
        const h=part.value_cents/maxAsset*(bottom-top);
        add(plot,'rect',{x:x(i)-barWidth/2,y:ay(accumulated+part.value_cents),width:barWidth,height:h,fill:part.color,opacity:part.kind==='holdings' ? .45 : .65,class:'asset-bar','data-part':part.kind,'data-date':a.date,'data-value-cents':part.value_cents});
        accumulated+=part.value_cents;
      }
      for(const [j,tr]of (a.transfers||[]).entries()){
        const gy=parts?ay(a.total_assets_cents)+Math.max(5,(bottom-ay(a.total_assets_cents))*(.2+j*.13)):bottom-8-j*8;
        add(plot,'line',{x1:x(i)-barWidth*.7,y1:gy,x2:x(i)+barWidth*.7,y2:gy,class:'transfer-mark'});
        add(plot,'circle',{cx:x(i),cy:gy,r:2,fill:'#fff',stroke:'#998cb7','stroke-width':1});
      }
    });
    let paintIndex=0;
    function paint(colors,x1,y1,x2,y2){
      if(colors.length===1)return colors[0].color;
      const id=uid+'-paint-'+(++paintIndex),gradient=add(defs,'linearGradient',{id,gradientUnits:'userSpaceOnUse',x1,y1,x2,y2});let offset=0;
      for(const c of colors){add(gradient,'stop',{offset:offset*100+'%','stop-color':c.color});offset+=c.share;add(gradient,'stop',{offset:Math.min(1,offset)*100+'%','stop-color':c.color});}
      return `url(#${id})`;
    }
    const indexMap=new Map(dates.map((d,i)=>[d,i]));
    for(const segment of makeLineSegments(totals,assets)){
      const x1=x(indexMap.get(segment.from.date)),y1=y(segment.from.value_cents),x2=x(indexMap.get(segment.to.date)),y2=y(segment.to.value_cents);
      add(plot,'path',{d:`M${x1},${y1} L${x2},${y2}`,fill:'none',stroke:paint(segment.colors,x1,y1,x2,y2),'stroke-width':3,'stroke-linecap':'round',class:'total-path','data-date':segment.to.date});
    }
    for(const p of isolatedLinePoints(totals)){
      const i=indexMap.get(p.date),px=x(i),py=y(p.value_cents);add(plot,'circle',{cx:px,cy:py,r:3.5,fill:paint(holdingColorShares(assets[i]?.positions),px-3.5,py,px+3.5,py),class:'total-point'});
    }
    const hover=add(svg,'line',{x1:left,y1:top,x2:left,y2:bottom,class:'hover-line',visibility:'hidden'}),tip=document.createElement('div');tip.className='chart-tooltip hidden';host.append(tip);
    geometry={svg,tip,hover,width,left,right,top,bottom,x,dates,totals,assets};
    const range=container.querySelector('#chart-window');if(range)range.textContent=count?`${dates[0]} — ${dates.at(-1)} · ${count}天`:'暂无日期';
    if(buttons.inside)buttons.inside.disabled=count<=2;if(buttons.outside)buttons.outside.disabled=count>=full.length;if(buttons.reset)buttons.reset.disabled=count>=full.length;
    const legend=container.querySelector('#holding-legend');
    if(legend){
      const held=new Map();for(const a of assets)for(const p of a.positions||[])held.set(p.stock_id,p);
      const list=[...held.values()];
      legend.innerHTML=`<span class="legend-chip"><i class="legend-solid"></i>总收益折线</span><span class="legend-chip"><i class="legend-dot" style="background:${CASH}"></i>现金</span><span class="legend-chip"><i class="legend-dot" style="background:${UP}"></i>资产柱 · 涨</span><span class="legend-chip"><i class="legend-dot" style="background:${DOWN}"></i>资产柱 · 跌</span><span class="legend-chip"><i class="legend-dot" style="background:${FLAT}"></i>持平 / 待确认</span>${list.map(p=>`<span class="legend-chip" title="${esc(p.code)}"><i class="legend-dot" style="background:${esc(p.color)}"></i>${esc(p.name)}</span>`).join('')}`;
    }
    if(!dashboard.coverage.has_returns&&!assets.some(a=>a.total_assets_cents!=null)){
      const empty=document.createElement('div');empty.className='chart-empty';empty.innerHTML=`<div class="empty-glyph">${icon('trend')}</div><h3>让第一笔收益，成为曲线的起点</h3><p>导入交易并更新行情后，在同一张图中回看收益和资产。</p><button class="btn btn-sm btn-quiet">更新行情 ${icon('arrow')}</button>`;empty.querySelector('button').onclick=()=>ui.onEmpty?.();host.append(empty);
    }
  }
  function mouse(event){
    const g=geometry,rect=g.svg.getBoundingClientRect();return {x:(event.clientX-rect.left)/rect.width*g.width,rect};
  }
  function onMove(event){
    const g=geometry;if(!g||!g.dates.length)return;
    if(drag){const rect=g.svg.getBoundingClientRect(),delta=(event.clientX-drag.x)/rect.width*g.width;view=panWindow(drag.view,-delta/(g.width-g.left-g.right)*(drag.view.end-drag.view.start),full.length);render();return;}
    const px=mouse(event).x,index=clamp(Math.round((px-g.left)/(g.width-g.left-g.right)*Math.max(g.dates.length-1,1)),0,g.dates.length-1),total=g.totals[index],asset=g.assets[index],positions=asset?.positions||[];
    g.hover.setAttribute('x1',g.x(index));g.hover.setAttribute('x2',g.x(index));g.hover.setAttribute('visibility','visible');
    let html=`<strong>${esc(g.dates[index])}</strong><div class="tooltip-row"><span>累计收益</span><b>¥ ${money(total?.value_cents,{sign:true})}</b></div><div class="tooltip-row"><span>当日盈亏</span><b>${money(total?.daily_cents,{sign:true})}</b></div><div class="tooltip-rule"></div><div class="tooltip-row"><span>账户总资产</span><b>¥ ${money(asset?.total_assets_cents)}</b></div><div class="tooltip-row"><span>现金余额</span><b>¥ ${money(asset?.cash_cents)}</b></div><div class="tooltip-row"><span>持仓市值</span><b>¥ ${money(asset?.holdings_cents)}</b></div>`;
    const colors=holdingColorShares(positions),known=positions.every(p=>p.market_value_cents!=null),shares=new Map(colors.map(c=>[c.stock_id,c.share]));
    if(positions.length){html+='<div class="tooltip-rule"></div>';for(const p of positions)html+=`<div class="tooltip-row"><span><i class="legend-dot" style="background:${esc(p.color)}"></i> ${esc(p.name)}</span><b>${money(p.market_value_cents)}${known?` · ${((shares.get(p.stock_id)||0)*100).toFixed(1)}%`:''}</b></div>`;if(!known)html+='<div class="tooltip-path">持仓或行情待核对，线段暂用中性色。</div>';}
    else html+='<div class="tooltip-path">当日无收盘持仓，线段使用中性色。</div>';
    for(const tr of asset?.transfers||[])html+=`<div class="tooltip-row"><span>${tr.kind==='deposit'?'银证转入':'银证转出'}</span><b>${tr.kind==='deposit'?'+':'−'}${money(tr.amount_cents)}</b></div>`;
    if(total?.value_cents==null)html+='<div class="tooltip-path">当日收益未完整确认，保留缺口。</div>';else if(!total.cumulative_complete)html+='<div class="tooltip-path">历史尚有缺口，累计值仅汇总已录金额。</div>';
    g.tip.innerHTML=html;g.tip.classList.remove('hidden');const box=host.getBoundingClientRect();
    g.tip.style.left=clamp(event.clientX-box.left+15,0,Math.max(0,host.clientWidth-g.tip.offsetWidth-6))+'px';g.tip.style.top=clamp(event.clientY-box.top-g.tip.offsetHeight/2,8,Math.max(8,host.clientHeight-g.tip.offsetHeight-8))+'px';
  }
  function reset(){view={start:0,end:full.length-1};render();}
  function onWheel(event){
    if(full.length<2||!geometry)return;event.preventDefault();
    const px=mouse(event).x,anchor=clamp((px-geometry.left)/(geometry.width-geometry.left-geometry.right),0,1),delta=event.deltaY*(event.deltaMode===1?16:event.deltaMode===2?host.clientHeight:1);
    view=zoomWindow(view,Math.exp(clamp(delta,-500,500)*.0025),anchor,full.length);render();
  }
  function onDown(event){if(event.button!==0||event.target.closest('button')||full.length<2)return;drag={x:event.clientX,view:{...view}};host.setPointerCapture?.(event.pointerId);host.classList.add('dragging');event.preventDefault();}
  function onUp(event){drag=null;host.classList.remove('dragging');if(host.hasPointerCapture?.(event.pointerId))host.releasePointerCapture(event.pointerId);}
  function onLeave(){if(!drag&&geometry){geometry.hover.setAttribute('visibility','hidden');geometry.tip.classList.add('hidden');}}
  function onDouble(event){event.preventDefault();reset();}
  host.addEventListener('wheel',onWheel,{passive:false});host.addEventListener('pointermove',onMove);host.addEventListener('pointerdown',onDown);host.addEventListener('pointerup',onUp);host.addEventListener('pointercancel',onUp);host.addEventListener('pointerleave',onLeave);host.addEventListener('dblclick',onDouble);
  if(buttons.inside)buttons.inside.onclick=()=>{view=zoomWindow(view,.65,.5,full.length);render();};if(buttons.outside)buttons.outside.onclick=()=>{view=zoomWindow(view,1/.65,.5,full.length);render();};if(buttons.reset)buttons.reset.onclick=reset;
  render();const observer=new ResizeObserver(()=>{clearTimeout(timer);timer=setTimeout(render,120);});observer.observe(host);
  return()=>{observer.disconnect();clearTimeout(timer);host.removeEventListener('wheel',onWheel);host.removeEventListener('pointermove',onMove);host.removeEventListener('pointerdown',onDown);host.removeEventListener('pointerup',onUp);host.removeEventListener('pointercancel',onUp);host.removeEventListener('pointerleave',onLeave);host.removeEventListener('dblclick',onDouble);for(const button of Object.values(buttons))if(button)button.onclick=null;};
}
