
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const out=process.env.SEMANTIC_BROWSER_OUTPUT||'docs/.staging/semantic-review-20260924/browser-final';
if(fs.existsSync(out+'/results.json'))throw Error('Preserve previous evidence');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:1000},reducedMotion:'reduce'}),p=await ctx.newPage();
 const records=[],checks=[],errors=[];p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(String(e)));
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({method:'Deterministic model boundary; real browser, HTTP confirmation and imported database. Not model accuracy.',records,checks,errors},null,2));
 function check(name,ok){checks.push({name,passed:!!ok});save();assert.ok(ok,name);}
 const clean=r=>{const c=JSON.parse(JSON.stringify(r));delete c.continuation;return c;};
 for(const route of ['query','confirm'])await p.route('**/api/'+route,r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 try{
  await p.goto('http://127.0.0.1:8771');
  await p.waitForFunction(()=>document.querySelector('#modelState')&&!document.querySelector('#modelState').textContent.includes('正在检查'));
  await p.locator('#question').fill('MOHB 那个设备是什么？');
  const first=p.waitForResponse(r=>r.url().endsWith('/api/query'));await p.locator('#send').click();
  const preview=await (await first).json();records.push({phase:'preview',response:clean(preview)});save();
  await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  check('preview no query',preview.status==='review'&&preview.timings_ms.execution===0&&!preview.records.length);
  const region=p.locator('.review-disagreement');
  check('disagreement visible in main conversation',await region.isVisible()&&await p.locator('dialog[open]').count()===0);
  const text=await region.innerText();check('alternative shown without stale current summary',text.includes('「MOHB01」')&&!text.includes('当前待执行'));
  const card=p.locator('.query-review').last();
  check('editable original not overwritten',await card.getByLabel('筛选条件1值').inputValue()==='MOHB');
  await card.getByLabel('任务1查询对象').selectOption('equipment_class');
  check('editor is sole current condition source',await card.getByLabel('任务1查询对象').inputValue()==='equipment_class'&&!((await region.innerText()).includes('当前待执行')));
  await p.screenshot({path:out+'/desktop.png',fullPage:true});
  await p.setViewportSize({width:900,height:900});
  check('small viewport no overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check('small viewport warning retained',await region.isVisible());await p.screenshot({path:out+'/small.png',fullPage:true});
  const confirmed=p.waitForResponse(r=>r.url().endsWith('/api/confirm'));await card.locator('.review-confirm').click();
  const response=await confirmed,result=await response.json();records.push({phase:'confirmed',submitted:response.request().postDataJSON(),response:clean(result)});save();
  check('user-chosen object executed',result.status==='ok'&&result.entity?.tree==='equipment_class'&&result.entity?.code==='MOHB');
  check('edited disagreement resolved without model',result.trace?.semantic_review_resolution?.candidate_edited===true&&result.trace.user_confirmed&&!result.trace.raw_output&&!result.trace.checklist_review);
  check('new confirmed state matches selection',result.context.business_request.tasks[0].target==='equipment_class'&&result.context.business_request.tasks[0].filters[0].value==='MOHB');
  check('no browser errors',errors.length===0);
 }finally{save();await browser.close();}
 console.log(JSON.stringify({checks:checks.length,passed:checks.filter(x=>x.passed).length,errors}));
})().catch(e=>{console.error(e);process.exitCode=1;});
