"""使用真实 Codex 调用和只读工具，对同一问题比较耗时。"""
import json
import argparse
import sys
import threading
import time
from pathlib import Path
from runtime import Runtime
from tools import DataTools, TOOLS

sys.stdout.reconfigure(encoding='utf-8')
out=Path(__file__).resolve().parents[1]/'docs/.staging/codex-agent-demo-20260924'
data=DataTools()
done=threading.Event()
current={}

def notify(method,params):
    if method=='item/agentMessage/delta' and 'first_response_seconds' not in current:
        current['first_response_seconds']=round(time.monotonic()-current['started'],2)
    if method=='item/completed' and params.get('item',{}).get('type')=='agentMessage':
        current.setdefault('messages',[]).append(params['item'])
    if method=='turn/completed':
        current['seconds']=round(time.monotonic()-current['started'],2)
        current['status']=params['turn']['status']
        done.set()

def tool(params):
    record={'name':params['tool'],'arguments':params['arguments']}
    current.setdefault('tools',[]).append(record)
    try:
        result=data.call(params['threadId'],params['tool'],params['arguments'])
    except Exception as error:
        record['error']=str(error)
        raise
    record['result']=result if params['tool']!='iccm_catalog' else {'snapshot':result['snapshot']}
    return result

runtime=Runtime(notify,tool)
try:
    parser=argparse.ArgumentParser()
    parser.add_argument('--models', nargs='+', default=['gpt-6-luna','gpt-6-sol','gpt-6-astra'])
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--tiers', nargs='+', default=['inherit'], choices=['inherit','default','priority'])
    args=parser.parse_args()
    stamp=time.strftime('%Y%m%d-%H%M%S')
    models=runtime.call('model/list',{'includeHidden':False})
    (out/('available-models-'+stamp+'.json')).write_text(json.dumps(models,ensure_ascii=False,indent=2),encoding='utf-8')
    cases=[(model,tier) for model in args.models for tier in args.tiers] * args.repeat
    for run,(model,tier) in enumerate(cases,1):
        done.clear()
        current={'model':model,'effort':'low','requested_service_tier':tier,'question':'XJ3ABC002RR 下的设备类描述3727下的部件有多少类？'}
        thread=runtime.new_thread(TOOLS,model=model,effort='low',service_tier=None if tier=='inherit' else tier)
        current['actual_model']=thread['model']
        current['actual_effort']=thread.get('reasoningEffort')
        current['thread_service_tier']=thread.get('serviceTier')
        current['started']=time.monotonic()
        turn=runtime.call('turn/start',{'threadId':thread['thread']['id'],'environments':[],
            'input':[{'type':'text','text':current['question']}],'effort':'low',
            **({'serviceTier':tier} if tier!='inherit' else {})})
        if not done.wait(150):
            runtime.call('turn/interrupt',{'threadId':thread['thread']['id'],'turnId':turn['turn']['id']})
            done.wait(10)
            current['timed_out']=True
        current.pop('started',None)
        (out/('timing-'+stamp+'-'+str(run)+'-'+model+'-low-'+tier+'.json')).write_text(json.dumps(current,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in current.items() if k!='tools'},ensure_ascii=False),flush=True)
finally:runtime.close()
