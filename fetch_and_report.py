#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""青岛招标商机监控 v3.6 - 阿里云服务器版
策略（2026-09-04 实测定型）：
  ccgp  逐词 subject 服务端检索（全历史按时间倒序） -> 本地窗口过滤
  ggzy  无参分页 pageIndex=1..N 拉最新列表（按时间倒序） -> 本地关键词+窗口过滤
  plap  逐词 title 服务端检索（自动翻页直到越过窗口） -> 本地窗口过滤
v3.6：
  - 日报页样式重做：藏蓝+金「政经日报」设计（社徽刊头/吸顶类型筛选/条目卡片/深藏蓝页脚）
  - 军采详情链接补 /freecms 前缀（修复 404）
  - TEST_MODE 测试模式：去时间限制，每源最多 60 条，输出 docs/test.html
  - 多接收人推送（receivers.json）+ 自动重试
"""
import json, os, re, sys, time, ssl, subprocess, datetime as dt
import urllib.parse as up
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
import pusher

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
DEFAULT_KEYWORDS = ["弱电","大屏","监控","LED","智能化","安全防范","安防","电子警察","广播","会议系统","网络安全","服务器","机房","动环","交换机"]

def load_keywords():
    """从 keywords.json 读关键词（管理后台维护）；无文件/异常时用默认 15 词"""
    try:
        kws = json.load(open(os.path.join(BASE, "keywords.json"), encoding="utf-8")).get("keywords", [])
        kws = [str(k).strip() for k in kws if str(k).strip()]
        if kws: return kws
    except Exception:
        pass
    return list(DEFAULT_KEYWORDS)

KEYWORDS = load_keywords()
WINDOW_HOURS = 24 * 7          # 统计窗口：7 天
GGZY_PAGES = 8                 # 公资交易列表分页数（每页约 8-10 条）
PLAP_MAX_PAGES = 3             # 军采逐词检索最多翻页数（每页 20 条）
ISSUE_BASE = dt.date(2026, 9, 4)   # 第一期日期（用于期数推算）
RETENTION_DAYS = 90                # 数据保留期：三个月，超期自动清理（去重记录/历史日报页/历史报告）
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

def log(m): print(m, file=sys.stderr, flush=True)

def fetch(url, data=None, headers=None, timeout=25):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers: h.update(headers)
    with urlopen(Request(url, data=data, headers=h), timeout=timeout, context=CTX) as r:
        raw = r.read()
    for enc in ("utf-8", "gbk"):
        try: return raw.decode(enc)
        except Exception: pass
    return raw.decode("utf-8", errors="replace")

def parse_time(s):
    if not s: return None
    s = str(s).replace("T", " ").strip()
    s = re.sub(r"\.\d+.*$", "", s); s = re.sub(r"(\+0800|\+08:00|Z)$", "", s).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try: return dt.datetime.strptime(s, fmt)
        except ValueError: pass
    return None

def hits(title):
    tl = title.lower(); out = []
    has_cjk = re.compile(r"[\u4e00-\u9fff]")
    for kw in KEYWORDS:
        if has_cjk.search(kw):
            if kw in title: out.append(kw)
        elif kw.lower() in tl:
            out.append(kw)
    return out

def ptype(title):
    for k in ["招标公告","更正公告","成交公告","中标公告","竞标公告","结果公示","废标公示","终止公告"]:
        if k in title: return k
    return "采购公告"

def type_group(t):
    """公告类型 -> 筛选组（与卡片徽章共用）"""
    if "招标" in t or "采购公告" in t: return "zb"
    if "更正" in t: return "gz"
    if "中标" in t or "成交" in t: return "cj"
    if "废标" in t or "流标" in t or "终止" in t: return "fb"
    return "jg"

def fmt_window(h):
    return str(h // 24) + " 天" if h and h % 24 == 0 else str(h) + " 小时"

TEST_MODE = os.environ.get("TEST_MODE") == "1"   # 测试模式：去时间限制，每源最多 60 条，输出 docs/test.html
try:
    from zoneinfo import ZoneInfo
    NOW = dt.datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
except Exception:
    NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)
CUTOFF = NOW - dt.timedelta(hours=(10 * 365 * 24 if TEST_MODE else WINDOW_HOURS))

def fetch_ccgp():
    items, err = [], None
    try:
        for kw in KEYWORDS:
            body = json.dumps({"subject": kw, "page": 1, "limit": 200, "colCode": "0303", "colCodes": None,
                               "sort": "-pdate", "area": None, "areaType": "city", "pdate": None,
                               "pdates": ["", ""], "unitName": None, "projectCode": None, "agentName": None,
                               "pdateType": None, "kindOf": None, "projectType": None}).encode()
            txt = fetch("http://zfcg.qingdao.gov.cn:58060/api/siteservice/free/qd/site-info/page",
                        data=body, headers={"Content-Type": "application/json"})
            for r in json.loads(txt)["data"]["data"]["records"]:
                t = parse_time(r.get("pdate"))
                if not t or t < CUTOFF: continue
                h = hits(r.get("subject") or "")
                if not h: continue
                items.append({"title": r["subject"].strip(),
                              "url": "http://www.ccgp-qingdao.gov.cn/qdsite/#/read?id=" + r["id"],
                              "date": t.strftime("%m-%d %H:%M"), "area": r.get("regionName") or "青岛",
                              "kw": h, "type": ptype(r["subject"])})
            time.sleep(0.5)
        merged = {}
        for it in items:
            k = it["url"]
            if k in merged: merged[k]["kw"] = sorted(set(merged[k]["kw"] + it["kw"]))
            else: merged[k] = it
        items = list(merged.values())
        for it in items: it["kw"] = "+".join(it["kw"])
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if "unreachable" in str(e) or "timed out" in str(e): err += "（疑似网络受限）"
    return items, err

def fetch_ggzy():
    items, err = [], None
    try:
        for pi in range(1, GGZY_PAGES + 1):
            html = fetch(f"https://ggzy.qingdao.gov.cn/Tradeinfo-GGGSList/0-0-0?pageIndex={pi}")
            oldest = None
            for seg in re.findall(r"<tr[\s\S]*?</tr>", html):
                a = re.search(r'<a[^>]+href="(/TradeDetals-ZtbShow/[^"]+)"[^>]*title="([^"]{4,150})"', seg)
                if not a: continue
                d = re.search(r"(20\d\d-\d{2}-\d{2})", seg)
                if not d: continue
                ds = d.group(1); oldest = ds
                if ds < CUTOFF.strftime("%Y-%m-%d"): continue
                h = hits(a.group(2))
                if not h: continue
                items.append({"title": a.group(2).strip(),
                              "url": "https://ggzy.qingdao.gov.cn" + a.group(1),
                              "date": ds[5:], "area": "青岛",
                              "kw": "+".join(h), "type": ptype(a.group(2))})
            if not TEST_MODE and oldest and oldest < CUTOFF.strftime("%Y-%m-%d"): break
            time.sleep(0.8)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if "unreachable" in str(e) or "timed out" in str(e): err += "（疑似网络受限）"
    return items, err

PLAP = "https://www.plap.mil.cn"
def fetch_plap():
    items, err = [], None
    try:
        for kw in KEYWORDS:
            page = 1
            while page <= PLAP_MAX_PAGES:
                url = (PLAP + "/freecms-glht/rest/v1/notice/selectInfoMoreChannel.do"
                       "?siteId=404bb030-5be9-4070-85bd-c94b1473e8de&channel=c5bff13f-21ca-4dac-b158-cb40accd3035"
                       "&currPage=" + str(page) + "&pageSize=20&title=" + quote(kw))
                d = json.loads(fetch(url))
                rows = d.get("data") or []
                if not rows: break
                oldest = None
                for r in rows:
                    t = parse_time(r.get("noticeTime"))
                    if not t: continue
                    if oldest is None or t < oldest: oldest = t
                    if not TEST_MODE and t < CUTOFF: continue
                    region = r.get("regionName") or ""
                    if "山东" not in region and "青岛" not in region: continue
                    h = hits(r.get("title") or "")
                    if not h: continue
                    hp = r.get("htmlpath") or ""
                    if hp.startswith("/site/"): hp = "/freecms" + hp
                    items.append({"title": r["title"].strip(),
                                  "url": PLAP + hp if hp.startswith("/") else hp,
                                  "date": t.strftime("%m-%d %H:%M"), "area": r.get("regionName") or "全国",
                                  "kw": h, "type": ptype(r["title"])})
                if len(rows) < 20 or (oldest and not TEST_MODE and oldest < CUTOFF): break
                page += 1
                time.sleep(0.4)
            time.sleep(0.5)
        merged = {}
        for it in items:
            k = it["url"]
            if k in merged: merged[k]["kw"] = sorted(set(merged[k]["kw"] + it["kw"]))
            else: merged[k] = it
        items = sorted(merged.values(), key=lambda x: x["date"], reverse=True)
        for it in items: it["kw"] = "+".join(it["kw"])
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        if "unreachable" in str(e) or "timed out" in str(e): err += "（疑似网络受限）"
    return items, err

# ---------- 多接收人推送 ----------
def load_receivers():
    try:
        return json.load(open(os.path.join(BASE, "receivers.json"), encoding="utf-8")).get("receivers", [])
    except Exception:
        return []

def push_all(title, body, click_url):
    results = []
    rcs = load_receivers()
    if rcs:
        for r in rcs:
            results.append(pusher.send_to(r, title, body, click_url))
        return results
    bark = os.environ.get("BARK_URL", "").strip().rstrip("/")
    ntfy = os.environ.get("NTFY_URL", "").strip()
    wecom = os.environ.get("WECOM_WEBHOOK", "").strip()
    if bark:
        try: results.append(pusher.send_to({"name": "bark", "type": "bark", "target": bark}, title, body, click_url))
        except Exception as e: results.append({"name": "bark", "result": "fail(" + type(e).__name__ + ")"})
    if ntfy:
        try: results.append(pusher.send_to({"name": "ntfy", "type": "ntfy", "target": ntfy}, title, body, click_url))
        except Exception as e: results.append({"name": "ntfy", "result": "fail(" + type(e).__name__ + ")"})
    if wecom:
        try: results.append(pusher.send_to({"name": "wecom", "type": "wecom", "target": wecom}, title, body))
        except Exception as e: results.append({"name": "wecom", "result": "fail(" + type(e).__name__ + ")"})
    return results

def build_summary(ccgp, ggzy, plap, errs):
    prio = {"招标公告": 0, "采购公告": 1, "更正公告": 2, "中标公告": 3, "成交公告": 4, "结果公示": 5}
    def rank(it):
        local = 0 if ("山东" in it["area"] or "青岛" in it["area"]) else 1
        t = next((v for k, v in prio.items() if k in it["type"]), 9)
        return (local, t)
    allit = sorted(ccgp + ggzy + plap, key=rank)
    lines = []
    for it in allit[:5]:
        tag = "山东/青岛" if rank(it)[0] == 0 else it["area"]
        lines.append("· [" + it["type"] + "·" + tag + "] " + it["title"][:40] + " (" + it["kw"] + ")")
    err_note = "；".join(s + "异常" for s, e in zip(("政采", "公资", "军采"), errs) if e)
    if err_note: lines.insert(0, "⚠️ " + err_note + "（详见报告）")
    return "\n".join(lines) if lines else "近" + fmt_window(WINDOW_HOURS) + "无命中关键词的新公告"

def fmt_window(h):
    return str(h // 24) + " 天" if h and h % 24 == 0 else str(h) + " 小时"

# ---------- 日报 HTML 渲染（GitHub Pages，藏蓝金「政经日报」设计） ----------
import html as _html

def _e(s, q=False):
    return _html.escape(str(s or ""), quote=q)

CSS = """
:root{
  --bg:#f5f2ea; --surface:#fffdf7; --navy:#0d2340; --navy-deep:#0a1c33;
  --fg:#1d2b3a; --muted:#5d6b7c; --border:#e6dfcf; --border-strong:#cfc7b0;
  --gold:#b78f2e; --gold-ink:#7e6019;
  --gold-soft:rgba(183,143,46,.14); --fg-soft:rgba(29,43,58,.06);
  --hairline:rgba(245,242,234,.16);
  --elev:0 2px 10px rgba(29,43,58,.08);
  --font-display:'Iowan Old Style','Palatino','Songti SC','STSongti-SC','SimSun',Georgia,serif;
  --font-body:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei','Segoe UI',system-ui,sans-serif;
  --font-mono:ui-monospace,'SF Mono',Menlo,Consolas,monospace;
  --container:680px; --radius:12px; --ease:cubic-bezier(.2,0,0,1);
}
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font-body);font-size:15px;line-height:1.6;-webkit-font-smoothing:antialiased}
h1,h2,h3,p,dl,dd,dt{margin:0}
a{color:inherit}
[hidden]{display:none!important}
::selection{background:var(--gold-soft)}
:focus-visible{outline:2px solid var(--gold);outline-offset:2px}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
.container{max-width:var(--container);margin-inline:auto;padding-inline:20px}
.num{font-family:var(--font-mono);font-variant-numeric:tabular-nums}
.meta{font-size:13px;color:var(--muted)}
/* masthead */
.masthead{background:var(--navy);color:var(--paper,#f5f2ea);border-top:3px solid var(--gold);padding-block:clamp(34px,7vw,56px) clamp(24px,5vw,38px)}
.masthead .container{display:flex;flex-direction:column;align-items:center;text-align:center}
.seal{width:46px;height:46px;margin-bottom:20px}
.mast-overline{font-size:11.5px;letter-spacing:.34em;text-indent:.34em;color:var(--gold);margin-bottom:12px;font-weight:500}
.mast-title{font-family:var(--font-display);font-weight:600;font-size:clamp(34px,10vw,44px);line-height:1.15;letter-spacing:.09em;text-indent:.09em;display:flex;align-items:center;justify-content:center;gap:10px;flex-wrap:wrap}
.mast-flag{font-family:var(--font-body);font-size:12px;font-weight:600;letter-spacing:.05em;color:var(--gold-ink);background:var(--gold-soft);border:1px solid var(--gold);border-radius:999px;padding:4px 12px;text-indent:0;vertical-align:middle}
.mast-rule{margin-block:20px;display:grid;gap:3px;width:min(320px,72%)}
.mast-rule .rule-thick{height:2px;background:var(--gold)}
.mast-rule .rule-thin{height:1px;background:var(--hairline)}
.mast-meta{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 14px;font-size:13px;color:var(--hairline);letter-spacing:.02em;color:rgba(245,242,234,.72)}
.mast-meta .num{color:#f5f2ea}
.mast-sub{margin-top:12px;font-size:13px;color:rgba(245,242,234,.72)}
.mast-sub strong{color:var(--gold);font-weight:600}
.masthead .container>*{animation:rise .5s var(--ease) both}
.masthead .container>*:nth-child(2){animation-delay:.06s}
.masthead .container>*:nth-child(3){animation-delay:.10s}
.masthead .container>*:nth-child(4){animation-delay:.14s}
.masthead .container>*:nth-child(5){animation-delay:.18s}
.masthead .container>*:nth-child(6){animation-delay:.22s}
@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
/* toolbar */
.toolbar{position:sticky;top:0;z-index:20;background:rgba(245,242,234,.9);-webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);border-bottom:1px solid var(--border)}
.toolbar-inner{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-block:12px}
.chips{display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;padding:2px}
.chips::-webkit-scrollbar{display:none}
.chip{flex:0 0 auto;display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:999px;border:1px solid var(--border);background:var(--surface);color:var(--fg);font-size:13.5px;letter-spacing:.02em;line-height:1.2;min-height:34px;transition:background .15s var(--ease),border-color .15s var(--ease),color .15s var(--ease)}
.chip .chip-num{font-size:11.5px;color:var(--muted)}
.chip:hover{border-color:var(--border-strong);background:var(--fg-soft)}
.chip:active{transform:translateY(1px)}
.chip.is-active{background:var(--navy);border-color:var(--navy);color:#f5f2ea}
.chip.is-active .chip-num{color:rgba(245,242,234,.72)}
.toolbar-meta{flex:0 0 auto;font-size:11.5px;letter-spacing:.04em}
@media (max-width:719px){.toolbar-meta{display:none}}
.noscript-note{margin:0;padding:10px 20px 12px;font-size:13px;color:var(--gold-ink);border-top:1px dashed var(--border)}
/* list */
.section{padding-block:32px 56px}
.list-head{display:flex;align-items:baseline;justify-content:space-between;gap:20px}
.list-head h2{font-family:var(--font-display);font-size:21px;font-weight:600;letter-spacing:.04em;line-height:1.2}
.list-head .count{flex:0 0 auto}
.list-lead{margin-top:12px;max-width:58ch;color:var(--muted);font-size:15px}
.alert{margin-top:14px;padding:12px 14px;background:#f6ead8;border:1px solid var(--gold);border-radius:8px;font-size:13px;color:var(--gold-ink)}
.tender-list{margin-top:20px;display:grid;gap:14px}
.tender-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:18px;transition:border-color .15s var(--ease),box-shadow .15s var(--ease)}
.tender-card:hover{border-color:var(--border-strong);box-shadow:var(--elev)}
.tc-head{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.tc-cat{display:inline-flex;align-items:center;padding:3px 10px;border:1px solid var(--border-strong);border-radius:999px;font-size:11.5px;letter-spacing:.05em;color:var(--muted);background:var(--bg)}
.badge{display:inline-flex;align-items:center;padding:3px 10px;border-radius:999px;font-size:11.5px;font-weight:600;letter-spacing:.04em}
.b-zb{background:#EBF0FC;color:#1D4ED8}.b-cj{background:#EEEFF1;color:#5C626B}.b-gz{background:#FCF3E3;color:#8A5A0B}.b-fb{background:#FBEAEA;color:#A93030}.b-jg{background:#EEEFF1;color:#5C626B}
.tc-urgent{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;background:var(--gold-soft);color:var(--gold-ink);font-size:11.5px;font-weight:600;letter-spacing:.05em}
.tc-urgent .dot{width:5px;height:5px;border-radius:999px;background:var(--gold)}
.tc-region{margin-left:auto;display:inline-flex;align-items:center;gap:4px;font-size:11.5px;letter-spacing:.04em;color:var(--muted)}
.tc-region svg{width:13px;height:13px}
.tc-region.local{color:var(--gold-ink);font-weight:600}
.tc-title{margin-top:12px;font-size:16.5px;font-weight:600;line-height:1.5;letter-spacing:.01em}
.tc-title a{color:inherit;text-decoration:none}
.tc-title a:hover{color:var(--navy);text-decoration:underline;text-underline-offset:3px}
.tc-meta{margin-top:12px;display:grid;grid-template-columns:1fr 1fr;gap:10px 18px;padding-top:12px;border-top:1px dashed var(--border)}
.tc-meta dt{display:flex;align-items:center;gap:4px;font-size:11.5px;letter-spacing:.06em;color:var(--muted)}
.tc-meta dt svg{width:13px;height:13px}
.tc-meta dd{margin-top:3px;font-size:14px;color:var(--fg)}
.kwchip{display:inline-block;font-size:11.5px;padding:2px 8px;border-radius:999px;background:var(--gold-soft);color:var(--gold-ink);font-weight:600;margin:0 4px 4px 0}
/* empty */
.empty{margin-top:20px;padding:56px 20px;border:1px dashed var(--border-strong);border-radius:var(--radius);text-align:center;color:var(--muted)}
.empty svg{width:34px;height:34px;margin:0 auto 12px;color:var(--border-strong)}
.empty-title{font-weight:600;color:var(--fg)}
.empty p+p{margin-top:4px;font-size:13px}
/* footer */
.pagefoot{background:var(--navy-deep);color:var(--hairline);border-top:1px solid var(--hairline);padding-block:32px}
.foot-brand{display:flex;align-items:center;gap:10px}
.foot-brand .seal{width:26px;height:26px;margin:0}
.foot-logo{font-family:var(--font-display);font-size:17px;font-weight:600;letter-spacing:.08em;color:#f5f2ea}
.foot-tag{margin-top:8px;font-size:13px}
.foot-base{margin-top:20px;padding-top:20px;border-top:1px solid var(--hairline);display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 16px;font-size:11.5px;color:var(--hairline);letter-spacing:.04em}
.foot-base .num{color:#f5f2ea}
@media (min-width:720px){.container{padding-inline:20px}.tender-card{padding:22px 24px}.section{padding-block:56px}}
"""

SEAL_SVG = ('<svg class="seal" viewBox="0 0 48 48" aria-hidden="true" focusable="false">'
            '<circle cx="24" cy="24" r="22" fill="none" stroke="var(--gold)" stroke-width="1.4"/>'
            '<circle cx="24" cy="24" r="18.5" fill="none" stroke="var(--gold)" stroke-width="0.8"/>'
            '<text x="24" y="29.5" text-anchor="middle" font-size="15" letter-spacing="1" fill="var(--gold)" '
            'font-family="Iowan Old Style,Palatino,Songti SC,STSongti-SC,SimSun,Georgia,serif" font-weight="600">招采</text></svg>')

PIN_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
           '<path d="M12 21s-6-5.1-6-10a6 6 0 1 1 12 0c0 4.9-6 10-6 10z"/><circle cx="12" cy="11" r="2.2"/></svg>')
CLOCK_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
             '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/></svg>')
TAG_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
           '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/>'
           '<circle cx="7.5" cy="7.5" r="1.2"/></svg>')
SEARCH_SVG = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">'
              '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8.2 11h5.6"/></svg>')

TYPE_LABELS = [("zb", "招标·采购公告"), ("cj", "中标·成交"), ("gz", "更正公告"), ("jg", "结果公示"), ("fb", "废标·流标")]
WEEK = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

def render_html(date_iso, sections, total, window_hours, gen_time, repo, test_mode=False):
    md, md_y = date_iso[5:7], date_iso[8:10]
    src_ids = ["ccgp", "ggzy", "plap"]
    src_short = {"ccgp": "政采网", "ggzy": "公资网", "plap": "军采网"}
    wtxt = fmt_window(window_hours) if not test_mode else "全历史（测试模式）"
    d = dt.datetime.strptime(date_iso, "%Y-%m-%d").date()
    issue = (d - ISSUE_BASE).days + 1
    week = WEEK[d.weekday()]

    allit = []
    for sid, (name, lst, err) in zip(src_ids, sections):
        for it in lst:
            x = dict(it); x["src"] = src_short[sid]; x["srcid"] = sid; x["grp"] = type_group(it["type"])
            x["local"] = ("山东" in it["area"] or "青岛" in it["area"])
            allit.append(x)
    allit.sort(key=lambda x: x["date"], reverse=True)
    grp_count = {}
    for x in allit: grp_count[x["grp"]] = grp_count.get(x["grp"], 0) + 1
    local_count = sum(1 for x in allit if x["local"])
    errs = [(name, err) for (name, lst, err) in sections if err]

    o = []
    o.append("<!doctype html>\n<html lang=\"zh-CN\">\n<head>\n<meta charset=\"utf-8\">")
    o.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    o.append("<title>青岛招采日报 · " + date_iso + "</title>\n<style>" + CSS + "</style>\n</head>\n<body>")
    # masthead
    o.append('<header class="masthead"><div class="container">' + SEAL_SVG)
    o.append('<p class="mast-overline">青岛 · 每日招采情报</p>')
    o.append('<h1 class="mast-title">青岛招采日报' + ('<span class="mast-flag">测试模式 · 全历史样例</span>' if test_mode else '') + '</h1>')
    o.append('<div class="mast-rule" aria-hidden="true"><span class="rule-thick"></span><span class="rule-thin"></span></div>')
    o.append('<div class="mast-meta"><span><span class="num">' + _e(f"{d.year}年{d.month}月{d.day}日") + '</span> ' + week + '</span><span>总第 <span class="num">' + str(issue) + '</span> 期</span></div>')
    o.append('<p class="mast-sub">本次收录 <strong class="num">' + str(total) + '</strong> 条招采动态 · 命中关键词 <strong class="num">' + str(len(KEYWORDS)) + '</strong> 个 · 每日 <span class="num">08:00</span> 更新</p>')
    o.append('</div></header>')
    # toolbar
    o.append('<div class="toolbar"><div class="container toolbar-inner"><div class="chips" role="group" aria-label="按来源筛选">')
    o.append('<button class="chip is-active" type="button" data-filter="all" aria-pressed="true">全部 <span class="chip-num num">' + str(total) + '</span></button>')
    for sid, (name, lst, err) in zip(src_ids, sections):
        o.append('<button class="chip" type="button" data-filter="' + sid + '" aria-pressed="false">' + _e(src_short[sid]) + ' <span class="chip-num num">' + str(len(lst)) + '</span></button>')
    o.append('</div><span class="toolbar-meta meta">更新于 <span class="num">' + _e(gen_time.split(" ")[-1] if " " in gen_time else gen_time) + '</span>' + (' · 测试模式' if test_mode else '') + '</span></div>')
    o.append('<noscript><p class="noscript-note">分类筛选需要启用 JavaScript；公告列表可直接滚动阅读。</p></noscript></div>')
    # main
    o.append('<main id="content"><section class="section"><div class="container">')
    o.append('<div class="list-head"><h2>招采动态</h2><span class="count meta">共 <span id="visibleCount" class="num" aria-live="polite">' + str(total) + '</span> 条 · 按发布时间排序</span></div>')
    zb_n = grp_count.get("zb", 0)
    o.append('<p class="list-lead">本页收录近 ' + wtxt + '内命中监控关键词的招采动态 ' + str(total) + ' 条：政采网 ' + str(len(sections[0][1])) + ' 条、公资网 ' + str(len(sections[1][1])) + ' 条、军采网 ' + str(len(sections[2][1])) + ' 条（军采网仅保留山东省内项目）；本地商机已用金色标签标出。</p>')
    for name, err in errs:
        o.append('<div class="alert"><strong>抓取异常：</strong>' + _e(err) + '。其余来源不受影响。</div>')
    o.append('<div class="tender-list" id="tenderList">')
    for x in allit:
        kws = "".join('<span class="kwchip">' + _e(k) + '</span>' for k in x["kw"].split("+"))
        o.append('<article class="tender-card" data-src="' + x["srcid"] + '">')
        o.append('<header class="tc-head"><span class="tc-cat">' + _e(x["src"]) + '</span><span class="badge b-' + x["grp"] + '">' + _e(x["type"]) + '</span>'
                 + ('<span class="tc-urgent"><span class="dot" aria-hidden="true"></span>本地商机</span>' if x["local"] else '')
                 + '<span class="tc-region' + (' local' if x["local"] else '') + '">' + PIN_SVG + _e(x["area"]) + '</span></header>')
        o.append('<h3 class="tc-title"><a href="' + _e(x["url"], True) + '" target="_blank" rel="noopener">' + _e(x["title"][:90]) + '</a></h3>')
        o.append('<dl class="tc-meta"><div><dt>' + CLOCK_SVG + '发布时间</dt><dd class="num">' + _e(x["date"]) + '</dd></div>'
                 + '<div><dt>' + TAG_SVG + '命中关键词</dt><dd>' + kws + '</dd></div></dl>')
        o.append('</article>')
    o.append('</div>')
    o.append('<div class="empty" id="emptyState" role="status" hidden>' + SEARCH_SVG + '<p class="empty-title">该分类下暂无公告</p><p>可切换其他类型查看，或明天 08:00 再来看更新。</p></div>')
    o.append('</div></section></main>')
    # footer
    o.append('<footer class="pagefoot"><div class="container"><div class="foot-brand">' + SEAL_SVG.replace('class="seal"', 'class="seal" width="26" height="26"') + '<span class="foot-logo">青岛招采日报</span></div>')
    o.append('<p class="foot-tag">每天 08:00，一分钟读完青岛招采动态。</p>')
    o.append('<div class="foot-base"><span>© 2026 青岛招采日报</span><span>数据来源：青岛市政府采购网 · 青岛市公共资源交易网 · 军队采购网</span><span>生成于 <span class="num">' + _e(gen_time) + '</span>（北京）</span></div>')
    o.append('</div></footer>')
    # filter js
    o.append('<script>(function(){var chips=Array.prototype.slice.call(document.querySelectorAll(".chip"));'
             'var cards=Array.prototype.slice.call(document.querySelectorAll(".tender-card"));'
             'var countEl=document.getElementById("visibleCount");var empty=document.getElementById("emptyState");'
             'chips.forEach(function(chip){chip.addEventListener("click",function(){'
             'chips.forEach(function(c){var a=c===chip;c.classList.toggle("is-active",a);c.setAttribute("aria-pressed",a?"true":"false");});'
             'var f=chip.getAttribute("data-filter");var v=0;'
             'cards.forEach(function(card){var s=f==="all"||card.getAttribute("data-src")===f;card.hidden=!s;if(s)v+=1;});'
             'countEl.textContent=String(v);empty.hidden=v>0;});});})();</script>')
    o.append("</body>\n</html>")
    return "\n".join(o)

# ---------- 过期数据自动清理 ----------
DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")

def cleanup_old_data():
    """清理超过保留期的历史数据（三个月前）：
    - state.json 的 seen 去重记录
    - docs/ 下带日期的历史日报 HTML
    - 根目录带日期的历史报告 Markdown
    返回清理清单；index.html / test.html / 无日期文件不受影响。
    """
    cutoff = (dt.date.today() - dt.timedelta(days=RETENTION_DAYS)).isoformat()
    removed = []
    state_path = os.path.join(BASE, "state.json")
    try:
        state = json.load(open(state_path, encoding="utf-8"))
        seen = state.get("seen", {})
        old = [k for k, v in seen.items() if str(v) < cutoff]
        if old:
            for k in old: seen.pop(k, None)
            state["seen"] = seen
            json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            removed.append("seen记录x" + str(len(old)))
    except Exception as e:
        removed.append("seen:error(" + type(e).__name__ + ")")
    for folder in ("docs", ""):
        d = os.path.join(BASE, folder) if folder else BASE
        if not os.path.isdir(d): continue
        for fn in os.listdir(d):
            if not (fn.endswith(".html") or fn.endswith(".md")): continue
            m = DATE_IN_NAME.search(fn)
            if not m or m.group(1) >= cutoff: continue
            try:
                os.remove(os.path.join(d, fn)); removed.append(fn)
            except Exception:
                pass
    return removed

# ---------- 报告/状态回传 GitHub ----------
def sync_to_github(rep_path):
    try:
        base = BASE
        if not os.path.isdir(os.path.join(base, ".git")):
            return "git:skip(非仓库)"
        env = dict(os.environ)
        env["GIT_SSH_COMMAND"] = "ssh -i " + base + "/deploy_key -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
        def git(*args):
            return subprocess.run(["git", *args], cwd=base, env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
        git("pull", "--rebase", "origin", "main")
        git("add", "-A", "--", "docs/", "state.json")
        git("add", "-A", "--", "*.md")
        git("commit", "-m", "日报 " + dt.date.today().isoformat())
        r = git("push", "origin", "main")
        return "git:ok" if r.returncode == 0 else "git:fail(" + r.stderr.decode("utf-8", "replace").strip()[:80] + ")"
    except Exception as e:
        return "git:fail(" + type(e).__name__ + ")"

def run():
    t0 = time.time()
    wtxt = fmt_window(WINDOW_HOURS)
    cleaned = cleanup_old_data()
    if cleaned: log("清理过期数据: " + "、".join(map(str, cleaned)))
    log("1/3 青岛政府采购网（逐词检索）...")
    ccgp, e1 = fetch_ccgp(); log(f"   -> {len(ccgp)} 条  err={e1}")
    log("2/3 公共资源交易网（最新分页）...")
    ggzy, e2 = fetch_ggzy(); log(f"   -> {len(ggzy)} 条  err={e2}")
    log("3/3 军队采购网（逐词检索+翻页）...")
    plap, e3 = fetch_plap(); log(f"   -> {len(plap)} 条  err={e3}")

    state_path = os.path.join(BASE, "state.json")
    try: state = json.load(open(state_path, encoding="utf-8"))
    except Exception: state = {"lastRun": None, "seen": {}}
    seen = state.get("seen", {})
    def dedup(src, lst):
        out = []
        for it in sorted(lst, key=lambda x: x["date"], reverse=True):
            key = src + ":" + re.sub(r"[^A-Za-z0-9]", "", it["url"])[-100:]
            if key in seen: continue
            seen[key] = dt.date.today().isoformat(); out.append(it)
        return out
    ccgp, ggzy, plap = dedup("ccgp", ccgp), dedup("ggzy", ggzy), dedup("plap", plap)
    if TEST_MODE:
        ccgp, ggzy, plap = ccgp[:60], ggzy[:60], plap[:60]
    total = len(ccgp) + len(ggzy) + len(plap)

    head = ("全历史测试样例 " + str(total) + " 条") if TEST_MODE else ("新增 " + str(total) + " 条")
    rep = ["# 青岛招采日报", "",
           f"**{dt.date.today().isoformat()} · {head}**（政府采购 {len(ccgp)} ｜ 公共资源交易 {len(ggzy)} ｜ 军队采购 {len(plap)}）· 统计窗口：近 {wtxt}", ""]
    sections = [("青岛市政府采购网 · 采购公告", ccgp, e1),
                ("青岛市公共资源交易网 · 招标公告", ggzy, e2),
                ("军队采购网（全军范围，重点看区域列）", plap, e3)]
    for name, lst, err in sections:
        rep += [f"## {name}（{len(lst)} 条）", ""]
        if err: rep += [f"> ⚠️ 抓取异常：{err}（其余来源不受影响）", ""]
        if lst:
            rep += ["| 标题 | 类型 | 区域 | 发布时间 | 命中关键词 |", "|---|---|---|---|---|"]
            for it in lst:
                rep.append(f"| [{it['title'][:58]}]({it['url']}) | {it['type']} | {it['area']} | {it['date']} | {it['kw']} |")
        elif not err:
            rep.append(f"近 {wtxt}无命中关键词的新公告。")
        rep.append("")
    rep += ["---", f"*生成时间 {NOW.strftime('%Y-%m-%d %H:%M')}（北京）· 关键词 {len(KEYWORDS)} 个 · 阿里云每天 08:00 自动执行*"]
    rep_path = os.path.join(BASE, ("test-" if TEST_MODE else "") + dt.date.today().isoformat() + ".md")
    open(rep_path, "w", encoding="utf-8").write("\n".join(rep))

    docs_dir = os.path.join(BASE, "docs")
    if not os.path.isdir(docs_dir): os.makedirs(docs_dir)
    repo = os.environ.get("GITHUB_REPOSITORY", "little-molly/qingdao-bids")
    html_str = render_html(dt.date.today().isoformat(), sections, total, WINDOW_HOURS, NOW.strftime("%Y-%m-%d %H:%M"), repo, TEST_MODE)
    out_name = "test.html" if TEST_MODE else "index.html"
    open(os.path.join(docs_dir, out_name), "w", encoding="utf-8").write(html_str)
    open(os.path.join(docs_dir, ("test-" if TEST_MODE else "") + dt.date.today().isoformat() + ".html"), "w", encoding="utf-8").write(html_str)

    report_url = f"https://{repo.split('/')[0]}.github.io/{repo.split('/')[1]}/" + ("test.html" if TEST_MODE else "")
    title = ("【测试】" if TEST_MODE else "") + f"青岛招采日报 {dt.date.today().strftime('%m-%d')}｜" + head
    body = (f"政采 {len(ccgp)} ｜公资 {len(ggzy)} ｜军采 {len(plap)}\n"
            + build_summary(ccgp, ggzy, plap, (e1, e2, e3))
            + "\n（点击通知打开完整报告）")
    force = os.environ.get("FORCE_PUSH") == "1"
    pushes = push_all(title, body, report_url) if (total or any((e1, e2, e3)) or force) else ["skip(无新增无异常)"]
    sync = sync_to_github(rep_path)

    if not TEST_MODE:
        cutoff_seen = (dt.date.today() - dt.timedelta(days=RETENTION_DAYS)).isoformat()
        state["seen"] = {k: v for k, v in seen.items() if v >= cutoff_seen}
        state["lastRun"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
        json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"total": total, "ccgp": len(ccgp), "ggzy": len(ggzy), "plap": len(plap),
                      "window": wtxt, "errors": [e for e in (e1, e2, e3) if e], "push": pushes,
                      "sync": sync, "cleanup": cleaned, "report": rep_path, "sec": round(time.time() - t0, 1)}, ensure_ascii=False))

if __name__ == "__main__":
    run()
