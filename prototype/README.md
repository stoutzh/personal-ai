# Aion Agents SDK 最小原型

这是 v0.3 旁边的独立实验入口，复用现有启动背景加载与文件工具，不替换原聊天循环或迁移存档。

## 开始

在 Mac 终端运行：

```bash
cd ~/Documents/AI/personal-ai
prototype/.venv/bin/python prototype/sdk_demo.py --check
prototype/.venv/bin/python prototype/sdk_demo.py --smoke
```

第二条会检查配置，不联网；第三条使用真实模型，按提示隐藏输入 DeepSeek API key。也可使用现有 `DEEPSEEK_API_KEY` 环境变量。不自动读取 .env，不把密钥保存到项目文件；可选 macOS 钥匙串保存，不需要 OpenAI key。真实调用会使用服务商额度，发送所选启动背景、测试问题及工具结果。

`--smoke` 要求模型实际调用列目录工具，然后在第二轮回忆随机口令。只有工具成功、口令正确且 Session 包含消息才显示 PASS。正常至少三次模型请求，各轮最多四次，无自动重试。

日常试聊：`prototype/.venv/bin/python prototype/sdk_demo.py`，输入 `/exit` 退出。可加 `--model 模型名` 临时覆盖模型。

## 你在验证什么

- Agent：一份角色说明、模型和工具清单。
- Runner：SDK 帮你完成“模型提出工具请求 → Python 执行 → 模型继续回答”的循环。
- FunctionTool：包装原有 `list_directory` 和 `read_text_file`，保留开放路径、越界与链接拦截、16000 字节文本限制。
- 启动背景：复用 `aion.load_instructions`，只加载 `aion.json` 的 files 名单。启动时显示文件名，`--check` 也会验证背景文件。每次启动重新加载，运行中不自动刷新。
- 运行事实：明确告诉模型当前是 SDK runtime 以及实际的持久或临时 Session 模式，旧背景中的存档描述不代表本次能力。progress 已明确区分 legacy 和 SDK；程序本身不自动改写 context。
- Session：SDK 自动保存并重新带上对话历史。普通聊天使用磁盘 SQLite 数据库；`--resume` 可跨进程恢复。`--no-save` 和 smoke 验证仍只使用内存。
- Provider：明确使用 Chat Completions 适配器和自定义客户端，不使用 Responses 或任何 OpenAI hosted-only 工具。tracing 同时在环境、SDK 全局和运行配置关闭。

## 更换兼容服务

沿用根目录 `aion.json` 的 provider 配置：endpoint、model、api_key_env、model_env、extra_body。SDK 会把完整 `/chat/completions` 地址转为 base_url。保留当前 DeepSeek 模型与 thinking 配置；切换服务时移除它不支持的 extra_body 选项。修改此共享配置也会影响 v0.3，实验前应留意 Git diff。

这里的 provider-agnostic 指支持 Chat Completions 工具调用协议的服务可换配置，并不保证任意模型/API 都兼容。

## 安装和离线验证

```bash
python3 -m venv prototype/.venv
prototype/.venv/bin/python -m pip install -r prototype/requirements.txt
prototype/.venv/bin/python -B -m unittest discover -s prototype -p 'test_*.py' -v
python3 -B -m unittest discover -s tests -v
```

虚拟环境是原型专用依赖箱，不更改系统 Python 包。requirements.txt 固定本次验证过的依赖版本。离线测试模拟服务端回复，但真实经过 SDK 适配器、工具执行与 Session；离线 PASS 不等于真实 DeepSeek 已通过。

官方参考：[Agents SDK 模型与服务商](https://developers.openai.com/api/docs/guides/agents/models)、[会话状态](https://developers.openai.com/api/docs/guides/agents/results)、[Tracing](https://developers.openai.com/api/docs/guides/agents/integrations-observability)。

## 第二阶段：背景与文件读取

第一阶段真实 DeepSeek 的列目录与两轮 Session 已由用户在本机验证通过。第二阶段新增启动背景及文本读取，离线测试已覆盖完整 SDK 工具往返、背景名单以及读取边界；真实 DeepSeek 的背景加载、文件读取和普通聊天也已由用户验证通过。

```bash
cd ~/Documents/AI/personal-ai
prototype/.venv/bin/python prototype/sdk_demo.py --smoke-files
```

这个命令先执行原有验证，再要求模型读取 README.md。只有本轮记录到成功的 read_text_file 调用才报告文件读取通过；它不自动评价概括文字的质量。默认 README.md 已在工具开放名单内。

普通聊天也可以尝试：“根据启动背景，概括 Aion 的目标”和“读取 README.md，说明文件工具的限制”。启动背景是之前保存的快照，当前项目事实应通过工具核对。

## 第三阶段：独立持久 Session

默认新建 SDK 会话，文件位于 `.aion/sdk-sessions/会话编号.sqlite3`。SDK 自动保存用户消息、模型回复及工具调用/结果；成功回合后打印 `[SDK Session 已保存]`。`.aion/sessions/` 的 v0.3 JSON 文件不会被读取或修改。

```bash
# 新会话
prototype/.venv/bin/python prototype/sdk_demo.py
# 退出后恢复最近一次成功保存的 SDK 会话
prototype/.venv/bin/python prototype/sdk_demo.py --resume
# 恢复启动时显示的指定编号
prototype/.venv/bin/python prototype/sdk_demo.py --resume 会话编号
# 临时聊天，不写入磁盘
prototype/.venv/bin/python prototype/sdk_demo.py --no-save
```

`--resume` 在原数据库追加消息，不复制旧库。没有存档或指定编号无效时明确报错，不会悄悄开始新会话。不要在两个终端同时恢复同一编号；程序拒绝并发使用同一会话。最近会话指针只在成功回合后更新，空会话和 smoke 测试不会挤掉它。API 失败或中断时不显示已保存提示；SDK 可能已保存部分中间消息，因此不能把失败回合视为完整结果。

会话目录权限 700、数据库权限 600，Git 忽略整个 `.aion/`，现有模型工具不能访问隐藏目录。会话是本地明文；存储前遮蔽当前 API key 和常见 sk- 字串，不存储客户端配置，但这不是通用秘密识别器。继续聊天会把历史发送给当前配置的服务商。历史中的系统说明不恢复，启动背景从现有名单重新加载。

### 本机真实 DeepSeek 验证

1. 不带参数启动，说“请记住本次恢复口令 blue-river-42，并读取 README.md”。看到回复和已保存提示后输入 `/exit`。
2. 新启动加 `--resume`，再次隐藏输入密钥。检查显示相同会话编号以及恢复消息数量。
3. 问“刚才的恢复口令是什么？刚才读过哪个文件？”，确认回忆正确，再说“继续：现在我们在验证重启恢复”。看到已保存提示后退出。
4. 再次 `--resume`，问“刚才我们在验证什么？”，确认追加的消息也被保存。

离线测试已用两个真正退出/重启的进程验证 SDK 会话及工具历史恢复、继续写入、背景更新和 legacy 文件不变；模型 API 回复为模拟。用户已验证真实 DeepSeek 退出、重启、同一会话恢复、正确回忆及继续回复后的保存提示。继续回复之后的第二次重启尚未展示。模型曾错误地把只读工具解释成不能持久保存，现已补充明确说明和实际恢复状态；这项措辞修正仍需日常使用观察。

## API key 只输入一次（macOS）

```bash
prototype/.venv/bin/python prototype/sdk_credentials.py
```

在本机终端隐藏输入，密钥保存到 macOS 登录钥匙串并校验可读取。以后 SDK runtime 优先使用配置的环境变量，其次使用钥匙串，无需重复输入。无以上来源时，交互终端仍支持一次性隐藏输入且不保存。

钥匙串条目按完整 endpoint 和 api_key_env 隔离。修改 endpoint 后需要为新地址保存密钥。再次运行上述命令可更新对应条目。`--status` 只报告可用性，不显示密钥。密钥不放进命令行参数、代码或 Git 文件；对话 SQLite 的密钥脱敏继续保留。此功能仅接入 SDK runtime，不改变 legacy 密钥流程。

macOS 可能要求解锁或允许 Python 访问钥匙串；系统权限由用户在系统窗口处理。保存完成后，Codex 可以尝试使用相同入口执行已授权的真实 API 测试，不需把密钥发到聊天。

### 自动真实验证结果（2026-09-10）

钥匙串凭据已由 Codex 自动读取并用于真实 DeepSeek 测试。为避免发送个人背景，测试使用生成的临时 README、背景和随机标记，数据库也独立。三次进程启动验证了工具调用、首次恢复（7 条历史）、继续聊天、第二次恢复（9 条历史）与新增标记回忆，最终保存 11 条消息。模型正确说明了程序自动保存与只读工具权限的区别。未改动用户正在使用的会话或 latest 指针；完整个人背景下的措辞表现仍通过日常使用观察。

## 当前运行能力事实层（2026-09-10）

`prototype/sdk_capabilities.py` 位于 SDK instructions 层，不是模型工具。`run_agent` 在每轮 Runner.run 前读取同一个 Session 的已有消息数，通过本地 RuntimeState 传给动态 instructions 回调；回调在每次模型请求前生成 runtime_capabilities。它不会作为 user/assistant 消息写入 Session，也不会改写历史。

事实来源：当前 Agent.tools 中启用的工具对象、注册时绑定的文件操作元数据、FileTools 实际开放路径、Session 实际 db_path，以及本轮开始前的消息数。SDK 会提前保存当前用户输入，因此历史数量在 Runner.run 之前采样，避免新会话被误判为有旧历史。工具作用不靠名字猜测；未知工具元数据或尚未适配的动态启用方式会在请求前报错。当前只支持现有 FunctionTool 和布尔启用开关，不增加任何工具或权限。

结构化字段包括 history_available、history_items_before_run、session_storage、program_session_persistence、available_tools、filesystem_actions、file_write_tool_present 和 file_tools_read_only。几句固定的解释只定义“历史上下文不授予权限”，具体能力由每次计算的字段决定。原型不再拼接旧的静态能力段，也不使用 legacy BASE 的能力声明；所选背景仍按原名单加载。

离线验证：14 项 SDK 测试及 20 项 legacy 测试通过，覆盖新旧历史、内存/磁盘、工具重命名/移除/禁用、未标注工具拒绝、实际请求注入和历史不变。真实 DeepSeek 使用完整启动背景和全新隔离 Session，三次请求验证无历史磁盘会话、有历史磁盘会话和无历史内存会话。检查实际发出的事实字段后，模型正确解释会话持久化不等于文件写权限。没有访问或改动用户既有历史；不保证模型未来每次回复都遵循，但事实来源与请求注入可独立检查。
