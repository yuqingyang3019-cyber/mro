"""ApprovalService 单元测试."""

import json
from unittest.mock import MagicMock, patch
import pytest
from zkh_punchout.order import OrderData, OrderApprovalStore, ApprovalStatus
from zkh_punchout.dingtalk import DingTalkClient
from zkh_punchout.approval import ApprovalService


class TestApprovalServiceBuildForm:
    @pytest.fixture
    def service(self, temp_db):
        dingtalk = DingTalkClient("test_key", "test_secret")
        return ApprovalService(
            dingtalk=dingtalk,
            store=temp_db,
            process_code="TEST-PROC",
            approver_user_id="approver_001",
        )

    def test_build_form_values(self, service, sample_order):
        form = service.build_form_values(sample_order)
        assert len(form) == 2
        assert form[0]["name"] == "事项"
        assert "采购订单审批" in form[0]["value"]
        assert "2026080700001A" in form[0]["value"]

        assert form[1]["name"] == "具体说明"
        detail = form[1]["value"]
        assert "2026080700001A" in detail
        assert "12,345.67" in detail  # 金额格式化后带千分位
        assert "测试商品A" in detail
        assert "测试商品B" in detail
        assert "张三" in detail
        assert "上海市浦东新区测试路100号" in detail

    def test_build_form_with_empty_sku(self, service):
        order = OrderData.from_checkout({
            "orderId": "EMPTY001",
            "orderPrice": "0",
            "orderNakedPrice": "0",
            "orderTaxPrice": "0",
            "freight": "0",
            "sku": [],
            "companyName": "Test",
            "name": "Test",
            "mobile": "138",
            "address": "Addr",
            "invoiceName": "Inv",
            "invoicePhone": "021",
            "invoiceAddress": "Addr",
            "remark": "",
        })
        form = service.build_form_values(order)
        assert len(form) == 2
        # 不应包含商品明细行
        detail = form[1]["value"]
        assert "商品明细" in detail


class TestApprovalServiceCreateApproval:
    @pytest.fixture
    def service(self, temp_db):
        dingtalk = MagicMock(spec=DingTalkClient)
        dingtalk.create_process_instance.return_value = {
            "errcode": 0,
            "process_instance_id": "INSTANCE-001",
        }
        return ApprovalService(
            dingtalk=dingtalk,
            store=temp_db,
            process_code="TEST-PROC",
            approver_user_id="approver_001",
        )

    def test_create_approval_success(self, service, sample_order):
        instance_id = service.create_approval(sample_order)
        assert instance_id == "INSTANCE-001"

        # 验证映射已建立
        order_id = service.store.get_order_by_instance("INSTANCE-001")
        assert order_id == "2026080700001A"

    def test_create_approval_failure(self, temp_db):
        dingtalk = MagicMock(spec=DingTalkClient)
        dingtalk.create_process_instance.return_value = None
        service = ApprovalService(
            dingtalk=dingtalk,
            store=temp_db,
            process_code="TEST-PROC",
            approver_user_id="approver_001",
        )
        order = OrderData.from_checkout({"orderId": "FAIL001", "orderPrice": "100", "sku": []})
        instance_id = service.create_approval(order)
        assert instance_id is None


class TestApprovalServiceHandleCallback:
    @pytest.fixture
    def service(self, temp_db):
        dingtalk = MagicMock(spec=DingTalkClient)
        return ApprovalService(
            dingtalk=dingtalk,
            store=temp_db,
            process_code="TEST-PROC",
            approver_user_id="approver_001",
        )

    def test_handle_callback_approved(self, service, sample_order):
        """审批通过回调"""
        # 保存订单和映射
        service.store.save_order(sample_order)
        service.store.set_approval_instance("2026080700001A", "INSTANCE-001")

        # 模拟 get_process_instance 返回已通过
        service.dingtalk.get_process_instance.return_value = {
            "status": "COMPLETED",
            "result": "agree",
            "title": "采购订单审批 - 2026080700001A",
        }

        result = service.handle_callback({
            "EventType": "bpms_instance_change",
            "processInstanceId": "INSTANCE-001",
        })
        assert result is True

        # 验证审批状态已更新
        approval = service.store.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.APPROVED

    def test_handle_callback_rejected(self, service, sample_order):
        """审批拒绝回调"""
        service.store.save_order(sample_order)
        service.store.set_approval_instance("2026080700001A", "INSTANCE-001")

        service.dingtalk.get_process_instance.return_value = {
            "status": "COMPLETED",
            "result": "refuse",
            "title": "采购订单审批 - 2026080700001A",
        }

        result = service.handle_callback({
            "EventType": "bpms_instance_change",
            "processInstanceId": "INSTANCE-001",
        })
        assert result is True

        approval = service.store.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.REJECTED

    def test_handle_callback_terminated(self, service, sample_order):
        """审批撤销回调"""
        service.store.save_order(sample_order)
        service.store.set_approval_instance("2026080700001A", "INSTANCE-001")

        service.dingtalk.get_process_instance.return_value = {
            "status": "TERMINATED",
            "result": "",
            "title": "采购订单审批 - 2026080700001A",
        }

        result = service.handle_callback({
            "EventType": "bpms_instance_change",
            "processInstanceId": "INSTANCE-001",
        })
        assert result is True

        approval = service.store.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.REJECTED

    def test_handle_callback_ignore_non_approval_event(self, service):
        """非审批事件应被忽略"""
        result = service.handle_callback({
            "EventType": "check_url",
            "processInstanceId": "INSTANCE-001",
        })
        assert result is True

    def test_handle_callback_missing_instance_id(self, service):
        result = service.handle_callback({"EventType": "bpms_instance_change"})
        assert result is False

    def test_find_order_by_title_fallback(self, service, sample_order):
        """DB 映射丢失时从标题提取 order_id"""
        service.store.save_order(sample_order)
        # 不建立映射，模拟映射丢失

        service.dingtalk.get_process_instance.return_value = {
            "status": "COMPLETED",
            "result": "agree",
            "title": "采购订单审批 - 2026080700001A",
        }

        result = service.handle_callback({
            "EventType": "bpms_instance_change",
            "processInstanceId": "INSTANCE-002",
        })
        assert result is True

        approval = service.store.get_approval("2026080700001A")
        assert approval.status == ApprovalStatus.APPROVED