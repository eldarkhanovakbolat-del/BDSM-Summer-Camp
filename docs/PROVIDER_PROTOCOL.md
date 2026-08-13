# Provider 接口协议

Provider 是公开版与用户私人系统之间的唯一边界。默认实现已经覆盖 OpenAI-compatible 模型接口和一个中立的 HTTP 记忆协议。

## AI Provider

默认类：`OpenAICompatibleProvider`。

### 请求

```http
POST {AI_BASE_URL}/chat/completions
Authorization: Bearer {AI_API_KEY}
Content-Type: application/json
X-Camp-Purpose: main | audience
X-Camp-Session: <session identifier>
```

```json
{
  "model": "configured-model",
  "messages": [
    { "role": "system", "content": "..." },
    { "role": "user", "content": "..." }
  ],
  "stream": false
}
```

本地无鉴权网关可以把 `AI_API_KEY` 留空。`AI_MODEL` 必填。

`AI_EXTRA_HEADERS_JSON` 可以给特殊网关附加字符串请求头；`AI_EXTRA_BODY_JSON` 可以附加温度等请求字段。两者都只能保存在服务端环境变量中。`Content-Type`、`X-Camp-Purpose`、`X-Camp-Session` 等保留请求头由应用最终设置，不能通过额外请求头覆盖，以免破坏主 AI 与观众隔离。

### 响应

```json
{
  "choices": [
    {
      "message": {
        "content": "回复文本"
      }
    }
  ]
}
```

`content` 也兼容由 `{ "text": "..." }` 片段组成的数组。

### 主 AI 与观众

默认情况下，同一个 Provider 会收到两类 purpose：

- `main`：主 AI；可包含服务端人设与 Memory Provider 召回；
- `audience`：文字 AI 观众；不得由网关注入主 AI 私人人设或记忆。

如果现有网关会对所有请求无条件注入私人上下文，需要在网关或自定义 Provider 中根据 `purpose` 做隔离。不能隔离时，可以设置 `AUDIENCE_AI_BASE_URL`、`AUDIENCE_AI_API_KEY`、`AUDIENCE_AI_MODEL`，让观众使用独立的 OpenAI-compatible 端点；也可以禁用观众。独立观众端点不会自动继承主 AI 密钥。

### 新增非兼容 Provider

在 `server/providers/ai.py`：

1. 继承 `AIProvider`；
2. 实现 `configured`；
3. 实现 `complete(messages, purpose, session_id)`；
4. 在 `build_ai_provider()` 注册一个中立名称；
5. 为主/观众隔离、错误脱敏和空回复添加测试。

不要把 SDK、供应商字段或秘密读取逻辑放进 `server/app.py`。

## Memory Provider

默认 `MEMORY_PROVIDER=off`。启用 `http` 后，服务端调用以下两个端点。

### 召回

```http
POST {MEMORY_BASE_URL}{MEMORY_RECALL_PATH}
Authorization: Bearer {MEMORY_API_KEY}
Content-Type: application/json
```

```json
{
  "namespace": "visitor:<visitor-id>:main",
  "session_id": "<summer-camp-session-id>",
  "query": "用户本轮文字",
  "limit": 8,
  "metadata": {
    "application": "bdsm-summer-camp",
    "topic": "Ageplay",
    "mode": "study",
    "visitor_id": "<visitor-id>"
  }
}
```

响应可使用合并文本：

```json
{ "text": "与本轮有关的记忆" }
```

或列表：

```json
{
  "memories": [
    "一条记忆",
    { "content": "另一条记忆" },
    { "text": "也支持 text 字段" }
  ]
}
```

### 写入

```http
POST {MEMORY_BASE_URL}{MEMORY_REMEMBER_PATH}
Authorization: Bearer {MEMORY_API_KEY}
Content-Type: application/json
```

```json
{
  "namespace": "visitor:<visitor-id>:main",
  "session_id": "<summer-camp-session-id>",
  "user_message": "用户本轮文字",
  "assistant_message": "主 AI 本轮回复",
  "metadata": {
    "application": "bdsm-summer-camp",
    "topic": "Ageplay",
    "mode": "study",
    "visitor_id": "<visitor-id>"
  }
}
```

任意 `2xx` JSON 对象响应都视为成功。

### 失败策略

记忆是可选增强：召回或写入失败会记录服务端警告，但不应阻断主 AI 回复。首次开场不会召回或写入长期记忆，以免把自动开场当成用户经历。

### 新增非兼容 Memory Provider

在 `server/providers/memory.py`：

1. 继承 `MemoryProvider`；
2. 实现 `recall()` 与 `remember()`；
3. 保证 `namespace` 隔离；
4. 不向日志打印记忆正文或密钥；
5. 在 `build_memory_provider()` 注册；
6. 添加失败不阻断主回复、观众不调用记忆的测试。

## 夏令营自身 HTTP API

前端使用以下端点：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/health` | 服务状态；不返回密钥和私人地址 |
| GET | `/api/catalog` | 三栏完整目录 |
| GET | `/api/sessions?visitor_id=` | 最近会话 |
| GET | `/api/sessions/{id}?visitor_id=` | 恢复会话 |
| POST | `/api/sessions` | 创建会话并生成开场 |
| POST | `/api/sessions/{id}/messages` | 发送一轮消息 |

服务端本身不提供用户账号认证；公开给多人之前不要把这些端点直接暴露给不受信任的互联网用户。
