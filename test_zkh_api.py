#!/usr/bin/env python3
"""Verify ZKH Punch-Out APIs - v2"""

import json, time, sys
import urllib.request, urllib.parse
import hashlib

BASE = "https://openapi.uat.zkh360.com/punchout/m2"
AUTH = {
    "client_id": "A2048732",
    "client_secret": "waterhealer1234",
    "username": "M2_waterhealer",
    "password": "ef73781effc5774100f87fe2f437a435",
}

ok, fail = 0, 0
token = None


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest().upper()


def req(path, payload, need_token=True, token_in_query=False, desc=""):
    global ok, fail, token
    url = f"{BASE}{path}"

    if need_token and token and token_in_query:
        url += f"?token={token}"

    headers = {"Content-Type": "application/json; charset=UTF-8"}
    data = json.dumps(payload).encode("utf-8")

    if need_token and token and not token_in_query:
        p = payload.copy()
        p["token"] = token
        data = json.dumps(p).encode("utf-8")

    try:
        r = urllib.request.Request(url, data=data, headers=headers, method="POST")
        resp = urllib.request.urlopen(r, timeout=10)
        body = json.loads(resp.read())
        succ = body.get("success") and body.get("resultCode") == "0000"
        if succ:
            ok += 1
            print(f"  [PASS] {desc}")
        else:
            fail += 1
            msg = body.get('resultMessage', '')
            code = body.get('resultCode', '')
            print(f"  [FAIL] {desc} -> [{code}] {msg}")
        return body
    except urllib.error.HTTPError as e:
        fail += 1
        body = e.read()
        try:
            j = json.loads(body)
            print(f"  [FAIL] {desc} -> HTTP {e.code} [{j.get('resultCode','')}] {j.get('resultMessage','')}")
        except:
            print(f"  [FAIL] {desc} -> HTTP {e.code} {body[:200]}")
        return None
    except Exception as e:
        fail += 1
        print(f"  [FAIL] {desc} -> {e}")
        return None


print("=" * 60)
print("ZKH Punch-Out API Verification v2")
print("=" * 60)

# --- 1. accessToken ---
print("\n[1] accessToken")
ts = time.strftime("%Y-%m-%d %H:%M:%S")
r = req("/accessToken", {**AUTH, "timestamp": ts}, need_token=False, desc="获取access_token")
if r and r.get("success"):
    token = r["result"]["access_token"]
    print(f"       token={token[:20]}... expires_in={r['result']['expires_in']}s")

if not token:
    print("FATAL: No token, aborting")
    sys.exit(1)

# --- 2. user/sync ---
print("\n[2] user/sync")
r = req("/user/sync", {"opt": "query", "uniqueNo": "test_001"}, desc="查询用户(预期不存在)")

ts_now = int(time.time())
r = req("/user/sync", {
    "opt": "insert",
    "uniqueNo": f"test_{ts_now}",
    "nickName": "测试用户",
    "email": "test@zkh.com",
    "mobile": "13800138000",
    "roleName": "采购员",
    "stateCode": 1,
}, desc="新增用户")

r = req("/user/sync", {
    "opt": "update",
    "uniqueNo": f"test_{ts_now}",
    "nickName": "测试用户已更新",
}, desc="更新用户")

r = req("/user/sync", {"opt": "query", "uniqueNo": f"test_{ts_now}"}, desc="查询用户(应存在)")

# --- 3. message/get (no type param = all) ---
print("\n[3] message/get")
r = req("/get", {}, desc="获取全部消息")

# --- 4. message/get with type 101 ---
r = req("/get", {"type": 101}, desc="获取消息(type=101)")

# --- 5. trustedLogin (token in query per doc) ---
print("\n[4] trustedLogin")
ts_ms = int(time.time() * 1000)
pin = "test_user"
unique_no = f"tester_{ts_now}"
sign = md5(f"{pin}{unique_no}{ts_ms}")
r = req("/strustNo", {
    "strustReqVo": {
        "pin": pin,
        "uniqueNo": unique_no,
        "time": ts_ms,
        "sign": sign,
    }
}, token_in_query=True, desc="获取信任登录标识")

# --- 6. confirmOrder ---
print("\n[5] confirmOrder")
r = req("/confirmOrder", {"orderId": "NONEXISTENT", "thirdOrder": "TEST001"}, desc="确认订单(预期无此订单)")

# --- 7. cancel ---
print("\n[6] cancel")
r = req("/cancel", {"orderId": "NONEXISTENT"}, desc="取消订单(预期无此订单)")

# --- 8. updateOrderDetail ---
print("\n[7] updateOrderDetail")
r = req("/order/detail/update/v2", {
    "orderId": "NONEXISTENT",
    "skuInfo": [{"skuNo": "A00300", "count": 1}],
}, desc="更新订单明细(预期无此订单)")

# --- 9. orderTrack ---
print("\n[8] orderTrack")
r = req("/orderTrack", {"packageId": "NONEXISTENT"}, desc="查询物流(预期无此发货单)")

# --- 10. package ---
print("\n[9] package")
r = req("/package", {"packageId": "NONEXISTENT"}, desc="查询包裹(预期无此发货单)")

# --- 11. confirmPackage ---
print("\n[10] confirmPackage")
r = req("/confirmPackage", {"packageId": "NONEXISTENT"}, desc="确认收货(预期无此发货单)")

# --- 12. serviceOrder ---
print("\n[11] serviceOrder")
r = req("/serviceOrder", {
    "orderNumber": "NONEXISTENT",
    "serviceType": 2,
    "applicant": "测试",
    "applicationPhone": "13800138000",
    "detail": [{"skuId": "A00300", "num": 1}],
}, desc="申请售后(预期无此订单)")

# --- 13. serviceOrder/cancel ---
print("\n[12] serviceOrder/cancel")
r = req("/serviceOrder/cancel", {"serviceId": "NONEXISTENT"}, desc="取消售后(预期无此售后单)")

# --- 14. serviceOrder/fetch ---
print("\n[13] serviceOrder/fetch")
r = req("/serviceOrder/fetch", {"serviceId": "NONEXISTENT"}, desc="查询售后(预期无此售后单)")

# --- 15. delete message (try with no id) ---
print("\n[14] message/delete")
r = req("/delete", {"id": "0"}, desc="删除消息(预期无此消息)")

# --- Summary ---
print("\n" + "=" * 60)
total = ok + fail
pct = ok / total * 100 if total else 0
print(f"Result: {ok}/{total} passed ({pct:.0f}%)")
print("Legend: PASS=接口可达+鉴权通过, FAIL=预期内(无合法订单/发货单ID)或需进一步排查")
print("=" * 60)