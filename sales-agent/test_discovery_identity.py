"""Identity gate for automatically discovered job and company pages."""
import tempfile
import unittest
from unittest.mock import patch

from core import SalesAgent


class DiscoveryIdentityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.agent=SalesAgent(self.directory.name+'/db')
        self.agent.configure({'llm_provider':'rules'})
        self.url='https://jobs.example.com/opening/123'

    def tearDown(self):self.directory.cleanup()

    def candidate(self,url=None):
        url=url or self.url
        return {'company_name':'','candidate_name':'Excel事務スタッフ募集',
                'source_title':'Excel事務スタッフ募集','identity_status':'unverified',
                'source_url':url,'website':'','source_text':'Excel集計を担当',
                'evidence':[{'url':url,'title':'Excel事務スタッフ募集','text':'Excel集計を担当'}],
                'contact_email':''}

    def discover(self,candidates):
        with patch('discovery.discover',return_value=candidates):
            return self.agent.discover()

    def test_unverified_title_is_saved_as_pending_and_cannot_run(self):
        lead=self.discover([self.candidate()])[0]
        self.assertEqual(lead['company'],'募集主未確認')
        self.assertEqual(lead['status'],'identity_pending')
        self.assertEqual(lead['research']['candidate_name'],'Excel事務スタッフ募集')
        self.assertEqual(self.agent.run(lead['id'])['status'],'identity_pending')
        self.assertEqual(self.agent.tick(force=True)['processed'],[])
        self.assertEqual(self.agent.detail(lead['id'])['outbox'],[])

    def test_confirmed_mapping_and_fragment_normalize_to_one_identity(self):
        self.agent.configure({'source_company_names':{self.url+'#job':'株式会社対象'}})
        lead=self.discover([self.candidate()])[0]
        self.assertEqual(lead['company'],'株式会社対象')
        self.assertEqual(lead['status'],'discovered')

    def test_conflicting_normalized_mappings_remain_pending(self):
        self.agent.configure({'source_company_names':{self.url:'株式会社A',self.url+'#x':'株式会社B'}})
        lead=self.discover([self.candidate()])[0]
        self.assertEqual(lead['status'],'identity_pending')
        self.assertTrue(self.agent.rows("SELECT * FROM events WHERE type='identity_conflict'"))

    def test_human_confirmation_persists_mapping_and_unblocks_research(self):
        lead=self.discover([self.candidate()])[0]
        verified=self.agent.verify_company(lead['id'],'株式会社対象')
        self.assertEqual(verified['company'],'株式会社対象')
        self.assertEqual(verified['status'],'discovered')
        self.assertEqual(self.agent.settings()['source_company_names'][self.url],'株式会社対象')
        self.assertEqual(len(self.discover([self.candidate()])),1)
        self.assertEqual(len(self.agent.rows('SELECT id FROM leads')),1)

    def test_other_status_cannot_relabel_company(self):
        lead=self.discover([self.candidate()])[0]
        self.agent.verify_company(lead['id'],'株式会社対象')
        with self.assertRaises(ValueError):self.agent.verify_company(lead['id'],'株式会社別会社')

    def test_discovery_does_not_downgrade_a_manually_named_lead(self):
        manual=self.agent.add({'company':'株式会社手入力','website':self.url,'source_text':'確認済み'})
        repeated=self.discover([self.candidate()])[0]
        self.assertEqual(repeated['id'],manual['id'])
        self.assertEqual(repeated['status'],'discovered')
        self.assertEqual(repeated['company'],'株式会社手入力')

    def test_source_failure_is_recorded_without_leaking_query_or_raw_exception(self):
        result={'leads':[self.candidate()],
                'errors':[{'kind':'feed','host':'jobs.example.com','index':1,
                           'reason':'fetch_failed','url':'https://jobs.example.com/?token=SENTINEL',
                           'error':'SENTINEL secret response'}]}
        with patch('discovery.discover',return_value=result):found=self.agent.discover()
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]['status'],'identity_pending')
        descriptions=' '.join(row['text'] for row in self.agent.rows("SELECT text FROM events WHERE type='discovery_error'"))
        self.assertIn('jobs.example.com',descriptions)
        self.assertNotIn('SENTINEL',descriptions)


if __name__=='__main__':unittest.main()
