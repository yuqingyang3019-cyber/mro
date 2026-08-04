"""
震坤行 Punch-Out 集成 Web 服务

提供 SSO 登录、订单回调接收、审批管理等接口。

启动方式：
    pip install flask
    python app.py

接口一览：
    GET  /api/zkh/sso?unique_no=xxx          → SSO 登录入口（返回自动提交的表单页面）
    POST /api/zkh/checkout                   → 接收震坤行订单回传（checkOut 回调）
    GET  /api/zkh/orders/pending             → 查看待审批订单列表
    POST /api/zkh/orders/<order_id>/approve   → 审批通过
    POST /api/zkh/orders/<order_id>/reject    → 审批拒绝
    GET  /api/zkh/messages                   → 拉取消息
"""

import os
import json
import logging
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

from zkh_punchout.client import ZKHClient
from zkh_punchout.order import OrderData, OrderApprovalStore, ApprovalStatus
from zkh_punchout.dingtalk import DingTalkClient
from zkh_punchout.approval import ApprovalService

# ==================== 配置 ====================

ZKH_CONFIG = {
    "base_url": os.getenv("ZKH_BASE_URL", "https://openapi.uat.zkh360.com"),
    "client_id": os.getenv("ZKH_CLIENT_ID", "A2048732"),
    "client_secret": os.getenv("ZKH_CLIENT_SECRET", "waterhealer1234"),
    "username": os.getenv("ZKH_USERNAME", "M2_waterhealer"),
    "password": os.getenv("ZKH_PASSWORD", "ef73781effc5774100f87fe2f437a435"),
}

SELF_BASE_URL = os.getenv("SELF_BASE_URL", "https://mro.water-healer.com")

DINGTALK_CONFIG = {
    "app_key": os.getenv("DINGTALK_APP_KEY", "ding1fqbfzewirie5zw8"),
    "app_secret": os.getenv("DINGTALK_APP_SECRET", "xHdkAO5DRED_lUobIDkFYHSwznaMOTe8do6kfdYbXjVapcd3swuffU2rHVi4srM3"),
    "app_id": os.getenv("DINGTALK_APP_ID", "3fd243f6-33a1-4dd2-b681-aabe7eb1fd5d"),
    "corp_id": os.getenv("DINGTALK_CORP_ID", "ding4f4b796d63d5f483f5bf40eda33b7ba0"),
}

APPROVAL_CONFIG = {
    "process_code": os.getenv("DINGTALK_PROCESS_CODE", "PROC-D94EFFF6-FA92-415E-B8F5-1205BE2B5BC4"),
    "approver_user_id": os.getenv("DINGTALK_APPROVER_USERID", "01432453192526187328"),
    "callback_token": os.getenv("DINGTALK_CALLBACK_TOKEN", ""),
    "callback_aes_key": os.getenv("DINGTALK_CALLBACK_AES_KEY", ""),
}

# ==================== 初始化 ====================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

client = ZKHClient(**ZKH_CONFIG)
store = OrderApprovalStore()
dingtalk = DingTalkClient(DINGTALK_CONFIG["app_key"], DINGTALK_CONFIG["app_secret"])
approval = ApprovalService(
    dingtalk=dingtalk,
    store=store,
    process_code=APPROVAL_CONFIG["process_code"],
    approver_user_id=APPROVAL_CONFIG["approver_user_id"],
)


def _api_detail(resp: dict) -> str:
    """提取 API 响应的错误详情"""
    if not resp:
        return "无响应"
    return f"[{resp.get('resultCode', '?')}] {resp.get('resultMessage', '未知错误')}"


# ==================== SSO 登录 ====================

SSO_FORM_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>震坤行采购平台</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f6fa;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh;
  }
  .container {
    text-align: center;
    padding: 48px 32px;
  }
  .logo {
    font-size: 28px; font-weight: 700; color: #1a1a2e;
    margin-bottom: 8px;
  }
  .spinner {
    width: 40px; height: 40px;
    margin: 32px auto 20px;
    border: 3px solid #e0e0e0;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .message {
    color: #666; font-size: 15px;
  }
</style>
</head>
<body>
  <div class="container">
    <div class="logo">震坤行采购平台</div>
    <div class="spinner"></div>
    <p class="message">正在进入震坤行，请稍候...</p>
  </div>
  <form id="zkhForm" action="{{ checkin_url }}" method="post" enctype="multipart/form-data">
    {% for key, value in form.items() %}
    <input type="hidden" name="{{ key }}" value="{{ value }}">
    {% endfor %}
  </form>
  <script>document.getElementById('zkhForm').submit();</script>
</body>
</html>
"""


@app.route("/api/zkh/sso")
def sso_login():
    """
    SSO 登录入口
    用户访问此接口，自动同步用户 → 获取 strustNo → 跳转震坤行

    参数：
        unique_no: 客户侧用户唯一标识（必填）
        pin: 震坤行用户名（可选）
        nick_name: 用户姓名（可选，用于自动创建用户）
        mobile: 手机号（可选）
        email: 邮箱（可选）
        custom_fields: 自定义参数 JSON（可选，如发票抬头）
    """
    unique_no = request.args.get("unique_no", "")
    pin = request.args.get("pin", "")
    nick_name = request.args.get("nick_name", "")
    mobile = request.args.get("mobile", "")
    email = request.args.get("email", "")
    custom_fields_str = request.args.get("custom_fields", "")

    if not unique_no:
        return jsonify({"error": "unique_no is required"}), 400

    custom_fields = None
    if custom_fields_str:
        try:
            custom_fields = json.loads(custom_fields_str)
        except json.JSONDecodeError:
            return jsonify({"error": "custom_fields must be valid JSON"}), 400

    # 自动同步用户：查询 → 不存在则创建
    if not client.ensure_user(unique_no, nick_name, email, mobile):
        logger.warning(f"Failed to ensure user: {unique_no}")
        # 不阻断流程，继续尝试 SSO（用户可能已存在）

    # hookUrl 是震坤行回传订单的地址
    hook_url = f"{SELF_BASE_URL}/api/zkh/checkout"

    result = client.sso_login(unique_no, hook_url, pin, custom_fields)
    if not result:
        return jsonify({"error": "SSO login failed"}), 500

    return render_template_string(
        SSO_FORM_TEMPLATE,
        checkin_url=result["checkin_url"],
        form=result["checkin_form"],
    )


# ==================== 钉钉 H5 免登 SSO ====================

DINGTALK_SSO_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>震坤行采购平台</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f6fa;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; text-align: center;
  }
  .container { padding: 48px 24px; }
  .logo { font-size: 24px; font-weight: 700; color: #1a1a2e; margin-bottom: 8px; }
  .spinner {
    width: 36px; height: 36px; margin: 28px auto 16px;
    border: 3px solid #e0e0e0; border-top-color: #2563eb;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .message { color: #666; font-size: 14px; }
  .error { color: #e53e3e; font-size: 13px; margin-top: 12px; display: none; }
  .steps { text-align: left; margin-top: 16px; font-size: 12px; display: none; }
  .step { padding: 6px 10px; margin: 4px 0; border-radius: 4px; background: #f8f9fa; border-left: 3px solid #ddd; }
  .step.ok { border-left-color: #22c55e; }
  .step.fail { border-left-color: #e53e3e; background: #fff5f5; }
  .step .label { font-weight: 600; }
  .step .detail { color: #999; margin-top: 2px; font-family: monospace; }
</style>
</head>
<body>
  <div class="container">
    <div class="logo">震坤行采购平台</div>
    <div class="spinner" id="spinner"></div>
    <p class="message" id="message">正在获取钉钉授权...</p>
    <p class="error" id="error"></p>
    <div class="steps" id="steps"></div>
  </div>
  <form id="zkhForm" action="" method="post" enctype="multipart/form-data"></form>

  <script src="https://g.alicdn.com/dingding/dingtalk-jsapi/3.1.0/dingtalk.open.js"></script>
  <script>
    var AUTH_URL = "{{ auth_url }}";
    var CORP_ID = "{{ corp_id }}";

    function showError(msg, steps) {
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('message').textContent = msg;
      document.getElementById('message').style.color = '#e53e3e';
      if (steps && steps.length) {
        var s = document.getElementById('steps');
        s.style.display = 'block';
        s.innerHTML = '<div style="font-weight:600;margin-bottom:6px;">调用链路：</div>';
        steps.forEach(function(step) {
          var cls = step.ok ? 'ok' : 'fail';
          var icon = step.ok ? '&#10003;' : '&#10007;';
          var detail = step.detail ? '<div class="detail">' + step.detail + '</div>' : '';
          if (step.api) detail += '<div class="detail">' + step.api + '</div>';
          s.innerHTML += '<div class="step ' + cls + '"><span class="label">' + icon + ' ' + step.step + '</span> ' + step.msg + detail + '</div>';
        });
      }
    }

    function showMessage(msg) {
      document.getElementById('message').textContent = msg;
    }

    function submitZKH(formData) {
      var form = document.getElementById('zkhForm');
      form.action = formData.checkin_url;
      for (var key in formData.form) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = key;
        input.value = formData.form[key];
        form.appendChild(input);
      }
      showMessage('正在进入震坤行，请稍候...');
      form.submit();
    }

    function doAuth() {
      showMessage('正在获取钉钉授权...');
      dd.ready(function () {
        dd.runtime.permission.requestAuthCode({
          corpId: CORP_ID,
          onSuccess: function (result) {
            showMessage('正在验证身份...');
            var xhr = new XMLHttpRequest();
            xhr.open('POST', AUTH_URL, true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.onload = function () {
              if (xhr.status === 200) {
                try {
                  var resp = JSON.parse(xhr.responseText);
                  if (resp.success && resp.form) {
                    submitZKH(resp);
                  } else {
                    showError(resp.error || 'SSO 登录失败', resp.zkh_steps);
                  }
                } catch (e) {
                  showError('数据解析失败');
                }
              } else {
                try {
                  var resp = JSON.parse(xhr.responseText);
                  showError(resp.error || '服务异常', resp.zkh_steps);
                } catch (e) {
                  showError('服务异常，请稍后重试');
                }
              }
            };
            xhr.onerror = function () {
              showError('网络异常，请检查连接');
            };
            xhr.send(JSON.stringify({ code: result.code }));
          },
          onFail: function (err) {
            showError('钉钉授权失败: ' + JSON.stringify(err));
          }
        });
      });
    }

    dd.error(function (err) {
      showError('钉钉初始化失败: ' + JSON.stringify(err));
    });
    doAuth();
  </script>
</body>
</html>
"""


@app.route("/dingtalk/sso")
def dingtalk_sso():
    """
    钉钉 H5 微应用入口
    用户在钉钉中打开此页面 → 自动免登 → 获取用户信息 → SSO 到震坤行
    """
    return render_template_string(
        DINGTALK_SSO_TEMPLATE,
        auth_url=f"{SELF_BASE_URL}/api/dingtalk/auth",
        corp_id=DINGTALK_CONFIG["corp_id"],
    )


@app.route("/api/dingtalk/auth", methods=["POST"])
def dingtalk_auth():
    """
    钉钉免登回调
    前端获取免登 code 后 POST 到此接口
    后端用 code 换用户信息，然后用 userid 做 ZKH SSO
    """
    data = request.get_json(force=True) or {}
    code = data.get("code", "")

    if not code:
        return jsonify({"error": "code is required"}), 400

    # 1. 用免登 code 换用户信息
    userinfo = dingtalk.get_userinfo_by_code(code)
    if not userinfo:
        return jsonify({"error": "Failed to get DingTalk user info"}), 500

    userid = userinfo.get("userid", "")
    name = userinfo.get("name", "")

    if not userid:
        return jsonify({"error": "No userid in response"}), 500

    logger.info(f"DingTalk user: {userid} ({name})")

    # 2. 获取用户详细信息（手机号、邮箱等）
    detail = dingtalk.get_user_detail(userid)
    mobile = detail.get("mobile", "") if detail else ""
    email = detail.get("email", "") if detail else ""

    # 3. 自动同步用户到震坤行
    steps = []
    client.ensure_token()
    user_result = client.user_sync("query", userid)
    if user_result and user_result.get("success"):
        steps.append({"step": "user_sync_query", "ok": True, "msg": "用户已存在"})
    else:
        steps.append({"step": "user_sync_query", "ok": False, "msg": "用户不存在，准备创建"})
        create_result = client.user_sync("insert", userid, nickName=name, email=email, mobile=mobile, roleName="采购员", stateCode=1)
        if create_result and create_result.get("success"):
            steps.append({"step": "user_sync_insert", "ok": True, "msg": "用户创建成功"})
        else:
            steps.append({"step": "user_sync_insert", "ok": False, "msg": "用户创建失败", "detail": _api_detail(create_result)})

    # 4. 获取信任登录标识
    strust_result = client.get_trusted_login(userid)
    if not strust_result:
        # 使用震坤行实际返回的错误信息
        last_err = client._last_error
        err_detail = _api_detail(last_err) if last_err else "无响应"
        return jsonify({
            "success": False,
            "error": f"震坤行 trustedLogin 失败: {err_detail}",
            "userid": userid,
            "name": name,
            "zkh_steps": steps + [{"step": "trustedLogin", "ok": False, "msg": "获取信任登录标识失败", "api": "POST /punchout/m2/strustNo", "detail": err_detail}],
        }), 500
    steps.append({"step": "trustedLogin", "ok": True, "msg": f"strustNo={strust_result}"})

    # 5. 构建 checkIn 表单
    hook_url = f"{SELF_BASE_URL}/api/zkh/checkout"
    form = client.build_checkin_form(userid, strust_result, hook_url)
    steps.append({"step": "checkIn", "ok": True, "msg": "表单构建完成"})

    return jsonify({
        "success": True,
        "userid": userid,
        "name": name,
        "checkin_url": f"{client.api_base}/strust/checkIn",
        "form": form,
        "zkh_steps": steps,
    })


# ==================== 订单回传（checkOut 回调）====================

@app.route("/api/zkh/checkout", methods=["POST"])
def checkout_callback():
    """
    震坤行订单回传接口（checkOut）
    用户在震坤行提交订单后，震坤行回调此接口推送预订单信息

    收到订单后：
    1. 验证签名
    2. 保存订单
    3. 创建审批记录（状态=待审批）
    4. 返回 success
    """
    data = request.get_json(force=True)
    logger.info(f"Checkout received: orderId={data.get('orderId')}")

    # 验证签名
    if not store.verify_checkout_sign(data):
        logger.warning(f"Invalid sign for order {data.get('orderId')}")
        return jsonify({"success": False, "resultMessage": "Invalid sign"}), 400

    # 解析并保存订单
    order = OrderData.from_checkout(data)
    store.save_order(order)

    # 自动创建钉钉审批
    instance_id = approval.create_approval(order)
    if instance_id:
        logger.info(f"Approval instance created for order {order.order_id}: {instance_id}")
    else:
        logger.warning(f"Failed to create approval for order {order.order_id}")

    return jsonify({
        "success": True,
        "resultCode": "0000",
        "resultMessage": "success",
    })


# ==================== 审批管理 ====================

@app.route("/api/zkh/orders/pending")
def list_pending_orders():
    """查看待审批订单列表"""
    pending = store.list_pending()
    return jsonify({"count": len(pending), "orders": pending})


@app.route("/api/zkh/orders/<order_id>/detail")
def get_order_detail(order_id: str):
    """查看订单详情"""
    order = store.get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    approval = store.get_approval(order_id)
    return jsonify({
        "order": order.to_dict(),
        "approval_status": approval.status.value if approval else "unknown",
    })


@app.route("/api/zkh/orders/<order_id>/approve", methods=["POST"])
def approve_order(order_id: str):
    """
    审批通过订单

    流程：
    1. 更新审批状态为"已通过"
    2. 生成客户侧订单号
    3. 调用震坤行 confirmOrder 接口确认订单
    4. 确认后震坤行开始配货

    请求体：
        approver: 审批人
        third_order: 客户侧订单号（可选，不传自动生成）
    """
    data = request.get_json(force=True) or {}
    approver = data.get("approver", "system")
    third_order = data.get("third_order", f"PO{order_id}")

    # 1. 更新审批状态
    record = store.approve_order(order_id, approver, third_order)
    if not record:
        return jsonify({"error": "Order not found or already processed"}), 400

    # 2. 调用震坤行确认订单
    success = client.confirm_order(order_id, third_order)
    if not success:
        # 回滚审批状态？取决于业务需求
        logger.error(f"Confirm order failed for {order_id}")
        return jsonify({
            "error": "Approval recorded but confirmOrder API failed",
            "order_id": order_id,
            "third_order": third_order,
        }), 500

    return jsonify({
        "success": True,
        "order_id": order_id,
        "third_order": third_order,
        "status": "approved",
        "message": "订单已确认，震坤行开始配货",
    })


@app.route("/api/zkh/orders/<order_id>/reject", methods=["POST"])
def reject_order(order_id: str):
    """
    审批拒绝订单

    流程：
    1. 更新审批状态为"已拒绝"
    2. 调用震坤行 cancel 接口取消订单
    """
    data = request.get_json(force=True) or {}
    approver = data.get("approver", "system")
    reason = data.get("reason", "")

    # 1. 更新审批状态
    record = store.reject_order(order_id, approver, reason)
    if not record:
        return jsonify({"error": "Order not found or already processed"}), 400

    # 2. 调用震坤行取消订单
    success = client.cancel_order(order_id)
    if not success:
        logger.warning(f"Cancel order failed for {order_id}")

    return jsonify({
        "success": True,
        "order_id": order_id,
        "status": "rejected",
        "reason": reason,
    })


# ==================== 消息拉取 ====================

@app.route("/api/zkh/messages")
def get_messages():
    """
    拉取震坤行消息（订单状态变更通知）
    建议定时任务调用，处理完后删除消息
    """
    msg_type = request.args.get("type", type=int)
    messages = client.get_messages(msg_type)
    if messages is None:
        return jsonify({"error": "Failed to fetch messages"}), 500

    # 处理消息并删除
    results = []
    for msg in messages:
        msg_id = msg.get("id", "")
        msg_type_val = msg.get("type")
        order_id = msg.get("orderId", "")

        # 根据消息类型处理业务逻辑
        if msg_type_val == 5:
            logger.info(f"Delivery status change: order={order_id}")
        elif msg_type_val == 101:
            logger.info(f"Order shipped: order={order_id}, package={msg.get('packageId')}")

        # 处理成功后删除消息
        client.delete_message(msg_id)
        results.append(msg)

    return jsonify({"count": len(results), "messages": results})


# ==================== 用户同步 ====================

@app.route("/api/zkh/users/sync", methods=["POST"])
def sync_user():
    """
    同步用户到震坤行
    请求体：{"opt": "insert", "unique_no": "xxx", "nick_name": "张三", ...}
    """
    data = request.get_json(force=True) or {}
    opt = data.pop("opt", "query")
    unique_no = data.pop("unique_no", "")

    if not unique_no:
        return jsonify({"error": "unique_no is required"}), 400

    # 字段名映射
    field_map = {
        "nick_name": "nickName",
        "email": "email",
        "mobile": "mobile",
        "role_name": "roleName",
        "invoice_customer_names": "invoiceCustomerNames",
        "state_code": "stateCode",
    }
    kwargs = {field_map.get(k, k): v for k, v in data.items()}

    result = client.user_sync(opt, unique_no, **kwargs)
    return jsonify(result or {})


# ==================== 审批回调 ====================

@app.route("/api/zkh/approval/callback", methods=["GET", "POST"])
def approval_callback():
    """
    钉钉审批事件回调接口
    GET: 事件订阅 URL 验证
    POST: 接收审批结果推送
    """
    if request.method == "GET":
        # 钉钉事件订阅 URL 验证
        return _handle_callback_verify()

    # POST: 处理审批事件
    try:
        raw_data = request.get_json(force=True, silent=True) or {}
    except Exception:
        raw_data = {}

    # 钉钉回调可能是加密的 {"encrypt": "..."} 或明文的 JSON
    if "encrypt" in raw_data:
        event_data = _decrypt_callback(raw_data.get("encrypt", ""))
    else:
        event_data = raw_data

    if not event_data:
        return jsonify({"errcode": 0, "errmsg": "ok"})

    logger.info(f"Approval callback received: {json.dumps(event_data, ensure_ascii=False)[:500]}")

    success = approval.handle_callback(event_data)
    if success:
        return jsonify({"errcode": 0, "errmsg": "ok"})
    else:
        return jsonify({"errcode": 0, "errmsg": "ok"})  # 告诉钉钉已收到，避免重复推送


def _handle_callback_verify():
    """处理钉钉事件订阅 URL 验证（GET 请求）"""
    import time as _time
    import hashlib as _hashlib
    import base64 as _base64

    signature = request.args.get("signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")
    echostr = request.args.get("echostr", "")

    token = APPROVAL_CONFIG["callback_token"]
    if not token:
        logger.warning("DINGTALK_CALLBACK_TOKEN not configured, returning echostr directly")
        return echostr

    # 验证签名
    tmp_arr = sorted([token, timestamp, nonce])
    tmp_str = "".join(tmp_arr)
    tmp_sign = _hashlib.sha1(tmp_str.encode()).hexdigest()

    if tmp_sign != signature:
        logger.warning(f"Callback verify signature mismatch")
        return "signature error", 403

    # 解密 echostr
    aes_key = APPROVAL_CONFIG["callback_aes_key"]
    if aes_key:
        try:
            from Crypto.Cipher import AES
            key = _base64.b64decode(aes_key + "=")
            cipher = AES.new(key, AES.MODE_CBC, key[:16])
            plain = cipher.decrypt(_base64.b64decode(echostr))
            # 去除 PKCS7 padding
            pad = plain[-1]
            plain = plain[:-pad]
            # 解析: 16字节随机 + 4字节长度 + 内容 + corpId
            content_len = int.from_bytes(plain[16:20], "big")
            content = plain[20:20 + content_len].decode("utf-8")
            return content
        except ImportError:
            logger.warning("pycryptodome not installed, cannot decrypt callback")
            return echostr

    return echostr


def _decrypt_callback(encrypt_str: str) -> dict:
    """解密钉钉回调加密数据"""
    import base64 as _base64

    aes_key = APPROVAL_CONFIG["callback_aes_key"]
    if not aes_key:
        logger.warning("DINGTALK_CALLBACK_AES_KEY not configured, cannot decrypt")
        return {}

    try:
        from Crypto.Cipher import AES
        key = _base64.b64decode(aes_key + "=")
        cipher = AES.new(key, AES.MODE_CBC, key[:16])
        plain = cipher.decrypt(_base64.b64decode(encrypt_str))
        pad = plain[-1]
        plain = plain[:-pad]
        content_len = int.from_bytes(plain[16:20], "big")
        content = plain[20:20 + content_len].decode("utf-8")
        return json.loads(content)
    except ImportError:
        logger.warning("pycryptodome not installed, cannot decrypt callback")
        return {}
    except Exception as e:
        logger.error(f"Callback decrypt error: {e}")
        return {}


# ==================== 健康检查 ====================

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ==================== 启动 ====================

if __name__ == "__main__":
    print("=" * 60)
    print("震坤行 Punch-Out 集成服务")
    print(f"SSO 入口:     GET  {SELF_BASE_URL}/api/zkh/sso?unique_no=xxx")
    print(f"钉钉免登:     GET  {SELF_BASE_URL}/dingtalk/sso")
    print(f"订单回调:     POST {SELF_BASE_URL}/api/zkh/checkout")
    print(f"待审批列表:   GET  {SELF_BASE_URL}/api/zkh/orders/pending")
    print(f"审批通过:     POST {SELF_BASE_URL}/api/zkh/orders/<id>/approve")
    print(f"审批拒绝:     POST {SELF_BASE_URL}/api/zkh/orders/<id>/reject")
    print("=" * 60)
    app.run(host="0.0.0.0", port=5000, debug=True)