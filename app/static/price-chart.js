// Price geometry uses the portfolio's date axis; no independent zoom state.
export const heldOn=(date,intervals)=>intervals.some(s=>(s.start==null||s.start<=date)&&(s.end==null||date<=s.end));
export function priceSegments(points,intervals){
  const result=[];let previous=null;
  for(const point of points){
    if(!Number.isFinite(point.close)){if(!point.closed)previous=null;continue;}
    if(previous)result.push({from:previous,to:point,held:intervals.some(s=>(s.start==null||s.start<=previous.date)&&(s.end==null||point.date<=s.end))});
    previous=point;
  }
  return result;
}
export function priceIsolatedPoints(points,intervals){
  const connected=new Set(priceSegments(points,intervals).flatMap(s=>[s.from.date,s.to.date]));
  return points.filter(p=>Number.isFinite(p.close)&&!connected.has(p.date));
}
export function priceBoundaries(intervals,dates){
  const visible=new Set(dates),marks=new Map();
  for(const s of intervals)for(const [date,label] of [[s.start,'买入'],[s.end,'清仓']]){
    if(!visible.has(date))continue;
    if(!marks.has(date))marks.set(date,new Set());marks.get(date).add(label);
  }
  return [...marks].sort(([a],[b])=>a.localeCompare(b)).map(([date,labels])=>({date,label:[...labels].join(' / ')}));
}
export function holdingAreas(totals,intervals,profits=[],x,y,top){
  const areas=[];
  intervals.forEach((interval,index)=>{
    const pnl=profits[index];if(!Number.isFinite(pnl)||pnl===0)return;
    let run=[];
    const flush=()=>{
      if(run.length>1)areas.push({pnl_cents:pnl,points:[
        [run[0][0],top],[run.at(-1)[0],top],...run.slice().reverse()
      ]});
      run=[];
    };
    totals.forEach((p,i)=>{
      if(!heldOn(p.date,[interval])||!Number.isFinite(p.value_cents)){flush();return;}
      if(p.gap_before)flush();
      run.push([x(i),y(p.value_cents)]);
    });
    flush();
  });
  return areas;
}
