const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const out=process.env.POPULATION_BROWSER_OUTPUT||'docs/.staging/relationship-population-20260924/browser-first';
if(fs.existsSync(out+'/results.json'))throw Error('Preserve previous evidence');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const ctx=await browser.newContext({viewport:{width:1536,height:1000},reducedMotion:'reduce'}),p=await ctx.newPage();
 const checks=[],records=[],errors=[];p.setDefaultTimeout(20000);p.on('pageerror',e=>errors.push(String(e)));
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({method:'Fixed model boundary; real browser editing, HTTP confirmation and imported data, not model accuracy.',checks,records,errors},null,2));
 const clean=r=>{const x=JSON.parse(JSON.stringify(r));delete x.continuation;return x;};
 const check=(name,ok)=>{checks.push({name,passed:!!ok});save();assert.ok(ok,name);};
 for(const route of ['query','confirm'])await p.route('**/api/'+route,r=>r.continue({postData:JSON.stringify({...r.request().postDataJSON(),trace:true})}));
 try{
  await p.goto('http://127.0.0.1:8771');await p.waitForFunction(()=>document.querySelector('#modelState')&&!document.querySelector('#modelState').textContent.includes('正在检查'));
  for(const [i,target] of ['config','parts'].entries()){
   await p.locator('#question').fill('构型MOHB01的全部下级部件');
   const response=p.waitForResponse(r=>r.url().endsWith('/api/query'));await p.locator('#send').click();
   const preview=await (await response).json();records.push({phase:'preview',response:clean(preview)});save();
   await p.waitForFunction(()=>!document.querySelector('#send').disabled);
   const card=p.locator('.query-review').last();
   check('preview zero execution '+i,preview.status==='review'&&preview.timings_ms.execution===0&&preview.records.length===0);
   check('inline relationship editor '+i,await card.isVisible()&&await p.locator('dialog[open]').count()===0);
   check('population choices restricted '+i,(await card.getByLabel('任务1查询对象').locator('option').allTextContents()).join('|')==='所有下级对象（不限类型）|仅下级部件');
   check('no accidental root-result filters '+i,await card.locator('.review-filters').count()===0);
   await card.getByLabel('任务1查询对象').selectOption(target);
   await card.getByLabel('任务1对象标识').fill(i?'RRGA31':'MOHB01');await card.getByLabel('任务1范围').selectOption(i?'direct':'all');
   if(!i){await p.screenshot({path:out+'/desktop.png',fullPage:true});await p.setViewportSize({width:900,height:900});check('small viewport no overflow',await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await p.screenshot({path:out+'/small.png',fullPage:true});}
   const confirmed=p.waitForResponse(r=>r.url().endsWith('/api/confirm'));await card.locator('.review-confirm').click();
   const reply=await confirmed,r=await reply.json();const pages=[];
   for(let page=1;page<Math.ceil((r.total||0)/20);page++){
    const result=await p.evaluate(async payload=>{const meta=await (await fetch('/api/meta')).json();const response=await fetch('/api/page',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Token':meta.token},body:JSON.stringify({...payload,version:meta.version})});return {http:response.status,response:await response.json()};},{session:reply.request().postDataJSON().session,result:r.result,page,version:preview.version});pages.push(result);
   }
   records.push({phase:'confirmed',submitted:reply.request().postDataJSON(),response:clean(r),pages});save();
   check('edited root and depth executed '+i,r.status==='ok'&&r.entity?.code===(i?'RRGA31':'MOHB01')&&r.scope===(i?'direct':'all'));
   const task=r.context?.business_request?.tasks?.[0];
   check('population persisted '+i,task?.operation==='descendants'&&task.population===(i?'parts':'all_objects'));
   check('no new model after confirmation '+i,r.trace?.user_confirmed&&!r.trace?.response_model&&!r.trace?.checklist_review);
   check('all object count includes nonparts '+i,i||r.total===222);
   check('all pages obtained '+i,pages.every(x=>x.http===200)&&r.records.length+pages.reduce((n,x)=>n+x.response.records.length,0)===r.total);
   await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  }
  check('no browser errors',errors.length===0);
 }finally{save();await browser.close();}
 console.log(JSON.stringify({checks:checks.length,passed:checks.filter(x=>x.passed).length,errors}));
})().catch(e=>{console.error(e);process.exitCode=1;});
