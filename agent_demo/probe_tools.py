"""使用无业务数据的回显工具临时诊断协议。"""
import json
import threading
from runtime import Runtime

done=threading.Event()
events=[]
def notify(method, params):
    if method=='item/completed':
        item=params.get('item',{})
        if item.get('type') in ('agentMessage','dynamicToolCall'):
            print(json.dumps(item,ensure_ascii=True),flush=True)
    if method=='turn/completed':done.set()

def tool(params):
    print('TOOL_CALLED '+params['tool'],flush=True)
    return {'verified':'echo-success'}

runtime=Runtime(notify,tool)
try:
    for env in [[],None]:
        done.clear()
        params={'cwd':str(__import__('pathlib').Path(__file__).parent.resolve()),'sandbox':'read-only','approvalPolicy':'never','ephemeral':True,
                'baseInstructions':'Use only the supplied echo tool. Do not inspect files or invoke other tools.',
                'dynamicTools':[{'type':'function','name':'demo_echo','description':'Return a diagnostic echo.','deferLoading':False,'inputSchema':{'type':'object','properties':{},'additionalProperties':False}}]}
        if env is not None:params['environments']=env
        thread=runtime.call('thread/start',params)
        print('ENV '+str(env)+' MODEL '+thread['model'],flush=True)
        runtime.call('turn/start',{'threadId':thread['thread']['id'],'input':[{'type':'text','text':'Call demo_echo once and quote the returned verified value.'}]})
        if not done.wait(55):
            print('TIMEOUT',flush=True)
            break
finally:runtime.close()
