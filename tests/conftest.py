"""pytest fixtures for MRO tests."""

import os
import json
import sqlite3
import tempfile
import pytest

from zkh_punchout.order import OrderData, OrderApprovalStore, ApprovalStatus, SkuItem
from zkh_punchout.client import ZKHClient
from zkh_punchout.dingtalk import DingTalkClient
from zkh_punchout.approval import ApprovalService
from zkh_punchout.callback_crypto import DingCallbackCrypto


# ==================== 订单数据 fixtures ====================

@pytest.fixture
def sample_checkout_data():
    """震坤行 checkOut 回调的模拟数据"""
    return {
        "pin": "test_user",
        "strustNo": "STRUST123456",
        "uniqueNo": "user_001",
        "appId": "ESP",
        "sign": "EXPECTED_SIGN",
        "orderId": "2026080700001A",
        "state": 1,
        "orderState": 1,
        "submitState": 1,
        "orderPrice": "12345.67",
        "orderNakedPrice": "10925.37",
        "orderTaxPrice": "1420.30",
        "freight": "0.00",
        "sku": [
            {
                "skuId": "A00300",
                "num": 10,
                "price": "1000.00",
                "name": "测试商品A",
                "tax": 13,
                "nakedPrice": "884.96",
                "image": "",
                "targetCatalogId": None,
                "thirdSku": "",
                "thirdSkuName": "",
                "demandNote": "",
            },
            {
                "skuId": "B00500",
                "num": 5,
                "price": "234.57",
                "name": "测试商品B",
                "tax": 13,
                "nakedPrice": "207.58",
                "image": "",
                "targetCatalogId": None,
                "thirdSku": "",
                "thirdSkuName": "",
                "demandNote": "",
            },
        ],
        "address": "上海市浦东新区测试路100号",
        "receiveRemark": 2,
        "name": "张三",
        "mobile": "13800138000",
        "purchaseOrg": "采购部",
        "companyName": "测试公司",
        "purchaseAccount": "zhangsan",
        "purchaseMobile": "13800138000",
        "invoiceName": "测试公司",
        "invoicePhone": "021-12345678",
        "invoiceAddress": "上海市浦东新区测试路100号",
        "remark": "测试备注",
        "deliveryRemark": 2,
        "aes256Sign": "",
    }


@pytest.fixture
def sample_order(sample_checkout_data):
    return OrderData.from_checkout(sample_checkout_data)


# ==================== 数据库 fixtures ====================

@pytest.fixture
def temp_db():
    """使用临时 SQLite 数据库，测试结束后自动清理"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = OrderApprovalStore(db_path=path)
    yield store
    os.unlink(path)


@pytest.fixture
def store_with_order(temp_db, sample_order):
    """已保存了订单的 store"""
    temp_db.save_order(sample_order)
    return temp_db


# ==================== 回调加解密 fixtures ====================

@pytest.fixture
def crypto():
    """创建 DingCallbackCrypto 实例（测试用 token/aes_key/corpId）"""
    # 43 位 base64 编码的 AES key
    encoding_aes_key = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
    return DingCallbackCrypto(
        token="test_token_123",
        encoding_aes_key=encoding_aes_key,
        owner_key="ding4f4b796d63d5f483f5bf40eda33b7ba0",
    )


# ==================== ZKHClient fixtures ====================

@pytest.fixture
def zkh_client():
    return ZKHClient(
        base_url="https://openapi.uat.zkh360.com",
        client_id="test_client",
        client_secret="test_secret",
        username="test_user",
        password="test_password_md5",
    )


# ==================== Flask app fixture ====================

@pytest.fixture
def app(temp_db):
    """创建测试用 Flask app"""
    import app as app_module

    # 替换 store 为临时数据库
    app_module.store = temp_db
    # 禁用真正的 dingtalk 调用
    app_module.dingtalk = DingTalkClient("test_key", "test_secret")
    app_module.approval = ApprovalService(
        dingtalk=app_module.dingtalk,
        store=temp_db,
        process_code="TEST-PROCESS-CODE",
        approver_user_id="test_approver",
        zkh_client=None,
    )
    app_module._callback_crypto = DingCallbackCrypto(
        token="test_token",
        encoding_aes_key="abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG",
        owner_key="ding4f4b796d63d5f483f5bf40eda33b7ba0",
    )

    # 替换 ZKH client 为 mock，避免真实 API 调用
    from unittest.mock import MagicMock
    mock_client = MagicMock()
    mock_client.confirm_order.return_value = True
    mock_client.cancel_order.return_value = True
    app_module.client = mock_client

    app_module.app.config["TESTING"] = True
    return app_module.app


@pytest.fixture
def client(app):
    return app.test_client()