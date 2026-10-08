const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const results=[],errors=[];
 try{
  for(let round=1;round<=3;round++){
   const context=await browser.newContext({viewport:{width:1440,height:900},reducedMotion:'reduce'}),page=await context.newPage();
   page.on('pageerror',e=>errors.push(String(e)));
   await page.goto('http://127.0.0.1:8766');await page.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
   await page.locator('#history').click();assert.equal(await page.locator('#historyConversation .answer').count(),0);
   for(let i=0;i<12;i++){
    await page.locator('#new').click();await page.locator('#startDevice').click();
    await page.waitForFunction(()=>document.querySelector('#conversation .answer')&&!document.querySelector('#send').disabled);
   }
   const current=await page.locator('#conversation').innerText();
   for(const [width,height] of [[1536,900],[950,850],[560,780]]){
    await page.setViewportSize({width,height});
    for(let cycle=0;cycle<5;cycle++){
     await page.locator('#workspace').evaluate(e=>e.scrollTop=e.scrollHeight);
     const before=await page.locator('#new').boundingBox(),scroll=await page.locator('#workspace').evaluate(e=>e.scrollTop);
     await page.locator('#history').click();assert.equal(await page.locator('#historySessions button').count(),12);
     await page.locator('#historySessions button').last().click();
     assert.equal(await page.locator('#historyConversation .answer').count(),1);
     assert.equal(await page.locator('#composer').isVisible(),false);
     const after=await page.locator('#new').boundingBox();assert.deepEqual(after,before);
     assert.equal(await page.evaluate(()=>window.scrollY),0);
     await page.locator('#backToCurrent').click();
     assert.equal(await page.locator('#conversation').innerText(),current);
     assert.ok(Math.abs(await page.locator('#workspace').evaluate(e=>e.scrollTop)-scroll)<1);
    }
    results.push({round,width,height,cycles:5,passed:true});
   }
   await page.reload();await page.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
   await page.locator('#history').click();assert.equal(await page.locator('#historySessions button').count(),12);
   assert.equal(await page.locator('#historyConversation .answer').count(),1);
   await page.locator('#new').click();assert.equal(await page.locator('#welcome').isVisible(),true);
   assert.equal(await page.locator('#workspace').evaluate(e=>e.scrollTop),0);
   const isolated=await context.newPage();await isolated.goto('http://127.0.0.1:8766');
   await isolated.locator('#history').click();assert.equal(await isolated.locator('#historySessions button').count(),0);
   results.push({round,refresh:true,newConversation:true,newTabIsolation:true,passed:true});
   await context.close();console.log('Browser round '+round+' passed');
  }
  assert.deepEqual(errors,[]);
 }catch(e){results.push({passed:false,error:String(e)});process.exitCode=1;console.error(e);}
 finally{fs.writeFileSync('docs/.staging/team-test-20260923/history-extended.json',JSON.stringify({results,errors},null,2));await browser.close();}
})();
