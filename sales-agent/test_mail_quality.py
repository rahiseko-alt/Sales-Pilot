import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core import SalesAgent
from mail_quality import check_email,load_policy,reference_case,prospect_scale


class MailQualityTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.agent=SalesAgent(self.directory.name+'/db')
        self.agent.configure({'llm_provider':'claude_code','ai_replies':True,'auto_send':True})
        self.lead=self.agent.add({'company':'検証会社','email':'owner@example.com','source_text':'求人にExcel集計の記載'})
        self.agent.update(self.lead['id'],status='waiting_reply',subject='Excel改善',proposal={'improvement':'Excelを活かす'},research={'evidence':[{'url':'https://example.com/job','text':'Excel集計','retrieved_at':'2026-09-29'}]})
        self.pass_review={'approved':True,'issues':[],'reason':'資料と質問に整合'}
    def tearDown(self):self.directory.cleanup()

    def test_repair_once_then_only_repaired_reply_is_sent(self):
        self.agent.receive(self.lead['id'],'具体的な工程を知りたい','in1')
        drafts=[{'action':'reply','reply':'**フォーム**で転記します。','reason':'通常質問'},
                {'action':'reply','reply':'既存Excelを活かし、入力済みの表を集計表へまとめる流れをご提案できます。','reason':'記法を修正'}]
        with patch('claude_provider.generate_reply',side_effect=drafts) as model,patch('claude_provider.review_email',return_value=self.pass_review) as reviewer:
            self.agent.process_ai_replies();self.agent.flush();self.agent.flush()
        self.assertEqual(model.call_count,2)
        self.assertIn('quality_feedback',model.call_args.args[0])
        self.assertEqual(reviewer.call_count,1)
        outbound=self.agent.rows("SELECT text FROM messages WHERE direction='outbound'")
        self.assertEqual(len(outbound),1);self.assertNotIn('**',outbound[0]['text'])
        self.assertTrue(self.agent.rows('SELECT before_text,after_text FROM quality_reviews WHERE before_text!=after_text'))

    def test_semantic_source_mismatch_gets_one_correction_then_handoff(self):
        self.agent.receive(self.lead['id'],'今のままのExcelでできますか','in1')
        bad={'action':'reply','reply':'御社は入力ミスに困っているので新システムへ全面移行しましょう。','reason':'通常質問'}
        review={'approved':False,'issues':['求人に入力ミスや困っているという事実はない','既存運用の希望に答えていない'],'reason':'根拠不整合'}
        with patch('claude_provider.generate_reply',return_value=bad) as model,patch('claude_provider.review_email',return_value=review) as reviewer,patch.object(self.agent,'mail_request') as mail:
            self.agent.process_ai_replies();self.agent.flush()
        self.assertEqual(model.call_count,2);self.assertEqual(reviewer.call_count,2)
        self.assertEqual(self.agent.lead(self.lead['id'])['status'],'handoff');mail.assert_not_called()
        self.assertEqual(self.agent.rows('SELECT * FROM outbox'),[])

    def test_final_send_gate_rechecks_after_policy_update(self):
        self.agent.configure({'llm_provider':'rules'})
        self.agent.queue(self.lead['id'],'テスト','**内部設定**になっています。','initial')
        with patch.object(self.agent,'rules_initial_email',return_value={'subject':'修正案','body':'**不合格**'}),patch.object(self.agent,'mail_request') as mail:
            self.assertEqual(self.agent.flush(),[])
        mail.assert_not_called();self.assertEqual(self.agent.lead(self.lead['id'])['status'],'handoff')
        self.assertEqual(self.agent.rows('SELECT status FROM outbox')[0]['status'],'cancelled')

    def test_incremental_audit_is_deduped_and_never_requeues_sent_mail(self):
        with self.agent.db() as c:c.execute('INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)',('m1',self.lead['id'],'outbound','**過去の送信文**','sent','r1','t1','2026-09-29'))
        first=self.agent.audit_mail_quality();second=self.agent.audit_mail_quality()
        self.assertEqual(first,{'audited':1,'flagged':1});self.assertEqual(second,{'audited':0,'flagged':0})
        self.assertEqual(len(self.agent.rows('SELECT * FROM mail_quality_audits')),1)
        self.assertEqual(self.agent.rows('SELECT * FROM outbox'),[])

    def test_policy_reload_applies_without_restart(self):
        file=Path(self.directory.name)/'policy.json';policy=load_policy();policy['limits']['reply_max_chars']=2
        file.write_text(json.dumps(policy),encoding='utf-8')
        with patch('mail_quality.POLICY_PATH',file):self.assertTrue(check_email('3文字の本文'))
        policy['limits']['reply_max_chars']=100;file.write_text(json.dumps(policy),encoding='utf-8')
        with patch('mail_quality.POLICY_PATH',file):self.assertEqual(check_email('3文字の本文'),[])

    def test_unconfigured_price_and_internal_analysis_are_detected(self):
        self.assertTrue(check_email('料金は3万円です。',context={'pricing':'確認後に見積'}))
        self.assertTrue(check_email('と仮説を立てる。小齊平氏のサービス範囲。',kind='initial'))
        self.assertEqual(check_email('ご予算1万円以内という希望を踏まえ、対応範囲を確認します。',context={'pricing':'確認後に見積'}),[])

    def test_initial_template_never_pastes_long_internal_proposal(self):
        self.agent.configure({'llm_provider':'rules'})
        proposal={'hypothesis':'30〜40代女性7名と仮説を立てる'*100,'improvement':'Step1 Step2 Step3'*100}
        email=self.agent.rules_initial_email(self.agent.lead(self.lead['id']),proposal,[])
        self.assertLess(len(email['body']),500);self.assertNotIn('仮説を立てる',email['body']);self.assertNotIn('女性',email['body'])

    def test_ai_notice_and_note_link_are_rejected(self):
        self.assertTrue(check_email('このメールはAIが作成しています。'))
        self.assertTrue(check_email('詳細は https://note.com/example へ。'))
        self.assertEqual(check_email('AIによる集計の改善をご提案します。'),[])

    def test_initial_requires_sourced_comparable_metric(self):
        case=reference_case({'source_text':'Excelで出荷資料を集計'})
        self.assertIsNotNone(case)
        self.assertTrue(check_email('Excelの改善をご提案します。',kind='initial',context={'reference_case':case}))
        self.assertEqual(check_email(case['reference_sentence'],kind='initial',context={'reference_case':case}),[])
        self.assertTrue(check_email('参考事例では年間900時間削減しました。',kind='initial',context={'reference_case':case}))

    def test_unrelated_case_is_not_selected(self):
        self.assertIsNone(reference_case({'source_text':'電話での予約受付'}))
        self.assertIsNone(reference_case({'source_text':'Excel入力'}))

    def test_small_and_unknown_size_do_not_select_large_annual_total(self):
        for size in ({}, {'employee_count':20,'confirmed':True,'source_url':'https://example.com/about'}):
            research={'source_text':'Excelの売上集計と出荷帳票','company_size':size}
            selected=reference_case(research)
            self.assertEqual(selected['id'],'jimukaru_monthly_report')
            self.assertNotIn('900',selected['metric_text'])
            self.assertTrue(check_email(selected['reference_sentence']+'年間約900時間',kind='initial',context={'research':research,'reference_case':selected}))

    def test_department_count_and_unconfirmed_count_are_not_company_size(self):
        self.assertEqual(prospect_scale({'source_text':'部門7名','company_size':{'employee_count':500}})['status'],'unknown')
        self.assertEqual(prospect_scale({'company_size':{'employee_count':20,'confirmed':True,'source_url':'https://example.com/about'}})['status'],'historical_or_undated')

    def test_old_undated_and_group_size_never_enable_large_case(self):
        base={'source_text':'Excelの売上集計と出荷帳票','workload_scope':'multi_system'}
        for as_of,scope in [('2010-01-01','company'),(None,'company'),('2026-09-01','includes_overseas_subsidiaries')]:
            research={**base,'company_size':{'employee_count':500,'confirmed':True,'source_url':'https://example.com/about','as_of':as_of,'scope':scope}}
            self.assertNotEqual(prospect_scale(research)['status'],'confirmed')
            selected=reference_case(research)
            self.assertNotEqual(selected['id'] if selected else None,'suzuyo_excel_sales')

    def test_recent_dated_company_count_can_enable_large_case_only_with_workload(self):
        from datetime import datetime, timezone, timedelta
        as_of=datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d')
        size={'employee_count':500,'confirmed':True,'source_url':'https://example.com/about',
              'as_of':as_of,'scope':'company'}
        base={'source_text':'Excelの売上集計と出荷帳票','company_size':size}
        self.assertEqual(prospect_scale(base)['status'],'confirmed')
        self.assertNotEqual(reference_case(base)['id'],'suzuyo_excel_sales')
        selected=reference_case({**base,'workload_scope':'multi_system'})
        self.assertEqual(selected['id'],'suzuyo_excel_sales')

    def test_initial_opens_with_purpose_and_uses_reference(self):
        lead=self.agent.lead(self.lead['id'])
        email=self.agent.rules_initial_email(lead,{},[])
        paragraphs=email['body'].split('\n\n')
        self.assertTrue(paragraphs[1].startswith('御社の求人を拝見し'))
        self.assertIn('採用への応募ではなく',paragraphs[1])
        self.assertIn('参考',email['body'])
        self.assertNotIn('note.com',email['body'])
        self.assertNotIn('AIが作成',email['body'])


if __name__=='__main__':unittest.main()
