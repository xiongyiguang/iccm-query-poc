"""本轮控制来源：独立请求与肯定范围不从引用名称、否定历史描述推导。"""
import copy
import re


def control_text(text):
    text = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"]*"|`[^`]*`', '', text)
    return re.sub(r'(?:名字(?:叫|为)|名称(?:为|是)|名为|编码(?:为|是))[^，。；：:]*', '', text)


def independent(text):
    text = control_text(text)
    return bool(re.search(r'独立(?:问题|查询|查)|(?:开始|另开|另起|另一个|新的?|新)(?:一个)?(?:独立)?问题|重新开始|不继承(?:以前|原来|之前|上次|旧)?(?:的)?(?:条件|范围|对象)', text))


def planning_context(question, context, store=None):
    if not independent(question): return copy.deepcopy(context or {})
    # 新请求保留数据/能力目录；执行历史仍留在原会话，只解除本轮规划所有者。
    out = {k: copy.deepcopy(v) for k, v in (context or {}).items()
           if k in ('verified_schema', 'verified_knowledge')}
    out['independent_request'] = True
    if store is not None:
        from request_gateway import reference_context
        out['verified_references'] = reference_context(out, None, store, question)
    return out


def positive_scope_text(text):
    clauses = re.split(r'[，,。；;！？!?]', control_text(text))
    # 否定和撤销的片段不提供正向范围。每个片段独立，后续肯定请求仍有效。
    return '，'.join(c for c in clauses if not re.search(r'不要|不(?:是|用|要|沿用|继承|保留|查|执行)|别(?:查|沿用|继承)|取消|撤销', c))


def depth_control(text):
    text = positive_scope_text(text)
    direct = bool(re.search(r'直接|直属|下一层|直接子|仅一层', text))
    all_depth = bool(re.search(r'全部(?:的)?(?:后代|下级)|所有(?:的)?(?:后代|下级)|全层级|全部层级|所有层级', text))
    if direct == all_depth: return None
    return 'direct' if direct else 'all'
