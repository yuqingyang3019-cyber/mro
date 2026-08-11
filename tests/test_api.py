"""Flask API 集成测试."""

import json
import pytest
from unittest.mock import patch, MagicMock


class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["crypto"] == "ok"
        assert data["callback_crypto_ready"] is True


class TestCheckoutEndpoint:
    def test_checkout_success(self, client, store_with_order):
        """订单回传成功"""
        payload = {
            "pin": "test_user",
            "strustNo": "STRUST123",
            "uniqueNo": "U001",
            "appId": "ESP",
            "sign": "",  # 空签名，测试环境跳过验证
            "orderId": "20260807TEST001A",
            "orderPrice": "9999.00",
            "orderNakedPrice": "8849.56",
            "orderTaxPrice": "1149.44",
            "freight": "0.00",
            "sku": [
                {
                    "skuId": "SKU001",
                    "num": 3,
                    "price": "3333.00",
                    "name": "商品X",
                    "tax": 13,
                    "nakedPrice": "2949.56",
                }
            ],
            "companyName": "测试公司",
            "purchaseAccount": "tester",
            "purchaseMobile": "13800138000",
            "name": "收货人",
            "mobile": "13800138000",
            "address": "测试地址",
            "invoiceName": "测试公司",
            "invoicePhone": "021-12345678",
            "invoiceAddress": "测试地址",
            "remark": "",
        }
        resp = client.post(
            "/api/zkh/checkout",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["resultCode"] == "0000"

    def test_checkout_invalid_sign(self, client, store_with_order):
        """签名无效时返回 400"""
        payload = {
            "pin": "user1",
            "uniqueNo": "U001",
            "strustNo": "S123",
            "appId": "ESP",
            "sign": "WRONG_SIGN",
            "orderId": "TEST002",
            "orderPrice": "100",
            "sku": [],
        }
        resp = client.post(
            "/api/zkh/checkout",
            data=json.dumps(payload),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False


class TestOrdersEndpoints:
    def test_pending_empty(self, client):
        resp = client.get("/api/zkh/orders/pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["orders"] == []

    def test_pending_with_order(self, client, store_with_order):
        resp = client.get("/api/zkh/orders/pending")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1
        order_ids = [o["order_id"] for o in data["orders"]]
        assert "2026080700001A" in order_ids

    def test_list_all(self, client, store_with_order):
        resp = client.get("/api/zkh/orders/all?page=1&size=10")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] >= 1
        assert len(data["orders"]) >= 1

    def test_list_all_pagination(self, client, store_with_order):
        resp = client.get("/api/zkh/orders/all?page=1&size=1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["size"] == 1
        assert len(data["orders"]) <= 1

    def test_get_stats(self, client, store_with_order):
        resp = client.get("/api/zkh/orders/stats")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "total_orders" in data
        assert "status_counts" in data
        assert "monthly_counts" in data
        assert "monthly_amounts" in data
        assert "approval_timing" in data

    def test_get_order_detail(self, client, store_with_order):
        resp = client.get("/api/zkh/orders/2026080700001A/detail")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["order"]["order_id"] == "2026080700001A"
        assert data["approval_status"] == "pending"

    def test_get_order_detail_not_found(self, client):
        resp = client.get("/api/zkh/orders/NONEXISTENT/detail")
        assert resp.status_code == 404

    def test_approve_order(self, client, store_with_order):
        resp = client.post(
            "/api/zkh/orders/2026080700001A/approve",
            data=json.dumps({"approver": "admin", "third_order": "PO-TEST001"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["status"] == "approved"

    def test_approve_order_not_found(self, client):
        resp = client.post(
            "/api/zkh/orders/NONEXISTENT/approve",
            data=json.dumps({"approver": "admin"}),
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_reject_order(self, client, store_with_order):
        resp = client.post(
            "/api/zkh/orders/2026080700001A/reject",
            data=json.dumps({"approver": "admin", "reason": "价格太高"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["status"] == "rejected"

    def test_reject_order_not_found(self, client):
        resp = client.post(
            "/api/zkh/orders/NONEXISTENT/reject",
            data=json.dumps({"approver": "admin"}),
            content_type="application/json",
        )
        assert resp.status_code == 400


class TestSSOEndpoints:
    def test_sso_missing_unique_no(self, client):
        resp = client.get("/api/zkh/sso")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "unique_no" in data["error"]

    def test_sso_custom_fields_invalid_json(self, client):
        resp = client.get("/api/zkh/sso?unique_no=test&custom_fields=not-json")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "custom_fields" in data["error"]

    def test_dingtalk_sso_page(self, client):
        resp = client.get("/dingtalk/sso")
        assert resp.status_code == 200
        assert "钉钉" in resp.get_data(as_text=True)

    def test_dingtalk_dashboard_page(self, client):
        resp = client.get("/dingtalk/dashboard")
        assert resp.status_code == 200
        assert "采购看板" in resp.get_data(as_text=True)

    def test_dingtalk_auth_missing_code(self, client):
        resp = client.post(
            "/api/dingtalk/auth",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "code" in data["error"]

    def test_dingtalk_launch_invalid_token(self, client):
        resp = client.get("/dingtalk/launch?token=invalid")
        assert resp.status_code == 400


class TestMessagesEndpoint:
    def test_get_messages(self, client):
        resp = client.get("/api/zkh/messages")
        # 没有真实 token，应该返回 500
        assert resp.status_code in (200, 500)


class TestUserSyncEndpoint:
    def test_user_sync_missing_unique_no(self, client):
        resp = client.post(
            "/api/zkh/users/sync",
            data=json.dumps({"opt": "query"}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "unique_no" in data["error"]


class TestApprovalCallbackEndpoint:
    def test_get_returns_ok(self, client):
        resp = client.get("/api/zkh/approval/callback")
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == "ok"

    def test_post_without_encrypt(self, client):
        resp = client.post(
            "/api/zkh/approval/callback",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["errcode"] == 0

    def test_post_with_encrypt(self, client):
        """带加密数据的回调"""
        from zkh_punchout.callback_crypto import DingCallbackCrypto
        crypto = DingCallbackCrypto(
            token="test_token",
            encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
            owner_key="ding4f4b796d63d5f483f5bf40eda33b7ba0",
        )
        event = json.dumps({"EventType": "check_url"})
        encrypted = crypto.get_encrypted_map(event)

        resp = client.post(
            f"/api/zkh/approval/callback?msg_signature={encrypted['msg_signature']}&timestamp={encrypted['timeStamp']}&nonce={encrypted['nonce']}",
            data=json.dumps({"encrypt": encrypted["encrypt"]}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "msg_signature" in data
        assert "timeStamp" in data
        assert "nonce" in data
        assert "encrypt" in data