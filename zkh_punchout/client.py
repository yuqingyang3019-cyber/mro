"""
震坤行 Punch-Out API 客户端

封装所有 Punch-Out 接口调用，包括鉴权、SSO 登录、订单、发货、售后、消息等。
"""

import json
import time
import hashlib
import urllib.request
import urllib.error
import logging
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class ZKHClient:
    """震坤行 Punch-Out API 客户端"""

    def __init__(self, base_url: str, client_id: str, client_secret: str,
                 username: str, password: str):
        """
        :param base_url: API 基础地址，如 https://openapi.uat.zkh360.com
        :param client_id: 对接账号
        :param client_secret: 对接账号密码
        :param username: 鉴权用户
        :param password: 鉴权密码（MD5）
        """
        self.base_url = base_url.rstrip("/")
        self.api_base = f"{self.base_url}/punchout/m2"
        self.client_id = client_id
        self.client_secret = client_secret
        self.username = username
        self.password = password
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0
        self._last_error: Optional[Dict[str, Any]] = None

    # ==================== 工具方法 ====================

    @staticmethod
    def md5(s: str) -> str:
        return hashlib.md5(s.encode("utf-8")).hexdigest().upper()

    def _request(self, path: str, payload: Optional[Dict] = None,
                 need_token: bool = True, token_in_query: bool = False,
                 form_data: bool = False) -> Optional[Dict[str, Any]]:
        """
        通用请求方法
        :param path: 接口路径，如 "/accessToken"
        :param payload: 请求体
        :param need_token: 是否需要 token 鉴权
        :param token_in_query: token 是否放 query 参数
        :param form_data: 是否 form 表单提交
        """
        url = f"{self.api_base}{path}"

        if need_token and self._token and token_in_query:
            url += f"?token={self._token}"

        if form_data and payload:
            # multipart/form-data
            boundary = "----ZKHFormBoundary"
            body = b""
            for key, value in payload.items():
                body += f"--{boundary}\r\n".encode()
                body += f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode()
                body += f"{value}\r\n".encode()
            body += f"--{boundary}--\r\n".encode()
            headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        else:
            p = payload or {}
            if need_token and self._token and not token_in_query:
                p = {**p, "token": self._token}
            body = json.dumps(p).encode("utf-8")
            headers = {"Content-Type": "application/json; charset=UTF-8"}

        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            resp = urllib.request.urlopen(req, timeout=30)
            result = json.loads(resp.read())
            if result.get("success") and result.get("resultCode") == "0000":
                return result
            else:
                self._last_error = result
                logger.warning(f"API fail [{path}]: [{result.get('resultCode')}] {result.get('resultMessage')}")
                return result
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP error [{path}]: {e.code} {e.read()[:200]}")
            return None
        except Exception as e:
            logger.error(f"Request error [{path}]: {e}")
            return None

    # ==================== 一、鉴权 ====================

    def get_access_token(self) -> Optional[str]:
        """获取 accessToken，有效期 24h"""
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        r = self._request("/accessToken", {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "timestamp": ts,
            "username": self.username,
            "password": self.password,
        }, need_token=False)

        if r and r.get("success"):
            self._token = r["result"]["access_token"]
            self._token_expires_at = time.time() + r["result"]["expires_in"] - 60
            logger.info(f"Token obtained, expires in {r['result']['expires_in']}s")
            return self._token
        return None

    def ensure_token(self) -> bool:
        """确保 token 有效，过期自动刷新"""
        if not self._token or time.time() > self._token_expires_at:
            return self.get_access_token() is not None
        return True

    # ==================== 二、SSO 登录 ====================

    def get_trusted_login(self, unique_no: str, pin: str = "") -> Optional[str]:
        """
        获取信任登录标识 strustNo（有效期 30 分钟）
        :param unique_no: 客户侧用户唯一标识
        :param pin: 震坤行用户名（可选）
        :return: strustNo
        """
        self.ensure_token()
        ts_ms = int(time.time() * 1000)
        sign = self.md5(f"{pin}{unique_no}{ts_ms}")

        r = self._request("/strustNo", {
            "pin": pin,
            "uniqueNo": unique_no,
            "time": ts_ms,
            "sign": sign,
        }, token_in_query=True)

        if r and r.get("success"):
            strust_no = r.get("result")
            logger.info(f"TrustedLogin obtained: {strust_no}")
            return strust_no
        return None

    def build_checkin_form(self, unique_no: str, strust_no: str,
                           hook_url: str, pin: str = "",
                           custom_fields: Optional[Dict] = None) -> Dict[str, str]:
        """
        构建 checkIn 表单参数，前端用此参数提交 form 跳转震坤行
        :param unique_no: 客户侧用户唯一标识
        :param strust_no: 信任登录标识
        :param hook_url: 订单信息回传地址（客户提供的回调 URL）
        :param pin: 震坤行用户名（可选）
        :param custom_fields: 自定义参数，如发票抬头等
        :return: form 表单参数字典
        """
        app_id = "ESP"
        sign = self.md5(f"{pin}{unique_no}{strust_no}{app_id}")

        form = {
            "pin": pin,
            "strustNo": strust_no,
            "appId": app_id,
            "sign": sign,
            "uniqueNo": unique_no,
            "hookUrl": hook_url,
        }
        if custom_fields:
            form["customFields"] = json.dumps(custom_fields, ensure_ascii=False)

        return form

    def checkin(self, unique_no: str, strust_no: str, hook_url: str,
                pin: str = "", custom_fields: Optional[Dict] = None) -> Optional[str]:
        """
        直接调用 checkIn 接口（服务端调用，通常不推荐，建议前端 form 提交）
        :return: 响应 HTML（通常是重定向页面）
        """
        form = self.build_checkin_form(unique_no, strust_no, hook_url, pin, custom_fields)
        return self._request("/strust/checkIn", form, need_token=False, form_data=True)

    # ==================== 三、SSO 完整流程（便捷方法）====================

    def sso_login(self, unique_no: str, hook_url: str, pin: str = "",
                  custom_fields: Optional[Dict] = None) -> Optional[Dict[str, str]]:
        """
        一键完成 SSO 登录准备：获取 token → 获取 strustNo → 构建 checkIn 表单
        :return: {"strust_no": "...", "checkin_form": {...}, "checkin_url": "..."}
        """
        if not self.ensure_token():
            return None

        strust_no = self.get_trusted_login(unique_no, pin)
        if not strust_no:
            return None

        form = self.build_checkin_form(unique_no, strust_no, hook_url, pin, custom_fields)
        return {
            "strust_no": strust_no,
            "checkin_form": form,
            "checkin_url": f"{self.api_base}/strust/checkIn",
        }

    # ==================== 四、订单 ====================

    def confirm_order(self, order_id: str, third_order: str) -> bool:
        """
        确认预订单（审批通过后调用），确认后电商开始配货
        :param order_id: 震坤行订单号
        :param third_order: 客户侧订单号
        """
        self.ensure_token()
        r = self._request("/confirmOrder", {
            "orderId": order_id,
            "thirdOrder": third_order,
        })
        return r is not None and r.get("success", False)

    def cancel_order(self, order_id: str) -> bool:
        """
        取消订单（仅未确认前可取消）
        :param order_id: 震坤行订单号
        """
        self.ensure_token()
        r = self._request("/cancel", {"orderId": order_id})
        return r is not None and r.get("success", False)

    def update_order_detail(self, order_id: str, sku_info: List[Dict]) -> bool:
        """
        更新订单明细（审批通过前可修改）
        :param order_id: 震坤行订单号
        :param sku_info: [{"skuNo": "xxx", "count": 1}, ...] count=0 表示取消该行
        """
        self.ensure_token()
        r = self._request("/order/detail/update/v2", {
            "orderId": order_id,
            "skuInfo": sku_info,
        })
        return r is not None and r.get("success", False)

    # ==================== 五、发货 ====================

    def get_order_track(self, package_id: str) -> Optional[Dict]:
        """查询发货单物流轨迹"""
        self.ensure_token()
        return self._request("/orderTrack", {"packageId": package_id})

    def get_package_detail(self, package_id: str) -> Optional[Dict]:
        """查询发货单包裹明细"""
        self.ensure_token()
        return self._request("/package", {"packageId": package_id})

    def confirm_package(self, package_id: str) -> bool:
        """确认收货"""
        self.ensure_token()
        r = self._request("/confirmPackage", {"packageId": package_id})
        return r is not None and r.get("success", False)

    # ==================== 六、售后 ====================

    def create_service_order(self, order_number: str, service_type: int,
                             applicant: str, application_phone: str,
                             detail: List[Dict], description: str = "",
                             return_type: int = 2) -> Optional[str]:
        """
        申请售后
        :param order_number: 震坤行订单号
        :param service_type: 1=退货退款, 2=仅退款
        :param applicant: 申请人
        :param application_phone: 申请人电话
        :param detail: [{"skuId": "xxx", "num": 1}]
        :param description: 申请原因
        :param return_type: 1=供应商上门, 2=客户物流
        :return: serviceId
        """
        self.ensure_token()
        r = self._request("/serviceOrder", {
            "orderNumber": order_number,
            "serviceType": service_type,
            "applicant": applicant,
            "applicationPhone": application_phone,
            "detail": detail,
            "description": description,
            "returnType": return_type,
        })
        if r and r.get("success"):
            return r.get("result", {}).get("serviceId")
        return None

    def cancel_service_order(self, service_id: str) -> bool:
        """取消售后单（未审核前）"""
        self.ensure_token()
        r = self._request("/serviceOrder/cancel", {"serviceId": service_id})
        return r is not None and r.get("success", False)

    def fetch_service_order(self, service_id: str) -> Optional[Dict]:
        """查询售后单状态"""
        self.ensure_token()
        return self._request("/serviceOrder/fetch", {"serviceId": service_id})

    # ==================== 七、消息 ====================

    def get_messages(self, msg_type: Optional[int] = None) -> Optional[List[Dict]]:
        """
        拉取订单变更消息
        :param msg_type: 消息类型，不传返回全部
            5=妥投/拒收, 10=订单取消, 11=预订单生成, 33=正式订单生成,
            101=发货消息, 301=售后处理消息
        """
        self.ensure_token()
        payload = {}
        if msg_type is not None:
            payload["type"] = msg_type
        r = self._request("/get", payload)
        if r and r.get("success"):
            return r.get("result", [])
        return None

    def delete_message(self, msg_id: str) -> bool:
        """删除消息（处理成功后删除，否则后续消息不会返回）"""
        self.ensure_token()
        r = self._request("/delete", {"id": msg_id})
        return r is not None and r.get("success", False)

    # ==================== 八、账号 ====================

    def user_sync(self, opt: str, unique_no: str, **kwargs) -> Optional[Dict]:
        """
        同步人员信息
        :param opt: query / insert / update
        :param unique_no: 客户侧用户唯一标识
        :param kwargs: nickName, email, mobile, roleName, invoiceCustomerNames, stateCode
        """
        self.ensure_token()
        payload = {"opt": opt, "uniqueNo": unique_no, **kwargs}
        return self._request("/user/sync", payload)

    def ensure_user(self, unique_no: str, nick_name: str = "",
                    email: str = "", mobile: str = "",
                    role_name: str = "采购员") -> bool:
        """
        确保用户存在于震坤行：先查询，不存在则自动创建
        :param unique_no: 客户侧用户唯一标识
        :param nick_name: 姓名
        :param email: 邮箱
        :param mobile: 手机号
        :param role_name: 角色（采购员/需求员/采购经理/集团管理员）
        :return: 是否成功
        """
        self.ensure_token()

        # 查询用户是否存在
        result = self.user_sync("query", unique_no)
        if result and result.get("success"):
            user_data = result.get("result", {})
            if user_data and user_data.get("uniqueNo"):
                logger.info(f"User exists: {unique_no}")
                return True

        # 不存在则创建
        logger.info(f"User not found, creating: {unique_no}")
        create_result = self.user_sync(
            "insert", unique_no,
            nickName=nick_name or unique_no,
            email=email,
            mobile=mobile,
            roleName=role_name,
            stateCode=1,
        )
        return create_result is not None and create_result.get("success", False)