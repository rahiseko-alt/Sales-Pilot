import os
import tempfile
import unittest
from unittest.mock import patch
from core import SalesAgent

class RehearsalTests(unittest.TestCase):
    def test_discovery_assigns_owner_rehearsal_without_changing_contact(self):
        with tempfile.TemporaryDirectory() as directory:
            a=SalesAgent(directory+'/db')
            url='https://example.com/job'
            a.configure({'allowed_recipients':['owner@example.com'],'rehearsal_source_url':url,'rehearsal_recipient':'owner@example.com','source_company_names':{url:'確認済み企業'}})
            with patch('discovery.discover',return_value=[{'company_name':'求人タイトル','source_url':url,'source_text':'Excel集計'}]):leads=a.discover()
            self.assertEqual(leads[0]['company'],'確認済み企業')
            self.assertEqual(leads[0]['email'],'')
            self.assertEqual(a.settings()['delivery_overrides'][leads[0]['id']],'owner@example.com')
    def test_initial_and_reply_are_routed_to_owner_by_thread(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'SALES_ALLOW_LIVE_SEND':'yes','AGENTMAIL_API_KEY':'test','AGENTMAIL_INBOX_ID':'agent@example.com'}):
            a=SalesAgent(directory+'/db')
            real=a.add({'company':'実企業','email':'','source_text':'Excel入力と月次集計'})
            owner=a.add({'company':'本人テスト','email':'owner@example.com'})
            a.configure({'llm_provider':'rules','dry_run':False,'auto_send':True,'ai_replies':True,'reply_only':False,'allowed_recipients':['owner@example.com'],'delivery_overrides':{real['id']:'owner@example.com'}})
            a.run(real['id'])
            sent=[]
            def mail(path,payload=None):
                if payload:
                    sent.append((path,payload));return {'message_id':'sent'+str(len(sent)),'thread_id':'campaign-thread'}
                if path.startswith('/messages?'):return {'messages':[{'message_id':'in1','from':'owner@example.com','thread_id':'campaign-thread','labels':['received']}]}
                return {'extracted_text':'今使っている方法でもできますか'}
            with patch.object(a,'mail_request',side_effect=mail):
                a.flush();a.sync()
                a.configure({'llm_provider':'claude_code'})
                # receive ran in legacy rules mode; explicitly requeue for this branch.
                a.update(real['id'],status='ai_pending')
                with a.db() as c:c.execute("UPDATE messages SET category='ai_pending' WHERE remote_id='in1'")
                with patch('claude_provider.review_email',return_value={'approved':True,'issues':[],'reason':'根拠整合'}),patch('claude_provider.generate_reply',return_value={'action':'reply','reply':'現在の方法を確認して提案します。','reason':'通常の質問'}):
                    a.process_ai_replies();a.flush()
            self.assertEqual(sent[0][1]['to'],['owner@example.com'])
            self.assertIn('実企業には未送信',sent[0][1]['text'])
            self.assertEqual(a.lead(real['id'])['email'],'')
            self.assertEqual(a.detail(owner['id'])['messages'],[])
            self.assertEqual(sent[1][0],'/messages/in1/reply')
