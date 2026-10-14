// 实际本机页面验证未决槽位随历史恢复，以及换根和独立请求的可见状态。
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const [url,out]=process.argv.slice(2);
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)||!out)throw Error('需要本机隔离服务及新证据目录');
fs.mkdirSync(out,{recursive:false});
(async()=>{
 const browser=await chromium.launch({headless:true});const results=[],errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:960},reducedMotion:'reduce'});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForFunction(()=>typeof meta!=='undefined'&&meta);
  await page.evaluate(()=>run('独立问题：请列出直接部件。'));
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).result.status),'clarify');
  const sid=await page.evaluate(()=>session);
  await page.evaluate(()=>reset());await page.evaluate(id=>openHistorySession(id),sid);
  assert.equal(await page.evaluate(()=>context.pending_public_query.depth),'direct');
  await page.reload();await page.waitForFunction(()=>typeof meta!=='undefined'&&meta);await page.evaluate(id=>openHistorySession(id),sid);
  assert.equal(await page.evaluate(()=>context.pending_public_query.depth),'direct');
  await page.screenshot({path:path.join(out,'pending-restored.png'),animations:'disabled'});
  await page.evaluate(()=>run('构型树 MOHB22。'));
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).result.status),'ok');
  assert.equal(await page.evaluate(()=>context.entity.code),'MOHB22');
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).result.total),15);
  await page.evaluate(()=>run('沿用刚才范围，把对象换成构型树 MOHA66，查部件。'));
  assert.equal(await page.evaluate(()=>context.entity.code),'MOHA66');
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).result.total),77);
  assert.equal(await page.evaluate(()=>context.scope),'direct');
  await page.screenshot({path:path.join(out,'new-root-resolved.png'),animations:'disabled'});
  await page.evaluate(()=>run('开始独立问题：直接部件有哪些？根对象还没有给。'));
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).result.status),'clarify');
  assert.equal(await page.evaluate(()=>context.entity||null),null);
  assert.equal(await page.evaluate(()=>context.pending_public_query.root),null);
  await page.screenshot({path:path.join(out,'independent-needs-root.png'),animations:'disabled'});
  assert.deepEqual(errors,[]);results.push({passed:true,pending_survives_session_switch:true,pending_survives_refresh:true,scope_survives_root_change:true,independent_request_does_not_reuse_old_root:true});
  await page.evaluate(async()=>{await api('/api/reset',{session});});
 }catch(error){results.push({passed:false,error:String(error)});process.exitCode=1;console.error(error);}
 finally{fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({results,errors},null,2));await browser.close();}
})();
