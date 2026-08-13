# 把 BDSM 夏令营交给你的 AI

这份说明同时写给用户和接手仓库的编程 AI。目标不是让用户学习后端，而是让 AI 快速识别现有条件，选择最少改动的接入方式。

## 用户只需要准备什么？

把你已经拥有的东西告诉接手 AI，知道多少说多少：

- AI 后端或网关的文档/地址；
- 模型名称；
- API 密钥（只通过安全方式提供，不要粘贴到公开 Issue 或截图）；
- 是否已有长期记忆系统；
- 想在本机、NAS、VPS 还是部署平台运行；
- 想只供自己使用，还是将来给多人使用。

不知道某一项就说“不知道”。接手 AI 应先检查现有环境，而不是让你猜。

## 路径 A：已有 AI 后端和记忆系统

这是能力最完整的路径。

接手 AI 应该：

1. 判断 AI 后端是否兼容 `POST /v1/chat/completions`；
2. 兼容时只填写 `.env` 的 `AI_BASE_URL`、`AI_API_KEY`、`AI_MODEL`；
3. 不兼容时在 `server/providers/ai.py` 增加一个小适配器；
4. 判断原有人设是由后端自动注入，还是需要通过 `AI_PERSONA_FILE` 读取；
5. 将记忆系统适配成 `docs/PROVIDER_PROTOCOL.md` 中的 `/recall` 与 `/remember` 契约，或直接新增 Memory Provider；
6. 验证观众调用不带人设、不召回记忆、不写入记忆。

典型配置：

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://example.invalid/v1
AI_API_KEY=replace-me
AI_MODEL=replace-me

# 若后端本来就会注入人设，留空。
AI_PERSONA_FILE=

MEMORY_PROVIDER=http
MEMORY_BASE_URL=http://127.0.0.1:8001
MEMORY_API_KEY=replace-me
MEMORY_RECALL_PATH=/recall
MEMORY_REMEMBER_PATH=/remember
```

如果网关本身会按身份注入人设，Provider 应确保主调用使用正确身份；观众调用根据 `X-Camp-Purpose: audience` 进入无私人记忆的隔离身份。

若现有网关做不到隔离，可直接给观众填写另一套 OpenAI-compatible 配置：

```dotenv
AUDIENCE_AI_PROVIDER=openai_compatible
AUDIENCE_AI_BASE_URL=https://audience.example.invalid/v1
AUDIENCE_AI_API_KEY=replace-me
AUDIENCE_AI_MODEL=replace-me
```

观众配置全部留空时会复用主 AI 后端。只要配置了独立观众端点，主 AI 的 `AI_API_KEY` 就不会自动传给它；请为观众明确填写自己的密钥，无鉴权端点则留空。

## 路径 B：只有 AI 后端

这是最简单也最常见的路径。SQLite 会保存夏令营里的会话，所以刷新和返回仍能继续聊天；只是模型不会自动记住其他应用或很久以前的关系记忆。

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://example.invalid/v1
AI_API_KEY=replace-me
AI_MODEL=replace-me
MEMORY_PROVIDER=off
```

如果后端不会自动注入 AI 原有人设，可以在仓库外创建一个纯文本文件并设置：

```dotenv
AI_PERSONA_FILE=/受保护的路径/persona.txt
```

不要把该文件提交到仓库。

## 路径 C：只有记忆系统

记忆系统只能提供过去的信息，不能自己生成回复，因此仍需要一个模型接口。

接手 AI 应该：

1. 先为用户选择的模型建立一个服务端对话接口；
2. 能做成 OpenAI Chat Completions 兼容格式时直接使用默认 Provider；
3. 再接入已有记忆；
4. 分别测试“召回成功”和“写入成功”；
5. 确认记忆失败时主对话仍可继续。

模型密钥必须留在服务端，不能由浏览器直接调用供应商。

## 路径 D：两者都没有

最快方式不是先造一套复杂后端，而是把一个可用模型接口接到默认 Provider，并保持记忆关闭。

接手 AI 可以选择：

- 用户已经购买额度的 OpenAI-compatible 模型服务；
- 本机或服务器上的、提供 OpenAI-compatible 端点的本地模型；
- 由 AI 编写一个很薄的服务端适配层，把所选模型的 SDK 转成 `chat/completions`。

最小接口只需要接收 `model` 和 `messages`，返回：

```json
{
  "choices": [
    { "message": { "content": "AI 的回复" } }
  ]
}
```

先让项目跑通，再决定是否增加长期记忆。不要在第一步引入数据库集群、向量服务或 MCP。

## 人设到底放在哪里？

按优先顺序选择一种，不要重复注入：

1. **后端原生人设**：最适合已有 AI 网关的用户，`AI_PERSONA_FILE` 留空；
2. **服务端人设文件**：后端没有人设能力时使用，文件放在仓库外；
3. **自定义 AI Provider**：后端要求特殊身份字段时，由 Provider 加入服务端请求。

AI 的“显示名称”只是界面字段，不等于后端身份，也不会自动创建人格。

## 记忆分成两类

- **本地会话记录**：默认 SQLite 自带，用来恢复夏令营中的对话；
- **长期关系记忆**：可选 Memory Provider，用来连接用户原有的跨应用记忆。

不要把两者混为一谈。关闭长期记忆不会让当前会话立即失忆；删除 SQLite 数据则会丢失夏令营会话。

## 接入完成检查表

- [ ] `GET /health` 显示 AI 已配置，但不泄露地址或密钥；
- [ ] 首页能加载 25 / 85 / 268 三栏目录；
- [ ] 能创建“共学”和“体验”会话；
- [ ] AI 名称可填写也可留空；
- [ ] 五种输入都能发送；
- [ ] 刷新后能恢复会话；
- [ ] 当前知识卡有 BDSM Wiki 来源链接；
- [ ] 观众可开关，且明确显示为 AI；
- [ ] 观众不读取或写入主 AI 记忆；
- [ ] `.env`、数据库和人设文件没有进入 Git；
- [ ] 构建、前端测试、后端测试与配置检查全部通过。

接口细节见 [docs/PROVIDER_PROTOCOL.md](./docs/PROVIDER_PROTOCOL.md)，部署见 [docs/DEPLOYMENT.md](./docs/DEPLOYMENT.md)。
