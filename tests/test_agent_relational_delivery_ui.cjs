// 保存的真实智能体事件在实际服务/页面验收；禁止额外提问和外网。
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const [url,input,out]=process.argv.slice(2),run=JSON.parse(fs.readFileSync(input,'utf8'));
if(new URL(url).hostname!=='127.0.0.1'||run.state!=='complete'||run.rows.length!==48)throw Error('需要完整48步真实结果及本机缓存服务');
fs.mkdirSync(out,{recursive:false});
(async()=>{
 const browser=await chromium.launch({headless:true}),ctx=await browser.newContext({viewport:{width:1440,height:980}}),page=await ctx.newPage(),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await ctx.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1'||['/api/ask','/api/stop','/api/shutdown'].includes(u.pathname))return route.abort();return route.continue();});
 const check=(name,ok)=>{checks.push({name,passed:!!ok});assert.ok(ok,name);};
 try{
  await page.goto(url);await page.locator('#send').waitFor({state:'visible'});await page.waitForFunction(()=>state.current);
  for(const id of ['MB34','MB35','MB36','MB39','MB43','MB40','MB41','MB42','MB47','MB48']){
   const row=run.rows.find(r=>r.id===id);
   await page.evaluate(row=>{state.current.id=row.session;document.querySelector('#conversation').replaceChildren();for(const e of row.events)render(e);},row);
   const text=await page.locator('#conversation>.assistant:not(.commentary)').last().innerText();
   check(id+'最终答案实际交付一致',text===row.delivered_answer);
   check(id+'技术详情默认折叠',await page.locator('.technical').evaluateAll(xs=>xs.every(x=>!x.open)));
   const final=row.events.filter(e=>e.kind==='message'&&e.phase!=='commentary').at(-1),ids=final.delivery_result_ids;
   const toolEvents=row.events.filter(e=>e.kind==='tool_result'&&ids.includes(e.result?.result_id));
   const tool=page.locator('[data-id="'+toolEvents.at(-1).id+'"]');
   await tool.locator('.result-details>summary').click();
   if(id==='MB39'){
    const detail=await tool.innerText();check('同来源重复原行均可见',detail.includes('测量点名称5970')&&detail.includes('测量点名称5971'));
    check('原CSV行号在输出可见',detail.includes('5971')&&detail.includes('5972'));
   }
   if(id==='MB43'){
    check('部分分类未标为全部完成',(await tool.locator('.tool-status').innerText()).includes('部分结果'));
    check('初页上一页不可用',await tool.getByRole('button',{name:'上一页',exact:true}).isDisabled());
    await tool.getByRole('button',{name:'下一页',exact:true}).click();
    await tool.locator('.result-details>summary').filter({hasText:'第 2 页'}).waitFor();
    const detail=await tool.innerText();check('翻页后三个未关联部件均可见',['MOHB01#42-1','MOHB01#42-2','MOHB01#42-3'].every(x=>detail.includes(x)));
    await page.screenshot({path:path.join(out,'MB43-page2.png'),fullPage:true});
    check('翻页后保留可折叠明细标题',await tool.locator('.result-details>summary').count()===1);
    await tool.getByRole('button',{name:'上一页',exact:true}).click();await tool.locator('.result-details>summary').filter({hasText:'第 1 页'}).waitFor();
    check('返回首页保留完整总数',(await tool.innerText()).includes('明细共 30 条'));
   }
   if(['MB40','MB41','MB42'].includes(id)){
    check(id+'独立任务均有交付明细',await tool.locator('.result-details>.query-task').count()===2);
    if(id==='MB42'){
     const tasks=tool.locator('.result-details>.query-task');const before=await tasks.first().innerText();
     if(await tasks.nth(1).getByRole('button',{name:'下一页',exact:true}).count()){
      await tasks.nth(1).getByRole('button',{name:'下一页',exact:true}).click();await tasks.nth(1).locator('.detail-hint').filter({hasText:'第 2 页'}).waitFor();
      check('翻第二任务不改变第一任务',await tasks.first().innerText()===before);
     }
    }
   }
   if(id==='MB47')check('零报警的健康边界留在最终答案',text.includes('健康')&&text.includes('不能'));
   if(id==='MB48')check('历史时长缺失不显示零小时',text.includes('开始时间')&&text.includes('恢复时间')&&text.includes('无法计算'));
   await page.locator('#conversation').evaluate(e=>e.scrollTop=e.scrollHeight);await page.screenshot({path:path.join(out,id+'.png'),fullPage:true});
   await page.setViewportSize({width:900,height:900});check(id+'窄屏无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.setViewportSize({width:1440,height:980});
  }
  await page.evaluate(async()=>{
   const result=await api('/api/page',{session:'ui-fixture',result:'ui-batch',page:1});state.current.id='ui-fixture';document.querySelector('#conversation').replaceChildren();
   render({kind:'tool_start',id:'fixture',tool:'iccm_relational',arguments:{},presentation:{title:'页面组合夹具（非模型问答）',rows:[]}});
   render({kind:'tool_result',id:'fixture',tool:'iccm_relational',seconds:0,result});
  });
  const fixture=page.locator('[data-id="fixture"]');await fixture.locator('.result-details>summary').click();
  const sections=fixture.locator('.result-details>.query-task'),firstText=await sections.first().innerText();
  await sections.nth(1).getByRole('button',{name:'下一页',exact:true}).click();await sections.nth(1).locator('.detail-hint').filter({hasText:'第 2 页'}).waitFor();
  check('组合夹具：第二项翻页不改变第一项',await sections.first().innerText()===firstText);
  check('组合夹具：分页保留任务标题',(await sections.nth(1).locator(':scope>h4').first().innerText()).includes('第二项'));
  await sections.nth(1).getByRole('button',{name:'上一页',exact:true}).click();await sections.nth(1).locator('.detail-hint').filter({hasText:'第 1 页'}).waitFor();
  check('组合夹具：连续返回首页仍保留第一项',await sections.first().innerText()===firstText);
  await page.screenshot({path:path.join(out,'independent-paging-fixture.png'),fullPage:true});
  const security=await page.evaluate(async()=>{
   const post=(body,headers={})=>fetch('/api/page',{method:'POST',headers:{'Content-Type':'application/json','X-Local-Token':state.token,...headers},body:JSON.stringify(body)}).then(r=>r.status);
   return {token:await post({session:'unknown',result:'unknown',page:1},{'X-Local-Token':'invalid'}),session:await post({session:'unknown',result:'unknown',page:1}),page:await post({session:state.current.id,result:'unknown',page:0})};
  });
  check('无本机会话令牌拒绝分页',security.token===403);check('无效会话拒绝分页',security.session===400);check('无效结果拒绝分页',security.page===400);
  check('浏览器无脚本异常',errors.length===0);
 }finally{fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({method:'真实保存的48步回执；另组合MB34/MB43原回执为长表独立分页夹具，夹具不是新增模型问答或业务评分；实际页面及缓存分页API；禁止模型调用及外网',input,checks,errors},null,2));await browser.close();}
 console.log(JSON.stringify({passed:checks.filter(x=>x.passed).length,total:checks.length,errors}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
