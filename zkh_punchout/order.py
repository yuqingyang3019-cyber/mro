"""
订单处理与审批模块

处理震坤行 checkOut 回调的订单数据，管理审批流程。
"""

import json
import os
import sqlite3
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
        """从震坤行 checkOut 回调数据构建订单（camelCase 键名）"""
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

    @classmethod
    def from_db(cls, data: Dict) -> "OrderData":
        """从数据库 snake_case 格式构建订单"""
        sku_list = []
        for sku_d in data.get("sku_list", []):
            sku_list.append(SkuItem(
                sku_id=sku_d.get("sku_id", ""),
                num=sku_d.get("num", 0),
                price=float(sku_d.get("price", 0)),
                name=sku_d.get("name", ""),
                tax=int(sku_d.get("tax", 0)),
                naked_price=float(sku_d.get("naked_price", 0)),
                image=sku_d.get("image", ""),
                target_catalog_id=sku_d.get("target_catalog_id"),
                third_sku=sku_d.get("third_sku", ""),
                third_sku_name=sku_d.get("third_sku_name", ""),
                demand_note=sku_d.get("demand_note", ""),
            ))

        return cls(
            pin=data.get("pin", ""),
            strust_no=data.get("strust_no", ""),
            unique_no=data.get("unique_no", ""),
            app_id=data.get("app_id", ""),
            sign=data.get("sign", ""),
            order_id=data.get("order_id", ""),
            state=data.get("state", 0),
            order_state=data.get("order_state", 0),
            submit_state=data.get("submit_state", 0),
            order_price=float(data.get("order_price", 0)),
            order_naked_price=float(data.get("order_naked_price", 0)),
            order_tax_price=float(data.get("order_tax_price", 0)),
            freight=float(data.get("freight", 0)),
            sku_list=sku_list,
            address=data.get("address", ""),
            receive_remark=data.get("receive_remark", 0),
            name=data.get("name", ""),
            mobile=data.get("mobile", ""),
            purchase_org=data.get("purchase_org", ""),
            company_name=data.get("company_name", ""),
            purchase_account=data.get("purchase_account", ""),
            purchase_mobile=data.get("purchase_mobile", ""),
            invoice_name=data.get("invoice_name", ""),
            invoice_phone=data.get("invoice_phone", ""),
            invoice_address=data.get("invoice_address", ""),
            remark=data.get("remark", ""),
            delivery_remark=data.get("delivery_remark", 0),
            aes256_sign=data.get("aes256_sign", ""),
        )

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["sku_list"] = [asdict(s) for s in self.sku_list]
        return d

    def to_camel_dict(self) -> Dict:
        """转换为 camelCase 格式，与 from_checkout 输入格式一致，用于 DB 存储"""
        return {
            "pin": self.pin,
            "strustNo": self.strust_no,
            "uniqueNo": self.unique_no,
            "appId": self.app_id,
            "sign": self.sign,
            "orderId": self.order_id,
            "state": self.state,
            "orderState": self.order_state,
            "submitState": self.submit_state,
            "orderPrice": str(self.order_price),
            "orderNakedPrice": str(self.order_naked_price),
            "orderTaxPrice": str(self.order_tax_price),
            "freight": str(self.freight),
            "sku": [
                {
                    "skuId": s.sku_id,
                    "num": s.num,
                    "price": str(s.price),
                    "name": s.name,
                    "tax": s.tax,
                    "nakedPrice": str(s.naked_price),
                    "image": s.image,
                    "targetCatalogId": s.target_catalog_id,
                    "thirdSku": s.third_sku,
                    "thirdSkuName": s.third_sku_name,
                    "demandNote": s.demand_note,
                }
                for s in self.sku_list
            ],
            "address": self.address,
            "receiveRemark": self.receive_remark,
            "name": self.name,
            "mobile": self.mobile,
            "purchaseOrg": self.purchase_org,
            "companyName": self.company_name,
            "purchaseAccount": self.purchase_account,
            "purchaseMobile": self.purchase_mobile,
            "invoiceName": self.invoice_name,
            "invoicePhone": self.invoice_phone,
            "invoiceAddress": self.invoice_address,
            "remark": self.remark,
            "deliveryRemark": self.delivery_remark,
            "aes256Sign": self.aes256_sign,
        }


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
    订单审批存储（基于 SQLite 持久化）
    """

    def __init__(self, db_path: str = "data/mro.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    order_id TEXT PRIMARY KEY,
                    data JSON NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approvals (
                    order_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pending',
                    third_order TEXT NOT NULL DEFAULT '',
                    approver TEXT NOT NULL DEFAULT '',
                    approve_time TEXT NOT NULL DEFAULT '',
                    reject_reason TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                    updated_at TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS approval_instances (
                    order_id TEXT PRIMARY KEY,
                    instance_id TEXT NOT NULL UNIQUE
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
                )
            """)

    def save_order(self, order: OrderData):
        """保存回传订单"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO orders (order_id, data) VALUES (?, ?)",
                (order.order_id, json.dumps(order.to_dict(), ensure_ascii=False)),
            )
            conn.execute(
                "INSERT OR IGNORE INTO approvals (order_id) VALUES (?)",
                (order.order_id,),
            )
        logger.info(f"Order saved: {order.order_id}")

    def get_order(self, order_id: str) -> Optional[OrderData]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT data FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        if not row:
            return None
        return OrderData.from_db(json.loads(row["data"]))

    def get_approval(self, order_id: str) -> Optional[ApprovalRecord]:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE order_id = ?", (order_id,)
            ).fetchone()
        if not row:
            return None
        return ApprovalRecord(
            order_id=row["order_id"],
            status=ApprovalStatus(row["status"]),
            third_order=row["third_order"],
            approver=row["approver"],
            approve_time=row["approve_time"],
            reject_reason=row["reject_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def approve_order(self, order_id: str, approver: str, third_order: str) -> Optional[ApprovalRecord]:
        """审批通过"""
        record = self.get_approval(order_id)
        if not record:
            return None
        if record.status != ApprovalStatus.PENDING:
            logger.warning(f"Order {order_id} already {record.status.value}")
            return None

        record.approve(approver, third_order)
        self._update_approval(record)
        logger.info(f"Order approved: {order_id} -> {third_order}")
        return record

    def reject_order(self, order_id: str, approver: str, reason: str = "") -> Optional[ApprovalRecord]:
        """审批拒绝"""
        record = self.get_approval(order_id)
        if not record:
            return None
        if record.status != ApprovalStatus.PENDING:
            return None

        record.reject(approver, reason)
        self._update_approval(record)
        logger.info(f"Order rejected: {order_id}, reason: {reason}")
        return record

    def _update_approval(self, record: ApprovalRecord):
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE approvals SET status=?, third_order=?, approver=?,
                   approve_time=?, reject_reason=?, updated_at=?
                   WHERE order_id=?""",
                (record.status.value, record.third_order, record.approver,
                 record.approve_time, record.reject_reason, record.updated_at,
                 record.order_id),
            )

    def set_approval_instance(self, order_id: str, instance_id: str):
        """记录订单与审批实例的映射"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO approval_instances (order_id, instance_id) VALUES (?, ?)",
                (order_id, instance_id),
            )

    def get_order_by_instance(self, instance_id: str) -> Optional[str]:
        """通过审批实例 ID 查找订单 ID"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT order_id FROM approval_instances WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        return row["order_id"] if row else None

    def list_pending(self) -> List[Dict]:
        """列出所有待审批订单"""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT a.order_id, a.created_at, o.data
                   FROM approvals a LEFT JOIN orders o ON a.order_id = o.order_id
                   WHERE a.status = 'pending'
                   ORDER BY a.created_at DESC"""
            ).fetchall()

        result = []
        for row in rows:
            order_data = json.loads(row["data"]) if row["data"] else {}
            result.append({
                "order_id": row["order_id"],
                "order_price": order_data.get("order_price", 0),
                "company_name": order_data.get("company_name", ""),
                "purchase_account": order_data.get("purchase_account", ""),
                "sku_count": len(order_data.get("sku_list", [])),
                "created_at": row["created_at"],
            })
        return result

    def list_all(self, page: int = 1, size: int = 20) -> Dict:
        """返回全量订单列表（含审批状态），支持分页"""
        offset = (page - 1) * size
        with self._get_conn() as conn:
            total_row = conn.execute("SELECT COUNT(*) FROM approvals").fetchone()
            total = total_row[0] if total_row else 0

            rows = conn.execute(
                """SELECT a.order_id, a.status, a.approver, a.approve_time,
                   a.reject_reason, a.created_at, a.updated_at, o.data
                   FROM approvals a LEFT JOIN orders o ON a.order_id = o.order_id
                   ORDER BY a.created_at DESC
                   LIMIT ? OFFSET ?""",
                (size, offset),
            ).fetchall()

        orders = []
        for row in rows:
            order_data = json.loads(row["data"]) if row["data"] else {}
            orders.append({
                "order_id": row["order_id"],
                "company_name": order_data.get("company_name", ""),
                "order_price": order_data.get("order_price", 0),
                "sku_count": len(order_data.get("sku_list", [])),
                "purchase_account": order_data.get("purchase_account", ""),
                "status": row["status"],
                "approver": row["approver"],
                "approve_time": row["approve_time"],
                "reject_reason": row["reject_reason"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            })
        return {"total": total, "page": page, "size": size, "orders": orders}

    def get_stats(self) -> Dict:
        """返回订单统计指标"""
        with self._get_conn() as conn:
            # 状态分布
            status_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM approvals GROUP BY status"
            ).fetchall()
            status_counts = {row["status"]: row["cnt"] for row in status_rows}
            for s in ("pending", "approved", "rejected", "cancelled"):
                status_counts.setdefault(s, 0)

            # 月度订单数
            monthly_rows = conn.execute(
                """SELECT strftime('%Y-%m', created_at) as month, COUNT(*) as cnt
                   FROM approvals GROUP BY month ORDER BY month"""
            ).fetchall()
            monthly_counts = [{"month": r["month"], "count": r["cnt"]} for r in monthly_rows]

            # 月度金额汇总
            amount_rows = conn.execute(
                """SELECT strftime('%Y-%m', a.created_at) as month,
                   SUM(CAST(json_extract(o.data, '$.order_price') AS REAL)) as total
                   FROM approvals a JOIN orders o ON a.order_id = o.order_id
                   WHERE o.data IS NOT NULL
                   GROUP BY month ORDER BY month"""
            ).fetchall()
            monthly_amounts = [{"month": r["month"], "total": round(r["total"] or 0, 2)} for r in amount_rows]

            # 审批时效（仅 approved 状态）
            timing_row = conn.execute(
                """SELECT
                   AVG((julianday(approve_time) - julianday(created_at)) * 24) as avg_hours,
                   MIN((julianday(approve_time) - julianday(created_at)) * 24) as min_hours,
                   MAX((julianday(approve_time) - julianday(created_at)) * 24) as max_hours
                   FROM approvals
                   WHERE status = 'approved' AND approve_time != '' AND created_at != ''"""
            ).fetchone()
            avg_h = round(timing_row["avg_hours"] or 0, 1)
            min_h = round(timing_row["min_hours"] or 0, 1)
            max_h = round(timing_row["max_hours"] or 0, 1)

            # 总订单数
            total_row = conn.execute("SELECT COUNT(*) FROM approvals").fetchone()
            total_orders = total_row[0] if total_row else 0

            # 总金额
            amount_row = conn.execute(
                "SELECT SUM(CAST(json_extract(data, '$.order_price') AS REAL)) FROM orders WHERE data IS NOT NULL"
            ).fetchone()
            total_amount = round(amount_row[0] or 0, 2)

        return {
            "status_counts": status_counts,
            "monthly_counts": monthly_counts,
            "monthly_amounts": monthly_amounts,
            "approval_timing": {"avg_hours": avg_h, "min_hours": min_h, "max_hours": max_h},
            "total_orders": total_orders,
            "total_amount": total_amount,
        }

    def verify_checkout_sign(self, data: Dict, secret_key: str = "") -> bool:
        """
        验证 checkOut 回调签名
        签名规则：MD5(pin + uniqueNo + strustNo + appId)
        """
        pin = data.get("pin", "")
        unique_no = data.get("uniqueNo", "")
        strust_no = data.get("strustNo", "")
        app_id = data.get("appId", "")
        actual = data.get("sign", "")

        # 方案1: MD5(pin + uniqueNo + strustNo + appId) 大写
        expected1 = hashlib.md5(
            f"{pin}{unique_no}{strust_no}{app_id}".encode("utf-8")
        ).hexdigest().upper()

        # 方案2: 小写
        expected2 = hashlib.md5(
            f"{pin}{unique_no}{strust_no}{app_id}".encode("utf-8")
        ).hexdigest()

        # 方案3: strustNo 签名 MD5(pin + uniqueNo + time) 大写
        expected3 = hashlib.md5(
            f"{pin}{unique_no}".encode("utf-8")
        ).hexdigest().upper()

        logger.info(f"Checkout sign verify: pin={pin}, uniqueNo={unique_no}, "
                    f"strustNo={strust_no}, appId={app_id}")
        logger.info(f"Checkout sign: actual={actual}")
        logger.info(f"Checkout sign: expected1(uppercase)={expected1} match={expected1==actual}")
        logger.info(f"Checkout sign: expected2(lowercase)={expected2} match={expected2==actual}")
        logger.info(f"Checkout sign: expected3(strustNo style)={expected3} match={expected3==actual}")

        # TODO: 测试环境 sign 为空，暂时跳过验签，上线前需确认 ZKH 生产环境是否传 sign
        if not actual:
            logger.warning("Checkout sign is empty, skipping verification (test mode)")
            return True
        return expected1 == actual

    # ==================== 应用配置 ====================

    def get_config(self, key: str) -> Optional[str]:
        """读取应用配置项"""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_config WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str):
        """设置应用配置项"""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) "
                "VALUES (?, ?, datetime('now', 'localtime'))",
                (key, value),
            )