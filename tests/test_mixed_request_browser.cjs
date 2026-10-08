const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const out=process.env.MIXED_BROWSER_OUTPUT||'docs/.staging/mixed-request-20260924/browser-first';
assert(!fs.existsSync(out+'/results.json'));fs.mkdirSync(out,{recursive:true});
const frozen=JSON.parse(fs.readFileSync('docs/.staging/mixed-request-20260924/frozen.json','utf8'));
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();
 const records=[],checks=[],errors=[];p.setDefaultTimeout(45000);p.on('pageerror',e=>errors.push(String(e)));
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({records,checks,errors},null,2));
 function check(name,ok){checks.push({name,passed:!!ok});save();assert.ok(ok,name);}
 const clean=x=>{const r=structuredClone(x);delete r.continuation;return r;};
 for(const endpoint of ['query','confirm'])await p.route('**/api/'+endpoint,r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 async function ask(id,q){
  await p.locator('#question').fill(q);const wait=p.waitForResponse(r=>r.url().endsWith('/api/query'));
  await p.locator('#send').click();const r=await (await wait).json();await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({id,question:q,phase:'preview',response:clean(r)});save();return r;
 }
 async function confirm(id){
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/confirm'));await p.locator('.review-confirm:enabled').last().click();
  const res=await wait,r=await res.json();await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  records.push({id,phase:'execution',submitted:res.request().postDataJSON(),response:clean(r)});save();return r;
 }
 try{
  await p.goto(process.env.ICCM_TEST_URL||'http://127.0.0.1:8769');await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  for(let n=1;n<=2;n++)for(const id of ['M02','M05','M08']){
   await p.locator('#new').click();const c=frozen.cases.find(x=>x[0]===id),r=await ask(id+'-'+n,c[1]);
   check(id+'-'+n+' preview-no-query',r.status==='review'&&r.records.length===0&&r.timings_ms.execution===0&&!r.context.business_request);
   const card=p.locator('.query-review').last(),noteIndex=r.review.tasks.findIndex(x=>!x.enabled),note=card.locator('.review-task').nth(noteIndex);
   check(id+'-'+n+' note-visible-readonly',noteIndex>=0&&await note.isVisible()&&(await note.locator('input,select,textarea').count())===0&&(await note.innerText()).includes(r.review.tasks[noteIndex].message));
   check(id+'-'+n+' inline-no-dialog',(await p.locator('dialog[open]').count())===0);
   if(n===1&&id==='M05')await p.screenshot({path:out+'/mixed-explanation-first.png'});
   if(n===1&&id==='M08')await card.getByRole('checkbox',{name:'执行任务1',exact:true}).uncheck();
   const result=await confirm(id+'-'+n),expected=(n===1&&id==='M08')?['t2','t3']:r.review.tasks.map((_,i)=>'t'+(i+1));
   check(id+'-'+n+' delivered',result.status==='batch'&&result.items.every(x=>['ok','conversation'].includes(x.status)));
   check(id+'-'+n+' stable-committed-tasks',JSON.stringify(result.context.business_request.tasks.map(x=>x.id))===JSON.stringify(expected));
   check(id+'-'+n+' no-model-after-confirm',result.trace.user_confirmed&&!result.trace.checklist_review&&!result.trace.raw_output);
   check(id+'-'+n+' note-label',await p.getByText('说明与能力边界',{exact:true}).last().isVisible());
   if(n===1&&id==='M02')await p.screenshot({path:out+'/mixed-capability-result.png'});
  }
  await p.locator('#new').click();await ask('cancel',frozen.cases.find(x=>x[0]==='M05')[1]);
  await p.setViewportSize({width:900,height:768});check('small-no-overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  const wait=p.waitForResponse(r=>r.url().endsWith('/api/review/cancel'));await p.locator('.query-review').last().getByRole('button',{name:'取消',exact:true}).click();await wait;
  await p.waitForFunction(()=>document.querySelector('.review-feedback')?.textContent.includes('已取消'));check('cancel-disabled',await p.locator('.review-confirm').last().isDisabled());
  await p.setViewportSize({width:1536,height:900});await p.locator('#new').click();await p.locator('#history').click();
  await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));check('history-readonly',(await p.locator('.review-confirm:enabled').count())===0);
  await p.screenshot({path:out+'/history-mixed.png'});check('no-page-errors',errors.length===0);
 }catch(e){checks.push({name:'runner',passed:false,error:String(e)});save();process.exitCode=1;}
 finally{await ctx.close();await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(x=>x.passed).length,checks:checks.length,requests:records.length}));
})();
