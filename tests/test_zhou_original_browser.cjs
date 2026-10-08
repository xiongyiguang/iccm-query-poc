// 真实 Edge 回放两份原件转录的问句清单。
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');
const dir=process.env.ZHOU_CASE_DIR||'docs/.staging/zhou-two-rounds-retest-20260923',out=process.env.ZHOU_BROWSER_OUTPUT||dir+'/browser-v2';
fs.mkdirSync(out,{recursive:true});
const cases=JSON.parse(fs.readFileSync(dir+'/cases.json','utf8')),base=process.env.ICCM_TEST_URL||'http://106.53.130.181:8899';
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),results=[],checks=[],errors=[],sessions=new Set();
 const ctx=await browser.newContext({viewport:{width:1536,height:900},reducedMotion:'reduce'}),p=await ctx.newPage();p.setDefaultTimeout(180000);p.on('pageerror',e=>errors.push(String(e)));
 const settle=()=>p.evaluate(async()=>{await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);await Promise.all(document.getAnimations().map(a=>a.finished.catch(()=>{})));});
 const save=()=>fs.writeFileSync(out+'/results.json',JSON.stringify({results,checks,errors},null,2));
 try{
  await p.goto(base);
  if(await p.locator('#username').count()){
  const creds=Object.fromEntries(fs.readFileSync('.local/cloud-8899-access.txt','utf8').replace(/^\uFEFF/,'').split(/\r?\n/).filter(x=>x.includes(':')).map(x=>{const i=x.indexOf(':');return [x.slice(0,i).trim(),x.slice(i+1).trim()]}));
  await p.locator('#username').fill(creds.Username);await p.locator('#password').fill(creds.Password);await p.locator('#submit').click();await p.waitForURL(base+'/');}
  await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  async function ask(c){
   await p.locator('#question').fill(c.question);const start=Date.now(),waiting=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');
   await p.locator('#send').click();const response=await waiting,r=await response.json(),request=response.request().postDataJSON();sessions.add(request.session);
   await p.waitForFunction(()=>!document.querySelector('#send').disabled);
   const entry={...c,seconds:(Date.now()-start)/1000,response:r,http_status:response.status(),session:request.session,
    contextText:await p.locator('#context').innerText(),renderedText:await p.locator('#conversation').innerText()};
   results.push(entry);await settle();await p.screenshot({path:out+'/'+c.id+'.png'});save();console.log(JSON.stringify({id:c.id,seconds:entry.seconds,status:r.status,error:r.error}));return entry;
  }
  let group='';
  for(const c of cases){
   if(group!==c.group){await p.locator('#new').click();group=c.group;}
   if(c.selection){
    const candidate=p.locator('#conversation article').last().locator('button').filter({hasText:c.selection.code}).first();
    if(await candidate.count())await candidate.click();else checks.push({id:c.id+'-candidate',passed:false,note:'候选按钮未出现'});
   }
   const entry=await ask(c);
   if(c.id==='A01c'){
    await p.locator('#new').click();await p.locator('#history').click();await p.locator('.history-session[data-session="'+entry.session+'"]').click();
    await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));await settle();
    const text=await p.locator('#conversation').innerText();
    checks.push({id:'A02-history',feedback:'一-2',passed:text.includes('介绍下XXXX1')&&text.includes('介绍下PBS的XXXX1')&&!(await p.locator('dialog[open]').count()),note:'左栏打开历史，主对话区域显示全部三轮，无临时窗口'});
    await p.screenshot({path:out+'/A02-history.png'});save();
   }
   if(c.id==='B03a'){
    await p.locator('#new').click();await ask({id:'B04-new-context',feedback:'二-4',question:'介绍下PBS的XXXX1',source:'历史切换干扰前置'});
    await p.locator('#history').click();await p.locator('.history-session[data-session="'+entry.session+'"]').click();
    await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));await settle();
    const continued=await ask({id:'B04-resume',feedback:'二-4',question:'看设备类那条',source:'恢复MOHB候选历史后的补充'});
    checks.push({id:'B04-resume',feedback:'二-4',passed:continued.response.entity?.tree==='equipment_class'&&continued.response.entity?.code==='MOHB'&&continued.session===entry.session});
    await p.reload();await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
    await p.locator('#history').click();await p.locator('.history-session[data-session="'+entry.session+'"]').click();
    await p.waitForFunction(()=>document.querySelector('#timing').textContent.includes('已恢复'));await settle();
    const refreshed=await ask({id:'B04-refresh',feedback:'二-4',question:'它的上级编码是什么？',source:'刷新并恢复后继续追问'});
    checks.push({id:'B04-refresh',feedback:'二-4',passed:refreshed.response.entity?.tree==='equipment_class'&&refreshed.response.entity?.code==='MOHB'&&refreshed.response.attributes?.some(x=>x.property==='parent'&&x.display_value==='MOH')});
   }
  }
  checks.push({id:'B07-no-undefined',feedback:'二-7',passed:results.filter(x=>x.id.startsWith('B07')).every(x=>!x.contextText.includes('undefined'))});
  checks.push({id:'A03-decimal-render',feedback:'一-3',passed:results.find(x=>x.id==='A03').renderedText.includes('-0.000000000405')});
  checks.push({id:'logout-visible',passed:base.includes('127.0.0.1')||await p.getByRole('button',{name:'退出登录',exact:true}).isVisible(),not_applicable:base.includes('127.0.0.1')});
  checks.push({id:'browser-errors',passed:errors.length===0});save();
 }catch(e){checks.push({id:'runner',passed:false,error:String(e)});save();console.error(String(e));process.exitCode=1;}
 finally{
  // 只移除本隔离浏览器测试创建的服务端会话。
  try{await p.evaluate(async ids=>{const meta=await fetch('/api/meta').then(r=>r.json());for(const session of ids)await fetch('/api/reset',{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Token':meta.token},body:JSON.stringify({session})});},[...sessions]);}catch{}
  await ctx.close();await browser.close();
 }
 console.log(JSON.stringify({queries:results.length,uiChecks:checks.length,failedUI:checks.filter(x=>!x.passed).length}));
})();
