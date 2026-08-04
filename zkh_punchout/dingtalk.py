"""
钉钉 H5 微应用免登服务

流程：
1. 用户在钉钉中打开 H5 页面
2. 前端调用 dd.runtime.permission.requestAuthCode 获取免登授权码
3. 后端用授权码换取用户信息（userid, name, avatar 等）
4. 用 userid 作为 unique_no 进行 ZKH SSO
"""

import json
import time
import urllib.request
import urllib.error
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class DingTalkClient:
    """钉钉 H5 微应用免登客户端"""

    DINGTALK_BASE = "https://oapi.dingtalk.com"

    def __init__(self, app_key: str, app_secret: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def _request(self, method: str, url: str, body: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """通用请求"""
        try:
            data = json.dumps(body).encode() if body else None
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Content-Type", "application/json; charset=UTF-8")
            resp = urllib.request.urlopen(req, timeout=15)
            result = json.loads(resp.read())
            if result.get("errcode") == 0:
                return result
            else:
                logger.warning(f"DingTalk API fail [{url}]: {result.get('errcode')} {result.get('errmsg')}")
                return result
        except urllib.error.HTTPError as e:
            logger.error(f"DingTalk HTTP error [{url}]: {e.code}")
            return None
        except Exception as e:
            logger.error(f"DingTalk request error [{url}]: {e}")
            return None

    # ==================== 鉴权 ====================

    def get_access_token(self) -> Optional[str]:
        """获取钉钉 access_token，有效期 7200s"""
        # 钉钉新版接口
        url = f"{self.DINGTALK_BASE}/gettoken?appkey={self.app_key}&appsecret={self.app_secret}"
        r = self._request("GET", url)
        if r and r.get("errcode") == 0:
            self._token = r["access_token"]
            self._token_expires_at = time.time() + r.get("expires_in", 7200) - 60
            logger.info("DingTalk token obtained")
            return self._token
        return None

    def ensure_token(self) -> bool:
        if not self._token or time.time() > self._token_expires_at:
            return self.get_access_token() is not None
        return True

    # ==================== 免登 ====================

    def get_userinfo_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        """
        免登：通过临时授权码获取用户信息
        :param code: 前端 dd.runtime.permission.requestAuthCode 返回的 code
        :return: {"userid": "...", "name": "...", "avatar": "..."} 等
        """
        self.ensure_token()
        url = f"{self.DINGTALK_BASE}/topapi/v2/user/getuserinfo?access_token={self._token}"
        r = self._request("POST", url, {"code": code})
        if r and r.get("errcode") == 0:
            return r.get("result", {})
        return None

    def get_user_detail(self, userid: str) -> Optional[Dict[str, Any]]:
        """获取用户详细信息"""
        self.ensure_token()
        url = f"{self.DINGTALK_BASE}/topapi/v2/user/get?access_token={self._token}"
        r = self._request("POST", url, {"userid": userid})
        if r and r.get("errcode") == 0:
            return r.get("result", {})
        return None

    # ==================== JSAPI 签名 ====================

    def get_jsapi_ticket(self) -> Optional[str]:
        """获取 JSAPI ticket（用于前端 dd.config 签名）"""
        self.ensure_token()
        url = f"{self.DINGTALK_BASE}/get_jsapi_ticket?access_token={self._token}"
        r = self._request("GET", url)
        if r and r.get("errcode") == 0:
            return r.get("ticket")
        return None

    # ==================== 审批 ====================

    def create_process_instance(
        self,
        process_code: str,
        originator_user_id: str,
        approver_user_ids: list,
        form_component_values: list,
        dept_id: int = -1,
    ) -> Optional[Dict[str, Any]]:
        """
        创建钉钉审批实例
        :param process_code: 审批模板编号
        :param originator_user_id: 发起人 userid
        :param approver_user_ids: 审批人 userid 列表
        :param form_component_values: 表单字段值列表
            [{"name": "事项", "value": "xxx"}, ...]
        :param dept_id: 发起人部门 ID，-1 表示默认
        :return: {"process_instance_id": "...", ...}
        """
        self.ensure_token()
        url = f"{self.DINGTALK_BASE}/topapi/processinstance/create?access_token={self._token}"
        payload = {
            "process_code": process_code,
            "originator_user_id": originator_user_id,
            "dept_id": dept_id,
            "approvers": approver_user_ids[0] if len(approver_user_ids) == 1 else "|".join(approver_user_ids),
            "form_component_values": form_component_values,
        }
        r = self._request("POST", url, payload)
        if r and r.get("errcode") == 0:
            logger.info(f"Approval instance created: {r.get('process_instance_id')}")
            return r
        return None

    def get_process_instance(self, process_instance_id: str) -> Optional[Dict[str, Any]]:
        """
        查询审批实例详情
        :param process_instance_id: 审批实例 ID
        :return: 实例详情，包含 status、result、form_component_values 等
        """
        self.ensure_token()
        url = f"{self.DINGTALK_BASE}/topapi/processinstance/get?access_token={self._token}"
        r = self._request("POST", url, {"process_instance_id": process_instance_id})
        if r and r.get("errcode") == 0:
            return r.get("process_instance", {})
        return None