# TradingAgents-CN 部署指南

纯镜像拉取部署，无需克隆代码仓库，只需两个文件即可一键启动。

## 快速开始

```bash
# 1. 创建部署目录并进入
mkdir tradingagents && cd tradingagents

# 2. 下载两个文件（任选其一）
#   方式 A：从仓库下载
wget https://raw.githubusercontent.com/bg8cfb/TradingAgents-CN/main/docker-compose.hub.nginx.yml
wget https://raw.githubusercontent.com/bg8cfb/TradingAgents-CN/main/deploy/.env.example

#   方式 B：从本地复制（如果已克隆仓库）
cp /path/to/TradingAgents-CN/docker-compose.hub.nginx.yml .
cp /path/to/TradingAgents-CN/deploy/.env.example .env

# 3. 修改 .env（可选 — 不修改也能启动，使用默认值）
vi .env

# 4. 启动
docker compose -f docker-compose.hub.nginx.yml up -d

# 5. 访问 http://localhost:8080
#    默认管理员: admin / admin123
```

## 配置加载优先级

从高到低：

1. **部署目录 `.env`** — 用户显式配置（docker compose 自动读取同目录 `.env`）
2. **`docker-compose.hub.nginx.yml` 的 `${VAR:-default}`** — 内联默认值
3. **应用代码默认值** — SecretService / Settings 类兜底

因此，无需创建 `.env` 也能启动；任何在 `.env` 中显式设置的值都会覆盖 compose 默认值。

## 关键变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TA_VERSION` | `latest` | 镜像 tag，可固定到指定版本 |
| `NGINX_PORT` | `8080` | 对外访问端口 |
| `MONGODB_PASSWORD` | `tradingagents123` | MongoDB root 密码（首次部署后请勿修改） |
| `REDIS_PASSWORD` | `tradingagents123` | Redis 密码（首次部署后请勿修改） |
| `JWT_SECRET` | 空 → 自动生成 | JWT 签名密钥（留空则由 SecretService 生成并持久化） |
| `CSRF_SECRET` | 空 → 自动生成 | CSRF 令牌密钥 |
| `INITIAL_ADMIN_PASSWORD` | `admin123` | 首次管理员密码（首次登录后立即修改） |
| `TUSHARE_TOKEN` | 空 | Tushare Pro API Token，用于 A 股数据接入 |

## 常用操作

```bash
# 查看日志
docker compose -f docker-compose.hub.nginx.yml logs -f backend

# 重启服务
docker compose -f docker-compose.hub.nginx.yml restart

# 停止并清理（保留数据卷）
docker compose -f docker-compose.hub.nginx.yml down

# 彻底清理（含数据卷，谨慎使用！）
docker compose -f docker-compose.hub.nginx.yml down -v
```

## 升级

```bash
# 拉取最新镜像并重启
docker compose -f docker-compose.hub.nginx.yml pull
docker compose -f docker-compose.hub.nginx.yml up -d
```

## 数据持久化

容器使用以下命名卷（位于 `/var/lib/docker/volumes/`）：

- `tradingagents_mongodb_data` — MongoDB 数据
- `tradingagents_redis_data` — Redis 数据
- `tradingagents_runtime` — 后端运行时（日志等）
- `tradingagents_config` — 用户配置（MCP、Agent 配置）

执行 `docker compose down` 不会删除数据；加 `-v` 才会一并删除卷。

## 故障排查

- **首次启动慢**：MongoDB 初始化、健康检查通过需要约 30-60 秒，请耐心等待。
- **JWT 警告**：留空 `JWT_SECRET` 时后端日志会提示自动生成，属正常现象。
- **忘记 admin 密码**：进入 MongoDB 直接修改 `users` 集合的 bcrypt 哈希，或参考后端文档的密码重置脚本。
