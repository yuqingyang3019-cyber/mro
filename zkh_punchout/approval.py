"""
钉钉审批集成模块

处理订单审批流程：创建审批实例、处理审批回调。
"""

import json
import logging
from typing import Optional, Dict, Any

from .dingtalk import DingTalkClient
from .order import OrderData, OrderApprovalStore, ApprovalStatus
from .client import ZKHClient

logger = logging.getLogger(__name__)

# 人事测试流程模板的表单字段 ID
FORM_FIELDS = {
    "事项": "TextField_MQPU6ZNTD9C0",
    "具体说明": "TextareaField_IPKY0GZC5YG0",
    "附件": "DDAttachment_22U587DFUK3K0",
}


class ApprovalService:
    """钉钉审批服务"""

    def __init__(self, dingtalk: DingTalkClient, store: OrderApprovalStore,
                 process_code: str, approver_user_id: str = "",
                 zkh_client: Optional[ZKHClient] = None):
        self.dingtalk = dingtalk
        self.store = store
        self.zkh = zkh_client
        self.process_code = process_code
        # 优先使用 DB 配置，无配置时回退到构造函数参数
        self._approver_user_id_fallback = approver_user_id

    def build_form_values(self, order: OrderData) -> list:
        """将订单数据转换为钉钉审批表单字段值"""
        subject = f"采购订单审批 - {order.order_id}"

        # 构建商品明细表格
        sku_lines = []
        for i, sku in enumerate(order.sku_list, 1):
            sku_lines.append(
                f"  {i}. {sku.name}（{sku.sku_id}）\n"
                f"     数量: {sku.num} | 含税单价: ¥{sku.price:.2f} | "
                f"不含税单价: ¥{sku.naked_price:.2f} | 税率: {sku.tax}%"
            )

        detail = f"""订单号: {order.order_id}
下单人: {order.purchase_account}（{order.purchase_mobile}）
公司: {order.company_name}
采购组织: {order.purchase_org}

=== 金额汇总 ===
订单总额（含税）: ¥{order.order_price:,.2f}
不含税金额: ¥{order.order_naked_price:,.2f}
税额: ¥{order.order_tax_price:,.2f}
运费: ¥{order.freight:,.2f}

=== 商品明细 ===
{chr(10).join(sku_lines)}

=== 收货信息 ===
收货人: {order.name}
手机: {order.mobile}
地址: {order.address}
发货备注: {"工作日" if order.delivery_remark == 2 else "任意时间" if order.delivery_remark == 1 else "未指定"}

=== 发票信息 ===
收票人: {order.invoice_name}
收票电话: {order.invoice_phone}
收票地址: {order.invoice_address}

=== 备注 ===
{order.remark or "无"}"""

        return [
            {"name": "事项", "value": subject},
            {"name": "具体说明", "value": detail},
        ]

    def create_approval(self, order: OrderData) -> Optional[str]:
        """
        为订单创建钉钉审批实例
        :return: process_instance_id 或 None
        """
        form_values = self.build_form_values(order)

        # 下单人作为审批发起人，审批人从 DB 配置读取（回退到环境变量）
        originator_user_id = order.unique_no
        approver = self.store.get_config("approver_user_id") or self._approver_user_id_fallback

        if not approver:
            logger.error(f"No approver configured for order {order.order_id}")
            return None

        result = self.dingtalk.create_process_instance(
            process_code=self.process_code,
            originator_user_id=originator_user_id,
            approver_user_ids=[approver],
            form_component_values=form_values,
        )

        if not result:
            logger.error(f"Failed to create approval for order {order.order_id}")
            return None

        instance_id = result.get("process_instance_id", "")
        logger.info(f"Approval created: order={order.order_id}, instance={instance_id}")

        # 建立订单与审批实例的映射关系
        self.store.set_approval_instance(order.order_id, instance_id)
        return instance_id

    def handle_callback(self, event_data: Dict[str, Any]) -> bool:
        """
        处理钉钉审批回调
        :param event_data: 钉钉推送的事件数据
        :return: 是否处理成功
        """
        event_type = event_data.get("EventType", "")
        if event_type not in ("bpms_instance_change", "bpms_task_change"):
            logger.debug(f"Ignoring event type: {event_type}")
            return True  # 非审批事件，忽略但不报错

        instance_id = event_data.get("processInstanceId", "")
        if not instance_id:
            logger.warning("Callback missing processInstanceId")
            return False

        # 查询审批实例详情
        instance = self.dingtalk.get_process_instance(instance_id)
        if not instance:
            logger.error(f"Failed to get instance: {instance_id}")
            return False

        status = instance.get("status", "")
        result = instance.get("result", "")
        title = instance.get("title", "")

        logger.info(f"Approval callback: instance={instance_id}, status={status}, result={result}")

        # 查找对应的订单
        order_id = self._find_order_by_instance(instance_id, title)
        if not order_id:
            logger.warning(f"No order found for instance: {instance_id}")
            return False

        # 根据审批结果处理
        if status == "COMPLETED":
            if result == "agree":
                return self._on_approved(order_id, instance_id)
            elif result == "refuse":
                return self._on_rejected(order_id, instance_id, "审批拒绝")
        elif status == "TERMINATED":
            return self._on_cancelled(order_id, instance_id)

        return True

    def _find_order_by_instance(self, instance_id: str, title: str = "") -> Optional[str]:
        """通过审批实例 ID 查找订单 ID，DB 中找不到时从标题提取"""
        # 先查 DB 中的映射
        order_id = self.store.get_order_by_instance(instance_id)
        if order_id:
            return order_id

        # 映射丢失（如旧数据），从标题提取：采购订单审批 - {order_id}
        if title:
            prefix = "采购订单审批 - "
            if title.startswith(prefix):
                order_id = title[len(prefix):]
                logger.info(f"Found order_id from title: {order_id}")
                return order_id

        return None

    def _on_approved(self, order_id: str, instance_id: str) -> bool:
        """审批通过：确认订单"""
        logger.info(f"Order approved via DingTalk: {order_id}")

        third_order = f"PO{order_id}"
        record = self.store.approve_order(order_id, "dingtalk", third_order)
        if not record:
            logger.warning(f"Order {order_id} not in pending state")
            return False

        # 调用震坤行 confirmOrder 确认订单
        if self.zkh:
            success = self.zkh.confirm_order(order_id, third_order)
            if not success:
                logger.error(f"ZKH confirmOrder failed for {order_id}")
                return False
            logger.info(f"ZKH order confirmed: {order_id} -> {third_order}")
        else:
            logger.warning(f"ZKH client not configured, skipping confirmOrder for {order_id}")

        return True

    def _on_rejected(self, order_id: str, instance_id: str, reason: str) -> bool:
        """审批拒绝：取消订单"""
        logger.info(f"Order rejected via DingTalk: {order_id}, reason: {reason}")
        record = self.store.reject_order(order_id, "dingtalk", reason)
        if not record:
            logger.warning(f"Order {order_id} not in pending state")
            return False

        # 调用震坤行 cancel 取消订单
        if self.zkh:
            success = self.zkh.cancel_order(order_id)
            if not success:
                logger.error(f"ZKH cancelOrder failed for {order_id}")
                return False
            logger.info(f"ZKH order cancelled: {order_id}")
        else:
            logger.warning(f"ZKH client not configured, skipping cancelOrder for {order_id}")

        return True

    def _on_cancelled(self, order_id: str, instance_id: str) -> bool:
        """审批撤销"""
        logger.info(f"Approval cancelled: {order_id}")
        record = self.store.reject_order(order_id, "dingtalk", "审批撤销")
        if not record:
            logger.warning(f"Order {order_id} not in pending state")
            return False

        # 调用震坤行 cancel 取消订单
        if self.zkh:
            success = self.zkh.cancel_order(order_id)
            if not success:
                logger.error(f"ZKH cancelOrder failed for {order_id}")
                return False
            logger.info(f"ZKH order cancelled: {order_id}")
        else:
            logger.warning(f"ZKH client not configured, skipping cancelOrder for {order_id}")

        return True