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

let state={view:'today',status:'all',subcategory:'all',month:new Date(),tasks:[],loading:true,aiStatus:null,aiPreview:null,aiLoading:false};

async function api(path,options={}){
  const response=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});
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
  const data=await api('/api/tasks');
  state.tasks=data.tasks;
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
  else if(state.view==='inbox')content.innerHTML=renderInbox();
  else content.innerHTML=renderDomain(state.view);
  bindDynamic();
}

function updateChrome(){
  const titles={today:'今日',inbox:'收件箱',research:'科研工作台',course:'课程学习',personal:'个人生活',week:'未来 7 天',month:'月历'};
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
  const planned=tasks.filter(task=>active(task)&&(task.start_date===today()||task.due_date===today())&&!mustIds.has(task.id)).sort(sortTasks);
  const overdue=tasks.filter(isOverdue).sort(sortTasks);
  const upcoming=tasks.filter(task=>active(task)&&task.due_date>today()).sort(sortTasks).slice(0,8);
  const todayTasks=[...must,...planned];
  const estimate=todayTasks.reduce((sum,task)=>sum+(Number(task.estimated_minutes)||0),0);
  const finished=tasks.filter(task=>task.status==='completed'&&task.completed_at&&iso(new Date(task.completed_at))===today()).length;
  const inbox=state.tasks.filter(task=>task.domain==='inbox'&&active(task)).sort(sortTasks).slice(0,5);
  return `<form class="quick-capture compact" id="quick-form"><div><strong>快速收件箱</strong><span>先记下导师临时任务或突然出现的想法，稍后再整理。</span></div><input id="quick-title" maxlength="160" required placeholder="刚想到什么？"><button class="primary-btn" type="submit">记下来</button></form><div class="summary-grid">
    <div class="summary-card hero"><p>今日工作面</p><strong>${todayTasks.length}</strong><span>${must.length} 项必须完成 · ${planned.length} 项计划推进</span></div>
    <div class="summary-card"><p>今日计划投入</p><strong>${fmtDuration(estimate)}</strong><span>科研与课程注意留出缓冲</span></div>
    <div class="summary-card"><p>今日已完成</p><strong>${finished}</strong><span>${overdue.length?`仍有 ${overdue.length} 项逾期`:'当前没有逾期任务'}</span></div>
  </div>
  ${listSection('今天必须完成',must,'没有必须今天完成的高优先级任务。')}
  ${listSection('今天计划完成',planned,'尚未安排今天的任务。')}
  ${listSection('已逾期任务',overdue,'很好，目前没有逾期任务。')}
  ${listSection('最近截止任务',upcoming,'近期没有明确 Deadline。')}
  ${listSection('收件箱待整理',inbox,'收件箱已经清空。')}`;
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

function listSection(title,tasks,emptyText='暂无任务'){
  return `<div class="section-head"><h2>${title}</h2><span>${tasks.length} 项</span></div>${tasks.length?`<div class="task-list">${tasks.map(taskCard).join('')}</div>`:`<div class="empty"><strong>这里暂时是空的</strong>${emptyText}</div>`}`;
}

function taskCard(task){
  const done=task.status==='completed';
  const meta=[DOMAINS[task.domain],task.subcategory,task.due_date?`截止 ${fmtDate(task.due_date)}`:'无 Deadline',fmtDuration(task.estimated_minutes)].filter(Boolean).join(' · ');
  return `<article class="task-card ${task.domain} ${done?'done':''} ${isOverdue(task)?'overdue':''}">
    <input class="check" type="checkbox" aria-label="标记完成" data-check="${task.id}" ${done?'checked':''} ${task.status==='cancelled'?'disabled':''}>
    <div class="task-main"><div class="task-title-row"><h3>${esc(task.title)}</h3><span class="status-badge ${task.status}">${STATUSES[task.status]}</span>${task.is_recurring?'<span class="badge">重复</span>':''}</div><p>${esc(meta)}</p>${task.description?`<p class="description">${esc(task.description)}</p>`:''}${task.tags?.length?`<div class="tag-row">${task.tags.map(tag=>`<span>#${esc(tag)}</span>`).join('')}</div>`:''}<div class="progress-track" title="完成度 ${task.progress}%"><i style="width:${task.progress}%"></i></div></div>
    <div class="task-controls"><select data-priority="${task.id}" aria-label="修改优先级" class="priority-select ${task.priority}">${Object.entries(PRIORITIES).map(([key,label])=>`<option value="${key}" ${key===task.priority?'selected':''}>${label}优先级</option>`).join('')}</select><input type="date" data-due="${task.id}" value="${task.due_date||''}" aria-label="修改截止日期"><button class="edit-btn" data-edit="${task.id}" aria-label="编辑任务">编辑</button></div>
  </article>`;
}

function renderWeek(){
  const start=new Date();start.setHours(0,0,0,0);
  const days=Array.from({length:7},(_,index)=>addDays(start,index));
  const tasks=state.tasks.filter(matchesFilters);
  return `<div class="week-grid">${days.map((day,index)=>{const date=iso(day);const daily=tasks.filter(task=>task.start_date===date||task.due_date===date).sort(sortTasks);return `<div class="day-column"><div class="day-head ${index===0?'today':''}">${['周日','周一','周二','周三','周四','周五','周六'][day.getDay()]}<strong>${day.getMonth()+1}/${day.getDate()}</strong></div>${daily.length?daily.map(task=>`<button class="mini-task ${task.domain} ${task.status==='completed'?'done':''}" data-edit="${task.id}"><b>${esc(task.title)}</b><span>${task.due_date===date?'Deadline':'计划开始'} · ${PRIORITIES[task.priority]}优先级</span></button>`).join(''):'<p class="day-empty">留白</p>'}</div>`}).join('')}</div>`;
}

function monthStart(date){const first=new Date(date.getFullYear(),date.getMonth(),1);const day=first.getDay()||7;first.setDate(first.getDate()-day+1);return first}
function renderMonth(){
  const year=state.month.getFullYear(),month=state.month.getMonth(),start=monthStart(state.month);
  const days=Array.from({length:42},(_,index)=>addDays(start,index));
  const tasks=state.tasks.filter(matchesFilters);
  const noDeadline=tasks.filter(task=>active(task)&&!task.due_date&&['urgent','high'].includes(task.priority)).sort(sortTasks);
  return `<div class="month-nav"><button id="prev-month">‹ 上个月</button><h2>${year} 年 ${month+1} 月</h2><button id="next-month">下个月 ›</button></div><div class="calendar">${['一','二','三','四','五','六','日'].map(day=>`<div class="calendar-weekday">周${day}</div>`).join('')}${days.map(day=>{const date=iso(day);const daily=tasks.filter(task=>task.due_date===date).sort(sortTasks);return `<div class="calendar-day ${day.getMonth()!==month?'outside':''} ${date===today()?'today':''}"><span class="num">${day.getDate()}</span>${daily.slice(0,4).map(task=>`<button class="cal-task ${task.domain}" data-edit="${task.id}">${task.status==='completed'?'✓ ':''}${esc(task.title)}</button>`).join('')}${daily.length>4?`<div class="cal-more">另 ${daily.length-4} 项</div>`:''}</div>`}).join('')}</div>${listSection('高优先级但尚无 Deadline',noDeadline,'目前没有需要补充 Deadline 的高优先级任务。')}`;
}

function renderAI(){
  const status=state.aiStatus||{configured:false};
  const statusText=status.configured
    ? `已连接 ${esc(status.provider)} · ${esc(status.model)}`
    : '尚未配置 API Key。请复制 .env.example 为 .env，并填写 DEEPSEEK_API_KEY。';
  const preview=state.aiPreview;
  return `<section class="ai-workbench">
    <div class="ai-hero"><div><p>人工智能辅助规划</p><h2>先预览，再由你决定是否写入任务库</h2><span>${statusText}</span></div><b class="ai-status ${status.configured?'ready':''}">${status.configured?'可用':'待配置'}</b></div>
    <form id="ai-form" class="ai-form"><label class="field full"><span>需要拆解的任务</span><textarea id="ai-task" rows="4" maxlength="1000" required placeholder="例如：准备下个月激光雷达组会汇报">${esc(preview?.source||'')}</textarea></label><button class="primary-btn" type="submit" ${state.aiLoading?'disabled':''}>${state.aiLoading?'正在生成…':'生成拆解预览'}</button></form>
    ${preview?`<div class="ai-preview"><div class="section-head"><h2>${esc(preview.breakdown.title)}</h2><span>${preview.breakdown.subtasks.length} 个子任务</span></div><div class="ai-subtasks">${preview.breakdown.subtasks.map((item,index)=>`<article><b>${index+1}</b><div><h3>${esc(item.name)}</h3><p>${item.dependencies.length?`前置：${item.dependencies.map(esc).join('、')}`:'无前置依赖'}</p></div><span>${esc(item.priority)} · ${item.estimated_hours} 小时</span></article>`).join('')}</div><div class="ai-confirm"><p>当前内容只是预览，尚未写入 SQLite。</p><button id="ai-confirm" class="primary-btn">确认并加入科研任务</button></div></div>`:''}
  </section>`;
}

function bindDynamic(){
  $$('[data-edit]').forEach(button=>button.onclick=()=>openDialog(state.tasks.find(task=>task.id===button.dataset.edit)));
  $$('[data-check]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.check);try{await patchTask(task.id,{status:input.checked?'completed':'in_progress',progress:input.checked?100:Math.min(task.progress,95)});toast(input.checked?'任务已完成':'任务已恢复为进行中')}catch(error){input.checked=!input.checked;showError(error)}});
  $$('[data-priority]').forEach(select=>select.onchange=async()=>{const task=state.tasks.find(item=>item.id===select.dataset.priority);try{await patchTask(task.id,{priority:select.value});toast('优先级已更新')}catch(error){select.value=task.priority;showError(error)}});
  $$('[data-due]').forEach(input=>input.onchange=async()=>{const task=state.tasks.find(item=>item.id===input.dataset.due);try{await patchTask(task.id,{due_date:input.value||null});toast('Deadline 已更新')}catch(error){input.value=task.due_date||'';showError(error)}});
  if($('#quick-form'))$('#quick-form').onsubmit=async event=>{event.preventDefault();const title=$('#quick-title').value.trim();if(!title)return;try{await createTask({title,domain:'inbox',priority:'medium',status:'not_started',progress:0,estimated_minutes:0});toast('已加入收件箱')}catch(error){showError(error)}};
  if($('#prev-month'))$('#prev-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()-1,1);render()};
  if($('#next-month'))$('#next-month').onclick=()=>{state.month=new Date(state.month.getFullYear(),state.month.getMonth()+1,1);render()};
  if($('#ai-form'))$('#ai-form').onsubmit=async event=>{event.preventDefault();const task=$('#ai-task').value.trim();if(!task)return;state.aiLoading=true;render();try{const data=await api('/api/ai/breakdown/preview',{method:'POST',body:JSON.stringify({task})});state.aiPreview={source:task,breakdown:data.breakdown};toast('拆解预览已生成，尚未写入数据库')}catch(error){showError(error)}finally{state.aiLoading=false;render()}};
  if($('#ai-confirm'))$('#ai-confirm').onclick=async()=>{if(!state.aiPreview)return;try{await api('/api/ai/breakdown/confirm',{method:'POST',body:JSON.stringify({domain:'research',breakdown:state.aiPreview.breakdown})});state.aiPreview=null;await loadTasks({migrate:false});state.view='research';render();toast('已确认并加入科研任务')}catch(error){showError(error)}};
}

async function createTask(payload){const data=await api('/api/tasks',{method:'POST',body:JSON.stringify(payload)});state.tasks.push(data.task);render();return data.task}
async function patchTask(id,changes){const data=await api(`/api/tasks/${id}`,{method:'PATCH',body:JSON.stringify(changes)});state.tasks=state.tasks.map(task=>task.id===id?data.task:task);render();return data.task}

function openDialog(task=null){
  $('#task-form').reset();
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
function toast(message){const node=$('#toast');node.textContent=message;node.classList.add('show');clearTimeout(toast.timer);toast.timer=setTimeout(()=>node.classList.remove('show'),2400)}
function showError(error){console.error(error);toast(error.message||'操作失败，请查看启动窗口日志')}

$('#task-form').onsubmit=async event=>{event.preventDefault();try{const id=$('#task-id').value;if(id)await patchTask(id,formPayload());else await createTask(formPayload());closeDialog();toast(id?'任务已更新':'任务已创建')}catch(error){showError(error)}};
$('#delete-btn').onclick=async()=>{const id=$('#task-id').value;if(!id||!confirm('确定永久删除这个任务吗？'))return;try{await api(`/api/tasks/${id}`,{method:'DELETE'});state.tasks=state.tasks.filter(task=>task.id!==id);closeDialog();render();toast('任务已删除')}catch(error){showError(error)}};
$('#add-btn').onclick=()=>openDialog();
$('#close-dialog').onclick=closeDialog;
$('#cancel-btn').onclick=closeDialog;
$('#task-recurring').onchange=event=>{$('#task-recurrence').disabled=!event.target.checked};
$('#task-status').onchange=event=>{if(event.target.value==='completed')$('#task-progress').value=100};
$$('.nav-item').forEach(button=>button.onclick=()=>{state.view=button.dataset.view;$('.sidebar').classList.remove('open');render()});
$('#status-filter').onchange=event=>{state.status=event.target.value;render()};
$('#subcategory-filter').onchange=event=>{state.subcategory=event.target.value;render()};
$('#menu-btn').onclick=()=>$('.sidebar').classList.toggle('open');
$('#export-btn').onclick=async()=>{try{const data=await api('/api/export');const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const anchor=document.createElement('a');anchor.href=URL.createObjectURL(blob);anchor.download=`Yantu备份-${today()}.json`;anchor.click();URL.revokeObjectURL(anchor.href);toast('备份已导出')}catch(error){showError(error)}};
$('#import-file').onchange=async event=>{try{const file=event.target.files[0];if(!file)return;const data=JSON.parse(await file.text());if(!Array.isArray(data.tasks))throw new Error('备份文件中没有任务列表');if(!confirm(`将合并导入 ${data.tasks.length} 个任务，是否继续？`))return;await api('/api/import',{method:'POST',body:JSON.stringify(data)});await loadTasks({migrate:false});toast('备份已导入')}catch(error){showError(error)}finally{event.target.value=''}};

loadTasks().catch(error=>{state.loading=false;$('#content').innerHTML=`<div class="empty error"><strong>无法连接 Yantu 后端</strong>${esc(error.message)}<br>请保留启动窗口并查看其中的错误信息。</div>`;showError(error)});
