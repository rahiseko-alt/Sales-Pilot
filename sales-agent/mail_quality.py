"""Reloadable editorial policy and conservative, objective pre-send checks."""
import json
import re
from pathlib import Path

POLICY_PATH = Path(__file__).parent / 'sales_quality_policy.json'


def load_policy():
    with POLICY_PATH.open(encoding='utf-8-sig') as file:
        policy = json.load(file)
    if not isinstance(policy, dict) or not isinstance(policy.get('rules'), list):
        raise ValueError('営業メール品質方針を読み込めません。')
    return policy


def policy_prompt():
    return json.dumps(load_policy(), ensure_ascii=False)


def prospect_scale(research):
    size = research.get('company_size', {}) if isinstance(research, dict) else {}
    employees = size.get('employee_count')
    confirmed = size.get('confirmed') is True and bool(size.get('source_url'))
    if not confirmed or isinstance(employees, bool) or not isinstance(employees, int) or employees < 1:
        return {'employee_count':None,'status':'unknown','proposal_scope':'single_task',
                'guidance':'人数・業務量は未確認。担当者一人の一工程を提案し、大規模な年間削減額や全社導入を持ち出さない。'}
    return {'employee_count':employees,'status':'confirmed','source_url':size['source_url'],
            'proposal_scope':'single_task','guidance':'企業人数と対象工程の作業量は別。規模だけで効果や予算を推測しない。'}


def reference_case(research, proposal=None):
    # Match observed work, not a generated promise or unrelated profile text.
    text = json.dumps(research, ensure_ascii=False)
    cases = load_policy().get('reference_cases', [])
    scale = prospect_scale(research)
    # Large multi-system totals need confirmed scale AND an observed matching
    # workload. A department headcount or an unknown company is insufficient.
    large = (scale['status']=='confirmed' and scale['employee_count'] >= 300
             and research.get('workload_scope') == 'multi_system')
    cases = [case for case in cases if case.get('deployment_scale') != 'large' or large]
    matches = [(sum(keyword in text for keyword in case['keywords']), case)
               for case in cases]
    best = max(matches, key=lambda match: match[0], default=(0, None))
    return best[1] if best[0] else None


def check_email(text, kind='reply', context=None, policy=None):
    """Hard fails are objective defects; editorial preferences stay in prompts.

    This is no semantic guarantee. Model instructions and one correction pass
    handle relevance, factuality and tone; uncertainty routes to the owner.
    """
    policy = policy or load_policy()
    context = context or {}
    text = str(text).strip()
    issues = []
    if not text:
        return ['本文が空です']
    maximum = policy.get('limits', {}).get(kind + '_max_chars', 1200)
    if len(text) > maximum:
        issues.append(f'本文が長すぎます（{len(text)}字、上限{maximum}字）')
    if '**' in text or '```' in text or re.search(r'^\s*#{1,6}\s', text, re.M):
        issues.append('プレーンテキストにMarkdown記法が残っています')
    if re.search(r'note\.com', text, re.I):
        issues.append('不要なNoteへの誘導があります')
    if re.search(r'(?:このメール|本メール).{0,12}AI.{0,12}(?:作成|生成|送信)|AI営業担当', text, re.I):
        issues.append('ユーザーが不要と指定したAI注記があります')
    for fragment in ('設定になって', '設定されていません', '権限がない', 'と仮説を立てる', '小齊平氏', '人間の担当者'):
        if fragment in text:
            issues.append('内部事情・内部分析の表現があります: ' + fragment)
    profile = context.get('seller_profile') or {}
    if '弊社' in text and not profile.get('company_name') and not profile.get('business_name'):
        issues.append('確認済みの屋号がないのに弊社と称しています')
    if re.search(r'(必ず|確実に|確約|保証).{0,18}(削減|減ら|短縮|改善)|(削減|短縮).{0,12}(保証|確約)', text):
        if not re.search(r'(保証|確約)(?:しません|できません|はしません)', text):
            issues.append('改善効果を保証する表現があります')
    if re.search(r'\d+\s*[%％].{0,8}(削減|短縮)|(削減|短縮).{0,8}\d+\s*[%％]', text):
        issues.append('実測で確認していない削減率を本文に含めています')
    if kind == 'initial':
        case = context.get('reference_case')
        if not case:
            issues.append('業務に適合する確認済みの類似事例がありません')
        elif case['metric_text'] not in text or case['publisher'] not in text or not any(word in text for word in ('参考', '他社の公開事例')):
            issues.append('出典付きの類似案件の参考数字が欠けています')
        allowed_case = reference_case(context.get('research') or {})
        for registered in policy.get('reference_cases', []):
            if registered.get('deployment_scale') == 'large' and registered['metric_text'] in text and (not allowed_case or allowed_case['id'] != registered['id']):
                issues.append('相手の確認済み規模・業務量に合わない大規模事例を引用しています')
        if re.search(r'\d+[〜～-]\d+代(?:女性|男性)|(?:女性|男性)\d+名|Step\s*[3-9]', text, re.I):
            issues.append('初回に不要な属性情報または多数の手順を列挙しています')
    max_questions = policy.get('limits', {}).get(kind + '_max_questions', 2)
    if text.count('？') + text.count('?') > max_questions:
        issues.append('一度に確認する質問が多すぎます')
    # A concrete advertised price must come from configured pricing, not from
    # the prospect's budget or another historical generated message.
    pricing = str(context.get('pricing') or '')
    amounts = re.findall(r'\d[\d,]*(?:\.\d+)?\s*(?:万円|円|ドル)', text)
    for amount in amounts:
        if amount.replace(' ', '') in pricing.replace(' ', ''):
            continue
        sentences = [sentence for sentence in re.split(r'[。\n]', text) if amount in sentence]
        if any(re.search(r'(?:プラン|コース|料金|費用|価格|見積).{0,12}(?:は|で|から|:|：).*' + re.escape(amount), sentence) and not any(word in sentence for word in ('予算', '未確定', '確定していません', '確認', '見積りします', 'お見積り')) for sentence in sentences):
            issues.append('未設定の料金を提示しています: ' + amount)
    return list(dict.fromkeys(issues))
