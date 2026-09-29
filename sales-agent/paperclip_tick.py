"""Paperclip process adapter entry: run one persistent sales work cycle."""
import json
import os
import urllib.request

base = os.environ.get('SALES_AGENT_URL', 'http://127.0.0.1:8765').rstrip('/')
request = urllib.request.Request(base + '/api/tick', data=b'{}', headers={'Content-Type': 'application/json'}, method='POST')
with urllib.request.urlopen(request, timeout=120) as response:
    print(json.dumps(json.load(response), ensure_ascii=False))
