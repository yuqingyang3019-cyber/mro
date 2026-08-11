"""OrderData, SkuItem, OrderApprovalStore 单元测试."""

import json
import pytest
from zkh_punchout.order import (
    OrderData, SkuItem, OrderApprovalStore, ApprovalRecord, ApprovalStatus
)


class TestSkuItem:
    def test_from_dict_basic(self):
        d = {
            "skuId": "A001",
            "num": 5,
            "price": "99.99",
            "name": "测试商品",
            "tax": 13,
            "nakedPrice": "88.49",
        }
        sku = SkuItem.from_dict(d)
        assert sku.sku_id == "A001"
        assert sku.num == 5
        assert sku.price == 99.99
        assert sku.name == "测试商品"
        assert sku.tax == 13
        assert sku.naked_price == 88.49

    def test_from_dict_defaults(self):
        sku = SkuItem.from_dict({})
        assert sku.sku_id == ""
        assert sku.num == 0
        assert sku.price == 0.0
        assert sku.name == ""

    def test_from_dict_optional_fields(self):
        d = {
            "skuId": "B002",
            "num": 3,
            "price": "50.00",
            "name": "可选字段商品",
            "tax": 0,
            "nakedPrice": "50.00",
            "image": "http://example.com/img.jpg",
            "targetCatalogId": 123,
            "thirdSku": "TSK001",
            "thirdSkuName": "第三方商品",
            "demandNote": "需求备注",
        }
        sku = SkuItem.from_dict(d)
        assert sku.image == "http://example.com/img.jpg"
        assert sku.target_catalog_id == 123
        assert sku.third_sku == "TSK001"
        assert sku.third_sku_name == "第三方商品"
        assert sku.demand_note == "需求备注"


class TestOrderData:
    def test_from_checkout(self, sample_checkout_data):
        order = OrderData.from_checkout(sample_checkout_data)
        assert order.pin == "test_user"
        assert order.order_id == "2026080700001A"
        assert order.order_price == 12345.67
        assert order.order_naked_price == 10925.37
        assert order.order_tax_price == 1420.30
        assert order.freight == 0.0
        assert order.company_name == "测试公司"
        assert order.purchase_account == "zhangsan"
        assert order.address == "上海市浦东新区测试路100号"
        assert order.name == "张三"
        assert order.mobile == "13800138000"

    def test_from_checkout_sku_list(self, sample_checkout_data):
        order = OrderData.from_checkout(sample_checkout_data)
        assert len(order.sku_list) == 2
        assert order.sku_list[0].sku_id == "A00300"
        assert order.sku_list[0].num == 10
        assert order.sku_list[0].price == 1000.00
        assert order.sku_list[1].sku_id == "B00500"
        assert order.sku_list[1].num == 5

    def test_from_checkout_empty_sku(self):
        data = {
            "orderId": "EMPTY001",
            "orderPrice": "0",
            "orderNakedPrice": "0",
            "orderTaxPrice": "0",
            "freight": "0",
            "sku": [],
        }
        order = OrderData.from_checkout(data)
        assert order.sku_list == []

    def test_to_dict(self, sample_checkout_data):
        order = OrderData.from_checkout(sample_checkout_data)
        d = order.to_dict()
        assert d["order_id"] == "2026080700001A"
        assert d["order_price"] == 12345.67
        assert d["company_name"] == "测试公司"
        assert len(d["sku_list"]) == 2
        assert d["sku_list"][0]["sku_id"] == "A00300"

    def test_to_dict_roundtrip(self, sample_checkout_data):
        """to_dict 后再 from_checkout 应该得到相同数据"""
        order1 = OrderData.from_checkout(sample_checkout_data)
        d = order1.to_dict()
        # 转换字段名回 camelCase
        camel = {
            "pin": d["pin"],
            "strustNo": d["strust_no"],
            "uniqueNo": d["unique_no"],
            "appId": d["app_id"],
            "sign": d["sign"],
            "orderId": d["order_id"],
            "orderPrice": str(d["order_price"]),
            "orderNakedPrice": str(d["order_naked_price"]),
            "orderTaxPrice": str(d["order_tax_price"]),
            "freight": str(d["freight"]),
            "sku": [
                {
                    "skuId": s["sku_id"],
                    "num": s["num"],
                    "price": str(s["price"]),
                    "name": s["name"],
                    "tax": s["tax"],
                    "nakedPrice": str(s["naked_price"]),
                }
                for s in d["sku_list"]
            ],
            "address": d["address"],
            "name": d["name"],
            "mobile": d["mobile"],
            "companyName": d["company_name"],
            "purchaseAccount": d["purchase_account"],
            "purchaseMobile": d["purchase_mobile"],
            "purchaseOrg": d["purchase_org"],
            "invoiceName": d["invoice_name"],
            "invoicePhone": d["invoice_phone"],
            "invoiceAddress": d["invoice_address"],
            "remark": d["remark"],
            "state": d["state"],
            "orderState": d["order_state"],
            "submitState": d["submit_state"],
            "receiveRemark": d["receive_remark"],
            "deliveryRemark": d["delivery_remark"],
            "aes256Sign": d["aes256_sign"],
        }
        order2 = OrderData.from_checkout(camel)
        assert order2.order_id == order1.order_id
        assert order2.order_price == order1.order_price
        assert len(order2.sku_list) == len(order1.sku_list)


class TestApprovalRecord:
    def test_default_status(self):
        record = ApprovalRecord(order_id="TEST001")
        assert record.status == ApprovalStatus.PENDING
        assert record.third_order == ""
        assert record.approver == ""

    def test_approve(self):
        record = ApprovalRecord(order_id="TEST001")
        record.approve("admin", "PO-TEST001")
        assert record.status == ApprovalStatus.APPROVED
        assert record.approver == "admin"
        assert record.third_order == "PO-TEST001"
        assert record.approve_time != ""

    def test_reject(self):
        record = ApprovalRecord(order_id="TEST001")
        record.reject("admin", "价格不合理")
        assert record.status == ApprovalStatus.REJECTED
        assert record.approver == "admin"
        assert record.reject_reason == "价格不合理"

    def test_cannot_reapprove(self):
        """审批记录状态变更后，store 层阻止重复审批"""
        # ApprovalRecord 本身不阻止重复 approve，由 OrderApprovalStore 层控制
        # 此行为在 test_approve_order_already_processed 中测试
        pass


class TestOrderApprovalStore:
    def test_init_creates_tables(self, temp_db):
        """初始化后数据库表应该存在"""
        conn = temp_db._get_conn()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [r[0] for r in tables]
        assert "orders" in table_names
        assert "approvals" in table_names
        assert "approval_instances" in table_names
        conn.close()

    def test_save_order(self, temp_db, sample_order):
        temp_db.save_order(sample_order)
        order = temp_db.get_order("2026080700001A")
        assert order is not None
        assert order.order_id == "2026080700001A"
        assert order.order_price == 12345.67

    def test_save_order_creates_approval(self, temp_db, sample_order):
        temp_db.save_order(sample_order)
        approval = temp_db.get_approval("2026080700001A")
        assert approval is not None
        assert approval.status == ApprovalStatus.PENDING

    def test_get_order_not_found(self, temp_db):
        assert temp_db.get_order("NONEXISTENT") is None

    def test_get_approval_not_found(self, temp_db):
        assert temp_db.get_approval("NONEXISTENT") is None

    def test_approve_order(self, store_with_order):
        record = store_with_order.approve_order("2026080700001A", "admin", "PO-2026080700001A")
        assert record is not None
        assert record.status == ApprovalStatus.APPROVED
        assert record.third_order == "PO-2026080700001A"

        # 验证 DB 中状态已更新
        approval = store_with_order.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.APPROVED

    def test_approve_order_not_found(self, temp_db):
        assert temp_db.approve_order("NONEXISTENT", "admin", "PO-X") is None

    def test_approve_order_already_processed(self, store_with_order):
        store_with_order.approve_order("2026080700001A", "admin", "PO-001")
        # 再次审批应返回 None
        assert store_with_order.approve_order("2026080700001A", "admin2", "PO-002") is None

    def test_reject_order(self, store_with_order):
        record = store_with_order.reject_order("2026080700001A", "admin", "价格太高")
        assert record is not None
        assert record.status == ApprovalStatus.REJECTED
        assert record.reject_reason == "价格太高"

        approval = store_with_order.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.REJECTED

    def test_reject_order_not_found(self, temp_db):
        assert temp_db.reject_order("NONEXISTENT", "admin") is None

    def test_reject_order_already_approved(self, store_with_order):
        store_with_order.approve_order("2026080700001A", "admin", "PO-001")
        assert store_with_order.reject_order("2026080700001A", "admin") is None

    def test_set_and_get_approval_instance(self, store_with_order):
        store_with_order.set_approval_instance("2026080700001A", "INSTANCE-123")
        order_id = store_with_order.get_order_by_instance("INSTANCE-123")
        assert order_id == "2026080700001A"

    def test_get_order_by_instance_not_found(self, store_with_order):
        assert store_with_order.get_order_by_instance("NONEXISTENT") is None

    def test_list_pending(self, store_with_order, sample_order):
        # 再保存一个订单
        data2 = {
            "orderId": "2026080700002A",
            "orderPrice": "500.00",
            "companyName": "公司B",
            "purchaseAccount": "lisi",
            "sku": [{"skuId": "C001", "num": 1, "price": "500.00", "name": "C", "tax": 0, "nakedPrice": "500.00"}],
        }
        order2 = OrderData.from_checkout(data2)
        store_with_order.save_order(order2)

        pending = store_with_order.list_pending()
        assert len(pending) == 2
        order_ids = [o["order_id"] for o in pending]
        assert "2026080700001A" in order_ids
        assert "2026080700002A" in order_ids

    def test_list_pending_empty(self, temp_db):
        assert temp_db.list_pending() == []

    def test_list_pending_excludes_approved(self, store_with_order):
        store_with_order.approve_order("2026080700001A", "admin", "PO-001")
        pending = store_with_order.list_pending()
        assert len(pending) == 0

    def test_list_all_pagination(self, store_with_order, sample_order):
        result = store_with_order.list_all(page=1, size=10)
        assert result["total"] == 1
        assert result["page"] == 1
        assert len(result["orders"]) == 1
        assert result["orders"][0]["order_id"] == "2026080700001A"
        assert result["orders"][0]["status"] == "pending"

    def test_list_all_empty(self, temp_db):
        result = temp_db.list_all()
        assert result["total"] == 0
        assert result["orders"] == []

    def test_get_stats(self, store_with_order, sample_order):
        stats = store_with_order.get_stats()
        assert stats["total_orders"] == 1
        assert stats["status_counts"]["pending"] == 1
        assert stats["status_counts"]["approved"] == 0
        assert stats["total_amount"] == 12345.67

    def test_get_stats_after_approve(self, store_with_order):
        store_with_order.approve_order("2026080700001A", "admin", "PO-001")
        stats = store_with_order.get_stats()
        assert stats["status_counts"]["pending"] == 0
        assert stats["status_counts"]["approved"] == 1

    def test_verify_checkout_sign_empty(self, temp_db):
        """sign 为空时应该跳过验证"""
        data = {"sign": ""}
        assert temp_db.verify_checkout_sign(data) is True

    def test_verify_checkout_sign_correct(self, temp_db):
        """正确的签名应该通过"""
        import hashlib
        pin, unique_no, strust_no, app_id = "user1", "U001", "S123", "ESP"
        expected = hashlib.md5(
            f"{pin}{unique_no}{strust_no}{app_id}".encode("utf-8")
        ).hexdigest().upper()
        data = {
            "pin": pin,
            "uniqueNo": unique_no,
            "strustNo": strust_no,
            "appId": app_id,
            "sign": expected,
        }
        assert temp_db.verify_checkout_sign(data) is True

    def test_verify_checkout_sign_wrong(self, temp_db):
        """错误的签名应该不通过"""
        data = {
            "pin": "user1",
            "uniqueNo": "U001",
            "strustNo": "S123",
            "appId": "ESP",
            "sign": "WRONG_SIGN",
        }
        assert temp_db.verify_checkout_sign(data) is False