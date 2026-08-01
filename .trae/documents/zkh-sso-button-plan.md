# 震坤行 SSO 一键登录 — 实现计划

## 一、当前状态

`GET /api/zkh/sso?unique_no=xxx` 已实现完整 SSO 流程，但缺少用户自动同步：
- 震坤行要求先用 `user/sync` 把用户信息同步过去，再用同样的 `uniqueNo` 做 SSO
- 当前没有自动同步逻辑，用户必须先手动调 `/api/zkh/users/sync` 创建用户

## 二、改动

### 1. `app.py` — 修改 SSO 登录路由

在 `sso_login()` 中，调用 `client.sso_login()` 之前，先自动同步用户：

```
用户请求 SSO → user/sync(query) 查用户是否存在
  → 不存在 → user/sync(insert) 创建用户
  → 存在 → 跳过
→ trustedLogin 获取 strustNo
→ 返回 checkIn 表单页面
```

### 2. `app.py` — 优化 SSO_FORM_TEMPLATE

将简陋的"正在跳转..."页面改为带加载动画的页面。

### 3. `zkh_punchout/client.py` — 新增 `ensure_user()` 方法

封装"查询 → 不存在则创建"的逻辑，方便复用。

## 三、文件改动

| 文件 | 改动 | 说明 |
|------|------|------|
| `zkh_punchout/client.py` | 新增 `ensure_user()` | 查询用户，不存在则自动创建 |
| `app.py` | 修改 `SSO_FORM_TEMPLATE` | 加载动画页面 |
| `app.py` | 修改 `sso_login()` 路由 | 调用 `ensure_user()` 再 SSO |

## 四、使用方式

```
访问：https://mro.water-healer.com/api/zkh/sso?unique_no=员工号&nick_name=张三&mobile=138xxxx
```

自动完成：同步用户 → 获取 strustNo → 跳转震坤行（已登录）。

## 五、验证

1. 本地启动 `python app.py`
2. 访问 `http://localhost:5000/api/zkh/sso?unique_no=test_user`
3. 日志应显示：user/sync query → （不存在则 insert） → trustedLogin → checkIn
4. 页面显示加载动画 → 自动跳转震坤行
5. `git push` → GitHub Actions → 生产验证