import os
import tempfile
import unittest
from unittest.mock import patch
from core import SalesAgent

class AIReplyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.agent=SalesAgent(self.temp.name+'/test.db')
        self.review=patch('claude_provider.review_email',return_value={'approved':True,'issues':[],'reason':'根拠整合'});self.review.start()
        self.agent.configure({'ai_replies':True,'llm_provider':'claude_code','auto_send':True,'paused':False,'allowed_recipients':['owner@example.com'],'reply_only':True})
        self.lead=self.agent.add({'company':'テスト','email':'owner@example.com'})
        self.agent.update(self.lead['id'],status='waiting_reply',proposal={'improvement':'フォーム集計'},subject='テスト')
    def tearDown(self): self.review.stop();self.temp.cleanup()
    def test_freeform_reply_uses_history_and_worker_sends_once(self):
        self.agent.receive(self.lead['id'],'うちのやり方でも使えるのかな','remote-inbound')
        result={'action':'reply','reply':'現在の入力方法を教えていただけますか？','reason':'一般的な質問'}
        with patch.object(self.agent,'sync',return_value=0),patch('claude_provider.generate_reply',return_value=result) as model:
            first=self.agent.tick(); second=self.agent.tick()
        self.assertEqual(len(first['sent']),1)
        self.assertEqual(second['sent'],[])
        model.assert_called_once()
        self.assertEqual(model.call_args.args[0]['latest_inbound'],'うちのやり方でも使えるのかな')
        self.assertIn('history',model.call_args.args[0])
        self.assertEqual(self.agent.detail(self.lead['id'])['outbox'][0]['text'],result['reply'])
    def test_model_failure_never_sends_template(self):
        self.agent.receive(self.lead['id'],'独自の質問','remote-inbound')
        with patch('claude_provider.generate_reply',side_effect=RuntimeError('timeout')):
            self.agent.process_ai_replies()
        self.assertEqual(self.agent.lead(self.lead['id'])['status'],'handoff')
        self.assertEqual(self.agent.detail(self.lead['id'])['outbox'],[])
    def test_stop_request_never_calls_model(self):
        self.agent.receive(self.lead['id'],'配信停止してください','remote-inbound')
        with patch('claude_provider.generate_reply') as model: self.agent.process_ai_replies()
        model.assert_not_called()
        self.assertEqual(self.agent.lead(self.lead['id'])['status'],'suppressed')
    def test_general_estimate_question_is_judged_by_ai(self):
        self.agent.receive(self.lead['id'],'見積の前に、今はどんな方法を選べますか？','remote-inbound')
        self.assertEqual(self.agent.lead(self.lead['id'])['status'],'ai_pending')
