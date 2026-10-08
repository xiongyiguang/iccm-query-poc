"""维护有容量上限的活动会话及带签名、有效期的续问快照。"""
import base64,hashlib,hmac,json,secrets,time

KEY=secrets.token_bytes(32)

def snapshot(sid,session,version):
    previous=session.get('last_success')
    summary=None if not previous else {k:previous.get(k) for k in ('query_receipt','entity','scope','note')}
    if summary is not None:summary['evidence']=previous.get('evidence',[])[:3]
    state={'session':sid,'version':version,'expires':int(time.time())+28800,
           'context':session['context'],'dialogue':session.get('dialogue',[]),'last_success':summary}
    payload=base64.urlsafe_b64encode(json.dumps(state,ensure_ascii=False,separators=(',',':')).encode()).decode()
    return payload+'.'+hmac.new(KEY,payload.encode(),hashlib.sha256).hexdigest()

def restore(token,sid,version):
    if not isinstance(token,str) or len(token)>120000:raise ValueError('历史续问凭据无效，请重新查询。')
    try:
        payload,signature=token.rsplit('.',1)
        if not hmac.compare_digest(signature,hmac.new(KEY,payload.encode(),hashlib.sha256).hexdigest()):raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(payload))
        if data['session']!=sid or data['expires']<time.time():raise ValueError()
    except (ValueError,KeyError,TypeError):raise ValueError('历史续问状态已过期或服务已更新；历史仍可回看，请新建对话重新查询。') from None
    if data['version']!=version:raise ValueError('历史使用不同数据快照，不能直接恢复旧筛选；请在当前数据中新建查询。')
    return {'context':data['context'],'dialogue':data['dialogue'],'last_success':data['last_success'],'results':{},'busy':False,'touched':time.monotonic()}

def make_room(sessions,limit=50):
    while len(sessions)>=limit:
        idle=[(s.get('touched',0),sid) for sid,s in sessions.items() if not s.get('busy')]
        if not idle:raise ValueError('当前查询繁忙，请稍后再试。')
        sessions.pop(min(idle)[1])

def public_result(result):
    """完整依据保存在服务端，仅传输数量受限的首屏内容。"""
    copy={**result,'records':result.get('records',[])[:20],'total':result.get('total',len(result.get('records',[])))}
    refs=result.get('evidence',[])
    copy['evidence']=refs[:20];copy['evidence_total']=len(refs)
    if 'items' in result:copy['items']=[public_result(x) for x in result['items']]
    return copy

def compact_evidence(store,result):
    """每个数据快照只复用一次不可变原始行，避免每次查询复制。"""
    if not hasattr(store,'evidence_pool'):store.evidence_pool={}
    def intern(ref):
        if not ref:return ref
        key=(ref['file'],ref['line'])
        return store.evidence_pool.setdefault(key,ref)
    result['evidence']=[intern(ref) for ref in result.get('evidence',[])]
    for row in result.get('records',[]):
        for key in ('evidence','class_evidence'):
            if row.get(key):row[key]=intern(row[key])
    for item in result.get('items',[]):compact_evidence(store,item)
    return result
