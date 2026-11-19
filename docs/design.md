# 钉钉 Stream 机器人适配设计

## 1. 目标

修复 `XiaosuHandler` 与 `dingtalk-stream 0.24.3` 的接口不匹配，使员工在钉钉群里 @ 小苏或私聊时能收到带引用的回复，异常时仍有兜底文案。

## 2. 现状与根因

SDK 回调链：

```
DingTalkStreamClient.route_message
  -> handler.raw_process(CallbackMessage)   # handlers.py:26
  -> await handler.process(CallbackMessage) # handlers.py:27
```

当前 `backend/app/dingtalk_bot.py` 的实现是：

```python
def process(self, message: dingtalk_stream.ChatbotMessage): ...
```

问题：

1. `process` 是同步函数，而 SDK 会 `await` 它的返回值，运行时会抛 `TypeError`。
2. `process` 实际收到的是 `CallbackMessage`（只有 `.data`/`.headers`），不是 `ChatbotMessage`，直接取 `message.session_webhook` / `message.text` 会抛 `AttributeError`。
3. 即使改成 `async def`，若在事件循环里同步调用 `answer_chat`（含 OpenAI 网络请求与数据库 IO），会阻塞 Stream 连接的心跳。

## 3. 设计方案

- `process` 改为 `async def process(self, callback: dingtalk_stream.CallbackMessage)`。
- 用 `dingtalk_stream.ChatbotMessage.from_dict(callback.data)` 解析业务消息。
- 只处理 `msgtype == "text"` 的消息；`message.text` 为空时直接 ACK，不回复。
- 会话键沿用现有逻辑：`sender_staff_id or sender_id` + `conversation_id`，保证按用户和会话隔离上下文。
- 数据库与 LLM 调用放入独立线程：`await asyncio.to_thread(_answer, ...)`；`_answer` 内部自行创建和关闭 `SessionLocal`，避免跨线程共享 Session。
- 回复改用 SDK 自带的 `reply_markdown(title, text, incoming_message)` 与 `reply_text(text, incoming_message)`，不再手写 `requests.post`，同时自动带上 @ 提问人。
- 有引用时在答案末尾追加「参考来源」列表（文件名 + 段落号）。
- 任何异常：记录日志，调用 `reply_text` 发送兜底文案，仍返回 `AckMessage.STATUS_OK`，避免钉钉侧一直重试。

## 4. 依赖（当前环境已实测）

| 依赖 | 版本 | 用途 |
|---|---|---|
| Python | >=3.11（当前 3.13.12） | 运行时，使用 `asyncio.to_thread` |
| dingtalk-stream | 0.24.3 | Stream 客户端、`CallbackMessage`、`ChatbotMessage`、`AckMessage` |
| openai | 2.54.0 | 问答与 Tool Calling |
| sqlalchemy | 2.1.9 | 会话与消息存储 |
| pytest / pytest-asyncio | 9.2.0 / 1.5.0 | 自动化测试 |

不新增第三方依赖；`requests` 由 `dingtalk-stream` 传递依赖，本轮代码不再直接导入。

## 5. 数据流

```
钉钉消息
  -> CallbackMessage
  -> ChatbotMessage.from_dict
  -> asyncio.to_thread(_answer)   # DB + RAG + Tool Calling
  -> reply_markdown / reply_text
  -> 员工
```

## 6. 测试方案

新增 `backend/tests/test_dingtalk_bot.py`，不依赖真实钉钉和 OpenAI：

1. 正常路径：mock `answer_chat` 返回答案与引用，断言 `process` 可被 await、返回 `STATUS_OK`，且 markdown 中包含答案与引用文件名。
2. 异常路径：mock `answer_chat` 抛错，断言调用兜底回复且仍返回 `STATUS_OK`。

手工验收（需真实凭证，未执行）：在钉钉测试群用两个不同账号分别提问，确认回复带引用且上下文互不串扰。

## 7. 已知限制

- `session_webhook` 有时效，答案生成过慢可能发送失败；后续可改为先 ACK、再由后台任务推送。
- 未按 `message_id` 做幂等，钉钉重推时可能重复回答。
- 真实企业后台的机器人权限与事件订阅仍需在开发者后台验证。

## 8. Windows 本地一键启动（补充）

### 背景

现有 `scripts/*.sh` 依赖 bash，Windows PowerShell 无法直接执行；同时 Next.js 的 `output: "standalone"` 在 Windows 上收集构建产物时需要创建符号链接，普通权限会报 `EPERM`，导致 `pnpm build` 失败。`pnpm dev` 不受影响。

### 方案

- 新增 `scripts/dev.ps1`、`scripts/start.ps1`、`scripts/test.ps1`，与现有 sh 脚本一一对应。
- `dev.ps1`：自动复制 `backend/.env` 与 `frontend/.env.local`，安装依赖，然后分别打开后端与前端窗口。
- `next.config.ts` 仅在环境变量 `NEXT_STANDALONE=1` 时启用 `output: "standalone"`；Docker 构建显式设置该变量，本地 Windows 构建不生成 standalone，从而绕开符号链接限制。
- `.env.example` 的 `OPENAI_API_KEY` 置空，避免占位值被误判为已配置。

### 验证

- `pnpm build` 在本机通过（不启用 standalone）。
- `.\scripts\test.ps1` 输出 7 passed。
- PowerShell 脚本使用 `[Parser]::ParseFile` 做语法校验。

## 9. 相对时间日期换算（补充）

### 问题

联调中问“他上周来上班几天？”时，模型调用 `get_attendance` 的日期参数是 `2024-04-01~2024-04-05`，而不是当前年份的上一周。根因是系统提示没有注入当前日期，模型只能凭训练数据猜测日期。

### 方案

- `agent.py` 新增 `build_system_prompt(context, now=None)`，把 `Asia/Shanghai` 的当前日期、星期和时分注入系统提示。
- 增加规则：遇到“今天/昨天/上周/本月”等相对时间，必须先按当前时间换算成具体日期，再调用工具。
- `answer_chat` 与 `stream_chat_events` 两条链路统一使用该函数。
- `now` 参数可注入，保证测试确定性。

### 验证

- 单元测试固定 `now=2026-11-19 10:30`，断言提示包含“2026-11-19 星期四 10:30”和相对时间规则。
- 用千问复测“员工 001 → 他上周来上班几天？”，工具参数为 `2026-11-12~2026-11-18`，回答“出勤 3 天”，不再出现 2024 年日期。模型将“上周”解释为最近 7 天；为消除歧义，提示中已约定“‘上周’指上一个自然周（周一至周日），‘最近一周/过去七天’指滚动 7 天”。
- Mock 考勤补充 `2026-11-09~11-13`（上一自然周），员工 001 上周出勤 5 天；即使按“最近 7 天”解释，结果同样为 5 天。

## 10. Web 调试页引用展示（补充）

### 问题

流式接口在结束时发送 `meta` 事件，其中包含 `citations` 和 `tools_used`，但 `Dashboard.tsx` 只处理了 `token` 与 `error`，因此 Web 调试页看不到引用来源，只有钉钉端会追加来源。

### 方案

- 前端新增 `Citation` 类型与 `citations` 状态，每次提问时清空。
- 解析到 `meta` 事件时写入引用列表。
- 在回答下方渲染“参考来源”标签：文件名 + 段落号，鼠标悬停显示该段原文。
- 仅改调试对话页；对话日志页暂不存储引用，范围不变。

### 验证

- `pnpm build` 通过。
- 浏览器实测：提问“员工每年有几天年假？”后，回答下方出现“参考来源”，显示《员工手册.md · 段落 1》与《FAQ.md · 段落 1》两个标签。
