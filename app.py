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

from zkh_punchout.client import ZKHClient
from zkh_punchout.order import OrderData, OrderApprovalStore, ApprovalStatus
from zkh_punchout.dingtalk import DingTalkClient

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
}

# ==================== 初始化 ====================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

client = ZKHClient(**ZKH_CONFIG)
store = OrderApprovalStore()
dingtalk = DingTalkClient(DINGTALK_CONFIG["app_key"], DINGTALK_CONFIG["app_secret"])

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
</style>
</head>
<body>
  <div class="container">
    <div class="logo">震坤行采购平台</div>
    <div class="spinner" id="spinner"></div>
    <p class="message" id="message">正在获取钉钉授权...</p>
    <p class="error" id="error"></p>
  </div>
  <form id="zkhForm" action="" method="post" enctype="multipart/form-data"></form>

  <script src="https://g.alicdn.com/dingding/dingtalk-jsapi/3.1.0/dingtalk.open.js"></script>
  <script>
    var AUTH_URL = "{{ auth_url }}";
    var CORP_ID = "{{ corp_id }}";

    function showError(msg) {
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('message').textContent = msg;
      document.getElementById('message').style.color = '#e53e3e';
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
                  if (resp.success && resp.checkin_form) {
                    submitZKH(resp);
                  } else {
                    showError(resp.error || 'SSO 登录失败');
                  }
                } catch (e) {
                  showError('数据解析失败');
                }
              } else {
                showError('服务异常，请稍后重试');
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
        corp_id=dingtalk.app_key if dingtalk.app_key.startswith("ding") else "",
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
    if not client.ensure_user(userid, name, email, mobile):
        logger.warning(f"Failed to ensure ZKH user: {userid}")

    # 4. SSO 登录震坤行
    hook_url = f"{SELF_BASE_URL}/api/zkh/checkout"
    result = client.sso_login(userid, hook_url)
    if not result:
        return jsonify({"error": "ZKH SSO login failed"}), 500

    return jsonify({
        "success": True,
        "userid": userid,
        "name": name,
        "checkin_url": result["checkin_url"],
        "form": result["checkin_form"],
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

    # TODO: 触发审批通知（如发送邮件、钉钉消息等）
    # notify_approvers(order)

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