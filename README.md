# astrbot_plugin_discord_chatbot

Discord AI 聊天机器人插件，支持角色系统和 AI Token 计量。

**基于 astrbot 原生 API 实现**，使用 `llm_generate`、`persona_manager`、`conversation_manager`。

## 功能特性

### 🎭 角色系统
- 预设多个系统角色（Nova、Luna、Jake、Lex 等）
- 支持用户自定义角色（最多 5 个）
- 一键切换角色
- 自动同步到 astrbot persona_manager

### 🎟️ AI Token 计量
- **每天 5 条免费消息**（可配置）
- **点赞获得 3000 Token**（12 小时有效）
- 自动过期清理
- 优先消费即将过期的 Token

### 🗳️ Top.gg 投票奖励
- 集成 Top.gg webhook 自动接收投票事件
- 投票后自动发放 Token 奖励
- **周末双倍奖励**
- 支持连续投票统计

### 💬 对话管理
- 使用 astrbot 原生 conversation_manager
- 支持清空历史
- 角色切换时自动更新 persona

## 命令列表

| 命令 | 说明 |
|------|------|
| `/chatbot_status` | 查看状态（角色、免费消息、Token 余额） |
| `/chatbot_characters` | 查看可用角色列表 |
| `/chatbot_switch <角色名>` | 切换角色 |
| `/chatbot_clear` | 清空对话历史 |
| `/chatbot_vote` | 查看投票状态和投票链接 |
| `/chatbot_claim_vote` | 手动领取投票奖励 |
| `/chatbot_create_char <名称> <prompt>` | 创建自定义角色 |
| `/chatbot_delete_char <名称>` | 删除自定义角色 |
| `/chatbot_my_chars` | 查看我的自定义角色 |

## 配置说明

本插件使用 AstrBot 原生插件配置机制：

- 插件根目录的 `_conf_schema.json` 定义配置 Schema
- AstrBot 启动时会根据 Schema 生成配置实体并保存到 `data/config/<plugin_name>_config.json`
- 插件 `__init__(..., config: AstrBotConfig)` 会收到注入的配置，本插件会优先使用该配置

`config.yaml` 仅作为兼容 fallback（当运行环境未注入 `AstrBotConfig` 时才会读取），建议以 WebUI 配置为准。

配置项示例：

```yaml
# 免费消息配置
free_messages:
  daily_limit: 5  # 每天免费消息数量

# 点赞奖励配置
vote_reward:
  tokens: 3000           # 点赞奖励 token 数量
  expiry_hours: 12       # token 有效期（小时）

# Top.gg 投票配置
topgg:
  enabled: true                    # 是否启用 Top.gg 投票功能
  webhook_path: "/topgg/webhook"   # Webhook 路径
  webhook_port: 8080               # Webhook 端口
  webhook_auth: "your_secret_key"  # Webhook 认证密钥（在 Top.gg 设置中配置）
  bot_id: "your_bot_id"            # Bot ID
  token: ""                        # Top.gg API Token（可选）

# 角色系统配置
character:
  default: "Nova"        # 默认角色名称
  max_custom_characters: 5  # 每用户最大自定义角色数
```

## 添加系统角色

在 `characters/` 目录下创建 `.txt` 文件，文件名即为角色名。

例如 `characters/Nova.txt`:
```
你是 Nova，一个活泼可爱的助手...
```

插件启动时会自动将角色同步到 astrbot 的 persona_manager。

## 目录结构

```
astrbot_plugin_discord_chatbot/
├── main.py              # 插件入口（含核心聊天逻辑）
├── config.yaml          # 配置文件
├── metadata.yaml        # 插件元数据
├── characters/          # 系统角色目录
│   ├── Nova.txt
│   ├── Luna.txt
│   ├── Jake.txt
│   └── Lex.txt
├── data/                # 数据目录（自动创建）
│   ├── user_characters.json    # 用户角色选择
│   ├── custom_characters.json  # 自定义角色
│   ├── user_message_limits.json # 每日消息计数
│   ├── ai_tokens.json          # Token 余额
│   └── voted_users.json        # 投票记录
└── src/
    ├── handlers/
    │   └── topgg_webhook.py    # Top.gg webhook 处理
    └── managers/
        ├── token_manager.py     # AI Token 计量
        └── character_manager.py # 角色管理
```

## Top.gg Webhook 配置

1. 在 Top.gg 的 Bot 设置页面找到 **Webhooks** 部分
2. 设置 Webhook URL: `http://your-server:8080/topgg/webhook`
3. 设置 Authorization（与 `config.yaml` 中的 `webhook_auth` 一致）
4. 保存设置

当用户在 Top.gg 投票后，webhook 会自动接收事件并发放 Token 奖励。

## 使用 astrbot API

插件使用以下 astrbot 原生 API：

```python
# 获取 LLM provider
provider_id = await self.context.get_current_chat_provider_id(umo=umo)

# 调用 LLM
llm_resp = await self.context.llm_generate(
    chat_provider_id=provider_id,
    prompt=user_message,
)

# 对话管理
conv_mgr = self.context.conversation_manager
await conv_mgr.new_conversation(unified_msg_origin=umo, persona_id=persona_id)
await conv_mgr.add_message_pair(cid=curr_cid, user_message=..., assistant_message=...)

# 人格管理
persona_mgr = self.context.persona_manager
persona_mgr.create_persona(persona_id=..., system_prompt=...)
```

## 许可证

MIT License
