import os
import tempfile
import unittest
from unittest.mock import patch
from core import SalesAgent

class AutonomyTests(unittest.TestCase):
    def test_tick_receives_replies_and_sends_only_allowed_reply_once(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SALES_ALLOW_LIVE_SEND':'yes','AGENTMAIL_API_KEY':'test','AGENTMAIL_INBOX_ID':'agent@example.com'}):
            agent=SalesAgent(directory+'/test.db')
            agent.configure({'paused':False,'dry_run':False,'auto_send':True,'llm_provider':'rules','reply_only':True,'allowed_recipients':['owner@example.com']})
            owner=agent.add({'company':'本人テスト','email':'owner@example.com','source_text':'Excel入力と月次集計'})
            other=agent.add({'company':'対象外','email':'other@example.com','source_text':'Excel入力と月次集計'})
            calls=[]
            def mail(path,payload=None):
                if payload is not None:
                    calls.append((path,payload))
                    return {'message_id':'reply1','thread_id':'thread1'}
                if path.startswith('/messages?'):
                    return {'messages':[{'message_id':'incoming1','from':'owner@example.com','thread_id':'thread1','labels':['received']}]}
                return {'extracted_text':'具体的には何を自動化できますか？'}
            # An existing researched conversation, as in the real test.
            agent.run(owner['id'])
            with patch.object(agent,'mail_request',side_effect=mail):
                first=agent.tick()
                second=agent.tick()
            self.assertEqual(first['received'],1)
            self.assertEqual(len(first['sent']),1)
            self.assertEqual(second['received'],0)
            self.assertEqual(second['sent'],[])
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0][0],'/messages/incoming1/reply')
            self.assertEqual(agent.lead(owner['id'])['status'],'waiting_reply')
            self.assertEqual(agent.detail(other['id'])['outbox'][0]['status'],'pending')
