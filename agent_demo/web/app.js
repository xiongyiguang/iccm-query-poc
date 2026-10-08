const $=id=>document.getElementById(id),state={token:'',current:null,sessions:[],polling:false};
const names={iccm_catalog:'读取项目知识与查询能力',iccm_find:'定位对象',iccm_query:'执行数据查询',iccm_page:'读取结果分页'};
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function formatText(node,text){node.replaceChildren();for(const part of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)){if(part.startsWith('**')&&part.endsWith('**'))node.append(el('strong',part.slice(2,-2)));else if(part.startsWith('`')&&part.endsWith('`'))node.append(el('code',part.slice(1,-1)));else node.append(document.createTextNode(part));}}
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json','X-Local-Token':state.token},body:body?JSON.stringify(body):undefined});const v=await r.json();if(!r.ok)throw Error(v.error||'连接失败');return v;}
function notice(text){$('notice').textContent=text;}
function buttons(){const s=state.current;$('send').disabled=state.creating||!state.token||!s||s.busy;$('stop').hidden=!s?.busy;$('activity').textContent=state.creating?'正在建立会话…':s?.busy?'正在核查数据…':'先核查，再回答';}
function list(){ $('sessions').replaceChildren();for(const s of state.sessions){const b=el('button',s.title,s===state.current?'active':'');b.onclick=()=>select(s);$('sessions').append(b);}}
function select(s){state.current=s;$('conversation').replaceChildren();for(const e of s.events)render(e);list();buttons();$('model').textContent=s.model;}
async function create(){const old=state.current;try{state.creating=true;buttons();$('new').disabled=true;notice('正在建立独立智能体会话…');const v=await api('/api/new',{model:$('model-choice').value});const s={...v,title:'新对话',events:[],cursor:0,busy:false};state.sessions.unshift(s);state.current=s;if(old)select(s);list();buttons();$('model').textContent=s.model+' · 低推理';notice('仅本机 · 与 r10 独立运行');}catch(e){notice(e.message);}finally{state.creating=false;$('new').disabled=false;buttons();}}
function findItem(id){return [...$('conversation').querySelectorAll('[data-id]')].find(n=>n.dataset.id===id);}
function processBody(){return [...$('conversation').querySelectorAll('.process-body')].at(-1);}
function processStatus(text){const p=processBody();if(p){p.parentElement.querySelector('.process-status').textContent=text;const step=p.querySelector('.process-step span:last-child');if(step)step.textContent='已核对本次会话和数据快照。';}}
function tableView(container,columns,rows){
 const wrap=el('div',undefined,'table-wrap'),table=el('table'),thead=el('thead'),head=el('tr'),body=el('tbody');
 for(const col of columns)head.append(el('th',col));thead.append(head);table.append(thead);
 for(const row of rows){const tr=el('tr');for(const value of row)tr.append(el('td',value===null||value===undefined||value===''?'未提供':typeof value==='object'?JSON.stringify(value):String(value)));body.append(tr);}
 table.append(body);wrap.append(table);container.append(wrap);
}
function understanding(container,view,executed=false,finished=false){
 container.replaceChildren();if(!view)return;
 if(view.rows?.length){container.append(el('h3',executed?'实际查询口径':finished?'本次理解 · 未完成':'本次理解 · 待执行'));
 const dl=el('dl',undefined,'understanding-fields');for(const r of view.rows)dl.append(el('dt',r.label),el('dd',r.text));container.append(dl);}
 if(view.route)container.append(el('p',(executed?'查询路径：':finished?'提交路径：':'计划路径：')+view.route,'query-route'));
 for(const task of view.tasks||[]){const section=el('section',undefined,'query-task');section.append(el('h4',task.question||task.title));const body=el('div');understanding(body,task,task.executed??executed,finished);section.append(body);container.append(section);}
}
function evidenceView(container,r){
 const entries=[...(r.evidence||[]),...(r.records||[]).flatMap(row=>Array.isArray(row.evidence)?row.evidence:row.evidence?[row.evidence]:[])];
 const seen=new Set(),unique=entries.filter(e=>{const key=JSON.stringify(e);if(seen.has(key))return false;seen.add(key);return true;});
 if(!unique.length)return;
 container.append(el('h4','原始数据依据'),el('p','以下为本页返回的来源摘录；统计使用完整筛选集合。','detail-hint'));
 for(const e of unique){const source=el('details',undefined,'evidence-source');source.append(el('summary',(e.file||'数据快照')+(e.line!==undefined?' · 第 '+e.line+' 行':'')));
 tableView(source,['原始字段','原始值'],Object.entries(e.fields||{}));container.append(source);}
}
function showResult(container,r){
 if(r.answer)container.append(el('p',r.answer,'summary'));
 if(r.note)container.append(el('p',r.note,'result-note'));
 if(r.attributes?.length)tableView(container,['属性','值','状态 / 说明'],r.attributes.map(f=>[f.label,f.display_value??f.value,({known:'已核实',missing:'未提供',unsupported:'现有数据不支持'}[f.status]||f.status)+(f.explanation?' · '+f.explanation:'')]));
 if(r.records?.length){let columns=r.columns?.map(c=>typeof c==='string'?c:(c.label||c.key));let rows;
  if(r.records[0].cells){rows=r.records.map(row=>row.cells);columns=columns?.length?columns:rows[0].map((_,i)=>'字段 '+(i+1));}
  else {const points=r.records.some(row=>'value'in row||'unit'in row);const fields=points?['name','code','value','unit','state','switch','source','time']:['name','code','tree','level'];columns=points?['测点名称','编码','测量值','单位','报警状态','开关','源系统','测量时间']:['对象名称','编码','对象树','层级'];
   const trees={pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类'};
   rows=r.records.map(row=>fields.map(f=>f==='tree'?(trees[row[f]]||row[f]):row[f]));}
  tableView(container,columns,rows);
  container.append(el('p','第 '+(r.page||1)+' 页 · 本页 '+r.records.length+' 条'+(r.has_more?'；尚有后续明细，可继续提问“查看下一页”。':'。'),'detail-hint'));
 }
 for(const item of r.items||[]){const section=el('section',undefined,'query-task');if(item.task_question||item.question)section.append(el('h4',item.task_question||item.question));showResult(section,item);container.append(section);}
 evidenceView(container,r);
}
function closeRunning(label){for(const tool of processBody()?.querySelectorAll('.tool[data-status="running"]')||[]){tool.dataset.status='stopped';understanding(tool.querySelector('.query-understanding'),tool._view,false,true);tool.querySelector('.tool-status').textContent=label;}}
function render(e){const c=$('conversation'),near=c.scrollHeight-c.scrollTop-c.clientHeight<140;let n;
 if(e.kind==='user'){ $('welcome')?.remove();c.append(el('div',e.text,'user'));}
 else if(e.kind==='process'){
  n=findItem(e.id);if(!n){n=el('details',undefined,'query-process');n.dataset.id=e.id;n.open=true;const heading=el('summary');heading.append(el('strong','查询过程'),el('span','正在分析问题','process-status'));
   const body=el('div',undefined,'process-body'),step=el('div',undefined,'process-step');step.append(el('span','准备','step-source'),el('span','已连接本次数据快照，正在分析问题。'));body.append(step);
   const info=el('details',undefined,'system-details');info.append(el('summary','系统准备记录'),el('div'));body.append(info);n.append(heading,body);c.append(n);}
  n.querySelector('.system-details>div').append(el('p',e.text));
 }
 else if(['message_start','delta','message'].includes(e.kind)){
  n=findItem(e.id);if(!n){n=el('div','','assistant');n.dataset.id=e.id;(e.phase==='commentary'&&processBody()?processBody():c).append(n);}
  if(e.phase==='commentary'){n.classList.add('commentary');if(processBody()&&n.parentElement!==processBody())processBody().append(n);processStatus('正在核对查询思路');}
  if(e.kind==='delta')n.textContent+=e.text;else if(e.kind==='message'){formatText(n,e.text);n.classList.toggle('commentary',e.phase==='commentary');}
 }
 else if(e.kind==='tool_start'){
  processStatus('正在'+(e.tool==='iccm_catalog'?'核对项目概念':'查询数据'));
  n=el('article',undefined,'tool');n.dataset.id=e.id;n.dataset.status='running';n.dataset.tool=e.tool;
  const heading=el('div',undefined,'tool-heading');heading.append(el('strong',e.presentation?.title||names[e.tool]||'查询数据'),el('span','进行中','tool-status'));
  const fields=el('div',undefined,'query-understanding');understanding(fields,e.presentation);
  const tech=el('details',undefined,'technical');tech.append(el('summary','技术详情'),el('pre',JSON.stringify({arguments:e.arguments},null,2)));n._args=e.arguments;n._view=e.presentation;
  n.append(heading,fields,el('div',undefined,'tool-content'),tech);(processBody()||c).append(n);
 }
 else if(e.kind==='tool_result'){
  n=findItem(e.id);if(n){const r=e.result;const needsAttention=(x)=>!!(x.status&&!['ok','success','completed','batch'].includes(x.status))||x.items?.some(needsAttention);
   const attention=needsAttention(r),candidate=r.match_type==='candidates_only';n.dataset.status=attention||candidate?'attention':'completed';
   n.querySelector('.tool-status').textContent=(attention?'需要核对':candidate?'仅候选，未选定':'已完成')+' · '+e.seconds+'秒';
   // 工具调用已经返回，不一定代表业务查询执行成功。
   const executed=!attention&&(!!r.query_receipt||e.tool==='iccm_page'||r.status==='batch');
   understanding(n.querySelector('.query-understanding'),e.presentation,executed,true);
   const content=n.querySelector('.tool-content');
   if(r.metrics?.length){const metrics=el('div',undefined,'result-metrics');for(const m of r.metrics){const metric=el('div');metric.append(el('span',m.label),el('b',String(m.value)));metrics.append(metric);}content.append(metrics);}
   if(e.tool==='iccm_catalog')content.append(el('p','已核对项目概念和可用数据关系。','detail-hint'));
   else {if(attention||candidate)content.append(el('p',candidate?'以下只列出候选对象，尚未替你选定。':r.answer||'本次请求尚需核对，不能视为已完成查询。','attention-note'));
    const details=el('details',undefined,'result-details');details.append(el('summary','查看明细与依据'+(r.records?.length?' · 本页 '+r.records.length+' 条':'')));showResult(details,r);content.append(details);}
   n.querySelector('.technical pre').textContent=JSON.stringify({arguments:n._args,result_id:r.result_id,status:r.status,query_receipt:r.query_receipt,result:r},null,2);
  }
 }
 else if(e.kind==='tool_error'){
  processStatus('查询遇到问题');n=findItem(e.id);if(n){n.dataset.status='error';understanding(n.querySelector('.query-understanding'),n._view,false,true);n.querySelector('.tool-status').textContent='未执行成功';n.querySelector('.tool-content').append(el('p',e.text,'error'));}
 }
 else if(e.kind==='error'){closeRunning('未完成');processStatus('处理遇到问题');c.append(el('div',e.text,'error'));}
 else if(e.kind==='progress')c.append(el('div',e.text,'done'));
 else if(e.kind==='done'){
  closeRunning(e.status==='interrupted'?'已停止':'未完成');processStatus(e.status==='completed'?'本轮结束':e.status==='interrupted'?'已停止':'未完成');
 }
 if(near||e.kind==='user')c.scrollTop=c.scrollHeight;
}
async function poll(){if(state.polling||!state.token)return;state.polling=true;try{for(const s of state.sessions){if(!s.busy||s.submitting)continue;try{const v=await api('/api/events?session='+s.id+'&after='+s.cursor);for(const e of v.events){s.events.push(e);s.cursor=e.seq;if(s===state.current)render(e);}s.busy=v.busy;if(s===state.current)buttons();}catch(e){s.busy=false;notice(e.message);buttons();}}}finally{state.polling=false;}}
async function send(question){const s=state.current;if(state.creating||!s||s.busy)return;s.busy=true;s.submitting=true;s.title=question.slice(0,28);buttons();list();try{await api('/api/ask',{session:s.id,question});s.submitting=false;$('question').value='';await poll();}catch(e){s.submitting=false;s.busy=false;notice(e.message);buttons();}}
$('form').onsubmit=e=>{e.preventDefault();const q=$('question').value.trim();if(q)send(q);};
$('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();$('form').requestSubmit();}};
$('new').onclick=create;$('stop').onclick=async()=>{try{await api('/api/stop',{session:state.current.id});}catch(e){notice(e.message);}};
for(const b of document.querySelectorAll('[data-question]'))b.onclick=()=>send(b.dataset.question);
(async()=>{try{const m=await api('/api/meta');state.token=m.token;$('connection').textContent=m.ready?'Codex 已连接':'Codex 未连接';const labels={pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类',points:'测点记录'};for(const [k,v]of Object.entries(m.counts)){const row=el('div');row.append(el('span',labels[k]||k),el('b',v.toLocaleString()));$('counts').append(row);}await create();setInterval(poll,450);}catch(e){notice(e.message);$('connection').textContent='未连接';}})();
