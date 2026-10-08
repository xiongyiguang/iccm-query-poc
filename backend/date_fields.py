"""保留原始日期文本，以明确时区的时间值执行范围比较。"""
from datetime import datetime,timezone,timedelta

TIMEZONE=timezone(timedelta(hours=8))
DATE_OPS={'date_gte','date_lt','date_equals'}
DATE_LABELS={'date_gte':'时间不早于','date_lt':'时间早于','date_equals':'时间等于'}

def parse_time(value):
 if not isinstance(value,str) or not value.strip() or len(value)>100:return None
 value=value.strip()
 try:
  parsed=datetime.fromisoformat(value.replace('/','-'))
 except ValueError:
  parsed=None
  for fmt in ('%Y/%m/%d %H:%M','%Y/%m/%d %H:%M:%S','%Y/%m/%d','%Y-%m-%d %H:%M','%Y-%m-%d'):
   try:parsed=datetime.strptime(value,fmt);break
   except ValueError:pass
  if parsed is None:return None
 return parsed.replace(tzinfo=TIMEZONE) if parsed.tzinfo is None else parsed.astimezone(TIMEZONE)

def compare_time(left,operator,right):
 a=parse_time(left)
 period=calendar_period(right) if operator=='date_equals' else None
 if period:return int(a is not None and period[0]<=a<period[1])
 b=parse_time(right)
 if a is None or b is None:return 0
 return int(a>=b if operator=='date_gte' else a<b if operator=='date_lt' else a==b if operator=='date_equals' else False)

def business_clock():
 now=datetime.now(TIMEZONE)
 return {'as_of':now.isoformat(),'timezone':'Asia/Shanghai','relative_time_basis':'用户提问时的业务时间；导入快照的记录时间不代替今年。'}

def canonical_year_filters(filters,store):
 """按业务时区归一日历年/月/日；文本年须全快照证明，不按条数猜等价。"""
 import re
 fs=list(filters);ranges=[]
 for field,op,value in fs:
  if field!='time' or op!='date_gte':continue
  start=parse_time(value)
  if start is None or start.year>=9999 or (start.month,start.day,start.hour,start.minute,start.second,start.microsecond)!=(1,1,0,0,0,0):continue
  end=next((f for f in fs if f[0]=='time' and f[1]=='date_lt' and parse_time(f[2])==start.replace(year=start.year+1)),None)
  if end:ranges.append(((field,op,value),end,str(start.year)))
 for left,right,year in ranges:
  if left in fs and right in fs:fs.remove(left);fs.remove(right);fs.append(('time','calendar_year',year))
 for field,op,value in list(fs):
  if field=='time' and op=='date_equals' and isinstance(value,str) and re.fullmatch(r'[1-9]\d{3}',value) and calendar_period(value):
   fs.remove((field,op,value));fs.append(('time','calendar_year',value))
 years={str(value) for field,op,value in fs if field=='time' and op=='contains' and re.fullmatch(r'[1-9]\d{3}',str(value))}
 for year in years:
  valid=True
  for row in store.rows('SELECT time FROM points'):
   raw=row['time'] or '';parsed=parse_time(raw)
   if (year in raw)!=(parsed is not None and parsed.year==int(year)):valid=False;break
  if valid:fs.remove(('time','contains',year));fs.append(('time','calendar_year',year))
 # 日、月精度与对应半开范围按精确边界归一，和记录条数无关。
 # 年归一保持既有形式；带时刻的相等仍是瞬间，不能当整日。
 for field,op,value in list(fs):
  if field!='time' or op!='date_gte':continue
  start=parse_time(value)
  if start is None or (start.hour,start.minute,start.second,start.microsecond)!=(0,0,0,0):continue
  candidates=[]
  if start.day==1:candidates.append(('calendar_month',start.strftime('%Y-%m')))
  candidates.append(('calendar_day',start.strftime('%Y-%m-%d')))
  for label,period_value in candidates:
   period=calendar_period(period_value)
   if period is None or period[0]!=start:continue
   end=next((f for f in fs if f[0]=='time' and f[1]=='date_lt' and parse_time(f[2])==period[1]),None)
   if end and (field,op,value) in fs:
    fs.remove((field,op,value));fs.remove(end);fs.append(('time',label,period_value));break
 for field,op,value in list(fs):
  if field=='time' and op=='date_equals' and isinstance(value,str) and calendar_period(value):
   parts=value.split('-')
   if len(parts) in (2,3):
    fs.remove((field,op,value));fs.append(('time','calendar_month' if len(parts)==2 else 'calendar_day',value))
 return fs

def calendar_period(value):
 """日期等于按明确的年、月、日精度比较，带时间仍精确比较瞬间。"""
 import re
 if not isinstance(value,str) or not re.fullmatch(r'[1-9]\d{3}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?',value):return None
 parts=value.split('-')
 try:
  start=datetime(int(parts[0]),int(parts[1]) if len(parts)>1 else 1,int(parts[2]) if len(parts)>2 else 1,tzinfo=TIMEZONE)
  if len(parts)==1:end=start.replace(year=start.year+1)
  elif len(parts)==2:end=start.replace(year=start.year+1,month=1) if start.month==12 else start.replace(month=start.month+1)
  else:end=start+timedelta(days=1)
  return start,end
 except (ValueError,OverflowError):return None
