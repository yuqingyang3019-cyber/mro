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
import uuid
import time
from flask import Flask, request, jsonify, render_template_string
from dotenv import load_dotenv

load_dotenv()

from zkh_punchout.client import ZKHClient
from zkh_punchout.order import OrderData, OrderApprovalStore, ApprovalStatus
from zkh_punchout.dingtalk import DingTalkClient
from zkh_punchout.approval import ApprovalService
from zkh_punchout.callback_crypto import DingCallbackCrypto

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
    # 事件订阅 OWNER_KEY 应为 appKey，注册回调地址用 corpId
    # 见: https://open.dingtalk.com/document/orgapp/configure-http-push
    "callback_owner_key": os.getenv("DINGTALK_CALLBACK_OWNER_KEY", DINGTALK_CONFIG["app_key"]),
}

API_KEY = os.getenv("API_KEY", "")

# ==================== SSO Token 存储（文件） ====================
# gunicorn 多 worker 之间内存不共享，必须用文件存储

import tempfile

_SSO_TOKEN_DIR = os.path.join(tempfile.gettempdir(), "mro_sso_tokens")
os.makedirs(_SSO_TOKEN_DIR, exist_ok=True)
SSO_TOKEN_TTL = 300  # 5 分钟有效

# ==================== 初始化 ====================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

client = ZKHClient(**ZKH_CONFIG)
store = OrderApprovalStore(db_path="data/mro.db")
dingtalk = DingTalkClient(DINGTALK_CONFIG["app_key"], DINGTALK_CONFIG["app_secret"])
approval = ApprovalService(
    dingtalk=dingtalk,
    store=store,
    process_code=APPROVAL_CONFIG["process_code"],
    approver_user_id=APPROVAL_CONFIG["approver_user_id"],
    zkh_client=client,
)

# 初始化钉钉回调加解密
_callback_crypto = None
if APPROVAL_CONFIG["callback_token"] and APPROVAL_CONFIG["callback_aes_key"]:
    _callback_crypto = DingCallbackCrypto(
        token=APPROVAL_CONFIG["callback_token"],
        encoding_aes_key=APPROVAL_CONFIG["callback_aes_key"],
        owner_key=APPROVAL_CONFIG["callback_owner_key"],
    )
    logger.info("DingCallbackCrypto initialized")
else:
    logger.warning("DingTalk callback crypto NOT configured (missing token or aes_key)")


def _api_detail(resp: dict) -> str:
    """提取 API 响应的错误详情"""
    if not resp:
        return "无响应"
    return f"[{resp.get('resultCode', '?')}] {resp.get('resultMessage', '未知错误')}"


def _require_api_key():
    """验证 API Key 鉴权，未配置 API_KEY 时跳过验证"""
    if not API_KEY:
        return True
    auth = request.headers.get("X-API-Key", "")
    return auth == API_KEY


def _store_sso_and_get_url(checkin_url: str, form: dict) -> str:
    """存储 SSO 表单数据到文件，返回一次性 launch URL"""
    token = str(uuid.uuid4())
    token_path = os.path.join(_SSO_TOKEN_DIR, f"{token}.json")
    with open(token_path, "w") as f:
        json.dump({
            "checkin_url": checkin_url,
            "form": form,
            "expires_at": time.time() + SSO_TOKEN_TTL,
        }, f)
    return f"{SELF_BASE_URL}/dingtalk/launch?token={token}"


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
  .btn {
    display: none;
    margin-top: 24px;
    padding: 14px 48px;
    background: #2563eb;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 16px;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
  }
  .btn:hover { background: #1d4ed8; }
  .btn:active { background: #1e40af; }
</style>
</head>
<body>
  <div class="container">
    <div class="logo">震坤行采购平台</div>
    <div class="spinner" id="spinner"></div>
    <p class="message" id="message">正在获取钉钉授权...</p>
    <p class="error" id="error"></p>
    <div class="steps" id="steps"></div>
    <a class="btn" id="enterBtn" href="#">进入震坤行采购平台</a>
  </div>

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

    function showSuccess(launchUrl) {
      document.getElementById('spinner').style.display = 'none';
      document.getElementById('message').textContent = '身份验证成功';
      document.getElementById('message').style.color = '#22c55e';
      var btn = document.getElementById('enterBtn');
      btn.style.display = 'inline-block';
      btn.href = launchUrl;
    }

    function openZKH(launchUrl) {
      dd.ready(function() {
        dd.biz.util.openLink({
          url: launchUrl,
          onSuccess: function() {
        // 打开成功后跳转到采购看板，不再关闭页面
        window.location.href = '/dingtalk/dashboard';
      },
          onFail: function(err) {
            // 降级：直接跳转
            window.location.href = launchUrl;
          }
        });
      });
      return false;  // 阻止默认链接行为
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
                  if (resp.success && resp.launch_url) {
                    showSuccess(resp.launch_url);
                    // 自动打开
                    setTimeout(function() {
                      openZKH(resp.launch_url);
                    }, 500);
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

    // 绑定按钮点击
    document.getElementById('enterBtn').onclick = function() {
      return openZKH(this.href);
    };

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

    # 2.5. 校验用户是否属于本企业（通过 dept_id_list 判断）
    # 应用已绑定沃乐 corpId，get_user_detail 返回的 dept_id_list 非空即表示用户属于该企业
    dept_id_list = detail.get("dept_id_list", []) if detail else []
    if not dept_id_list:
        logger.warning(f"User {userid} has no department, not a valid enterprise member")
        return jsonify({
            "success": False,
            "error": "企业校验失败：非本企业员工或用户信息不完整",
            "userid": userid,
            "name": name,
        }), 403
    logger.info(f"Enterprise check passed: user {userid} in depts {dept_id_list}")

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
        "launch_url": _store_sso_and_get_url(
            checkin_url=f"{client.api_base}/strust/checkIn",
            form=form,
        ),
        "zkh_steps": steps,
    })


# ==================== 订单回传（checkOut 回调）====================


LAUNCH_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>正在进入震坤行</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f5f6fa;
    display: flex; justify-content: center; align-items: center;
    min-height: 100vh; text-align: center;
  }
  .spinner {
    width: 36px; height: 36px; margin: 0 auto 16px;
    border: 3px solid #e0e0e0; border-top-color: #2563eb;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .message { color: #666; font-size: 14px; }
</style>
</head>
<body>
  <div style="padding: 48px 24px;">
    <div class="spinner"></div>
    <p class="message">正在进入震坤行采购平台...</p>
  </div>
  <form id="zkhForm" action="{{ checkin_url }}" method="post" enctype="multipart/form-data">
    {% for key, value in form.items() %}
    <input type="hidden" name="{{ key }}" value="{{ value }}">
    {% endfor %}
  </form>
  <script>
    document.getElementById('zkhForm').submit();
  </script>
</body>
</html>
"""


@app.route("/dingtalk/launch")
def dingtalk_launch():
    """SSO 跳转页：从文件 token 取出表单数据，自动提交到震坤行"""
    token = request.args.get("token", "")
    token_path = os.path.join(_SSO_TOKEN_DIR, f"{token}.json")

    try:
        with open(token_path, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return "<h3 style='text-align:center;padding:40px;'>链接已过期，请重新从钉钉进入</h3>", 400

    # 用完即删
    os.remove(token_path)

    if time.time() > data.get("expires_at", 0):
        return "<h3 style='text-align:center;padding:40px;'>链接已过期，请重新从钉钉进入</h3>", 400

    return render_template_string(
        LAUNCH_TEMPLATE,
        checkin_url=data["checkin_url"],
        form=data["form"],
    )


DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>采购看板</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #f0f2f5;
    color: #1a1a2e;
    padding-bottom: 24px;
  }
  .header {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    color: #fff;
    padding: 20px 16px 24px;
    text-align: center;
  }
  .header h1 { font-size: 20px; font-weight: 700; }
  .header .sub { font-size: 12px; opacity: 0.8; margin-top: 4px; }
  .tabs {
    display: flex; margin: -12px 12px 0; position: relative; z-index: 1;
  }
  .tab {
    flex: 1; text-align: center; padding: 10px 0; font-size: 14px;
    font-weight: 600; color: #fff; background: rgba(255,255,255,0.15);
    border-radius: 8px 8px 0 0; cursor: pointer; transition: background 0.2s;
    margin: 0 2px;
  }
  .tab.active { background: #f0f2f5; color: #2563eb; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }
  .cards {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    padding: 16px 12px;
    margin-top: -12px;
  }
  .card {
    background: #fff;
    border-radius: 10px;
    padding: 14px 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.06);
    text-align: center;
  }
  .card .label { font-size: 11px; color: #888; margin-bottom: 4px; }
  .card .value { font-size: 22px; font-weight: 700; }
  .card .value.blue { color: #2563eb; }
  .card .value.orange { color: #f59e0b; }
  .card .value.green { color: #22c55e; }
  .card .value.purple { color: #8b5cf6; }
  .btn-wrap { padding: 0 12px 16px; text-align: center; }
  .btn {
    display: inline-block; width: 100%; max-width: 320px;
    padding: 14px 0; background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    color: #fff; border: none; border-radius: 10px;
    font-size: 16px; font-weight: 600; text-decoration: none; cursor: pointer;
    box-shadow: 0 2px 8px rgba(37,99,235,0.3);
  }
  .btn:active { opacity: 0.9; }
  .section {
    background: #fff; border-radius: 10px; margin: 0 12px 12px;
    padding: 16px 12px; box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  }
  .section h3 {
    font-size: 14px; font-weight: 600; color: #333;
    margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #f0f0f0;
  }
  .order-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .order-table th {
    background: #f8f9fa; padding: 8px 6px; text-align: left;
    font-weight: 600; color: #555; border-bottom: 1px solid #eee;
    position: sticky; top: 0;
  }
  .order-table td {
    padding: 8px 6px; border-bottom: 1px solid #f5f5f5; vertical-align: middle;
  }
  .order-table tr { cursor: pointer; }
  .order-table tr:active { background: #f0f4ff; }
  .order-table .oid { color: #2563eb; font-family: monospace; font-size: 11px; }
  .order-table .price { font-weight: 600; white-space: nowrap; }
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600;
  }
  .badge.pending { background: #fef3c7; color: #b45309; }
  .badge.approved { background: #dcfce7; color: #15803d; }
  .badge.rejected { background: #fee2e2; color: #b91c1c; }
  .badge.cancelled { background: #f3f4f6; color: #6b7280; }
  .table-scroll { max-height: 500px; overflow-y: auto; }
  .loading { text-align: center; padding: 40px; color: #888; }
  .spinner {
    width: 28px; height: 28px; margin: 0 auto 12px;
    border: 3px solid #e0e0e0; border-top-color: #2563eb;
    border-radius: 50%; animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  .empty { text-align: center; padding: 32px; color: #aaa; font-size: 13px; }

  /* 详情弹窗 */
  .overlay {
    display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.4); z-index: 100; justify-content: center; align-items: flex-end;
  }
  .overlay.show { display: flex; }
  .detail-panel {
    background: #fff; width: 100%; max-height: 85vh; border-radius: 16px 16px 0 0;
    overflow-y: auto; padding: 20px 16px 32px; animation: slideUp 0.25s ease;
  }
  @keyframes slideUp { from { transform: translateY(100%); } to { transform: translateY(0); } }
  .detail-panel h2 { font-size: 17px; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
  .detail-panel .close-btn {
    margin-left: auto; width: 28px; height: 28px; border: none; background: #f0f0f0;
    border-radius: 50%; font-size: 16px; cursor: pointer; line-height: 28px; text-align: center;
  }
  .detail-row {
    display: flex; justify-content: space-between; padding: 8px 0;
    border-bottom: 1px solid #f5f5f5; font-size: 13px;
  }
  .detail-row .dl { color: #888; flex-shrink: 0; }
  .detail-row .dv { color: #333; text-align: right; word-break: break-all; }
  .detail-section { margin-top: 16px; }
  .detail-section h4 {
    font-size: 13px; font-weight: 600; color: #555;
    margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #eee;
  }
  .sku-item {
    padding: 8px 0; border-bottom: 1px solid #f5f5f5; font-size: 12px;
  }
  .sku-item .sku-name { font-weight: 600; color: #333; }
  .sku-item .sku-meta { color: #888; margin-top: 2px; }
  .detail-loading { text-align: center; padding: 40px; color: #888; }
</style>
</head>
<body>
  <div class="header">
    <h1>震坤行采购看板</h1>
    <div class="sub">订单记录与审批追踪</div>
  </div>

  <div class="cards" id="cards">
    <div class="card"><div class="label">总订单</div><div class="value blue" id="val-total">-</div></div>
    <div class="card"><div class="label">待审批</div><div class="value orange" id="val-pending">-</div></div>
    <div class="card"><div class="label">总金额</div><div class="value green" id="val-amount">-</div></div>
    <div class="card"><div class="label">已通过</div><div class="value purple" id="val-approved">-</div></div>
  </div>

  <div class="btn-wrap">
    <a class="btn" href="javascript:void(0)" onclick="enterZKH()">进入震坤行采购</a>
  </div>

  <div class="section">
    <h3>订单列表</h3>
    <div class="table-scroll" id="orderTable">
      <div class="loading"><div class="spinner"></div>加载中...</div>
    </div>
  </div>

  <!-- 详情弹窗 -->
  <div class="overlay" id="detailOverlay" onclick="if(event.target===this)closeDetail()">
    <div class="detail-panel" id="detailPanel">
      <div class="detail-loading"><div class="spinner"></div>加载详情...</div>
    </div>
  </div>

  <script>
    var STATUS_LABELS = {pending: '待审批', approved: '已通过', rejected: '已拒绝', cancelled: '已取消'};

    function fmtMoney(n) {
      n = Number(n) || 0;
      if (n >= 10000) return '¥' + (n / 10000).toFixed(1) + '万';
      return '¥' + n.toLocaleString('zh-CN', {minimumFractionDigits: 0, maximumFractionDigits: 0});
    }

    function renderCards(stats) {
      document.getElementById('val-total').textContent = stats.total_orders;
      document.getElementById('val-pending').textContent = stats.status_counts.pending || 0;
      document.getElementById('val-amount').textContent = fmtMoney(stats.total_amount);
      document.getElementById('val-approved').textContent = stats.status_counts.approved || 0;
    }

    function renderOrderTable(orders) {
      var container = document.getElementById('orderTable');
      if (!orders || orders.length === 0) {
        container.innerHTML = '<div class="empty">暂无订单记录</div>';
        return;
      }
      var html = '<table class="order-table"><thead><tr><th>订单号</th><th>金额</th><th>状态</th><th>时间</th></tr></thead><tbody>';
      orders.forEach(function(o) {
        var oid = (o.order_id || '').substring(0, 16);
        html += '<tr onclick="showDetail(\'' + o.order_id + '\')">' +
          '<td><span class="oid">' + oid + '</span></td>' +
          '<td class="price">' + fmtMoney(o.order_price) + '</td>' +
          '<td><span class="badge ' + o.status + '">' + (STATUS_LABELS[o.status] || o.status) + '</span></td>' +
          '<td style="font-size:11px;color:#888;">' + (o.created_at || '-') + '</td>' +
          '</tr>';
      });
      html += '</tbody></table>';
      container.innerHTML = html;
    }

    function showDetail(orderId) {
      var overlay = document.getElementById('detailOverlay');
      var panel = document.getElementById('detailPanel');
      overlay.classList.add('show');
      panel.innerHTML = '<div class="detail-loading"><div class="spinner"></div>加载详情...</div>';

      fetch('/api/zkh/orders/' + orderId + '/detail')
        .then(function(r) { return r.json(); })
        .then(function(data) { renderDetail(data, orderId); })
        .catch(function() { panel.innerHTML = '<div class="detail-loading">加载失败</div>'; });
    }

    function closeDetail() {
      document.getElementById('detailOverlay').classList.remove('show');
    }

    function renderDetail(data, orderId) {
      var order = data.order || {};
      var skuList = order.sku_list || [];
      var status = data.approval_status || 'unknown';

      var html = '<h2>' +
        '<span class="badge ' + status + '">' + (STATUS_LABELS[status] || status) + '</span>' +
        ' ' + (orderId || '').substring(0, 16) +
        '<button class="close-btn" onclick="closeDetail()">✕</button></h2>';

      // 基本信息
      html += '<div class="detail-section"><h4>基本信息</h4>';
      html += kv('订单号', order.order_id);
      html += kv('下单公司', order.company_name);
      html += kv('采购账号', order.purchase_account);
      html += kv('采购组织', order.purchase_org);
      html += kv('下单时间', data.order ? (order.created_at || '-') : '-');
      html += '</div>';

      // 金额
      html += '<div class="detail-section"><h4>金额汇总</h4>';
      html += kv('含税总额', fmtMoney(order.order_price));
      html += kv('不含税金额', fmtMoney(order.order_naked_price));
      html += kv('税额', fmtMoney(order.order_tax_price));
      html += kv('运费', fmtMoney(order.freight));
      html += '</div>';

      // 商品明细
      if (skuList.length > 0) {
        html += '<div class="detail-section"><h4>商品明细（' + skuList.length + ' 项）</h4>';
        skuList.forEach(function(sku, i) {
          html += '<div class="sku-item">' +
            '<div class="sku-name">' + (i+1) + '. ' + (sku.name || sku.sku_id || '-') + '</div>' +
            '<div class="sku-meta">数量: ' + (sku.num || 0) +
            ' | 含税单价: ' + fmtMoney(sku.price) +
            ' | 不含税: ' + fmtMoney(sku.naked_price) +
            ' | 税率: ' + (sku.tax || 0) + '%</div>' +
            '</div>';
        });
        html += '</div>';
      }

      // 收货信息
      html += '<div class="detail-section"><h4>收货信息</h4>';
      html += kv('收货人', order.name);
      html += kv('手机', order.mobile);
      html += kv('地址', order.address);
      html += kv('发货备注', order.delivery_remark == 2 ? '工作日' : order.delivery_remark == 1 ? '任意时间' : '未指定');
      html += '</div>';

      // 发票信息
      html += '<div class="detail-section"><h4>发票信息</h4>';
      html += kv('收票人', order.invoice_name);
      html += kv('收票电话', order.invoice_phone);
      html += kv('收票地址', order.invoice_address);
      html += '</div>';

      // 审批信息
      html += '<div class="detail-section"><h4>审批信息</h4>';
      html += kv('审批状态', STATUS_LABELS[status] || status);
      html += kv('审批人', order.approver || '-');
      html += kv('审批时间', order.approve_time || '-');
      html += kv('拒绝原因', order.reject_reason || '-');
      html += '</div>';

      // 备注
      if (order.remark) {
        html += '<div class="detail-section"><h4>备注</h4>';
        html += '<div style="font-size:13px;color:#555;padding:8px 0;">' + order.remark + '</div></div>';
      }

      document.getElementById('detailPanel').innerHTML = html;
    }

    function kv(label, value) {
      var v = value || '-';
      return '<div class="detail-row"><span class="dl">' + label + '</span><span class="dv">' + v + '</span></div>';
    }

    function loadDashboard() {
      var ts = '?t=' + Date.now();
      Promise.all([
        fetch('/api/zkh/orders/stats' + ts).then(function(r) { return r.json(); }),
        fetch('/api/zkh/orders/all?page=1&size=50&_t=' + Date.now()).then(function(r) { return r.json(); })
      ]).then(function(results) {
        renderCards(results[0]);
        renderOrderTable(results[1].orders);
      }).catch(function(err) {
        console.error('Dashboard load error:', err);
        document.getElementById('orderTable').innerHTML = '<div class="empty" style="color:#e53e3e;">加载失败，请下拉刷新页面重试</div>';
        var cards = ['val-total', 'val-pending', 'val-amount', 'val-approved'];
        cards.forEach(function(id) { document.getElementById(id).textContent = '?'; });
      });
    }

    function enterZKH() {
      var params = new URLSearchParams(window.location.search);
      var launchUrl = params.get('launch_url');
      if (launchUrl) {
        if (window.dd && dd.ready) {
          dd.ready(function() {
            dd.biz.util.openLink({
              url: launchUrl,
              onFail: function() { window.location.href = launchUrl; }
            });
          });
        } else {
          window.location.href = launchUrl;
        }
      }
    }

    loadDashboard();
  </script>
</body>
</html>
"""


@app.route("/dingtalk/dashboard")
def dingtalk_dashboard():
    """钉钉 H5 采购看板页面"""
    return render_template_string(DASHBOARD_TEMPLATE)


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
    logger.info(f"Checkout full body: {json.dumps(data, ensure_ascii=False)}")

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


@app.route("/api/zkh/orders/all")
def list_all_orders():
    """查看全量订单列表（含审批状态），支持分页 ?page=1&size=20"""
    page = request.args.get("page", 1, type=int)
    size = request.args.get("size", 20, type=int)
    return jsonify(store.list_all(page, size))


@app.route("/api/zkh/orders/stats")
def get_order_stats():
    """获取订单统计指标"""
    return jsonify(store.get_stats())


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


# ==================== 应用配置 ====================

@app.route("/api/config", methods=["GET"])
def get_config():
    """获取应用配置（需 API Key 鉴权）"""
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    return jsonify({
        "approver_user_id": store.get_config("approver_user_id") or APPROVAL_CONFIG["approver_user_id"],
    })


@app.route("/api/config", methods=["POST"])
def set_config():
    """更新应用配置（需 API Key 鉴权）"""
    if not _require_api_key():
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(force=True) or {}
    approver_user_id = data.get("approver_user_id", "").strip()
    if not approver_user_id:
        return jsonify({"error": "approver_user_id is required"}), 400
    store.set_config("approver_user_id", approver_user_id)
    logger.info(f"Config updated: approver_user_id={approver_user_id}")
    return jsonify({"success": True, "approver_user_id": approver_user_id})


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

    钉钉 POST 请求参数：
      - query params: msg_signature, timestamp, nonce
      - body: {"encrypt": "..."}

    处理流程（严格遵循钉钉官方文档）：
      1. 提取 query params 中的 msg_signature, timestamp, nonce
      2. 提取 body 中的 encrypt 密文
      3. 验证签名 → 解密 → 获取事件类型
      4. check_url: 返回加密的 "success" 响应
      5. bpms_instance_change: 处理审批事件
      6. 所有事件均返回加密的 "success" 响应
    """
    if request.method == "GET":
        return "ok"

    if not _callback_crypto:
        logger.error("DingCallbackCrypto not initialized, cannot process callback")
        return jsonify({"errcode": 0, "errmsg": "ok"})

    # 1. 从 query params 中提取加解密参数
    msg_signature = request.args.get("msg_signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")

    # 2. 从 body 中提取加密数据
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    encrypt_msg = body.get("encrypt", "")
    if not encrypt_msg:
        logger.warning(f"Callback missing encrypt field. body keys: {list(body.keys())}")
        logger.warning(f"Query params: msg_signature={msg_signature[:20]}..., timestamp={timestamp}, nonce={nonce}")
        return jsonify({"errcode": 0, "errmsg": "ok"})

    logger.info(f"Callback received: msg_signature={msg_signature[:20]}..., "
                f"timestamp={timestamp}, nonce={nonce}")

    # 3. 验证签名并解密
    try:
        decrypt_msg = _callback_crypto.get_decrypt_msg(
            msg_signature, timestamp, nonce, encrypt_msg
        )
    except ValueError as e:
        logger.error(f"Callback decrypt/signature error: {e}")
        return jsonify({"errcode": 0, "errmsg": "ok"})

    # 4. 解析事件数据
    try:
        event_data = json.loads(decrypt_msg)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decrypted event: {decrypt_msg[:200]}")
        return jsonify({"errcode": 0, "errmsg": "ok"})

    event_type = event_data.get("EventType", "")
    logger.info(f"Callback event: {event_type}, data: {json.dumps(event_data, ensure_ascii=False)[:500]}")

    # 5. 根据事件类型处理
    if event_type == "check_url":
        logger.info("URL verification (check_url) received, returning encrypted success")
    elif event_type in ("bpms_instance_change", "bpms_task_change"):
        approval.handle_callback(event_data)
    else:
        logger.info(f"Ignoring event type: {event_type}")

    # 6. 返回加密的 "success" 响应（钉钉要求在 2500ms 内响应）
    success_map = _callback_crypto.get_encrypted_map("success")
    logger.info(f"Callback response: msg_signature={success_map['msg_signature'][:20]}..., "
                f"timeStamp={success_map['timeStamp']}, nonce={success_map['nonce']}")
    return jsonify(success_map)


# ==================== 健康检查 ====================

@app.route("/health")
def health():
    status = {"status": "ok"}
    try:
        from Crypto.Cipher import AES
        status["crypto"] = "ok"
    except ImportError:
        status["crypto"] = "missing"
    status["callback_token"] = "set" if APPROVAL_CONFIG["callback_token"] else "missing"
    status["callback_aes_key"] = "set" if APPROVAL_CONFIG["callback_aes_key"] else "missing"
    status["callback_owner_key"] = (APPROVAL_CONFIG["callback_owner_key"][:8] + "..."
                                    if APPROVAL_CONFIG["callback_owner_key"] else "missing")
    status["callback_crypto_ready"] = _callback_crypto is not None
    return jsonify(status)


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