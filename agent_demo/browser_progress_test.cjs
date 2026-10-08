// 实际浏览器界面时延和 Codex 查询测试，不模拟响应。
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');let browser,page;
(async()=>{
 const out=path.resolve(__dirname,'../docs/.staging/codex-agent-progress-20260925');
 browser=await chromium.launch({channel:'msedge',headless:true});page=await browser.newPage({viewport:{width:1440,height:960}});
 const errors=[],runs=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8771/');await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 async function ask(label,question,expected){
  await page.locator('#question').fill(question);
  await page.evaluate(()=>{
   window.progressTiming={};const previous=document.querySelectorAll('.query-process').length;
   document.querySelector('#send').addEventListener('click',()=>{
    const start=performance.now();
    const observer=new MutationObserver(()=>{
     const cards=document.querySelectorAll('.query-process');if(cards.length<=previous)return;
     const card=cards[cards.length-1];
     if(card.querySelector('.process-step')&&!window.progressTiming.queued){
      window.progressTiming.queued=true;
      requestAnimationFrame(()=>requestAnimationFrame(()=>{window.progressTiming.firstProcessMs=performance.now()-start;}));
     }
     if(card.querySelector('.commentary')?.textContent.length>5&&!window.progressTiming.firstModelMs)window.progressTiming.firstModelMs=performance.now()-start;
    });observer.observe(document.querySelector('#conversation'),{childList:true,subtree:true,characterData:true});
    window.progressObserver=observer;
   },{once:true});
  });
  await page.locator('#send').click();
  await page.waitForFunction(()=>window.progressTiming.firstProcessMs!==undefined,{},{timeout:5000});
  if(label==='cross_tree')await page.screenshot({path:path.join(out,'first-process.png'),fullPage:true});
  await page.waitForFunction(()=>!document.querySelector('#send').disabled,{},{timeout:200000});
  const result=await page.evaluate(()=>{window.progressObserver.disconnect();const i=state.current.events.findLastIndex(e=>e.kind==='user');return {timing:window.progressTiming,events:state.current.events.slice(i)};});
  const correct=result.events.some(e=>e.kind==='tool_result'&&e.tool==='iccm_query'&&JSON.stringify(e.result.metrics?.map(m=>m.value))===JSON.stringify(expected));
  runs.push({label,question,...result,correct,withinFiveSeconds:result.timing.firstProcessMs<5000});
  console.log(JSON.stringify({label,timing:result.timing,correct}));
 }
 await ask('cross_tree','XJ3ABC002RR 下的设备类描述3727下的部件有多少类？',[90,23]);
 await ask('followup','把范围换成 XJ2ABC001MO，设备类不变，有多少部件、多少类？',[0,0]);
 const before=await page.locator('.aside-bottom').boundingBox();
 await page.locator('#new').click();await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 await ask('numeric','筛选测量值大于50且小于80摄氏度的测点，告诉我总数。',[205,205]);
 await page.screenshot({path:path.join(out,'completed-process.png'),fullPage:true});
 await page.locator('#sessions button').last().click();const after=await page.locator('.aside-bottom').boundingBox();
 const historyStable=Math.abs(before.y-after.y)<1&&await page.locator('.query-process').count()===2;
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'mobile-process.png'),fullPage:true});
 const noOverflow=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);
 const report={runs,historyStable,noOverflow,errors};fs.writeFileSync(path.join(out,'real-browser.json'),JSON.stringify(report,null,2));
 await browser.close();if(!historyStable||!noOverflow||errors.length||runs.some(r=>!r.withinFiveSeconds||!r.correct))process.exitCode=1;
})().catch(async e=>{console.error(e.stack);if(page)await page.screenshot({path:path.resolve(__dirname,'../docs/.staging/codex-agent-progress-20260925/failure.png')});if(browser)await browser.close();process.exitCode=1;});
