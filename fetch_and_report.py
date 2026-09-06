#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""青岛招标商机监控 - GitHub Actions 云端版
策略（2026-09-04 实测定型）：
  ccgp  逐词 subject 服务端检索（全历史按时间倒序） -> 本地 48h 过滤
  ggzy  无参分页 pageIndex=1..N 拉最新列表（按时间倒序） -> 本地关键词+48h 过滤
  plap  逐词 title 服务端检索（每词最新 20 条） -> 本地 48h 过滤
云端增强：
  - 时间统一按北京时间（GitHub runner 是 UTC）
  - 报告生成后按 secrets 推送手机（Bark / ntfy / 企业微信，配哪个用哪个，都没配则跳过）
  - state.json 由 workflow 提交回仓库，实现跨天去重持久化
"""
import json, os, re, sys, time, ssl, datetime as dt
import urllib.parse as up
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
KEYWORDS = ["弱电","大屏","监控","LED","智能化","安全防范","安防","电子警察","广播","会议系统","网络安全","服务器","机房","动环","交换机"]
WINDOW_HOURS = 48
GGZY_PAGES = 5
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
    for kw in KEYWORDS:
        if (kw == "LED" and "led" in tl) or (kw != "LED" and kw in title):
            out.append(kw)
    return out

def ptype(title):
    for k in ["招标公告","更正公告","成交公告","中标公告","竞标公告","结果公示","废标公示","终止公告"]:
        if k in title: return k
    return "采购公告"

try:
    from zoneinfo import ZoneInfo
    NOW = dt.datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
except Exception:
    NOW = dt.datetime.utcnow() + dt.timedelta(hours=8)
CUTOFF = NOW - dt.timedelta(hours=WINDOW_HOURS)

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
            if oldest and oldest < CUTOFF.strftime("%Y-%m-%d"): break
            time.sleep(0.8)
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
    return items, err

PLAP = "https://www.plap.mil.cn"
def fetch_plap():
    items, err = [], None
    try:
        for kw in KEYWORDS:
            url = (PLAP + "/freecms-glht/rest/v1/notice/selectInfoMoreChannel.do"
                   "?siteId=404bb030-5be9-4070-85bd-c94b1473e8de&channel=c5bff13f-21ca-4dac-b158-cb40accd3035"
                   "&currPage=1&pageSize=20&title=" + quote(kw))
            d = json.loads(fetch(url))
            for r in d.get("data") or []:
                t = parse_time(r.get("noticeTime"))
                if not t or t < CUTOFF: continue
                h = hits(r.get("title") or "")
                if not h: continue
                hp = r.get("htmlpath") or ""
                items.append({"title": r["title"].strip(),
                              "url": PLAP + hp if hp.startswith("/") else hp,
                              "date": t.strftime("%m-%d %H:%M"), "area": r.get("regionName") or "全国",
                              "kw": h, "type": ptype(r["title"])})
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
    return items, err

# ---------- 手机推送（配了哪个 secret 就用哪个，可同时配多个） ----------
def push_notify(title, body):
    results = []
    bark = os.environ.get("BARK_URL", "").strip().rstrip("/")
    ntfy = os.environ.get("NTFY_URL", "").strip()
    wecom = os.environ.get("WECOM_WEBHOOK", "").strip()
    if bark:
        try:
            fetch(f"{bark}/{up.quote(title)}/{up.quote(body[:500])}?group=qingdao-bid", timeout=15)
            results.append("bark:ok")
        except Exception as e:
            results.append(f"bark:fail({type(e).__name__})")
    if ntfy:
        try:
            payload = json.dumps({"topic": ntfy.rstrip("/").split("/")[-1],
                                  "title": title, "message": body[:900]}).encode()
            with urlopen(Request(ntfy, data=payload, headers={"Content-Type": "application/json"}),
                         timeout=15, context=CTX) as r:
                r.read()
            results.append("ntfy:ok")
        except Exception as e:
            results.append(f"ntfy:fail({type(e).__name__})")
    if wecom:
        try:
            payload = json.dumps({"msgtype": "text", "text": {"content": (title + "\n" + body)[:2000]}}).encode()
            with urlopen(Request(wecom, data=payload, headers={"Content-Type": "application/json"}),
                         timeout=15, context=CTX) as r:
                r.read()
            results.append("wecom:ok")
        except Exception as e:
            results.append(f"wecom:fail({type(e).__name__})")
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
        tag = "🟢山东/青岛" if rank(it)[0] == 0 else it["area"]
        lines.append(f"· [{it['type']}·{tag}] {it['title'][:40]} ({it['kw']})")
    err_note = "；".join(f"{s}异常" for s, e in zip(("政采", "公资", "军采"), errs) if e)
    if err_note: lines.insert(0, f"⚠️ {err_note}（详见报告）")
    return "\n".join(lines) if lines else "近48小时无命中关键词的新公告"

def run():
    t0 = time.time()
    log("1/3 青岛政府采购网（逐词检索）...")
    ccgp, e1 = fetch_ccgp(); log(f"   -> {len(ccgp)} 条  err={e1}")
    log("2/3 公共资源交易网（最新分页）...")
    ggzy, e2 = fetch_ggzy(); log(f"   -> {len(ggzy)} 条  err={e2}")
    log("3/3 军队采购网（逐词检索）...")
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
    total = len(ccgp) + len(ggzy) + len(plap)

    rep = ["# 青岛招标商机日报", "",
           f"**{dt.date.today().isoformat()} · 新增 {total} 条**（政府采购 {len(ccgp)} ｜ 公共资源交易 {len(ggzy)} ｜ 军队采购 {len(plap)}）· 统计窗口：近 {WINDOW_HOURS} 小时", ""]
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
            rep.append(f"近 {WINDOW_HOURS} 小时无命中关键词的新公告。")
        rep.append("")
    rep += ["---", f"*生成时间 {NOW.strftime('%Y-%m-%d %H:%M')}（北京）· 关键词 {len(KEYWORDS)} 个 · 由 GitHub Actions 云端执行*"]
    rep_path = os.path.join(BASE, dt.date.today().isoformat() + ".md")
    open(rep_path, "w", encoding="utf-8").write("\n".join(rep))

    # 推送手机
    title = f"青岛招标日报 {dt.date.today().strftime('%m-%d')}｜新增 {total} 条"
    body = (f"政采 {len(ccgp)} ｜公资 {len(ggzy)} ｜军采 {len(plap)}\n"
            + build_summary(ccgp, ggzy, plap, (e1, e2, e3))
            + f"\n（完整报告见仓库 {dt.date.today().isoformat()}.md）")
    pushes = push_notify(title, body) if total or any((e1, e2, e3)) else ["skip(无新增无异常)"]

    cutoff_seen = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    state["seen"] = {k: v for k, v in seen.items() if v >= cutoff_seen}
    state["lastRun"] = NOW.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(state, open(state_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({"total": total, "ccgp": len(ccgp), "ggzy": len(ggzy), "plap": len(plap),
                      "errors": [e for e in (e1, e2, e3) if e], "push": pushes, "report": rep_path,
                      "sec": round(time.time() - t0, 1)}, ensure_ascii=False))

if __name__ == "__main__":
    run()
