const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const base=process.env.ICCM_TEST_URL||'http://127.0.0.1:8768',out=process.env.ICCM_TEST_OUTPUT||'docs/.staging/team-refactor-20260923/browser-local';
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),results=[],errors=[];
 try{
  const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();p.on('pageerror',e=>errors.push(String(e)));
  await p.goto(base);
  if(await p.locator('#username').count()){
   const c=Object.fromEntries(fs.readFileSync('.local/cloud-8899-access.txt','utf8').replace(/^\uFEFF/,'').split(/\r?\n/).filter(x=>x.includes(':')).map(x=>{let i=x.indexOf(':');return [x.slice(0,i).trim(),x.slice(i+1).trim()]}));
   await p.locator('#username').fill(c.Username);await p.locator('#password').fill(c.Password);await p.locator('#submit').click();await p.waitForURL(base+'/');
  }
  await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  const coords=()=>p.evaluate(()=>Object.fromEntries([...document.querySelectorAll('#new,#history,.source-item,#modelState')].filter(e=>e.offsetHeight).map((e,i)=>{const r=e.getBoundingClientRect();return [e.id||'data-'+i,[r.x,r.y,r.width,r.height]]})));
  const before=await coords();
  async function ask(question,check){await p.locator('#question').fill(question);const waiting=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');await p.locator('#send').click();const response=await waiting,r=await response.json();await p.waitForFunction(()=>!document.querySelector('#send').disabled);assert.ok(check(r),JSON.stringify({question,answer:r.answer,error:r.error}));results.push({question,passed:true,timings:r.timings_ms});return r;}
  await ask('测量点名称11 的高2阈值是多少?',r=>r.requested_thresholds?.[0]==='actual_high2'&&r.answer.includes('80'));
  assert.ok((await p.locator('#conversation').innerText()).includes('真实值报警阈值-高2'));
  await p.locator('#new').click();await ask('设备类描述1860 对应哪个设备类?',r=>r.entity?.tree==='equipment_class'&&r.entity?.code==='MOHB');
  await p.locator('#history').click();await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));
  await p.locator('.history-session').filter({hasText:'测量点名称11'}).click();await p.waitForFunction(()=>document.querySelector('#context').textContent.includes('XJ2ABC001MO.TMP.2ABC109MT.BBe'));
  await ask('那高3呢？',r=>r.requested_thresholds?.[0]==='actual_high3'&&r.answer.includes('90'));
  assert.deepEqual(await coords(),before);results.push({check:'resume-old-session-and-scope',passed:true});
  await p.reload();await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  await p.locator('#history').click();await p.locator('.history-session').filter({hasText:'测量点名称11'}).click();await p.waitForFunction(()=>!document.querySelector('#composer').hidden&&document.querySelector('#context').textContent.includes('XJ2ABC001MO.TMP.2ABC109MT.BBe'));
  await ask('低2呢？',r=>r.requested_thresholds?.[0]==='actual_low2'&&r.answer.includes('20'));
  results.push({check:'refresh-and-resume',passed:true});
  await p.screenshot({path:out+'/resumed-threshold.png'});
  await p.locator('#new').click();await ask('哪些测点的测量值大于60摄氏度？',r=>r.status==='ok'&&r.query.filters.some(f=>f.operator==='gt'&&f.value==='60'));
  assert.ok(!(await p.locator('#context').innerText()).includes('undefined'));await p.screenshot({path:out+'/numeric-query.png'});
  for(const [width,height] of [[1536,900],[1440,720],[1440,480],[560,780]]){
   await p.setViewportSize({width,height});const stable=await coords();if(stable.modelState)assert.ok(stable.modelState[1]+stable.modelState[3]<=height+1,'footer fits short viewport');
   for(let round=0;round<3;round++){
    await p.locator('#new').click();assert.deepEqual(await coords(),stable);
    await p.locator('#history').click();await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));assert.deepEqual(await coords(),stable);
    await p.locator('.history-session').filter({hasText:'设备类描述1860'}).click();await p.waitForFunction(()=>document.querySelector('#context').textContent.includes('MOHB'));assert.deepEqual(await coords(),stable);
    results.push({check:'stable-navigation',width,height,round,passed:true});
   }
  }
  assert.deepEqual(errors,[]);await ctx.close();
 }catch(e){results.push({passed:false,error:String(e)});console.error(e);process.exitCode=1;}
 finally{fs.writeFileSync(out+'/results.json',JSON.stringify({results,errors},null,2));await browser.close();}
 console.log(JSON.stringify({checks:results.length,failed:results.filter(x=>!x.passed).length}));
})();
