# 阿里云 ECS 部署指南

本文档介绍如何将 Crypto OI Dashboard 部署到阿里云 ECS（以 Ubuntu 22.04 为例），并通过 Nginx 反向代理 + HTTPS 对外提供服务。

## 前置准备

1. **阿里云账号**：已完成实名认证。
2. **域名**：已在阿里云完成域名注册或转入。
3. **备案**：若域名解析到中国大陆服务器，必须完成 ICP 备案（阿里云提供备案助手）。
4. **服务器**：建议至少 2核 4GB 内存，带宽 3-5Mbps。

## 1. 购买并初始化 ECS

1. 登录 [阿里云 ECS 控制台](https://ecs.console.aliyun.com/)。
2. 创建实例：
   - **地域**：选择离你用户最近的地域（如华东 1 杭州）。
   - **镜像**：Ubuntu 22.04 LTS（推荐）或 Alibaba Cloud Linux 3。
   - **实例规格**：2核 4GB 起步。
   - **带宽**：3Mbps 以上，按固定带宽计费更稳定。
   - **安全组**：放行 `22`（SSH）、`80`（HTTP）、`443`（HTTPS）端口。
3. 创建完成后，记录公网 IP 和 root 密码/密钥。

## 2. 域名解析

1. 进入 [阿里云云解析 DNS 控制台](https://dns.console.aliyun.com/)。
2. 为你的域名添加 A 记录：
   - **主机记录**：`oi`（例如二级域名 `oi.example.com`）
   - **记录值**：ECS 公网 IP
   - **TTL**：默认 10 分钟
3. 等待解析生效（通常几分钟到几小时）。

## 3. 连接服务器

```bash
ssh root@<ECS公网IP>
```

如果使用密钥，命令为：

```bash
ssh -i /path/to/your-key.pem root@<ECS公网IP>
```

## 4. 安装 Docker 和 Docker Compose

```bash
# 更新系统
apt-get update && apt-get upgrade -y

# 安装必要工具
apt-get install -y curl ca-certificates gnupg lsb-release git

# 安装 Docker
curl -fsSL https://get.docker.com | bash

# 启动并启用 Docker
systemctl enable --now docker

# 验证
docker --version
docker compose version
```

## 5. 克隆代码并配置

```bash
# 克隆仓库
git clone https://github.com/mmdzzh/coinglass_look.git /opt/coinglass_
cd /opt/coinglass_

# 创建环境变量文件
cp .env.example .env
nano .env
```

关键配置项：

```env
# 域名
DOMAIN=oi.example.com
ACME_EMAIL=your-email@example.com

# 数据库密码（建议生成强密码）
DATABASE_URL=postgresql+psycopg2://coinglass:YOUR_DB_PASSWORD@db:5432/coinglass
POSTGRES_USER=coinglass
POSTGRES_PASSWORD=YOUR_DB_PASSWORD

# 数据源
DATA_SOURCES=bybit,binance
DEFAULT_DATA_SOURCE=bybit

# 同步周期（可选）
BACKFILL_DAYS_5M=30
BACKFILL_DAYS_15M=30
BACKFILL_DAYS_1H=30
BACKFILL_DAYS_4H=365
```

> **安全提示**：生产环境务必将 `POSTGRES_PASSWORD` 和 `DATABASE_URL` 中的密码改为强密码。

## 6. 启动服务

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

检查状态：

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f web
```

## 7. 初始化数据库并同步数据

```bash
# 初始化表结构
docker compose -f docker-compose.prod.yml exec web python -c "from database import init_db; init_db()"

# 首次全量同步（建议先跑日线）
docker compose -f docker-compose.prod.yml exec web python sync_once.py

# 补全高频数据（根据需求选择）
docker compose -f docker-compose.prod.yml exec web python sync_intervals.py bybit --intervals 4h 1h 15m 5m
docker compose -f docker-compose.prod.yml exec web python sync_intervals.py binance --intervals 4h 1h 15m 5m
```

> 高频同步数据量较大，建议在 `screen` 或 `tmux` 中执行，避免 SSH 断开后中断。

```bash
apt-get install -y tmux
tmux new -s sync
docker compose -f docker-compose.prod.yml exec web python sync_intervals.py bybit --intervals 4h 1h 15m 5m
# 按 Ctrl+B 再按 D  detach，稍后可通过 tmux attach -t sync 查看
```

## 8. HTTPS 与反向代理

`docker-compose.prod.yml` 已内置 Caddy 反向代理，会自动申请 Let's Encrypt 证书。只要域名解析正确、80/443 端口放行，部署完成后即可访问：

```
https://oi.example.com
```

如果你更习惯 Nginx，可以关闭 Caddy 服务，改用外部 Nginx：

```bash
# 停止 Caddy
docker compose -f docker-compose.prod.yml stop caddy
```

然后安装 Nginx 并配置：

```bash
apt-get install -y nginx
certbot --nginx -d oi.example.com
```

Nginx 配置示例（` /etc/nginx/sites-available/coinglass`）：

```nginx
server {
    listen 80;
    server_name oi.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name oi.example.com;

    ssl_certificate /etc/letsencrypt/live/oi.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/oi.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 9. 配置定时同步（可选）

在服务器上添加 cron 任务，定时增量同步：

```bash
crontab -e
```

添加：

```cron
# 每小时增量同步日线
0 * * * * cd /opt/coinglass_ && docker compose -f docker-compose.prod.yml exec -T web python sync_intervals.py bybit --intervals 1d >> /var/log/coinglass_cron.log 2>&1

# 每 15 分钟同步高频
*/15 * * * * cd /opt/coinglass_ && docker compose -f docker-compose.prod.yml exec -T web python sync_intervals.py bybit --intervals 5m 15m 1h 4h >> /var/log/coinglass_cron.log 2>&1
```

> `-T` 参数用于避免 cron 环境下没有 TTY 导致的错误。

## 10. 常见问题

### 10.1 访问 Bybit / Binance API 超时

阿里云大陆地域访问境外交易所 API 可能不稳定。解决方案：

- 在 `.env` 中配置代理：
  ```env
  HTTP_PROXY=http://your-proxy-ip:port
  HTTPS_PROXY=http://your-proxy-ip:port
  ```
- 或在安全组允许出向访问，并选择香港/新加坡等海外地域部署。

### 10.2 备案要求

- 域名解析到中国大陆 ECS 必须完成 ICP 备案。
- 若不想备案，可选择阿里云香港/新加坡等境外地域，但延迟会稍高。

### 10.3 数据库备份

PostgreSQL 数据持久化在 Docker Volume `pgdata` 中。建议定期备份：

```bash
docker exec coinglass_db pg_dump -U coinglass coinglass > /backup/coinglass_$(date +%F).sql
```

### 10.4 升级部署

```bash
cd /opt/coinglass_
git pull origin main
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

## 11. 费用估算（参考）

| 项目 | 配置 | 费用 |
|------|------|------|
| ECS | 2核 4GB，3Mbps 带宽 | 约 50-100 元/月 |
| 域名 | .com / .cn | 约 60-100 元/年 |
| HTTPS | Let's Encrypt | 免费 |
| 备案 | 阿里云备案 | 免费 |

合计：约 **60-100 元/月** 即可稳定运行。

---

如有问题，参考项目根目录 `README.md` 或 `AGENTS.md`。
