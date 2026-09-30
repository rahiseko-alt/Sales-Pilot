import tempfile,json
import unittest
from unittest.mock import patch
from core import SalesAgent


class CompanyProfileSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.agent=SalesAgent(self.directory.name+'/db')
        self.agent.configure({'llm_provider':'rules'})
    def tearDown(self):self.directory.cleanup()
    def source(self,url,text='従業員数25名'):
        return {'url':url,'text':text,'title':'会社概要','retrieved_at':'2026-09-29'}
    def test_config_is_validated_deduplicated_and_persistent(self):
        settings=self.agent.configure({'company_profile_sources':{'対象会社':['https://example.com/about#top','https://example.com/about']}})
        self.assertEqual(settings['company_profile_sources'],{'対象会社':['https://example.com/about']})
        self.assertEqual(SalesAgent(self.agent.path).settings()['company_profile_sources'],settings['company_profile_sources'])
        for invalid in [[],{'対象会社':'https://example.com'},{'':['https://example.com']},{'対象会社':['file:///local']},{'対象会社':['https://user:secret@example.com']},{'対象会社':[42]},{'対象会社':['https://example.com/1','https://example.com/2','https://example.com/3']},{'対象会社':[],' 対象会社 ':[]}]:
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):self.agent.configure({'company_profile_sources':invalid})
    def test_verified_company_profile_is_used_even_without_job_url(self):
        url='https://example.com/about'
        self.agent.configure({'company_profile_sources':{'対象会社':[url]}})
        lead=self.agent.add({'company':'対象会社','source_text':'求人には人数なし'})
        with patch('discovery.research_company',return_value=self.source(url)) as fetch:
            result=self.agent.run(lead['id'])
        fetch.assert_called_once_with(url)
        self.assertTrue(result['research']['company_size']['confirmed'])
        self.assertEqual(result['research']['company_size']['employee_count'],25)
        self.assertNotIn('company_identity_verified',result['research']['evidence'][0])
    def test_profile_failures_do_not_prevent_next_source_or_job_research(self):
        job='https://jobs.example.com/a';failed='https://example.com/unavailable';valid='https://example.com/about'
        self.agent.configure({'company_profile_sources':{'対象会社':[failed,valid]}})
        lead=self.agent.add({'company':'対象会社','website':job})
        def fetch(url):
            if url==failed:raise ValueError('Source unavailable')
            return self.source(url,'入力をExcelへ転記' if url==job else '従業員数25名')
        with patch('discovery.research_company',side_effect=fetch) as research:result=self.agent.run(lead['id'])
        self.assertEqual(research.call_count,3)
        self.assertTrue(result['research']['company_size']['confirmed'])
        self.assertTrue(self.agent.rows("SELECT * FROM events WHERE type='research_error'"))

    def test_profile_failure_event_excludes_query_and_provider_error(self):
        url='https://example.com/about?token=SENTINEL'
        self.agent.configure({'company_profile_sources':{'対象会社':[url]}})
        lead=self.agent.add({'company':'対象会社'})
        with patch('discovery.research_company',side_effect=ValueError('SENTINEL internal text')):
            self.agent.run(lead['id'])
        events=' '.join(row['text'] for row in self.agent.rows("SELECT text FROM events WHERE type='research_error'"))
        self.assertIn('example.com',events)
        self.assertNotIn('SENTINEL',events)
    def test_duplicate_job_and_profile_fetch_once_and_add_attribution(self):
        job='https://example.com/about'
        self.agent.configure({'company_profile_sources':{'対象会社':[job,job+'#fragment']}})
        lead=self.agent.add({'company':'対象会社','website':job})
        with patch('discovery.research_company',return_value=self.source(job)) as fetch:result=self.agent.run(lead['id'])
        self.assertEqual(fetch.call_count,1)
        self.assertTrue(result['research']['company_size']['confirmed'])
    def test_at_most_two_distinct_profile_urls_and_other_companies_ignored(self):
        urls=['https://example.com/'+str(i) for i in range(3)]
        # Runtime cap also protects data imported outside configure validation.
        with self.agent.db() as connection:connection.execute("UPDATE settings SET value=? WHERE key='company_profile_sources'",(json.dumps({'対象会社':urls,'別会社':['https://other.example.com/about']}),))
        lead=self.agent.add({'company':'対象会社'})
        with patch('discovery.research_company',side_effect=lambda url:self.source(url)) as fetch:self.agent.run(lead['id'])
        self.assertEqual([call.args[0] for call in fetch.call_args_list],urls[:2])
    def test_redirect_to_unregistered_url_does_not_confirm_identity(self):
        requested='https://example.com/about';redirected='https://unrelated.example.org/about'
        self.agent.configure({'company_profile_sources':{'対象会社':[requested]}})
        lead=self.agent.add({'company':'対象会社'})
        with patch('discovery.research_company',return_value=self.source(redirected)):result=self.agent.run(lead['id'])
        self.assertFalse(result['research']['company_size']['confirmed'])
        self.assertNotIn('company_identity_verified',result['research']['evidence'][0])
    def test_group_size_remains_unknown_even_on_verified_profile(self):
        url='https://example.com/about'
        self.agent.configure({'company_profile_sources':{'対象会社':[url]}})
        lead=self.agent.add({'company':'対象会社'})
        with patch('discovery.research_company',return_value=self.source(url,'従業員数110名（海外子会社含む）')):result=self.agent.run(lead['id'])
        self.assertFalse(result['research']['company_size']['confirmed'])


if __name__=='__main__':unittest.main()
