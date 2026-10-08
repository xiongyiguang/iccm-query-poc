// 经 run_cloud_browser.cjs 使用，凭据不进入源码或输出。
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),ctx=await browser.newContext({viewport:{width:1440,height:900}}),p=await ctx.newPage(),results=[],errors=[];
 p.on('pageerror',e=>errors.push(String(e)));
 async function ask(q,check){
  await p.locator('#question').fill(q);const response=p.waitForResponse(r=>r.url().endsWith('/api/query')&&r.request().method()==='POST');await p.locator('#send').click();
  const res=await response,r=await res.json();await p.waitForFunction(()=>!document.querySelector('#send').disabled);
  const passed=res.ok()&&check(r);results.push({question:q,passed,response:r});assert.ok(passed,q);
 }
 try{
  await p.goto('http://127.0.0.1:8766');await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  assert.equal(await p.locator('#logout').isVisible(),true);
  await ask('介绍XXXX1',r=>r.status==='clarify');await ask('PBS',r=>r.entity?.code==='XJ3ABC002RR&RRGA02.Zaf.IDS');
  await p.locator('#new').click();await ask('2ABC109MT 这个测点现在多少度？',r=>r.status==='ambiguous'&&r.candidate_only);
  await p.locator('#conversation .answer').last().getByRole('button').filter({hasText:'XJ2ABC001MO.TMP.2ABC109MT.BBe'}).first().click();
  await ask('就这个，继续刚才的问题',r=>r.entity?.code==='XJ2ABC001MO.TMP.2ABC109MT.BBe'&&r.attributes?.some(x=>x.property==='value'));
  await p.locator('#new').click();await ask('查询测点 XJ1ABC001PO.JVD.1ABC029MV.LBe_Y 的变化速率',r=>r.attributes?.some(x=>x.display_value==='-0.000000000405'));
  assert.ok((await p.locator('#conversation').innerText()).includes('-0.000000000405'));
  await p.locator('#history').click();assert.ok((await p.locator('#historyConversation').innerText()).includes('-0.000000000405'));
  await p.screenshot({path:'docs/.staging/team-test-20260923/cloud-history-decimal.png'});
  await p.locator('#new').click();await ask('按PBS对象层级统计对象数量',r=>r.analysis?.group_by==='level'&&r.records.reduce((a,x)=>a+x.cells[2],0)===16796);
  assert.ok(await p.locator('#conversation .analysis-chart').count());
  await p.locator('#history').click();assert.ok(await p.locator('#historyConversation .analysis-chart').count());
  await p.screenshot({path:'docs/.staging/team-test-20260923/cloud-history-groups.png'});
  await p.reload();await p.locator('#history').click();assert.equal(await p.locator('#historySessions button').count(),4);
  await p.locator('#logout').click();await p.waitForURL('**/login');
  assert.equal((await ctx.request.get('http://127.0.0.1:8766/api/meta')).status(),401);
  assert.equal(await p.evaluate(()=>sessionStorage.getItem('iccm-tab-history-v1')),null);
  results.push({test:'history-refresh-and-logout-clears-records',passed:true});assert.deepEqual(errors,[]);
 }catch(e){results.push({passed:false,error:String(e)});process.exitCode=1;console.error(e)}
 finally{fs.writeFileSync('docs/.staging/team-test-20260923/cloud-journey.json',JSON.stringify({results,errors},null,2));await browser.close()}
})();
