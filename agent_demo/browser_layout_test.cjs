// 仅检查界面布局和 HTTP 边界，阻止创建会话，不调用模型。
const {chromium}=require('C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const path=require('path'),fs=require('fs');
(async()=>{
 const out=path.resolve(__dirname,'../docs/.staging/codex-agent-demo-20260924');
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/new',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({id:'layout-only',model:'布局验证 · 未调用模型'})}));
 await page.goto('http://127.0.0.1:8771/');
 await page.waitForFunction(()=>!document.querySelector('#send').disabled);
 const checks=[];
 const bottom=()=>page.locator('.aside-bottom').boundingBox();
 const before=await bottom();
 await page.locator('#new').click();
 await page.waitForFunction(()=>document.querySelectorAll('#sessions button').length===2);
 const after=await bottom();
 checks.push({name:'new_conversation_bottom_stable',pass:Math.abs(before.y-after.y)<1});
 const fixture=await page.request.get('http://127.0.0.1:8771/api/meta');
 checks.push({name:'local_metadata',pass:fixture.ok()});
 const forbidden=await page.request.post('http://127.0.0.1:8771/api/ask',{data:{session:'layout-only',question:'must not run'},headers:{'X-Local-Token':'invalid'}});
 checks.push({name:'invalid_token_rejected',pass:forbidden.status()===403});
 const cross=await page.request.get('http://127.0.0.1:8771/api/meta',{headers:{Origin:'https://example.invalid'}});
 checks.push({name:'cross_origin_rejected',pass:cross.status()===403});
 await page.evaluate(()=>{
  render({kind:'user',text:'布局样例：展示查询依据'});
  render({kind:'message',id:'sample',text:'这是界面验证样例，不是实际模型回答。',phase:'final_answer'});
  render({kind:'tool_start',id:'tool',tool:'iccm_query',arguments:{test:'layout only'}});
  render({kind:'tool_result',id:'tool',tool:'iccm_query',seconds:0,result:{answer:'布局验证样例',columns:['名称','编码'],records:[{cells:['<script>alert(1)</script>','XJ3ABC002RR']}],evidence:[]}});
 });
 await page.locator('details.tool').evaluate(e=>e.open=true);
 checks.push({name:'source_text_escaped',pass:await page.locator('td').first().innerText()==='<script>alert(1)</script>'});
 await page.screenshot({path:path.join(out,'layout-desktop.png'),fullPage:true});
 for(const width of [1024,600,390]){
  await page.setViewportSize({width,height:800});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  checks.push({name:'no_horizontal_overflow_'+width,pass:!overflow});
 }
 await page.screenshot({path:path.join(out,'layout-mobile.png'),fullPage:true});
 checks.push({name:'no_browser_errors',pass:errors.length===0,errors});
 fs.writeFileSync(path.join(out,'layout-test.json'),JSON.stringify({mode:'local UI fixtures, model requests blocked',checks},null,2));
 console.log(JSON.stringify(checks));await browser.close();if(checks.some(c=>!c.pass))process.exitCode=1;
})().catch(e=>{console.error(e.message);process.exitCode=1;});
