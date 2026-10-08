// 对已授权的 Codex 模型执行真实浏览器操作，不模拟响应。
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('fs'),path=require('path');
let browser,page;
(async()=>{
 const out=path.resolve(__dirname,'../docs/.staging/codex-agent-demo-20260924');
 browser=await chromium.launch({channel:'msedge',headless:true});
 page=await browser.newPage({viewport:{width:1440,height:960}});const errors=[],checks=[],runs=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8771/');
 await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 console.log('page ready');
 checks.push({name:'default_luna',pass:(await page.locator('#model').innerText()).includes('gpt-6-luna')});
 async function ask(label,question,test){
  console.log('ask',label);await page.locator('#question').fill(question);await page.locator('#send').click();
  await page.waitForFunction(()=>document.querySelector('#send').disabled);
  await page.waitForFunction(()=>!document.querySelector('#send').disabled,{},{timeout:200000});
  const result=await page.evaluate(()=>({events:state.current.events,model:state.current.model}));
  const lastUser=result.events.findLastIndex(e=>e.kind==='user');
  const events=result.events.slice(lastUser),final=events.filter(e=>e.kind==='message'&&e.phase==='final_answer').map(e=>e.text).join('\n');
  runs.push({label,question,events,final});
  const pass=test(events,final);checks.push({name:label,pass});console.log(label,pass,final);
 }
 const count=(events,wanted)=>events.some(e=>e.kind==='tool_result'&&e.tool==='iccm_query'&&JSON.stringify(e.result.metrics?.map(m=>m.value))===JSON.stringify(wanted));
 await ask('cross_tree','XJ3ABC002RR 下的设备类描述3727下的部件有多少类？',(es,text)=>count(es,[90,23])&&/23/.test(text));
 await ask('switch_subject','把范围换成 XJ2ABC001MO，设备类不变，有多少部件、多少类？',(es,text)=>count(es,[0,0])&&/0/.test(text));
 const before=await page.locator('.aside-bottom').boundingBox();
 await page.locator('#new').click();await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 await ask('numeric_filter','筛选测量值大于50且小于80摄氏度的测点，告诉我总数。',(es,text)=>{
  const query=es.findLast(e=>e.kind==='tool_start'&&e.tool==='iccm_query');
  const filters=query?.arguments.intent.query?.filters||[];
  return /205/.test(text)&&filters.some(f=>f.field==='value'&&f.operator==='gt'&&String(f.value)==='50')&&filters.some(f=>f.field==='value'&&f.operator==='lt'&&String(f.value)==='80')&&filters.some(f=>f.field==='unit');
 });
 await page.screenshot({path:path.join(out,'live-luna-result.png'),fullPage:true});
 await page.locator('#sessions button').last().click();
 const after=await page.locator('.aside-bottom').boundingBox();
 checks.push({name:'history_same_page_stable_sidebar',pass:Math.abs(before.y-after.y)<1&&await page.locator('.user').count()===2});
 checks.push({name:'visible_real_tool_steps',pass:await page.locator('details.tool').count()>0});
 checks.push({name:'browser_no_errors',pass:errors.length===0,errors});
 fs.writeFileSync(path.join(out,'browser-live.json'),JSON.stringify({checks,runs},null,2));
 console.log(JSON.stringify(checks));await browser.close();if(checks.some(x=>!x.pass))process.exitCode=1;
})().catch(async e=>{console.error(e.stack);if(page){console.error(await page.locator('body').innerText());await page.screenshot({path:path.resolve(__dirname,'../docs/.staging/codex-agent-demo-20260924/browser-failure.png')});}if(browser)await browser.close();process.exitCode=1;});
