"""补充预期勘误与负例，保留原 V1 记录。"""
import replay_team_feedback_extended as suite

def exact_empty(r,target,field,value):
 return r.get('status')=='ok' and r.get('records')==[] and r.get('total')==0 and r.get('query')=={'target':target,'filters':[{'field':field,'operator':'equals','value':value}]} and not r.get('candidate_only')

suite.CASES=[
 ('name','只按名称精确查找构型MOHB01，不要按编码查','名称精确过滤且空列表；V1状态预期勘误',lambda r:exact_empty(r,'config','name','MOHB01')),
 ('count','统计测点编码严格等于2ABC109MT的记录数，不要包含匹配','精确统计零条，不可候选放宽',lambda r:exact_empty(r,'points','code','2ABC109MT')),
 ('source','查询来源为不存在的源、编码为2ABC109MT的测点监测值','候选召回保留来源约束',lambda r:r.get('status')=='not_found'),
 ('short','查询编码为2的测点监测值','短片段不可过度召回',lambda r:r.get('status')=='not_found'),
 ('special','查询编码为%__的测点监测值','通配字符按文本处理，不得匹配全库',lambda r:r.get('status')=='not_found'),
 ('abandon','查一下测点2ABC109MT的监测值','进入候选待选状态',lambda r:r.get('status')=='ambiguous' and r.get('candidate_only')),
 ('abandon','这个先不选了，告诉我构型MOHB01的名称','未选候选时独立新问题不受旧任务污染',suite.entity('MOHB01')),
 ('abandon','它的上级编码是什么？','新对象代词不能回到旧测点',lambda r:suite.entity('MOHB01')(r) and suite.attrs('parent')(r)),
 ('units','XJ2ABC001MO.TMP.2ABC109MT.BBe这个测点现在多少摄氏度？','读取原值，不补造摄氏度单位',lambda r:suite.entity('XJ2ABC001MO.TMP.2ABC109MT.BBe')(r) and suite.attrs('value')(r) and '摄氏度' not in r.get('answer','') and '40.69898987' in r.get('answer','')),
 ('mixed','查询测点XJ1ABC001PO.JVD.1ABC029MV.LBe_Y的编码和变化速率','编码保持文本，速率精确展开',lambda r:suite.rate(r) and suite.attrs('code','rate')(r)),
]
if __name__=='__main__':raise SystemExit(suite.main())
