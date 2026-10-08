const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),assert=require('node:assert/strict');
const dest=process.env.FIRST_TRANSITION_OUTPUT||'docs/.staging/team-test-20260923/sidebar-first-transition.json';
if(fs.existsSync(dest))throw Error('Preserve previous evidence');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true}),results=[],errors=[];
 try{
 for(let round=1;round<=3;round++)for(const [width,height] of [[1536,900],[1440,720],[1440,1100],[560,780]]){
  const ctx=await browser.newContext({viewport:{width,height},reducedMotion:'reduce'}),p=await ctx.newPage();p.on('pageerror',e=>errors.push(String(e)));
  await p.goto('http://127.0.0.1:8766');await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  const coords=()=>p.evaluate(()=>Object.fromEntries([...document.querySelectorAll('#new,#history,.source-item,#modelState')].filter(e=>e.offsetHeight).map((e,i)=>{const r=e.getBoundingClientRect();return [e.id||'data-'+i,[r.x,r.y,r.width,r.height]]})));
  const before=await coords();
  if(round===1&&width===1536)await p.screenshot({path:'docs/.staging/team-test-20260923/sidebar-first-initial.png'});
  async function check(stage){const actual=await coords(),passed=JSON.stringify(actual)===JSON.stringify(before);results.push({round,width,height,stage,passed,before,actual})}
  await p.locator('#history').click();await check('first-empty-history');
  if(round===1&&width===1536)await p.screenshot({path:'docs/.staging/team-test-20260923/sidebar-first-history.png'});
  await p.locator('#backToCurrent').click();await check('return-empty-current');
  await p.locator('#new').click();await p.locator('#startDevice').click();await p.waitForFunction(()=>document.querySelector('#conversation .answer')&&!document.querySelector('#send').disabled);await check('first-answer');
  await p.locator('#new').click();await check('new-after-answer');
  for(let n=0;n<3;n++){await p.locator('#history').click();await check('populated-history-'+n);await p.locator('#backToCurrent').click();await check('return-current-'+n)}
  await p.reload();await p.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));await check('reload-with-saved-history');
  await p.locator('#history').click();await check('history-after-reload');
  await ctx.close();
 }
 assert.deepEqual(errors,[]);
 }catch(e){results.push({passed:false,error:String(e)});console.error(e)}
 finally{fs.writeFileSync(dest,JSON.stringify({results,errors},null,2));await browser.close()}
 const failed=results.filter(x=>!x.passed);console.log(JSON.stringify({checks:results.length,failures:failed.length,firstFailure:failed[0]}));if(failed.length)process.exitCode=1;
})();
