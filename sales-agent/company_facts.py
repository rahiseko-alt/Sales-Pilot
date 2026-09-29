"""Conservative extraction of published company size and workload evidence.

``confirmed`` means a count is attributable to the named legal entity on a
verified page. It does not establish the current employee count. ``as_of``
and ``scope`` allow callers to make that separate judgment.
"""
from datetime import date
import re

COUNT = re.compile(r'(従業員数|社員数|従業員)\s*[:：]?\s*([\d,]+)\s*(?:名|人)')
WORKLOAD = re.compile(r'(?:月間|月あたり|毎月|1日あたり|日次)\s*[約]?\s*[\d,]+\s*(?:件|時間|分)')
NOT_TOTAL = re.compile(r'部署|部門|工場|拠点|営業部|予定|見込|推定|取引先|顧客|導入先|派遣元|紹介会社|以上|以下|仮に|例えば|例[:：]|想定|とすると|かもしれない|試算')
GROUP = re.compile(r'連結|グループ|海外子会社|子会社')
SUBSET = re.compile(r'(?:正|契約|派遣|常勤|非常勤)$')
DATE_JP = re.compile(r'(?<!\d)((?:19|20)\d{2})年(\d{1,2})月(?:(\d{1,2})日|末|初|中旬)?')
DATE_ISO = re.compile(r'(?<!\d)((?:19|20)\d{2})[-/](\d{1,2})(?:[-/](\d{1,2}))?')


def _context(text, start, end):
    left=max(text.rfind('\n',0,start),text.rfind('。',0,start))+1
    stops=[position for separator in ('\n','。') if (position:=text.find(separator,end)) >= 0]
    right=min(stops) if stops else len(text)
    return text[max(left,start-200):min(right,end+200)].strip()


def _date_value(fragment):
    matches=[]
    for pattern in (DATE_JP,DATE_ISO):
        matches.extend((match.start(),match) for match in pattern.finditer(fragment))
    for _,match in sorted(matches):
        year,month,day=(int(value) if value else None for value in match.groups())
        try:date(year,month,day or 1)
        except ValueError:continue
        return f'{year:04d}-{month:02d}-{day:02d}' if day else f'{year:04d}-{month:02d}'
    return None


def _as_of(text, start, end):
    # Never borrow a later corporation's date from flattened HTML.
    following=text[end:end+100]
    following=re.split(r'。|\n|株式会社|従業員数|社員数',following,maxsplit=1)[0]
    value=_date_value(following)
    if value:return value
    preceding=text[max(0,start-55):start]
    preceding=re.split(r'。|\n|株式会社|従業員数|社員数',preceding)[-1]
    return _date_value(preceding)


def _candidate(item, count, quote, scope, as_of, attributed):
    return {'employee_count':count,'source_url':item['url'],'quote':quote,
            'scope':scope,'as_of':as_of,'attribution_confirmed':attributed,
            'retrieved_at':item.get('retrieved_at')}


def _named_entity_candidates(item, company_name, attributed):
    """Parse only the target corporation's row of a multi-company roster."""
    text=item['text']
    if not company_name or not company_name.startswith('株式会社'):return []
    normalized=re.sub(r'\s+','',company_name)
    pattern=re.compile(r'\s*'.join(re.escape(char) for char in normalized)
                       +r'\s*[:：]?\s*([\d,]+)\s*(?:名|人)')
    rows=[]
    for match in pattern.finditer(text):
        # The source parser collapses DOM whitespace. A heading more than 200
        # characters before the row cannot be safely tied to this number, so
        # such a row stays unknown until a better structured source is added.
        prefix=text[max(0,match.start()-200):match.start()]
        if '従業員数' not in prefix:continue
        count=int(match[1].replace(',',''))
        if count<=0:continue
        rows.append(_candidate(item,count,match[0].strip(),'named_legal_entity',
                               _as_of(text,match.start(),match.end()),attributed))
    return rows


def extract_company_facts(evidence, company_name=None):
    sizes=[];workloads=[]
    for raw in evidence:
        if not isinstance(raw,dict):continue
        item=dict(raw);url=item.get('url','')
        if not isinstance(url,str) or not url.startswith(('https://','http://')):continue
        text=item.get('text','')
        if not isinstance(text,str):continue
        attributed=bool(company_name and item.get('company_name')==company_name
                        and item.get('company_identity_verified') is True)
        sizes.extend(_named_entity_candidates(item,company_name,attributed))
        for match in COUNT.finditer(text):
            if SUBSET.search(text[max(0,match.start()-10):match.start()]):continue
            context=_context(text,match.start(),match.end())
            nearby=text[max(0,match.start()-80):match.end()+80]
            if NOT_TOTAL.search(nearby):continue
            count=int(match[2].replace(',',''))
            if count<=0:continue
            scope='includes_overseas_subsidiaries' if '海外子会社' in nearby else 'unknown' if GROUP.search(nearby) else 'company'
            sizes.append(_candidate(item,count,context,scope,
                                    _as_of(text,match.start(),match.end()),attributed))
        for match in WORKLOAD.finditer(text):
            context=_context(text,match.start(),match.end())
            if re.search(r'削減|短縮|予測|見込|予定|目標|可能|導入後',context):continue
            workloads.append({'quote':context,'source_url':url,
                              'attribution_confirmed':attributed,
                              'retrieved_at':item.get('retrieved_at')})
    qualified=[candidate for candidate in sizes if candidate['scope'] in ('company','named_legal_entity')]
    counts={candidate['employee_count'] for candidate in qualified}
    if len(counts)==1 and qualified and all(candidate['attribution_confirmed'] for candidate in qualified):
        company_size={**qualified[0],'confirmed':True,'status':'published_count'}
    else:
        group_only=not qualified and len(sizes)==1 and sizes[0]['scope']=='includes_overseas_subsidiaries'
        company_size={'confirmed':False,'employee_count':None,'status':'unknown',
                      'scope':'includes_overseas_subsidiaries' if group_only else 'unknown',
                      'as_of':sizes[0]['as_of'] if group_only else None,
                      'reason':'資料間で人数が異なる' if len(counts)>1 else
                               '対象企業への帰属未確認' if qualified else
                               '子会社込みの人数は単体人数ではない' if group_only else
                               '全社人数の明示資料なし','candidates':sizes}
    return {'company_size':company_size,'workload_evidence':workloads}
