# Nexora

为资源搜索、订阅下载和媒体整理提供统一入口。

Nexora 是一个面向私有媒体库的资源搜索、订阅下载与整理系统，通过 Telegram 交互连接 M-Team、qBittorrent 与媒体库整理流程。

## ✨ 功能特性

### 基础功能
- 🔍 通过 Telegram Bot 搜索 M-Team 资源
- 📂 支持按类别筛选（电影/剧集/音乐/其他/全部）
- ⬇️ 一键添加到 qBittorrent 下载
- 📊 查看下载状态

### 进阶功能
- 📡 **订阅管理**：订阅 TMDB 剧集/电影，自动轮询下载新集
- 🎬 **资源整理**：下载完成后自动/手动复制到 NAS 媒体库
- 🏷️ **刮削元数据**：自动生成 NFO、下载海报/封面（兼容 Emby/Jellyfin/Kodi）
- 🐳 Docker 一键部署

## 🚀 快速开始

### 1. 准备工作

- 安装 [uv](https://docs.astral.sh/uv/getting-started/installation/)（本地运行）或 Docker（容器部署）
- 获取 Telegram Bot Token（通过 [@BotFather](https://t.me/BotFather)）
- 获取 M-Team API Key（从网站设置中获取）
- 确保 qBittorrent WebUI 已启用
- （可选）获取 [TMDB API Key](https://www.themoviedb.org/settings/api)（用于刮削）

### 2. 本地运行

```bash
cd <repo-dir>

# 安装依赖
uv sync

# 复制配置文件并编辑
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入实际配置

# 运行
uv run python main.py
```

### 3. Docker 部署

#### 方式 A：从源码构建（推荐）
如果你已经 Clone 了源码，建议直接构建使用，确保版本最新：

```bash
# 准备配置文件
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入你的配置

# 构建并启动
docker-compose up -d --build
```

#### 方式 B：使用预编译镜像
如果你不想本地构建，可以直接拉取 GitHub 发布的镜像：

```bash
# 拉取最新镜像
docker-compose pull

# 启动
docker-compose up -d
```

**说明**：`docker-compose.yml` 中同时定义了 `build` 和 `image`。
- 使用 `--build` 时，Docker 会从本地源码构建镜像，并标记为对应的 `image` 名称。
- 不使用 `--build` 时，Docker 会优先使用本地已有镜像，或从 Registry 拉取。

#### 常用命令
```bash
# 查看日志
docker-compose logs -f

# 停止
docker-compose down
```

## 📖 配置说明

配置文件 `config.yaml` 主要选项：

```yaml
telegram:
  token: "BOT_TOKEN"        # Telegram Bot Token（必填）
  chat_id: ""               # 允许的 Chat ID（可选，留空允许所有）
  admins: []                # 管理员 User ID 列表

mteam:
  api_key: "API_KEY"        # M-Team API Key（必填）
  domain: "m-team.io"       # M-Team 域名
  categories:               # 搜索类别配置
    movie:
      name: "电影"
      ids: ["401", "419", "420", "421", "439"]
    # ... 其他类别

qbittorrent:
  host: "http://localhost"  # qBittorrent 地址（必填）
  port: 8080                # 端口
  username: "admin"         # 用户名
  password: "password"      # 密码

download:
  default_path: "/downloads"  # 默认下载路径

# 资源整理（可选）
organize:
  enabled: true
  mode: "manual"            # auto/manual/both
  dry_run: false            # 测试模式（只输出日志不实际复制）
  strict_id:
    enabled: true
    tv: true                # 电视剧必须命中 TMDB ID
    movie: true             # 电影必须命中 TMDB ID
  libraries:
    movie: "/media/Movies"
    tv: "/media/TV"
  naming:
    movie: "{{ title }}{% if year %} ({{ year }}){% endif %}/{{ title }}{% if year %} ({{ year }}){% endif %}{{ fileExt }}"
    tv: "{{ title }}{% if year %} ({{ year }}){% endif %}/Season {{ season }}/{{ title }} - S{{ '%02d' % season }}E{{ '%02d' % episode }}{{ fileExt }}"

  # TMDB 刮削（需要 API Key）
  tmdb:
    api_key: "YOUR_TMDB_API_KEY"
    language: "zh-CN"

# 订阅管理（可选）
subscription:
  enabled: true
  interval_minutes: 30      # 轮询间隔
  max_subs: 10              # 单次处理订阅数
  max_items_per_sub: 5      # 每个订阅最多下载集数
```

### 环境变量

Docker 部署时可通过环境变量覆盖配置：

| 变量 | 说明 |
|------|------|
| `TELEGRAM_TOKEN` | Telegram Bot Token |
| `MTEAM_API_KEY` | M-Team API Key |
| `QBIT_HOST` | qBittorrent 地址 |
| `QBIT_PORT` | qBittorrent 端口 |
| `QBIT_USERNAME` | qBittorrent 用户名 |
| `QBIT_PASSWORD` | qBittorrent 密码 |
| `TMDB_API_KEY` | TMDB API Key |

## 📱 使用方法

在 Telegram 中与 Bot 对话：

| 命令 | 说明 |
|------|------|
| 🔍 搜索 / `/search 关键词` | 搜索资源 |
| `/status` | 查看下载状态 |
| `/organize` | 手动整理：扫描已完成任务 |
| `/org_status` | 查看整理进度 |
| `/subscribe` | 添加订阅 |
| `/subs` | 查看/管理订阅 |
| `/help` | 显示帮助 |

### 搜索流程

1. 发送搜索关键词
2. 选择搜索类别（电影/剧集/音乐/其他/全部）
3. 从搜索结果中选择要下载的资源
4. 自动添加到 qBittorrent

### 订阅流程

1. 发送 `/subscribe` 或点击订阅按钮
2. 输入片名（支持季号如 `生活大爆炸 S05`）
3. 选择 电视剧/电影
4. 从 TMDB 搜索结果中选择
5. 系统自动轮询 M-Team 下载新集
6. 订阅状态自动按进度计算：`downloaded == total` 显示"已完成"，否则"更新中"
7. 轮询任务会自动跳过"已完成"的订阅，减少无效检查

## 🐳 Docker Compose 架构

 ```
 ┌──────────────────────────────────────────────────────────────┐
 │                Docker Compose (Bridge Network)               │
 ├──────────────────────────────────────────────────────────────┤
 │  ┌──────────────────────────────┐                           │
 │  │          nexora              │                           │
 │  │  ┌────────┐   ┌──────────┐  │                           │
 │  │  │ Nginx  │──►│ Python   │  │                           │
 │  │  │ :80    │   │ API+Bot  │  │                           │
 │  │  └────┬───┘   └────┬─────┘  │                           │
 │  │       │             │        │                           │
 │  │   supervisord 管理   │        │                           │
 │  └──────────────────────────────┘                           │
 │          │             │                                    │
 │          ▼             ▼                                    │
 │     Browser/User  qBittorrent                               │
 │      (Port 8000)  (Host/External IP)                        │
 └──────────────────────────────────────────────────────────────┘
 ```

 **说明**：单个容器内通过 supervisord 同时运行 Nginx（静态文件 + 反向代理）和 Python（API + Telegram Bot），对外仅暴露一个端口。

 **⚠️ 网络配置注意**：
 - 服务默认运行在 Docker `bridge` 网络中。
 - 如果您的 qBittorrent 运行在宿主机上（非 Docker），请在 `config.yaml` 中将 `host` 设置为宿主机 IP（如 Docker 网关 `172.17.0.1`），**不能**使用 `localhost`。

## 📁 项目结构

```
nexora/
├── main.py                # 主程序入口
├── modules/
│   ├── config.py          # 配置加载
│   ├── telegram_bot.py    # Telegram 交互
│   ├── pt_client.py       # PT 站点抽象接口（支持多站点扩展）
│   ├── mteam.py           # M-Team API
│   ├── qbit.py            # qBittorrent API
│   ├── organize.py        # 资源整理/刮削
│   ├── organize_queue.py  # 整理任务队列
│   ├── subscription.py    # 订阅管理（智能资源选择）
│   ├── tmdb_client.py     # TMDB API 客户端
│   ├── tmdb_nfo.py        # TMDB NFO 生成
│   ├── jinja_naming.py    # Jinja 命名模板
│   ├── meta_parser.py     # 文件名解析
│   └── store.py           # SQLite 数据存储
├── tests/                 # 单元测试
│   ├── test_pt_client.py  # PT 客户端测试
│   └── test_subscription.py # 订阅模块测试
├── pyproject.toml         # 项目配置与依赖 (uv)
├── config.yaml            # 配置文件（git 忽略）
├── config.example.yaml    # 配置示例
├── Dockerfile             # Docker 多阶段构建（前端+后端+Nginx）
├── nginx.conf             # Nginx 配置（容器内静态文件 + 反向代理）
├── supervisord.conf       # Supervisord 配置（管理 Nginx + Python 进程）
├── docker-compose.yml     # Docker Compose
└── web/                   # 前端源码 (React + Vite)
    ├── Dockerfile         # 独立前端镜像构建（备用）
    └── nginx.conf         # 独立前端 Nginx 配置（备用）
```

## 🧪 开发与测试

### 运行测试

```bash
# 安装开发依赖
uv sync --dev

# 运行所有测试
uv run pytest tests/ -v

# 运行代码检查
uv run ruff check modules/ main.py
```

### CI/CD

项目包含两个 GitHub Actions 工作流：

| 工作流 | 触发条件 | 说明 |
|--------|---------|------|
| `test.yml` | Push/PR | 自动运行 lint + pytest |
| `docker-build.yml` | 任意分支 Push、Tag 或手动触发 | 构建并推送 Docker 镜像到 ghcr.io |

`master` 分支 push 会更新 `latest`，其他分支 push 仅产出分支名和 `sha-*` 标签；`v*` tag 会产出版本标签并同步更新 `latest`。

### 扩展 PT 站点

项目支持多 PT 站点扩展，只需实现 `PTClient` 抽象接口：

```python
from modules.pt_client import PTClient, TorrentResult

class HDSkyClient(PTClient):
    @property
    def site_name(self) -> str:
        return "HDSky"

    def search(self, keyword: str, ...) -> list[TorrentResult]:
        # 实现搜索逻辑
        pass

    # 实现其他抽象方法...
```

### 资源选择优先级

订阅自动下载时，按以下优先级选择最佳资源：

1. **中字优先** - 带中文字幕的资源优先
2. **高分辨率** - 4K > 1080P > 720P
3. **来源质量** - REMUX > BluRay > WEB-DL
4. **做种数** - 做种多的优先

## ⚠️ 注意事项

1. **路径映射**：Docker 容器内路径必须与 qBittorrent 保存路径一致，否则无法读取源文件
2. **TMDB API**：电影/剧集刮削需要 TMDB API Key
3. **Dry Run 模式**：首次使用建议设置 `dry_run: true` 测试路径映射是否正确
4. **严格 ID 模式**：开启后未命中 TMDB ID 的文件会被 `skipped`，不会落盘
5. **剧集季目录规范**：系统会将 `.s2` 自动归一为 `.s02`；若历史 `.s2` 目录已存在，会优先复用旧目录避免分叉

## 📄 许可证

MIT License
