const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.ICCM_TEST_URL||'http://127.0.0.1:8769';
const out=process.env.REVIEW_BROWSER_OUTPUT||'docs/.staging/query-review-20260924/browser-first';
if(fs.existsSync(out+'/results.json'))throw Error('Preserve existing evidence');
fs.mkdirSync(out,{recursive:true});
const frozen=JSON.parse(fs.readFileSync('docs/.staging/semantic-holdout-20260924/frozen.json','utf8'));
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();
 const records=[],checks=[],errors=[];let currentPreview;
 p.setDefaultTimeout(45000);p.on('pageerror',e=>errors.push(String(e)));
 await p.route('**/api/query',r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 await p.route('**/api/confirm',r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 const clean=r=>{const c=JSON.parse(JSON.stringify(r));delete c.continuation;return c;};
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({records,checks,errors},null,2));
 function check(name,ok){checks.push({name,passed:!!ok});save();assert.ok(ok,name);}
 async function ask(id,question){
  await p.locator('#question').fill(question);
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');
  await p.locator('#send').click();const response=await wait,r=await response.json();
  await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({id,question,phase:'interpretation',response:clean(r)});save();
  currentPreview=r;console.log(id,r.status,r.error||'',r.server_ms);
  return r;
 }
 async function confirm(id){
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/confirm'));
  await p.locator('#conversation .review-confirm:enabled').last().click();
  const response=await wait,r=await response.json();
  await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({id,phase:'confirmed_execution',submitted:response.request().postDataJSON(),response:clean(r)});save();
  check(id+' confirmed',r.mode==='confirmed'&&r.status==='ok');
  check(id+' no-model-after-confirm',r.trace?.user_confirmed&&!r.trace?.checklist_review&&!r.trace?.raw_output);
  console.log(id,'confirmed',r.total,r.server_ms);return r;
 }
 try{
  await p.goto(base);await p.waitForFunction(()=>document.querySelector('#modelState')&&!document.querySelector('#modelState').textContent.includes('正在检查'));
  for(let round=1;round<=3;round++){
   await p.locator('#new').click();
   const question=frozen.suites.A.find(x=>x.id==='A01').question;
   const r=await ask('bounds-'+round,question);
   check('bounds-'+round+' preview-only',r.status==='review'&&r.records.length===0&&r.timings_ms.execution===0&&!r.context.business_request);
   const card=p.locator('#conversation .query-review').last();
   check('bounds-'+round+' no-modal',(await p.locator('dialog[open]').count())===0);
   const rows=card.locator('.review-filter');
   let found=false;
   for(let i=0;i<await rows.count();i++){
    const row=rows.nth(i),field=await row.locator('select').nth(0).inputValue(),op=await row.locator('select').nth(1).inputValue();
    if(field==='value'&&['lte','lt'].includes(op)){await row.locator('select').nth(1).selectOption('lt');found=true;}
   }
   check('bounds-'+round+' upper-editable',found);
   if(round===1)await p.screenshot({path:out+'/confirmation-desktop.png'});
   const result=await confirm('bounds-'+round);
   check('bounds-'+round+' exact-upper',result.context.query.filters.some(f=>f.field==='value'&&f.operator==='lt'&&f.value==='80'));
   if(round===1){
    await ask('followup','下限改为55，上限和其他条件保持。');
    const after=await confirm('followup');
    check('followup-retains-confirmed-upper',after.context.query.filters.some(f=>f.field==='value'&&f.operator==='lt'&&f.value==='80'));
    check('followup-changes-lower',after.context.query.filters.some(f=>f.field==='value'&&f.operator==='gte'&&f.value==='55'));
   }
  }
  await p.locator('#new').click();
  const multi=await ask('multi','分别读取测量点名称51的测量值和单位，以及测量点名称52的预测值和真实值高2。');
  check('multi-preview',multi.status==='review'&&multi.review.tasks.length===2);
  await p.getByRole('checkbox',{name:'执行任务2',exact:true}).uncheck();
  const selected=await confirm('multi');
  check('multi-only-first-projection',JSON.stringify(selected.requested_properties)===JSON.stringify(['value','unit']));
  await p.locator('#new').click();
  await ask('cancel','筛选测量值大于50且小于80的测点。');
  const before=await p.locator('#new').boundingBox();
  await p.setViewportSize({width:900,height:768});
  await p.screenshot({path:out+'/confirmation-small.png'});
  check('small-no-horizontal-overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const waitCancel=p.waitForResponse(r=>r.url().endsWith('/api/review/cancel'));
  await p.locator('.query-review').last().getByRole('button',{name:'取消',exact:true}).click();await waitCancel;
  await p.waitForFunction(()=>document.querySelector('.review-feedback')?.textContent.includes('已取消'));
  check('cancel-disables-confirm',await p.locator('.query-review').last().getByRole('button',{name:'确认并查询',exact:true}).isDisabled());
  await p.setViewportSize({width:1536,height:900});
  const after=await p.locator('#new').boundingBox();
  check('sidebar-stable',before.x===after.x&&before.y===after.y&&before.width===after.width);
  await p.locator('#new').click();await p.locator('#history').click();
  await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));
  check('history-review-readonly',(await p.locator('.query-review .review-confirm:enabled').count())===0);
  await p.screenshot({path:out+'/history-readonly.png'});
  await p.locator('#new').click();
  const simple=await ask('simple','列出名称包含ABC的部件。');
  check('simple-direct',simple.status==='ok'&&!simple.review);
  check('no-browser-errors',errors.length===0);save();
 }catch(e){checks.push({name:'runner',passed:false,error:String(e)});save();process.exitCode=1;}
 finally{await ctx.close();await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(x=>x.passed).length,checks:checks.length,requests:records.length}));
})();

