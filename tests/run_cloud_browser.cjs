// 执行既有界面测试，只替换公网地址、输出目录和登录步骤。
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'C:/Users/xiong/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base=process.env.ICCM_TEST_URL,out=process.env.ICCM_TEST_OUTPUT,suite=process.argv[2];
if(!base||!out||!suite)throw Error('Set ICCM_TEST_URL and ICCM_TEST_OUTPUT; supply suite filename');
fs.mkdirSync(out,{recursive:true});
const credentials=Object.fromEntries(fs.readFileSync('.local/cloud-8899-access.txt','utf8').replace(/^\uFEFF/,'').split(/\r?\n/).filter(x=>x.includes(':')).map(x=>{const i=x.indexOf(':');return [x.slice(0,i).trim(),x.slice(i+1).trim()]}));
const originalLaunch=chromium.launch.bind(chromium);
chromium.launch=async options=>{
 const browser=await originalLaunch(options),originalContext=browser.newContext.bind(browser);
 browser.newContext=async options=>{
  const ctx=await originalContext(options),page=await ctx.newPage();
  await page.goto(base);await page.locator('#username').fill(credentials.Username);await page.locator('#password').fill(credentials.Password);
  await page.locator('#submit').click();await page.waitForURL(base+'/');
  await page.waitForFunction(()=>!document.querySelector('#modelState').textContent.includes('正在检查'));
  assert.equal(await page.locator('#logout').isVisible(),true);
  await page.close();return ctx;
 };
 return browser;
};
let code=fs.readFileSync(path.join(__dirname,suite),'utf8');
code=code.replaceAll('http://127.0.0.1:8766',base).replaceAll('docs/.staging/team-test-20260923',out.replaceAll('\\','/'));
// 使用冻结测试集所用的同一绝对路径 Playwright 安装。
eval(code);
