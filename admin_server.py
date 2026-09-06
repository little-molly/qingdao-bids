#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""青岛招标监控 · 接收人/关键词管理后台（零依赖，标准库实现）
  - 登录鉴权（SHA256+盐，会话 token 7 天）
  - 接收人增删查、单条测试推送（Bark / ntfy / 企业微信） -> receivers.json
  - 监控关键词增删（即时保存） -> keywords.json（日报脚本运行时读取）
监听 0.0.0.0:8787，systemd 常驻。
"""
import json, os, sys, hashlib, hmac, secrets, time, re
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
from pusher import send_to

ADMIN_PATH = os.path.join(BASE, "admin.json")
RECV_PATH = os.path.join(BASE, "receivers.json")
KW_PATH = os.path.join(BASE, "keywords.json")
PORT = int(os.environ.get("ADMIN_PORT", "8787"))
TOKEN_TTL = 7 * 24 * 3600
TYPES = {"bark": "Bark（iOS）", "ntfy": "ntfy", "wecom": "企业微信"}
MAX_KW = 60

TOKENS = {}

def load_receivers():
    try:
        return json.load(open(RECV_PATH, encoding="utf-8")).get("receivers", [])
    except Exception:
        return []

def save_receivers(rcs):
    json.dump({"receivers": rcs}, open(RECV_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def load_keywords():
    try:
        return json.load(open(KW_PATH, encoding="utf-8")).get("keywords", [])
    except Exception:
        return []

def save_keywords(kws):
    json.dump({"keywords": kws, "updated": time.strftime("%Y-%m-%d %H:%M")},
              open(KW_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def clean_keywords(raw):
    out, seen = [], set()
    for k in raw:
        k = str(k).strip()[:30]
        if k and k not in seen:
            seen.add(k); out.append(k)
        if len(out) >= MAX_KW: break
    return out

def check_pw(pw):
    try:
        a = json.load(open(ADMIN_PATH, encoding="utf-8"))
        h = hashlib.sha256((a["salt"] + (pw or "")).encode("utf-8")).hexdigest()
        return hmac.compare_digest(h, a["password_sha256"])
    except Exception:
        return False

def new_id():
    return "r" + secrets.token_hex(4)

PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>青岛招标监控 · 接收人与关键词管理</title>
<style>
:root{--paper:#FAFAF8;--ink:#1B1E23;--ink2:#5C626B;--line:#E5E3DC;--accent:#1D4ED8;--accent-soft:#EBF0FC;--ok:#166534;--ok-bg:#E8F5EC;--err:#A93030;--err-bg:#FBEAEA;--card:#FFFFFF}
@media (prefers-color-scheme: dark){:root{--paper:#15171B;--ink:#E7E9EC;--ink2:#9BA1AA;--line:#2A2E35;--accent:#84A9F8;--accent-soft:#1C2740;--ok:#7CC98F;--ok-bg:#1B2E20;--err:#E88B8B;--err-bg:#331C1C;--card:#1D2025}}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);font-family:-apple-system,'PingFang SC','Noto Sans SC','Microsoft YaHei',sans-serif;line-height:1.55;min-height:100vh;display:flex;justify-content:center;padding:32px 16px}
.wrap{width:100%;max-width:640px}
.kicker{font-size:12px;letter-spacing:.18em;color:var(--ink2);margin-bottom:6px}
h1{font-size:20px;font-weight:700}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;padding-bottom:16px;border-bottom:2px solid var(--ink);margin-bottom:22px;flex-wrap:wrap;gap:8px}
.topbar .links a{font-size:13px;color:var(--accent);text-decoration:none;margin-left:14px}
.topbar .links a:hover{text-decoration:underline}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:20px;margin-bottom:18px}
.card h3{font-size:14px;margin-bottom:12px}
label{display:block;font-size:12px;color:var(--ink2);margin:10px 0 4px}
input{width:100%;padding:10px 12px;font-size:14px;border:1px solid var(--line);border-radius:8px;background:var(--paper);color:var(--ink);min-height:44px}
input:focus{outline:2px solid var(--accent);outline-offset:-1px}
.types{display:flex;gap:8px;margin:4px 0 2px;flex-wrap:wrap}
.types .pill{flex:1;min-width:96px;text-align:center;padding:9px 0;border:1px solid var(--line);border-radius:8px;font-size:13px;cursor:pointer;color:var(--ink2);user-select:none}
.types .pill.on{border-color:var(--accent);color:var(--accent);background:var(--accent-soft);font-weight:600}
button{padding:10px 16px;font-size:14px;border-radius:8px;border:1px solid var(--accent);background:var(--accent);color:#fff;cursor:pointer;min-height:44px;font-weight:600}
button.ghost{background:transparent;color:var(--accent)}
button.small{padding:6px 12px;min-height:32px;font-size:12px;font-weight:500}
button.danger{border-color:var(--err);color:var(--err);background:transparent}
button:hover{filter:brightness(1.08)} button:active{transform:translateY(1px)}
.row{display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.row input{flex:1;min-width:180px}
.hint{font-size:12px;color:var(--ink2);margin-top:6px}
.rcv{padding:14px 0;border-bottom:1px solid var(--line)}
.rcv:last-child{border-bottom:none}
.rcv .name{font-weight:600;font-size:14px}
.badge{font-size:11px;padding:3px 8px;border-radius:4px;background:var(--accent-soft);color:var(--accent);font-weight:600;margin-left:6px}
.rcv .target{font-size:12px;color:var(--ink2);font-family:ui-monospace,Menlo,monospace;word-break:break-all;margin:4px 0 8px}
.rcv .ops{display:flex;gap:8px;flex-wrap:wrap}
.msg{padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:14px;display:none}
.msg.ok{display:block;background:var(--ok-bg);color:var(--ok)}
.msg.err{display:block;background:var(--err-bg);color:var(--err)}
.empty{padding:22px 0;text-align:center;color:var(--ink2);font-size:14px}
.err-inline{color:var(--err);font-size:12px;margin-top:4px;display:none}
.kwbox{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:4px}
.kwchip{display:inline-flex;align-items:center;gap:6px;font-size:13px;padding:6px 10px;border-radius:999px;background:var(--accent-soft);color:var(--accent);font-weight:600}
.kwchip button{background:transparent;border:none;color:inherit;font-size:13px;padding:0;min-height:0;font-weight:700;line-height:1}
.kwchip button:hover{color:var(--err)}
</style>
</head>
<body>
<div class="wrap">
  <div class="topbar">
    <div><div class="kicker">青岛招标商机监控</div><h1>接收人与关键词管理</h1></div>
    <div class="links"><a href="https://little-molly.github.io/qingdao-bids/" target="_blank" rel="noopener">最新日报</a><a href="#" id="logout">退出</a></div>
  </div>
  <div id="msg" class="msg"></div>
  <div id="loginView" class="card" style="max-width:360px;margin:60px auto 0">
    <h3>管理员登录</h3>
    <label for="pw">管理密码</label>
    <input type="password" id="pw" autocomplete="current-password">
    <div class="err-inline" id="loginErr">密码错误</div>
    <div style="margin-top:14px"><button style="width:100%" id="loginBtn">登录</button></div>
  </div>
  <div id="adminView" style="display:none">
    <div class="card">
      <h3>添加接收人</h3>
      <label for="rname">名称（如：老板手机）</label>
      <input id="rname" placeholder="接收人名称">
      <label>推送方式</label>
      <div class="types">
        <div class="pill on" data-t="bark">Bark（iOS）</div>
        <div class="pill" data-t="ntfy">ntfy</div>
        <div class="pill" data-t="wecom">企业微信</div>
      </div>
      <label for="rtarget">推送地址</label>
      <input id="rtarget" placeholder="https://api.day.app/你的key">
      <div class="hint" id="targetHint">Bark 填 App 里的示例地址到 key 为止，如 https://api.day.app/AbC123</div>
      <div style="margin-top:14px"><button id="addBtn" style="width:100%">添加接收人</button></div>
    </div>
    <div class="card">
      <h3>接收人列表</h3>
      <div id="rcvList"><div class="empty">加载中...</div></div>
      <div class="hint">日报每天 08:00 会推送给列表中的全部接收人。改动即时生效，无需重启。</div>
    </div>
    <div class="card">
      <h3>监控关键词</h3>
      <div class="kwbox" id="kwBox"><div class="empty">加载中...</div></div>
      <div class="row" style="margin-top:10px">
        <input id="kwInput" placeholder="输入新关键词，如：充电桩">
        <button class="ghost" id="kwAdd" style="min-width:96px">添加</button>
      </div>
      <div class="hint">标题命中任一关键词即收录进日报。增删即时保存，下一次运行（每天 08:00）生效。当前 <span id="kwCount">-</span> 个。</div>
    </div>
  </div>
</div>
<script>
var curType = "bark";
var HINTS = {
  bark: "Bark 填 App 里的示例地址到 key 为止，如 https://api.day.app/AbC123",
  ntfy: "ntfy 填订阅主题地址，如 https://ntfy.sh/qd-bid-x7k9",
  wecom: "企业微信群机器人 Webhook 完整地址（key=... 结尾）"
};
function $(id){ return document.getElementById(id); }
function esc(s){ var d = document.createElement("div"); d.textContent = s == null ? "" : s; return d.innerHTML; }
function showMsg(text, ok){
  var m = $("msg"); m.textContent = text; m.className = "msg " + (ok ? "ok" : "err");
  setTimeout(function(){ m.className = "msg"; }, 5000);
}
async function api(path, opts){
  var o = opts || {};
  o.headers = {"Content-Type": "application/json"};
  o.credentials = "same-origin";
  if (o.body && typeof o.body !== "string") o.body = JSON.stringify(o.body);
  var r = await fetch(path, o);
  if (r.status === 401) { showLogin(); throw new Error("未登录"); }
  return r.json();
}
async function loadList(){
  var d = await api("/api/receivers");
  var list = $("rcvList"); list.innerHTML = "";
  if (!d.receivers.length){ list.innerHTML = '<div class="empty">还没有接收人，用上方表单添加第一个。</div>'; return; }
  d.receivers.forEach(function(r){
    var div = document.createElement("div"); div.className = "rcv";
    div.innerHTML = '<div class="name">' + esc(r.name) + '<span class="badge">' + esc(r.type) + '</span></div>'
      + '<div class="target">' + esc(r.target) + '</div>'
      + '<div class="ops"><button class="small ghost" data-test="' + r.id + '">测试推送</button>'
      + '<button class="small danger" data-del="' + r.id + '">删除</button></div>';
    list.appendChild(div);
  });
  list.querySelectorAll("[data-test]").forEach(function(b){
    b.onclick = async function(){
      b.textContent = "推送中..."; b.disabled = true;
      try {
        var r = await api("/api/test", {method:"POST", body:{id: b.getAttribute("data-test")}});
        showMsg(r.ok ? ("✓ 已向「" + r.name + "」发送测试推送：" + r.result) : ("✗ 推送失败：" + r.result), r.ok);
      } catch(e) { showMsg("✗ 请求失败", false); }
      b.textContent = "测试推送"; b.disabled = false;
    };
  });
  list.querySelectorAll("[data-del]").forEach(function(b){
    b.onclick = async function(){
      if (!confirm("确定删除该接收人？")) return;
      await api("/api/receivers/delete", {method:"POST", body:{id: b.getAttribute("data-del")}});
      showMsg("已删除", true); loadList();
    };
  });
}
async function loadKeywords(){
  var d = await api("/api/keywords");
  var box = $("kwBox"); box.innerHTML = "";
  $("kwCount").textContent = d.keywords.length;
  if (!d.keywords.length){ box.innerHTML = '<div class="empty">还没有关键词，添加后开始监控。</div>'; return; }
  d.keywords.forEach(function(k){
    var chip = document.createElement("span"); chip.className = "kwchip";
    chip.innerHTML = esc(k) + ' <button type="button" data-kw="' + esc(k) + '" title="删除">×</button>';
    box.appendChild(chip);
  });
  box.querySelectorAll("[data-kw]").forEach(function(b){
    b.onclick = async function(){
      var kws = d.keywords.filter(function(k){ return k !== b.getAttribute("data-kw"); });
      var r = await api("/api/keywords", {method:"POST", body:{keywords: kws}});
      showMsg(r.ok ? ("已删除，现剩 " + r.count + " 个关键词") : ("✗ " + (r.error || "保存失败")), !!r.ok);
      if (r.ok) loadKeywords();
    };
  });
}
async function saveKeywords(kws){
  var r = await api("/api/keywords", {method:"POST", body:{keywords: kws}});
  if (r.ok){ showMsg("已保存，现共 " + r.count + " 个关键词（下次运行生效）", true); loadKeywords(); }
  else showMsg("✗ " + (r.error || "保存失败"), false);
}
$("kwAdd").onclick = async function(){
  var v = $("kwInput").value.trim();
  if (!v){ showMsg("请输入关键词", false); return; }
  var d = await api("/api/keywords");
  var kws = d.keywords.slice();
  if (kws.indexOf(v) > -1){ showMsg("关键词已存在", false); return; }
  kws.push(v);
  $("kwInput").value = "";
  saveKeywords(kws);
};
$("kwInput").addEventListener("keydown", function(e){ if (e.key === "Enter") $("kwAdd").click(); });
function showLogin(){ $("loginView").style.display = "block"; $("adminView").style.display = "none"; }
function showAdmin(){ $("loginView").style.display = "none"; $("adminView").style.display = "block"; loadList(); loadKeywords(); }
document.querySelectorAll(".types .pill").forEach(function(p){
  p.onclick = function(){
    document.querySelectorAll(".types .pill").forEach(function(x){ x.classList.remove("on"); });
    p.classList.add("on"); curType = p.getAttribute("data-t");
    $("targetHint").textContent = HINTS[curType];
    $("rtarget").placeholder = curType === "bark" ? "https://api.day.app/你的key" : (curType === "ntfy" ? "https://ntfy.sh/你的topic" : "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=***");
  };
});
$("loginBtn").onclick = async function(){
  var r = await fetch("/api/login", {method:"POST", headers:{"Content-Type":"application/json"}, credentials:"same-origin", body: JSON.stringify({password: $("pw").value})});
  if (r.ok){ showAdmin(); } else { $("loginErr").style.display = "block"; }
};
$("logout").onclick = function(e){ e.preventDefault(); fetch("/api/logout", {method:"POST"}); showLogin(); };
(async function(){
  try {
    var r = await fetch("/api/session", {credentials:"same-origin"});
    if (r.ok) showAdmin(); else showLogin();
  } catch(e){ showLogin(); }
})();
</script>
</body>
</html>
"""

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, obj, cookie=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if cookie:
            self.send_header("Set-Cookie", "qb_token=" + cookie + "; Path=/; Max-Age=" + str(TOKEN_TTL) + "; HttpOnly")
        self.end_headers()
        self.wfile.write(body)

    def _cookie_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            part = part.strip()
            if part.startswith("qb_token="):
                return part.split("=", 1)[1].strip()
        return None

    def _authed(self):
        t = self._cookie_token()
        if t and TOKENS.get(t) and TOKENS[t] > time.time():
            return True
        TOKENS.pop(t, None)
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0: return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/" or p == "/index.html":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif p == "/api/session":
            self._json(200 if self._authed() else 401, {"ok": self._authed()})
        elif p == "/api/receivers":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            self._json(200, {"receivers": load_receivers()})
        elif p == "/api/keywords":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            self._json(200, {"keywords": load_keywords()})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        body = self._body()
        if p == "/api/login":
            if check_pw(body.get("password")):
                t = secrets.token_hex(24)
                TOKENS[t] = time.time() + TOKEN_TTL
                self._json(200, {"ok": True}, cookie=t)
            else:
                self._json(401, {"ok": False, "error": "密码错误"})
        elif p == "/api/logout":
            t = self._cookie_token()
            TOKENS.pop(t, None)
            self._json(200, {"ok": True})
        elif p == "/api/receivers":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            name = (body.get("name") or "").strip()
            typ = (body.get("type") or "").strip().lower()
            target = (body.get("target") or "").strip()
            if not name: return self._json(400, {"error": "名称不能为空"})
            if typ not in TYPES: return self._json(400, {"error": "推送方式无效"})
            if not target.startswith("http"): return self._json(400, {"error": "地址必须是 http(s) 链接"})
            rcs = load_receivers()
            rcs.append({"id": new_id(), "name": name[:40], "type": typ, "target": target[:300],
                        "created": time.strftime("%Y-%m-%d")})
            save_receivers(rcs)
            self._json(200, {"ok": True})
        elif p == "/api/receivers/delete":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            rid = body.get("id")
            rcs = [r for r in load_receivers() if r.get("id") != rid]
            save_receivers(rcs)
            self._json(200, {"ok": True})
        elif p == "/api/keywords":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            raw = body.get("keywords")
            if not isinstance(raw, list): return self._json(400, {"error": "keywords 必须是数组"})
            kws = clean_keywords(raw)
            save_keywords(kws)
            self._json(200, {"ok": True, "count": len(kws), "keywords": kws})
        elif p == "/api/test":
            if not self._authed(): return self._json(401, {"error": "未登录"})
            rid = body.get("id")
            rcv = next((r for r in load_receivers() if r.get("id") == rid), None)
            if not rcv: return self._json(404, {"error": "接收人不存在"})
            title = "青岛招标监控 · 测试推送"
            text = "如果你收到了这条消息，说明「" + rcv.get("name", "") + "」配置正确。完整日报每天早上 8 点推送。"
            pages = "https://little-molly.github.io/qingdao-bids/"
            r = send_to(rcv, title, text, pages)
            self._json(200, {"ok": r["result"] == "ok", "name": r["name"], "result": r["result"]})
        else:
            self._json(404, {"error": "not found"})

class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    srv = Server(("0.0.0.0", PORT), Handler)
    print("管理后台运行中: 0.0.0.0:" + str(PORT), flush=True)
    srv.serve_forever()
