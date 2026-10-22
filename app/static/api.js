let token='';
export function setToken(value){token=value;}
export async function api(path,options={}){
  const method=options.method||'GET';
  const headers={...(options.headers||{})};
  if(method!=='GET'){headers['Content-Type']='application/json';headers['X-StockFold-Token']=token;}
  const res=await fetch(path,{...options,method,headers,body:options.body===undefined?undefined:JSON.stringify(options.body)});
  const data=await res.json();
  if(!res.ok)throw new Error(data.error||'操作未完成，请重试');
  return data;
}
export function fileBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(new Error('文件读取失败'));r.readAsDataURL(file);});}
export function download(url){const a=document.createElement('a');a.href=url;a.download='';document.body.append(a);a.click();a.remove();}
