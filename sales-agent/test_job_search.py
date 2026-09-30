import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import job_search
from core import SalesAgent


class JobSearchTests(unittest.TestCase):
    def test_only_company_pages_with_job_and_excel_evidence_reach_identity_gate(self):
        urls = [
            'https://example.com/recruit/accounting',
            'https://mamaworks.jp/job/33590',
            'http://example.net/recruit',
            'https://example.org/about',
        ]
        envelope = {'is_error': False, 'structured_output': {'urls': urls}}
        pages = {'leads': [
            {'source_url': urls[0], 'source_title': '事務職採用',
             'source_text': '事務職を募集します。Excelへの入力、転記、集計を担当。'},
            {'source_url': urls[3], 'source_title': '会社概要',
             'source_text': '当社はExcel製品を販売しています。'},
        ], 'errors': []}
        with patch.object(job_search, 'provider_status', return_value={'ready': True}), \
             patch.object(job_search, '_run', return_value=SimpleNamespace(returncode=0, stdout=json.dumps(envelope))), \
             patch.object(job_search, 'discover', return_value=pages) as discovery:
            result = job_search.discover_jobs()
        self.assertEqual(discovery.call_args.kwargs['company_urls'], [urls[0], urls[3]])
        self.assertEqual([lead['source_url'] for lead in result['leads']], [urls[0]])
        with tempfile.TemporaryDirectory() as directory:
            agent = SalesAgent(Path(directory) / 'sales.sqlite3')
            lead = agent.discover(candidates=result)[0]
            self.assertEqual(lead['status'], 'identity_pending')
            self.assertEqual(lead['company'], '募集主未確認')
            self.assertEqual(lead['email'], '')
            self.assertEqual(agent.rows('SELECT * FROM outbox'), [])

    def test_invalid_search_output_fails_closed(self):
        with patch.object(job_search, 'provider_status', return_value={'ready': True}), \
             patch.object(job_search, '_run', return_value=SimpleNamespace(returncode=0, stdout='{}')):
            with self.assertRaises(RuntimeError):
                job_search.search_job_urls()


if __name__ == '__main__':
    unittest.main()
