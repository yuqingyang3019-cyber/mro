md = """# 震坤行 Punch-Out 接口清单

基础信息：
- 服务域名：`openapi.uat.zkh360.com`（测试）/ 生产域名由震坤行提供
- 协议：HTTPS
- 鉴权：accessToken（24h 有效期）
- 格式：JSON
- 公共请求头：`Content-Type: application/json; charset=UTF-8`

---

## 一、鉴权

### 1.1 获取 accessToken

| 项目 | 内容 |
|------|------|
| 接口名 | accessToken |
| 路径 | `POST /punchout/m2/accessToken` |
| 鉴权 | 不需要授权 |
| 用途 | 获取 token，后续业务接口鉴权凭证 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| client_id | String | Y | 对接账号 |
| client_secret | String | Y | 对接账号密码 |
| timestamp | String | Y | 调用时间，格式 `yyyy-MM-dd HH:mm:ss` |
| username | String | Y | 鉴权用户 |
| password | String | Y | 鉴权密码 |

**响应参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| access_token | String | Y | token 值 |
| expires_in | Int | Y | 过期时间（秒），默认 24h |
| refresh_token | String | N | 刷新 token |
| time | String | Y | 当前时间 |

---

## 二、登录

### 2.1 获取信任登录标识 trustedLogin

| 项目 | 内容 |
|------|------|
| 接口名 | trustedLogin |
| 路径 | `POST /punchout/m2/strustNo?token={access_token}` |
| 鉴权 | 需要授权（token 放在 query 参数） |
| 用途 | 获取信任登录标识，有效期 30 分钟 |

**请求参数（strustReqVo）：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| pin | String | N | 震坤行用户名 |
| uniqueNo | String | Y | 客户侧用户唯一标识 |
| time | Long | Y | 生成时间（毫秒级） |
| sign | String | Y | 签名（MD5） |

**签名规则：** `MD5(pin + uniqueNo + time)` 转大写

**响应：** 返回信任登录标识 strustNo

### 2.2 系统登录 checkIn

| 项目 | 内容 |
|------|------|
| 接口名 | checkIn |
| 路径 | `POST /punchout/m2/strust/checkIn` |
| 鉴权 | 不需要授权 |
| 格式 | form 表单提交（`multipart/form-data`） |
| 用途 | 用户使用信任标识登记访问，获取初始入口地址 |

**请求参数（form 表单）：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| pin | String | N | 震坤行用户名 |
| strustNo | String | Y | 信任登录标识 |
| appId | String | Y | 模块 ID（固定值 `ESP`） |
| sign | String | Y | 签名（MD5） |
| uniqueNo | String | Y | 客户侧用户唯一标识 |
| hookUrl | String | N | 订单信息回传地址（客户提供） |
| customfield1 | String | N | 自定义参数 |
| customFields | String | N | 自定义参数（JSON，支持发票抬头） |

**签名规则：** `MD5(pin + uniqueNo + strustNo + appId)`

**响应：** 成功跳转到 APPID 对应首页；失败跳转错误页面

---

## 三、订单

### 3.1 推送订单 checkOut

| 项目 | 内容 |
|------|------|
| 接口名 | checkOut |
| 路径 | 由客户实现的回调接口（即 checkIn 传入的 hookUrl） |
| 方法 | `POST` |
| 鉴权 | 需要授权 |
| 用途 | 震坤行回调客户系统，推送预订单信息 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| pin | String | Y | 客户平台用户名 |
| strustNo | String | Y | 信任登录标识 |
| uniqueNo | String | Y | 客户端唯一标识 |
| appId | String | Y | 模块 ID |
| sign | String | Y | 签名 |
| orderId | String | Y | 电商订单号 |
| state | Int | Y | 物流状态（0新建/1妥投/2拒收/3部分妥投） |
| orderState | Int | Y | 订单状态（0取消/1有效） |
| submitState | Int | Y | 确认状态（0未确认/1确认） |
| orderPrice | Double | Y | 订单含税价格 |
| orderNakedPrice | Double | Y | 不含税价格 |
| orderTaxPrice | Double | Y | 税额 |
| freight | Double | Y | 总运费 |
| sku | sku_entity[] | Y | 商品列表 |
| address | String | N | 收货人详细地址 |
| receiveRemark | Int | N | 收货备注（1任意/2工作日） |
| name | String | N | 收货人 |
| mobile | String | N | 收货人手机号 |
| purchaseOrg | String | N | 采购组织名称 |
| companyName | String | N | 发票抬头 |
| purchaseAccount | String | N | 下单人用户名 |
| purchaseMobile | String | N | 下单人电话 |
| invoiceName | String | N | 收票人姓名 |
| invoicePhone | String | N | 收票人电话 |
| invoiceAddress | String | N | 收票人地址 |
| remark | String | N | 备注（<100字） |
| deliveryRemark | Int | N | 发货备注（1有货先发/2货齐再发） |
| aes256Sign | String | N | 订单加密签名 |

**sku_entity[]：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skuId | String | Y | 商品编码 |
| num | Int | Y | 商品数量 |
| price | BigDecimal | Y | 含税协议价格 |
| name | String | Y | 商品名称 |
| tax | Int | Y | 商品税率 |
| nakedPrice | BigDecimal | Y | 不含税协议价 |
| image | String | N | 商品图片地址 |
| targetCatalogId | Long | N | 客户目录 ID |
| thirdSku | String | N | 客户物料号 |
| thirdSkuName | String | N | 客户物料名称 |
| demandNote | String | N | 需求描述 |

### 3.2 确认订单 confirmOrder

| 项目 | 内容 |
|------|------|
| 接口名 | confirmOrder |
| 路径 | `POST /punchout/m2/confirmOrder` |
| 鉴权 | 需要授权 |
| 用途 | 确认预订单，确认后电商开始配货 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| orderId | String | Y | ZKH 订单号 |
| thirdOrder | String | Y | 客户订单号 |

### 3.3 取消订单 cancel

| 项目 | 内容 |
|------|------|
| 接口名 | cancel |
| 路径 | `POST /punchout/m2/cancel` |
| 鉴权 | 需要授权 |
| 用途 | 订单未确认前取消（确认后不允许取消） |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| orderId | String | Y | ZKH 订单号 |

### 3.4 更新订单明细 updateOrderDetail

| 项目 | 内容 |
|------|------|
| 接口名 | updateOrderDetail |
| 路径 | `POST /punchout/m2/order/detail/update/v2` |
| 鉴权 | 需要授权 |
| 用途 | 订单未审批通过前更新明细（不支持增加数量） |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| orderId | String | Y | ZKH 订单号 |
| skuInfo | sku_entity[] | Y | 订单明细 |

**skuInfo：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| skuNo | String | Y | 商品编码 |
| count | Int | Y | 数量（0 表示取消该行） |

---

## 四、发货

### 4.1 查询发货单物流轨迹 orderTrack

| 项目 | 内容 |
|------|------|
| 接口名 | orderTrack |
| 路径 | `POST /punchout/m2/orderTrack` |
| 鉴权 | 需要授权 |
| 用途 | 根据发货单号查询物流轨迹 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| packageId | String | Y | 发货单号 |

**响应：**

| 名称 | 类型 | 说明 |
|------|------|------|
| packageId | String | 发货单号 |
| orderTrack | orderTrack_entity[] | 配送信息 |
| selfOperated | Boolean | 是否自营物流 |
| selfLogisticsInfo | Object | 自营轨迹 URL |

**orderTrack_entity：** `msgTime`（时间）、`content`（内容）、`operator`（操作人）

### 4.2 查询发货单包裹明细 package

| 项目 | 内容 |
|------|------|
| 接口名 | package |
| 路径 | `POST /punchout/m2/package` |
| 鉴权 | 需要授权 |
| 用途 | 根据发货单号查询包裹 SKU、数量、物流单号 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| packageId | String | Y | 发货单号 |

**响应：**

| 名称 | 类型 | 说明 |
|------|------|------|
| packageId | String | 发货单号 |
| orderId | String | 订单号 |
| deliveryCode | String | 物流单号 |
| deliveryTime | String | 发货时间 |
| deliveryName | String | 物流公司 |
| deliveryItems | deliveryItems_entity[] | 发货明细 |

**deliveryItems_entity：** `skuId`（商品编码）、`num`（数量）

### 4.3 确认收货 confirmPackage

| 项目 | 内容 |
|------|------|
| 接口名 | confirmPackage |
| 路径 | `POST /punchout/m2/confirmPackage` |
| 鉴权 | 需要授权 |
| 用途 | 通知震坤行发货单已确认收货 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| packageId | String | Y | ZKH 发货单号 |

---

## 五、售后

### 5.1 申请售后 serviceOrder

| 项目 | 内容 |
|------|------|
| 接口名 | serviceOrder |
| 路径 | `POST /punchout/m2/serviceOrder` |
| 鉴权 | 需要授权 |
| 用途 | 申请售后（仅退款 / 退货退款） |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| orderNumber | String | Y | 震坤行订单号 |
| serviceType | Integer | Y | 售后类型（1退货退款/2仅退款） |
| detail | detail_entity[] | Y | 售后商品集合 |
| description | String | N | 申请原因 |
| returnType | Integer | N | 售后方式（1供应商上门/2客户物流） |
| applicant | String | Y | 申请人名称 |
| applicationPhone | String | Y | 申请人电话 |

**detail_entity：** `skuId`（商品编号）、`num`（数量）

**响应：** 返回 `serviceId`（售后单号）

### 5.2 取消售后单 serviceOrder/cancel

| 项目 | 内容 |
|------|------|
| 接口名 | serviceOrder/cancel |
| 路径 | `POST /punchout/m2/serviceOrder/cancel` |
| 鉴权 | 需要授权 |
| 用途 | 未审核的售后单取消 |

**请求参数：** `serviceId`（售后单号）

### 5.3 查询售后单 serviceOrder/fetch

| 项目 | 内容 |
|------|------|
| 接口名 | serviceOrder/fetch |
| 路径 | `POST /punchout/m2/serviceOrder/fetch` |
| 鉴权 | 需要授权 |
| 用途 | 查询售后单当前状态 |

**请求参数：** `serviceId`（售后单号）

**响应：**

| 名称 | 类型 | 说明 |
|------|------|------|
| serviceId | String | 售后单号 |
| state | String | 状态（1审核中/3驳回/4通过/5完成/6取消） |
| remark | String | 说明 |
| taxFreeTotalPrice | Double | 未税总金额 |
| tax | Double | 税额 |
| totalPrice | Double | 含税总金额 |
| orderNumber | String | 订单号 |
| serviceType | String | 售后类型 |
| detail | ZKHServiceOrderDetailDTO[] | 商品信息 |

---

## 六、消息

### 6.1 获取消息 get

| 项目 | 内容 |
|------|------|
| 接口名 | get |
| 路径 | `POST /punchout/m2/get` |
| 鉴权 | 需要授权 |
| 用途 | 拉取订单变更消息（建议最多一次 100 条） |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| type | Int | N | 消息类型（不传返回全部） |

**消息类型：**

| type | 说明 |
|------|------|
| 5 | 妥投/拒收消息（订单/发货单） |
| 10 | 订单取消消息 |
| 11 | 预订单生成成功 |
| 33 | 正式订单生成成功 |
| 101 | 订单发货消息（拆分发货单） |
| 301 | 售后处理消息 |

**响应消息体 result_entity：**

| 名称 | 类型 | 说明 |
|------|------|------|
| id | String | 推送 ID |
| time | String | 推送时间 |
| type | Int | 消息类型 |
| orderId | String | 订单编号 |
| orderType | Int | 类型（1订单/2发货单） |
| packageId | String | 发货单号 |

### 6.2 删除消息 delete

| 项目 | 内容 |
|------|------|
| 接口名 | delete |
| 路径 | `POST /punchout/m2/delete` |
| 鉴权 | 需要授权 |
| 用途 | 消息处理成功后删除，否则后续消息不会返回 |

**请求参数：** `id`（推送消息 ID）

---

## 七、账号

### 7.1 同步人员信息 user/sync

| 项目 | 内容 |
|------|------|
| 接口名 | user/sync |
| 路径 | `POST /punchout/m2/user/sync` |
| 鉴权 | 需要授权 |
| 用途 | 查询/新增/更新人员账号 |

**请求参数：**

| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| token | String | Y | token |
| opt | String | Y | 操作模式（query/insert/update） |
| uniqueNo | String | Y | 客户侧用户唯一标识 |
| nickName | String | N | 姓名 |
| email | String | N | 邮箱 |
| mobile | String | N | 电话 |
| roleName | String | N | 角色（采购员/需求员/采购经理/集团管理员） |
| invoiceCustomerNames | Array | N | 关联发票抬头（最多 50 个） |
| stateCode | Integer | N | 状态（0停用/1启用） |

---

## 接口汇总表

| # | 接口名 | 路径 | 方向 | 说明 |
|---|--------|------|------|------|
| 1 | accessToken | `POST /punchout/m2/accessToken` | → ZKH | 获取 token |
| 2 | trustedLogin | `POST /punchout/m2/strustNo` | → ZKH | 获取信任登录标识 |
| 3 | checkIn | `POST /punchout/m2/strust/checkIn` | → ZKH | 系统登录（form） |
| 4 | checkOut | 客户 hookUrl | ZKH → | 推送预订单 **（需客户实现）** |
| 5 | confirmOrder | `POST /punchout/m2/confirmOrder` | → ZKH | 确认订单 |
| 6 | cancel | `POST /punchout/m2/cancel` | → ZKH | 取消订单 |
| 7 | updateOrderDetail | `POST /punchout/m2/order/detail/update/v2` | → ZKH | 更新订单明细 |
| 8 | orderTrack | `POST /punchout/m2/orderTrack` | → ZKH | 查询物流轨迹 |
| 9 | package | `POST /punchout/m2/package` | → ZKH | 查询包裹明细 |
| 10 | confirmPackage | `POST /punchout/m2/confirmPackage` | → ZKH | 确认收货 |
| 11 | serviceOrder | `POST /punchout/m2/serviceOrder` | → ZKH | 申请售后 |
| 12 | serviceOrder/cancel | `POST /punchout/m2/serviceOrder/cancel` | → ZKH | 取消售后 |
| 13 | serviceOrder/fetch | `POST /punchout/m2/serviceOrder/fetch` | → ZKH | 查询售后 |
| 14 | get | `POST /punchout/m2/get` | → ZKH | 获取消息 |
| 15 | delete | `POST /punchout/m2/delete` | → ZKH | 删除消息 |
| 16 | user/sync | `POST /punchout/m2/user/sync` | → ZKH | 同步人员信息 |
"""

with open("/Users/forestdeep/mro/ZKH_PunchOUT_API_List.md", "w") as f:
    f.write(md)
print("Done")