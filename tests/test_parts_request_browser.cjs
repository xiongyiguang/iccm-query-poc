
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const out=process.env.PARTS_BROWSER_OUTPUT||'docs/.staging/parts-request-20260924/browser-first';
if(fs.existsSync(out+'/results.json'))throw Error('Preserve evidence');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();
 const records=[],checks=[],errors=[];p.setDefaultTimeout(45000);
 p.on('pageerror',e=>errors.push(String(e)));
 for(const route of ['query','confirm'])await p.route('**/api/'+route,r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({records,checks,errors},null,2));
 const clean=r=>{const c=JSON.parse(JSON.stringify(r));delete c.continuation;return c;};
 function check(name,ok){checks.push({name,passed:!!ok});save();assert.ok(ok,name);}
 async function ask(q){
  await p.locator('#question').fill(q);
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');
  await p.locator('#send').click();const r=await (await wait).json();
  await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({phase:'query',question:q,response:clean(r)});save();return r;
 }
 async function confirm(){
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/confirm'));
  await p.locator('#conversation .review-confirm:enabled').last().click();
  const response=await wait,r=await response.json();
  await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({phase:'confirm',submitted:response.request().postDataJSON(),response:clean(r)});save();return r;
 }
 try{
  await p.goto('http://127.0.0.1:8769');
  await p.waitForFunction(()=>document.querySelector('#modelState')&&!document.querySelector('#modelState').textContent.includes('正在检查'));
  await p.locator('#new').click();
  const r=await ask('构型MOHB01的全部下级部件有多少？');
  check('complex request preview without execution',r.status==='review'&&r.records.length===0&&r.timings_ms.execution===0);
  const card=p.locator('#conversation .query-review').last();
  check('inline without modal',await p.locator('dialog[open]').count()===0);
  check('tree restricted to config',await card.getByLabel('任务1对象树').locator('option').count()===1);
  check('original root visible',await card.getByLabel('任务1对象标识').inputValue()==='MOHB01');
  await card.getByLabel('任务1范围',{exact:true}).selectOption('direct');
  await p.screenshot({path:out+'/desktop-preview.png',fullPage:true});
  const first=await confirm();
  check('direct scope executed exactly',first.status==='ok'&&first.scope==='direct'&&first.entity?.code==='MOHB01'&&first.total===51);
  check('confirmation no model call',first.trace?.user_confirmed&&!first.trace?.raw_output&&!first.trace?.checklist_review);
  const follow=await ask('范围不变，根构型换成MOHB02。');
  check('followup preserves confirmed direct scope',follow.status==='review'&&follow.review.tasks[0].values.scope==='direct');
  const next=p.locator('#conversation .query-review').last();
  await next.getByLabel('任务1对象标识').fill('MOHB01');
  await next.getByLabel('任务1范围',{exact:true}).selectOption('all');
  await p.setViewportSize({width:900,height:900});
  await p.screenshot({path:out+'/small-preview.png',fullPage:true});
  check('no horizontal overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const second=await confirm();
  check('edited root and scope executed',second.status==='ok'&&second.scope==='all'&&second.entity?.code==='MOHB01');
  check('edited state retained',second.context.business_request.tasks[0].scope==='all'&&second.context.business_request.tasks[0].filters[0].value==='MOHB01');
  check('no browser errors',errors.length===0);
 }finally{save();await browser.close();}
 console.log(JSON.stringify({checks:checks.length,passed:checks.filter(x=>x.passed).length,errors}));
})().catch(e=>{console.error(e);process.exitCode=1;});
