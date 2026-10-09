// 真实智能体回执的页面诊断；不新增模型调用，也不把呈现通过当成业务通过。
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const [url,input,out]=process.argv.slice(2),run=JSON.parse(fs.readFileSync(input,'utf8'));
if(new URL(url).hostname!=='127.0.0.1'||run.state!=='complete'||run.rows.length!==48)throw Error('需要本机服务及完整48步真实智能体结果');
fs.mkdirSync(out,{recursive:false});let browser;
(async()=>{
 browser=await chromium.launch({headless:true});const ctx=await browser.newContext({viewport:{width:1440,height:980}}),page=await ctx.newPage(),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await ctx.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1')return route.abort();if(u.pathname==='/api/new')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'delivery-ui-diagnostic-only',model:'gpt-6-sol'})});if(['/api/ask','/api/stop','/api/shutdown'].includes(u.pathname))return route.abort();return route.continue();});
 const check=(name,ok)=>{checks.push({name,passed:!!ok});assert.ok(ok,name);};
 try{
  await page.goto(url);await page.locator('#send').waitFor({state:'visible'});
  for(const id of ['MB34','MB39','MB43','MB47','MB48']){
   const row=run.rows.find(r=>r.id===id);
   await page.evaluate(events=>{document.querySelector('#conversation').replaceChildren();for(const e of events)render(e);},row.events);
   const text=await page.locator('#conversation>.assistant:not(.commentary)').last().innerText();
   check(id+'显示实际交付文本',text===row.delivered_answer);
   check(id+'技术细节默认折叠',await page.locator('.technical').evaluateAll(xs=>xs.every(x=>!x.open)));
   for(const summary of await page.locator('.tool .result-details>summary').all())await summary.click();
   if(id==='MB39'){
    const detail=await page.locator('.tool .result-details').last().innerText();
    check('两条同来源记录名称均可见',detail.includes('测量点名称5970')&&detail.includes('测量点名称5971'));
    check('来源行号在依据可见',detail.includes('第 5971 行')&&detail.includes('第 5972 行'));
   }
   if(id==='MB47'){
    const draft=row.events.find(e=>e.kind==='message'&&e.phase!=='commentary'&&e.model_draft)?.model_draft||'';
    check('真实诊断证明健康边界说明被交付层替换',draft.includes('不能')&&draft.includes('健康')&&!text.includes('健康'));
   }
   await page.locator('#conversation').evaluate(e=>e.scrollTop=e.scrollHeight);await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
   await page.setViewportSize({width:900,height:900});check(id+'窄屏无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1440,height:980});
  }
  check('浏览器无脚本异常',errors.length===0);
 }finally{
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({method:'真实保存事件在实际智能体页面呈现；禁止提问、外网和修改服务；包含缺陷证明，呈现诊断通过不代表业务目标完成',input,checks,errors},null,2));await browser.close();
 }
 console.log(JSON.stringify({passed:checks.filter(x=>x.passed).length,total:checks.length,errors}));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
