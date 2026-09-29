import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from unittest.mock import patch
import server
from core import SalesAgent


class HTTPTests(unittest.TestCase):
    def test_dashboard_workflow_and_cross_origin_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = SalesAgent(Path(directory) / 'test.sqlite3')
            agent.configure({'llm_provider': 'rules', 'ai_replies': False})
            with patch.object(server, 'agent', agent), patch.object(agent, 'llm', return_value=None):
                http = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
                thread = threading.Thread(target=http.serve_forever, daemon=True)
                thread.start()
                base = 'http://127.0.0.1:' + str(http.server_port)
                def request(path, body=None, headers=None):
                    req = Request(base + path, None if body is None else json.dumps(body).encode(), headers or {'Content-Type': 'application/json'})
                    with urlopen(req, timeout=5) as response:
                        return response.read()
                try:
                    self.assertIn('営業'.encode(), request('/'))
                    lead = json.loads(request('/api/leads', {'company':'検証企業','email':'test@example.invalid','source_text':'Excelの転記と月次集計'}))
                    request('/api/leads/'+lead['id']+'/run', {})
                    request('/api/settings', {'auto_send':True})
                    request('/api/tick', {})
                    detail = json.loads(request('/api/leads/'+lead['id']))
                    self.assertEqual(detail['lead']['status'], 'waiting_reply')
                    self.assertEqual(detail['messages'][0]['category'], 'simulated')
                    request('/api/leads/'+lead['id']+'/reply', {'text':'詳しい話を聞きたい'})
                    self.assertEqual(json.loads(request('/api/leads/'+lead['id']))['lead']['status'], 'handoff')
                    with self.assertRaises(HTTPError) as error:
                        request('/api/settings', {'dry_run':False}, {'Content-Type':'application/json','Origin':'https://example.com'})
                    self.assertEqual(error.exception.code,403)
                finally:
                    http.shutdown()
                    thread.join(5)
                    http.server_close()


if __name__ == '__main__':
    unittest.main()
