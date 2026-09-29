"""Run: python server.py --port 8765 (local-only by default)."""
import argparse, json, mimetypes, os, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from core import SalesAgent

ROOT=Path(__file__).resolve().parent
def load_env():
    file=ROOT/'.env'
    if file.exists():
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1); os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
load_env()
agent=SalesAgent(os.getenv('SALES_DB_PATH'))

class Handler(BaseHTTPRequestHandler):
    def respond(self,code,data):
        body=json.dumps(data,ensure_ascii=False).encode(); self.send_response(code); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=urlparse(self.path).path
        try:
            if path in ('/api/state','/api/status'): return self.respond(200,agent.state())
            if path=='/api/leads': return self.respond(200,agent.state()['leads'])
            if path.startswith('/api/leads/'): return self.respond(200,agent.detail(path.split('/')[3]))
            if path=='/api/health': return self.respond(200,{'ok':True})
            relative='index.html' if path=='/' else path.lstrip('/')
            file=(ROOT/'static'/relative).resolve()
            if not file.is_relative_to((ROOT/'static').resolve()) or not file.is_file(): return self.respond(404,{'error':'見つかりません'})
            body=file.read_bytes(); self.send_response(200); self.send_header('Content-Type',mimetypes.guess_type(str(file))[0] or 'application/octet-stream'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        except ValueError as e: self.respond(404,{'error':str(e)})
        except Exception as e: self.respond(500,{'error':str(e)[:300]})
    def do_POST(self):
        # Local UI only; reject browser cross-origin requests and DNS rebinding.
        host=self.headers.get('Host','').split(':')[0]
        origin=self.headers.get('Origin')
        if host not in ('127.0.0.1','localhost','[::1]') or (origin and urlparse(origin).netloc!=self.headers.get('Host')): return self.respond(403,{'error':'ローカル画面から操作してください'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>1000000: return self.respond(413,{'error':'入力が大きすぎます'})
            data=json.loads(self.rfile.read(size) or '{}'); path=urlparse(self.path).path; parts=path.strip('/').split('/')
            if path=='/api/leads': result=agent.add(data)
            elif path in ('/api/seed','/api/demo'): result=agent.seed()
            elif path in ('/api/tick','/api/run'): result=agent.tick(force=True)
            elif path=='/api/settings': result=agent.configure(data)
            elif path=='/api/discover': result=agent.discover(data)
            elif len(parts)==4 and parts[:2]==['api','leads']:
                id,action=parts[2:]
                if action=='run': result=agent.run(id)
                elif action=='reply': result=agent.receive(id,data.get('text',''))
                elif action=='handoff': result=agent.handoff(id,data.get('reason','担当者への引継ぎ'))
                else: return self.respond(404,{'error':'操作が見つかりません'})
            elif len(parts)==4 and parts[:2]==['api','outbox'] and parts[3]=='approve': result=agent.approve(parts[2])
            else: return self.respond(404,{'error':'操作が見つかりません'})
            self.respond(200,result)
        except (ValueError,TypeError,KeyError) as e: self.respond(400,{'error':str(e)[:300]})
        except Exception as e: self.respond(500,{'error':str(e)[:300]})
    def log_message(self,fmt,*args): pass

def worker(stop):
    while not stop.wait(30):
        try: agent.tick()
        except Exception as e: agent.event('','worker_error',str(e)[:200])

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8765); args=parser.parse_args()
    stop=threading.Event(); threading.Thread(target=worker,args=(stop,),daemon=True).start()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'営業担当 AI: http://127.0.0.1:{args.port} (dry run default)',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set(); server.server_close()
if __name__=='__main__': main()
