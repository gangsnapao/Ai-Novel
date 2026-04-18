# Ai-Novel Lite

一个适合直接上传仓库并通过 Docker Compose 在服务器部署的 AI 小说项目分支。

## 目标

- `git clone` 后即可进入生产部署流程
- 使用单一 `docker-compose.yml`
- 对外开放前端 `5173` 端口
- 后端仅绑定到宿主机 `127.0.0.1:8000`
- Postgres / Redis 不对外暴露
- 数据持久化到 Docker volume

## 目录说明

- `frontend/`：React + Vite + Nginx
- `backend/`：FastAPI + SQLAlchemy + Alembic + RQ
- `docker-compose.yml`：生产部署主文件
- `.env.example`：部署环境变量模板

当前默认部署方案使用：

- PostgreSQL：业务主库
- Redis：任务队列
- Chroma 持久化目录：向量数据默认保存在 `ainovel_app_data`

这样可以避免强依赖 pgvector 特殊镜像，提升开箱部署成功率。

## 生产部署

### 1. 克隆项目

```bash
git clone -b lite <your-repo-url> Ai-Novel
cd Ai-Novel
```

### 2. 准备环境变量

```bash
cp .env.example .env
```

建议至少修改：

- `POSTGRES_PASSWORD`
- `AUTH_ADMIN_USER_ID` / `AUTH_ADMIN_PASSWORD`（如果你希望首次启动时自动创建管理员）

> 如果你不填管理员账号，项目也可以启动；之后可直接在页面注册首个普通账号。

### 3. 启动

```bash
docker compose up -d --build
```

### 4. 访问

- 前端：`http://<服务器IP>:5173`
- 后端健康检查（仅宿主机本地）：`http://127.0.0.1:8000/api/health`

## 更新部署

```bash
git pull
docker compose up -d --build
```

常用检查命令：

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
docker compose logs -f rq_worker
```

## 数据持久化

Compose 会自动创建以下 volume：

- `ainovel_postgres_data`
- `ainovel_app_data`

其中：

- PostgreSQL 数据保存在 `ainovel_postgres_data`
- 向量数据 / 自动生成密钥等保存在 `ainovel_app_data`

如果你要彻底清空白板数据：

```bash
docker compose down -v
```

## 现有 SQLite 数据迁移

如果你之前本地使用的是 `backend/ainovel.db`，它不会自动进入 Docker 的 Postgres。

仓库已提供迁移工具：

- `backend/scripts/migrate_sqlite_to_postgres.py`
- `backend/scripts/migrate_sqlite_to_postgres.md`

请先部署 Postgres，再按文档执行迁移。

## 开发模式

本仓库仍保留 `start.py` 作为本地开发入口，但**生产部署请使用 Docker Compose**。

## 安全建议

- 不要把真实 `.env` 提交到仓库
- 不要对外暴露 Postgres / Redis
- 为管理员设置强密码
- 正式上线时建议在 5173 前再接一层反向代理 / HTTPS
