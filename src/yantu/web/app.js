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
let savedFocusDraft={};try{savedFocusDraft=JSON.parse(localStorage.getItem('yantu.focus.draft.v1')||'{}')||{}}catch{}
let state={view:'today',status:'all',subcategory:'all',month:new Date(),tasks:[],projects:[],events:[],courses:[],semesters:[],trash:{tasks:[],courses:[]},dailyPlan:{},dailyProjection:null,planningProfile:null,planBlocks:[],planState:null,planPreview:null,scheduleWeek:new Date(),semesterFilter:'',schedulePreview:null,loading:true,aiStatus:null,aiPreview:null,aiLoading:false,aiSettings:null,preferences:null,zoteroSources:[],researchInbox:[],researchAllItems:[],researchProjectId:'',researchProjectItems:[],researchFolders:[],researchFolderId:'',zoteroCollections:[],researchImportPreview:null,researchTaskPreview:null,appearance:structuredClone(APPEARANCE_DEFAULT),appearanceDraft:null,appearanceImageFile:null,appearancePreviewUrl:null,appearanceRemoveImage:false,focus:null,focusStats:null,focusSaving:false,focusImmersive:false,focusWarningPlayed:false,focusHabits:[],focusHabitCapability:null,focusHabitStats:null,focusHabitResult:null,focusHabitLastRefresh:0,focusAnalytics:null,focusAnalyticsRange:'28',focusAnalyticsStart:'',focusAnalyticsEnd:'',focusDraft:{taskId:String(savedFocusDraft.taskId||''),planBlockId:'',preset:['planning','25','50','custom','free'].includes(savedFocusDraft.preset)?savedFocusDraft.preset:'planning',mode:savedFocusDraft.mode==='free'?'free':'pomodoro',minutes:savedFocusDraft.minutes?Math.max(1,Math.min(720,Number(savedFocusDraft.minutes))):null,habitProfileId:String(savedFocusDraft.habitProfileId||'__default__')}};

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
function taskDeadline(task){const value=task?.deadline||task?.due_date;if(!value)return null;const key=String(value).slice(0,10);return /^\d{4}-\d{2}-\d{2}$/.test(key)?key:null}
function currentSemester(){const key=today(),active=state.semesters.find(item=>item.start_date<=key&&item.end_date>=key);if(active)return active;return [...state.semesters].sort((a,b)=>Math.abs(parseDate(a.start_date)-new Date())-Math.abs(parseDate(b.start_date)-new Date()))[0]||null}
function isOverdue(task){const deadline=taskDeadline(task);return ACTIVE_STATUSES.has(task.status)&&Boolean(deadline&&deadline<today())}
function active(task){return ACTIVE_STATUSES.has(task.status)}
function matchesFilters(task){return (state.status==='all'||task.status===state.status)&&(state.subcategory==='all'||task.subcategory===state.subcategory)}
function viewTasks(){let tasks=state.tasks.filter(matchesFilters);if(['research','course','personal','inbox'].includes(state.view))tasks=tasks.filter(task=>task.domain===state.view);if(state.view==='free_learning')tasks=tasks.filter(task=>task.task_kind==='free_learning');return tasks}
function sortTasks(a,b){const aDeadline=taskDeadline(a),bDeadline=taskDeadline(b);return Number(['completed','cancelled'].includes(a.status))-Number(['completed','cancelled'].includes(b.status))||({urgent:0,high:1,medium:2,low:3}[a.priority]-{urgent:0,high:1,medium:2,low:3}[b.priority])||Number(!aDeadline)-Number(!bDeadline)||(aDeadline||'9999').localeCompare(bDeadline||'9999')||a.title.localeCompare(b.title,'zh-CN')}

async function loadTasks({migrate=true}={}){
  const rangeStart=iso(addDays(new Date(),-180)),rangeEnd=iso(addDays(new Date(),180));
  const [data,projectData,semesterData,courseData,eventData,planData,profileData,confirmedPlan,focusData,statsData,preferencesData,aiSettingsData,zoteroData,researchData,habitData,habitCapabilityData,draftData]=await Promise.all([api('/api/tasks'),api('/api/projects'),api('/api/semesters'),api('/api/courses'),api(`/api/calendar/events?start=${rangeStart}&end=${rangeEnd}`),api(`/api/planning/daily?date=${today()}`),api('/api/planning/profile'),api(`/api/planning/plans?date=${today()}`),api('/api/focus/active'),api(`/api/focus/stats?start=${iso(addDays(new Date(),-6))}&end=${today()}`),api('/api/settings/preferences'),api('/api/settings/ai'),api('/api/research/sources'),api('/api/research/inbox'),api('/api/focus/habits'),api('/api/focus/habits/capability'),api('/api/settings/focus-draft')]);
  state.tasks=data.tasks;
  state.projects=projectData.projects;
  state.semesters=semesterData.semesters;state.courses=courseData.courses;state.events=eventData.events;
  state.dailyPlan=Object.fromEntries(planData.allocations.map(item=>[item.task_id,item]));
  state.dailyProjection=planData;state.planningProfile=profileData.profile;state.planBlocks=confirmedPlan.blocks;state.planState=confirmedPlan.plan_state;
  state.focus=focusData.session;state.focusStats=statsData.stats;state.preferences=preferencesData.preferences;state.aiSettings=aiSettingsData.ai;
  state.focusHabits=habitData.profiles;state.focusHabitCapability=habitCapabilityData.capability;
  if(migrate){
    let draft=draftData.draft;
    if(!draft&&Object.keys(savedFocusDraft).length){draft=(await api('/api/settings/focus-draft',{method:'PUT',body:JSON.stringify(state.focusDraft)})).draft}
    if(draft)state.focusDraft={...state.focusDraft,...draft,planBlockId:''};
    if(draft)localStorage.removeItem('yantu.focus.draft.v1');
  }
  try{state.focusHabitStats=(await api(`/api/focus/habits/stats?start=${iso(addDays(new Date(),-27))}&end=${today()}`)).stats}catch{state.focusHabitStats=null}
  state.zoteroSources=zoteroData.sources;state.researchInbox=researchData.items;
  const researchProjects=state.projects.filter(project=>project.category==='科研');
  if(!researchProjects.some(project=>project.id===state.researchProjectId))state.researchProjectId=researchProjects[0]?.id||'';
  await refreshProjectPapers(state.researchProjectId);
  state.researchAllItems=(await api('/api/research/items')).items;
  try{state.aiStatus=await api('/api/ai/status')}catch(error){state.aiStatus={configured:false,error:error.message}}
  if(migrate&&state.tasks.length===0)await migrateLegacyTasks();
  if(state.view==='focus_analytics')await loadFocusAnalytics(false);
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
  else if(state.view==='focus_analytics')content.innerHTML=renderFocusAnalytics();
  else if(state.view==='research_library')content.innerHTML=renderResearchLibrary();
  else if(state.view==='free_learning')content.innerHTML=renderFreeLearning();
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
  const titles={today:'今日',inbox:'收件箱',research:'科研工作台',course:'课程学习',personal:'个人生活',free_learning:'自由学习',week:'未来 7 天',month:'月历',schedule:'课程表',research_library:'科研文献',focus_analytics:'专注分析',trash:'回收站'};
  $('#view-title').textContent=titles[state.view]||'AI 任务拆解';
  const now=new Date();
  $('#date-label').textContent=`${now.getFullYear()}年${now.getMonth()+1}月${now.getDate()}日 · ${['星期日','星期一','星期二','星期三','星期四','星期五','星期六'][now.getDay()]}`;
  const semester=currentSemester(),indicator=$('#semester-indicator');indicator.classList.toggle('hidden',!semester);if(semester)indicator.innerHTML=`<b>${esc(semester.stage_label||semester.name)}</b><span>第 1 周 ${esc(semester.start_date.slice(5))} · 可修改</span>`;
  $$('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.view===state.view));
  for(const domain of ['research','course','personal','inbox']){
    const count=state.tasks.filter(task=>task.domain===domain&&active(task)).length;
    $(`#count-${domain}`).textContent=count;
  }
  $('#count-free-learning').textContent=state.tasks.filter(task=>task.task_kind==='free_learning'&&active(task)).length;
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
  const must=tasks.filter(task=>active(task)&&taskDeadline(task)===today()&&['urgent','high'].includes(task.priority)).sort(sortTasks);
  const mustIds=new Set(must.map(task=>task.id));
  const planned=tasks.filter(task=>active(task)&&state.dailyPlan[task.id]&&!mustIds.has(task.id)&&!isOverdue(task)).sort(sortTasks);
  const overdue=tasks.filter(isOverdue).sort(sortTasks);
  const upcoming=tasks.filter(task=>{const deadline=taskDeadline(task);return active(task)&&deadline&&deadline>today()}).sort(sortTasks).slice(0,8);
  const todayTasks=[...must,...planned];
  const estimate=todayTasks.reduce((sum,task)=>sum+(Number(state.dailyPlan[task.id]?.planned_minutes)||0),0);
  const finished=tasks.filter(task=>task.status==='completed'&&task.completed_at&&iso(new Date(task.completed_at))===today()).length;
  const inbox=state.tasks.filter(task=>task.domain==='inbox'&&active(task)).sort(sortTasks).slice(0,5);
  const classes=state.events.filter(event=>event.date===today());
  return `<form class="quick-capture compact" id="quick-form"><div><strong>快速收件箱</strong><span>先记下导师临时任务或突然出现的想法，稍后再整理。</span></div><input id="quick-title" maxlength="160" required placeholder="刚想到什么？"><button class="primary-btn" type="submit">记下来</button></form>${renderActiveFocusBanner()}<div class="summary-grid">
    <div class="summary-card hero"><p>今日工作面</p><strong>${todayTasks.length}</strong><span>${must.length} 项必须完成 · ${planned.length} 项计划推进</span></div>
    <div class="summary-card"><p>今日建议投入</p><strong>${fmtDuration(estimate)}</strong><span>按剩余日期分摊，专注记录会自动扣减</span></div>
    <div class="summary-card"><p>今日已完成</p><strong>${finished}</strong><span>${overdue.length?`仍有 ${overdue.length} 项逾期`:'当前没有逾期任务'}</span></div>
  </div>
  ${renderPlanningTimeline()}
  ${eventSection('今日时间段',classes,'今天没有固定时间安排。')}
  ${listSection('今天必须完成',must,'没有必须今天完成的高优先级任务。',true)}
  ${listSection('今天计划推进',planned,'尚未安排今天的任务。',true)}
  ${listSection('已逾期任务',overdue,'很好，目前没有逾期任务。')}
  ${listSection('最近截止任务',upcoming,'近期没有明确 Deadline。')}
  ${listSection('收件箱待整理',inbox,'收件箱已经清空。')}`;
}

function renderPlanningTimeline(){
  const blocks=state.planBlocks||[];
  const stale=state.planState?.needs_refresh;
  const head=`<div class="section-head planning-head"><div><h2>今日时间轴</h2><p>${stale?'任务进度或日期已变化，建议重新生成时间表':'任务、课程占用与恢复节奏分开呈现'}</p></div><button class="secondary-btn ${stale?'plan-refresh-needed':''}" id="open-planning">${blocks.length?'重新规划':'安排今日'}</button></div>`;
  if(!blocks.length)return `${head}<div class="planning-empty"><span>⌁</span><div><strong>还没有确认的时间表</strong><p>先生成预览，再决定是否采用；不会直接覆盖任务。</p></div></div>`;
  return `${head}<div class="day-plan">${blocks.map(block=>{const task=state.tasks.find(item=>item.id===block.task_id);const labels={focus:task?.title||block.task_title||'专注任务',short_break:'短暂恢复',long_break:'长休息',buffer:'切换缓冲'};return `<article class="plan-block ${block.block_type}"><time>${esc(block.start_time)}<i></i>${esc(block.end_time)}</time><div><strong>${esc(labels[block.block_type]||block.block_type)}</strong><p>${esc(block.rationale||'')}</p></div>${block.block_type==='focus'?`<button class="more-btn" data-plan-focus="${block.task_id}" data-plan-block="${block.id||''}">开始专注</button>`:'<span class="plan-rest">REST</span>'}</article>`}).join('')}</div>`;
}

let temporalDate=today();
let temporalRefreshing=false;
async function refreshTemporalViews(){
  if(temporalRefreshing||document.hidden||state.loading)return;
  const currentDate=today();
  if(currentDate!==temporalDate){temporalDate=currentDate;await loadTasks({migrate:false});return}
  temporalRefreshing=true;
  try{
    const [planData,confirmedPlan,focusData]=await Promise.all([
      api(`/api/planning/daily?date=${currentDate}`),
      api(`/api/planning/plans?date=${currentDate}`),
      api('/api/focus/active')
    ]);
    state.dailyProjection=planData;
    state.dailyPlan=Object.fromEntries(planData.allocations.map(item=>[item.task_id,item]));
    state.planBlocks=confirmedPlan.blocks;state.planState=confirmedPlan.plan_state;
    state.focus=focusData.session;
    if(state.view==='today')render();
  }finally{temporalRefreshing=false}
}

function renderInbox(){
  const tasks=viewTasks().sort(sortTasks);
  return `<form class="quick-capture" id="quick-form"><div><strong>先记下来，稍后再整理</strong><span>导师临时安排、突然想到的实验点子，都可以先放进收件箱。</span></div><input id="quick-title" maxlength="160" required placeholder="快速记录一个任务…"><button class="primary-btn" type="submit">加入收件箱</button></form>${listSection('待整理',tasks,'收件箱已经清空。')}`;
}

function renderFreeLearning(){
  const tasks=viewTasks().sort(sortTasks),ongoing=tasks.filter(active);
  const recorded=tasks.reduce((sum,task)=>sum+Number(task.actual_minutes||0),0);
  return `<div class="domain-intro research"><div><p>自由学习</p><h2>随时继续，不受截止日期驱动</h2></div><div><strong>${ongoing.length}</strong><span>可继续的学习任务</span></div><div><strong>${recorded?fmtDuration(recorded):'0 分钟'}</strong><span>累计记录投入</span></div></div>${listSection('自由学习任务',tasks,'新建任务时选择“自由学习”，或从科研文献快速开始。')}`;
}

function renderDomain(domain){
  const tasks=viewTasks().sort(sortTasks);
  const activeCount=tasks.filter(active).length;
  const minutes=tasks.filter(task=>active(task)&&task.task_kind!=='free_learning').reduce((sum,task)=>sum+(Number(task.estimated_minutes)||0),0);
  return `<div class="domain-intro ${domain}"><div><p>${DOMAINS[domain]}领域</p><h2>${domain==='research'?'推进研究，而不只是响应任务':domain==='course'?'让课程投入可见、可控':'生活是长期科研的底盘'}</h2></div><div><strong>${activeCount}</strong><span>进行中的任务</span></div><div><strong>${fmtDuration(minutes)}</strong><span>剩余预计投入</span></div></div>${listSection(`${DOMAINS[domain]}任务`,tasks,`还没有${DOMAINS[domain]}任务。`)}`;
}

function listSection(title,tasks,emptyText='暂无任务',showDailyAllocation=false){
  return `<div class="section-head"><h2>${title}</h2><span>${tasks.length} 项</span></div>${tasks.length?`<div class="task-list">${tasks.map(task=>taskCard(task,showDailyAllocation?state.dailyPlan[task.id]:null)).join('')}</div>`:`<div class="empty"><strong>这里暂时是空的</strong>${emptyText}</div>`}`;
}

function taskCard(task,dailyAllocation=null){
  const done=task.status==='completed';
  const focus=activeFocusForTask(task),displayProgress=taskDisplayProgress(task),deadline=taskDeadline(task),overdue=isOverdue(task);
  const free=task.task_kind==='free_learning',timed=task.schedule_mode==='time_block';
  const meta=timed?[DOMAINS[task.domain],task.subcategory,`${fmtDate(task.scheduled_date)} ${task.scheduled_start_time||''}–${task.scheduled_end_time||''}`,task.is_recurring?`每周重复至 ${fmtDate(task.recurrence_until)}`:'单次占用'].filter(Boolean).join(' · '):free?[DOMAINS[task.domain],task.subcategory,'自由学习',`已投入 ${task.actual_minutes?fmtDuration(task.actual_minutes):'0 分钟'}`,`当前时长上限 ${fmtDuration(task.estimated_minutes)}`].filter(Boolean).join(' · '):[DOMAINS[task.domain],task.subcategory,deadline?`截止 ${fmtDate(deadline)}`:'无 Deadline',fmtDuration(task.estimated_minutes),dailyAllocation?`今日建议 ${fmtDuration(dailyAllocation.planned_minutes)}`:''].filter(Boolean).join(' · ');
  return `<article class="task-card ${task.domain} ${done?'done':''} ${focus?'focus-running':''} ${isOverdue(task)?'overdue':''}" data-task-context="${task.id}">
    <input class="check" type="checkbox" aria-label="标记完成" data-check="${task.id}" ${done?'checked':''} ${task.status==='cancelled'?'disabled':''}>
    <div class="task-main"><div class="task-title-row"><h3>${esc(task.title)}</h3><span class="status-badge ${task.status}">${STATUSES[task.status]}</span>${overdue?'<span class="status-badge overdue">已过期</span>':''}${free?'<span class="badge">自由学习</span>':''}${timed?'<span class="badge time-block">时间段</span>':''}${task.is_recurring?'<span class="badge">重复</span>':''}</div><p>${esc(meta)}</p>${focus?`<div class="task-focus-live" data-focus-task-live="${task.id}"><span><i></i>${focus.status==='paused'?'专注已暂停':'正在专注'}</span><time>${focusClock(focusElapsed(focus))}</time><b>${free?'持续投入':`${displayProgress}%`}</b></div>`:''}${task.description?`<p class="description">${esc(task.description)}</p>`:''}${task.tags?.length?`<div class="tag-row">${task.tags.map(tag=>`<span>#${esc(tag)}</span>`).join('')}</div>`:''}<div class="progress-track" data-task-progress="${task.id}" title="${free?'完成度由你手动记录':`完成度 ${displayProgress}%`}"><i style="width:${displayProgress}%"></i></div></div>
    <div class="task-controls"><select data-priority="${task.id}" aria-label="修改优先级" class="priority-select ${task.priority}">${Object.entries(PRIORITIES).map(([key,label])=>`<option value="${key}" ${key===task.priority?'selected':''}>${label}优先级</option>`).join('')}</select>${timed?'<span class="free-learning-cadence">固定占用</span>':free?'<span class="free-learning-cadence">随时开始</span>':`<input type="date" data-due="${task.id}" value="${deadline||''}" aria-label="修改截止日期">`}<button class="edit-btn" data-edit="${task.id}" aria-label="编辑任务">编辑</button><button class="more-btn" data-task-menu="${task.id}" aria-label="任务快捷操作">⋯</button></div>
  </article>`;
}

function activeFocusForTask(task){const focus=state.focus;return focus&&focus.session_type==='focus'&&focus.task_id===task.id&&['running','paused','awaiting_action'].includes(focus.status)?focus:null}
function taskDisplayProgress(task){if(task.task_kind==='free_learning')return Number(task.progress)||0;const focus=activeFocusForTask(task),estimated=Math.max(0,Number(task.estimated_minutes)||0),recorded=Math.max(0,Number(task.actual_minutes)||0),live=focus?focusElapsed(focus)/60:0,measured=estimated?Math.min(99,Math.floor((recorded+live)*100/estimated)):0;return Math.max(Number(task.progress)||0,measured)}
function focusBannerMetrics(task,focus){
  const elapsed=focusElapsed(focus),target=Number(focus.target_seconds||0),remaining=focus.mode==='free'?null:Math.max(0,target-elapsed);
  if(task.task_kind==='free_learning'){
    const accumulated=Math.round(Number(task.actual_minutes||0)+elapsed/60);
    return `本轮 ${focusClock(elapsed)}${remaining===null?' · 自由计时':` · 当前时段剩余 ${focusClock(remaining)}`} · 累计学习 <b>${accumulated?fmtDuration(accumulated):'0 分钟'}</b>`;
  }
  return `已专注 ${focusClock(elapsed)}${remaining===null?' · 自由计时':` · 剩余 ${focusClock(remaining)}`} · 预计完成度 <b>${taskDisplayProgress(task)}%</b>`;
}
function renderActiveFocusBanner(){
  const focus=state.focus;if(!focus||focus.session_type!=='focus')return '';
  const task=focusTask();if(!task)return '';
  return `<section class="active-focus-banner" data-active-focus-banner><div class="active-focus-signal"><i></i><span>ACTIVE FOCUS</span></div><div><small>${focus.status==='paused'?'本轮已暂停':focus.status==='awaiting_action'?'等待确认':'任务正在推进'}</small><strong>${esc(task.title)}</strong><p>${focusBannerMetrics(task,focus)}</p></div><button class="secondary-btn" id="resume-active-focus">返回专注</button></section>`;
}

function eventSection(title,events,emptyText){return `<div class="section-head"><h2>${title}</h2><span>${events.length} 项</span></div>${events.length?`<div class="event-list">${events.map(event=>{const taskEvent=event.source_type==='task';return `<div class="event-row"><div><b>${esc(event.start_time)}–${esc(event.end_time)} · ${esc(event.title)}</b><span>${taskEvent?'时间段任务':`${esc(event.location||'地点待定')} · 第 ${event.week} 周`}</span></div><button class="more-btn" ${taskEvent?`data-edit="${event.task_id}"`:`data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"`} aria-label="快捷操作">⋯</button></div>`}).join('')}</div>`:`<div class="empty">${emptyText}</div>`}`}

function clockMinutes(value){const [hours,minutes]=String(value||'').split(':').map(Number);return Number.isFinite(hours)&&Number.isFinite(minutes)?hours*60+minutes:null}
function timedCalendarEvent(event,style){const taskEvent=event.source_type==='task',action=taskEvent?`data-edit="${event.task_id}"`:`data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"`;return `<button class="week-timed-event ${taskEvent?'time-block':'course'}" style="${style};--event-color:${esc(event.color||'#4f77bb')}" ${action}><time>${esc(event.start_time)}–${esc(event.end_time)}</time><b>${esc(event.title)}</b><span>${esc(taskEvent?'时间段任务':event.location||'地点待定')}</span></button>`}
function renderWeek(){
  const start=new Date();start.setHours(0,0,0,0);
  const days=Array.from({length:7},(_,index)=>addDays(start,index)),dates=new Set(days.map(iso));
  const tasks=state.tasks.filter(matchesFilters),events=state.events.filter(event=>dates.has(event.date));
  const timed=[...events,...(state.planBlocks||[]).filter(block=>dates.has(block.block_date))];
  const starts=timed.map(item=>clockMinutes(item.start_time)).filter(Number.isFinite),ends=timed.map(item=>clockMinutes(item.end_time)).filter(Number.isFinite);
  const profileStart=clockMinutes(state.planningProfile?.workday_start),profileEnd=clockMinutes(state.planningProfile?.workday_end);
  const rangeStart=Math.max(0,Math.floor(Math.min(8*60,profileStart??8*60,...starts)/60)*60),rangeEnd=Math.min(24*60,Math.ceil(Math.max(22*60,profileEnd??22*60,...ends)/60)*60);
  const hourHeight=64,laneHeight=(rangeEnd-rangeStart)/60*hourHeight;
  const labels=[];for(let minute=rangeStart;minute<rangeEnd;minute+=60)labels.push(`<span style="top:${(minute-rangeStart)/60*hourHeight}px">${pad(Math.floor(minute/60))}:00</span>`);
  const position=(from,to)=>{const startMinute=clockMinutes(from),endMinute=clockMinutes(to);if(startMinute===null||endMinute===null)return null;return `top:${Math.max(0,(startMinute-rangeStart)/60*hourHeight)}px;height:${Math.max(28,(endMinute-startMinute)/60*hourHeight-3)}px`};
  const headers=days.map((day,index)=>`<div class="week-day-head ${index===0?'today':''}"><span>${['周日','周一','周二','周三','周四','周五','周六'][day.getDay()]}</span><strong>${day.getMonth()+1}/${day.getDate()}</strong></div>`).join('');
  const allDay=days.map(day=>{const date=iso(day),daily=tasks.filter(task=>task.start_date===date||taskDeadline(task)===date).sort(sortTasks);return `<div class="week-all-day-cell">${daily.map(task=>`<button class="week-task-chip ${task.domain} ${task.status==='completed'?'done':''} ${isOverdue(task)?'overdue':''}" data-task-context="${task.id}" data-edit="${task.id}"><b>${taskDeadline(task)===date?'D':'S'}</b><span>${esc(task.title)}</span></button>`).join('')||'<span class="week-free">留白</span>'}</div>`}).join('');
  const lanes=days.map((day,index)=>{const date=iso(day),classes=events.filter(event=>event.date===date),blocks=(state.planBlocks||[]).filter(block=>block.block_date===date),now=new Date(),nowMinute=now.getHours()*60+now.getMinutes(),nowLine=index===0&&nowMinute>=rangeStart&&nowMinute<=rangeEnd?`<i class="week-now-line" style="top:${(nowMinute-rangeStart)/60*hourHeight}px"><b>现在</b></i>`:'';return `<div class="week-time-lane ${index===0?'today':''}" style="height:${laneHeight}px">${nowLine}${classes.map(event=>{const style=position(event.start_time,event.end_time);return style?timedCalendarEvent(event,style):''}).join('')}${blocks.map(block=>{const style=position(block.start_time,block.end_time),task=state.tasks.find(item=>item.id===block.task_id),title=block.block_type==='focus'?(task?.title||block.task_title||'专注任务'):planTypeLabel(block.block_type);if(!style)return '';return block.block_type==='focus'?`<button class="week-timed-event plan focus" style="${style}" data-plan-focus="${block.task_id}" data-plan-block="${block.id||''}"><time>${esc(block.start_time)}–${esc(block.end_time)}</time><b>${esc(title)}</b></button>`:`<div class="week-timed-event plan rest" style="${style}"><time>${esc(block.start_time)}–${esc(block.end_time)}</time><b>${esc(title)}</b></div>`}).join('')}</div>`}).join('');
  return `<div class="week-legend"><span><i class="course"></i>课程占用</span><span><i class="time-block"></i>时间段任务</span><span><i class="focus"></i>专注计划</span><span><b>D</b> Deadline</span><span><b>S</b> 计划开始</span></div><div class="week-scroll"><div class="week-timeline"><div class="week-corner">全天事项</div>${headers}<div class="week-all-day-label">任务</div>${allDay}<div class="week-time-axis" style="height:${laneHeight}px">${labels.join('')}</div>${lanes}</div></div>`;
}

function monthStart(date){const first=new Date(date.getFullYear(),date.getMonth(),1);const day=first.getDay()||7;first.setDate(first.getDate()-day+1);return first}
function renderMonth(){
  const year=state.month.getFullYear(),month=state.month.getMonth(),start=monthStart(state.month);
  const days=Array.from({length:42},(_,index)=>addDays(start,index));
  const tasks=state.tasks.filter(matchesFilters);
  const noDeadline=tasks.filter(task=>active(task)&&task.task_kind!=='free_learning'&&!taskDeadline(task)&&['urgent','high'].includes(task.priority)).sort(sortTasks);
  return `<div class="month-nav"><button id="prev-month">‹ 上个月</button><h2>${year} 年 ${month+1} 月</h2><button id="next-month">下个月 ›</button></div><div class="calendar">${['一','二','三','四','五','六','日'].map(day=>`<div class="calendar-weekday">周${day}</div>`).join('')}${days.map(day=>{const date=iso(day);const daily=tasks.filter(task=>taskDeadline(task)===date).sort(sortTasks);const classes=state.events.filter(event=>event.date===date);return `<div class="calendar-day ${day.getMonth()!==month?'outside':''} ${date===today()?'today':''}"><span class="num">${day.getDate()}</span>${classes.slice(0,2).map(event=>`<button class="calendar-course" ${event.source_type==='task'?`data-edit="${event.task_id}"`:`data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"`}>${esc(event.start_time)} ${esc(event.title)}</button>`).join('')}${daily.slice(0,Math.max(0,4-classes.length)).map(task=>`<button class="cal-task ${task.domain} ${isOverdue(task)?'overdue':''}" data-task-context="${task.id}" data-edit="${task.id}">${task.status==='completed'?'✓ ':isOverdue(task)?'逾 ':''}${esc(task.title)}</button>`).join('')}${daily.length+classes.length>4?`<div class="cal-more">另 ${daily.length+classes.length-4} 项</div>`:''}</div>`}).join('')}</div>${listSection('高优先级但尚无 Deadline',noDeadline,'目前没有需要补充 Deadline 的高优先级任务。')}`;
}

function mondayOf(value){const day=new Date(value);day.setHours(0,0,0,0);day.setDate(day.getDate()-(day.getDay()||7)+1);return day}
function renderSchedule(){
  const monday=mondayOf(state.scheduleWeek),days=Array.from({length:7},(_,index)=>addDays(monday,index));
  const weekEvents=state.events.filter(event=>event.source_type==='course'&&event.date>=iso(days[0])&&event.date<=iso(days[6])&&(!state.semesterFilter||event.semester_id===state.semesterFilter));
  const semesterOptions=state.semesters.map(item=>`<option value="${item.id}" ${state.semesterFilter===item.id?'selected':''}>${esc(item.name)}</option>`).join('');
  const cells=[];
  cells.push('<div class="schedule-cell head">节次</div>',...days.map(day=>`<div class="schedule-cell head">周${'一二三四五六日'[day.getDay()===0?6:day.getDay()-1]}<br>${day.getMonth()+1}/${day.getDate()}</div>`));
  for(let period=1;period<=13;period++){
    cells.push(`<div class="schedule-cell period">第 ${period} 节</div>`);
    for(const day of days){
      const entries=weekEvents.filter(event=>event.date===iso(day)&&event.start_period===period);
      cells.push(`<div class="schedule-cell">${entries.map(event=>`<button class="course-event" style="border-left-color:${esc(event.color)}" data-course-menu="${event.course_id}" data-meeting-id="${event.meeting_id}" data-event-date="${event.date}"><b>${esc(event.title)}</b><span>${esc(event.start_time)}–${esc(event.end_time)}<br>${esc(event.location||'地点待定')}</span></button>`).join('')}</div>`);
    }
  }
  return `<div class="schedule-toolbar"><label class="field"><span>当前学期</span><select id="semester-filter"><option value="">全部学期</option>${semesterOptions}</select></label><button class="secondary-btn" id="edit-current-semester">修改学期</button><button class="secondary-btn" id="schedule-prev">‹ 上一周</button><button class="secondary-btn" id="schedule-today">本周</button><button class="secondary-btn" id="schedule-next">下一周 ›</button><button class="primary-btn" id="import-schedule">导入课表</button></div>${state.semesters.length?`<div class="schedule-board">${cells.join('')}</div>`:'<div class="empty"><strong>还没有课程表</strong>导入 PDF、图片、XLSX 或 CSV，核对预览后再加入日程。<br><br><button class="primary-btn" id="import-schedule-empty">导入第一份课表</button></div>'}`;
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

function researchCreators(item){return (item.creators||[]).slice(0,3).map(person=>person.name||[person.first_name,person.last_name].filter(Boolean).join(' ')).filter(Boolean).join('、')||'作者待补充'}
function researchFolderPath(folder){const parts=[],seen=new Set();while(folder&&!seen.has(folder.id)){seen.add(folder.id);parts.unshift(folder.name);folder=state.researchFolders.find(item=>item.id===folder.parent_id)}return parts.join(' / ')}
function researchVisiblePapers(){if(!state.researchFolderId)return state.researchProjectItems;const selected=new Set([state.researchFolderId]);let changed=true;while(changed){changed=false;for(const folder of state.researchFolders)if(selected.has(folder.parent_id)&&!selected.has(folder.id)){selected.add(folder.id);changed=true}}return state.researchProjectItems.filter(item=>(item.folder_ids||[]).some(id=>selected.has(id)))}
function renderResearchFolders(){const folders=[...state.researchFolders].sort((a,b)=>researchFolderPath(a).localeCompare(researchFolderPath(b),'zh-CN'));return `<div class="research-folder-tree"><button class="${state.researchFolderId?'':'active'}" data-research-folder="">全部论文 <span>${state.researchProjectItems.length}</span></button>${folders.map(folder=>`<button class="${state.researchFolderId===folder.id?'active':''}" data-research-folder="${folder.id}" style="padding-left:${12+Math.min(4,researchFolderPath(folder).split(' / ').length-1)*18}px">${esc(folder.name)} <span>${folder.paper_count}</span></button>`).join('')}</div>`}
function renderResearchPapers(){
  const papers=researchVisiblePapers();
  if(!papers.length)return '<div class="empty"><strong>当前类目还没有论文</strong>可以从 Zotero 文件夹导入，或将项目论文加入此类目。</div>';
  return `<div class="research-inbox project-papers">${papers.map(item=>{
    const history=item.reading_history||[],latest=history.at(-1);
    const resumable=history.some(task=>ACTIVE_STATUSES.has(task.status)&&!task.due_date&&
      (task.task_kind==='free_learning'||(task.task_title===`阅读：${item.title}`&&Number(task.estimated_minutes)===60)));
    const folderOptions=state.researchFolders.map(folder=>`<option value="${folder.id}">${esc(researchFolderPath(folder))}</option>`).join('');
    const progress=history.length?latest.task_kind==='free_learning'?`阅读累计 ${latest.actual_minutes?fmtDuration(latest.actual_minutes):'0 分钟'} · ${latest.focus_sessions||0} 轮留档`:`${latest.progress}% · ${fmtDuration(latest.actual_minutes)}`:'';
    const historyButtons=history.map(task=>`<div class="research-reading-history-entry"><button data-reading-task="${task.task_id}">${esc(task.task_title)} · ${esc(task.created_at.slice(0,10))} · ${task.task_kind==='free_learning'?`${task.focus_sessions||0} 轮 · ${task.actual_minutes?fmtDuration(task.actual_minutes):'0 分钟'}`:`${task.progress}%`}</button>${ACTIVE_STATUSES.has(task.status)&&!task.due_date?`<button class="secondary-btn" data-continue-reading="${task.task_id}" data-paper-id="${item.id}">继续此任务</button>`:''}</div>`).join('');
    return `<article><div class="research-paper"><small>${esc(item.item_type)} · ${esc(item.source_name)}</small><h3>${esc(item.title)}</h3><p>${esc(researchCreators(item))}${item.published_at?` · ${esc(item.published_at)}`:''}</p><p class="research-reading-progress">${history.length?`阅读/复盘 ${history.length} 条任务 · 最近：${latest.status==='completed'?'已完成':latest.status==='in_progress'?'进行中':'待开始'} · ${progress}`:'尚无阅读记录'}</p>${history.length?`<details class="research-reading-history"><summary>查看阅读路径</summary>${historyButtons}</details>`:''}</div><div class="research-actions">${item.zotero_uri?`<a class="secondary-btn" href="${esc(item.zotero_uri)}">在 Zotero 打开</a>`:''}<label class="compact-field"><span>归入类目</span><select data-paper-folder="${item.id}"><option value="">选择类目</option>${folderOptions}</select></label><button class="primary-btn" data-quick-reading="${item.id}">${resumable?'继续阅读':'快速开始阅读'}</button></div></article>`;
  }).join('')}</div>`;
}
function renderResearchLibrary(){
  const source=state.zoteroSources[0],items=state.researchInbox;
  const connection=source?`<div class="research-connection"><div><small>${source.access_mode==='local'?'LOCAL API':'WEB API'}</small><strong>${esc(source.display_name)}</strong><span>${source.last_sync_status==='ok'?`上次同步 ${esc(source.last_synced_at||'')}`:source.last_sync_status==='error'?esc(source.last_sync_error):'尚未同步'}</span></div><button class="secondary-btn" id="research-configure">连接设置</button><button class="primary-btn" id="research-sync">同步新论文</button></div>`:`<div class="research-connection empty"><div><strong>连接 Zotero 文库</strong><span>推荐使用本机 API：无需密钥，题录不会经过额外网络。</span></div><button class="primary-btn" id="research-configure">开始连接</button></div>`;
  const projects=state.projects.filter(project=>project.category==='科研');
  const projectOptions=projects.map(project=>`<option value="${project.id}" ${project.id===state.researchProjectId?'selected':''}>${esc(project.name)}</option>`).join('');
  const projectPapers=state.researchProjectItems.length?renderResearchPapers():'<div class="empty"><strong>这个项目还没有论文</strong>可按 Zotero 文件夹整批导入，或按标题、作者、年份检索导入。</div>';
  const selectedManualFolder=state.researchFolders.find(folder=>folder.id===state.researchFolderId&&!folder.source_collection_key);
  const projectSection=`<section class="research-project-section"><div class="section-head"><div><h2>科研项目论文</h2><p>按类目回看论文和每次阅读任务</p></div><span>${state.researchProjectItems.length} 篇</span></div><div class="research-project-toolbar">${projects.length?`<label class="compact-field"><span>科研项目</span><select id="research-project-select">${projectOptions}</select></label>`:'<p>尚未创建科研项目</p>'}<button class="secondary-btn" id="create-research-project">新建科研项目</button><button class="secondary-btn" id="create-research-folder" ${!projects.length?'disabled':''}>新建子类目</button><button class="secondary-btn" id="rename-research-folder" ${!selectedManualFolder?'disabled':''}>重命名类目</button><button class="primary-btn" id="open-research-import" ${!source||!projects.length?'disabled':''}>从 Zotero 导入论文</button></div><div class="research-folder-layout">${renderResearchFolders()}<div>${projectPapers}</div></div></section>`;
  const list=items.length?`<div class="research-inbox">${items.map(item=>`<article><div class="research-paper"><small>${esc(item.item_type)} · ${esc(item.source_name)}</small><h3>${esc(item.title)}</h3><p>${esc(researchCreators(item))}${item.published_at?` · ${esc(item.published_at)}`:''}</p>${item.abstract?`<span>${esc(item.abstract)}</span>`:''}</div><div class="research-actions">${item.zotero_uri?`<a class="secondary-btn" href="${esc(item.zotero_uri)}">在 Zotero 打开</a>`:''}<button class="secondary-btn" data-research-dismiss="${item.id}">忽略</button><button class="primary-btn" data-research-task="${item.id}">创建阅读任务</button><button class="secondary-btn" data-quick-reading="${item.id}">快速开始</button></div></article>`).join('')}</div>`:'<div class="empty"><strong>科研收件箱为空</strong>同步后，新收集的论文会先出现在这里，不会自动创建任务。</div>';
  return `${connection}${projectSection}<div class="section-head research-inbox-head"><div><h2>待处理论文</h2><p>检查后再转为任务</p></div><span>${items.length} 篇</span></div>${list}`;
}
async function refreshResearch(){const [sources,inbox,allItems]=await Promise.all([api('/api/research/sources'),api('/api/research/inbox'),api('/api/research/items')]);state.zoteroSources=sources.sources;state.researchInbox=inbox.items;state.researchAllItems=allItems.items;await refreshProjectPapers()}
async function refreshProjectPapers(projectId=state.researchProjectId){state.researchProjectId=projectId;if(!projectId){state.researchProjectItems=[];state.researchFolders=[];state.researchFolderId='';return}const [papers,folders]=await Promise.all([api(`/api/research/projects/${projectId}/items`),api(`/api/research/projects/${projectId}/folders`)]);state.researchProjectItems=papers.items;state.researchFolders=folders.folders;if(!state.researchFolders.some(folder=>folder.id===state.researchFolderId))state.researchFolderId=''}
async function createResearchProject(){const name=prompt('科研项目名称');if(!name?.trim())return;try{const data=await api('/api/projects',{method:'POST',body:JSON.stringify({name:name.trim(),category:'科研'})});state.projects.unshift(data.project);await refreshProjectPapers(data.project.id);render();toast('科研项目已创建')}catch(error){showError(error)}}
async function createResearchFolder(){if(!state.researchProjectId)return;const name=prompt(state.researchFolderId?'新建子类目名称':'新建类目名称');if(!name?.trim())return;try{await api(`/api/research/projects/${state.researchProjectId}/folders`,{method:'POST',body:JSON.stringify({name:name.trim(),parent_id:state.researchFolderId||null})});await refreshProjectPapers();render();toast('论文类目已创建')}catch(error){showError(error)}}
async function renameResearchFolder(){const folder=state.researchFolders.find(item=>item.id===state.researchFolderId);if(!folder||folder.source_collection_key)return;const name=prompt('重命名类目',folder.name);if(!name?.trim()||name.trim()===folder.name)return;try{await api(`/api/research/projects/${state.researchProjectId}/folders/${folder.id}`,{method:'PUT',body:JSON.stringify({name:name.trim()})});await refreshProjectPapers();render();toast('类目已重命名')}catch(error){showError(error)}}
async function addPaperToFolder(itemId,folderId){if(!folderId)return;try{await api(`/api/research/projects/${state.researchProjectId}/folders/${folderId}/items/${itemId}`,{method:'POST'});await refreshProjectPapers();render();toast('论文已加入类目')}catch(error){showError(error)}}
async function quickStartReading(itemId,title='',resumeTaskId=''){try{const data=await api(`/api/research/items/${itemId}/quick-task`,{method:'POST',body:JSON.stringify({title:title.trim()||null,resume_task_id:resumeTaskId||null})});if($('#quick-reading-dialog').open)$('#quick-reading-dialog').close();await loadTasks({migrate:false});state.view='research_library';render();const task=data.task,remaining=Math.max(1,Number(task.estimated_minutes||60)-Number(task.actual_minutes||0));state.focusDraft={...state.focusDraft,taskId:task.id,planBlockId:'',preset:'custom',mode:'pomodoro',minutes:Math.min(720,remaining)};persistFocusDraft();openFocus(task.id);toast(data.reused?'已接续原论文阅读任务；本轮到时会自动延长':'已建立自由学习任务；初始 1 小时，到时会自动延长')}catch(error){showError(error)}}
function fillQuickPaperOptions(){const query=$('#quick-paper-search').value.trim().toLowerCase(),current=$('#quick-paper').value;const matches=state.researchAllItems.filter(item=>item.title.toLowerCase().includes(query));$('#quick-paper').innerHTML=matches.length?matches.map(item=>`<option value="${item.id}">${esc(item.title)}</option>`).join(''):'<option value="">没有找到已保存论文</option>';if(matches.some(item=>item.id===current))$('#quick-paper').value=current}
function openQuickReading(){closeDialog();$('#quick-reading-form').reset();fillQuickPaperOptions();$('#quick-reading-dialog').showModal();$('#quick-paper-search').focus()}
async function loadZoteroCollections(){const sourceId=$('#research-import-source').value;const select=$('#research-import-collection');select.innerHTML='<option value="">正在读取文件夹…</option>';if(!sourceId)return;try{const data=await api(`/api/research/sources/${sourceId}/collections`);state.zoteroCollections=data.collections;select.innerHTML=data.collections.length?data.collections.map(item=>`<option value="${item.key}">${esc(item.path)}</option>`).join(''):'<option value="">没有可用文件夹</option>'}catch(error){select.innerHTML='<option value="">读取失败</option>';showError(error)}}
function updateResearchImportMode(){const collection=$('#research-import-mode').value==='collection';$('#research-collection-field').classList.toggle('hidden',!collection);$('#research-subcollections-row').classList.toggle('hidden',!collection);$('#research-organize-row').classList.toggle('hidden',!collection);$('#research-search-field').classList.toggle('hidden',collection);state.researchImportPreview=null;$('#confirm-research-import').disabled=true;$('#research-import-preview').innerHTML='<div class="empty"><strong>选择范围后开始预览</strong>预览不会写入 Yantu，也不会修改 Zotero。</div>'}
async function openResearchImport(){const projects=state.projects.filter(project=>project.category==='科研');if(!projects.length)return createResearchProject();if(!state.zoteroSources.length)return openSettings('zotero');state.researchImportPreview=null;$('#research-import-project').innerHTML=projects.map(project=>`<option value="${project.id}" ${project.id===state.researchProjectId?'selected':''}>${esc(project.name)}</option>`).join('');$('#research-import-source').innerHTML=state.zoteroSources.map(source=>`<option value="${source.id}">${esc(source.display_name)}</option>`).join('');$('#research-import-mode').value='collection';$('#research-import-query').value='';$('#research-include-subcollections').checked=true;$('#research-organize').checked=true;updateResearchImportMode();$('#research-import-dialog').showModal();await loadZoteroCollections()}
function closeResearchImport(){$('#research-import-dialog').close();state.researchImportPreview=null}
function renderResearchImportPreview(){const preview=state.researchImportPreview,node=$('#research-import-preview');node.innerHTML=preview.items.length?`<div class="section-head"><h3>选择要导入的论文</h3><span>${preview.count} 篇${preview.truncated?' · 已截取前 500 篇':''}</span></div>${preview.mode==='collection'?`<p class="form-hint">将保留 ${preview.collections.length} 个 Zotero 文件夹层级；论文不会自动变成待办。</p>`:''}<div class="research-import-list">${preview.items.map((item,index)=>`<label><input type="checkbox" data-import-paper="${index}" checked><span><b>${esc(item.title)}</b><small>${esc(researchCreators(item))}${item.published_at?` · ${esc(item.published_at)}`:''}</small></span></label>`).join('')}</div>`:'<div class="empty"><strong>没有找到论文</strong>请更换文件夹或检索词后重试。</div>';$('#confirm-research-import').disabled=!preview.items.length}
async function previewResearchImport(){const sourceId=$('#research-import-source').value,mode=$('#research-import-mode').value,payload={mode,collection_key:mode==='collection'?$('#research-import-collection').value:null,query:mode==='search'?$('#research-import-query').value.trim():'',include_subcollections:$('#research-include-subcollections').checked},button=$('#preview-research-import');button.disabled=true;button.textContent='正在读取…';try{const data=await api(`/api/research/sources/${sourceId}/project-import-preview`,{method:'POST',body:JSON.stringify(payload)});state.researchImportPreview=data.preview;renderResearchImportPreview()}catch(error){showError(error)}finally{button.disabled=false;button.textContent='读取预览'}}
async function confirmResearchImport(event){event.preventDefault();const preview=state.researchImportPreview;if(!preview)return;const itemKeys=$$('[data-import-paper]:checked').map(input=>preview.items[Number(input.dataset.importPaper)].external_key);if(!itemKeys.length)return toast('请至少选择一篇论文');const projectId=$('#research-import-project').value,button=$('#confirm-research-import');button.disabled=true;button.textContent='正在导入…';try{const result=await api(`/api/research/projects/${projectId}/imports`,{method:'POST',body:JSON.stringify({source_id:preview.source_id,mode:preview.mode,collection_key:preview.collection_key,query:preview.query,item_keys:itemKeys,include_subcollections:preview.include_subcollections,organize_by_collection:preview.mode==='collection'&&$('#research-organize').checked})});await refreshProjectPapers(projectId);state.researchAllItems=(await api('/api/research/items')).items;closeResearchImport();render();toast(`已导入 ${result.imported_count} 篇${result.existing_count?`，已在项目中保留 ${result.existing_count} 篇重复论文`:''}`)}catch(error){showError(error)}finally{button.disabled=false;button.textContent='导入所选论文'}}
async function syncResearch(){const source=state.zoteroSources[0];if(!source)return openSettings('zotero');const button=$('#research-sync');if(button){button.disabled=true;button.textContent='同步中…'}try{const result=await api(`/api/research/sources/${source.id}/sync`,{method:'POST'});await refreshResearch();render();toast(`同步完成：更新 ${result.imported_count} 篇，移除 ${result.deleted_count} 篇`)}catch(error){showError(error)}finally{if(button){button.disabled=false;button.textContent='同步新论文'}}}
async function openResearchTask(itemId){try{const data=await api(`/api/research/inbox/${itemId}/task-preview`,{method:'POST',body:'{}'});state.researchTaskPreview=data.preview;const task=data.preview.task;$('#research-item-id').value=itemId;$('#research-task-title').value=task.title;$('#research-task-minutes').value=task.estimated_minutes;$('#research-task-due').value=task.due_date||'';$('#research-task-priority').value=task.priority;$('#research-task-status').value=task.status;$('#research-task-description').value=task.description||'';$('#research-task-dialog').showModal()}catch(error){showError(error)}}
function closeResearchTask(){$('#research-task-dialog').close();state.researchTaskPreview=null}
async function confirmResearchTask(event){event.preventDefault();const itemId=$('#research-item-id').value;const payload={task:{title:$('#research-task-title').value.trim(),estimated_minutes:Number($('#research-task-minutes').value),due_date:$('#research-task-due').value||null,priority:$('#research-task-priority').value,status:$('#research-task-status').value,description:$('#research-task-description').value.trim(),subcategory:'论文阅读',tags:['Zotero']}};try{const result=await api(`/api/research/inbox/${itemId}/task-confirm`,{method:'POST',body:JSON.stringify(payload)});closeResearchTask();await loadTasks({migrate:false});state.view='research_library';render();toast(result.created?'阅读任务已创建':'该论文已转换过，已返回原任务')}catch(error){showError(error)}}
async function dismissResearch(itemId){if(!confirm('从科研收件箱忽略这篇论文？论文题录仍会保留。'))return;try{await api(`/api/research/inbox/${itemId}`,{method:'DELETE'});await refreshResearch();render();toast('已从科研收件箱移除')}catch(error){showError(error)}}

function bindDynamic(){
  if(state.view==='focus_analytics')bindFocusAnalytics();
  $$('[data-edit]').forEach(button=>button.onclick=()=>openDialog(state.tasks.find(task=>task.id===button.dataset.edit)));
  $$('[data-check]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.check);try{await patchTask(task.id,{status:input.checked?'completed':'in_progress',progress:input.checked?100:Math.min(task.progress,95)});toast(input.checked?'任务已完成':'任务已恢复为进行中')}catch(error){input.checked=!input.checked;showError(error)}});
  $$('[data-priority]').forEach(select=>select.onchange=async()=>{const task=state.tasks.find(item=>item.id===select.dataset.priority);try{await patchTask(task.id,{priority:select.value});toast('优先级已更新')}catch(error){select.value=task.priority;showError(error)}});
  $$('[data-due]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.due);try{await patchTask(task.id,{due_date:input.value||null});toast('Deadline 已更新')}catch(error){input.value=taskDeadline(task)||'';showError(error)}});
  if($('#quick-form'))$('#quick-form').onsubmit=async event=>{event.preventDefault();const title=$('#quick-title').value.trim();if(!title)return;try{await createTask({title,domain:'inbox',priority:'medium',status:'not_started',progress:0,estimated_minutes:0});toast('已加入收件箱')}catch(error){showError(error)}};
  if($('#resume-active-focus'))$('#resume-active-focus').onclick=()=>openFocus(state.focus?.task_id||'');
  if($('#open-planning'))$('#open-planning').onclick=openPlanningDialog;
  $$('[data-plan-focus]').forEach(button=>button.onclick=()=>openFocus(button.dataset.planFocus,button.dataset.planBlock));
  if($('#prev-month'))$('#prev-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()-1,1);render()};
  if($('#next-month'))$('#next-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()+1,1);render()};
  if($('#ai-form'))$('#ai-form').onsubmit=async event=>{event.preventDefault();const task=$('#ai-task').value.trim();if(!task)return;state.aiLoading=true;render();try{const data=await api('/api/ai/breakdown/preview',{method:'POST',body:JSON.stringify({task})});state.aiPreview={source:task,breakdown:data.breakdown};toast('拆解预览已生成，尚未写入数据库')}catch(error){showError(error)}finally{state.aiLoading=false;render()}};
  if($('#ai-confirm'))$('#ai-confirm').onclick=async()=>{if(!state.aiPreview)return;try{await api('/api/ai/breakdown/confirm',{method:'POST',body:JSON.stringify({domain:'research',breakdown:state.aiPreview.breakdown})});state.aiPreview=null;await loadTasks({migrate:false});state.view='research';render();toast('已确认并加入科研任务')}catch(error){showError(error)}};
  if($('#open-ai-settings'))$('#open-ai-settings').onclick=()=>openSettings('ai');
  if($('#research-configure'))$('#research-configure').onclick=()=>openSettings('zotero');
  if($('#research-sync'))$('#research-sync').onclick=syncResearch;
  if($('#create-research-project'))$('#create-research-project').onclick=createResearchProject;
  if($('#create-research-folder'))$('#create-research-folder').onclick=createResearchFolder;
  if($('#rename-research-folder'))$('#rename-research-folder').onclick=renameResearchFolder;
  if($('#open-research-import'))$('#open-research-import').onclick=openResearchImport;
  if($('#research-project-select'))$('#research-project-select').onchange=async event=>{try{await refreshProjectPapers(event.target.value);render()}catch(error){showError(error)}};
  $$('[data-research-folder]').forEach(button=>button.onclick=()=>{state.researchFolderId=button.dataset.researchFolder;render()});
  $$('[data-paper-folder]').forEach(select=>select.onchange=()=>addPaperToFolder(select.dataset.paperFolder,select.value));
  $$('[data-quick-reading]').forEach(button=>button.onclick=()=>quickStartReading(button.dataset.quickReading));
  $$('[data-continue-reading]').forEach(button=>button.onclick=()=>quickStartReading(button.dataset.paperId,'',button.dataset.continueReading));
  $$('[data-reading-task]').forEach(button=>button.onclick=()=>{const task=state.tasks.find(item=>item.id===button.dataset.readingTask);if(task)openDialog(task)});
  $$('[data-research-task]').forEach(button=>button.onclick=()=>openResearchTask(button.dataset.researchTask));
  $$('[data-research-dismiss]').forEach(button=>button.onclick=()=>dismissResearch(button.dataset.researchDismiss));
  $$('[data-task-context]').forEach(node=>node.oncontextmenu=event=>{event.preventDefault();showTaskMenu(node.dataset.taskContext,event.clientX,event.clientY)});
  $$('[data-task-menu]').forEach(node=>node.onclick=event=>{event.stopPropagation();showTaskMenu(node.dataset.taskMenu,event.clientX,event.clientY)});
  $$('[data-course-menu]').forEach(node=>{node.onclick=event=>{event.stopPropagation();showCourseMenu(node.dataset.courseMenu,node.dataset.meetingId,node.dataset.eventDate,event.clientX,event.clientY)};node.oncontextmenu=event=>{event.preventDefault();showCourseMenu(node.dataset.courseMenu,node.dataset.meetingId,node.dataset.eventDate,event.clientX,event.clientY)}});
  if($('#schedule-prev'))$('#schedule-prev').onclick=()=>{state.scheduleWeek=addDays(state.scheduleWeek,-7);render()};
  if($('#schedule-next'))$('#schedule-next').onclick=()=>{state.scheduleWeek=addDays(state.scheduleWeek,7);render()};
  if($('#schedule-today'))$('#schedule-today').onclick=()=>{state.scheduleWeek=new Date();render()};
  if($('#semester-filter'))$('#semester-filter').onchange=event=>{state.semesterFilter=event.target.value;render()};
  if($('#edit-current-semester'))$('#edit-current-semester').onclick=()=>openSemesterDialog(state.semesterFilter||currentSemester()?.id);
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

function openScheduleDialog(){state.schedulePreview=null;$('#schedule-form').reset();const now=new Date(),start=addDays(mondayOf(now),now.getDay()===0?7:0);$('#semester-name').value=`${start.getFullYear()} 秋季学期`;$('#semester-stage').value='研一上';$('#semester-start').value=iso(start);$('#semester-end').value=iso(addDays(start,118));$('#schedule-step-input').classList.remove('hidden');$('#schedule-preview').classList.add('hidden');$('#schedule-dialog').showModal()}
function openSemesterDialog(id){const semester=state.semesters.find(item=>item.id===id)||currentSemester();if(!semester)return toast('请先导入一个学期');$('#edit-semester-id').value=semester.id;$('#edit-semester-name').value=semester.name;$('#edit-semester-stage').value=semester.stage_label||'';$('#edit-semester-start').value=semester.start_date;$('#edit-semester-end').value=semester.end_date;$('#semester-dialog').showModal()}
function meetingWeekValue(meeting){return meeting.week_pattern==='custom'?`${(meeting.custom_weeks||[]).join(',')} custom`:`${meeting.start_week||1}-${meeting.end_week||18} ${meeting.week_pattern||'all'}`}
function previewMeetingRow(meeting,index){return `<div class="preview-meeting" data-meeting-index="${index}"><select data-meeting-field="weekday">${[1,2,3,4,5,6,7].map(day=>`<option value="${day}" ${day===meeting.weekday?'selected':''}>周${'一二三四五六日'[day-1]}</option>`).join('')}</select><input type="number" data-meeting-field="start_period" value="${meeting.start_period||1}" min="1" max="30" placeholder="开始节"><input type="number" data-meeting-field="end_period" value="${meeting.end_period||1}" min="1" max="30" placeholder="结束节"><input type="time" data-meeting-field="start_time" value="${meeting.start_time||''}"><input type="time" data-meeting-field="end_time" value="${meeting.end_time||''}"><input data-meeting-field="weeks" value="${esc(meetingWeekValue(meeting))}" title="1-16 all、1-16 odd 或 1,3,5 custom"><input data-meeting-field="teacher_override" value="${esc(meeting.teacher_override||'')}" placeholder="本课次教师"><input data-meeting-field="location_override" value="${esc(meeting.location_override||'')}" placeholder="本课次地点"></div>`}
function previewLearningItems(items){if(!items?.length)return '';return `<div class="section-head preview-learning-head"><h2>无固定时间课程</h2><span>将建立自由学习任务</span></div><div class="preview-learning-items">${items.map((item,index)=>`<div data-learning-index="${index}"><input type="checkbox" data-learning-field="selected" ${item.selected?'checked':''}><input data-learning-field="title" value="${esc(item.title)}" placeholder="课程名称"><input data-learning-field="teacher" value="${esc(item.teacher||'')}" placeholder="教师"><input data-learning-field="class_name" value="${esc(item.class_name||'')}" placeholder="班级 / MOOC 时间"></div>`).join('')}</div>`}
function renderSchedulePreview(){const preview=state.schedulePreview;const node=$('#schedule-preview');node.classList.remove('hidden');$('#schedule-step-input').classList.add('hidden');node.innerHTML=`<div class="section-head"><h2>核对识别结果</h2><span>${preview.courses.length} 门课程</span></div>${preview.warnings.map(item=>`<p class="preview-message">${esc(item)}</p>`).join('')}<div class="schedule-preview-list">${preview.courses.map((course,index)=>`<div class="preview-course ${course.errors.length?'invalid':''}" data-preview-index="${index}"><div class="preview-course-head"><input type="checkbox" data-course-field="selected" ${course.selected?'checked':''} ${course.errors.length?'disabled':''}><input data-course-field="name" value="${esc(course.name)}" placeholder="课程名称"><input data-course-field="teacher" value="${esc(course.teacher)}" placeholder="默认教师"><input data-course-field="location" value="${esc(course.location)}" placeholder="默认地点"></div><div class="preview-meetings"><small>星期 · 节次 · 时间 · 周次规则 · 本课次教师/地点</small>${course.meetings.map(previewMeetingRow).join('')}</div>${[...course.errors,...course.warnings].map(item=>`<p class="preview-message">${esc(item)}</p>`).join('')}</div>`).join('')}</div>${previewLearningItems(preview.learning_items)}<div class="dialog-actions"><button class="secondary-btn" type="button" id="preview-back">返回</button><span></span><button class="secondary-btn" type="button" id="preview-cancel">取消</button><button class="primary-btn" type="button" id="confirm-schedule">确认导入</button></div>`;
  $('#preview-back').onclick=()=>{$('#schedule-step-input').classList.remove('hidden');node.classList.add('hidden')};$('#preview-cancel').onclick=()=>$('#schedule-dialog').close();$('#confirm-schedule').onclick=confirmScheduleImport;
}
function collectSchedulePreview(){const preview=structuredClone(state.schedulePreview);$$('[data-preview-index]').forEach(card=>{const course=preview.courses[Number(card.dataset.previewIndex)],courseField=name=>card.querySelector(`[data-course-field="${name}"]`);course.selected=courseField('selected').checked;course.name=courseField('name').value.trim();course.teacher=courseField('teacher').value.trim();course.location=courseField('location').value.trim();course.meetings=[...card.querySelectorAll('[data-meeting-index]')].map(row=>{const field=name=>row.querySelector(`[data-meeting-field="${name}"]`),meeting=course.meetings[Number(row.dataset.meetingIndex)]||{},[range,pattern='all']=field('weeks').value.trim().split(/\s+/),numbers=range.split(pattern==='custom'?/,/:/-/).map(Number).filter(Number.isFinite),custom=pattern==='custom'?numbers:[];return {...meeting,weekday:Number(field('weekday').value),start_period:Number(field('start_period').value),end_period:Number(field('end_period').value),start_time:field('start_time').value,end_time:field('end_time').value,start_week:Math.min(...numbers),end_week:Math.max(...numbers),week_pattern:pattern,custom_weeks:custom,teacher_override:field('teacher_override').value.trim(),location_override:field('location_override').value.trim()}})});$$('[data-learning-index]').forEach(row=>{const item=preview.learning_items[Number(row.dataset.learningIndex)],field=name=>row.querySelector(`[data-learning-field="${name}"]`);item.selected=field('selected').checked;item.title=field('title').value.trim();item.teacher=field('teacher').value.trim();item.class_name=field('class_name').value.trim()});return preview}
async function confirmScheduleImport(){const preview=collectSchedulePreview();await api('/api/schedule-import/confirm',{method:'POST',body:JSON.stringify(preview)});$('#schedule-dialog').close();await loadTasks({migrate:false});state.view='schedule';render();toast('课表已加入日程')}

let editingCourseMeetings=[];
async function openCourseDialog(id){const data=await api(`/api/courses/${id}`),course=data.course,meeting=course.meetings[0];editingCourseMeetings=structuredClone(course.meetings);$('#course-id').value=id;$('#course-name').value=course.name;$('#course-teacher').value=course.teacher;$('#course-location').value=course.location;$('#course-notes').value=course.notes;$('#course-weekday').value=meeting.weekday;$('#course-start-period').value=meeting.start_period;$('#course-end-period').value=meeting.end_period;$('#course-start-time').value=meeting.start_time;$('#course-end-time').value=meeting.end_time;$('#course-start-week').value=meeting.start_week;$('#course-end-week').value=meeting.end_week;$('#course-week-pattern').value=meeting.week_pattern==='custom'?'all':meeting.week_pattern;$('#course-dialog').showModal()}

async function createTask(payload){const data=await api('/api/tasks',{method:'POST',body:JSON.stringify(payload)});state.tasks.push(data.task);render();return data.task}
async function patchTask(id,changes){const data=await api(`/api/tasks/${id}`,{method:'PATCH',body:JSON.stringify(changes)});state.tasks=state.tasks.map(task=>task.id===id?data.task:task);render();return data.task}

function openDialog(task=null){
  $('#task-form').reset();
  $('.advanced-settings').open=Boolean(task);
  $('#task-id').value=task?.id||'';
  $('#dialog-title').textContent=task?'编辑任务':'新建任务';
  $('#delete-btn').classList.toggle('hidden',!task);
  $('#open-quick-reading').classList.toggle('hidden',Boolean(task));
  $('#task-title').value=task?.title||'';
  $('#task-domain').value=task?.domain||(['research','course','personal','inbox'].includes(state.view)?state.view:'research');
  $('#task-kind').value=task?.schedule_mode==='time_block'?'time_block':task?.task_kind||(state.view==='free_learning'?'free_learning':'standard');
  $('#task-paper').innerHTML='<option value="">不关联论文</option>'+state.researchAllItems.map(item=>`<option value="${item.id}">${esc(item.title)}</option>`).join('');
  $('#task-paper').value='';
  updateTaskPaperField(Boolean(task));
  $('#task-subcategory').value=task?.subcategory||'';
  $('#task-description').value=task?.description||'';
  $('#task-start-date').value=task?.start_date||'';
  $('#task-due-date').value=taskDeadline(task)||'';
  $('#task-block-date').value=task?.scheduled_date||today();
  $('#task-block-start').value=task?.scheduled_start_time||'09:00';
  $('#task-block-end').value=task?.scheduled_end_time||'10:00';
  $('#task-block-weekly').checked=Boolean(task?.schedule_mode==='time_block'&&task?.is_recurring);
  $('#task-block-until').value=task?.recurrence_until||'';
  $('#task-block-until').disabled=!$('#task-block-weekly').checked;
  updateTaskKindField();
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
function updateTaskKindField(){const kind=$('#task-kind').value,free=kind==='free_learning',timed=kind==='time_block';$('#task-due-field').classList.toggle('hidden',free||timed);$('#task-due-date').disabled=free||timed;$('#task-time-block-fields').classList.toggle('hidden',!timed);if(free||timed)$('#task-due-date').value='';$('#task-kind-hint').textContent=free?'不设截止日期，不参与按日期自动分摊；投入会跨多次计时累计，到达当前时长上限后自动扩展。':timed?'按明确的日期和时间占据日历；自动规划会避让，发生重叠时仍可确认保存。':'目标任务按日期参与每日规划。'}
function updateTaskPaperField(editing=false){$('#task-paper-field').classList.toggle('hidden',editing||$('#task-domain').value!=='research')}
function formPayload(){const selectedKind=$('#task-kind').value,timed=selectedKind==='time_block',free=selectedKind==='free_learning',scheduledDate=timed?$('#task-block-date').value||null:null,startDate=timed?scheduledDate:$('#task-start-date').value||null,dueDate=free||timed?null:$('#task-due-date').value||null,weekly=timed&&$('#task-block-weekly').checked;if(startDate&&dueDate&&startDate>dueDate)throw new Error('开始日期不能晚于截止日期');if(timed&&(!scheduledDate||!$('#task-block-start').value||!$('#task-block-end').value))throw new Error('时间段任务需要完整的日期和起止时间');if(timed&&$('#task-block-end').value<=$('#task-block-start').value)throw new Error('结束时间必须晚于开始时间');if(weekly&&!$('#task-block-until').value)throw new Error('每周重复需要填写结束日期');return {title:$('#task-title').value.trim(),domain:$('#task-domain').value,task_kind:free?'free_learning':'standard',schedule_mode:timed?'time_block':'flexible',scheduled_date:scheduledDate,scheduled_start_time:timed?$('#task-block-start').value:null,scheduled_end_time:timed?$('#task-block-end').value:null,schedule_timezone:'Asia/Shanghai',recurrence_until:weekly?$('#task-block-until').value:null,subcategory:$('#task-subcategory').value.trim(),description:$('#task-description').value.trim(),start_date:startDate,due_date:dueDate,priority:$('#task-priority').value,status:$('#task-status').value,progress:Number($('#task-progress').value)||0,tags:$('#task-tags').value.split(',').map(value=>value.trim()).filter(Boolean),estimated_minutes:Number($('#task-estimated').value)||0,actual_minutes:Number($('#task-actual').value)||0,is_recurring:timed?weekly:$('#task-recurring').checked,recurrence_rule:timed?(weekly?'weekly':''):($('#task-recurring').checked?$('#task-recurrence').value.trim():''),notes:$('#task-notes').value.trim(),research_item_id:$('#task-domain').value==='research'?$('#task-paper').value||null:null}}
function timeBlockConflicts(payload,taskId=''){if(payload.schedule_mode!=='time_block')return [];const first=parseDate(payload.scheduled_date),last=parseDate(payload.recurrence_until||payload.scheduled_date),weekday=first?.getDay();return state.events.filter(event=>{if(event.task_id===taskId||event.date<payload.scheduled_date||event.date>(payload.recurrence_until||payload.scheduled_date))return false;const day=parseDate(event.date);if(payload.is_recurring&&day?.getDay()!==weekday)return false;if(!payload.is_recurring&&event.date!==payload.scheduled_date)return false;return event.start_time<payload.scheduled_end_time&&payload.scheduled_start_time<event.end_time})}
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
  renderHabitSettings();
  fillZoteroSettings();
}
function resetHabitForm(){
  $('#habit-profile-id').value='';$('#habit-name').value='';$('#habit-apps').value='';$('#habit-idle').value=60;$('#habit-switch-warning').value=8;
}
function renderHabitSettings(){
  const capability=state.focusHabitCapability||{};
  $('#habit-capability').textContent=capability.available?'Windows 活动采样可用；滚屏、键入或鼠标操作只用于判断是否活跃。':(capability.reason||'当前环境无法监测应用，番茄钟仍可正常使用。');
  const stats=state.focusHabitStats;$('#habit-longterm-summary').innerHTML=stats&&stats.completed_sessions?`<div><b>${Math.round(stats.active_seconds/60)} 分</b><span>近 28 天有效专注</span></div><div><b>${stats.quality_score}%</b><span>专注质量</span></div><div><b>${stats.current_streak_days} 天</b><span>当前连续学习</span></div>`:'<p>完成启用习惯方案的专注后，这里会形成 28 天学习循环趋势。</p>';
  $('#habit-current-app').disabled=!capability.available;
  $('#habit-profile-list').innerHTML=state.focusHabits.length?state.focusHabits.map(profile=>`<article><button type="button" data-habit-edit="${profile.id}"><b>${esc(profile.name)}</b><span>${profile.allowed_apps.map(esc).join(' · ')}</span></button><button type="button" class="danger-link" data-habit-delete="${profile.id}">停用</button></article>`).join(''):'<div class="empty compact"><strong>尚无习惯方案</strong>为代码、阅读或写作设置常用应用。</div>';
  $$('[data-habit-edit]').forEach(button=>button.onclick=()=>{const profile=state.focusHabits.find(item=>item.id===button.dataset.habitEdit);if(!profile)return;$('#habit-profile-id').value=profile.id;$('#habit-name').value=profile.name;$('#habit-apps').value=profile.allowed_apps.join(', ');$('#habit-idle').value=profile.idle_threshold_seconds;$('#habit-switch-warning').value=profile.switch_warning_count});
  $$('[data-habit-delete]').forEach(button=>button.onclick=()=>disableHabitProfile(button.dataset.habitDelete));
}
async function saveHabitProfile(){
  const id=$('#habit-profile-id').value,payload={name:$('#habit-name').value.trim(),allowed_apps:$('#habit-apps').value.split(',').map(value=>value.trim()).filter(Boolean),idle_threshold_seconds:Number($('#habit-idle').value),switch_warning_count:Number($('#habit-switch-warning').value)};
  try{const data=await api(id?`/api/focus/habits/${id}`:'/api/focus/habits',{method:id?'PUT':'POST',body:JSON.stringify(payload)});state.focusHabits=[data.profile,...state.focusHabits.filter(item=>item.id!==data.profile.id)];state.focusDraft.habitProfileId=data.profile.id;persistFocusDraft();resetHabitForm();renderHabitSettings();toast('习惯方案已保存，并设为下一轮监测方案')}catch(error){showError(error)}
}
async function disableHabitProfile(id){if(!confirm('停用这个专注习惯方案？历史记录会保留。'))return;try{await api(`/api/focus/habits/${id}`,{method:'DELETE'});state.focusHabits=state.focusHabits.filter(item=>item.id!==id);resetHabitForm();renderHabitSettings();toast('方案已停用')}catch(error){showError(error)}}
async function addCurrentHabitApp(){const button=$('#habit-current-app');button.disabled=true;button.textContent='3 秒后读取…';toast('请在 3 秒内切换到目标应用');await new Promise(resolve=>setTimeout(resolve,3000));try{const data=await api('/api/focus/habits/current-app');const apps=$('#habit-apps').value.split(',').map(value=>value.trim()).filter(Boolean);if(!apps.includes(data.activity.process_name))apps.push(data.activity.process_name);$('#habit-apps').value=apps.join(', ');toast(`已加入 ${data.activity.process_name}`)}catch(error){showError(error)}finally{button.disabled=false;button.textContent='加入当前应用'}}
function openSettings(tab='focus'){fillSettings();selectSettingsTab(tab);$('#settings-dialog').showModal()}
function closeSettings(){$('#settings-dialog').close();$('#ai-api-key').value='';$('#zotero-api-key').value=''}
async function savePreferences(event){event.preventDefault();let notification=$('#setting-notification').checked;if(notification&&'Notification'in window&&Notification.permission!=='granted'){const permission=await Notification.requestPermission();notification=permission==='granted';$('#setting-notification').checked=notification;if(!notification)toast('通知未获授权，将继续使用标题、Toast 和提示音提醒')}try{const data=await api('/api/settings/preferences',{method:'PUT',body:JSON.stringify({sound_enabled:$('#setting-sound').checked,notification_enabled:notification,auto_start_break:$('#setting-auto-break').checked,volume:Number($('#setting-volume').value)})});state.preferences=data.preferences;toast('专注偏好已保存')}catch(error){showError(error)}}
async function saveAiSettings(){const button=$('#save-ai-settings');button.disabled=true;try{const data=await api('/api/settings/ai',{method:'PUT',body:JSON.stringify({api_key:$('#ai-api-key').value.trim(),base_url:$('#ai-base-url').value.trim(),model:$('#ai-model').value.trim(),timeout:Number($('#ai-timeout').value)})});state.aiSettings=data.ai;$('#ai-api-key').value='';fillSettings();toast('AI 设置已安全保存')}catch(error){showError(error)}finally{button.disabled=false}}
async function testAiSettings(){const button=$('#test-ai-key');button.disabled=true;button.textContent='连接中…';try{const data=await api('/api/settings/ai/test',{method:'POST'});toast(data.model_available?'连接成功，所选模型可用':'连接成功，但所选模型不在模型列表中')}catch(error){showError(error)}finally{button.disabled=false;button.textContent='测试连接'}}
async function deleteAiKey(){if(!confirm('从 Windows 凭据管理器删除 DeepSeek API Key？'))return;try{const data=await api('/api/settings/ai/key',{method:'DELETE'});state.aiSettings=data.ai;fillSettings();toast('API Key 已删除')}catch(error){showError(error)}}

function fillZoteroSettings(){const source=state.zoteroSources[0]||{};$('#zotero-source-id').value=source.id||'';$('#zotero-access-mode').value=source.access_mode||'local';$('#zotero-display-name').value=source.display_name||'我的 Zotero';$('#zotero-library-type').value=source.library_type||'user';$('#zotero-library-id').value=source.library_id||'';$('#zotero-base-url').value=source.base_url||(source.access_mode==='web'?'https://api.zotero.org':'http://127.0.0.1:23119/api');$('#zotero-api-key').value='';const text=!source.id?'尚未建立连接':source.credential_error?source.credential_error:source.access_mode==='local'?'本机读取无需 API Key':source.configured?`已安全配置 ${source.masked_hint||''}`:'尚未配置 Web API Key';$('#zotero-settings-status').textContent=text;$('#delete-zotero-key').disabled=!source.id||source.credential_source!=='credential_manager';updateZoteroFields()}
function updateZoteroFields(){const local=$('#zotero-access-mode').value==='local';$('#zotero-key-field').classList.toggle('hidden',local);if(local&&(!$('#zotero-base-url').value||$('#zotero-base-url').value==='https://api.zotero.org'))$('#zotero-base-url').value='http://127.0.0.1:23119/api';if(!local&&$('#zotero-base-url').value.includes('23119'))$('#zotero-base-url').value='https://api.zotero.org';$('#zotero-library-id').placeholder=local&&$('#zotero-library-type').value==='user'?'本机个人文库可留空':'Zotero 数字文库 ID'}
function zoteroPayload(){return {id:$('#zotero-source-id').value||undefined,access_mode:$('#zotero-access-mode').value,display_name:$('#zotero-display-name').value.trim(),library_type:$('#zotero-library-type').value,library_id:$('#zotero-library-id').value.trim(),base_url:$('#zotero-base-url').value.trim(),api_key:$('#zotero-api-key').value.trim()}}
async function saveZoteroConnection(){const button=$('#save-zotero');button.disabled=true;try{const data=await api('/api/research/sources',{method:'POST',body:JSON.stringify(zoteroPayload())});state.zoteroSources=[data.source,...state.zoteroSources.filter(item=>item.id!==data.source.id)];$('#zotero-api-key').value='';fillZoteroSettings();toast('Zotero 连接已保存');return data.source}catch(error){showError(error);return null}finally{button.disabled=false}}
async function testZoteroConnection(){let source=state.zoteroSources.find(item=>item.id===$('#zotero-source-id').value);if(!source)source=await saveZoteroConnection();if(!source)return;const button=$('#test-zotero');button.disabled=true;button.textContent='连接中…';try{const data=await api(`/api/research/sources/${source.id}/test`,{method:'POST'});await refreshResearch();fillZoteroSettings();toast(`Zotero 连接成功${data.library_version?` · 文库版本 ${data.library_version}`:''}`)}catch(error){showError(error)}finally{button.disabled=false;button.textContent='测试连接'}}
async function syncZoteroFromSettings(){const source=state.zoteroSources.find(item=>item.id===$('#zotero-source-id').value);if(!source)return toast('请先保存 Zotero 连接');const button=$('#sync-zotero');button.disabled=true;button.textContent='同步中…';try{const result=await api(`/api/research/sources/${source.id}/sync`,{method:'POST'});await refreshResearch();fillZoteroSettings();toast(`已同步 ${result.imported_count} 篇论文`)}catch(error){showError(error)}finally{button.disabled=false;button.textContent='立即同步'}}
async function deleteZoteroKey(){const sourceId=$('#zotero-source-id').value;if(!sourceId||!confirm('从 Windows 凭据管理器删除 Zotero API Key？'))return;try{const data=await api(`/api/research/sources/${sourceId}/key`,{method:'DELETE'});state.zoteroSources=state.zoteroSources.map(item=>item.id===sourceId?data.source:item);fillZoteroSettings();toast('Zotero API Key 已删除')}catch(error){showError(error)}}

function fillPlanningProfile(){const profile=state.planningProfile;$('#plan-work-start').value=profile.workday_start;$('#plan-work-end').value=profile.workday_end;$('#plan-use-pomodoro').value=String(profile.use_pomodoro);$('#plan-focus').value=profile.focus_minutes;$('#plan-short-break').value=profile.short_break_minutes;$('#plan-long-break').value=profile.long_break_minutes;$('#plan-long-after').value=profile.long_break_after;$('#plan-max-continuous').value=profile.max_continuous_focus;$('#plan-buffer').value=profile.buffer_minutes}
function planningProfilePayload(){return {workday_start:$('#plan-work-start').value,workday_end:$('#plan-work-end').value,use_pomodoro:$('#plan-use-pomodoro').value==='true',focus_minutes:Number($('#plan-focus').value),short_break_minutes:Number($('#plan-short-break').value),long_break_minutes:Number($('#plan-long-break').value),long_break_after:Number($('#plan-long-after').value),max_continuous_focus:Number($('#plan-max-continuous').value),buffer_minutes:Number($('#plan-buffer').value)}}
function openPlanningDialog(){state.planPreview=null;fillPlanningProfile();$('#confirm-planning').classList.add('hidden');$('#planning-preview').innerHTML='<div class="empty"><strong>先生成一个可检查的时间表</strong>会综合任务优先级、Deadline、课程占用和休息偏好。</div>';$('#planning-dialog').showModal()}
function closePlanningDialog(){$('#planning-dialog').close();state.planPreview=null}
function planTypeLabel(type){return {focus:'专注',short_break:'短休息',long_break:'长休息',buffer:'切换缓冲',course:'课程'}[type]||type}
function renderPlanningPreview(){const preview=state.planPreview;if(!preview)return;const taskNames=Object.fromEntries(state.tasks.map(task=>[task.id,task.title]));const items=[...preview.blocks.map(block=>({...block,title:block.block_type==='focus'?taskNames[block.task_id]:planTypeLabel(block.block_type)})),...preview.fixed_events.map(event=>({start_time:event.start_time,end_time:event.end_time,block_type:'course',title:event.title,rationale:event.location||'固定课程'}))].sort((a,b)=>a.start_time.localeCompare(b.start_time));$('#planning-preview').innerHTML=`<div class="plan-summary"><div><strong>${fmtDuration(preview.summary.scheduled_focus_minutes)}</strong><span>已安排专注</span></div><div><strong>${fmtDuration(preview.summary.break_minutes)}</strong><span>主动恢复</span></div><div><strong>${fmtDuration(preview.summary.unscheduled_minutes)}</strong><span>超出容量</span></div></div>${preview.warnings.length?`<div class="plan-warnings">${preview.warnings.map(esc).join('<br>')}</div>`:''}<div class="preview-timeline">${items.map(item=>`<article class="${item.block_type}"><time>${esc(item.start_time)}–${esc(item.end_time)}</time><div><strong>${esc(item.title)}</strong><p>${esc(item.rationale||planTypeLabel(item.block_type))}</p></div></article>`).join('')}</div>`;$('#confirm-planning').classList.remove('hidden')}
async function previewPlanning(){const button=$('#preview-planning');button.disabled=true;button.textContent='正在计算…';try{const saved=await api('/api/planning/profile',{method:'PUT',body:JSON.stringify(planningProfilePayload())});state.planningProfile=saved.profile;state.focusDraft.preset='planning';state.focusDraft.mode=saved.profile.use_pomodoro?'pomodoro':'free';state.focusDraft.minutes=saved.profile.focus_minutes;persistFocusDraft();const result=await api('/api/planning/preview',{method:'POST',body:JSON.stringify({date:today()})});state.planPreview=result.preview;renderPlanningPreview()}catch(error){showError(error)}finally{button.disabled=false;button.textContent='保存并生成预览'}}
async function savePlanningProfile(){const button=$('#save-planning-profile');button.disabled=true;try{const saved=await api('/api/planning/profile',{method:'PUT',body:JSON.stringify(planningProfilePayload())});state.planningProfile=saved.profile;state.focusDraft.preset='planning';state.focusDraft.mode=saved.profile.use_pomodoro?'pomodoro':'free';state.focusDraft.minutes=saved.profile.focus_minutes;persistFocusDraft();toast(`规划偏好已保存 · ${saved.profile.use_pomodoro?`${saved.profile.focus_minutes} 分钟专注 / ${saved.profile.short_break_minutes} 分钟休息`:'自由工作模式'}`)}catch(error){showError(error)}finally{button.disabled=false}}
async function confirmPlanning(event){event.preventDefault();if(!state.planPreview)return;const button=$('#confirm-planning');button.disabled=true;try{await api('/api/planning/confirm',{method:'POST',body:JSON.stringify(state.planPreview)});closePlanningDialog();await loadTasks({migrate:false});toast('今日时间表已确认')}catch(error){showError(error)}finally{button.disabled=false}}

function restoreFocus(){}
function focusElapsed(timer=state.focus){if(!timer)return 0;let elapsed=Number(timer.elapsed_seconds||0);if(timer.status==='running'&&timer.last_resumed_at)elapsed+=Math.max(0,(Date.now()-new Date(timer.last_resumed_at).getTime())/1000);return elapsed}
function focusClock(seconds){const value=Math.max(0,Math.floor(seconds));return `${pad(Math.floor(value/60))}:${pad(value%60)}`}
function focusTask(){return state.tasks.find(task=>task.id===state.focus?.task_id)}
function habitSummary(habit){
  if(!habit)return '';
  if(habit.status==='unavailable')return `<div class="focus-habit-card unavailable"><b>应用监测不可用</b><span>${esc(habit.unavailable_reason||'本轮仍可正常计时')}</span></div>`;
  const basic=!habit.profile_id,attention=!basic&&habit.status==='monitoring'&&Number(habit.switch_count)>=Number(habit.switch_warning_count||999),apps=habit.apps||[];
  const metrics=basic?`<div><dt>输入活跃</dt><dd>${focusClock(habit.active_seconds||0)}</dd></div><div><dt>空闲</dt><dd>${focusClock(habit.idle_seconds||0)}</dd></div><div><dt>应用切换</dt><dd>${habit.switch_count||0} 次</dd></div>`:`<div><dt>目标应用活跃</dt><dd>${focusClock(habit.active_seconds||0)}</dd></div><div><dt>空闲</dt><dd>${focusClock(habit.idle_seconds||0)}</dd></div><div><dt>非目标应用</dt><dd>${focusClock(habit.distraction_seconds||0)}</dd></div><div><dt>切换</dt><dd>${habit.switch_count||0} 次</dd></div>`;
  const appRows=apps.length?`<div class="focus-app-breakdown"><div class="focus-app-breakdown-head"><b>应用明细</b><span>输入活跃 / 空闲</span></div>${apps.map(item=>`<div class="focus-app-row"><span><i class="${item.is_allowed?'allowed':'outside'}"></i>${esc(item.process_name)}</span><b>${focusClock(item.active_seconds||0)} / ${focusClock(item.idle_seconds||0)}</b></div>`).join('')}</div>`:`<div class="focus-app-empty">等待获取前台应用数据…</div>`;
  return `<div class="focus-habit-card ${attention?'attention':''}"><div><b>${esc(habit.profile_name)}</b><span>${habit.status==='monitoring'?'正在聚合本轮活动':'本轮专注复盘'}</span></div><dl class="${basic?'basic':''}">${metrics}</dl>${appRows}<small>${attention?'切换次数较多，建议暂停并整理工作环境 · ':''}${basic?'活跃占比':'专注质量'} ${habit.quality_score??100}% · 当前 ${esc(habit.last_process_name||'等待采样')}</small></div>`
}
function updateFocusTaskIndicators(){
  const focus=state.focus;if(!focus||focus.session_type!=='focus')return;
  const task=focusTask();if(!task)return;
  const elapsed=focusElapsed(focus),progress=taskDisplayProgress(task),free=task.task_kind==='free_learning';
  $$(`[data-focus-task-live="${task.id}"]`).forEach(node=>{
    const label=node.querySelector('span'),time=node.querySelector('time'),value=node.querySelector('b');
    if(label)label.innerHTML=`<i></i>${focus.status==='paused'?'专注已暂停':focus.status==='awaiting_action'?'等待确认':'正在专注'}`;
    if(time)time.textContent=focusClock(elapsed);
    if(value)value.textContent=free?'持续投入':`${progress}%`;
  });
  $$(`[data-task-progress="${task.id}"]`).forEach(node=>{
    node.title=free?'完成度由你手动记录':`完成度 ${progress}%`;
    const bar=node.querySelector('i');if(bar)bar.style.width=`${progress}%`;
  });
  const paragraph=$('[data-active-focus-banner] p');
  if(paragraph)paragraph.innerHTML=focusBannerMetrics(task,focus);
}
let focusDraftSaveTimer=null;
function persistFocusDraft(){const draft={taskId:state.focusDraft.taskId,preset:state.focusDraft.preset,mode:state.focusDraft.mode,minutes:state.focusDraft.minutes,habitProfileId:state.focusDraft.habitProfileId};clearTimeout(focusDraftSaveTimer);focusDraftSaveTimer=setTimeout(()=>api('/api/settings/focus-draft',{method:'PUT',body:JSON.stringify(draft)}).catch(showError),250)}
function captureFocusDraft(){const task=$('#focus-task'),mode=$('#focus-mode'),minutes=$('#focus-custom-minutes'),habit=$('#focus-habit');if(task)state.focusDraft.taskId=task.value;if(mode)state.focusDraft.mode=mode.value;if(minutes){const next=Math.max(1,Math.min(720,Number(minutes.value)||25));if(next!==state.focusDraft.minutes)state.focusDraft.preset='custom';state.focusDraft.minutes=next}if(habit)state.focusDraft.habitProfileId=habit.value;persistFocusDraft()}
function openFocus(taskId='',planBlockId=''){
  if(taskId)state.focusDraft.taskId=taskId;
  if(planBlockId)state.focusDraft.planBlockId=planBlockId;
  const task=state.tasks.find(item=>item.id===taskId);
  if(task&&!state.focus&&!planBlockId&&task.task_kind==='free_learning'){
    state.focusDraft.preset='custom';state.focusDraft.mode='pomodoro';
    state.focusDraft.minutes=Math.min(720,Math.max(1,Number(task.estimated_minutes||60)-Number(task.actual_minutes||0)));
    persistFocusDraft();
  }
  const panel=$('#focus-panel');panel.classList.remove('hidden');renderFocusPanel();
}
function closeFocus(){captureFocusDraft();$('#focus-panel').classList.add('hidden')}
function manageFocusHabits(){captureFocusDraft();closeFocus();openSettings('focus');setTimeout(()=>$('.habit-settings')?.scrollIntoView({block:'start',behavior:'smooth'}),80)}
function clearFocus(){state.focus=null;state.focusWarningPlayed=false;document.title='研途 · 研究生个人工作台';renderFocusPanel()}
function focusTone(kind='done'){if(!state.preferences?.sound_enabled)return;try{const context=new AudioContext(),gain=context.createGain(),osc=context.createOscillator();gain.gain.value=(state.preferences.volume||60)/500;osc.frequency.value=kind==='warning'?660:kind==='break'?440:880;osc.connect(gain);gain.connect(context.destination);osc.start();gain.gain.exponentialRampToValueAtTime(.0001,context.currentTime+.45);osc.stop(context.currentTime+.46)}catch{}}
function focusNotify(title,body){if(state.preferences?.notification_enabled&&'Notification'in window&&Notification.permission==='granted'){try{new Notification(title,{body,icon:'/assets/logo-192.png'});return}catch{}}toast(`${title} · ${body}`)}
function renderFocusPanel(){
  const panel=$('#focus-panel');if(panel.classList.contains('hidden'))return;
  const activeTasks=state.tasks.filter(active).sort(sortTasks);
  if(!state.focus){
    const profile=state.planningProfile||{focus_minutes:25},stats=state.focusStats||{},todayMinutes=(stats.by_day||[]).find(item=>item.date===today())?.minutes||0;
    const selected=activeTasks.some(task=>task.id===state.focusDraft.taskId)?state.focusDraft.taskId:(activeTasks[0]?.id||''),selectedHabit=state.focusHabits.some(item=>item.id===state.focusDraft.habitProfileId)?state.focusDraft.habitProfileId:(state.focusDraft.habitProfileId==='__off__'?'__off__':'__default__');
    state.focusDraft.taskId=selected;state.focusDraft.habitProfileId=selectedHabit;
    const preset=state.focusDraft.preset||'planning',usesPlanning=preset==='planning',minutes=usesPlanning?Number(profile.focus_minutes):Math.max(1,Math.min(720,Number(state.focusDraft.minutes)||profile.focus_minutes)),mode=usesPlanning?(profile.use_pomodoro?'pomodoro':'free'):(preset==='free'?'free':'pomodoro');
    const monitorHint=selectedHabit==='__default__'?'默认记录所有前台应用的输入活跃与空闲时长':selectedHabit==='__off__'?'本轮已关闭应用监测':`本轮将应用“${esc(state.focusHabits.find(item=>item.id===selectedHabit)?.name||'习惯方案')}”`;
    panel.innerHTML=`<div class="focus-head"><div><i></i><small>FOCUS DECK // READY</small><strong>专注工作台</strong></div><div class="focus-head-actions"><button id="focus-expand" aria-label="沉浸模式">${state.focusImmersive?'↙':'↗'}</button><button id="focus-close" aria-label="关闭专注面板">×</button></div></div><div class="focus-dashboard"><div class="focus-metrics"><div><strong>${todayMinutes}分</strong><span>今日专注</span></div><div><strong>${stats.focus_minutes||0}分</strong><span>近 7 天</span></div><div><strong>${stats.pomodoros||0}</strong><span>完成番茄</span></div><div><strong>${stats.plan_completion_rate||0}%</strong><span>规划完成率</span></div></div><div class="focus-setup">${state.focusHabitResult?habitSummary(state.focusHabitResult):''}<label><span>关联任务</span><select id="focus-task">${activeTasks.map(task=>`<option value="${task.id}" ${task.id===selected?'selected':''}>${esc(task.title)}</option>`).join('')}</select></label><div class="focus-preset-row"><button type="button" data-focus-preset="25" class="${preset==='25'?'active':''}">25 分钟</button><button type="button" data-focus-preset="50" class="${preset==='50'?'active':''}">50 分钟</button><button type="button" data-focus-preset="planning" class="${usesPlanning?'active':''}">规划偏好 · ${profile.use_pomodoro?`${profile.focus_minutes}/${profile.short_break_minutes}`:'自由'}</button><button type="button" data-focus-preset="free" class="${preset==='free'?'active':''}">自由计时</button></div><label id="focus-minutes-field" class="${mode==='free'?'hidden':''}"><span>本轮专注分钟</span><input id="focus-custom-minutes" type="number" min="1" max="720" value="${minutes}"></label><label><span>应用监测</span><select id="focus-habit"><option value="__default__" ${selectedHabit==='__default__'?'selected':''}>基础监测（默认，无需方案）</option><option value="__off__" ${selectedHabit==='__off__'?'selected':''}>关闭应用监测</option>${state.focusHabits.map(item=>`<option value="${item.id}" ${item.id===selectedHabit?'selected':''}>${esc(item.name)} · ${item.allowed_apps.length} 个目标应用</option>`).join('')}</select></label><input type="hidden" id="focus-mode" value="${mode}"><div class="focus-helper-row"><span>${monitorHint}</span><button type="button" id="focus-manage-habits">${state.focusHabits.length?'管理方案':'创建筛选方案'}</button></div><button class="focus-primary" id="focus-start">${activeTasks.length?'启动专注':'先新建一个任务'}</button><div class="focus-shortcuts"><span><kbd>Q</kbd> 新建任务</span><span><kbd>F</kbd> 打开专注</span><span><kbd>Esc</kbd> 收起</span></div></div></div>`;
    bindFocusChrome();$('#focus-manage-habits').onclick=manageFocusHabits;$('#focus-start').onclick=activeTasks.length?startFocus:()=>{closeFocus();openDialog()};
    $('#focus-task').onchange=event=>{if(state.focusDraft.taskId!==event.target.value)state.focusDraft.planBlockId='';state.focusDraft.taskId=event.target.value;persistFocusDraft()};$('#focus-habit').onchange=event=>{state.focusDraft.habitProfileId=event.target.value;persistFocusDraft();renderFocusPanel()};$('#focus-custom-minutes').onchange=event=>{state.focusDraft.preset='custom';state.focusDraft.minutes=Math.max(1,Math.min(720,Number(event.target.value)||25));event.target.value=state.focusDraft.minutes;persistFocusDraft()};
    $$('[data-focus-preset]').forEach(button=>button.onclick=()=>{const value=button.dataset.focusPreset;state.focusDraft.preset=value;state.focusDraft.mode=value==='free'||(value==='planning'&&!profile.use_pomodoro)?'free':'pomodoro';if(['25','50'].includes(value))state.focusDraft.minutes=Number(value);if(value==='planning')state.focusDraft.minutes=profile.focus_minutes;persistFocusDraft();renderFocusPanel()});return
  }
  const elapsed=focusElapsed(),isBreak=state.focus.session_type!=='focus',target=Number(state.focus.target_seconds||0),remaining=state.focus.mode==='free'?elapsed:Math.max(0,target-elapsed),progress=state.focus.mode==='free'?0:Math.min(1,elapsed/Math.max(1,target)),task=focusTask(),awaiting=state.focus.status==='awaiting_action';
  const label=isBreak?'RECOVERY // BREAK':state.focus.mode==='free'?'FLOW // OPEN TIMER':'FOCUS // DEEP WORK';
  document.title=`${focusClock(remaining)} · ${isBreak?'休息':task?.title||'专注'}`;
  const finishLabel=isBreak?'结束休息':task?.task_kind==='free_learning'?'结束本轮并记录':(!awaiting&&state.focus.mode==='pomodoro'&&elapsed<target?'提前结束并记录':'完成并记录');
  panel.innerHTML=`<div class="focus-head"><div><i class="${state.focus.status==='running'?'live':''}"></i><small>${label}</small><strong>${isBreak?(state.focus.session_type==='long_break'?'长休息':'短休息'):esc(task?.title||'专注任务')}</strong></div><div class="focus-head-actions"><button id="focus-expand" aria-label="沉浸模式">${state.focusImmersive?'↙':'↗'}</button><button id="focus-close" aria-label="收起专注面板">×</button></div></div><div class="focus-active"><div class="focus-phase-rail"><span class="done">准备</span><i></i><span class="current">${isBreak?'恢复':'专注'}</span><i></i><span>下一轮</span></div><div class="focus-orbit" style="--focus-progress:${progress*360}deg"><div><time>${focusClock(remaining)}</time><span>${awaiting?'等待确认':state.focus.status==='running'?(isBreak?'恢复中':'专注中'):'已暂停'}</span></div></div><p>${awaiting?(isBreak?'休息计时已结束，准备好后返回任务。':'本轮已到时，由你确认是否记入实际投入。'):isBreak?'离开屏幕、活动肩颈，让注意力真正恢复。':state.focus.mode==='free'?'自由计时不会强制打断当前心流。':`完成后将按偏好进入休息，本轮已暂停 ${state.focus.pause_count||0} 次。`}</p>${isBreak&&state.focusHabitResult?habitSummary(state.focusHabitResult):!isBreak&&state.focus.habit?habitSummary(state.focus.habit):''}<div class="focus-actions"><button id="focus-pause" ${awaiting?'disabled':''}>${state.focus.status==='running'?'暂停':'继续'}</button><button class="focus-primary" id="focus-finish">${finishLabel}</button><button class="focus-ghost" id="focus-discard">放弃</button></div><div class="focus-shortcuts"><span><kbd>Space</kbd> 暂停/继续</span><span><kbd>Ctrl + Enter</kbd> 结束</span><span><kbd>Esc</kbd> 收起</span></div></div>`;
  bindFocusChrome();$('#focus-pause').onclick=toggleFocusPause;$('#focus-finish').onclick=finishFocus;$('#focus-discard').onclick=discardFocus;
}
async function openDesktopFocusWidget(){
  if(!state.focus)return toast('先启动一轮专注，再打开桌面小窗');
  const bridge=window.pywebview?.api;
  if(!bridge?.show_widget)return toast('桌面小窗仅在 Windows 桌面版可用');
  try{if(!await bridge.show_widget())toast('当前没有可显示的活动计时')}catch(error){showError(error)}
}
function bindFocusChrome(){
  const actions=$('.focus-head-actions'),button=document.createElement('button');
  button.id='focus-widget-toggle';button.type='button';button.textContent='▣';
  button.title='打开独立的桌面专注小窗';button.setAttribute('aria-label','打开桌面专注小窗');
  button.onclick=openDesktopFocusWidget;actions.prepend(button);
  $('#focus-close').onclick=closeFocus;
  $('#focus-expand').onclick=()=>{state.focusImmersive=!state.focusImmersive;$('#focus-panel').classList.toggle('immersive',state.focusImmersive);renderFocusPanel()}
}
async function startFocus(){captureFocusDraft();const taskId=state.focusDraft.taskId,usePlanning=state.focusDraft.preset==='planning',mode=usePlanning?(state.planningProfile?.use_pomodoro?'pomodoro':'free'):state.focusDraft.mode,minutes=usePlanning?state.planningProfile?.focus_minutes:state.focusDraft.minutes,habitSelection=state.focusDraft.habitProfileId||'__default__',monitorApps=habitSelection!=='__off__',habitProfileId=state.focusHabits.some(item=>item.id===habitSelection)?habitSelection:null;if(!taskId)return;try{const data=await api('/api/focus/sessions',{method:'POST',body:JSON.stringify({task_id:taskId,plan_block_id:state.focusDraft.planBlockId||null,mode,target_seconds:mode==='free'?0:Math.round(minutes*60),use_planning_profile:usePlanning,monitor_apps:monitorApps,habit_profile_id:habitProfileId})});state.focus=data.session;state.focusDraft.planBlockId='';state.focusHabitResult=null;const task=state.tasks.find(item=>item.id===taskId);if(task&&['not_started','waiting'].includes(task.status))task.status='in_progress';state.focusWarningPlayed=false;focusTone('start');render();renderFocusPanel();updateFocusTaskIndicators();toast(`${usePlanning?'规划偏好已应用 · ':''}${mode==='free'?'自由专注':`${minutes} 分钟番茄钟`}已开始${monitorApps?(habitProfileId?' · 筛选方案已开启':' · 基础应用监测已开启'):' · 未监测应用'}`)}catch(error){showError(error)}}
async function toggleFocusPause(){if(!state.focus)return;try{const action=state.focus.status==='paused'?'resume':'pause',data=await api(`/api/focus/sessions/${state.focus.id}/${action}`,{method:'POST'});state.focus=data.session;renderFocusPanel();updateFocusTaskIndicators()}catch(error){showError(error)}}
async function finishFocus(){
  if(!state.focus||state.focusSaving)return;
  const elapsed=focusElapsed(),target=Number(state.focus.target_seconds||0);
  const learning=focusTask()?.task_kind==='free_learning';
  const early=state.focus.session_type==='focus'&&state.focus.mode==='pomodoro'&&!learning&&state.focus.status!=='awaiting_action'&&elapsed<target;
  if(early&&!confirm(`本轮还剩 ${focusClock(target-elapsed)}。确定提前结束并记录已投入时间？`))return;
  state.focusSaving=true;
  const wasBreak=state.focus.session_type!=='focus';
  try{
    const data=await api(`/api/focus/sessions/${state.focus.id}/complete`,{method:'POST'});
    if(data.habit_result)state.focusHabitResult=data.habit_result;
    state.focus=data.next_session||null;
    focusTone(wasBreak?'done':'break');
    focusNotify(wasBreak?'休息结束':'本轮专注已记录',wasBreak?'准备好后开始下一轮。':state.focus?'现在进入恢复时间。':'实际投入已同步到任务。');
    await loadTasks({migrate:false});
    if(state.focus)openFocus();else renderFocusPanel();
  }catch(error){showError(error)}finally{state.focusSaving=false}
}
async function discardFocus(){if(!state.focus||!confirm('放弃本次计时且不记录投入？'))return;try{await api(`/api/focus/sessions/${state.focus.id}/cancel`,{method:'POST',body:JSON.stringify({record_partial:false})});clearFocus();await loadTasks({migrate:false});toast('本次计时已放弃')}catch(error){showError(error)}}
async function tickFocus(){
  if(!state.focus||state.focusSaving)return;
  const elapsed=focusElapsed(),target=Number(state.focus.target_seconds||0),remaining=target-elapsed;
  const learning=focusTask()?.task_kind==='free_learning';
  if(state.focus.habit&&Date.now()-state.focusHabitLastRefresh>5000){
    state.focusHabitLastRefresh=Date.now();
    try{const data=await api(`/api/focus/sessions/${state.focus.id}/habit`);state.focus.habit=data.habit}catch{}
  }
  if(state.focus.mode==='pomodoro'&&state.focus.status==='running'&&remaining<=60&&remaining>0&&!state.focusWarningPlayed){
    state.focusWarningPlayed=true;focusTone('warning');toast(learning?'还剩 1 分钟，当前学习时段将自动延长':'还剩 1 分钟，准备收尾');
  }
  if(state.focus.mode==='pomodoro'&&state.focus.status==='running'&&remaining<=0&&!state.focus.expiry_checked){
    state.focus.expiry_checked=true;
    try{
      const data=await api('/api/focus/active');
      state.focus=data.session;
      if(learning&&state.focus?.status==='running'&&Number(state.focus.target_seconds)>target){
        state.focusWarningPlayed=false;
        toast(`学习时段已自动延长 ${Math.round((Number(state.focus.target_seconds)-target)/3600)} 小时，可继续阅读`);
      }else if(state.focus){
        focusTone('done');
        focusNotify(state.focus.session_type==='focus'?'专注时间到':'休息时间到','请回到 Yantu 确认下一步。');
      }
    }catch(error){showError(error)}
  }
  renderFocusPanel();updateFocusTaskIndicators();
}

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

$('#task-form').onsubmit=async event=>{event.preventDefault();try{const id=$('#task-id').value,payload=formPayload(),conflicts=timeBlockConflicts(payload,id);if(conflicts.length&&!confirm(`检测到 ${conflicts.length} 个时间重叠，仍要保存这个时间段任务吗？`))return;if(id)await patchTask(id,payload);else await createTask(payload);if(payload.schedule_mode==='time_block')await loadTasks({migrate:false});closeDialog();toast(id?'任务已更新':'任务已创建')}catch(error){showError(error)}};
$('#delete-btn').onclick=async()=>{const id=$('#task-id').value;if(!id)return;try{closeDialog();await trashTask(id)}catch(error){showError(error)}};
$('#add-btn').onclick=()=>openDialog();
$('#focus-btn').onclick=()=>openFocus();
$('#settings-btn').onclick=()=>openSettings();
$('#close-settings').onclick=closeSettings;$('#cancel-settings').onclick=closeSettings;$('#settings-form').onsubmit=savePreferences;
$$('[data-settings-tab]').forEach(button=>button.onclick=()=>selectSettingsTab(button.dataset.settingsTab));
$('#setting-volume').oninput=event=>{$('#setting-volume-output').textContent=`${event.target.value}%`};
$('#habit-new').onclick=resetHabitForm;$('#habit-save').onclick=saveHabitProfile;$('#habit-current-app').onclick=addCurrentHabitApp;
$('#toggle-ai-key').onclick=()=>{const input=$('#ai-api-key'),show=input.type==='password';input.type=show?'text':'password';$('#toggle-ai-key').textContent=show?'隐藏':'显示'};
$('#save-ai-settings').onclick=saveAiSettings;$('#test-ai-key').onclick=testAiSettings;$('#delete-ai-key').onclick=deleteAiKey;
$('#zotero-access-mode').onchange=updateZoteroFields;$('#zotero-library-type').onchange=updateZoteroFields;$('#toggle-zotero-key').onclick=()=>{const input=$('#zotero-api-key'),show=input.type==='password';input.type=show?'text':'password';$('#toggle-zotero-key').textContent=show?'隐藏':'显示'};$('#save-zotero').onclick=saveZoteroConnection;$('#test-zotero').onclick=testZoteroConnection;$('#sync-zotero').onclick=syncZoteroFromSettings;$('#delete-zotero-key').onclick=deleteZoteroKey;
$('#open-planning-settings').onclick=()=>{closeSettings();openPlanningDialog()};
$('#close-dialog').onclick=closeDialog;
$('#cancel-btn').onclick=closeDialog;
$('#open-quick-reading').onclick=openQuickReading;
$('#close-quick-reading').onclick=()=>$('#quick-reading-dialog').close();
$('#cancel-quick-reading').onclick=()=>$('#quick-reading-dialog').close();
$('#quick-paper-search').oninput=fillQuickPaperOptions;
$('#quick-reading-form').onsubmit=event=>{event.preventDefault();const paperId=$('#quick-paper').value;if(paperId)quickStartReading(paperId,$('#quick-task-title').value)};
$('#task-recurring').onchange=event=>{$('#task-recurrence').disabled=!event.target.checked};
$('#task-block-weekly').onchange=event=>{$('#task-block-until').disabled=!event.target.checked;if(event.target.checked&&!$('#task-block-until').value)$('#task-block-until').value=iso(addDays(parseDate($('#task-block-date').value||today()),112))};
$('#task-domain').onchange=()=>updateTaskPaperField(Boolean($('#task-id').value));
$('#task-kind').onchange=updateTaskKindField;
$('#task-status').onchange=event=>{if(event.target.value==='completed')$('#task-progress').value=100};
$$('.nav-item').forEach(button=>button.onclick=async()=>{state.view=button.dataset.view;$('.sidebar').classList.remove('open');try{if(state.view==='trash')state.trash=await api('/api/trash');if(state.view==='focus_analytics')await loadFocusAnalytics(false)}catch(error){showError(error)}render()});
$('#status-filter').onchange=event=>{state.status=event.target.value;render()};
$('#subcategory-filter').onchange=event=>{state.subcategory=event.target.value;render()};
$('#menu-btn').onclick=()=>$('.sidebar').classList.toggle('open');
$('#export-btn').onclick=async()=>{try{const data=await api('/api/export');const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const anchor=document.createElement('a');anchor.href=URL.createObjectURL(blob);anchor.download=`Yantu备份-${today()}.json`;anchor.click();URL.revokeObjectURL(anchor.href);toast('备份已导出')}catch(error){showError(error)}};
$('#import-file').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;const data=JSON.parse(await file.text());if(!Array.isArray(data.tasks))throw new Error('备份文件中没有任务列表');if(!confirm(`将合并导入 ${data.tasks.length} 个任务，是否继续？`))return;await api('/api/import',{method:'POST',body:JSON.stringify(data)});await loadTasks({migrate:false});toast('备份已导入')}catch(error){showError(error)}finally{event.target.value=''}};

$('#schedule-form').onsubmit=async event=>{event.preventDefault();const file=$('#schedule-file').files[0];if(!file)return;if(!$('#semester-start-confirm').checked)return showError(new Error('请先确认教学第 1 周第一天'));const form=new FormData();form.append('file',file);form.append('config',JSON.stringify({semester:{name:$('#semester-name').value.trim(),stage_label:$('#semester-stage').value.trim(),start_date:$('#semester-start').value,end_date:$('#semester-end').value}}));const button=$('#recognize-schedule');button.disabled=true;button.textContent='正在本地识别…';try{const data=await api('/api/schedule-import/preview',{method:'POST',body:form});state.schedulePreview=data.preview;renderSchedulePreview()}catch(error){showError(error)}finally{button.disabled=false;button.textContent='识别并预览'}};
$('#close-schedule-dialog').onclick=()=>$('#schedule-dialog').close();$('#cancel-schedule').onclick=()=>$('#schedule-dialog').close();
$('#semester-indicator').onclick=()=>openSemesterDialog(currentSemester()?.id);$('#close-semester-dialog').onclick=()=>$('#semester-dialog').close();$('#cancel-semester-edit').onclick=()=>$('#semester-dialog').close();
$('#semester-form').onsubmit=async event=>{event.preventDefault();const id=$('#edit-semester-id').value,existing=state.semesters.find(item=>item.id===id);if(!existing)return;try{await api(`/api/semesters/${id}`,{method:'PUT',body:JSON.stringify({...existing,name:$('#edit-semester-name').value.trim(),stage_label:$('#edit-semester-stage').value.trim(),start_date:$('#edit-semester-start').value,end_date:$('#edit-semester-end').value})});$('#semester-dialog').close();await loadTasks({migrate:false});toast('学期已更新，课程日期已重新计算')}catch(error){showError(error)}};
$('#course-form').onsubmit=async event=>{event.preventDefault();const id=$('#course-id').value,first={...(editingCourseMeetings[0]||{}),weekday:Number($('#course-weekday').value),start_period:Number($('#course-start-period').value),end_period:Number($('#course-end-period').value),start_time:$('#course-start-time').value,end_time:$('#course-end-time').value,start_week:Number($('#course-start-week').value),end_week:Number($('#course-end-week').value),week_pattern:$('#course-week-pattern').value,custom_weeks:[]};try{await api(`/api/courses/${id}`,{method:'PUT',body:JSON.stringify({name:$('#course-name').value.trim(),teacher:$('#course-teacher').value.trim(),location:$('#course-location').value.trim(),notes:$('#course-notes').value.trim(),meetings:[first,...editingCourseMeetings.slice(1)]})});$('#course-dialog').close();await loadTasks({migrate:false});toast('课程已更新')}catch(error){showError(error)}};
$('#close-course-dialog').onclick=()=>$('#course-dialog').close();$('#cancel-course').onclick=()=>$('#course-dialog').close();
$('#research-task-form').onsubmit=confirmResearchTask;$('#close-research-task').onclick=closeResearchTask;$('#cancel-research-task').onclick=closeResearchTask;
$('#research-import-form').onsubmit=confirmResearchImport;$('#close-research-import').onclick=closeResearchImport;$('#cancel-research-import').onclick=closeResearchImport;$('#preview-research-import').onclick=previewResearchImport;$('#research-import-mode').onchange=updateResearchImportMode;$('#research-import-source').onchange=loadZoteroCollections;
$('#planning-form').onsubmit=confirmPlanning;$('#save-planning-profile').onclick=savePlanningProfile;$('#preview-planning').onclick=previewPlanning;$('#close-planning').onclick=closePlanningDialog;$('#cancel-planning').onclick=closePlanningDialog;
$('#appearance-btn').onclick=()=>{closeSettings();openAppearance()};$('#close-appearance').onclick=cancelAppearance;$('#cancel-appearance').onclick=cancelAppearance;$('#appearance-form').onsubmit=saveAppearance;
$$('#appearance-form input[name="appearance-mode"],#appearance-form input[name="appearance-preset"],#appearance-form input[type="color"],#appearance-form input[type="range"],#appearance-background-type').forEach(control=>{control.oninput=()=>previewAppearance().catch(showError);control.onchange=()=>previewAppearance().catch(showError)});
$('#appearance-image-file').onchange=event=>{const file=event.target.files[0];if(!file)return;if(file.size>8*1024*1024||!['image/png','image/jpeg','image/webp'].includes(file.type)){event.target.value='';return showError(new Error('请选择不超过 8 MB 的 PNG、JPG 或 WebP 图片'))}clearAppearancePreview();state.appearanceImageFile=file;state.appearanceRemoveImage=false;$('#appearance-background-type').value='image';previewAppearance().catch(showError)};
$('#remove-background').onclick=()=>{state.appearanceRemoveImage=true;state.appearanceImageFile=null;$('#appearance-image-file').value='';$('#appearance-background-type').value='none';previewAppearance().catch(showError)};
$('#reset-appearance').onclick=()=>{if(!confirm('恢复默认外观？保存前仍可取消。'))return;clearAppearancePreview();state.appearanceDraft=clone(APPEARANCE_DEFAULT);state.appearanceImageFile=null;state.appearanceRemoveImage=state.appearance.has_background_image;fillAppearanceForm(state.appearanceDraft);previewAppearance().catch(showError)};
const systemTheme=matchMedia('(prefers-color-scheme: dark)');systemTheme.addEventListener?.('change',()=>{if(state.appearance.mode==='system'&&!$('#appearance-dialog').open)applyAppearance(state.appearance,{cache:true});else if(state.appearanceDraft?.mode==='system')previewAppearance()});
document.addEventListener('click',event=>{if(!event.target.closest('#context-menu')&&!event.target.closest('[data-task-menu]')&&!event.target.closest('[data-course-menu]'))closeContextMenu()});
document.addEventListener('keydown',event=>{const menu=$('#context-menu'),panel=$('#focus-panel'),typing=['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName),dialogOpen=Boolean($('dialog[open]')),key=event.key.toLowerCase();if(event.key==='Escape'){closeContextMenu();if(!panel.classList.contains('hidden'))closeFocus()}if(!typing&&!dialogOpen){if(!panel.classList.contains('hidden')&&state.focus){if(event.code==='Space'&&!['awaiting_action','completed','cancelled'].includes(state.focus.status)){event.preventDefault();toggleFocusPause()}if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();finishFocus()}}else{if(key==='q'){event.preventDefault();if(!panel.classList.contains('hidden'))closeFocus();openDialog()}if(key==='f'&&panel.classList.contains('hidden')){event.preventDefault();openFocus()}if(event.key==='?')toast('快捷键：Q 新建任务 · F 打开专注 · 专注中 Space 暂停 · Ctrl+Enter 结束')}}if(!menu.classList.contains('hidden')&&['ArrowDown','ArrowUp'].includes(event.key)){event.preventDefault();const buttons=[...menu.querySelectorAll('button')],index=buttons.indexOf(document.activeElement),step=event.key==='ArrowDown'?1:-1;buttons[(index+step+buttons.length)%buttons.length]?.focus()}});
window.addEventListener('scroll',closeContextMenu,true);window.addEventListener('resize',closeContextMenu);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshTemporalViews().catch(showError)});

restoreFocus();setInterval(()=>tickFocus().catch(showError),1000);
setInterval(()=>refreshTemporalViews().catch(showError),60000);
loadAppearance().catch(error=>{console.warn('外观设置加载失败，使用研林主题',error);state.appearance=clone(APPEARANCE_DEFAULT);applyAppearance(state.appearance,{cache:true})});
loadTasks().catch(error=>{state.loading=false;$('#content').innerHTML=`<div class="empty error"><strong>无法连接 Yantu 后端</strong>${esc(error.message)}<br>请保留启动窗口并查看其中的错误信息。</div>`;showError(error)});
