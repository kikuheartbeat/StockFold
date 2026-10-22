export const $=(selector,root=document)=>root.querySelector(selector);
export const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];
export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const money=(cents,{sign=false,empty='—'}={})=>cents==null?empty:(sign&&cents>0?'+':'')+(cents/100).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2});
export const tone=cents=>cents>0?'profit':cents<0?'loss':'neutral';
export const compact=cents=>cents==null?'—':Math.abs(cents)>=1000000?(cents/1000000).toFixed(2)+'万':money(cents);
export function parseMoney(value,nullable=false){
  const s=String(value??'').trim();if(!s&&nullable)return null;
  if(!/^-?\d+(\.\d{1,2})?$/.test(s))throw new Error('金额请输入最多两位小数，零收益请填写0');
  const negative=s.startsWith('-');const [whole,frac='']=s.replace('-','').split('.');
  const n=Number(whole)*100+Number(frac.padEnd(2,'0'));
  if(!Number.isSafeInteger(n)||Math.abs(n)>1e14)throw new Error('金额超出允许范围');return negative?-n:n;
}
const paths={
  grid:'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  pen:'m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15z',
  clock:'M12 8v5l3 2M21 12a9 9 0 1 1-3-6.7M21 3v6h-6',
  layers:'m3 7 9-5 9 5-9 5zm0 5 9 5 9-5M3 17l9 5 9-5',
  database:'M20 6c0 2-3.6 4-8 4S4 8 4 6s3.6-4 8-4 8 2 8 4zm0 0v12c0 2-3.6 4-8 4s-8-2-8-4V6m0 6c0 2 3.6 4 8 4s8-2 8-4',
  list:'M9 5h12M9 12h12M9 19h12M3 5h.1M3 12h.1M3 19h.1',
  plus:'M12 5v14M5 12h14',upload:'M12 16V3m-5 5 5-5 5 5M4 15v5h16v-5',
  down:'M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5',arrow:'M5 12h14m-5-5 5 5-5 5',
  chevron:'m9 5 7 7-7 7',close:'m6 6 12 12M6 18 18 6',search:'m21 21-5-5m2-6a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  wallet:'M3 5h16v4M3 5v15h18V9H3m12 4h6v4h-6z',trend:'m3 17 6-6 4 4 8-10m-6 0h6v6',
  calendar:'M4 5h16v16H4zM4 10h16M8 2v6m8-6v6',check:'m5 12 4 4L19 6',
  shield:'m12 2 8 3v7c0 5-8 10-8 10S4 17 4 12V5zm-4 10 3 3 5-6',
  info:'M12 11v6m0-10h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  spark:'m12 2 2.5 7.5L22 12l-7.5 2.5L12 22l-2.5-7.5L2 12l7.5-2.5z',
  eye:'M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12zm13 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0',
  folder:'M3 6h6l2 3h10v12H3z',trash:'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7',
  power:'M12 2v10m-6-7a9 9 0 1 0 12 0',menu:'M3 6h18M3 12h18M3 18h18',
};
export const icon=(name,cls='')=>`<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.grid}"/></svg>`;
export function toast(message,type='success'){
  const n=document.createElement('div');n.className=`toast ${type}`;n.innerHTML=icon(type==='error'?'info':'check')+`<span>${esc(message)}</span>`;
  $('#toast-stack').append(n);setTimeout(()=>{n.classList.add('out');setTimeout(()=>n.remove(),200);},4500);
}
export function modal(title,body,{wide=false,drawer=false,subtitle=''}={}){
  const root=$('#modal-root');const previous=document.activeElement;
  root.innerHTML=`<div class="modal-backdrop ${drawer?'drawer-backdrop':''}"><section class="modal ${wide?'wide':''} ${drawer?'drawer':''}" role="dialog" aria-modal="true" aria-label="${esc(title)}"><header class="modal-header"><div><h2>${esc(title)}</h2>${subtitle?`<p>${esc(subtitle)}</p>`:''}</div><button class="icon-btn modal-close" aria-label="关闭">${icon('close')}</button></header><div class="modal-content">${body}</div></section></div>`;
  const close=()=>{root.innerHTML='';document.removeEventListener('keydown',key);previous?.focus();};
  const key=e=>{if(e.key==='Escape')close();if(e.key==='Tab'){const nodes=$$('button,input,select,textarea,a[href]',root).filter(x=>!x.disabled);if(!nodes.length)return;const first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}};
  $('.modal-close',root).onclick=close;$('.modal-backdrop',root).onclick=e=>{if(e.target.classList.contains('modal-backdrop'))close();};document.addEventListener('keydown',key);
  setTimeout(()=>$('.modal-content input, .modal-content button, .modal-close',root)?.focus(),40);
  return {root,close};
}
export function confirmDialog(title,message,onConfirm,{danger=false,label='确认'}={}){
  const m=modal(title,`<p class="confirm-copy">${esc(message)}</p><div class="modal-actions"><button class="btn btn-quiet" id="confirm-cancel">取消</button><button class="btn ${danger?'btn-danger':'btn-primary'}" id="confirm-yes">${esc(label)}</button></div>`);
  $('#confirm-cancel',m.root).onclick=m.close;$('#confirm-yes',m.root).onclick=async e=>{e.currentTarget.disabled=true;try{await onConfirm();m.close();}catch(err){toast(err.message,'error');e.currentTarget.disabled=false;}};
}
export async function busy(button,action){const old=button.innerHTML;button.disabled=true;button.innerHTML='<span class="spinner"></span>处理中';try{return await action();}finally{button.disabled=false;button.innerHTML=old;}}
