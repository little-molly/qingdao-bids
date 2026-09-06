#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送发送模块：Bark / ntfy / 企业微信，供日报脚本与管理后台共用"""
import json, ssl, time
import urllib.parse as up
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE

def _fetch(url, data=None, headers=None, timeout=15):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers: h.update(headers)
    req = Request(url, data=data, headers=h)
    with urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()

def send_bark(target, title, body, click_url=None):
    # 改用 POST /push 接口：GET 路径模式在长摘要下会超 URL 长度限制（HTTP 431）
    parts = (target or "").strip().rstrip("/").split("/")
    key = parts[-1]
    host = "/".join(parts[:3])
    payload = {"device_key": key, "title": title[:64], "body": body[:1500], "group": "qingdao-bid"}
    if click_url: payload["url"] = click_url
    _fetch(host + "/push", data=json.dumps(payload).encode("utf-8"),
           headers={"Content-Type": "application/json; charset=utf-8"})

def send_ntfy(target, title, body, click_url=None):
    payload = {"topic": (target or "").strip().rstrip("/").split("/")[-1],
               "title": title, "message": body[:900]}
    if click_url: payload["click"] = click_url
    _fetch((target or "").strip(), data=json.dumps(payload).encode(),
           headers={"Content-Type": "application/json"})

def send_wecom(target, title, body):
    payload = json.dumps({"msgtype": "text", "text": {"content": (title + "\n" + body)[:2000]}}).encode()
    _fetch((target or "").strip(), data=payload, headers={"Content-Type": "application/json"})

def send_to(rcv, title, body, click_url=None):
    """向单个接收人推送，自动重试一次，返回 {"name":..., "result":"ok"/"fail(...)"}"""
    t = (rcv.get("type") or "").lower()
    target = rcv.get("target") or ""
    name = rcv.get("name") or t
    last = ""
    for attempt in range(3):
        try:
            if t == "bark": send_bark(target, title, body, click_url)
            elif t == "ntfy": send_ntfy(target, title, body, click_url)
            elif t == "wecom": send_wecom(target, title, body)
            else: return {"name": name, "result": "fail(未知类型 " + t + ")"}
            return {"name": name, "result": "ok"}
        except Exception as e:
            last = type(e).__name__ + (getattr(e, "code", "") and " code=" + str(getattr(e, "code", "")) or "")
            if attempt < 2: time.sleep(3 if attempt == 0 else 12)
    return {"name": name, "result": "fail(" + last + ")"}
