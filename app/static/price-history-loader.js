// Loading a chart requires the whole selected date range, not just held dates.
export async function loadPriceHistory(api,payload,{force=false,isCurrent=()=>true,onCached=()=>{},onSyncing=()=>{}}={}){
  const cached=await api('/api/stock-history?'+new URLSearchParams(payload));
  if(!isCurrent())return null;
  onCached(cached);
  if(!force&&!cached.needs_sync)return {data:cached};
  onSyncing();
  try{
    const data=await api('/api/stock-history/sync',{method:'POST',body:payload});
    return isCurrent()?{data}:null;
  }catch(error){
    return isCurrent()?{data:cached,warning:error.message}:null;
  }
}
