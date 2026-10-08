const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),webcrypto=require('node:crypto').webcrypto;
const source=fs.readFileSync(require('node:path').join(__dirname,'../frontend/app.js'),'utf8');
function setup(fail=false){
 const elements=new Map(),calls=[];
 const el=()=>({children:[],value:'',hidden:false,textContent:'',classList:{add(){},remove(){}},append(...x){this.children.push(...x)},prepend(...x){this.children.unshift(...x)},replaceChildren(...x){this.children=x},setAttribute(){},addEventListener(){},querySelectorAll(){return []},querySelector(){return null},remove(){},scrollIntoView(){},isConnected:true});
 const document={getElementById(id){if(!elements.has(id))elements.set(id,el());return elements.get(id)},createElement:el,querySelectorAll(){return []}};
 const context=vm.createContext({document,crypto:{getRandomValues:array=>webcrypto.getRandomValues(array)},Uint8Array,console,AbortController,performance,setTimeout,clearTimeout,requestAnimationFrame:fn=>fn(),window:{matchMedia:()=>({matches:true})},location:{replace(){}},fetch:async(path,options)=>{calls.push({path,body:options.body?JSON.parse(options.body):null});if(fail)throw new TypeError('offline');return {ok:true,status:200,json:async()=>path==='/api/meta'?{token:'synthetic',auth_required:true,version:'test',counts:{pbs:5},model:{available:true}}:{status:'ok',answer:'test result',records:[],total:0,metrics:[],columns:[],context:{}}};}});
 return {context,document,calls,elements};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 const a=setup();vm.runInContext(source,a.context);await tick();
 assert.equal(a.calls[0].path,'/api/meta');assert.equal(a.document.getElementById('modelState').children[1].textContent,'密钥已配置');
 const old=vm.runInContext('session',a.context);assert.ok(old.length>20);
 await a.document.getElementById('startDevice').onclick();assert.equal(a.calls.find(x=>x.path==='/api/query').body.intent.operation,'equipment');
 await a.document.getElementById('new').onclick();assert.notEqual(vm.runInContext('session',a.context),old);assert.ok(!a.calls.some(x=>x.path==='/api/reset'),'completed history remains resumable');
 const ids=vm.runInContext('Array.from({length:1000},()=>createSessionId())',a.context);assert.equal(new Set(ids).size,1000);
 const b=setup(true);vm.runInContext(source,b.context);await tick();assert.equal(b.document.getElementById('modelState').children[1].textContent,'服务未连接');
 console.log('PASS: HTTP bootstrap, device query, new conversation, random IDs, connection failure');
})().catch(e=>{console.error(e.message);process.exitCode=1});
