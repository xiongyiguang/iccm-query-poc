// 合成历史用于测试布局边界，真实引导查询用于测试状态留存。
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const output='docs/.staging/team-test-20260923/sidebar-space-matrix.json';
if(fs.existsSync(output))throw Error('Preserve existing result; choose another output path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),results=[],errors=[];
 const save=()=>fs.writeFileSync(output,JSON.stringify({results,errors},null,2));
 try{
 for(let round=1;round<=3;round++){
  const ctx=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'}),page=await ctx.newPage();
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto('http://127.0.0.1:8766');await page.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  for(let i=0;i<3;i++){await page.locator('#new').click();await page.locator('#startDevice').click();await page.waitForFunction(()=>document.querySelector('#conversation .answer')&&!document.querySelector('#send').disabled)}
  await page.reload();await page.locator('#history').click();assert.equal(await page.locator('#historySessions button').count(),3);
  const sample=await page.evaluate(()=>JSON.parse(sessionStorage.getItem('iccm-tab-history-v1'))[0]);
  results.push({round,test:'real-three-sessions-refresh',passed:true});
  let index=0;
  for(const count of [0,1,100]){
   await page.evaluate(({count,sample})=>sessionStorage.setItem('iccm-tab-history-v1',JSON.stringify(Array.from({length:count},(_,i)=>({...sample,session:'synthetic-'+i,question:'合成布局用例 '+i+'：'+('很长的历史对话标题'.repeat(12))})))),{count,sample});
   await page.reload();await page.locator('#history').click();
   for(const [width,height] of [[1440,1100],[1440,1001],[1440,1000],[1440,900],[1440,720],[1440,600],[1440,480],[1001,720],[1000,720],[560,780],[560,480]]){
    index++;await page.setViewportSize({width,height});
    const row={round,index,count,width,height,passed:true,failures:[]};
    const check=(ok,message)=>{if(!ok){row.passed=false;row.failures.push(message)}};
    const measure=()=>page.evaluate(()=>{
     const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom}};
     const rail=document.querySelector('.rail'),hist=document.querySelector('#historySessions'),data=[...document.querySelectorAll('.source-item')],note=document.querySelector('.rail-note'),model=document.querySelector('#modelState');
     return {nav:rect(document.querySelector('#new')),rail:rect(rail),history:rect(hist),dataHeight:data.reduce((a,e)=>a+e.offsetHeight,0),noteVisible:getComputedStyle(note).display!=='none',model:rect(model),modelVisible:model.offsetHeight>0,outerY:scrollY,outerWidth:document.documentElement.scrollWidth,railOverflow:rail.scrollHeight-rail.clientHeight,historyCount:hist.children.length};
    });
    row.before=await measure();const m=row.before;
    check(m.historyCount===count,'历史数量不符');check(m.outerY===0,'整页发生滚动');check(m.outerWidth<=width,'整页横向溢出');
    check(m.history.height>=70,'历史区域低于最小高度');
    check(m.noteVisible===(width>1000&&height>1000),'说明文字响应断点错误');
    if(width>1000){check(m.dataHeight<=120,'统计区域过大');if(height>=720)check(m.history.height>m.dataHeight,'历史未优先获得空间');check(m.model.bottom<=height+1,'底部模型状态被挤出视口')}
    check(m.railOverflow<=1,'侧栏出现外层滚动');
    if(count){await page.locator('#historySessions button').last().click();check((await page.locator('#historyConversation .user').innerText()).includes('合成布局用例 '+(count-1)),'选择记录内容错误')}
    for(let cycle=0;cycle<3;cycle++){
     await page.locator('#backToCurrent').click();await page.locator('#history').click();
     const after=await measure();check(Math.abs(after.nav.y-m.nav.y)<1&&Math.abs(after.nav.x-m.nav.x)<1,'切换导致导航移动');
    }
    row.after=await measure();
    if(!row.passed)await page.screenshot({path:`docs/.staging/team-test-20260923/sidebar-space-failure-${round}-${index}.png`});
    results.push(row);save();
   }
  }
  // 独立列表滚动不能带动右侧面板或整个页面滚动。
  await page.setViewportSize({width:1440,height:900});await page.locator('#history').click();
  const mainBefore=await page.locator('#workspace').evaluate(e=>e.scrollTop);
  await page.locator('#historySessions').hover();await page.mouse.wheel(0,2000);
  await page.waitForFunction(()=>document.querySelector('#historySessions').scrollTop>0);
  assert.equal(await page.locator('#workspace').evaluate(e=>e.scrollTop),mainBefore);assert.equal(await page.evaluate(()=>scrollY),0);
  results.push({round,test:'independent-list-scroll',passed:true});
  await page.locator('#new').click();assert.equal(await page.locator('#welcome').isVisible(),true);
  await page.locator('#history').click();assert.equal(await page.locator('#historySessions button').count(),100);
  results.push({round,test:'new-conversation-preserves-100-history',passed:true});
  await ctx.close();save();console.log('round '+round+' complete');
 }
 }catch(e){results.push({passed:false,error:String(e)});console.error(e)}
 finally{save();await browser.close()}
 const failures=results.filter(x=>!x.passed);console.log(JSON.stringify({checks:results.length,failed:failures.length,pageErrors:errors.length,failures:failures.map(x=>({round:x.round,count:x.count,width:x.width,height:x.height,failures:x.failures,error:x.error}))}));
 if(failures.length||errors.length)process.exitCode=1;
})();
