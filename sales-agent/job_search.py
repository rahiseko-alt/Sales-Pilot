"""Find possible company-owned job pages with subscription WebSearch.

Search output is a URL suggestion, never evidence of an employer or contact.
"""
import json
import re
from urllib.parse import urlsplit

from claude_provider import _run, provider_status
from discovery import MAX_SOURCES, discover

SCHEMA = {'type': 'object', 'properties': {'urls': {'type': 'array', 'items': {'type': 'string'}}},
          'required': ['urls'], 'additionalProperties': False}
BLOCKED_HOSTS = (
    'indeed.com', 'wantedly.com', '求人ボックス.com', 'xn--pckua2a7gp15o89zb.com',
    'mamaworks.jp', 'townwork.net', 'baitoru.com', 'en-gage.net', 'doda.jp',
    'mynavi.jp', 'rikunabi.com', 'hellowork.mhlw.go.jp',
)
JOB_WORDS = re.compile(r'求人|採用|募集|職種|仕事内容|応募|recruit|career', re.I)
TASK_WORDS = re.compile(r'Excel|エクセル|データ入力|転記|集計|表計算', re.I)


def search_job_urls():
    if not provider_status().get('ready'):
        raise RuntimeError('Claude サブスクリプション認証が必要です。')
    args = [
        '-p', '--output-format', 'json', '--json-schema', json.dumps(SCHEMA),
        '--tools', 'WebSearch', '--allowedTools', 'WebSearch',
        '--disable-slash-commands', '--no-chrome', '--strict-mcp-config',
        '--mcp-config', '{"mcpServers":{}}', '--setting-sources', '',
        '--settings', '{"disableAllHooks":true}', '--no-session-persistence',
        '--permission-mode', 'dontAsk',
        '--system-prompt', (
            'WebSearchだけを使い、日本国内の企業が自社サイトで公開する求人ページを探す。'
            'Excelへの入力・転記・集計を仕事内容に含む求人に絞る。'
            '求人媒体・検索サイト・SNSのURLは返さない。'
            '会社名や連絡先を推測せず、実際に見つかったURLだけをJSONで返す。'
        ),
    ]
    result = _run(args, '企業公式サイトの該当求人URLを最大3件探してください。', 120)
    if result.returncode:
        raise RuntimeError('Claude WebSearch を完了できませんでした。')
    try:
        envelope = json.loads(result.stdout)
        urls = envelope.get('structured_output', {}).get('urls')
        if envelope.get('is_error') or not isinstance(urls, list):
            raise ValueError('Invalid search output')
    except (ValueError, TypeError, AttributeError) as error:
        raise RuntimeError('求人検索結果を検証できませんでした。') from error
    approved = []
    for url in urls[:10]:
        if not isinstance(url, str) or len(url) > 1500:
            continue
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or '').encode('idna').decode('ascii').lower()
            if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
                continue
            if not host or any(host == blocked or host.endswith('.' + blocked) for blocked in BLOCKED_HOSTS):
                continue
            if url not in approved:
                approved.append(url)
        except (ValueError, UnicodeError):
            continue
    return approved[:3]


def discover_jobs():
    urls = search_job_urls()
    results = discover(company_urls=urls[:MAX_SOURCES])
    leads = [candidate for candidate in results['leads']
             if JOB_WORDS.search(candidate['source_text']) and TASK_WORDS.search(candidate['source_text'])]
    return {'leads': leads, 'errors': results['errors'], 'searched_urls': len(urls)}
