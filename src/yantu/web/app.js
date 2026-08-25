const DOMAINS={research:'科研',course:'课程',personal:'个人',inbox:'收件箱'};
const STATUSES={not_started:'未开始',in_progress:'进行中',waiting:'等待',completed:'已完成',cancelled:'已取消'};
const PRIORITIES={urgent:'紧急',high:'高',medium:'中',low:'低'};
const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const pad=n=>String(n).padStart(2,'0');
const iso=date=>`${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())}`;
const parseDate=value=>{if(!value)return null;const [y,m,d]=value.split('-').map(Number);return new Date(y,m-1,d)};
const today=()=>iso(new Date());
const addDays=(date,days)=>{const next=new Date(date);next.setDate(next.getDate()+days);return next};
const ACTIVE_STATUSES=new Set(['not_started','in_progress','waiting']);
const APPEARANCE_DEFAULT={version:1,preset:'forest',mode:'system',background:{type:'none',color:'#e8eee8',gradient_start:'#e5efe8',gradient_end:'#dbe7ee',gradient_angle:135},surface_opacity:.92,has_background_image:false,background_url:null};
const THEME_PALETTES={
  forest:{light:{canvas:'#f4f7f3',surface:'#fffefb',strong:'#f9fcf8',text:'#17241e',muted:'#526059',border:'#b9c6bf',accent:'#275e48',soft:'#e4efe9'},dark:{canvas:'#132019',surface:'#1d2b24',strong:'#18251f',text:'#f2f7f3',muted:'#b9c8c0',border:'#52655b',accent:'#78b99b',soft:'#293d33'}},
  paper:{light:{canvas:'#f7f2e7',surface:'#fffdf7',strong:'#fbf7ee',text:'#29251f',muted:'#655e52',border:'#cec2ae',accent:'#765b34',soft:'#eee4d2'},dark:{canvas:'#211e19',surface:'#2c2821',strong:'#27231d',text:'#faf5e9',muted:'#c9bfad',border:'#665d4d',accent:'#d0ad70',soft:'#3d3529'}},
  mist:{light:{canvas:'#eef4f5',surface:'#fbfeff',strong:'#f5fafb',text:'#17272d',muted:'#50636b',border:'#b8c8cd',accent:'#3c7180',soft:'#dfecef'},dark:{canvas:'#132127',surface:'#1b2c33',strong:'#17272d',text:'#eff7f8',muted:'#b6c8cd',border:'#50666e',accent:'#7eb5c2',soft:'#263d45'}},
  night:{light:{canvas:'#edf0f6',surface:'#fbfcff',strong:'#f5f7fb',text:'#1d2433',muted:'#566074',border:'#bcc4d3',accent:'#405d8c',soft:'#e1e7f1'},dark:{canvas:'#111927',surface:'#1b2638',strong:'#162132',text:'#f1f5fb',muted:'#b5c0d2',border:'#4b5a72',accent:'#86a6da',soft:'#27364d'}}
};

const REQUEST_TOKEN=document.querySelector('meta[name="yantu-request-token"]')?.content||'';
let state={view:'today',status:'all',subcategory:'all',month:new Date(),tasks:[],events:[],courses:[],semesters:[],trash:{tasks:[],courses:[]},dailyPlan:{},planningProfile:null,planBlocks:[],planPreview:null,scheduleWeek:new Date(),semesterFilter:'',schedulePreview:null,loading:true,aiStatus:null,aiPreview:null,aiLoading:false,aiSettings:null,preferences:null,appearance:structuredClone(APPEARANCE_DEFAULT),appearanceDraft:null,appearanceImageFile:null,appearancePreviewUrl:null,appearanceRemoveImage:false,focus:null,focusStats:null,focusSaving:false,focusImmersive:false,focusWarningPlayed:false};

async function api(path,options={}){
  const unsafe=options.method&&options.method.toUpperCase()!=='GET';
  const security=unsafe&&REQUEST_TOKEN?{'X-Yantu-Token':REQUEST_TOKEN}:{};
  const headers=options.body instanceof FormData?{...security,...(options.headers||{})}:{'Content-Type':'application/json',...security,...(options.headers||{})};
  const response=await fetch(path,{...options,headers});
  if(!response.ok){let message=`请求失败（${response.status}）`;try{const data=await response.json();message=data.error||message}catch{}throw new Error(message)}
  return response.status===204?null:response.json();
}

function esc(value=''){const node=document.createElement('div');node.textContent=String(value);return node.innerHTML}
function fmtDuration(minutes=0){const n=Number(minutes)||0;if(!n)return '未估时';return n>=60?(n%60?`${Math.floor(n/60)}小时${n%60}分`:`${n/60}小时`):`${n}分钟`}
function fmtDate(value){if(!value)return '无截止日期';const d=parseDate(value);return `${d.getMonth()+1}月${d.getDate()}日`}
function isOverdue(task){return ACTIVE_STATUSES.has(task.status)&&task.due_date&&task.due_date<today()}
function active(task){return ACTIVE_STATUSES.has(task.status)}
function matchesFilters(task){return (state.status==='all'||task.status===state.status)&&(state.subcategory==='all'||task.subcategory===state.subcategory)}
function viewTasks(){let tasks=state.tasks.filter(matchesFilters);if(['research','course','personal','inbox'].includes(state.view))tasks=tasks.filter(task=>task.domain===state.view);return tasks}
function sortTasks(a,b){return Number(['completed','cancelled'].includes(a.status))-Number(['completed','cancelled'].includes(b.status))||({urgent:0,high:1,medium:2,low:3}[a.priority]-{urgent:0,high:1,medium:2,low:3}[b.priority])||Number(!a.due_date)-Number(!b.due_date)||(a.due_date||'9999').localeCompare(b.due_date||'9999')||a.title.localeCompare(b.title,'zh-CN')}

async function loadTasks({migrate=true}={}){
  const rangeStart=iso(addDays(new Date(),-180)),rangeEnd=iso(addDays(new Date(),180));
  const [data,semesterData,courseData,eventData,planData,profileData,confirmedPlan,focusData,statsData,preferencesData,aiSettingsData]=await Promise.all([api('/api/tasks'),api('/api/semesters'),api('/api/courses'),api(`/api/calendar/events?start=${rangeStart}&end=${rangeEnd}`),api(`/api/planning/daily?date=${today()}`),api('/api/planning/profile'),api(`/api/planning/plans?date=${today()}`),api('/api/focus/active'),api(`/api/focus/stats?start=${iso(addDays(new Date(),-6))}&end=${today()}`),api('/api/settings/preferences'),api('/api/settings/ai')]);
  state.tasks=data.tasks;
  state.semesters=semesterData.semesters;state.courses=courseData.courses;state.events=eventData.events;
  state.dailyPlan=Object.fromEntries(planData.allocations.map(item=>[item.task_id,item]));
  state.planningProfile=profileData.profile;state.planBlocks=confirmedPlan.blocks;
  state.focus=focusData.session;state.focusStats=statsData.stats;state.preferences=preferencesData.preferences;state.aiSettings=aiSettingsData.ai;
  try{state.aiStatus=await api('/api/ai/status')}catch(error){state.aiStatus={configured:false,error:error.message}}
  if(migrate&&state.tasks.length===0)await migrateLegacyTasks();
  state.loading=false;
  render();
}

async function migrateLegacyTasks(){
  const marker='yantu.sqlite.migrated.v2';
  if(localStorage.getItem(marker))return;
  let legacy=[];
  try{legacy=JSON.parse(localStorage.getItem('yantu.tasks.v1'))||[]}catch{}
  if(legacy.length){
    const mapped=legacy.map(task=>({
      id:task.id,
      title:task.title,
      domain:task.category==='life'?'personal':(task.category||'inbox'),
      subcategory:'',tags:[],description:'',start_date:task.date||null,due_date:task.date||null,
      estimated_minutes:Number(task.duration)||0,actual_minutes:0,priority:task.priority||'medium',
      status:task.done?'completed':'not_started',progress:task.done?100:0,is_recurring:false,
      recurrence_rule:'',notes:task.notes||'',created_at:new Date().toISOString()
    }));
    await api('/api/import',{method:'POST',body:JSON.stringify({tasks:mapped})});
    const data=await api('/api/tasks');state.tasks=data.tasks;
    toast(`已将浏览器中的 ${mapped.length} 个旧任务迁移到 SQLite`);
  }
  localStorage.setItem(marker,'1');
}

function render(){
  updateChrome();
  const content=$('#content');
  if(state.loading){content.innerHTML='<div class="loading">正在读取 SQLite 数据库…</div>';return}
  if(state.view==='ai')content.innerHTML=renderAI();
  else if(state.view==='today')content.innerHTML=renderToday();
  else if(state.view==='week')content.innerHTML=renderWeek();
  else if(state.view==='month')content.innerHTML=renderMonth();
  else if(state.view==='schedule')content.innerHTML=renderSchedule();
  else if(state.view==='trash')content.innerHTML=renderTrash();
  else if(state.view==='inbox')content.innerHTML=renderInbox();
  else content.innerHTML=renderDomain(state.view);
  bindDynamic();
}

function updateChrome(){
  const titles={today:'今日',inbox:'收件箱',research:'科研工作台',course:'课程学习',personal:'个人生活',week:'未来 7 天',month:'月历',schedule:'课程表',trash:'回收站'};
  $('#view-title').textContent=titles[state.view]||'AI 任务拆解';
  const now=new Date();
  $('#date-label').textContent=`${now.getFullYear()}年${now.getMonth()+1}月${now.getDate()}日 · ${['星期日','星期一','星期二','星期三','星期四','星期五','星期六'][now.getDay()]}`;
  $$('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.view===state.view));
  for(const domain of ['research','course','personal','inbox']){
    const count=state.tasks.filter(task=>task.domain===domain&&active(task)).length;
    $(`#count-${domain}`).textContent=count;
  }
  const values=[...new Set(state.tasks.map(task=>task.subcategory).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
  const select=$('#subcategory-filter');
  const current=state.subcategory;
  select.innerHTML='<option value="all">全部</option>'+values.map(value=>`<option value="${esc(value)}">${esc(value)}</option>`).join('');
  select.value=values.includes(current)?current:'all';
  if(select.value==='all')state.subcategory='all';
  $('#status-filter').value=state.status;
}

function renderToday(){
  const tasks=state.tasks.filter(matchesFilters);
  const must=tasks.filter(task=>active(task)&&task.due_date===today()&&['urgent','high'].includes(task.priority)).sort(sortTasks);
  const mustIds=new Set(must.map(task=>task.id));
  const planned=tasks.filter(task=>active(task)&&state.dailyPlan[task.id]&&!mustIds.has(task.id)&&!isOverdue(task)).sort(sortTasks);
  const overdue=tasks.filter(isOverdue).sort(sortTasks);
  const upcoming=tasks.filter(task=>active(task)&&task.due_date>today()).sort(sortTasks).slice(0,8);
  const todayTasks=[...must,...planned];
  const estimate=todayTasks.reduce((sum,task)=>sum+(Number(state.dailyPlan[task.id]?.planned_minutes)||0),0);
  const finished=tasks.filter(task=>task.status==='completed'&&task.completed_at&&iso(new Date(task.completed_at))===today()).length;
  const inbox=state.tasks.filter(task=>task.domain==='inbox'&&active(task)).sort(sortTasks).slice(0,5);
  const classes=state.events.filter(event=>event.date===today());
  return `<form class="quick-capture compact" id="quick-form"><div><strong>快速收件箱</strong><span>先记下导师临时任务或突然出现的想法，稍后再整理。</span></div><input id="quick-title" maxlength="160" required placeholder="刚想到什么？"><button class="primary-btn" type="submit">记下来</button></form><div class="summary-grid">
    <div class="summary-card hero"><p>今日工作面</p><strong>${todayTasks.length}</strong><span>${must.length} 项必须完成 · ${planned.length} 项计划推进</span></div>
    <div class="summary-card"><p>今日建议投入</p><strong>${fmtDuration(estimate)}</strong><span>按剩余日期分摊，专注记录会自动扣减</span></div>
    <div class="summary-card"><p>今日已完成</p><strong>${finished}</strong><span>${overdue.length?`仍有 ${overdue.length} 项逾期`:'当前没有逾期任务'}</span></div>
  </div>
  ${renderPlanningTimeline()}
  ${eventSection('今日课程',classes,'今天没有课程安排。')}
  ${listSection('今天必须完成',must,'没有必须今天完成的高优先级任务。',true)}
  ${listSection('今天计划推进',planned,'尚未安排今天的任务。',true)}
  ${listSection('已逾期任务',overdue,'很好，目前没有逾期任务。')}
  ${listSection('最近截止任务',upcoming,'近期没有明确 Deadline。')}
  ${listSection('收件箱待整理',inbox,'收件箱已经清空。')}`;
}

function renderPlanningTimeline(){
  const blocks=state.planBlocks||[];
  const head=`<div class="section-head planning-head"><div><h2>今日时间轴</h2><p>任务、课程占用与恢复节奏分开呈现</p></div><button class="secondary-btn" id="open-planning">${blocks.length?'重新规划':'安排今日'}</button></div>`;
  if(!blocks.length)return `${head}<div class="planning-empty"><span>⌁</span><div><strong>还没有确认的时间表</strong><p>先生成预览，再决定是否采用；不会直接覆盖任务。</p></div></div>`;
  return `${head}<div class="day-plan">${blocks.map(block=>{const task=state.tasks.find(item=>item.id===block.task_id);const labels={focus:task?.title||block.task_title||'专注任务',short_break:'短暂恢复',long_break:'长休息',buffer:'切换缓冲'};return `<article class="plan-block ${block.block_type}"><time>${esc(block.start_time)}<i></i>${esc(block.end_time)}</time><div><strong>${esc(labels[block.block_type]||block.block_type)}</strong><p>${esc(block.rationale||'')}</p></div>${block.block_type==='focus'?`<button class="more-btn" data-plan-focus="${block.task_id}" data-plan-block="${block.id||''}">开始专注</button>`:'<span class="plan-rest">REST</span>'}</article>`}).join('')}</div>`;
}

function renderInbox(){
  const tasks=viewTasks().sort(sortTasks);
  return `<form class="quick-capture" id="quick-form"><div><strong>先记下来，稍后再整理</strong><span>导师临时安排、突然想到的实验点子，都可以先放进收件箱。</span></div><input id="quick-title" maxlength="160" required placeholder="快速记录一个任务…"><button class="primary-btn" type="submit">加入收件箱</button></form>${listSection('待整理',tasks,'收件箱已经清空。')}`;
}

function renderDomain(domain){
  const tasks=viewTasks().sort(sortTasks);
  const activeCount=tasks.filter(active).length;
  const minutes=tasks.filter(active).reduce((sum,task)=>sum+(Number(task.estimated_minutes)||0),0);
  return `<div class="domain-intro ${domain}"><div><p>${DOMAINS[domain]}领域</p><h2>${domain==='research'?'推进研究，而不只是响应任务':domain==='course'?'让课程投入可见、可控':'生活是长期科研的底盘'}</h2></div><div><strong>${activeCount}</strong><span>进行中的任务</span></div><div><strong>${fmtDuration(minutes)}</strong><span>剩余预计投入</span></div></div>${listSection(`${DOMAINS[domain]}任务`,tasks,`还没有${DOMAINS[domain]}任务。`)}`;
}

function listSection(title,tasks,emptyText='暂无任务',showDailyAllocation=false){
  return `<div class="section-head"><h2>${title}</h2><span>${tasks.length} 项</span></div>${tasks.length?`<div class="task-list">${tasks.map(task=>taskCard(task,showDailyAllocation?state.dailyPlan[task.id]:null)).join('')}</div>`:`<div class="empty"><strong>这里暂时是空的</strong>${emptyText}</div>`}`;
}

function taskCard(task,dailyAllocation=null){
  const done=task.status==='completed';
  const meta=[DOMAINS[task.domain],task.subcategory,task.due_date?`截止 ${fmtDate(task.due_date)}`:'无 Deadline',fmtDuration(task.estimated_minutes),dailyAllocation?`今日建议 ${fmtDuration(dailyAllocation.planned_minutes)}`:''].filter(Boolean).join(' · ');
  return `<article class="task-card ${task.domain} ${done?'done':''} ${isOverdue(task)?'overdue':''}" data-task-context="${task.id}">
    <input class="check" type="checkbox" aria-label="标记完成" data-check="${task.id}" ${done?'checked':''} ${task.status==='cancelled'?'disabled':''}>
    <div class="task-main"><div class="task-title-row"><h3>${esc(task.title)}</h3><span class="status-badge ${task.status}">${STATUSES[task.status]}</span>${task.is_recurring?'<span class="badge">重复</span>':''}</div><p>${esc(meta)}</p>${task.description?`<p class="description">${esc(task.description)}</p>`:''}${task.tags?.length?`<div class="tag-row">${task.tags.map(tag=>`<span>#${esc(tag)}</span>`).join('')}</div>`:''}<div class="progress-track" title="完成度 ${task.progress}%"><i style="width:${task.progress}%"></i></div></div>
    <div class="task-controls"><select data-priority="${task.id}" aria-label="修改优先级" class="priority-select ${task.priority}">${Object.entries(PRIORITIES).map(([key,label])=>`<option value="${key}" ${key===task.priority?'selected':''}>${label}优先级</option>`).join('')}</select><input type="date" data-due="${task.id}" value="${task.due_date||''}" aria-label="修改截止日期"><button class="edit-btn" data-edit="${task.id}" aria-label="编辑任务">编辑</button><button class="more-btn" data-task-menu="${task.id}" aria-label="任务快捷操作">⋯</button></div>
  </article>`;
}

function eventSection(title,events,emptyText){return `<div class="section-head"><h2>${title}</h2><span>${events.length} 节</span></div>${events.length?`<div class="event-list">${events.map(event=>`<div class="event-row" data-course-context="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"><div><b>${esc(event.start_time)}–${esc(event.end_time)} · ${esc(event.title)}</b><span>${esc(event.location||'地点待定')} · 第 ${event.week} 周</span></div><button class="more-btn" data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}" aria-label="课程快捷操作">⋯</button></div>`).join('')}</div>`:`<div class="empty">${emptyText}</div>`}`}

function renderWeek(){
  const start=new Date();start.setHours(0,0,0,0);
  const days=Array.from({length:7},(_,index)=>addDays(start,index));
  const tasks=state.tasks.filter(matchesFilters);
  return `<div class="week-grid">${days.map((day,index)=>{const date=iso(day);const daily=tasks.filter(task=>task.start_date===date||task.due_date===date).sort(sortTasks);const classes=state.events.filter(event=>event.date===date);return `<div class="day-column"><div class="day-head ${index===0?'today':''}">${['周日','周一','周二','周三','周四','周五','周六'][day.getDay()]}<strong>${day.getMonth()+1}/${day.getDate()}</strong></div>${classes.map(event=>`<button class="course-event" data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"><b>${esc(event.start_time)} ${esc(event.title)}</b><span>${esc(event.location||'地点待定')}</span></button>`).join('')}${daily.map(task=>`<button class="mini-task ${task.domain} ${task.status==='completed'?'done':''}" data-task-context="${task.id}" data-edit="${task.id}"><b>${esc(task.title)}</b><span>${task.due_date===date?'Deadline':'计划开始'} · ${PRIORITIES[task.priority]}优先级</span></button>`).join('')}${!daily.length&&!classes.length?'<p class="day-empty">留白</p>':''}</div>`}).join('')}</div>`;
}

function monthStart(date){const first=new Date(date.getFullYear(),date.getMonth(),1);const day=first.getDay()||7;first.setDate(first.getDate()-day+1);return first}
function renderMonth(){
  const year=state.month.getFullYear(),month=state.month.getMonth(),start=monthStart(state.month);
  const days=Array.from({length:42},(_,index)=>addDays(start,index));
  const tasks=state.tasks.filter(matchesFilters);
  const noDeadline=tasks.filter(task=>active(task)&&!task.due_date&&['urgent','high'].includes(task.priority)).sort(sortTasks);
  return `<div class="month-nav"><button id="prev-month">‹ 上个月</button><h2>${year} 年 ${month+1} 月</h2><button id="next-month">下个月 ›</button></div><div class="calendar">${['一','二','三','四','五','六','日'].map(day=>`<div class="calendar-weekday">周${day}</div>`).join('')}${days.map(day=>{const date=iso(day);const daily=tasks.filter(task=>task.due_date===date).sort(sortTasks);const classes=state.events.filter(event=>event.date===date);return `<div class="calendar-day ${day.getMonth()!==month?'outside':''} ${date===today()?'today':''}"><span class="num">${day.getDate()}</span>${classes.slice(0,2).map(event=>`<button class="calendar-course" data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}">${esc(event.start_time)} ${esc(event.title)}</button>`).join('')}${daily.slice(0,Math.max(0,4-classes.length)).map(task=>`<button class="cal-task ${task.domain}" data-task-context="${task.id}" data-edit="${task.id}">${task.status==='completed'?'✓ ':''}${esc(task.title)}</button>`).join('')}${daily.length+classes.length>4?`<div class="cal-more">另 ${daily.length+classes.length-4} 项</div>`:''}</div>`}).join('')}</div>${listSection('高优先级但尚无 Deadline',noDeadline,'目前没有需要补充 Deadline 的高优先级任务。')}`;
}

function mondayOf(value){const day=new Date(value);day.setHours(0,0,0,0);day.setDate(day.getDate()-(day.getDay()||7)+1);return day}
function renderSchedule(){
  const monday=mondayOf(state.scheduleWeek),days=Array.from({length:7},(_,index)=>addDays(monday,index));
  const weekEvents=state.events.filter(event=>event.date>=iso(days[0])&&event.date<=iso(days[6])&&(!state.semesterFilter||event.semester_id===state.semesterFilter));
  const semesterOptions=state.semesters.map(item=>`<option value="${item.id}" ${state.semesterFilter===item.id?'selected':''}>${esc(item.name)}</option>`).join('');
  const cells=[];
  cells.push('<div class="schedule-cell head">节次</div>',...days.map(day=>`<div class="schedule-cell head">周${'一二三四五六日'[day.getDay()===0?6:day.getDay()-1]}<br>${day.getMonth()+1}/${day.getDate()}</div>`));
  for(let period=1;period<=10;period++){
    cells.push(`<div class="schedule-cell period">第 ${period} 节</div>`);
    for(const day of days){
      const entries=weekEvents.filter(event=>event.date===iso(day)&&event.start_period===period);
      cells.push(`<div class="schedule-cell">${entries.map(event=>`<button class="course-event" style="border-left-color:${esc(event.color)}" data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"><b>${esc(event.title)}</b><span>${esc(event.start_time)}–${esc(event.end_time)}<br>${esc(event.location||'地点待定')}</span></button>`).join('')}</div>`);
    }
  }
  return `<div class="schedule-toolbar"><label class="field"><span>当前学期</span><select id="semester-filter"><option value="">全部学期</option>${semesterOptions}</select></label><button class="secondary-btn" id="schedule-prev">‹ 上一周</button><button class="secondary-btn" id="schedule-today">本周</button><button class="secondary-btn" id="schedule-next">下一周 ›</button><button class="primary-btn" id="import-schedule">导入课表</button></div>${state.semesters.length?`<div class="schedule-board">${cells.join('')}</div>`:'<div class="empty"><strong>还没有课程表</strong>导入图片、XLSX 或 CSV，核对预览后再加入日程。<br><br><button class="primary-btn" id="import-schedule-empty">导入第一份课表</button></div>'}`;
}

function renderTrash(){
  const rows=[...state.trash.tasks.map(item=>({type:'task',id:item.id,name:item.title,detail:'任务'})),...state.trash.courses.map(item=>({type:'course',id:item.id,name:item.name,detail:'课程'}))];
  return `<div class="section-head"><h2>可恢复的条目</h2><span>${rows.length} 项</span></div>${rows.length?`<div class="trash-list">${rows.map(item=>`<div class="trash-row"><div><b>${esc(item.name)}</b><span>${item.detail}</span></div><button class="secondary-btn" data-restore-type="${item.type}" data-restore="${item.id}">恢复</button><button class="danger-link" data-permanent-type="${item.type}" data-permanent="${item.id}">永久删除</button></div>`).join('')}</div>`:'<div class="empty"><strong>回收站为空</strong>从快捷菜单删除的任务和课程会暂存在这里。</div>'}`;
}

function renderAI(){
  const status=state.aiStatus||{configured:false};
  const statusText=status.configured
    ? `已连接 ${esc(status.provider)} · ${esc(status.model)}`
    : '尚未配置 API Key，可直接在 Yantu 设置中安全保存。';
  const preview=state.aiPreview;
  return `<section class="ai-workbench">
    <div class="ai-hero"><div><p>人工智能辅助规划</p><h2>先预览，再由你决定是否写入任务库</h2><span>${statusText}</span></div><b class="ai-status ${status.configured?'ready':''}">${status.configured?'可用':'待配置'}</b></div>
    ${status.configured?'':`<div class="ai-confirm"><p>密钥只保存在 Windows 凭据库，不会写入数据库或备份。</p><button id="open-ai-settings" class="primary-btn">配置 API Key</button></div>`}
    <form id="ai-form" class="ai-form"><label class="field full"><span>需要拆解的任务</span><textarea id="ai-task" rows="4" maxlength="1000" required placeholder="例如：准备下个月激光雷达组会汇报">${esc(preview?.source||'')}</textarea></label><button class="primary-btn" type="submit" ${state.aiLoading||!status.configured?'disabled':''}>${state.aiLoading?'正在生成…':'生成拆解预览'}</button></form>
    ${preview?`<div class="ai-preview"><div class="section-head"><h2>${esc(preview.breakdown.title)}</h2><span>${preview.breakdown.subtasks.length} 个子任务</span></div><div class="ai-subtasks">${preview.breakdown.subtasks.map((item,index)=>`<article><b>${index+1}</b><div><h3>${esc(item.name)}</h3><p>${item.dependencies.length?`前置：${item.dependencies.map(esc).join('、')}`:'无前置依赖'}</p></div><span>${esc(item.priority)} · ${item.estimated_hours} 小时</span></article>`).join('')}</div><div class="ai-confirm"><p>当前内容只是预览，尚未写入 SQLite。</p><button id="ai-confirm" class="primary-btn">确认并加入科研任务</button></div></div>`:''}
  </section>`;
}

function bindDynamic(){
  $$('[data-edit]').forEach(button=>button.onclick=()=>openDialog(state.tasks.find(task=>task.id===button.dataset.edit)));
  $$('[data-check]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.check);try{await patchTask(task.id,{status:input.checked?'completed':'in_progress',progress:input.checked?100:Math.min(task.progress,95)});toast(input.checked?'任务已完成':'任务已恢复为进行中')}catch(error){input.checked=!input.checked;showError(error)}});
  $$('[data-priority]').forEach(select=>select.onchange=async()=>{const task=state.tasks.find(item=>item.id===select.dataset.priority);try{await patchTask(task.id,{priority:select.value});toast('优先级已更新')}catch(error){select.value=task.priority;showError(error)}});
  $$('[data-due]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.due);try{await patchTask(task.id,{due_date:input.value||null});toast('Deadline 已更新')}catch(error){input.value=task.due_date||'';showError(error)}});
  if($('#quick-form'))$('#quick-form').onsubmit=async event=>{event.preventDefault();const title=$('#quick-title').value.trim();if(!title)return;try{await createTask({title,domain:'inbox',priority:'medium',status:'not_started',progress:0,estimated_minutes:0});toast('已加入收件箱')}catch(error){showError(error)}};
  if($('#open-planning'))$('#open-planning').onclick=openPlanningDialog;
  $$('[data-plan-focus]').forEach(button=>button.onclick=()=>openFocus(button.dataset.planFocus,button.dataset.planBlock));
  if($('#prev-month'))$('#prev-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()-1,1);render()};
  if($('#next-month'))$('#next-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()+1,1);render()};
  if($('#ai-form'))$('#ai-form').onsubmit=async event=>{event.preventDefault();const task=$('#ai-task').value.trim();if(!task)return;state.aiLoading=true;render();try{const data=await api('/api/ai/breakdown/preview',{method:'POST',body:JSON.stringify({task})});state.aiPreview={source:task,breakdown:data.breakdown};toast('拆解预览已生成，尚未写入数据库')}catch(error){showError(error)}finally{state.aiLoading=false;render()}};
  if($('#ai-confirm'))$('#ai-confirm').onclick=async()=>{if(!state.aiPreview)return;try{await api('/api/ai/breakdown/confirm',{method:'POST',body:JSON.stringify({domain:'research',breakdown:state.aiPreview.breakdown})});state.aiPreview=null;await loadTasks({migrate:false});state.view='research';render();toast('已确认并加入科研任务')}catch(error){showError(error)}};
  if($('#open-ai-settings'))$('#open-ai-settings').onclick=()=>openSettings('ai');
  $$('[data-task-context]').forEach(node=>node.oncontextmenu=event=>{event.preventDefault();showTaskMenu(node.dataset.taskContext,event.clientX,event.clientY)});
  $$('[data-task-menu]').forEach(node=>node.onclick=event=>{event.stopPropagation();showTaskMenu(node.dataset.taskMenu,event.clientX,event.clientY)});
  $$('[data-course-menu]').forEach(node=>{node.onclick=event=>{event.stopPropagation();showCourseMenu(node.dataset.courseMenu,node.dataset.meetingId,node.dataset.eventDate,event.clientX,event.clientY)};node.oncontextmenu=event=>{event.preventDefault();showCourseMenu(node.dataset.courseMenu,node.dataset.meetingId,node.dataset.eventDate,event.clientX,event.clientY)}});
  if($('#schedule-prev'))$('#schedule-prev').onclick=()=>{state.scheduleWeek=addDays(state.scheduleWeek,-7);render()};
  if($('#schedule-next'))$('#schedule-next').onclick=()=>{state.scheduleWeek=addDays(state.scheduleWeek,7);render()};
  if($('#schedule-today'))$('#schedule-today').onclick=()=>{state.scheduleWeek=new Date();render()};
  if($('#semester-filter'))$('#semester-filter').onchange=event=>{state.semesterFilter=event.target.value;render()};
  if($('#import-schedule'))$('#import-schedule').onclick=openScheduleDialog;
  if($('#import-schedule-empty'))$('#import-schedule-empty').onclick=openScheduleDialog;
  $$('[data-restore]').forEach(button=>button.onclick=()=>restoreTrash(button.dataset.restoreType,button.dataset.restore));
  $$('[data-permanent]').forEach(button=>button.onclick=()=>permanentDelete(button.dataset.permanentType,button.dataset.permanent));
}

function menuButton(label,action,danger=false){return `<button role="menuitem" data-menu-action="${action}" class="${danger?'danger':''}">${label}</button>`}
function positionMenu(x,y){const menu=$('#context-menu');menu.classList.remove('hidden');const rect=menu.getBoundingClientRect();menu.style.left=`${Math.max(8,Math.min(x,innerWidth-rect.width-8))}px`;menu.style.top=`${Math.max(8,Math.min(y,innerHeight-rect.height-8))}px`;menu.querySelector('button')?.focus()}
function closeContextMenu(){$('#context-menu').classList.add('hidden')}
function bindMenu(actions,x,y){const menu=$('#context-menu');menu.innerHTML=actions.html;menu.querySelectorAll('[data-menu-action]').forEach(button=>button.onclick=async()=>{closeContextMenu();try{await actions.run(button.dataset.menuAction)}catch(error){showError(error)}});positionMenu(x,y)}
function showTaskMenu(id,x,y){const task=state.tasks.find(item=>item.id===id);if(!task)return;bindMenu({html:[menuButton('开始专注','focus'),menuButton('编辑','edit'),menuButton(task.status==='completed'?'恢复为进行中':'标记完成','toggle'),'<hr>',menuButton('改到今天','today'),menuButton('改到明天','tomorrow'),menuButton('改到下周','nextweek'),menuButton('清除截止日期','clear'),'<hr>',menuButton('复制任务','duplicate'),menuButton('移动领域…','move'),menuButton('移入回收站','delete',true)].join(''),run:async action=>{
    if(action==='focus')return openFocus(id);
    if(action==='edit')return openDialog(task);
    if(action==='toggle')return patchTask(id,{status:task.status==='completed'?'in_progress':'completed'});
    if(['today','tomorrow','nextweek','clear'].includes(action)){const dates={today:today(),tomorrow:iso(addDays(new Date(),1)),nextweek:iso(addDays(new Date(),7)),clear:null};await patchTask(id,{due_date:dates[action]});return toast('截止日期已更新')}
    if(action==='duplicate'){const copy={...task,title:`${task.title}（副本）`,status:'not_started',progress:0,completed_at:null};for(const key of ['id','created_at','updated_at','deleted_at','deadline','estimated_hours','actual_hours','parent_task_id'])delete copy[key];await createTask(copy);return toast('任务已复制')}
    if(action==='move'){const target=prompt('输入目标领域：research / course / personal / inbox',task.domain);if(target&&DOMAINS[target]){await patchTask(id,{domain:target});toast('任务领域已更新')}return}
    if(action==='delete')return trashTask(id);
  }},x,y)}
function showCourseMenu(id,meetingId,eventDate,x,y){bindMenu({html:[menuButton('编辑课程','edit'),menuButton('复制课程','duplicate'),meetingId&&eventDate?menuButton('跳过本次','skip'):'',menuButton('移入回收站','delete',true)].join(''),run:async action=>{
    if(action==='edit')return openCourseDialog(id);
    if(action==='duplicate'){await api(`/api/courses/${id}/duplicate`,{method:'POST'});await loadTasks({migrate:false});return toast('课程已复制')}
    if(action==='skip'){await api(`/api/course-meetings/${meetingId}/exceptions`,{method:'POST',body:JSON.stringify({kind:'skip',date:eventDate})});await loadTasks({migrate:false});return toast('已跳过本次课程')}
    if(action==='delete')return trashCourse(id);
  }},x,y)}

async function trashTask(id){await api(`/api/tasks/${id}`,{method:'DELETE'});state.tasks=state.tasks.filter(item=>item.id!==id);render();toast('任务已移入回收站','撤销',async()=>{await api(`/api/tasks/${id}/restore`,{method:'POST'});await loadTasks({migrate:false})})}
async function trashCourse(id){await api(`/api/courses/${id}`,{method:'DELETE'});await loadTasks({migrate:false});toast('课程已移入回收站','撤销',async()=>{await api(`/api/courses/${id}/restore`,{method:'POST'});await loadTasks({migrate:false})})}
async function loadTrash(){state.trash=await api('/api/trash');render()}
async function restoreTrash(type,id){await api(type==='task'?`/api/tasks/${id}/restore`:`/api/courses/${id}/restore`,{method:'POST'});await loadTasks({migrate:false});await loadTrash();toast('条目已恢复')}
async function permanentDelete(type,id){if(!confirm('永久删除后无法恢复，是否继续？'))return;await api(type==='task'?`/api/tasks/${id}/permanent`:`/api/courses/${id}/permanent`,{method:'DELETE'});await loadTrash();toast('条目已永久删除')}

function openScheduleDialog(){state.schedulePreview=null;$('#schedule-form').reset();const start=mondayOf(new Date());$('#semester-name').value=`${start.getFullYear()} 学期`;$('#semester-start').value=iso(start);$('#semester-end').value=iso(addDays(start,139));$('#schedule-step-input').classList.remove('hidden');$('#schedule-preview').classList.add('hidden');$('#schedule-dialog').showModal()}
function renderSchedulePreview(){const preview=state.schedulePreview;const node=$('#schedule-preview');node.classList.remove('hidden');$('#schedule-step-input').classList.add('hidden');node.innerHTML=`<div class="section-head"><h2>核对识别结果</h2><span>${preview.courses.length} 门课程</span></div>${preview.warnings.map(item=>`<p class="preview-message">${esc(item)}</p>`).join('')}<div class="schedule-preview-list">${preview.courses.map((course,index)=>{const meeting=course.meetings[0]||{};return `<div class="preview-course ${course.errors.length?'invalid':''}" data-preview-index="${index}"><div class="preview-course-grid"><input type="checkbox" data-field="selected" ${course.selected?'checked':''} ${course.errors.length?'disabled':''}><input data-field="name" value="${esc(course.name)}" placeholder="课程名称"><input data-field="teacher" value="${esc(course.teacher)}" placeholder="教师"><input data-field="location" value="${esc(course.location)}" placeholder="地点"><span></span><select data-field="weekday">${[1,2,3,4,5,6,7].map(day=>`<option value="${day}" ${day===meeting.weekday?'selected':''}>周${'一二三四五六日'[day-1]}</option>`).join('')}</select><input type="number" data-field="start_period" value="${meeting.start_period||1}" min="1" placeholder="开始节"><input type="number" data-field="end_period" value="${meeting.end_period||2}" min="1" placeholder="结束节"><span></span><input type="time" data-field="start_time" value="${meeting.start_time||''}"><input type="time" data-field="end_time" value="${meeting.end_time||''}"><input data-field="weeks" value="${meeting.start_week||1}-${meeting.end_week||18} ${meeting.week_pattern||'all'}" title="示例：1-16 odd"></div>${[...course.errors,...course.warnings].map(item=>`<p class="preview-message">${esc(item)}</p>`).join('')}</div>`}).join('')}</div><div class="dialog-actions"><button class="secondary-btn" type="button" id="preview-back">返回</button><span></span><button class="secondary-btn" type="button" id="preview-cancel">取消</button><button class="primary-btn" type="button" id="confirm-schedule">确认导入</button></div>`;
  $('#preview-back').onclick=()=>{$('#schedule-step-input').classList.remove('hidden');node.classList.add('hidden')};$('#preview-cancel').onclick=()=>$('#schedule-dialog').close();$('#confirm-schedule').onclick=confirmScheduleImport;
}
function collectSchedulePreview(){const preview=structuredClone(state.schedulePreview);$$('[data-preview-index]').forEach(card=>{const course=preview.courses[Number(card.dataset.previewIndex)],field=name=>card.querySelector(`[data-field="${name}"]`);course.selected=field('selected').checked;course.name=field('name').value.trim();course.teacher=field('teacher').value.trim();course.location=field('location').value.trim();const [range,pattern='all']=field('weeks').value.trim().split(/\s+/),parts=range.split('-').map(Number),meeting=course.meetings[0]||{};Object.assign(meeting,{weekday:Number(field('weekday').value),start_period:Number(field('start_period').value),end_period:Number(field('end_period').value),start_time:field('start_time').value,end_time:field('end_time').value,start_week:parts[0],end_week:parts[1]||parts[0],week_pattern:pattern,custom_weeks:[]});course.meetings=[meeting]});return preview}
async function confirmScheduleImport(){const preview=collectSchedulePreview();await api('/api/schedule-import/confirm',{method:'POST',body:JSON.stringify(preview)});$('#schedule-dialog').close();await loadTasks({migrate:false});state.view='schedule';render();toast('课表已加入日程')}

async function openCourseDialog(id){const data=await api(`/api/courses/${id}`),course=data.course,meeting=course.meetings[0];$('#course-id').value=id;$('#course-name').value=course.name;$('#course-teacher').value=course.teacher;$('#course-location').value=course.location;$('#course-notes').value=course.notes;$('#course-weekday').value=meeting.weekday;$('#course-start-period').value=meeting.start_period;$('#course-end-period').value=meeting.end_period;$('#course-start-time').value=meeting.start_time;$('#course-end-time').value=meeting.end_time;$('#course-start-week').value=meeting.start_week;$('#course-end-week').value=meeting.end_week;$('#course-week-pattern').value=meeting.week_pattern==='custom'?'all':meeting.week_pattern;$('#course-dialog').showModal()}

async function createTask(payload){const data=await api('/api/tasks',{method:'POST',body:JSON.stringify(payload)});state.tasks.push(data.task);render();return data.task}
async function patchTask(id,changes){const data=await api(`/api/tasks/${id}`,{method:'PATCH',body:JSON.stringify(changes)});state.tasks=state.tasks.map(task=>task.id===id?data.task:task);render();return data.task}

function openDialog(task=null){
  $('#task-form').reset();
  $('.advanced-settings').open=Boolean(task);
  $('#task-id').value=task?.id||'';
  $('#dialog-title').textContent=task?'编辑任务':'新建任务';
  $('#delete-btn').classList.toggle('hidden',!task);
  $('#task-title').value=task?.title||'';
  $('#task-domain').value=task?.domain||(['research','course','personal','inbox'].includes(state.view)?state.view:'research');
  $('#task-subcategory').value=task?.subcategory||'';
  $('#task-description').value=task?.description||'';
  $('#task-start-date').value=task?.start_date||'';
  $('#task-due-date').value=task?.due_date||'';
  $('#task-priority').value=task?.priority||'medium';
  $('#task-status').value=task?.status||'not_started';
  $('#task-progress').value=task?.progress||0;
  $('#task-tags').value=(task?.tags||[]).join(', ');
  $('#task-estimated').value=task?.estimated_minutes??60;
  $('#task-actual').value=task?.actual_minutes??0;
  $('#task-recurring').checked=Boolean(task?.is_recurring);
  $('#task-recurrence').disabled=!task?.is_recurring;
  $('#task-recurrence').value=task?.recurrence_rule||'';
  $('#task-notes').value=task?.notes||'';
  $('#task-dialog').showModal();
}
function closeDialog(){$('#task-dialog').close()}
function formPayload(){const startDate=$('#task-start-date').value||null,dueDate=$('#task-due-date').value||null;if(startDate&&dueDate&&startDate>dueDate)throw new Error('开始日期不能晚于截止日期');return {title:$('#task-title').value.trim(),domain:$('#task-domain').value,subcategory:$('#task-subcategory').value.trim(),description:$('#task-description').value.trim(),start_date:startDate,due_date:dueDate,priority:$('#task-priority').value,status:$('#task-status').value,progress:Number($('#task-progress').value)||0,tags:$('#task-tags').value.split(',').map(value=>value.trim()).filter(Boolean),estimated_minutes:Number($('#task-estimated').value)||0,actual_minutes:Number($('#task-actual').value)||0,is_recurring:$('#task-recurring').checked,recurrence_rule:$('#task-recurring').checked?$('#task-recurrence').value.trim():'',notes:$('#task-notes').value.trim()}}
function toast(message,actionLabel='',action=null){const node=$('#toast'),button=$('#toast-action');$('#toast-text').textContent=message;button.textContent=actionLabel;button.classList.toggle('hidden',!action);button.onclick=action?async()=>{button.classList.add('hidden');try{await action();toast('操作已撤销')}catch(error){showError(error)}}:null;node.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.classList.remove('show'),action?6000:2400)}
function showError(error){console.error(error);toast(error.message||'操作失败，请查看启动窗口日志')}

function selectSettingsTab(tab='focus'){
  $$('[data-settings-tab]').forEach(button=>button.classList.toggle('active',button.dataset.settingsTab===tab));
  $$('[data-settings-page]').forEach(page=>page.classList.toggle('hidden',page.dataset.settingsPage!==tab));
  $('#save-preferences').classList.toggle('hidden',tab!=='focus');
}
function fillSettings(){
  const preferences=state.preferences||{sound_enabled:true,notification_enabled:false,auto_start_break:true,volume:60};
  $('#setting-sound').checked=preferences.sound_enabled;$('#setting-notification').checked=preferences.notification_enabled;$('#setting-auto-break').checked=preferences.auto_start_break;$('#setting-volume').value=preferences.volume;$('#setting-volume-output').textContent=`${preferences.volume}%`;
  const ai=state.aiSettings||{};$('#ai-base-url').value=ai.base_url||'https://api.deepseek.com';$('#ai-model').value=ai.model||'deepseek-v4-flash';$('#ai-timeout').value=ai.timeout||60;$('#ai-api-key').value='';$('#ai-api-key').disabled=Boolean(ai.managed_by_environment);$('#save-ai-settings').disabled=false;
  const source=ai.credential_source==='environment'?'由环境变量管理':ai.configured?`已安全配置 ${ai.masked_hint||''}`:'尚未配置';
  $('#ai-settings-status').textContent=ai.credential_error?`${source}；${ai.credential_error}`:source;
  $('#delete-ai-key').disabled=!ai.configured||ai.managed_by_environment;
}
function openSettings(tab='focus'){fillSettings();selectSettingsTab(tab);$('#settings-dialog').showModal()}
function closeSettings(){$('#settings-dialog').close();$('#ai-api-key').value=''}
async function savePreferences(event){event.preventDefault();let notification=$('#setting-notification').checked;if(notification&&'Notification'in window&&Notification.permission!=='granted'){const permission=await Notification.requestPermission();notification=permission==='granted';$('#setting-notification').checked=notification;if(!notification)toast('通知未获授权，将继续使用标题、Toast 和提示音提醒')}try{const data=await api('/api/settings/preferences',{method:'PUT',body:JSON.stringify({sound_enabled:$('#setting-sound').checked,notification_enabled:notification,auto_start_break:$('#setting-auto-break').checked,volume:Number($('#setting-volume').value)})});state.preferences=data.preferences;toast('专注偏好已保存')}catch(error){showError(error)}}
async function saveAiSettings(){const button=$('#save-ai-settings');button.disabled=true;try{const data=await api('/api/settings/ai',{method:'PUT',body:JSON.stringify({api_key:$('#ai-api-key').value.trim(),base_url:$('#ai-base-url').value.trim(),model:$('#ai-model').value.trim(),timeout:Number($('#ai-timeout').value)})});state.aiSettings=data.ai;$('#ai-api-key').value='';fillSettings();toast('AI 设置已安全保存')}catch(error){showError(error)}finally{button.disabled=false}}
async function testAiSettings(){const button=$('#test-ai-key');button.disabled=true;button.textContent='连接中…';try{const data=await api('/api/settings/ai/test',{method:'POST'});toast(data.model_available?'连接成功，所选模型可用':'连接成功，但所选模型不在模型列表中')}catch(error){showError(error)}finally{button.disabled=false;button.textContent='测试连接'}}
async function deleteAiKey(){if(!confirm('从 Windows 凭据管理器删除 DeepSeek API Key？'))return;try{const data=await api('/api/settings/ai/key',{method:'DELETE'});state.aiSettings=data.ai;fillSettings();toast('API Key 已删除')}catch(error){showError(error)}}

function fillPlanningProfile(){const profile=state.planningProfile;$('#plan-work-start').value=profile.workday_start;$('#plan-work-end').value=profile.workday_end;$('#plan-use-pomodoro').value=String(profile.use_pomodoro);$('#plan-focus').value=profile.focus_minutes;$('#plan-short-break').value=profile.short_break_minutes;$('#plan-long-break').value=profile.long_break_minutes;$('#plan-long-after').value=profile.long_break_after;$('#plan-max-continuous').value=profile.max_continuous_focus;$('#plan-buffer').value=profile.buffer_minutes}
function planningProfilePayload(){return {workday_start:$('#plan-work-start').value,workday_end:$('#plan-work-end').value,use_pomodoro:$('#plan-use-pomodoro').value==='true',focus_minutes:Number($('#plan-focus').value),short_break_minutes:Number($('#plan-short-break').value),long_break_minutes:Number($('#plan-long-break').value),long_break_after:Number($('#plan-long-after').value),max_continuous_focus:Number($('#plan-max-continuous').value),buffer_minutes:Number($('#plan-buffer').value)}}
function openPlanningDialog(){state.planPreview=null;fillPlanningProfile();$('#confirm-planning').classList.add('hidden');$('#planning-preview').innerHTML='<div class="empty"><strong>先生成一个可检查的时间表</strong>会综合任务优先级、Deadline、课程占用和休息偏好。</div>';$('#planning-dialog').showModal()}
function closePlanningDialog(){$('#planning-dialog').close();state.planPreview=null}
function planTypeLabel(type){return {focus:'专注',short_break:'短休息',long_break:'长休息',buffer:'切换缓冲',course:'课程'}[type]||type}
function renderPlanningPreview(){const preview=state.planPreview;if(!preview)return;const taskNames=Object.fromEntries(state.tasks.map(task=>[task.id,task.title]));const items=[...preview.blocks.map(block=>({...block,title:block.block_type==='focus'?taskNames[block.task_id]:planTypeLabel(block.block_type)})),...preview.fixed_events.map(event=>({start_time:event.start_time,end_time:event.end_time,block_type:'course',title:event.title,rationale:event.location||'固定课程'}))].sort((a,b)=>a.start_time.localeCompare(b.start_time));$('#planning-preview').innerHTML=`<div class="plan-summary"><div><strong>${fmtDuration(preview.summary.scheduled_focus_minutes)}</strong><span>已安排专注</span></div><div><strong>${fmtDuration(preview.summary.break_minutes)}</strong><span>主动恢复</span></div><div><strong>${fmtDuration(preview.summary.unscheduled_minutes)}</strong><span>超出容量</span></div></div>${preview.warnings.length?`<div class="plan-warnings">${preview.warnings.map(esc).join('<br>')}</div>`:''}<div class="preview-timeline">${items.map(item=>`<article class="${item.block_type}"><time>${esc(item.start_time)}–${esc(item.end_time)}</time><div><strong>${esc(item.title)}</strong><p>${esc(item.rationale||planTypeLabel(item.block_type))}</p></div></article>`).join('')}</div>`;$('#confirm-planning').classList.remove('hidden')}
async function previewPlanning(){const button=$('#preview-planning');button.disabled=true;button.textContent='正在计算…';try{const saved=await api('/api/planning/profile',{method:'PUT',body:JSON.stringify(planningProfilePayload())});state.planningProfile=saved.profile;const result=await api('/api/planning/preview',{method:'POST',body:JSON.stringify({date:today()})});state.planPreview=result.preview;renderPlanningPreview()}catch(error){showError(error)}finally{button.disabled=false;button.textContent='生成预览'}}
async function confirmPlanning(event){event.preventDefault();if(!state.planPreview)return;const button=$('#confirm-planning');button.disabled=true;try{await api('/api/planning/confirm',{method:'POST',body:JSON.stringify(state.planPreview)});closePlanningDialog();await loadTasks({migrate:false});toast('今日时间表已确认')}catch(error){showError(error)}finally{button.disabled=false}}

function restoreFocus(){}
function focusElapsed(timer=state.focus){if(!timer)return 0;let elapsed=Number(timer.elapsed_seconds||0);if(timer.status==='running'&&timer.last_resumed_at)elapsed+=Math.max(0,(Date.now()-new Date(timer.last_resumed_at).getTime())/1000);return elapsed}
function focusClock(seconds){const value=Math.max(0,Math.floor(seconds));return `${pad(Math.floor(value/60))}:${pad(value%60)}`}
function focusTask(){return state.tasks.find(task=>task.id===state.focus?.task_id)}
function openFocus(taskId='',planBlockId=''){const panel=$('#focus-panel');panel.classList.remove('hidden');panel.dataset.preselected=taskId;panel.dataset.planBlock=planBlockId||'';renderFocusPanel()}
function closeFocus(){$('#focus-panel').classList.add('hidden')}
function clearFocus(){state.focus=null;state.focusWarningPlayed=false;document.title='研途 · 研究生个人工作台';renderFocusPanel()}
function focusTone(kind='done'){if(!state.preferences?.sound_enabled)return;try{const context=new AudioContext(),gain=context.createGain(),osc=context.createOscillator();gain.gain.value=(state.preferences.volume||60)/500;osc.frequency.value=kind==='warning'?660:kind==='break'?440:880;osc.connect(gain);gain.connect(context.destination);osc.start();gain.gain.exponentialRampToValueAtTime(.0001,context.currentTime+.45);osc.stop(context.currentTime+.46)}catch{}}
function focusNotify(title,body){if(state.preferences?.notification_enabled&&'Notification'in window&&Notification.permission==='granted'){try{new Notification(title,{body,icon:'/assets/logo-192.png'});return}catch{}}toast(`${title} · ${body}`)}
function renderFocusPanel(){
  const panel=$('#focus-panel');if(panel.classList.contains('hidden'))return;
  const activeTasks=state.tasks.filter(active).sort(sortTasks);
  if(!state.focus){const selected=panel.dataset.preselected||activeTasks[0]?.id||'',profile=state.planningProfile||{focus_minutes:25,short_break_minutes:5},stats=state.focusStats||{},todayMinutes=(stats.by_day||[]).find(item=>item.date===today())?.minutes||0;panel.innerHTML=`<div class="focus-head"><div><i></i><small>FOCUS DECK // READY</small><strong>专注工作台</strong></div><div class="focus-head-actions"><button id="focus-expand" aria-label="沉浸模式">${state.focusImmersive?'↙':'↗'}</button><button id="focus-close" aria-label="关闭专注面板">×</button></div></div><div class="focus-dashboard"><div class="focus-metrics"><div><strong>${todayMinutes}分</strong><span>今日专注</span></div><div><strong>${stats.focus_minutes||0}分</strong><span>近 7 天</span></div><div><strong>${stats.pomodoros||0}</strong><span>完成番茄</span></div><div><strong>${stats.plan_completion_rate||0}%</strong><span>规划完成率</span></div></div><div class="focus-setup"><label><span>关联任务</span><select id="focus-task">${activeTasks.map(task=>`<option value="${task.id}" ${task.id===selected?'selected':''}>${esc(task.title)}</option>`).join('')}</select></label><div class="focus-preset-row"><button type="button" data-focus-preset="25">25 / 5</button><button type="button" data-focus-preset="50">50 / 10</button><button type="button" data-focus-preset="${profile.focus_minutes}">规划偏好</button><button type="button" data-focus-preset="free">自由计时</button></div><label><span>本轮专注分钟</span><input id="focus-custom-minutes" type="number" min="1" max="720" value="${profile.focus_minutes}"></label><input type="hidden" id="focus-mode" value="pomodoro"><p>到时后等待你确认，再记录投入并进入休息。</p><button class="focus-primary" id="focus-start" ${activeTasks.length?'':'disabled'}>${activeTasks.length?'启动专注':'暂无可专注任务'}</button></div></div>`;bindFocusChrome();$$('[data-focus-preset]').forEach(button=>button.onclick=()=>{$$('#focus-panel [data-focus-preset]').forEach(item=>item.classList.remove('active'));button.classList.add('active');const value=button.dataset.focusPreset;$('#focus-mode').value=value==='free'?'free':'pomodoro';if(value!=='free')$('#focus-custom-minutes').value=value});$('#focus-start').onclick=startFocus;return}
  const elapsed=focusElapsed(),isBreak=state.focus.session_type!=='focus',target=Number(state.focus.target_seconds||0),remaining=state.focus.mode==='free'?elapsed:Math.max(0,target-elapsed),progress=state.focus.mode==='free'?0:Math.min(1,elapsed/Math.max(1,target)),task=focusTask(),awaiting=state.focus.status==='awaiting_action';
  const label=isBreak?'RECOVERY // BREAK':state.focus.mode==='free'?'FLOW // OPEN TIMER':'FOCUS // DEEP WORK';
  document.title=`${focusClock(remaining)} · ${isBreak?'休息':task?.title||'专注'}`;
  const finishLabel=isBreak?'结束休息':(!awaiting&&state.focus.mode==='pomodoro'&&elapsed<target?'提前结束并记录':'完成并记录');
  panel.innerHTML=`<div class="focus-head"><div><i class="${state.focus.status==='running'?'live':''}"></i><small>${label}</small><strong>${isBreak?(state.focus.session_type==='long_break'?'长休息':'短休息'):esc(task?.title||'专注任务')}</strong></div><div class="focus-head-actions"><button id="focus-expand" aria-label="沉浸模式">${state.focusImmersive?'↙':'↗'}</button><button id="focus-close" aria-label="收起专注面板">×</button></div></div><div class="focus-active"><div class="focus-phase-rail"><span class="done">准备</span><i></i><span class="current">${isBreak?'恢复':'专注'}</span><i></i><span>下一轮</span></div><div class="focus-orbit" style="--focus-progress:${progress*360}deg"><div><time>${focusClock(remaining)}</time><span>${awaiting?'等待确认':state.focus.status==='running'?(isBreak?'恢复中':'专注中'):'已暂停'}</span></div></div><p>${awaiting?(isBreak?'休息计时已结束，准备好后返回任务。':'本轮已到时，由你确认是否记入实际投入。'):isBreak?'离开屏幕、活动肩颈，让注意力真正恢复。':state.focus.mode==='free'?'自由计时不会强制打断当前心流。':`完成后将按偏好进入休息，本轮已暂停 ${state.focus.pause_count||0} 次。`}</p><div class="focus-actions"><button id="focus-pause" ${awaiting?'disabled':''}>${state.focus.status==='running'?'暂停':'继续'}</button><button class="focus-primary" id="focus-finish">${finishLabel}</button><button class="focus-ghost" id="focus-discard">放弃</button></div></div>`;
  bindFocusChrome();$('#focus-pause').onclick=toggleFocusPause;$('#focus-finish').onclick=finishFocus;$('#focus-discard').onclick=discardFocus;
}
function bindFocusChrome(){$('#focus-close').onclick=closeFocus;$('#focus-expand').onclick=()=>{state.focusImmersive=!state.focusImmersive;$('#focus-panel').classList.toggle('immersive',state.focusImmersive);renderFocusPanel()}}
async function startFocus(){const taskId=$('#focus-task').value,mode=$('#focus-mode').value,minutes=Math.max(1,Number($('#focus-custom-minutes').value)||25);if(!taskId)return;try{const data=await api('/api/focus/sessions',{method:'POST',body:JSON.stringify({task_id:taskId,plan_block_id:$('#focus-panel').dataset.planBlock||null,mode,target_seconds:mode==='free'?0:Math.round(minutes*60)})});state.focus=data.session;state.focusWarningPlayed=false;focusTone('start');renderFocusPanel();toast(mode==='free'?'自由专注已开始':`${minutes} 分钟番茄钟已开始`)}catch(error){showError(error)}}
async function toggleFocusPause(){if(!state.focus)return;try{const action=state.focus.status==='paused'?'resume':'pause',data=await api(`/api/focus/sessions/${state.focus.id}/${action}`,{method:'POST'});state.focus=data.session;renderFocusPanel()}catch(error){showError(error)}}
async function finishFocus(){if(!state.focus||state.focusSaving)return;state.focusSaving=true;const wasBreak=state.focus.session_type!=='focus';try{const data=await api(`/api/focus/sessions/${state.focus.id}/complete`,{method:'POST'});state.focus=data.next_session||null;focusTone(wasBreak?'done':'break');focusNotify(wasBreak?'休息结束':'本轮专注已记录',wasBreak?'准备好后开始下一轮。':state.focus?'现在进入恢复时间。':'实际投入已同步到任务。');await loadTasks({migrate:false});if(state.focus)openFocus();else renderFocusPanel()}catch(error){showError(error)}finally{state.focusSaving=false}}
async function discardFocus(){if(!state.focus||!confirm('放弃本次计时且不记录投入？'))return;try{await api(`/api/focus/sessions/${state.focus.id}/cancel`,{method:'POST',body:JSON.stringify({record_partial:false})});clearFocus();await loadTasks({migrate:false});toast('本次计时已放弃')}catch(error){showError(error)}}
async function tickFocus(){if(!state.focus||state.focusSaving)return;const elapsed=focusElapsed(),target=Number(state.focus.target_seconds||0),remaining=target-elapsed;if(state.focus.mode==='pomodoro'&&state.focus.status==='running'&&remaining<=60&&remaining>0&&!state.focusWarningPlayed){state.focusWarningPlayed=true;focusTone('warning');toast('还剩 1 分钟，准备收尾')}if(state.focus.mode==='pomodoro'&&state.focus.status==='running'&&remaining<=0&&!state.focus.expiry_checked){state.focus.expiry_checked=true;try{const data=await api('/api/focus/active');state.focus=data.session;focusTone('done');focusNotify(state.focus.session_type==='focus'?'专注时间到':'休息时间到','请回到 Yantu 确认下一步。')}catch(error){showError(error)}}renderFocusPanel()}

function clone(value){return JSON.parse(JSON.stringify(value))}
function hexRgb(hex){return [1,3,5].map(index=>parseInt(hex.slice(index,index+2),16))}
function luminance(rgb){const c=rgb.map(value=>{const n=value/255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4});return .2126*c[0]+.7152*c[1]+.0722*c[2]}
function contrast(a,b){const [high,low]=[luminance(a),luminance(b)].sort((x,y)=>y-x);return (high+.05)/(low+.05)}
function mixed(surface,background,alpha){return surface.map((value,index)=>Math.round(value*alpha+background[index]*(1-alpha)))}
function resolveMode(mode){return mode==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):mode}
function safeSurface(palette,stats,requested){
  const surface=hexRgb(palette.surface),candidates=(stats?[stats.min,stats.avg,stats.max]:[luminance(hexRgb(palette.canvas))]).map(value=>[value*255,value*255,value*255]);
  let alpha=Math.max(.84,Math.min(.98,Number(requested)||.92)),bestText=hexRgb(palette.text),ratio=0;
  for(;alpha<=.981;alpha+=.01){ratio=Math.min(...candidates.map(bg=>contrast(bestText,mixed(surface,bg,alpha))));if(ratio>=4.5)break}
  if(ratio<4.5){const choices=[[20,27,24],[248,250,249]];bestText=choices.sort((a,b)=>Math.min(...candidates.map(bg=>contrast(b,mixed(surface,bg,.98))))-Math.min(...candidates.map(bg=>contrast(a,mixed(surface,bg,.98)))))[0];alpha=.98;ratio=Math.min(...candidates.map(bg=>contrast(bestText,mixed(surface,bg,alpha))));}
  return {alpha:Math.min(.98,alpha),text:`#${bestText.map(v=>Math.round(v).toString(16).padStart(2,'0')).join('')}`,ratio};
}
function backgroundCss(settings,imageUrl){const bg=settings.background;if(bg.type==='solid')return bg.color;if(bg.type==='gradient')return `linear-gradient(${bg.gradient_angle}deg,${bg.gradient_start},${bg.gradient_end})`;if(bg.type==='image'&&imageUrl)return `linear-gradient(rgba(0,0,0,.02),rgba(0,0,0,.02)),url("${imageUrl}")`;return 'none'}
function colorStatsForSettings(settings){const bg=settings.background;if(bg.type==='solid'){const l=luminance(hexRgb(bg.color));return {min:l,avg:l,max:l}}if(bg.type==='gradient'){const a=luminance(hexRgb(bg.gradient_start)),b=luminance(hexRgb(bg.gradient_end));return {min:Math.min(a,b),avg:(a+b)/2,max:Math.max(a,b)}}return null}
function sampleImage(source){return new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>{try{const canvas=document.createElement('canvas');canvas.width=48;canvas.height=48;const context=canvas.getContext('2d',{willReadFrequently:true});context.drawImage(image,0,0,48,48);const pixels=context.getImageData(0,0,48,48).data,values=[];for(let i=0;i<pixels.length;i+=16){if(pixels[i+3]<32)continue;values.push(luminance([pixels[i],pixels[i+1],pixels[i+2]]))}if(!values.length)throw new Error('图片没有可见像素');resolve({min:Math.min(...values),max:Math.max(...values),avg:values.reduce((a,b)=>a+b,0)/values.length})}catch(error){reject(error)}};image.onerror=()=>reject(new Error('背景图片无法读取'));image.src=source})}
async function applyAppearance(settings,{file=null,cache=false}={}){
  const resolved=resolveMode(settings.mode),palette=THEME_PALETTES[settings.preset]?.[resolved]||THEME_PALETTES.forest[resolved];
  let imageUrl=settings.background_url,stats=colorStatsForSettings(settings);
  if(file){if(!state.appearancePreviewUrl)state.appearancePreviewUrl=URL.createObjectURL(file);imageUrl=state.appearancePreviewUrl}
  if(settings.background.type==='image'&&imageUrl){try{stats=await sampleImage(imageUrl)}catch(error){imageUrl=null;stats=null;if(!file)console.warn('背景图片回退到研林主题',error)}}
  const readable=safeSurface(palette,stats,settings.surface_opacity),root=document.documentElement;
  const values={'--canvas':palette.canvas,'--surface-rgb':hexRgb(palette.surface).join(', '),'--surface-strong-rgb':hexRgb(palette.strong).join(', '),'--surface-alpha':readable.alpha,'--text-primary':readable.text,'--text-secondary':palette.muted,'--border':palette.border,'--accent':palette.accent,'--accent-soft':palette.soft,'--app-background':backgroundCss(settings,imageUrl)};
  Object.entries(values).forEach(([name,value])=>root.style.setProperty(name,value));root.dataset.theme=resolved;root.dataset.preset=settings.preset;
  $('#theme-color')?.setAttribute('content',settings.background.type==='solid'?settings.background.color:palette.canvas);
  if($('#contrast-note'))$('#contrast-note').textContent=`正文与面板最低对比度 ${readable.ratio.toFixed(2)}:1 · ${readable.ratio>=4.5?'符合 WCAG AA':'已启用最强可读遮罩'}`;
  if(cache){localStorage.setItem('yantu.appearance.cache.v1',JSON.stringify({...settings,resolved_mode:resolved}))}
}
async function loadAppearance(){const data=await api('/api/appearance');state.appearance=data.appearance;await applyAppearance(state.appearance,{cache:true})}
function fillAppearanceForm(settings){
  $(`input[name="appearance-mode"][value="${settings.mode}"]`).checked=true;$(`input[name="appearance-preset"][value="${settings.preset}"]`).checked=true;
  $('#appearance-background-type').value=settings.background.type;$('#appearance-color').value=settings.background.color;$('#appearance-gradient-start').value=settings.background.gradient_start;$('#appearance-gradient-end').value=settings.background.gradient_end;$('#appearance-gradient-angle').value=settings.background.gradient_angle;$('#appearance-opacity').value=settings.surface_opacity;updateAppearanceFields();
}
function readAppearanceForm(){return {version:1,preset:$('input[name="appearance-preset"]:checked').value,mode:$('input[name="appearance-mode"]:checked').value,background:{type:$('#appearance-background-type').value,color:$('#appearance-color').value,gradient_start:$('#appearance-gradient-start').value,gradient_end:$('#appearance-gradient-end').value,gradient_angle:Number($('#appearance-gradient-angle').value)},surface_opacity:Number($('#appearance-opacity').value),has_background_image:state.appearance.has_background_image,background_url:state.appearance.background_url}}
function updateAppearanceFields(){const type=$('#appearance-background-type').value;$('#appearance-solid').classList.toggle('hidden',type!=='solid');$('#appearance-gradient').classList.toggle('hidden',type!=='gradient');$('#appearance-image').classList.toggle('hidden',type!=='image');$('#appearance-angle-output').textContent=`${$('#appearance-gradient-angle').value}°`;$('#appearance-opacity-output').textContent=`${Math.round(Number($('#appearance-opacity').value)*100)}%`;$('#remove-background').classList.toggle('hidden',!state.appearance.has_background_image||state.appearanceRemoveImage)}
async function previewAppearance(){updateAppearanceFields();state.appearanceDraft=readAppearanceForm();await applyAppearance(state.appearanceDraft,{file:state.appearanceImageFile})}
function clearAppearancePreview(){if(state.appearancePreviewUrl)URL.revokeObjectURL(state.appearancePreviewUrl);state.appearancePreviewUrl=null}
function openAppearance(){clearAppearancePreview();state.appearanceDraft=clone(state.appearance);state.appearanceImageFile=null;state.appearanceRemoveImage=false;fillAppearanceForm(state.appearanceDraft);$('#appearance-dialog').showModal();previewAppearance()}
async function cancelAppearance(){clearAppearancePreview();state.appearanceImageFile=null;state.appearanceRemoveImage=false;$('#appearance-dialog').close();await applyAppearance(state.appearance,{cache:true})}
async function saveAppearance(event){event.preventDefault();try{let settings=readAppearanceForm();if(state.appearanceRemoveImage)await api('/api/appearance/background',{method:'DELETE'});if(state.appearanceImageFile){const form=new FormData();form.append('file',state.appearanceImageFile);const uploaded=await api('/api/appearance/background',{method:'POST',body:form});settings.background.type='image';settings.background_url=uploaded.appearance.background_url;settings.has_background_image=true}const saved=await api('/api/appearance',{method:'PUT',body:JSON.stringify(settings)});state.appearance=saved.appearance;clearAppearancePreview();state.appearanceImageFile=null;state.appearanceRemoveImage=false;await applyAppearance(state.appearance,{cache:true});$('#appearance-dialog').close();toast('外观设置已保存')}catch(error){showError(error)}}

$('#task-form').onsubmit=async event=>{event.preventDefault();try{const id=$('#task-id').value;if(id)await patchTask(id,formPayload());else await createTask(formPayload());closeDialog();toast(id?'任务已更新':'任务已创建')}catch(error){showError(error)}};
$('#delete-btn').onclick=async()=>{const id=$('#task-id').value;if(!id)return;try{closeDialog();await trashTask(id)}catch(error){showError(error)}};
$('#add-btn').onclick=()=>openDialog();
$('#focus-btn').onclick=()=>openFocus();
$('#settings-btn').onclick=()=>openSettings();
$('#close-settings').onclick=closeSettings;$('#cancel-settings').onclick=closeSettings;$('#settings-form').onsubmit=savePreferences;
$$('[data-settings-tab]').forEach(button=>button.onclick=()=>selectSettingsTab(button.dataset.settingsTab));
$('#setting-volume').oninput=event=>{$('#setting-volume-output').textContent=`${event.target.value}%`};
$('#toggle-ai-key').onclick=()=>{const input=$('#ai-api-key'),show=input.type==='password';input.type=show?'text':'password';$('#toggle-ai-key').textContent=show?'隐藏':'显示'};
$('#save-ai-settings').onclick=saveAiSettings;$('#test-ai-key').onclick=testAiSettings;$('#delete-ai-key').onclick=deleteAiKey;
$('#open-planning-settings').onclick=()=>{closeSettings();openPlanningDialog()};
$('#close-dialog').onclick=closeDialog;
$('#cancel-btn').onclick=closeDialog;
$('#task-recurring').onchange=event=>{$('#task-recurrence').disabled=!event.target.checked};
$('#task-status').onchange=event=>{if(event.target.value==='completed')$('#task-progress').value=100};
$$('.nav-item').forEach(button=>button.onclick=async()=>{state.view=button.dataset.view;$('.sidebar').classList.remove('open');if(state.view==='trash')try{state.trash=await api('/api/trash')}catch(error){showError(error)}render()});
$('#status-filter').onchange=event=>{state.status=event.target.value;render()};
$('#subcategory-filter').onchange=event=>{state.subcategory=event.target.value;render()};
$('#menu-btn').onclick=()=>$('.sidebar').classList.toggle('open');
$('#export-btn').onclick=async()=>{try{const data=await api('/api/export');const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const anchor=document.createElement('a');anchor.href=URL.createObjectURL(blob);anchor.download=`Yantu备份-${today()}.json`;anchor.click();URL.revokeObjectURL(anchor.href);toast('备份已导出')}catch(error){showError(error)}};
$('#import-file').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;const data=JSON.parse(await file.text());if(!Array.isArray(data.tasks))throw new Error('备份文件中没有任务列表');if(!confirm(`将合并导入 ${data.tasks.length} 个任务，是否继续？`))return;await api('/api/import',{method:'POST',body:JSON.stringify(data)});await loadTasks({migrate:false});toast('备份已导入')}catch(error){showError(error)}finally{event.target.value=''}};

$('#schedule-form').onsubmit=async event=>{event.preventDefault();const file=$('#schedule-file').files[0];if(!file)return;const form=new FormData();form.append('file',file);form.append('config',JSON.stringify({semester:{name:$('#semester-name').value.trim(),start_date:$('#semester-start').value,end_date:$('#semester-end').value}}));const button=$('#recognize-schedule');button.disabled=true;button.textContent='正在本地识别…';try{const data=await api('/api/schedule-import/preview',{method:'POST',body:form});state.schedulePreview=data.preview;renderSchedulePreview()}catch(error){showError(error)}finally{button.disabled=false;button.textContent='识别并预览'}};
$('#close-schedule-dialog').onclick=()=>$('#schedule-dialog').close();$('#cancel-schedule').onclick=()=>$('#schedule-dialog').close();
$('#course-form').onsubmit=async event=>{event.preventDefault();const id=$('#course-id').value;try{await api(`/api/courses/${id}`,{method:'PUT',body:JSON.stringify({name:$('#course-name').value.trim(),teacher:$('#course-teacher').value.trim(),location:$('#course-location').value.trim(),notes:$('#course-notes').value.trim(),meetings:[{weekday:Number($('#course-weekday').value),start_period:Number($('#course-start-period').value),end_period:Number($('#course-end-period').value),start_time:$('#course-start-time').value,end_time:$('#course-end-time').value,start_week:Number($('#course-start-week').value),end_week:Number($('#course-end-week').value),week_pattern:$('#course-week-pattern').value,custom_weeks:[]}]})});$('#course-dialog').close();await loadTasks({migrate:false});toast('课程已更新')}catch(error){showError(error)}};
$('#close-course-dialog').onclick=()=>$('#course-dialog').close();$('#cancel-course').onclick=()=>$('#course-dialog').close();
$('#planning-form').onsubmit=confirmPlanning;$('#preview-planning').onclick=previewPlanning;$('#close-planning').onclick=closePlanningDialog;$('#cancel-planning').onclick=closePlanningDialog;
$('#appearance-btn').onclick=()=>{closeSettings();openAppearance()};$('#close-appearance').onclick=cancelAppearance;$('#cancel-appearance').onclick=cancelAppearance;$('#appearance-form').onsubmit=saveAppearance;
$$('#appearance-form input[name="appearance-mode"],#appearance-form input[name="appearance-preset"],#appearance-form input[type="color"],#appearance-form input[type="range"],#appearance-background-type').forEach(control=>{control.oninput=()=>previewAppearance().catch(showError);control.onchange=()=>previewAppearance().catch(showError)});
$('#appearance-image-file').onchange=event=>{const file=event.target.files[0];if(!file)return;if(file.size>8*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){event.target.value='';return showError(new Error('请选择不超过 8 MB 的 PNG、JPG 或 WebP 图片'))}clearAppearancePreview();state.appearanceImageFile=file;state.appearanceRemoveImage=false;$('#appearance-background-type').value='image';previewAppearance().catch(showError)};
$('#remove-background').onclick=()=>{state.appearanceRemoveImage=true;state.appearanceImageFile=null;$('#appearance-image-file').value='';$('#appearance-background-type').value='none';previewAppearance().catch(showError)};
$('#reset-appearance').onclick=()=>{if(!confirm('恢复默认外观？保存前仍可取消。'))return;clearAppearancePreview();state.appearanceDraft=clone(APPEARANCE_DEFAULT);state.appearanceImageFile=null;state.appearanceRemoveImage=state.appearance.has_background_image;fillAppearanceForm(state.appearanceDraft);previewAppearance().catch(showError)};
const systemTheme=matchMedia('(prefers-color-scheme: dark)');systemTheme.addEventListener?.('change',()=>{if(state.appearance.mode==='system'&&!$('#appearance-dialog').open)applyAppearance(state.appearance,{cache:true});else if(state.appearanceDraft?.mode==='system')previewAppearance()});
document.addEventListener('click',event=>{if(!event.target.closest('#context-menu')&&!event.target.closest('[data-task-menu]')&&!event.target.closest('[data-course-menu]'))closeContextMenu()});
document.addEventListener('keydown',event=>{const menu=$('#context-menu'),typing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);if(event.key==='Escape'){closeContextMenu();if(!$('#focus-panel').classList.contains('hidden'))closeFocus()}if(!typing&&!$('#focus-panel').classList.contains('hidden')&&state.focus){if(event.code==='Space'&&!['awaiting_action','completed','cancelled'].includes(state.focus.status)){event.preventDefault();toggleFocusPause()}if(event.key==='Enter'){event.preventDefault();finishFocus()}}if(!menu.classList.contains('hidden')&&['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement),step=event.key==='ArrowDown'?1:-1;buttons[(index+step+buttons.length)%buttons.length]?.focus()}});
window.addEventListener('scroll',closeContextMenu,true);window.addEventListener('resize',closeContextMenu);

restoreFocus();setInterval(()=>tickFocus().catch(showError),1000);
loadAppearance().catch(error=>{console.warn('外观设置加载失败，使用研林主题',error);state.appearance=clone(APPEARANCE_DEFAULT);applyAppearance(state.appearance,{cache:true})});
loadTasks().catch(error=>{state.loading=false;$('#content').innerHTML=`<div class="empty error"><strong>无法连接 Yantu 后端</strong>${esc(error.message)}<br>请保留启动窗口并查看其中的错误信息。</div>`;showError(error)});
