'use strict';
function disableReviews(){for(const card of document.querySelectorAll('.query-review'))for(const c of card.querySelectorAll('input,select,button'))c.disabled=true;}
function reviewSelect(options,value,label,onchange){
 const select=node('select');select.setAttribute('aria-label',label);
 for(const [key,text] of Object.entries(options)){const opt=node('option',text);opt.value=key;select.append(opt);}
 if(!Object.hasOwn(options,String(value))){const opt=node('option',String(value)+'（请核对）');opt.value=value??'';select.append(opt);}
 select.value=value??'';select.onchange=()=>onchange(select.value);return select;
}
function renderReview(result,label,target){
 const review=result.review,originalSession=session,originalGeneration=generation,forms=JSON.parse(JSON.stringify(review.tasks));
 const card=node('article',undefined,'answer message query-review');card.dataset.review=review.id;
 const heading=node('div',undefined,'review-heading');heading.append(node('span','待确认 · 尚未查询','review-status'),node('h3','核对对象和条件'));
 card.append(heading,node('p','按下面的条件查询。可直接修改；多项筛选需要同时满足。','note'));
 if(review.semantic_review){
  const difference=review.semantic_review,region=node('section',undefined,'review-disagreement');
  region.setAttribute('aria-label','查询理解分歧');
  region.append(node('h4',difference.title),node('p','请核对下方可编辑条件，确认后按编辑结果查询。供对照的另一种理解：','note'));
  const alternative=node('ul');for(const text of difference.alternative)alternative.append(node('li',text));region.append(alternative);
  if(difference.state_warning)region.append(node('p',difference.state_warning,'note'));
  card.append(region);
 }
 const catalog=review.catalog,fieldLabel=k=>catalog.properties[k]||fieldNames[k]||({location:'功能位置'}[k])||k;
 const operations={search:'筛选记录',attributes:'读取属性',analyze:'统计分析',parts:'查看部件',descendants:'查看下级对象',equipment:'对应设备',equipment_class:'所属设备类',part_class:'所属部件类',parent:'上级对象',measurement:'读取测量值',measurements:'查看测点',threshold:'读取阈值',alarms:'查看报警测点',duration:'报警时间',object:'查看对象',data_overview:'数据概览',relation_check:'核对对象关系'};
 const groups={location:'功能位置',status:'报警状态',switch:'开关',source:'源系统',class_code:'部件类',level:'层级'};
 function control(parent,title,element){const row=node('label',undefined,'review-control');row.append(node('span',title),element);parent.append(row);return row;}
 function textInput(value,label,change){const input=node('input');input.value=value??'';input.setAttribute('aria-label',label);input.oninput=()=>change(input.value);return input;}
 function filtersEditor(parent,filters,getTarget,title){
  const region=node('section',undefined,'review-filters');parent.append(region);
  const draw=()=>{
   region.replaceChildren(node('h4',title));
   if(!filters.length)region.append(node('p','不限条件','note'));
   filters.forEach((filter,index)=>{
    const row=node('div',undefined,'review-filter');
    const fields=Object.fromEntries((catalog.fields[getTarget()]||[]).map(k=>[k,fieldLabel(k)]));
    const field=reviewSelect(fields,filter.field,title+(index+1)+'字段',v=>{filter.field=v;});
    const operator=reviewSelect({...opNames,gt:'大于（不含边界）',gte:'大于等于（含边界）',lt:'小于（不含边界）',lte:'小于等于（含边界）'},filter.operator,title+(index+1)+'比较方式',v=>{filter.operator=v;if(['is_blank','not_blank'].includes(v))filter.value='';draw();});
    const value=textInput(filter.value,title+(index+1)+'值',v=>{filter.value=v;});value.classList.add('review-value');
    value.disabled=['is_blank','not_blank'].includes(filter.operator);
    row.append(field,operator,value,button('移除',()=>{filters.splice(index,1);draw();},'review-remove'));region.append(row);
   });
   const add=button('＋ 添加条件',()=>{filters.push({field:(catalog.fields[getTarget()]||['name'])[0],operator:'equals',value:''});draw();},'review-add');add.disabled=filters.length>=8;region.append(add);
  };draw();return draw;
 }
 for(const form of forms){
  const section=node('fieldset',undefined,'review-task'),legend=node('legend');legend.append(node('span','任务 '+(form.index+1)+' · '+(operations[form.operation]||'查询说明')));
  if(form.enabled){const keep=node('input');keep.type='checkbox';keep.checked=true;keep.setAttribute('aria-label','执行任务'+(form.index+1));keep.onchange=()=>{form.enabled=keep.checked;};legend.prepend(keep);}
  section.append(legend,node('p',form.question,'review-question'));card.append(section);
  if(!form.enabled){section.append(node('p',form.message||'需要补充信息后才能查询。','note'));continue;}
  const values=form.values,top=node('div',undefined,'review-top');section.append(top);
  if(values.entity){const e=values.entity,key=Object.hasOwn(e,'code')?'code':Object.hasOwn(e,'name')?'name':'identity';control(top,'对象树',reviewSelect(form.entity_trees||{pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类'},e.tree,'任务'+(form.index+1)+'对象树',v=>e.tree=v));control(top,key==='code'?'对象编码':key==='name'?'对象名称':'对象名称或编码',textInput(e[key],'任务'+(form.index+1)+'对象标识',v=>e[key]=v));control(top,'下级范围',reviewSelect({direct:'直接下级',all:'全部下级'},values.scope,'任务'+(form.index+1)+'范围',v=>values.scope=v));}
  if(values.query){
   const query=values.query;let redraw=()=>{};
   control(top,'查询对象',reviewSelect(form.query_targets||catalog.targets,query.target,'任务'+(form.index+1)+'查询对象',v=>{query.target=v;redraw();}));
   if(!values.entity)top.append(node('p','范围：所选对象类型中的全部记录，再按下列条件筛选。','note'));
   if(!form.fixed_population)redraw=filtersEditor(section,query.filters,()=>query.target,'筛选条件');
   if(query.equipment_class){const rel=query.equipment_class;const r=node('div',undefined,'review-top');control(r,'所属设备类匹配',reviewSelect({identity:'名称或编码',name:'名称',code:'编码'},rel.field,'设备类匹配字段',v=>rel.field=v));control(r,'设备类',textInput(rel.value,'设备类名称或编码',v=>rel.value=v));section.append(r);}
  }
  if(values.subjects){for(const [i,subject] of values.subjects.entries()){const row=node('div',undefined,'review-top');control(row,'关系对象 '+(i+1),reviewSelect({pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类'},subject.tree,'关系对象'+(i+1)+'树',v=>subject.tree=v));control(row,'名称或编码',textInput(subject.identifier,'关系对象'+(i+1)+'标识',v=>subject.identifier=v));section.append(row);}}
  if(values.topics)section.append(node('p','概览内容：'+values.topics.map(k=>({counts:'数据数量',relationships:'对象关系',capabilities:'支持能力',limitations:'数据限制'}[k]||k)).join('、'),'note'));
  if(form.operation==='threshold'&&!values.thresholds)section.append(node('p','返回字段：全部阈值档位及测量值。','note'));
  if(values.properties||values.thresholds){
   const key=values.properties?'properties':'thresholds',selected=values[key];
   const fields=key==='thresholds'?Object.fromEntries(Object.entries(catalog.properties).filter(([k])=>/^(actual|estimate|rate_deviation)_/.test(k))):{'*':'全部属性',...catalog.properties};
   const details=node('details',undefined,'review-properties'),summary=node('summary');details.append(summary);
   const update=()=>{summary.textContent='返回字段：'+selected.map(k=>fields[k]||k).join('、');};update();
   const choices=node('div',undefined,'review-field-choices');
   for(const [key,label] of Object.entries(fields)){const c=node('input');c.type='checkbox';c.checked=selected.includes(key);c.onchange=()=>{if(c.checked){if(key==='*')selected.splice(0,selected.length,'*');else{const i=selected.indexOf('*');if(i>=0)selected.splice(i,1);selected.push(key);}}else{const i=selected.indexOf(key);if(i>=0)selected.splice(i,1);}for(const other of choices.querySelectorAll('input'))other.checked=selected.includes(other.value);update();};c.value=key;const l=node('label');l.append(c,node('span',label));choices.append(l);}details.append(choices);section.append(details);
  }
  if(values.analysis){
   const a=values.analysis,area=node('div',undefined,'review-analysis');section.append(area,node('p',a.kind==='ratio'?'占比：基础筛选为分母，下列附加条件为分子。':'按完整筛选结果统计，不按当前页计算。','note'));
   if(a.kind==='ratio')filtersEditor(section,a.numerator,()=>values.query.target,'分子附加条件');
   else{control(area,'按什么分组',reviewSelect(groups,a.group_by,'统计分组',v=>a.group_by=v));control(area,'数量排序',reviewSelect({desc:'从多到少',asc:'从少到多'},a.order,'统计排序',v=>a.order=v));const input=textInput(a.limit,'展示分组数量',v=>a.limit=Number(v));input.type='number';input.min=1;input.max=100;control(area,'最多展示',input);}
  }
 }
 const feedback=node('p','','review-feedback');feedback.setAttribute('role','status');card.append(feedback);
 const actions=node('div',undefined,'review-actions');
 const confirm=button('确认并查询',async()=>{
  if(busy||session!==originalSession||generation!==originalGeneration){feedback.textContent='对话已变化，请重新提问生成确认单。';return;}
  busy=true;const gen=++generation,started=performance.now();controller=new AbortController();$('send').disabled=true;$('cancel').hidden=false;const controlStates=[...card.querySelectorAll('input,select,button')].map(c=>[c,c.disabled]);for(const [c] of controlStates)c.disabled=true;
  try{
   const response=await api('/api/confirm',{session:originalSession,review:review.id,tasks:forms.map(({index,enabled,values})=>({index,enabled,values}))},controller.signal);
   if(gen!==generation)return;
   historyTurns=historyTurns.filter(t=>!(t.session===originalSession&&t.result?.review?.id===review.id));
   rememberTurn(label,response);for(const obj of [...(response.path||[]),...(response.records||[])])rememberObject(obj);applyResultContext(response);setContext();
   const holder=node('div');const answer=render(response,label,holder);card.replaceWith(answer);
   const total=(response.review_confirmation?.preparation_ms||0)+(performance.now()-started);
   $('timing').textContent=(total/1000).toFixed(2)+'秒 · 理解与查询总耗时，不含人工核对'+(total>5000?' · 超过5秒目标':'');
   revealMessage(answer);
  }catch(e){if(gen===generation){feedback.textContent=e.name==='AbortError'?'已取消。':e.message;for(const [c,disabled] of controlStates)c.disabled=disabled;generation=originalGeneration;}}
  finally{if(gen===generation||generation===originalGeneration){busy=false;$('send').disabled=false;$('cancel').hidden=true;controller=null;}}
 },'review-confirm');
 const cancel=button('取消',async()=>{if(busy||session!==originalSession||generation!==originalGeneration)return;try{await api('/api/review/cancel',{session:originalSession,review:review.id});for(const c of card.querySelectorAll('input,select,button'))c.disabled=true;feedback.textContent='已取消，未执行查询。';}catch(e){feedback.textContent=e.message;}});
 actions.append(confirm,cancel);card.insertBefore(actions,card.children[2]);target.append(card);
 if(review.readOnly){for(const c of card.querySelectorAll('input,select,button'))c.disabled=true;feedback.textContent='历史确认单仅供回看。需要查询时，请重新提问。';}
 return card;
}
const $=id=>document.getElementById(id);
// getRandomValues 可用于 HTTP 页面；randomUUID 要求安全上下文。
function createSessionId(){return Array.from(crypto.getRandomValues(new Uint8Array(24)),n=>n.toString(16).padStart(2,'0')).join('');}
let meta,session=createSessionId(),selection=null,context={},busy=false,generation=0,controller=null;
const sample={tree:'pbs',code:'XJ2ABC002MO&MOHB01'};
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
function button(text,fn,cls){const b=node('button',text,cls);b.type='button';b.onclick=fn;return b;}
async function api(path,body,signal){let r;try{r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-Demo-Token':meta.token}:{},body:body?JSON.stringify({...body,version:meta?.version}):undefined,signal});}catch(e){if(e.name==='AbortError')throw e;throw new Error('暂时无法连接演示服务，请稍后重试。');}if(r.status===401){clearHistory();location.replace('/login');throw new Error('请重新登录。');}const v=await r.json();if(!r.ok)throw new Error(v.error||'请求失败');return v;}
function revealMessage(message){requestAnimationFrame(()=>{if(message.isConnected)message.scrollIntoView({behavior:window.matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});});}
function showNotice(text,cls='error'){const message=node('div',text,'message '+cls);message.setAttribute('role',cls==='error'?'alert':'status');$('welcome').hidden=true;$('conversation').append(message);revealMessage(message);return message;}
const targetNames={objects:'跨树对象',parts:'部件构型',equipment:'设备构型',config:'构型对象',pbs:'PBS对象',equipment_class:'设备类字典',part_class:'部件类字典',points:'测点记录'};
const fieldNames={identity:'名称或编码',name:'名称',code:'编码',level:'层级',parent:'父编码',class_code:'部件类编码',source:'源系统',status:'状态',switch:'开关',unit:'单位',time:'测量时间'};
const opNames={gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于',eq_num:'数值等于',contains:'包含',equals:'等于',starts_with:'开头为',not_contains:'不包含',is_blank:'未提供',not_blank:'已提供'};
let contextSync=Promise.resolve();
function clearContext(){contextSync=api('/api/context',{session});return contextSync;}
const objectDetails=new Map();
function rememberObject(e){if(!e?.tree||!e?.code)return;const key=e.tree+'|'+e.code;const old=objectDetails.get(key)||{};objectDetails.set(key,{...old,...Object.fromEntries(Object.entries(e).filter(([k,v])=>['tree','code','name','level'].includes(k)&&v))});}
function objectSummary(e){const detail=objectDetails.get(e.tree+'|'+e.code)||e;const tree={pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类'}[e.tree]||e.tree;return `当前对象：${detail.name||'名称未提供'} ｜ 编码：${e.code} ｜ ${tree}${detail.level?' · '+detail.level:''}${!selection&&context.operation==='parts'?' ｜ 查询范围：'+(context.scope==='all'?'全部下级':'直接下级'):''}`;}
function objectContextCard(e){const detail=objectDetails.get(e.tree+'|'+e.code)||e;const card=node('div',undefined,'context-object');const title=node('div',undefined,'context-object-title');title.append(node('span','当前对象','context-object-label'),node('strong',detail.name||'名称未提供'),node('code',e.code));card.append(title);const tree={pbs:'PBS',config:'构型树',equipment_class:'设备类',part_class:'部件类'}[e.tree]||e.tree;card.append(node('div',tree+(detail.level?' · '+detail.level:'')+(!selection&&context.operation==='parts'?' · '+(context.scope==='all'?'全部下级':'直接下级'):''),'context-object-meta'));return card;}
function setContext(){const e=selection||context.entity;$('context').replaceChildren();$('context').hidden=!e&&!context.query&&!context.branches&&!context.pending_request;if(context.pending_request){$('context').append(node('span','上次问题尚未完成，请补充所需条件或点选候选对象后继续。'));}if(context.branches){$('context').append(node('span','上一轮有多组结果，请指明第几项或点选对象后追问。'));}if(context.query){const filters=node('div',undefined,'context-row context-filter-row');$('context').append(filters);filters.append(node('span','当前筛选：'+(context.query_receipt?.grain==='pbs_object'&&context.query.target==='parts'?'现场部件':targetNames[context.query.target])+' · '+[...(context.query.equipment_class?['设备分类'+opNames[context.query.equipment_class.operator]+context.query.equipment_class.value]:[]),...context.query.filters.map(f=>(meta.field_labels?.[f.field]||fieldNames[f.field]||f.field)+(opNames[f.operator]||f.operator)+f.value)].join('；')),button('清除筛选',async()=>{if(busy)return;await clearContext();selection=null;context={};setContext();}));}if(e){const objectRow=node('div',undefined,'context-row');$('context').append(objectRow);objectRow.append(objectContextCard(e),button('清除条件',()=>{if(busy)return;selection=null;context={};clearContext().catch(e=>{$('timing').textContent=e.message;});setContext();}));const actions=e.tree==='config'?[['查看名称','object'],['直接部件','parts'],['部件类','part_class']]:e.tree==='pbs'?[['对应设备','equipment'],['查看测点','measurements'],['阈值对照','threshold'],['报警时长','duration']]:[['查看名称','object']];for(const [label,op] of actions)objectRow.append(follow(label,op,e,'direct'));}}
function choose(e){if(busy)return;rememberObject(e);selection={tree:e.tree,code:e.code};if(!context.pending_request){context={};clearContext().catch(e=>{$('timing').textContent=e.message;});}setContext();$('browser').close();$('question').focus();}
function follow(label,operation,entity,scope='direct'){return button(label,()=>run(label,{operation,entity,scope}));}
function evidence(refs){$('evidenceBody').replaceChildren();if(!refs.length)$('evidenceBody').append(node('p','本次结果没有可定位的原始记录。'));for(const r of refs.filter(Boolean)){const div=node('div',undefined,'ref');div.append(node('h4',`${r.file} · 第 ${r.line} 行`));const dl=node('dl');for(const [k,v] of Object.entries(r.fields)){dl.append(node('dt',k),node('dd',v===''?'未提供':String(v)));}div.append(dl);$('evidenceBody').append(div);}$('evidence').showModal();}
function drawRows(container,rows,columns=[]){container.replaceChildren();if(!rows.length){container.append(node('p','本次筛选没有匹配记录。','note'));return;}if(rows[0].cells){const table=node('table');if(columns.length){const head=node('thead');const tr=node('tr');for(const label of columns)tr.append(node('th',label));head.append(tr);table.append(head);}for(const row of rows){const tr=node('tr');for(const cell of row.cells)tr.append(node('td',String(cell)));table.append(tr);}container.append(table);return;}const monitoring=Object.hasOwn(rows[0],'state');const thresholds=false;const table=node('table');const header=node('tr');for(const label of monitoring?['测点名称 / 编码','来源','测量值',...(thresholds?['真实值高1','差值']:[]),'状态','测量时间','归属位置','依据']:['对象名称 / 编码','层级 / 部件类','上级','依据'])header.append(node('th',label));const thead=node('thead');thead.append(header);table.append(thead);const tbody=node('tbody');for(const r of rows){const tr=node('tr');const first=node('td');const name=button(r.name||'未提供名称',()=>{choose(r);});name.append(node('code',r.code));first.append(name);tr.append(first);if(monitoring){tr.append(node('td',r.source||'未提供'));tr.append(node('td',`${r.value} ${r.unit==='未提供'?'':r.unit}`));if(thresholds)tr.append(node('td',r.high1),node('td',r.difference));const td=node('td');td.append(node('span',r.state,r.state==='已报警'?'alarm':''));tr.append(td,node('td',r.time),node('td',r.location));}else{tr.append(node('td',r.class||r.level||'—'),node('td',r.parent||'—'));}const td=node('td');td.append(button('查看',()=>evidence([r.evidence,r.class_evidence])));tr.append(td);tbody.append(tr);}table.append(tbody);container.append(table);}
function renderChart(chart){const area=node('div',undefined,'analysis-chart');area.setAttribute('role','figure');area.setAttribute('aria-label',chart.kind==='ratio'?'记录占比':'分组记录数量');if(chart.kind==='ratio'){const n=chart.numerator,d=chart.denominator;area.append(node('strong',d?`${(n/d*100).toFixed(2)}%`:'无法计算占比'));const track=node('div',undefined,'analysis-track'),fill=node('div',undefined,'analysis-fill');fill.style.width=(d?n/d*100:0)+'%';track.append(fill);area.append(track,node('span',`符合条件 ${n} 条 / 基础范围 ${d} 条`));}else{const max=Math.max(1,...chart.items.map(x=>x.value));for(const item of chart.items){const row=node('div',undefined,'analysis-bar-row'),track=node('div',undefined,'analysis-track'),fill=node('div',undefined,'analysis-fill');fill.style.width=(item.value/max*100)+'%';track.append(fill);row.append(node('span',item.label),track,node('strong',String(item.value)));area.append(row);}if(!chart.items.length)area.append(node('span','没有符合条件的数据。'));}return area;}
function attributeSummary(result){const name=result.path?.[0]?.name||'当前对象',code=result.entity?.code||'编码未提供';const type=result.attributes.find(f=>f.property==='type'&&f.status==='known');return type?`${name}（${code}）的对象类型为${type.value}。`:`${name}（${code}）的属性如下。`;}
function render(result,label,target=$('conversation')){if(result.status==='review')return renderReview(result,label,target);if(result.status==='batch'){const group=node('div',undefined,'message');target.append(group);const batchHead=node('div',undefined,'batch-heading');batchHead.append(node('h3',result.answer));group.append(batchHead);for(const item of result.items){const card=render(item,item.task_question,target);card.prepend(node('p',`${item.task_number}. ${item.task_question}`,'answer-task'));group.append(card);}return group;}const wrap=node('article',undefined,'answer message');const head=node('div',undefined,'answer-head');const details=node('div',undefined,'answer-details');head.append(details);details.append(node('span','', 'dot'),node('span',result.outcome?({not_found:'未找到指定对象',ambiguous:'需要确认对象',incomplete:'关联数据不完整'}[result.outcome.kind]||'查询反馈'):result.status==='conversation'?'说明与能力边界':result.mode==='confirmed'?'已确认条件 · 实际数据查询':result.mode==='model'?(result.status==='conversation'?'使用帮助与交流':result.status==='clarify'?'请补充业务口径':'DeepSeek 理解 · 实际数据查询'):'引导查询 · 实际数据结果'));if(result.evidence?.length)details.append(button('查看关联依据 ↗',()=>result.evidence_total>result.evidence.length?pagedEvidence(result,session):evidence(result.evidence),'evidence-link'));wrap.append(head,node('h3',result.attributes?.length>1?attributeSummary(result):result.answer));if(result.business_scope)wrap.append(node('p',result.business_scope,'business-scope'));if(result.query_basis||result.note){const basis=node('details',undefined,'query-basis');basis.append(node('summary','查询依据'));if(result.query_basis?.conditions)basis.append(node('p',result.query_basis.conditions));if(result.note)basis.append(node('p',result.note));if(result.query_basis?.plan){const technical=node('details');technical.append(node('summary','技术条件'),node('pre',JSON.stringify(result.query_basis.plan,null,2)));basis.append(technical);}wrap.append(basis);}const resultContext=result.context||result.task_context||{};const pointQuery=result.query||resultContext.query;if(result.status==='ok'&&!result.entity&&(pointQuery?.target==='points'||['alarms','measurements'].includes(resultContext.operation))){wrap.append(node('p','查询范围：全部测点','note'));}if(result.path?.length&&!result.attributes){const path=node('div',undefined,'path');result.path.forEach((e,i)=>{if(i)path.append(node('span','→'));const b=button(e.name||e.level,()=>choose(e));b.append(node('code',e.code));path.append(b);});wrap.append(path);}if(result.metrics?.length){const ms=node('div',undefined,'metrics');for(const m of result.metrics){const d=node('div',undefined,'metric');d.append(node('span',m.label),node('b',m.value));ms.append(d);}wrap.append(ms);}
if(result.status==='ok' && result.total===0 && !result.attributes && !result.relation){wrap.append(node('p','没有匹配记录；查询条件已保留，可继续修改。','note'));}
if(result.threshold_details?.length){const details=node('details');details.open=true;details.append(node('summary','各来源阈值字段'));for(const item of result.threshold_details){details.append(node('strong',`${item.source||'未提供来源'} · ${item.time}`));const table=node('table');for(const [label,value] of Object.entries(item.thresholds)){const row=node('tr');row.append(node('th',label),node('td',value));table.append(row);}details.append(table);}wrap.append(details);}if(result.chart)wrap.append(renderChart(result.chart));if(result.aggregation){wrap.append(node('p',(result.columns||[]).join(' / '),'note'));}if(result.total){const holder=node('div',undefined,'table-wrap');drawRows(holder,result.records,result.columns);wrap.append(holder);let page=0;const pager=node('div',undefined,'pager');const info=node('span',`共 ${result.total} 条 · 第 1 页`);const prev=button('上一页',()=>turn(-1));const next=button('下一页',()=>turn(1));prev.disabled=true;next.disabled=result.total<=20;const originalSession=session;async function turn(step){try{const target=page+step;const v=await api('/api/page',{session:originalSession,result:result.result,page:target});page=target;drawRows(holder,v.records,result.columns);info.textContent=`共 ${result.total} 条 · 第 ${page+1} 页`;prev.disabled=page===0;next.disabled=(page+1)*20>=result.total;}catch(e){info.textContent=e.message;}}pager.append(info,prev,next);wrap.append(pager);}

if(result.relation){const rel=result.relation;if(rel.status==='reference_only'){wrap.append(node('p',`${rel.subject.name} → ${rel.target_code}（未导入详情）`,'note'));}else if(rel.status==='resolved'&&rel.kind==='parent'){wrap.append(node('p',rel.navigated===false?`已查看父对象：${rel.target.name}（${rel.target.code}）；当前讨论对象保持为${rel.subject.name}（${rel.subject.code}）。如需移动，请明确向上一层。`:`当前讨论对象已转到父对象：${rel.target.name}（${rel.target.code}）。明确要求向上一层可继续导航。`,'note'));}if(rel.status!=='resolved'){wrap.append(head);target.append(wrap);return wrap;}}
if(result.attributes){if(result.attributes.length>1){const holder=node('div',undefined,'table-wrap attribute-results');const table=node('table');table.setAttribute('aria-label','对象属性');const thead=node('thead'),header=node('tr');const sourced=result.attributes.some(f=>f.source||f.time);for(const label of ['属性','内容',...(sourced?['来源 / 测量时间']:[])])header.append(node('th',label));thead.append(header);table.append(thead);const tbody=node('tbody');for(const fact of result.attributes){if(fact.property==='name'&&fact.status==='known'&&fact.value===result.path?.[0]?.name&&!fact.source&&!fact.time)continue;const tr=node('tr'),key=node('th',fact.label);key.scope='row';const value=fact.status==='known'?(fact.display_value??fact.value):fact.status==='missing'?'未提供':'无法可靠确定';const cell=node('td');cell.append(node(['code','parent','class_code'].includes(fact.property)?'code':'span',String(value)));if(fact.explanation)cell.append(node('p',fact.explanation,'note'));tr.append(key,cell);if(sourced)tr.append(node('td',`${fact.source||'来源未提供'} / ${fact.time||'时间未提供'}`));tbody.append(tr);}table.append(tbody);holder.append(table);wrap.append(holder);} wrap.append(head);target.append(wrap);return wrap;}

if(result.status!=='ok'||result.query||result.aggregation){wrap.append(head);target.append(wrap);return wrap;}
const fs=node('div',undefined,'followups');const e=result.entity;if(e?.tree==='config'){fs.append(follow('对应设备类','equipment_class',e),follow('直接部件','parts',e),follow('全部下级部件','parts',e,'all'),follow('所属部件类','part_class',e),follow('上级对象','parent',e));}else if(e?.tree==='pbs'){fs.append(follow('查看测点','measurements',e),follow('全部阈值','threshold',e),follow('报警多久了？','duration',e));}fs.append(follow('查询全部报警测点','alarms',null));wrap.append(fs);wrap.append(head);target.append(wrap);return wrap;}
function applyResultContext(result){if(result.status==='ok'||result.status==='clarify'||result.status==='batch'||result.outcome){context=result.context;selection=null;}}
async function run(label,intent){if(busy||!meta)return;disableReviews();busy=true;try{await contextSync;}catch(e){busy=false;showNotice('条件清除失败，请新建对话后重试。');return;}const gen=++generation;const currentSession=session;const started=performance.now();controller=new AbortController();$('welcome').hidden=true;$('conversation').append(node('div',label,'message user'));const pending=node('div',intent?'正在查询原始数据…':'正在理解问题…','message note');$('conversation').append(pending);$('send').disabled=true;$('cancel').hidden=false;$('timing').textContent='';try{const result=await api('/api/query',{session:currentSession,question:label,selection,intent},controller.signal);if(gen!==generation)return;pending.remove();rememberTurn(label,result);for(const obj of [...(result.path||[]),...(result.records||[])])rememberObject(obj);applyResultContext(result);setContext();const box=render(result,label);await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);const elapsed=performance.now()-started;const labelTime=`${(elapsed/1000).toFixed(2)}秒 · ${result.status==='review'?'条件待确认，尚未查询':result.outcome?'查询反馈已展示':result.status==='clarify'?'待补充业务口径，尚未查询':intent?'引导查询，不含模型耗时':elapsed>5000?'超过5秒目标':'完整结果已展示'}`;$('timing').textContent=labelTime;const timeNote=node('span',labelTime,'answer-time');const details=box.querySelector('.answer-details');if(result.status==='batch'){const totalTime=node('span',labelTime,'batch-time');box.querySelector('.batch-heading').append(totalTime);}else if(details){const link=details.querySelector('.evidence-link');details.insertBefore(node('span','','dot'),link);details.insertBefore(timeNote,link);}else{box.prepend(timeNote);}revealMessage(box);}catch(e){if(gen!==generation)return;pending.remove();showNotice(e.name==='AbortError'?'已取消；上下文未更新。':e.message);}finally{if(gen===generation){busy=false;$('send').disabled=false;$('cancel').hidden=true;controller=null;}}}
async function reset(){historyLoad++;const wasBusy=busy;showCurrentConversation();currentConversationScroll=0;$('workspace').scrollTop=0;contextSync=Promise.resolve();generation++;controller?.abort();const old=session;session=createSessionId();selection=null;context={};busy=false;if(wasBusy)api('/api/reset',{session:old});else api('/api/review/cancel',{session:old}).catch(()=>{});$('conversation').replaceChildren();$('welcome').hidden=false;$('send').disabled=false;$('cancel').hidden=true;$('timing').textContent='';setContext();}
let searchGeneration=0,browserHistory=[],browserView=null;
function relationCard(e){const card=node('div',undefined,'relation-card');const open=button(e.name||'名称未提供',()=>navigateObject(e.code),'relation-open');open.append(node('code',e.code));card.append(open,node('span',(e.level||'层级未提供')+' · '+(e.children?`${e.children} 个直接下级`:'无下级'),'relation-type'));const actions=node('div',undefined,'relation-actions');actions.append(button(e.children?'浏览下级 →':'查看位置',()=>navigateObject(e.code)),button('选此对象提问',()=>choose(e)));card.append(actions);return card;}
async function loadBrowser(view,push=true){const gen=++searchGeneration;if(push&&browserView)browserHistory.push({...browserView});browserView={...view};$('tree').value=view.tree;$('search').value=view.q||'';$('objectList').textContent='正在读取对象关系…';try{const params=new URLSearchParams({tree:view.tree,page:String(view.page||0)});if(view.code!==null&&view.code!==undefined)params.set('code',view.code);else if(view.q)params.set('q',view.q);const data=await api('/api/browse?'+params);if(gen!==searchGeneration)return;browserView.page=data.page;$('objectList').replaceChildren();const nav=node('div',undefined,'relation-nav');const back=button('← 返回',()=>{const prev=browserHistory.pop();if(prev){$('tree').value=prev.tree;$('search').value=prev.q||'';loadBrowser(prev,false);}});back.disabled=!browserHistory.length;nav.append(back,button('返回顶层',()=>loadBrowser({tree:view.tree,code:null,q:'',page:0})));for(const e of data.path){nav.append(node('span','›'),button(e.name||e.code,()=>navigateObject(e.code)));}if(data.current)nav.append(node('span','›'),node('strong',data.current.name||data.current.code));$('objectList').append(nav);
if(data.current){rememberObject(data.current);const focus=node('div',undefined,'relation-focus');focus.append(node('span','当前浏览对象','relation-focus-label'),node('h3',data.current.name||'名称未提供'),node('code',data.current.code),node('p',(data.current.level||'层级未提供')+` · ${data.total} 个直接下级`),button('选此对象提问',()=>choose(data.current),'relation-select'));if(data.current.parent&&!data.path.length)focus.append(node('small','上级编码 '+data.current.parent+' 未在本树中匹配'));$('objectList').append(focus,node('div','↓ 以下为该对象的直接下级','relation-connector'));}
const heading=node('div',undefined,'relation-heading');heading.append(node('strong',data.current?'直接下级':view.q?'搜索结果':'顶层对象'),node('span',`共 ${data.total} 个对象`));$('objectList').append(heading);const grid=node('div',undefined,'relation-grid');for(const e of data.records)grid.append(relationCard(e));if(!data.records.length)grid.append(node('p',data.current?'该对象没有直接下级。可返回上级，或选为当前问答对象。':'未找到匹配对象，请调整名称或编码。'));$('objectList').append(grid);if(data.total>data.page_size){const pager=node('div',undefined,'pager');const prev=button('上一页',()=>loadBrowser({...browserView,page:data.page-1},false));const next=button('下一页',()=>loadBrowser({...browserView,page:data.page+1},false));prev.disabled=data.page===0;next.disabled=(data.page+1)*data.page_size>=data.total;pager.append(prev,node('span',`第 ${data.page+1} / ${Math.ceil(data.total/data.page_size)} 页`),next);$('objectList').append(pager);}}
catch(e){if(gen!==searchGeneration)return;$('objectList').replaceChildren(node('p',e.message));if(browserHistory.length)$('objectList').append(button('返回上一位置',()=>loadBrowser(browserHistory.pop(),false)));}}
function navigateObject(code){loadBrowser({tree:browserView.tree,code,q:browserView.q||'',page:0});}
function search(){loadBrowser({tree:$('tree').value,code:null,q:$('search').value.trim(),page:0});}
function browse(){$('browser').showModal();if(browserView)loadBrowser(browserView,false);else search();}
for(const dialog of document.querySelectorAll('dialog')){
 let startedOutside=false;
 const outside=e=>{const r=dialog.getBoundingClientRect();return e.target===dialog&&(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom);};
 dialog.addEventListener('pointerdown',e=>{startedOutside=e.button===0&&outside(e);});
 dialog.addEventListener('pointercancel',()=>{startedOutside=false;});
 dialog.addEventListener('click',e=>{const dismiss=startedOutside&&outside(e);startedOutside=false;if(dismiss)dialog.close();});
 dialog.addEventListener('close',()=>{startedOutside=false;});
}
$('browse').onclick=browse;$('pick').onclick=browse;$('new').onclick=reset;$('closeBrowser').onclick=()=>$('browser').close();$('closeEvidence').onclick=()=>$('evidence').close();$('searchButton').onclick=()=>search();$('tree').onchange=()=>search();$('search').onkeydown=e=>{if(e.key==='Enter')search();};
$('startDevice').onclick=()=>run('这个 PBS 对象对应什么设备？',{operation:'equipment',entity:sample,scope:'direct'});$('startParts').onclick=()=>run('这个设备构型下面有哪些部件？',{operation:'parts',entity:sample,scope:'direct'});$('startAlarms').onclick=()=>run('哪些测点开启了监测且已报警？',{operation:'alarms',entity:null,scope:'direct'});
$('ask').onsubmit=e=>{e.preventDefault();const q=$('question').value.trim();if(q){$('question').value='';run(q);}};$('question').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('ask').requestSubmit();}};
$('cancel').onclick=()=>{for(const p of document.querySelectorAll('#conversation > .note'))p.remove();generation++;controller?.abort();api('/api/reset',{session});context={};busy=false;$('send').disabled=false;$('cancel').hidden=true;setContext();showNotice('已取消，未更新查询上下文。','note');};
api('/api/meta').then(v=>{meta=v;$('logout').hidden=!v.auth_required;refreshCounts(v);$('modelState').replaceChildren(node('div','DeepSeek Flash'),node('div',v.model.available?'密钥已配置':'待配置密钥'));}).catch(e=>{$('modelState').replaceChildren(node('div','DeepSeek Flash'),node('div','服务未连接'));});




function refreshCounts(v){for(const e of document.querySelectorAll('#welcome .cards,#welcome > .context'))e.hidden=v.sample_available===false;for(const [k,n] of Object.entries(v.counts||{})){const e=$('count-'+k);if(e)e.textContent=n.toLocaleString();}}
let importSchema=null,importPreview=null,importWorking=false;
function invalidateImport(){importPreview=null;$('commitImport').disabled=true;$('importFeedback').replaceChildren();}
function importWorkingState(value){importWorking=value;for(const id of ['importFiles','importMode','previewImport','previewRestore','importHistory'])$(id).disabled=value;for(const e of $('importFileList').querySelectorAll('select'))e.disabled=value;$('commitImport').disabled=value||!importPreview;}
$('importData').onclick=async()=>{if(busy){showNotice('请先完成当前查询再导入数据。');return;}try{importSchema=await api('/api/import/schema');$('importHistory').replaceChildren();for(const h of importSchema.history){const option=node('option',new Date(h.created*1000).toLocaleString()+' · '+Object.entries(h.counts).map(([k,n])=>importSchema.labels[k]+' '+n).join(' / '));option.value=h.id;$('importHistory').append(option);}invalidateImport();$('importDialog').showModal();}catch(e){showNotice(e.message);}};
$('closeImport').onclick=()=>{if(!importWorking)$('importDialog').close();};$('importDialog').addEventListener('cancel',e=>{if(importWorking)e.preventDefault();});
$('importMode').onchange=()=>{invalidateImport();$('importModeHint').textContent=$('importMode').value==='replace'?'全部五类已有数据将被替换；未提供的类型变为空。校验成功后才切换，保留旧快照。':'同编码、同内容的对象跳过；同编码但内容不同会报错。相同内容文件不重复追加。';};
$('importFiles').onchange=()=>{invalidateImport();$('importFileList').replaceChildren();for(const file of $('importFiles').files){const row=node('div',undefined,'import-file');row.append(node('strong',file.name));const select=node('select');select.setAttribute('aria-label',file.name+' 数据类型');for(const [k,label] of Object.entries(importSchema.labels)){const option=node('option',label);option.value=k;select.append(option);}const known={'pbs.csv':'pbs','构型树.csv':'config','设备类.csv':'equipment_class','部件类.csv':'part_class','测量点数据分析.csv':'points'};if(known[file.name.toLowerCase()])select.value=known[file.name.toLowerCase()];const details=node('details');const summary=node('summary','查看要求的字段');details.append(summary);const fields=node('p',importSchema.schemas[select.value].join('、'),'note');details.append(fields);select.onchange=()=>{invalidateImport();fields.textContent=importSchema.schemas[select.value].join('、');};row.append(select,details);$('importFileList').append(row);}};
function fileBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('无法读取文件：'+file.name));r.readAsDataURL(file);});}
async function previewData(restore){invalidateImport();importWorkingState(true);$('importFeedback').textContent='正在校验文件和数据关系…';try{let body;if(restore){if(!$('importHistory').value)throw new Error('暂无历史快照。');body={restore:$('importHistory').value};}else{const files=Array.from($('importFiles').files);if(!files.length||files.length>10)throw new Error('请选择1至10个CSV文件。');if(files.some(f=>f.size>16*1024*1024)||files.reduce((s,f)=>s+f.size,0)>32*1024*1024)throw new Error('单文件最多16MB，总大小最多32MB。');const selects=$('importFileList').querySelectorAll('select');body={mode:$('importMode').value,files:await Promise.all(files.map(async(f,i)=>({name:f.name,kind:selects[i].value,content:await fileBase64(f)})))};}const v=await api('/api/import/preview',body);importPreview=v.preview;$('importFeedback').replaceChildren(node('h3','校验通过，请核对导入后数量'));const table=node('table');const tr=node('tr');for(const label of ['数据类型','当前','导入后'])tr.append(node('th',label));table.append(tr);for(const [k,n] of Object.entries(v.after)){const row=node('tr');row.append(node('td',importSchema.labels[k]),node('td',String(v.before[k])),node('td',String(n)));table.append(row);}$('importFeedback').append(table,node('p','重复文件跳过：'+v.skipped_files+'。提交后将清除旧对话上下文。','note'));for(const w of v.warnings)$('importFeedback').append(node('p',w,'note'));$('commitImport').textContent=v.mode==='restore'?'确认恢复快照':v.mode==='replace'?'确认清空并导入':'确认追加导入';}catch(e){$('importFeedback').textContent=e.message;}finally{importWorkingState(false);}}
$('previewImport').onclick=()=>previewData(false);$('previewRestore').onclick=()=>previewData(true);
$('commitImport').onclick=async()=>{if(!importPreview)return;importWorkingState(true);try{const v=await api('/api/import/commit',{preview:importPreview});importPreview=null;meta=await api('/api/meta');await reset();objectDetails.clear();refreshCounts(meta);$('importFeedback').replaceChildren(node('h3','导入成功'),node('p','已切换数据并清除旧查询。关闭窗口后即可开始提问；历史快照可用于恢复。'));$('importFiles').value='';$('importFileList').replaceChildren();}catch(e){$('importFeedback').append(node('p',e.message,'error'));}finally{importWorkingState(false);}};

$('importHistory').onchange=invalidateImport;

$('logout').onclick=async()=>{try{await api('/api/auth/logout',{});clearHistory();location.replace('/login');}catch(e){showNotice(e.message);}};


// 用户可见历史与模型的短上下文窗口分别维护。
const historyKey='iccm-tab-history-v1';
let historyTurns=[],historyStorageError=false;
try {const saved=JSON.parse(sessionStorage.getItem(historyKey)||'[]');if(Array.isArray(saved))historyTurns=saved.filter(x=>x&&typeof x.question==='string'&&typeof x.answer==='string').slice(-100);}catch(e){}
function historyAnswer(result){
 if(result.status==='batch')return result.items.map(x=>x.task_question+'：'+historyAnswer(x)).join('\n');
 return result.answer||'';
}
function rememberTurn(question,result){
 const savedResult=historySnapshot(result);delete savedResult.trace;
 historyTurns.push({question,result:savedResult,answer:historyAnswer(result),time:new Date().toLocaleString(),session,version:result.version||meta.version,status:result.status});
 historyTurns=historyTurns.slice(-100);
 try{sessionStorage.setItem(historyKey,JSON.stringify(historyTurns));historyStorageError=false;}catch(e){historyStorageError=true;}
}
function clearHistory(){historyTurns=[];try{sessionStorage.removeItem(historyKey);}catch(e){}}
let historyView=false,currentConversationScroll=0;
function showCurrentConversation(){
 const returningFromHistory=historyView;
 historyView=false;$('historyPane').hidden=true;$('conversation').hidden=false;
 $('composer').hidden=false;$('welcome').hidden=$('conversation').children.length>0;
 $('new').setAttribute('aria-pressed','true');$('history').setAttribute('aria-pressed','false');
 if(returningFromHistory)$('workspace').scrollTop=currentConversationScroll;
}
function historySnapshot(result){
 const copy=JSON.parse(JSON.stringify(result));
 if(copy.review)copy.review.readOnly=true;
 if(copy.items)copy.items=copy.items.map(historySnapshot);
 if(copy.evidence?.length>30){copy.evidence=copy.evidence.slice(0,30);copy.note=(copy.note||'')+' 历史保留前30条汇总依据。';}
 const saved=(copy.records||[]).length;
 if(copy.total>saved)copy.note=(copy.note||'')+` 历史保留当时展示的 ${saved} 条记录（原结果共 ${copy.total} 条），完整明细请返回当前对话重新查询。`;
 copy.total=saved;return copy;
}
let historyLoad=0;
async function openHistorySession(id){
 if(busy)return;
 const load=++historyLoad;
 const turns=historyTurns.filter(t=>t.session===id);
 if(!turns.length){$('historyPane').hidden=false;$('historyConversation').textContent='暂无历史对话。';$('conversation').hidden=true;$('welcome').hidden=true;$('composer').hidden=true;historyView=true;return;}
 const latest=turns.at(-1);let restored=null,error='';
 if(latest.version!==meta.version)error='这段历史使用其他数据快照，仅供回看。请新建对话查询当前数据。';
 else if(!latest.result?.continuation)error='旧版历史没有可恢复的查询状态，仅供回看。请新建对话重新查询。';
 else try{restored=await api('/api/resume',{session:id,continuation:latest.result.continuation});}catch(e){error=e.message;}
 if(load!==historyLoad)return;
 historyView=false;$('historyPane').hidden=true;$('conversation').hidden=false;$('welcome').hidden=true;
 const body=$('conversation');body.replaceChildren();
 if(restored){session=id;context=restored.context;selection=null;contextSync=Promise.resolve();}
 for(const turn of turns){body.append(node('div',turn.question,'message user'));if(turn.result){const card=render(historySnapshot(turn.result),turn.question,body);if(!restored)for(const b of card.querySelectorAll('button'))b.disabled=true;}else body.append(node('p',turn.answer));}
 $('composer').hidden=!restored;
 if(error)body.append(node('p',error,'error'));
 else {setContext();$('timing').textContent='已恢复此会话，可以继续提问。';}
 $('new').setAttribute('aria-pressed','false');$('history').setAttribute('aria-pressed','true');
 for(const b of $('historySessions').children)b.setAttribute('aria-current',b.dataset.session===id?'true':'false');
 $('workspace').scrollTop=0;
}
$('history').onclick=()=>{
 const sessions=new Map();for(const turn of historyTurns)if(!sessions.has(turn.session))sessions.set(turn.session,turn);
 const list=$('historySessions');list.replaceChildren();list.hidden=false;
 for(const [id,turn] of [...sessions].reverse()){
  const entry=button(turn.question,()=>openHistorySession(id),'history-session');entry.dataset.session=id;entry.title=turn.question;list.append(entry);
 }
 openHistorySession([...sessions.keys()].at(-1));
};
$('backToCurrent').onclick=showCurrentConversation;

async function pagedEvidence(result,sid,page=0){
 try{const data=await api('/api/evidence',{session:sid,result:result.result,page});evidence(data.evidence);const nav=node('div',undefined,'pager');if(page)nav.append(button('上一页依据',()=>pagedEvidence(result,sid,page-1)));nav.append(node('span',`依据 ${page*20+1}–${Math.min((page+1)*20,data.total)} / ${data.total}`));if((page+1)*20<data.total)nav.append(button('下一页依据',()=>pagedEvidence(result,sid,page+1)));$('evidenceBody').append(nav);}catch(e){showNotice(e.message);}
}
