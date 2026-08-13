# 部署说明

本页给接手仓库的 AI 使用。普通用户只需提供想使用的设备或服务器。

> 当前版本没有登录系统。默认只部署给本人或彼此完全信任的人；需要从公网访问时，必须先在站点外层增加可靠的登录或访问保护。

## 环境要求

- Node.js 22.13+；
- pnpm；
- Python 3.11+；
- 能访问用户选择的 AI 后端；
- 选课时能访问 `https://www.bdsmwiki.info/`，已缓存词条可离线继续使用。

Python 服务端只使用标准库，无需 `pip install`。

前端使用 **vinext**，不是标准 Next.js 运行时。请保留仓库现有的 `pnpm dev`、`pnpm run build` 和 `pnpm start` 命令，不要擅自替换成 `next` CLI。

## 本机开发

```bash
pnpm install
cp .env.example .env
python server/app.py
pnpm dev
```

前端默认 `127.0.0.1:3000`，夏令营服务端默认 `127.0.0.1:8765`。前端通过同域 `/api` 转发访问服务端。

## 生产构建

```bash
pnpm install --frozen-lockfile
pnpm run build
pnpm start -- --hostname 127.0.0.1 --port 3000
python server/app.py
```

生产环境应使用进程管理器分别保持两个进程运行：

- Web：`pnpm start -- --hostname 127.0.0.1 --port 3000`
- API：`python server/app.py`

对外反向代理只需要指向 Web 的 `127.0.0.1:3000`。API 保持内网监听，Web 通过 `CAMP_SERVER_URL=http://127.0.0.1:8765` 访问它。

## 关键环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `CAMP_SERVER_URL` | `http://127.0.0.1:8765` | Web 服务端访问夏令营 API 的地址 |
| `CAMP_BIND_HOST` | `127.0.0.1` | Python API 监听地址 |
| `CAMP_PORT` | `8765` | Python API 端口 |
| `CAMP_DB_PATH` | `./data/camp.db` | SQLite 数据库 |
| `AI_BASE_URL` | 本机占位地址 | 模型接口基础 URL |
| `AI_API_KEY` | 空 | 服务端模型密钥 |
| `AI_MODEL` | 空 | 必填模型名 |
| `AI_PERSONA_FILE` | 空 | 可选、仓库外的人设文本文件 |
| `AUDIENCE_AI_BASE_URL` | 空 | 可选的独立观众模型端点；留空则复用主 AI Provider |
| `AUDIENCE_AI_API_KEY` | 空 | 独立观众端点自己的密钥，不继承主 AI 密钥 |
| `AUDIENCE_AI_MODEL` | 空 | 独立观众端点的模型名 |
| `MEMORY_PROVIDER` | `off` | `off` 或 `http` |

完整列表见 `.env.example`。

## 反向代理要求

- 终止 HTTPS；
- 转发 `Host` 和 `X-Forwarded-Proto`；
- 允许普通 GET/POST 请求；
- AI 请求可能较慢，代理读取超时建议不少于 180 秒；
- 不缓存 `/api/*`；
- 不直接公开 `.env`、`data/`、人设文件或源代码目录。
- 访问日志不要记录查询字符串；会话读取请求的 `visitor_id` 位于查询参数中。以 Nginx 为例，应让自定义日志格式记录 `$uri`，不要记录 `$request` 或 `$request_uri`。

## 数据与备份

需要持久保存：

- `.env`：秘密配置，限制读取权限；
- `data/camp.db`：会话与词条缓存；
- 可选的人设文件。

更新前先备份数据库和配置。SQLite 在线备份应使用 SQLite 的备份能力或短暂停止写入后复制，避免只复制 WAL 主文件导致不完整。

## 健康检查

```bash
curl -fsS http://127.0.0.1:8765/health
curl -fsS http://127.0.0.1:3000/
```

`/health` 只说明 AI 是否配置、记忆是否启用，不显示密钥或私人地址。

## 部署前验证

```bash
pnpm run build
node --test tests/rendered-html.test.mjs
python -m unittest -v server/test_app.py
python scripts/check_setup.py
```

然后创建真实会话并刷新恢复。若部署平台只允许单进程，接手 AI 可以用平台原生多服务方案，或写一个只负责启动 Web 与 API 的轻量入口；不要因此把模型密钥移到浏览器。

## 多人使用警告

把网页暴露到公网并不等于适合陌生多人共用。外层访问保护只适合本人或一组共用凭据的可信使用者；若用户要求互不信任的多人托管，先暂停部署并实现真正的账号认证、数据所有权、记忆隔离、持久限流和删除机制。
