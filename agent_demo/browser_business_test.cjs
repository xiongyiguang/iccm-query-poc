// 实际浏览器界面时延和 Codex 查询测试，不模拟响应。
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');let browser,page,out;
(async()=>{
 out=path.resolve(__dirname,'../docs/.staging/codex-agent-business-ui-20260927/run-'+new Date().toISOString().replace(/[:.]/g,'-'));fs.mkdirSync(out,{recursive:true});console.log('Evidence: '+out);
 browser=await chromium.launch({channel:'msedge',headless:true});page=await browser.newPage({viewport:{width:1440,height:960}});
 const errors=[],runs=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
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
  const query=page.locator('.tool[data-tool="iccm_query"]').last();
  const text=await query.locator('.query-understanding').innerText();
  const visibleTech=await query.locator('.technical pre').isVisible();
  checks.push({label,receiptShown:text.includes('实际查询口径'),technicalCollapsed:!visibleTech,
    scopeCorrect:label==='cross_tree'?text.includes('XJ3ABC002RR')&&text.includes('设备类描述3727')&&text.includes('部件类编码'):label==='followup'?text.includes('XJ2ABC001MO')&&!text.includes('XJ3ABC002RR'):text.includes('>「50」')&&text.includes('<「80」')&&text.includes('℃')});
  await query.locator('.result-details>summary').click();
  const source=query.locator('.evidence-source').first();await source.locator('summary').click();
  checks.at(-1).evidenceReadable=await source.locator('table').isVisible();
  if(label==='numeric')checks.at(-1).numericColumns=(await query.locator('.result-details table').first().innerText()).includes('测量值');
  await query.scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,label+'-evidence.png'),fullPage:true});
  await query.locator('.result-details>summary').click();

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
 await page.setViewportSize({width:1440,height:960});await page.locator('.tool[data-tool="iccm_query"]').first().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'business-overview.png'),fullPage:true});
 // 新会话确实存在歧义时，不能静默选择旧对象。
 await page.setViewportSize({width:1440,height:960});await page.locator('#new').click();await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 await page.locator('#question').fill('它属于哪个设备类？');await page.locator('#send').click();await page.waitForFunction(()=>!document.querySelector('#send').disabled,{},{timeout:200000});
 const ambiguity=await page.evaluate(()=>({events:state.current.events,askedForClarification:state.current.events.some(e=>e.kind==='message'&&/哪个|提供|名称|编码|对象/.test(e.text)),inventedQuery:state.current.events.some(e=>e.kind==='tool_result'&&e.tool==='iccm_query'&&e.result.status==='ok')}));
 await page.screenshot({path:path.join(out,'ambiguity.png'),fullPage:true});
 // 以下单独检查合成界面状态，不属于模型效果评测。
 const uiStates=await page.evaluate(()=>{
  const c=document.getElementById('conversation');c.replaceChildren();
  render({kind:'process',id:'fixture',stage:'prepared',text:'页面状态样例，不是真实模型测试'});
  render({kind:'tool_start',id:'candidate',tool:'iccm_find',arguments:{identifier:'<img src=x onerror=alert(1)>',tree:'pbs'},presentation:{title:'定位对象',rows:[{label:'查找内容',text:'<img src=x onerror=alert(1)>'}]}});
  render({kind:'tool_result',id:'candidate',tool:'iccm_find',seconds:0,result:{match_type:'candidates_only',records:[{code:'A',name:'候选对象',tree:'pbs'}],answer:'候选对象'},presentation:{title:'定位对象',rows:[{label:'查找内容',text:'<img src=x onerror=alert(1)>'}]}});
  render({kind:'tool_start',id:'failed',tool:'iccm_query',arguments:{},presentation:{title:'查询数据',rows:[]}});render({kind:'tool_error',id:'failed',text:'参数校验失败，未执行查询'});
  render({kind:'tool_start',id:'batch',tool:'iccm_query',arguments:{},presentation:{title:'分别查询',rows:[],tasks:[]}});
  render({kind:'tool_result',id:'batch',tool:'iccm_query',seconds:0,result:{status:'batch',items:[{status:'ok',answer:'结果一'},{status:'ok',answer:'结果二'}]},presentation:{title:'分别查询',rows:[],tasks:[{question:'A',executed:true,rows:[{label:'对象',text:'A'}]},{question:'B',executed:true,rows:[{label:'对象',text:'B'}]}]}});
  render({kind:'tool_start',id:'attributes',tool:'iccm_query',arguments:{}});render({kind:'tool_result',id:'attributes',tool:'iccm_query',seconds:0,result:{status:'ok',attributes:[{label:'测量值',value:'0',status:'known'},{label:'单位',value:null,status:'missing'}]}});
  render({kind:'tool_start',id:'stopped',tool:'iccm_query',arguments:{},presentation:{title:'查询数据',rows:[]}});render({kind:'done',status:'interrupted',seconds:1});
  return {batchSuccess:findItem('batch').dataset.status==='completed'&&findItem('batch').querySelectorAll('h3').length===2,attributesReadable:findItem('attributes').querySelector('table').textContent.includes('未提供')&&findItem('attributes').querySelector('table').textContent.includes('0'),candidateNotSelected:findItem('candidate').querySelector('.tool-status').textContent.includes('未选定'),failureNotSuccess:findItem('failed').dataset.status==='error',stopNotRunning:findItem('stopped').querySelector('.tool-status').textContent==='已停止',htmlEscaped:c.querySelector('img')===null&&c.textContent.includes('<img'),technicalCollapsed:[...c.querySelectorAll('.technical')].every(n=>!n.open)};
 });
 const report={runs,checks,ambiguity,uiStates,historyStable,noOverflow,errors};fs.writeFileSync(path.join(out,'real-browser.json'),JSON.stringify(report,null,2));
 await browser.close();if(!historyStable||!noOverflow||errors.length||runs.some(r=>!r.withinFiveSeconds||!r.correct)||checks.some(c=>Object.entries(c).some(([k,v])=>k!=='label'&&!v))||!ambiguity.askedForClarification||ambiguity.inventedQuery||Object.values(uiStates).some(v=>!v))process.exitCode=1;
})().catch(async e=>{console.error(e.stack);if(page)await page.screenshot({path:path.join(out,'failure.png')});if(browser)await browser.close();process.exitCode=1;});
