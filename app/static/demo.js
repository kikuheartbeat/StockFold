const iso=d=>d.toISOString().slice(0,10);
export function makeDemo(today,level=2,start=null,end=null,sectors=[]){
  const finish=new Date(today+'T12:00:00Z'),begin=new Date(finish);begin.setUTCDate(begin.getUTCDate()-55);
  const configs=[
    {id:9001,code:'002281',name:'光迅科技',first_level:'通信',second_level:'通信设备',color:'#517AEC'},
    {id:9002,code:'002463',name:'沪电股份',first_level:'电子',second_level:'元件',color:'#184BD8'},
    {id:9003,code:'000831',name:'中国稀土',first_level:'有色金属',second_level:'小金属',color:'#9A763B'},
    {id:9004,code:'603893',name:'瑞芯微',first_level:'电子',second_level:'半导体',color:'#184BD8'},
    {id:9005,code:'002837',name:'英维克',first_level:'机械设备',second_level:'专用设备',color:'#F2DD87'},
  ];
  for(const stock of configs)stock.color=sectors.find(s=>s.level===1&&s.name===stock.first_level)?.color||stock.color;
  const allDates=[],allTotal=[],allAssets=[];const series=configs.map(c=>({...c,asset_type:'stock',has_data:true,has_holdings:true,points:[],period_pnl_cents:0,cumulative_pnl_cents:0}));
  let cumulative=0,assets=5000000,tradeDay=0,confirmed=0;
  for(let i=0;i<56;i++){
    const d=new Date(begin);d.setUTCDate(d.getUTCDate()+i);const day=iso(d),skip=[0,6].includes(d.getUTCDay());allDates.push(day);
    let daily=0;
    series.forEach((s,j)=>{
      const raw=skip?0:Math.round((Math.sin(tradeDay*.61+j*1.3)*(j===2?95:135)+Math.cos(tradeDay*.23+j)*60+(j===2?-14:21))*100);
      s.cumulative_pnl_cents+=raw;daily+=raw;s.points.push({date:day,value_cents:s.cumulative_pnl_cents,daily_cents:raw,gap_before:false,holding:true,status:skip?'skip':'confirmed'});
    });
    if(!skip){tradeDay++;confirmed++;}cumulative+=daily;
    const transfers=[];
    if(i===19)transfers.push({kind:'deposit',amount_cents:1200000,cash_change_cents:1200000,summary:'银行转证券'});
    if(i===41)transfers.push({kind:'withdraw',amount_cents:450000,cash_change_cents:-450000,summary:'证券转银行'});
    assets+=daily+transfers.reduce((s,t)=>s+t.cash_change_cents,0);
    const cash=Math.round(assets*(.22+.05*Math.sin(i*.18)));
    let allocated=0;const positions=configs.map((s,j)=>{
      const value=j===configs.length-1?assets-cash-allocated:Math.round((assets-cash)*(j+2)/20);allocated+=value;
      return {stock_id:s.id,code:s.code,name:s.name,color:s.color,quantity:100,market_value_cents:value};
    });
    const color=daily>0?'#D14343':daily<0?'#16845B':'#94A3B8';
    allTotal.push({date:day,value_cents:cumulative,recorded_cumulative_cents:cumulative,daily_cents:daily,recorded_daily_cents:daily,status:skip?'skip':'confirmed',gap_before:false,cumulative_complete:true,color});
    allAssets.push({date:day,total_assets_cents:assets,cash_cents:cash,holdings_cents:assets-cash,positions,daily_cents:daily,color,transfers,net_transfer_cents:transfers.reduce((s,t)=>s+t.cash_change_cents,0)});
  }
  const visible=allDates.filter(d=>(!start||d>=start)&&(!end||d<=end));
  const included=new Set(visible);const totals=allTotal.filter(p=>included.has(p.date)),asset=allAssets.filter(p=>included.has(p.date));
  for(const s of series){let running=0;s.points=s.points.filter(p=>included.has(p.date)).map(p=>({...p,value_cents:running+=p.daily_cents}));s.has_holdings=s.points.length>0;s.period_pnl_cents=running;}
  const groups=new Map();for(const s of series){const name=level===1?s.first_level:s.second_level;let g=groups.get(name);if(!g){g={id:'demo:'+name,name,parent_name:s.first_level,color:s.color,pnl_cents:0,stock_ids:[],stock_names:[]};groups.set(name,g);}g.pnl_cents+=s.period_pnl_cents;g.stock_ids.push(s.id);g.stock_names.push(s.name);}
  const last=asset.at(-1);
  return {demo:true,metadata:{record_start:iso(begin),start:visible[0]||iso(begin),end:visible.at(-1)||today,industry_level:level,today},
    dates:visible,total_series:totals,series,assets:asset,sectors:[...groups.values()].sort((a,b)=>b.pnl_cents-a.pnl_cents),
    summary:{recorded_cumulative_cents:totals.at(-1)?.value_cents||0,period_pnl_cents:totals.reduce((s,p)=>s+p.daily_cents,0),latest_daily_cents:totals.at(-1)?.daily_cents,other_pnl_cents:0,latest_assets_cents:last?.total_assets_cents,latest_cash_cents:last?.cash_cents,latest_asset_date:last?.date,stock_count:5,record_count:confirmed*5,ledger_count:0,import_count:0},
    coverage:{complete:true,missing_dates:[],missing_count:0,confirmed_count:totals.filter(p=>p.status==='confirmed').length,unclassified_count:0,has_returns:true},reconciliation:[]};
}
