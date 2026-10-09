// 使用真实回放结果核验实际页面、分页及独立任务，不新增模型调用。
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const [url,input,out]=process.argv.slice(2);
if(!url||!input||!out||new URL(url).hostname!=='127.0.0.1')throw Error('仅允许本机服务和完整真实回放文件');
const run=JSON.parse(fs.readFileSync(input,'utf8'));
if(run.state!=='complete'||run.rows.length!==48)throw Error('需要完整48步结果');
fs.mkdirSync(out,{recursive:false});
let browser;
(async()=>{
 browser=await chromium.launch({headless:true});
 const ctx=await browser.newContext({viewport:{width:1440,height:980},reducedMotion:'reduce'}),page=await ctx.newPage();
 const errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 let active;
 await ctx.route('**/*',route=>{
  const u=new URL(route.request().url());if(u.hostname!=='127.0.0.1')return route.abort();
  if(['/api/query','/api/confirm'].includes(u.pathname))return route.abort();
  if(u.pathname==='/api/page'){
   const n=route.request().postDataJSON().page,p=active.pages[n];if(!p)throw Error('没有真实分页回执');
   return route.fulfill({status:p.http,contentType:'application/json',body:JSON.stringify(p)});
  }
  return route.continue();
 });
 const check=(name,value)=>{checks.push({name,passed:!!value});assert.ok(value,name);};
 try{
  await page.goto(url);await page.waitForFunction(()=>document.querySelector('#modelState')&&!document.querySelector('#modelState').textContent.includes('正在检查'));
  for(const id of ['MB43','MB23','MB39','MB41','MB42','MB34']){
   active=run.rows.find(r=>r.id===id);assert.equal(active.http,200,id+'实际响应成功');
   await page.evaluate(r=>{document.querySelector('#welcome').hidden=true;document.querySelector('#conversation').replaceChildren();render(r,'真实回执呈现核验');},active.response);
   let text=await page.locator('#conversation').innerText();
   check(id+'技术条件默认折叠',await page.locator('.query-basis details').evaluateAll(xs=>xs.every(x=>!x.open)));
   check(id+'业务范围中文',!(await page.locator('.business-scope').allTextContents()).some(t=>/collection|equipment_class|part_class|direct|all|self|points|parts/.test(t)));
   if(id==='MB43'){
    check('部分分类状态明确',text.includes('关联数据不完整')&&text.includes('222')&&text.includes('219')&&text.includes('3'));
    const card=page.locator('article.answer').last();
    while(await card.getByRole('button',{name:'下一页',exact:true}).isEnabled())await card.getByRole('button',{name:'下一页',exact:true}).click();
    text=await card.innerText();check('分页显示全部三条缺失对象',['#42-1','#42-2','#42-3'].every(c=>text.includes(c)));
   }
   if(id==='MB23')check('跨表明细与报警字段交付',text.includes('最近现场部件')&&text.includes('报警状态')&&text.includes('源系统')&&await page.locator('table tr').count()===12);
   if(id==='MB39')check('同码同来源原行分别保留',['5971','5972','测量点名称5970','测量点名称5971'].every(c=>text.includes(c)));
   if(id==='MB41'||id==='MB42'){
    check(id+'两个任务卡片',await page.locator('article.answer').count()===2);
    check(id+'独立根保持',text.includes('XJ1ABC002PO&POZB01')&&text.includes('MOHB02'));
   }
   if(id==='MB34')check('关联缺失保留原对象',text.includes('XJ4ABC001MO&MOHB01#42-1')&&text.includes('没有精确关联记录'));
   await page.screenshot({path:path.join(out,id+'-desktop.png'),fullPage:true});
   await page.setViewportSize({width:900,height:900});
   check(id+'窄屏无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(out,id+'-small.png'),fullPage:true});await page.setViewportSize({width:1440,height:980});
  }
  check('浏览器无脚本异常',errors.length===0);
 }finally{
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({method:'真实HTTP回执在实际本机页面呈现；分页使用同次真实HTTP数据；未新增模型调用',input,checks,errors},null,2));await browser.close();
 }
 console.log(JSON.stringify({passed:checks.filter(x=>x.passed).length,total:checks.length,errors}));
})().catch(e=>{console.error(e.message);process.exitCode=1;});
