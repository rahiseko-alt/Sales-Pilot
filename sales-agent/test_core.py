import os
import tempfile
import unittest
from unittest.mock import patch
from core import SalesAgent


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'sales.sqlite3')
        self.environment = patch.dict(os.environ, {'OPENAI_API_KEY': '', 'AGENTMAIL_API_KEY': '', 'AGENTMAIL_INBOX_ID': '', 'SALES_ALLOW_LIVE_SEND': ''})
        self.environment.start()
        self.agent = SalesAgent(self.path)
        self.agent.configure({'llm_provider':'rules'})
        self.lead = self.agent.add({'company': '試験株式会社', 'email': 'contact@example.com', 'source_text': 'Excel データ入力と集計'})
        self.id = self.lead['id']

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def draft(self):
        self.agent.run(self.id)
        return self.agent.detail(self.id)['outbox'][0]

    def test_workflow_persists_and_resume_does_not_duplicate(self):
        self.agent.configure({'paused': False, 'auto_send': True})
        self.agent.tick()
        resumed = SalesAgent(self.path)
        self.assertEqual(resumed.lead(self.id)['status'], 'waiting_reply')
        self.assertIn('入力フォーム', resumed.lead(self.id)['proposal']['improvement'])
        resumed.tick()
        self.assertEqual(len(resumed.detail(self.id)['outbox']), 1)
        self.assertEqual(len(resumed.detail(self.id)['messages']), 1)

    def test_unsubscribe_cancels_all_outbox_and_blocks_future_send(self):
        self.draft()
        self.agent.receive(self.id, '料金はいくらですか', 'pricing-1')
        for row in self.agent.detail(self.id)['outbox']:
            self.agent.approve(row['id'])
        self.agent.receive(self.id, '配信停止してください', 'stop-1')
        self.agent.configure({'auto_send': True})
        self.assertEqual(self.agent.flush(), [])
        self.assertEqual(self.agent.lead(self.id)['status'], 'suppressed')
        self.assertTrue(all(row['status'] == 'cancelled' for row in self.agent.detail(self.id)['outbox']))
        self.assertEqual(len(self.agent.rows('SELECT * FROM suppression')), 1)

    def test_same_reply_is_recorded_and_answered_once(self):
        self.draft()
        self.agent.receive(self.id, '料金はいくらですか', 'provider-message-1')
        self.agent.receive(self.id, '料金はいくらですか', 'provider-message-1')
        detail = self.agent.detail(self.id)
        self.assertEqual(len(detail['messages']), 1)
        self.assertEqual(len([x for x in detail['outbox'] if x['reply_to'] == 'provider-message-1']), 1)

    def test_handoff_cancels_outreach_and_stays_under_human_control(self):
        self.draft()
        self.agent.receive(self.id, '詳しい話を聞きたいので商談お願いします', 'meeting-1')
        self.agent.receive(self.id, '料金はいくらですか', 'pricing-2')
        self.agent.configure({'auto_send': True})
        self.assertEqual(self.agent.flush(), [])
        self.assertEqual(self.agent.lead(self.id)['status'], 'handoff')
        self.assertEqual(len(self.agent.detail(self.id)['outbox']), 1)

    def test_uncertain_network_result_never_retries_automatically(self):
        row = self.draft()
        self.agent.approve(row['id'])
        self.agent.configure({'dry_run': False})
        with patch.dict(os.environ, {'SALES_ALLOW_LIVE_SEND': 'yes'}), patch.object(self.agent, 'mail_request', side_effect=TimeoutError('response lost')) as send:
            self.agent.flush()
            self.agent.flush()
            self.assertEqual(send.call_count, 1)
        resumed = SalesAgent(self.path)
        self.assertEqual(resumed.detail(self.id)['outbox'][0]['status'], 'uncertain')
        self.assertEqual(resumed.flush(), [])

    def test_crashed_sending_recovers_to_uncertain(self):
        row = self.draft()
        with self.agent.db() as connection:
            connection.execute("UPDATE outbox SET status='sending' WHERE id=?", (row['id'],))
        resumed = SalesAgent(self.path)
        self.assertEqual(resumed.detail(self.id)['outbox'][0]['status'], 'uncertain')
        self.assertEqual(resumed.flush(), [])

    def test_inbound_reply_preempts_stale_initial_outreach(self):
        self.draft()
        self.agent.receive(self.id, '費用はいくらですか', 'pricing-3')
        self.agent.configure({'auto_send': True})
        self.agent.flush()
        outbound = [x for x in self.agent.detail(self.id)['messages'] if x['direction'] == 'outbound']
        self.assertEqual(len(outbound), 1)
        self.assertIn('ご返信ありがとうございます', outbound[0]['text'])

    def test_details_reply_preempts_stale_initial_outreach(self):
        self.draft()
        self.agent.receive(self.id, '具体的には何ができますか', 'details-1')
        self.agent.configure({'auto_send': True})
        self.agent.flush()
        detail = self.agent.detail(self.id)
        initial = [x for x in detail['outbox'] if x['reply_to'] == 'initial']
        outbound = [x for x in detail['messages'] if x['direction'] == 'outbound']
        self.assertEqual(initial[0]['status'], 'cancelled')
        self.assertEqual(len(outbound), 1)
        self.assertIn('入力フォーム', outbound[0]['text'])


if __name__ == '__main__':
    unittest.main()
