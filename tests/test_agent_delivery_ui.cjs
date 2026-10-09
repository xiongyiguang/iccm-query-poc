// 用真实模型已保存回执检查实际页面呈现；阻止新会话和外网，不新增模型调用。
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const [url,input,out,diagnosticInput]=process.argv.slice(2);
if(!url||!input||!out||new URL(url).hostname!=='127.0.0.1')throw Error('仅允许本机URL，并指定真实回放结果与新输出目录');
const evidence=JSON.parse(fs.readFileSync(input,'utf8'));
if(!evidence.complete||evidence.results.length!==117)throw Error('需要完整117步真实结果，不能用未完成记录接受页面');
fs.mkdirSync(out,{recursive:false});
let browser;
(async()=>{
 browser=await chromium.launch({headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:980}}),page=await context.newPage();
 const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 await context.route('**/*',route=>{
  const u=new URL(route.request().url());
  if(u.hostname!=='127.0.0.1')return route.abort();
  if(u.pathname==='/api/new')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'receipt-ui-only',model:'真实回执页面回放 · 不调用模型'})});
  if(u.pathname==='/api/ask')return route.abort();
  return route.continue();
 });
 await page.goto(url);await page.locator('#send').waitFor({state:'visible'});
 checks.push({name:'new_session_default_sol',pass:await page.locator('#model-choice').inputValue()==='gpt-6-sol'});
 const selected=['threshold-3','top-time-1','partial-1','limit-1','scope-name','scope-filter','identity-1'];
 for(const id of selected){
  const row=evidence.results.find(r=>r.id===id);if(!row)throw Error('缺少真实用例'+id);
  await page.evaluate(events=>{
   document.querySelector('#conversation').replaceChildren();
   for(const e of events)render(e);
  },row.events);
  const tools=page.locator('.tool');if(await tools.count()===0)throw Error(id+'无实际工具卡片');
  const final=page.locator('#conversation>.assistant:not(.commentary)').last();
  const published=await final.innerText();
  checks.push({name:id+'_published_receipt',pass:published===row.delivered_answer,original_business_pass:row.passed});
  // closed details中的元素仍可能有布局尺寸；核验折叠状态及实际可见性。
  const tech=await page.locator('.technical').evaluateAll(xs=>xs.every(x=>!x.open&&[...x.querySelectorAll('pre')].every(p=>!p.checkVisibility())));
  checks.push({name:id+'_technical_collapsed',pass:tech});
  const last=tools.last();await last.locator('.result-details>summary').click();
  const understanding=await last.locator('.query-understanding').innerText();
  if(id==='threshold-3'){
   checks.push({name:'threshold_goal_business_label',pass:understanding.includes('报警阈值')&&!understanding.includes('thresholds')});
   const facts=row.response?.attributes||[];
   const rows=await last.locator('.result-details table').first().locator('tbody tr').allTextContents();
   checks.push({name:'sorted_facts_same_order',pass:rows.length===facts.length&&facts.every((f,i)=>rows[i].includes(String(f.display_value??f.value??'未提供')))});
  }
  if(id==='top-time-1'){
   const columns=await last.locator('.result-details table').first().locator('thead').innerText();
   checks.push({name:'time_and_value_columns',pass:columns.includes('测量时间')&&columns.includes('测量值')});
  }
  if(id==='partial-1')checks.push({name:'partial_not_all_completed',pass:(await last.locator('.tool-status').innerText()).includes('需要核对')&&understanding.includes('实际查询口径')});
  if(id==='limit-1')checks.push({name:'bounds_are_visible',pass:published.includes('100')&&!(row.response?.goal_receipt?.completed)});
  if(id==='scope-name'||id==='scope-filter'){
   checks.push({name:id+'_actual_parent_scope',pass:understanding.includes('XJ2ABC002MO&MOHB01')&&understanding.includes('PBS')});
   if(id==='scope-filter')checks.push({name:'zero_with_root_and_source',pass:published.includes('0 条')&&understanding.includes('源系统1')&&published.includes('XJ2ABC002MO&MOHB01')});
  }
  if(id==='identity-1'){
   const records=row.response?.records||[];
   checks.push({name:'cross_domain_candidates_not_selected',pass:records.length===2&&!row.response?.entity&&!row.response?.goal_receipt?.completed&&published.includes('尚未选定')});
   const displayed=await last.locator('.result-details').innerText();
   checks.push({name:'actual_candidate_names_visible',pass:records.every(r=>displayed.includes(r.name)&&displayed.includes(r.code))});
  }
  await last.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
 }
 let diagnosticMethod=null;
 if(diagnosticInput){
  const fixture=JSON.parse(fs.readFileSync(diagnosticInput,'utf8'));diagnosticMethod=fixture.method;
  await page.evaluate(events=>{document.querySelector('#conversation').replaceChildren();for(const e of events)render(e);},fixture.events);
  const card=page.locator('.tool').last(),actualError=fixture.events.find(e=>e.kind==='tool_error').text;
  checks.push({name:'offline_protocol_error_business_message',pass:(await card.locator('.tool-content').innerText()).includes('查询参数未通过核验')&&!(await card.locator('.tool-content').innerText()).includes('request.')});
  checks.push({name:'offline_protocol_error_path_retained',pass:(await card.locator('.technical').textContent()).includes(actualError)});
  checks.push({name:'offline_protocol_error_technical_collapsed',pass:await card.locator('.technical').evaluate(x=>!x.open)});
  await page.screenshot({path:path.join(out,'protocol-error.png'),fullPage:true});
 }
 checks.push({name:'no_browser_errors',pass:errors.length===0});
 const report={method:'实际浏览器对真实保存回执的呈现验证；新会话/提问被拦截，不是新增模型或完整浏览器问答复测',diagnosticMethod,checks,errors,passed:checks.every(x=>x.pass),input:path.resolve(input),screenshots:[...selected.map(id=>id+'.png'),...(diagnosticInput?['protocol-error.png']:[])]};
 fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({passed:report.passed,checks:checks.length,errors:errors.length}));
 if(!report.passed)process.exitCode=1;
})().catch(e=>{console.error(e.message);process.exitCode=1;}).finally(async()=>{if(browser)await browser.close();});
