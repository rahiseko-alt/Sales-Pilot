import unittest
import tempfile
from core import SalesAgent
from company_facts import extract_company_facts
from mail_quality import prospect_scale


class CompanyFactsTests(unittest.TestCase):
    def evidence(self,text,url='https://example.com/about'):
        return {'text':text,'url':url,'retrieved_at':'2026-09-29','company_name':'対象企業','company_identity_verified':True}

    def facts(self,items):
        return extract_company_facts(items,'対象企業')

    def test_explicit_company_size_keeps_source_and_quote(self):
        facts=self.facts([self.evidence('従業員数：25名。月間300件の注文')])
        self.assertEqual(facts['company_size']['employee_count'],25)
        self.assertEqual(facts['company_size']['status'],'published_count')
        self.assertIsNone(facts['company_size']['as_of'])
        self.assertEqual(prospect_scale(facts)['status'],'historical_or_undated')
        self.assertEqual(facts['workload_evidence'][0]['quote'],'月間300件の注文')
        self.assertEqual(facts['company_size']['source_url'],'https://example.com/about')

    def test_team_group_and_recruitment_counts_are_not_company_size(self):
        for text in ['部署の従業員数：7名','連結従業員数：500名','採用予定3名、事務7名','工場 従業員数：50名','来年の予定社員数20名']:
            self.assertFalse(self.facts([self.evidence(text)])['company_size']['confirmed'])

    def test_conflicting_sizes_remain_unknown(self):
        facts=self.facts([self.evidence('社員数20名'),self.evidence('社員数40名')])
        self.assertFalse(facts['company_size']['confirmed'])
        self.assertEqual(prospect_scale(facts)['status'],'unknown')

    def test_unattributed_or_estimated_size_is_not_confirmed(self):
        for item in [self.evidence('社員数20名',''),self.evidence('社員数20〜30名')]:
            self.assertFalse(self.facts([item])['company_size']['confirmed'])

    def test_suffix_and_agency_headings_remain_unknown(self):
        for text in ['従業員数500名（連結）','従業員数7名（営業部）','従業員数20名を予定','派遣元の会社概要\n従業員数1500名']:
            self.assertFalse(self.facts([self.evidence(text)])['company_size']['confirmed'])

    def test_company_identity_must_be_verified(self):
        item=self.evidence('社員数30名');item['company_name']='別会社'
        self.assertFalse(self.facts([item])['company_size']['confirmed'])
        item=self.evidence('社員数30名');item.pop('company_identity_verified')
        self.assertFalse(self.facts([item])['company_size']['confirmed'])

    def test_projected_savings_are_not_existing_workload(self):
        facts=self.facts([self.evidence('毎月10時間を削減できる見込み')])
        self.assertEqual(facts['workload_evidence'],[])

    def test_employment_subsets_are_not_total_company_size(self):
        for text in ['正社員数20名、パート30名','契約社員数10名','派遣社員数15名']:
            self.assertFalse(self.facts([self.evidence(text)])['company_size']['confirmed'])

    def test_hypothetical_examples_are_not_company_size(self):
        for text in ['仮に従業員数100名とすると','例：社員数30名のケース','従業員数50名を想定']:
            self.assertFalse(self.facts([self.evidence(text)])['company_size']['confirmed'])

    def test_registered_evidence_survives_without_becoming_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            agent=SalesAgent(directory+'/test.db');agent.configure({'llm_provider':'rules'})
            lead=agent.add({'company':'対象企業','source_text':'求人にExcel集計の記載',
                           'evidence':[self.evidence('社員数25名。月間300件の注文')]})
            result=agent.run(lead['id']);research=result['research']
            self.assertTrue(any(item.get('url')=='https://example.com/about' for item in research['evidence']))
            self.assertFalse(research['company_size']['confirmed'])
            self.assertEqual(research['workload_evidence'][0]['quote'],'月間300件の注文')
            self.assertFalse(research['workload_evidence'][0]['attribution_confirmed'])

    def test_i_and_you_legal_entity_row_without_other_company_counts(self):
        text=('従業員数 株式会社 アシスト物流サービス 40名 '
              '株式会社 アイアンドユー 10名 株式会社 アイルサービス 60名 '
              '株式会社 ドリームサービス 15名')
        item={'url':'https://www.asisuto-b.co.jp/profile/','text':text,
              'retrieved_at':'2026-09-29T07:46:43Z','company_name':'株式会社アイアンドユー',
              'company_identity_verified':True}
        size=extract_company_facts([item],'株式会社アイアンドユー')['company_size']
        self.assertTrue(size['confirmed']);self.assertEqual(size['employee_count'],10)
        self.assertEqual(size['scope'],'named_legal_entity');self.assertIsNone(size['as_of'])
        self.assertEqual(size['status'],'published_count')
        self.assertIn('アイアンドユー 10名',size['quote'])
        self.assertNotIn('40名',size['quote']);self.assertNotIn('60名',size['quote'])

    def test_other_legal_entity_rows_are_not_attributed(self):
        item=self.evidence('従業員数 株式会社 アシスト物流サービス 40名 株式会社 アイルサービス 60名')
        self.assertFalse(self.facts([item])['company_size']['confirmed'])

    def test_myfarm_published_count_and_month_end_date(self):
        item={'url':'https://hrmos.co/pages/myfarm/jobs/d0017',
              'text':'従業員数 226名（うちアルバイト139名）※2026年8月末時点',
              'retrieved_at':'2026-09-29','company_name':'株式会社マイファーム',
              'company_identity_verified':True}
        size=extract_company_facts([item],'株式会社マイファーム')['company_size']
        self.assertTrue(size['confirmed']);self.assertEqual(size['employee_count'],226)
        self.assertEqual(size['scope'],'company');self.assertEqual(size['as_of'],'2026-08')

    def test_asterisk_group_count_stays_unconfirmed_with_scope_and_date(self):
        item={'url':'https://www.asx.co.jp/corporate/data/',
              'text':'従業員 110名（海外子会社含む、2025年8月31日現在）',
              'retrieved_at':'2026-09-29','company_name':'株式会社アスタリスク',
              'company_identity_verified':True}
        size=extract_company_facts([item],'株式会社アスタリスク')['company_size']
        self.assertFalse(size['confirmed']);self.assertIsNone(size['employee_count'])
        self.assertEqual(size['scope'],'includes_overseas_subsidiaries')
        self.assertEqual(size['candidates'][0]['employee_count'],110)
        self.assertEqual(size['candidates'][0]['as_of'],'2025-08-31')

    def test_old_published_count_not_treated_as_current_scale(self):
        size=self.facts([self.evidence('従業員数20名（2018年4月1日現在）')])['company_size']
        self.assertTrue(size['confirmed']);self.assertEqual(size['as_of'],'2018-04-01')
        self.assertEqual(prospect_scale({'company_size':size})['status'],'historical_or_undated')


if __name__=='__main__':unittest.main()
