const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
const base=process.env.ICCM_TEST_URL||'http://127.0.0.1:8769';
const out=process.env.BLIND_BROWSER_OUTPUT||'docs/.staging/semantic-holdout-20260924/browser-final';
if(fs.existsSync(out+'/results.json'))throw Error('Existing evidence must be preserved');
fs.mkdirSync(out,{recursive:true});
const frozen=JSON.parse(fs.readFileSync('docs/.staging/semantic-holdout-20260924/frozen.json','utf8'));
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();
 if(process.env.REQUEST_TRACE==='1')await p.route('**/api/query',route=>{
  const req=route.request();
  if(req.method()!=='POST')return route.continue();
  return route.continue({postData:JSON.stringify({...req.postDataJSON(),trace:true})});
 });
 const results=[],checks=[],errors=[],sessions=new Set();
 p.setDefaultTimeout(120000);p.on('pageerror',e=>errors.push(String(e)));
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({results,checks,errors},null,2));
 try{
  await p.goto(base);
  if(await p.locator('#username').count()){
   const creds=Object.fromEntries(fs.readFileSync('.local/cloud-8899-access.txt','utf8').replace(/^\uFEFF/,'').split(/\r?\n/).filter(x=>x.includes(':')).map(x=>{const i=x.indexOf(':');return [x.slice(0,i).trim(),x.slice(i+1).trim()]}));
   await p.locator('#username').fill(creds.Username);await p.locator('#password').fill(creds.Password);await p.locator('#submit').click();await p.waitForURL(base+'/');
  }
  await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  async function ask(c){
   await p.locator('#question').fill(c.question);const waiting=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');
   await p.locator('#send').click();const response=await waiting,r=await response.json();const session=response.request().postDataJSON().session;sessions.add(session);
   await p.waitForFunction(()=>!document.querySelector('#send').disabled);
   const entry={...c,response:r,session,rendered:await p.locator('#conversation').innerText()};results.push(entry);save();console.log(c.id,r.status,r.error||'');return entry;
  }
  for(const id of ['A01','A02','A03'])await ask(frozen.suites.A.find(x=>x.id===id));
  await p.screenshot({path:out+'/range.png'});
  await p.locator('#new').click();
  let last;for(const id of ['A11','A12','A13'])last=await ask(frozen.suites.A.find(x=>x.id===id));
  const code=last.expect.code;
  checks.push({name:'replace-subject-keeps-properties',passed:last.response.entity?.code===code&&last.response.attributes?.some(x=>x.property==='prediction')&&last.response.attributes?.some(x=>x.property==='actual_high3')});
  await p.screenshot({path:out+'/subject.png'});
  await p.locator('#new').click();await p.locator('#history').click();await p.locator('.history-session[data-session="'+last.session+'"]').click();
  await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));
  checks.push({name:'history-main-pane',passed:!(await p.locator('dialog[open]').count())&&(await p.locator('#conversation').innerText()).includes('对象换成测量点名称19')});
  await p.reload();await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  await p.locator('#history').click();await p.locator('.history-session[data-session="'+last.session+'"]').click();
  await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));
  const next=await ask({id:'H01',question:'再换回测量点名称7，仍保留刚才两项。'});
  checks.push({name:'refresh-retains-projection',passed:next.response.entity?.code===frozen.suites.A.find(x=>x.id==='A11').expect.code&&['prediction','actual_high3'].every(k=>next.response.attributes?.some(x=>x.property===k))});
  if(process.env.REQUEST_STATE_REQUIRED==='1'){
   checks.push({name:'all-queries-commit-business-request',passed:results.every(x=>x.response.context?.business_request?.version===1)});
   const before=last.response.context?.business_request,after=next.response.context?.business_request;
   checks.push({name:'signed-history-preserves-task-and-projection-sources',passed:!!before&&!!after&&after.revision===before.revision+1&&after.tasks[0].id===before.tasks[0].id&&JSON.stringify(after.tasks[0].sources.properties)===JSON.stringify(before.tasks[0].sources.properties)});
  }
  await p.screenshot({path:out+'/history-resume.png'});
  checks.push({name:'no-page-errors',passed:errors.length===0});save();
 }catch(e){checks.push({name:'runner',passed:false,error:String(e)});save();process.exitCode=1;}
 finally{
  try{await p.evaluate(async ids=>{const meta=await fetch('/api/meta').then(r=>r.json());for(const session of ids)await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Token':meta.token},body:JSON.stringify({session})});},[...sessions]);}catch{}
  await ctx.close();await browser.close();
 }
 console.log(JSON.stringify({queries:results.length,passed:checks.filter(x=>x.passed).length,checks:checks.length}));
})();
