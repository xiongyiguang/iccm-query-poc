// 在实际页面验证成功、异常、切换会话及恢复；错误由实际HTTP非法范围触发。
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const url=process.argv[2],out=process.argv[3];
if(!/^http:\/\/127\.0\.0\.1:\d+$/.test(url)||!out)throw Error('需要本机临时服务及新证据目录');
fs.mkdirSync(out,{recursive:false});
(async()=>{
 const browser=await chromium.launch({headless:true});const results=[],errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:960},reducedMotion:'reduce'});page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForFunction(()=>typeof meta!=='undefined'&&meta);
  await page.evaluate(()=>run('构型MOHB01直接部件',{operation:'parts',entity:{tree:'config',code:'MOHB01'},scope:'direct',clarification:''}));
  const sid=await page.evaluate(()=>session);
  await page.route('**/api/query',async route=>{
   const body=route.request().postDataJSON();
   if(body.question==='异常问答留存验证'){
    body.intent={operation:'parts',entity:{tree:'config',code:'MOHB01'},scope:'invalid',clarification:''};
    const response=await route.fetch({postData:JSON.stringify(body)});await route.fulfill({response});
   }else await route.continue();
  });
  await page.evaluate(()=>run('异常问答留存验证'));
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).status),'error');
  assert.equal(await page.evaluate(()=>historyTurns.at(-1).question),'异常问答留存验证');
  assert.ok(await page.evaluate(()=>Boolean(historyTurns.at(-1).result.continuation)));
  const answer=await page.evaluate(()=>historyTurns.at(-1).answer);
  await page.locator('#conversation article').last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'failure-visible.png'),animations:'disabled'});
  await page.evaluate(()=>reset());await page.evaluate(id=>openHistorySession(id),sid);
  assert.ok((await page.locator('#conversation').innerText()).includes('异常问答留存验证'));
  assert.ok((await page.locator('#conversation').innerText()).includes(answer));
  assert.equal(await page.evaluate(()=>context.entity.code),'MOHB01');
  assert.equal(await page.locator('#composer').isVisible(),true);
  await page.reload();await page.waitForFunction(()=>typeof meta!=='undefined'&&meta);await page.evaluate(id=>openHistorySession(id),sid);
  assert.ok((await page.locator('#conversation').innerText()).includes('异常问答留存验证'));
  assert.equal(await page.evaluate(()=>context.entity.code),'MOHB01');
  await page.locator('#conversation article').last().scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'history-restored.png'),animations:'disabled'});
  results.push({passed:true,error_saved:true,question_saved:true,new_session_return:true,refresh_restore:true,actual_focus_preserved:true});
  assert.deepEqual(errors,[]);
 }catch(e){results.push({passed:false,error:String(e)});process.exitCode=1;console.error(e);}
 finally{fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({results,errors},null,2));await browser.close();}
})();
