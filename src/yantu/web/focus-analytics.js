function focusAnalyticsDuration(seconds){
  const minutes=Math.round(Number(seconds||0)/60);
  return minutes>=60?`${Math.floor(minutes/60)} 小时 ${minutes%60} 分`:`${minutes} 分`;
}

function focusAnalyticsTime(value){
  return new Date(value).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false});
}

let focusAnalyticsRequest=0;
async function loadFocusAnalytics(renderNow=true){
  const request=++focusAnalyticsRequest;
  const end=state.focusAnalyticsRange==='custom'?state.focusAnalyticsEnd:today();
  const start=state.focusAnalyticsRange==='custom'?state.focusAnalyticsStart:
    state.focusAnalyticsRange==='all'?'1970-01-01':iso(addDays(new Date(),1-Number(state.focusAnalyticsRange)));
  if(!start||!end)throw new Error('请选择开始和结束日期');
  const data=await api(`/api/focus/analytics?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`);
  if(request!==focusAnalyticsRequest)return;
  state.focusAnalytics=data.analytics;
  if(renderNow&&state.view==='focus_analytics')render();
}

function focusAnalyticsBreakdown(title,items,label){
  const shown=items.filter(item=>item.seconds>0).slice(0,10);
  const max=shown[0]?.seconds||1;
  return `<section class="focus-analysis-panel"><h2>${title}</h2>${shown.length?
    shown.map(item=>`<div class="focus-analysis-row"><span title="${esc(item[label])}">${esc(item[label])}</span><div class="focus-analysis-track"><i style="width:${Math.max(2,item.seconds/max*100)}%"></i></div><b>${focusAnalyticsDuration(item.seconds)}</b></div>`).join(''):
    '<p class="focus-analysis-muted">这段时间没有留档的专注。</p>'}</section>`;
}

function renderFocusAnalytics(){
  const data=state.focusAnalytics;
  const ranges=[['7','近 7 天'],['28','近 28 天'],['90','近 90 天'],['all','全部历史'],['custom','自选日期']];
  const chooser=`<div class="focus-analysis-controls"><div class="focus-analysis-ranges">${ranges.map(([value,label])=>`<button type="button" data-focus-range="${value}" class="${state.focusAnalyticsRange===value?'active':''}">${label}</button>`).join('')}</div>${state.focusAnalyticsRange==='custom'?`<form id="focus-analysis-dates"><label>开始 <input type="date" id="focus-analysis-start" value="${esc(state.focusAnalyticsStart||iso(addDays(new Date(),-27)))}" required></label><label>结束 <input type="date" id="focus-analysis-end" value="${esc(state.focusAnalyticsEnd||today())}" max="${today()}" required></label><button type="submit" class="secondary-btn">查看</button></form>`:''}<button type="button" class="secondary-btn" id="focus-analysis-refresh">刷新</button></div>`;
  if(!data)return `<div class="focus-analysis"><p class="focus-analysis-intro">回看已经结束并留档的专注时间。</p>${chooser}<div class="empty"><strong>正在读取专注记录</strong>请稍候或点击刷新。</div></div>`;
  const s=data.summary;
  const attention=data.attention;
  const attentionRate=attention.sampled_seconds?Math.round(attention.active_seconds/attention.sampled_seconds*100):null;
  const daily=data.daily;
  let latest=daily.slice(-60);
  if(['7','28','90'].includes(state.focusAnalyticsRange)){
    const saved=new Map(daily.map(item=>[item.date,item]));
    latest=[];
    for(let day=parseDate(data.start),end=parseDate(data.end);day<=end;day=addDays(day,1))latest.push(saved.get(iso(day))||{date:iso(day),seconds:0,sessions:0});
  }
  const maxDay=Math.max(1,...latest.map(item=>item.seconds));
  const dayBars=latest.length?latest.map(item=>`<div class="focus-analysis-day" title="${esc(item.date)} · ${focusAnalyticsDuration(item.seconds)} · ${item.sessions} 次"><div>${item.seconds?`<i style="height:${Math.max(3,item.seconds/maxDay*100)}%"></i>`:''}</div><small>${esc(item.date.slice(5))}</small></div>`).join(''):'<p class="focus-analysis-muted">这个范围内没有留档记录。</p>';
  const hourGroups=[0,4,8,12,16,20].map(hour=>({name:`${String(hour).padStart(2,'0')}:00–${String(hour+4).padStart(2,'0')}:00`,seconds:data.by_hour.filter(item=>item.hour>=hour&&item.hour<hour+4).reduce((sum,item)=>sum+item.seconds,0)}));
  const weekday=['周一','周二','周三','周四','周五','周六','周日'];
  const weekdays=data.by_weekday.map(item=>({name:weekday[item.weekday],seconds:item.seconds})).sort((a,b)=>b.seconds-a.seconds);
  return `<div class="focus-analysis"><p class="focus-analysis-intro">回看已经结束并留档的专注时间。${esc(data.start)} 至 ${esc(data.end)}</p>${chooser}
    <div class="focus-analysis-cards">
      <article><small>累计专注</small><strong>${focusAnalyticsDuration(s.seconds)}</strong><span>${s.session_count} 次留档 · ${s.partial_sessions} 次提前结束并记录</span></article>
      <article><small>活跃天数</small><strong>${s.active_days} 天</strong><span>最长连续 ${s.longest_streak_days} 天</span></article>
      <article><small>平均每次</small><strong>${focusAnalyticsDuration(s.average_seconds)}</strong><span>最长一次 ${focusAnalyticsDuration(s.longest_seconds)}</span></article>
      <article><small>暂停次数</small><strong>${s.pause_count} 次</strong><span>番茄 ${data.by_mode.find(item=>item.mode==='pomodoro')?focusAnalyticsDuration(data.by_mode.find(item=>item.mode==='pomodoro').seconds):'0 分'}</span></article>
    </div>
    <section class="focus-analysis-panel"><div class="focus-analysis-heading"><h2>日期趋势</h2><span>按结束日期归档 · ${['7','28','90'].includes(state.focusAnalyticsRange)?`显示 ${latest.length} 天`:`显示最近 ${latest.length} 个有记录的日期`}</span></div><div class="focus-analysis-day-scroll"><div class="focus-analysis-day-grid">${dayBars}</div></div></section>
    <div class="focus-analysis-columns">${focusAnalyticsBreakdown('任务',data.by_task,'name')}${focusAnalyticsBreakdown('领域',data.by_domain.map(item=>({...item,domain:DOMAINS[item.domain]||item.domain})),'domain')}${focusAnalyticsBreakdown('项目',data.by_project,'name')}${focusAnalyticsBreakdown('计时方式',data.by_mode.map(item=>({...item,mode:item.mode==='free'?'自由计时':'番茄钟'})),'mode')}${focusAnalyticsBreakdown('星期分布',weekdays,'name')}${focusAnalyticsBreakdown('开始时段',hourGroups,'name')}</div>
    <section class="focus-analysis-panel"><div class="focus-analysis-heading"><h2>应用监测</h2><span>仅使用有监测样本的留档会话</span></div>${attentionRate===null?'<p class="focus-analysis-muted">这段时间没有可用于分析的应用监测样本。</p>':`<div class="focus-analysis-attention"><strong>${attentionRate}%</strong><span>监测样本中的活跃占比 · ${attention.sessions} 次会话</span><span>活跃 ${focusAnalyticsDuration(attention.active_seconds)} · 空闲 ${focusAnalyticsDuration(attention.idle_seconds)} · 分心 ${focusAnalyticsDuration(attention.distraction_seconds)} · 切换 ${attention.switch_count} 次</span></div>`}</section>
    <section class="focus-analysis-panel"><div class="focus-analysis-heading"><h2>留档记录</h2><span>最近 ${data.recent_sessions.length} / ${data.recent_sessions_total} 条</span></div><div class="focus-analysis-session-list">${data.recent_sessions.length?data.recent_sessions.map(item=>`<article><time>${esc(item.archive_date)} ${esc(focusAnalyticsTime(item.ended_at))}</time><div><strong>${esc(item.task_title)}</strong><small>${esc(item.project_name)} · ${esc(DOMAINS[item.task_domain]||item.task_domain)} · ${item.mode==='free'?'自由计时':'番茄钟'}${item.status==='cancelled'?' · 提前结束并记录':''}</small></div><b>${focusAnalyticsDuration(item.elapsed_seconds)}</b></article>`).join(''):'<p class="focus-analysis-muted">这个范围内没有留档记录。</p>'}</div></section>
    <p class="focus-analysis-footnote">${esc(data.basis)}。应用监测占比仅反映采集到的样本，不等同于全部专注时间。</p>
  </div>`;
}

function bindFocusAnalytics(){
  document.querySelectorAll('[data-focus-range]').forEach(button=>button.onclick=async()=>{
    state.focusAnalyticsRange=button.dataset.focusRange;
    if(state.focusAnalyticsRange==='custom'){state.focusAnalyticsStart=state.focusAnalyticsStart||iso(addDays(new Date(),-27));state.focusAnalyticsEnd=state.focusAnalyticsEnd||today();render();return}
    try{await loadFocusAnalytics()}catch(error){showError(error)}
  });
  const form=document.querySelector('#focus-analysis-dates');
  if(form)form.onsubmit=async event=>{event.preventDefault();state.focusAnalyticsStart=document.querySelector('#focus-analysis-start').value;state.focusAnalyticsEnd=document.querySelector('#focus-analysis-end').value;try{await loadFocusAnalytics()}catch(error){showError(error)}};
  const refresh=document.querySelector('#focus-analysis-refresh');
  if(refresh)refresh.onclick=()=>loadFocusAnalytics().catch(showError);
}
