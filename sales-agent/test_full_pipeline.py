import os
import tempfile
import unittest
from unittest.mock import patch
from core import SalesAgent
from mail_quality import reference_case

class FullPipelineTests(unittest.TestCase):
    def test_discovery_to_initial_mail_and_ai_reply_then_handoff(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'SALES_ALLOW_LIVE_SEND':'yes','AGENTMAIL_API_KEY':'test','AGENTMAIL_INBOX_ID':'agent@example.com'}):
            agent=SalesAgent(directory+'/test.db')
            agent.configure({'paused':False,'dry_run':False,'auto_send':True,'reply_only':False,'allowed_recipients':['owner@example.com'],'ai_replies':True,'feed_urls':['https://example.com/jobs.xml'],'source_company_names':{'https://example.com/company':'検証企業'}})
            candidate={'company_name':'検証企業','contact_email':'owner@example.com','source_url':'https://example.com/company','source_text':'求人:注文をExcelへ転記して集計する事務担当者'}
            proposal={'hypothesis':'転記に手間がかかる可能性','improvement':'フォーム入力から自動集計','tools':['フォーム'],'effect':'転記負担軽減を実測する','questions':['入力件数は？']}
            sends=[]
            reference=reference_case({'source_text':candidate['source_text']})
            initial_email={'subject':'Excelの集計改善について','body':'御社の求人を拝見し、採用への応募ではなくExcelの集計改善をご提案します。\n'+reference['reference_sentence']+'\n手順案をお送りしてもよろしいでしょうか。\n小齊平 恒平'}
            def mail(path,payload=None):
                sends.append((path,payload))
                return {'message_id':'sent'+str(len(sends)),'thread_id':'thread1'}
            with patch('claude_provider.generate_initial_email',return_value=initial_email),patch('claude_provider.review_email',return_value={'approved':True,'issues':[],'reason':'根拠整合'}),patch('discovery.discover',return_value=[candidate]),patch('discovery.research_company',return_value={'url':candidate['source_url'],'text':candidate['source_text'],'title':'求人'}),patch.object(agent,'llm',return_value=proposal),patch.object(agent,'sync',return_value=0),patch.object(agent,'mail_request',side_effect=mail):
                initial=agent.tick()
                self.assertEqual(len(initial['processed']),1)
                self.assertEqual(len(initial['sent']),1)
                lead=agent.rows('SELECT id FROM leads')[0]
                self.assertEqual(agent.lead(lead['id'])['status'],'waiting_reply')
                self.assertEqual(sends[0][0],'/messages/send')
                agent.receive(lead['id'],'そのやり方ならうちにも合いそうです','inbound1','thread1')
                with patch('claude_provider.generate_reply',return_value={'action':'reply','reply':'現在の入力件数を教えてください。','reason':'通常の会話'}):
                    reply=agent.tick()
                self.assertEqual(len(reply['sent']),1)
                self.assertEqual(sends[1][0],'/messages/inbound1/reply')
                agent.receive(lead['id'],'担当者と商談したい','inbound2','thread1')
                with patch('claude_provider.generate_reply',return_value={'action':'handoff','reply':'','reason':'商談希望'}):
                    meeting=agent.tick()
                self.assertEqual(meeting['sent'],[])
                self.assertEqual(agent.lead(lead['id'])['status'],'handoff')
                self.assertEqual(len(sends),2)
