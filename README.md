# 演出票务与场次座位管理平台（纯后端）

演出剧目、场次与购票订单管理的纯后端 API 服务，作为 Feature 迭代题的基座工程。

## 技术栈

- Python + Django + Django REST Framework
- MySQL 8（字符集 utf8mb4），通过 PyMySQL 连接
- JWT 鉴权（djangorestframework-simplejwt）
- Gunicorn 运行

## 启动（Docker）

```bash
docker compose up --build
```

MySQL 就绪后，应用容器自动执行数据库迁移、灌入种子数据，服务监听 `http://127.0.0.1:7652`。

## 内置账号

唯一管理员（本平台只有 admin 一个角色）：

- 用户名：`admin`
- 密码：`admin123`

## 已实现的基础功能

- 登录签发 JWT、获取当前用户（`/api/auth/login`、`/api/auth/me`）
- 演出剧目增删改查（`/api/shows`）
- 场次增删改查（`/api/performances`）
- 购票下单（带余票校验、自动算金额并扣减库存）与订单查询（`/api/orders`）
- 仪表盘统计（`/api/dashboard/stats`）
- 健康检查（`/api/health`）

除 `login` 与 `health` 外，接口均需 `Authorization: Bearer <token>`。

## 编码说明

数据库使用 utf8mb4；DRF 开启 UNICODE_JSON，中文以 UTF-8 原样返回、不转义。
