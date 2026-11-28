"""Fixed local-only notification and result relay. Never reads ChatGPT output."""
import json
import re
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.request import Request, build_opener, HTTPRedirectHandler

ID=re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None

def telegram(token, method, body):
    if not re.fullmatch(r"[0-9]{5,16}:[A-Za-z0-9_-]{20,100}",token):
        raise ValueError("Invalid Telegram token")
    if method not in ("getUpdates","sendMessage"):
        raise ValueError("Invalid Telegram method")
    try:
        req=Request("https://api.telegram.org/bot"+token+"/"+method,
            data=json.dumps(body).encode(),headers={"Content-Type":"application/json"},method="POST")
        with build_opener(NoRedirect()).open(req,timeout=12) as r:
            raw=r.read(512*1024+1)
        if len(raw)>512*1024:
            raise ValueError("Too much Telegram data")
        reply=json.loads(raw)
        if reply.get("ok") is not True:
            raise ValueError("Telegram rejected request")
        return reply["result"]
    except (OSError,ValueError,TypeError,KeyError):
        # Do not print an exception URL containing the bot token.
        raise ValueError("Telegram API unavailable or rejected request") from None

def configure_bot(getpass,input_fn=input):
    token=getpass("New Telegram bot token (Enter to skip, hidden): ").strip()
    if not token:
        return None,None
    challenge="/start "+secrets.token_hex(6)
    print("Send this exact message to the new bot in a private chat:",challenge)
    input_fn("Then press Enter here: ")
    updates=telegram(token,"getUpdates",{"limit":100,"timeout":0,"allowed_updates":["message"]})
    ids={u["message"]["chat"]["id"] for u in updates if isinstance(u,dict)
        and u.get("message",{}).get("text")==challenge
        and u["message"].get("chat",{}).get("type")=="private"
        and type(u["message"]["chat"].get("id")) is int
        and u["message"]["chat"]["id"]>0}
    if len(ids)!=1:
        raise ValueError("No unique private chat found. Use a new bot and repeat.")
    chat=ids.pop()
    telegram(token,"sendMessage",{"chat_id":chat,"text":"✅ BTC-Lab: уведомления подключены."})
    return token,chat

class Relay:
    def __init__(self,key,repo,control,new_bytes,encoded,utc,bot_token=None,chat=None):
        self.key,self.repo,self.control=key,repo,control
        self.new_bytes,self.encoded,self.utc=new_bytes,encoded,utc
        self.bot_token,self.chat=bot_token,chat
        self.event=None
        self.lock=threading.Lock()

    def notify(self,event_id,message):
        if not self.bot_token or not ID.fullmatch(event_id):
            return
        # Reserve before delivery; never repeat on an ambiguous network failure.
        path=self.control/"notifications"/(event_id+".json")
        try:
            self.new_bytes(path,self.encoded({"utc":self.utc(),"message":message[:260]}))
        except FileExistsError:
            return
        try:
            telegram(self.bot_token,"sendMessage",{"chat_id":self.chat,"text":message[:260]})
        except ValueError:
            print("Telegram delivery not confirmed:",event_id,flush=True)

    def progress(self,p):
        if p is None:
            return False
        if (not isinstance(p,dict) or set(p)!={"id","kind","text"}
            or not isinstance(p["id"],str) or not ID.fullmatch(p["id"]) or len(p["id"])>55
            or p["kind"] not in ("progress","attention")
            or not isinstance(p["text"],str) or not 1<=len(p["text"])<=200
            or "\n" in p["text"] or "\r" in p["text"]):
            raise ValueError("Invalid progress message")
        prefix="🚨❗ BTC-Lab: " if p["kind"]=="attention" else "🔧 BTC-Lab: "
        self.notify("p-"+p["id"],prefix+p["text"])
        return p["kind"]=="attention"

    def publish(self,job,result):
        jid=job["id"]
        with self.lock:
            if (self.control/"claims"/(jid+".json")).exists():
                return
            if self.event is not None and self.event["id"]!=jid:
                raise ValueError("Previous browser event still pending")
            status=result.get("status","error")
            if status not in ("ok","error","interrupted"):
                status="error"
            self.event={"id":jid,"message":
                "BTC-Lab: локальное задание "+jid+" завершено ("+status+
                "). Прочитай через GitHub "+self.repo+"/results/"+jid+
                ".json, проверь результат и продолжай по ROADMAP.md. "+
                "При необходимости участия владельца создай progress.json с kind=attention."}

    def pending(self):
        with self.lock:
            return self.event is not None

    def request(self,method,path,body):
        alert=None
        with self.lock:
            if method=="GET" and path=="/next":
                return self.event or {}
            if method=="POST" and path=="/claim":
                if set(body)!={"id"} or not self.event or body["id"]!=self.event["id"]:
                    return {"ok":False}
                jid=body["id"]
                self.new_bytes(self.control/"claims"/(jid+".json"),self.encoded({"utc":self.utc()}))
                self.event=None
                return {"ok":True}
            if method=="POST" and path=="/ack":
                jid=body.get("id")
                if (set(body)!={"id","status"} or not isinstance(jid,str) or not ID.fullmatch(jid)
                    or body["status"] not in ("clicked","blocked")
                    or not (self.control/"claims"/(jid+".json")).is_file()):
                    return {"ok":False}
                ack=self.control/"claims"/(jid+".ack.json")
                if not ack.exists():
                    self.new_bytes(ack,self.encoded({"status":body["status"],"utc":self.utc()}))
                    if body["status"]=="blocked":
                        alert="b-"+jid
                answer={"ok":True}
            else:
                answer={"ok":False}
        if alert:
            threading.Thread(target=self.notify,args=(alert,"🚨 BTC-Lab: отправка в чат не подтверждена. Проверь Brave."),daemon=True).start()
        return answer

    def start(self):
        relay=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):
                pass
            def reply(self,status,obj):
                raw=relay.encoded(obj)
                self.send_response(status)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(raw)))
                self.send_header("Cache-Control","no-store")
                self.end_headers()
                self.wfile.write(raw)
            def route(self):
                self.connection.settimeout(4)
                try:
                    if self.headers.get("Host")!="127.0.0.1:18746" or not secrets.compare_digest(
                        self.headers.get("Authorization",""),"Bearer "+relay.key):
                        return self.reply(403,{"ok":False})
                    body={}
                    if self.command=="POST":
                        n=int(self.headers.get("Content-Length","0"))
                        if not 0<n<=2048:
                            return self.reply(400,{"ok":False})
                        body=json.loads(self.rfile.read(n))
                        if not isinstance(body,dict):
                            return self.reply(400,{"ok":False})
                    self.reply(200,relay.request(self.command,self.path,body))
                except (OSError,ValueError,KeyError,TypeError):
                    try:
                        self.reply(400,{"ok":False})
                    except OSError:
                        pass
            do_GET=route
            do_POST=route
        server=HTTPServer(("127.0.0.1",18746),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        return server
