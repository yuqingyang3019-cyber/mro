"""
订单处理与审批模块

处理震坤行 checkOut 回调的订单数据，管理审批流程。
"""

import json
import time
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    PENDING = "pending"       # 待审批
    APPROVED = "approved"     # 已通过
    REJECTED = "rejected"     # 已拒绝
    CANCELLED = "cancelled"   # 已取消


@dataclass
class SkuItem:
    """商品明细"""
    sku_id: str
    num: int
    price: float
    name: str
    tax: int
    naked_price: float
    image: str = ""
    target_catalog_id: Optional[int] = None
    third_sku: str = ""
    third_sku_name: str = ""
    demand_note: str = ""

    @classmethod
    def from_dict(cls, d: Dict) -> "SkuItem":
        return cls(
            sku_id=d.get("skuId", ""),
            num=d.get("num", 0),
            price=float(d.get("price", 0)),
            name=d.get("name", ""),
            tax=int(d.get("tax", 0)),
            naked_price=float(d.get("nakedPrice", 0)),
            image=d.get("image", ""),
            target_catalog_id=d.get("targetCatalogId"),
            third_sku=d.get("thirdSku", ""),
            third_sku_name=d.get("thirdSkuName", ""),
            demand_note=d.get("demandNote", ""),
        )


@dataclass
class OrderData:
    """震坤行回传的预订单数据"""
    # 用户信息
    pin: str = ""
    strust_no: str = ""
    unique_no: str = ""
    app_id: str = ""
    sign: str = ""

    # 订单信息
    order_id: str = ""
    state: int = 0
    order_state: int = 0
    submit_state: int = 0
    order_price: float = 0.0
    order_naked_price: float = 0.0
    order_tax_price: float = 0.0
    freight: float = 0.0
    sku_list: List[SkuItem] = field(default_factory=list)

    # 收货信息
    address: str = ""
    receive_remark: int = 0
    name: str = ""
    mobile: str = ""

    # 采购信息
    purchase_org: str = ""
    company_name: str = ""
    purchase_account: str = ""
    purchase_mobile: str = ""

    # 发票信息
    invoice_name: str = ""
    invoice_phone: str = ""
    invoice_address: str = ""

    # 其他
    remark: str = ""
    delivery_remark: int = 0
    aes256_sign: str = ""

    @classmethod
    def from_checkout(cls, data: Dict) -> "OrderData":
        """从震坤行 checkOut 回调数据构建订单"""
        sku_list = []
        for sku_d in data.get("sku", []):
            sku_list.append(SkuItem.from_dict(sku_d))

        return cls(
            pin=data.get("pin", ""),
            strust_no=data.get("strustNo", ""),
            unique_no=data.get("uniqueNo", ""),
            app_id=data.get("appId", ""),
            sign=data.get("sign", ""),
            order_id=data.get("orderId", ""),
            state=data.get("state", 0),
            order_state=data.get("orderState", 0),
            submit_state=data.get("submitState", 0),
            order_price=float(data.get("orderPrice", 0)),
            order_naked_price=float(data.get("orderNakedPrice", 0)),
            order_tax_price=float(data.get("orderTaxPrice", 0)),
            freight=float(data.get("freight", 0)),
            sku_list=sku_list,
            address=data.get("address", ""),
            receive_remark=data.get("receiveRemark", 0),
            name=data.get("name", ""),
            mobile=data.get("mobile", ""),
            purchase_org=data.get("purchaseOrg", ""),
            company_name=data.get("companyName", ""),
            purchase_account=data.get("purchaseAccount", ""),
            purchase_mobile=data.get("purchaseMobile", ""),
            invoice_name=data.get("invoiceName", ""),
            invoice_phone=data.get("invoicePhone", ""),
            invoice_address=data.get("invoiceAddress", ""),
            remark=data.get("remark", ""),
            delivery_remark=data.get("deliveryRemark", 0),
            aes256_sign=data.get("aes256Sign", ""),
        )

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["sku_list"] = [asdict(s) for s in self.sku_list]
        return d


@dataclass
class ApprovalRecord:
    """审批记录"""
    order_id: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    third_order: str = ""             # 客户侧订单号
    approver: str = ""                # 审批人
    approve_time: str = ""            # 审批时间
    reject_reason: str = ""           # 拒绝原因
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    updated_at: str = ""

    def approve(self, approver: str, third_order: str):
        self.status = ApprovalStatus.APPROVED
        self.approver = approver
        self.third_order = third_order
        self.approve_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.updated_at = self.approve_time

    def reject(self, approver: str, reason: str = ""):
        self.status = ApprovalStatus.REJECTED
        self.approver = approver
        self.reject_reason = reason
        self.updated_at = time.strftime("%Y-%m-%d %H:%M:%S")


class OrderApprovalStore:
    """
    订单审批存储（内存版，生产环境替换为数据库）
    """

    def __init__(self):
        self._orders: Dict[str, OrderData] = {}
        self._approvals: Dict[str, ApprovalRecord] = {}
        self._approval_instances: Dict[str, str] = {}  # order_id -> process_instance_id

    def save_order(self, order: OrderData):
        """保存回传订单"""
        self._orders[order.order_id] = order
        self._approvals[order.order_id] = ApprovalRecord(order_id=order.order_id)
        logger.info(f"Order saved: {order.order_id}")

    def get_order(self, order_id: str) -> Optional[OrderData]:
        return self._orders.get(order_id)

    def get_approval(self, order_id: str) -> Optional[ApprovalRecord]:
        return self._approvals.get(order_id)

    def approve_order(self, order_id: str, approver: str, third_order: str) -> Optional[ApprovalRecord]:
        """审批通过"""
        record = self._approvals.get(order_id)
        if not record:
            return None
        if record.status != ApprovalStatus.PENDING:
            logger.warning(f"Order {order_id} already {record.status.value}")
            return None
        record.approve(approver, third_order)
        logger.info(f"Order approved: {order_id} -> {third_order}")
        return record

    def reject_order(self, order_id: str, approver: str, reason: str = "") -> Optional[ApprovalRecord]:
        """审批拒绝"""
        record = self._approvals.get(order_id)
        if not record:
            return None
        if record.status != ApprovalStatus.PENDING:
            return None
        record.reject(approver, reason)
        logger.info(f"Order rejected: {order_id}, reason: {reason}")
        return record

    def list_pending(self) -> List[Dict]:
        """列出所有待审批订单"""
        result = []
        for order_id, record in self._approvals.items():
            if record.status == ApprovalStatus.PENDING:
                order = self._orders.get(order_id)
                result.append({
                    "order_id": order_id,
                    "order_price": order.order_price if order else 0,
                    "company_name": order.company_name if order else "",
                    "purchase_account": order.purchase_account if order else "",
                    "sku_count": len(order.sku_list) if order else 0,
                    "created_at": record.created_at,
                })
        return result

    def verify_checkout_sign(self, data: Dict, secret_key: str = "") -> bool:
        """
        验证 checkOut 回调签名
        签名规则：MD5(pin + uniqueNo + strustNo + appId)
        """
        pin = data.get("pin", "")
        unique_no = data.get("uniqueNo", "")
        strust_no = data.get("strustNo", "")
        app_id = data.get("appId", "")
        expected = hashlib.md5(
            f"{pin}{unique_no}{strust_no}{app_id}".encode("utf-8")
        ).hexdigest().upper()
        actual = data.get("sign", "")
        return expected == actual