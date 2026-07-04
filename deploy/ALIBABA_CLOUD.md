# 阿里云 ECS 部署指南

本文档介绍如何将 Crypto OI Dashboard 部署到阿里云 ECS，并**重点保证 Bybit / Binance 等境外交易所 API 的数据可以正常下载**。

## 前置准备

1. **阿里云账号**：已完成实名认证。
2. **域名**：已在阿里云完成域名注册或转入。
3. **备案**：若域名解析到**中国大陆**服务器，必须完成 ICP 备案。
4. **服务器**：建议至少 2核 4GB 内存，带宽 3-5Mbps。

---

## 重要：如何保证能下载到数据

本服务需要从 Bybit、Binance 等境外交易所 API 拉取 Open Interest 数据。**阿里云中国大陆地域（如杭州、上海、深圳）默认访问这些 API 可能出现超时、连接重置或速度极慢的情况**。部署前请务必先解决网络问题。

### 方案一：选择阿里云境外地域（推荐、最简单）

直接购买阿里云**中国香港、新加坡、东京、法兰克福**等境外地域的 ECS：

- **优点**：无需代理即可直接访问 Bybit / Binance API，部署最简单。
- **缺点**：域名无需备案即可解析到境外服务器；但访问网站的用户在国内延迟可能稍高。
- **推荐配置**：
  - 地域：**中国香港** 或 **新加坡**
  - 镜像：Ubuntu 22.04 LTS
  - 规格：2核 4GB
  - 带宽：3Mbps 起步

### 方案二：中国大陆 ECS + 代理（需要代理资源）

如果你已经购买了大陆 ECS 并已完成备案，可以通过代理访问境外 API。

#### 2.1 准备一个可用的代理

代理形式可以是：

- 你自己已有的 Clash / V2Ray / Xray 节点
- 一台境外 VPS 转发的 SOCKS5/HTTP 代理
- 第三方代理服务（需自行判断合规性）

假设你有一个 HTTP 代理：`http://代理IP:端口`

#### 2.2 在服务器上安装并运行代理客户端

以 Clash 为例：

```bash
# 下载 Clash Premium（需自行准备 config.yaml）
cd /opt
mkdir clash && cd clash
wget https://github.com/Dreamacro/clash/releases/download/premium/clash-linux-amd64-2023.08.17.gz
gunzip clash-linux-amd64-2023.08.17.gz
chmod +x clash-linux-amd64-2023.08.17
ln -s clash-linux-amd64-2023.08.17 clash

# 将你的 config.yaml 放到 /opt/clash/
# 启动 Clash（HTTP 代理默认端口 7890）
nohup ./clash -f config.yaml > clash.log 2>&1 &
```

#### 2.3 配置服务使用代理

编辑 `/opt/coinglass_/.env`，添加：

```env
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
```

然后重启 web 容器：

```bash
cd /opt/coinglass_
docker compose -f docker-compose.prod.yml restart web
```

#### 2.4 验证 API 连通性

进入 web 容器测试：

```bash
docker compose -f docker-compose.prod.yml exec web bash

# 测试 Bybit API
python -c "
import requests, os
proxies = {'http': os.getenv('HTTP_PROXY',''), 'https': os.getenv('HTTPS_PROXY','')}
r = requests.get('https://api.bybit.com/v5/market/time', proxies=proxies, timeout=10)
print('Bybit:', r.status_code, r.text)
"

# 测试 Binance API
python -c "
import requests, os
proxies = {'http': os.getenv('HTTP_PROXY',''), 'https': os.getenv('HTTPS_PROXY','')}
r = requests.get('https://fapi.binance.com/fapi/v1/time', proxies=proxies, timeout=10)
print('Binance:', r.status_code, r.text)
"
```

如果能返回正常 JSON，说明代理配置成功。

### 方案三：中国大陆 ECS + 轻量应用服务器做代理

如果你只有大陆 ECS 但没有境外代理，可以临时购买一台阿里云**香港轻量应用服务器**（约 24 元/月），在上面安装 [gost](https://github.com/ginuerzh/gost) 转发 HTTP 代理：

```bash
# 在香港轻量服务器上
nohup gost -L http://:7890 > gost.log 2>&1 &
```

然后在大陆 ECS 的 `.env` 中配置：

```env
HTTP_PROXY=http://香港服务器IP:7890
HTTPS_PROXY=http://香港服务器IP:7890
```

> 安全提示：建议在香港服务器上配置防火墙，仅允许大陆 ECS 的 IP 访问 7890 端口。

---

## 1. 购买并初始化 ECS

1. 登录 [阿里云 ECS 控制台](https://ecs.console.aliyun.com/)。
2. 创建实例：
   - **地域**：优先选择 **中国香港 / 新加坡**；若必须大陆，请选择有代理方案的地域。
   - **镜像**：Ubuntu 22.04 LTS（推荐）或 Alibaba Cloud Linux 3。
   - **实例规格**：2核 4GB 起步。
   - **带宽**：3Mbps 以上，按固定带宽计费更稳定。
   - **安全组**：放行 `22`（SSH）、`80`（HTTP）、`443`（HTTPS）。
3. 创建完成后，记录公网 IP 和 root 密码/密钥。

## 2. 域名解析

1. 进入 [阿里云云解析 DNS 控制台](https://dns.console.aliyun.com/)。
2. 为你的域名添加 A 记录：
   - **主机记录**：`oi`（例如二级域名 `oi.example.com`）
   - **记录值**：ECS 公网 IP
   - **TTL**：默认 10 分钟
3. 等待解析生效（通常几分钟到几小时）。
4. 如果 ECS 在中国大陆，域名必须完成 ICP 备案才能通过 80/443 访问。

## 3. 连接服务器

```bash
ssh root@<ECS公网IP>
```

如果使用密钥：

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

# 如需代理（大陆 ECS 必填）
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
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
apt-get install -y nginx certbot python3-certbot-nginx
certbot --nginx -d oi.example.com
```

Nginx 配置示例（`/etc/nginx/sites-available/coinglass`）：

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

## 9. 配置定时同步（保证数据持续更新）

在服务器上添加 cron 任务：

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

## 10. 数据同步监控

### 10.1 查看最近一次同步是否成功

```bash
docker compose -f docker-compose.prod.yml logs --tail=50 web
```

### 10.2 查看数据库中各数据源的数据量

```bash
docker compose -f docker-compose.prod.yml exec db psql -U coinglass -d coinglass -c "
SELECT source, interval, COUNT(*) as cnt, MIN(timestamp), MAX(timestamp)
FROM open_interest
GROUP BY source, interval
ORDER BY source, interval;
"
```

### 10.3 检查 API 是否可达

```bash
docker compose -f docker-compose.prod.yml exec web bash
python -c "
from data_sources.bybit_source import BybitDataSource
from datetime import datetime, timezone, timedelta
src = BybitDataSource()
data = src.fetch_oi_history('BTCUSDT', '1h', start_time=datetime.now(timezone.utc)-timedelta(days=1), limit=5)
print('Bybit BTCUSDT 1h:', len(data), 'rows')
"
```

## 11. 常见问题

### 11.1 同步任务提示 API 超时或连接失败

- 确认 ECS 地域：境外地域通常可直接访问；大陆地域需要代理。
- 检查 `.env` 中 `HTTP_PROXY` / `HTTPS_PROXY` 是否配置正确。
- 在容器内运行第 10.3 节的 API 测试脚本验证。

### 11.2 备案要求

- 域名解析到中国大陆 ECS 必须完成 ICP 备案。
- 若不想备案，可选择阿里云香港/新加坡等境外地域。

### 11.3 数据库备份

PostgreSQL 数据持久化在 Docker Volume `pgdata` 中。建议定期备份：

```bash
mkdir -p /backup
docker exec coinglass_db pg_dump -U coinglass coinglass > /backup/coinglass_$(date +%F).sql
```

### 11.4 升级部署

```bash
cd /opt/coinglass_
git pull origin main
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```

## 12. 费用估算（参考）

| 项目 | 配置 | 费用 |
|------|------|------|
| ECS（境外） | 2核 4GB，3Mbps 带宽 | 约 60-120 元/月 |
| ECS（大陆） | 2核 4GB，3Mbps 带宽 | 约 50-100 元/月 |
| 香港轻量代理（可选） | 1核 1GB | 约 24 元/月 |
| 域名 | .com / .cn | 约 60-100 元/年 |
| HTTPS | Let's Encrypt | 免费 |
| 备案 | 阿里云备案 | 免费 |

合计：**60-150 元/月** 即可稳定运行。

---

如有问题，参考项目根目录 `README.md` 或 `AGENTS.md`。
