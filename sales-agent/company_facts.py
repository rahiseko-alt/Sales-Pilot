"""Conservative extraction of explicitly published size and workload facts."""
import re


def _context(text, start, end):
    left=max(text.rfind('\n',0,start),text.rfind('。',0,start))+1
    stops=[position for separator in ('\n','。') if (position:=text.find(separator,end)) >= 0]
    right=min(stops) if stops else len(text)
    return text[max(left,start-200):min(right,end+200)].strip()


def extract_company_facts(evidence, company_name=None):
    sizes = []
    workloads = []
    for item in evidence:
        url = item.get('url', '')
        if not url.startswith(('https://', 'http://')):
            continue
        text = item.get('text', '')
        attributed = bool(company_name and item.get('company_name') == company_name
                          and item.get('company_identity_verified') is True)
        for match in re.finditer(r'(従業員数|社員数)\s*[:：]?\s*([\d,]+)\s*(?:名|人)', text):
            if re.search(r'(?:正|契約|派遣|常勤|非常勤)$',text[max(0,match.start()-10):match.start()]):
                continue
            context=_context(text,match.start(),match.end())
            scope=text[max(0,match.start()-80):match.end()+80]
            if re.search(r'連結|グループ|部署|部門|工場|拠点|営業部|予定|見込|推定|取引先|顧客|導入先|派遣元|紹介会社|子会社|以上|以下|仮に|例えば|例[:：]|想定|とすると|かもしれない|試算', scope):
                continue
            count = int(match[2].replace(',', ''))
            if count > 0:
                sizes.append({'employee_count':count,'source_url':url,
                              'quote':context,'attribution_confirmed':attributed,
                              'retrieved_at':item.get('retrieved_at')})
        for match in re.finditer(r'(?:月間|月あたり|毎月|1日あたり|日次)\s*[約]?\s*[\d,]+\s*(?:件|時間|分)', text):
            context=_context(text,match.start(),match.end())
            if re.search(r'削減|短縮|予測|見込|予定|目標|可能|導入後',context):
                continue
            workloads.append({'quote':context,'source_url':url,'attribution_confirmed':attributed,
                              'retrieved_at':item.get('retrieved_at')})
    counts = {item['employee_count'] for item in sizes}
    company_size = ({**sizes[0], 'confirmed':True} if len(counts)==1 and all(item['attribution_confirmed'] for item in sizes) else
                    {'confirmed':False,'employee_count':None,
                     'reason':'資料間で人数が異なる' if len(counts)>1 else '対象企業への帰属未確認' if counts else '全社人数の明示資料なし',
                     'candidates':sizes})
    return {'company_size':company_size,'workload_evidence':workloads}
