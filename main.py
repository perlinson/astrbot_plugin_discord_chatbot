# -*- coding: utf-8 -*-
"""
Discord AI Chatbot 插件
- 角色系统（使用 astrbot persona_manager）
- AI Token 计量（每天 N 条免费消息，点赞奖励）
- 对话历史管理（使用 astrbot conversation_manager）
- Top.gg 投票奖励
"""
import inspect
import yaml
from pathlib import Path
from typing import Optional, List

from astrbot.api import logger, AstrBotConfig
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, register, Context
from astrbot.core.agent.message import (
    AssistantMessageSegment,
    UserMessageSegment,
    TextPart,
)

from .src.managers.token_manager import token_manager
from .src.managers.character_manager import character_manager
from .src.handlers.topgg_webhook import topgg_webhook


def _load_plugin_config() -> dict:
    """加载插件配置"""
    config_path = Path(__file__).parent / "config.yaml"
    try:
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
    return {}


@register(
    name="DiscordChatbot",
    author="SXP-Simon",
    desc="Discord AI 聊天机器人插件，支持角色系统和 AI Token 计量",
    version="1.0.0",
)
class DiscordChatbot(Star):
    """Discord AI Chatbot 插件"""
    
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config = config
        self._plugin_config = _load_plugin_config() if not self.config else {}
        
        # 应用配置
        self._apply_config()

        import asyncio

        # 初始化人格到 astrbot persona_manager
        asyncio.create_task(self._init_personas())

        # 启动 Top.gg webhook 服务器
        asyncio.create_task(self._start_topgg_webhook())
        
        logger.info("DiscordChatbot 插件已加载")
    
    async def _start_topgg_webhook(self):
        """启动 Top.gg webhook 服务器"""
        try:
            await topgg_webhook.start()
        except Exception as e:
            logger.error(f"启动 Top.gg webhook 失败: {e}")
    
    def _apply_config(self):
        """应用配置到各管理器"""
        cfg = self.config if self.config else self._plugin_config
        
        # Token 管理器配置
        free_msg_cfg = cfg.get("free_messages", {})
        vote_cfg = cfg.get("vote_reward", {})
        token_manager.configure(
            free_messages=free_msg_cfg.get("daily_limit", 5),
            vote_tokens=vote_cfg.get("tokens", 3000),
            vote_expiry_hours=vote_cfg.get("expiry_hours", 12)
        )
        
        # 角色管理器配置
        char_cfg = cfg.get("character", {})
        character_manager.configure(
            default_character=char_cfg.get("default", "Nova"),
            max_custom=char_cfg.get("max_custom_characters", 5)
        )
        
        # Top.gg webhook 配置
        topgg_cfg = cfg.get("topgg", {})
        topgg_webhook.configure(
            enabled=topgg_cfg.get("enabled", False),
            webhook_path=topgg_cfg.get("webhook_path", "/topgg/webhook"),
            webhook_port=topgg_cfg.get("webhook_port", 8080),
            webhook_auth=topgg_cfg.get("webhook_auth", "")
        )
        
        # 保存 bot_id 用于生成投票链接
        self._topgg_bot_id = topgg_cfg.get("bot_id", "")
    
    async def _init_personas(self):
        """将本地角色同步到 astrbot persona_manager"""
        try:
            persona_mgr = self.context.persona_manager
            all_personas = await persona_mgr.get_all_personas()
            existing_personas = {p.persona_id for p in all_personas}
            
            # 同步系统角色
            for char_name, prompt in character_manager.system_characters.items():
                persona_id = f"chatbot_{char_name}"
                if persona_id not in existing_personas:
                    try:
                        created = persona_mgr.create_persona(
                            persona_id=persona_id,
                            system_prompt=prompt,
                            begin_dialogs=[],
                            tools=None  # 允许所有工具
                        )
                        if inspect.isawaitable(created):
                            await created
                        logger.info(f"创建人格: {persona_id}")
                    except ValueError:
                        # 已存在，更新
                        updated = persona_mgr.update_persona(
                            persona_id=persona_id,
                            system_prompt=prompt
                        )
                        if inspect.isawaitable(updated):
                            await updated
        except Exception as e:
            logger.error(f"初始化人格失败: {e}")
    
    # ==================== 核心聊天功能 ====================
    
    async def chat(self, event: AstrMessageEvent, user_message: str) -> Optional[str]:
        """
        核心聊天方法 - 使用 astrbot 原生 API
        
        Args:
            event: 消息事件
            user_message: 用户消息
            
        Returns:
            AI 回复文本，或 None（如果无法发送）
        """
        user_id = self._get_user_id(event)
        if not user_id:
            return None
        
        # 1. 检查是否可以发送消息
        estimated_tokens = token_manager.estimate_tokens(user_message) + 3000  # 预估输出
        can_send, reason, details = token_manager.can_send_message(user_id, estimated_tokens)
        
        if not can_send:
            return (
                f"❌ **Token 不足**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 当前余额: {details['balance']:,}\n"
                f"📊 预估需要: {details['estimated_cost']:,}\n"
                f"💡 今日免费消息已用完 ({details['free_messages_used']} 条)\n\n"
                f"使用 `/chatbot_vote` 领取点赞奖励获得更多 Token！"
            )
        
        try:
            # 2. 获取当前角色的 persona_id
            char_name = character_manager.get_user_character(user_id)
            persona_id = f"chatbot_{char_name}"
            
            # 3. 获取 LLM provider
            umo = event.unified_msg_origin
            provider_id = await self.context.get_current_chat_provider_id(umo=umo)
            
            # 4. 获取对话管理器
            conv_mgr = self.context.conversation_manager
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
            
            # 如果没有对话，创建一个
            if not curr_cid:
                curr_cid = await conv_mgr.new_conversation(
                    unified_msg_origin=umo,
                    persona_id=persona_id
                )
            
            # 5. 构建用户消息
            user_msg = UserMessageSegment(content=[TextPart(text=user_message)])
            
            # 6. 调用 LLM
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=user_message,
            )
            
            response_text = llm_resp.completion_text
            
            # 7. 保存对话记录
            await conv_mgr.add_message_pair(
                cid=curr_cid,
                user_message=user_msg,
                assistant_message=AssistantMessageSegment(
                    content=[TextPart(text=response_text)]
                ),
            )
            
            # 8. 消费 Token
            actual_tokens = token_manager.estimate_tokens(user_message + response_text)
            
            # 增加消息计数
            token_manager.increment_message_count(user_id)
            
            # 如果超出免费额度，消费 token
            if not token_manager.is_within_free_messages(user_id):
                token_manager.spend_ai_tokens(user_id, actual_tokens)
            
            return response_text
            
        except Exception as e:
            logger.error(f"聊天失败: {e}")
            return f"❌ 聊天出错: {str(e)}"
    
    # ==================== 命令处理 ====================
    
    @filter.command("chatbot_status")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看 chatbot 状态"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        # 获取 token 状态
        free_remaining = token_manager.get_free_messages_remaining(user_id)
        token_balance = token_manager.get_ai_token_balance(user_id)
        daily_limit = token_manager.free_messages_daily
        
        # 获取当前角色
        character = character_manager.get_user_character(user_id)
        
        msg = (
            f"📊 **Chatbot 状态**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎭 当前角色: `{character}`\n"
            f"💬 今日免费消息: {free_remaining}/{daily_limit}\n"
            f"🎟️ AI Token 余额: {token_balance:,}\n"
        )
        
        return event.plain_result(msg)
    
    @filter.command("chatbot_characters")
    async def cmd_characters(self, event: AstrMessageEvent):
        """查看可用角色列表"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        characters = character_manager.get_all_characters(user_id)
        current = character_manager.get_user_character(user_id)
        
        char_list = "\n".join([
            f"{'✅' if c == current else '○'} {c}" 
            for c in characters
        ])
        
        msg = (
            f"🎭 **可用角色列表**\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{char_list}\n\n"
            f"使用 `/chatbot_switch <角色名>` 切换角色"
        )
        
        return event.plain_result(msg)
    
    @filter.command("chatbot_switch")
    async def cmd_switch(self, event: AstrMessageEvent, character: str = None):
        """切换角色"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        if not character:
            return event.plain_result("❌ 请指定角色名，如: `/chatbot_switch Nova`")
        
        success = character_manager.set_user_character(user_id, character)
        if success:
            # 同时更新 astrbot 的对话 persona
            try:
                umo = event.unified_msg_origin
                conv_mgr = self.context.conversation_manager
                persona_id = f"chatbot_{character}"
                await conv_mgr.update_conversation(
                    unified_msg_origin=umo,
                    conversation_id=None,  # 当前对话
                    persona_id=persona_id
                )
            except Exception as e:
                logger.warning(f"更新对话 persona 失败: {e}")
            
            return event.plain_result(f"✅ 已切换到角色: `{character}`")
        else:
            return event.plain_result(f"❌ 角色 `{character}` 不存在")
    
    @filter.command("chatbot_clear")
    async def cmd_clear(self, event: AstrMessageEvent):
        """清空对话历史"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        # 使用 astrbot 的对话管理器删除当前对话
        try:
            umo = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            await conv_mgr.delete_conversation(unified_msg_origin=umo, conversation_id=None)
        except Exception as e:
            logger.warning(f"删除对话失败: {e}")
        
        return event.plain_result("✅ 对话历史已清空")
    
    @filter.command("chatbot_vote")
    async def cmd_vote(self, event: AstrMessageEvent):
        """查看投票状态和投票链接"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        # 获取投票信息
        vote_info = topgg_webhook.get_vote_info(user_id)
        is_voter = topgg_webhook.is_voter(user_id)
        
        # 获取 token 状态
        token_balance = token_manager.get_ai_token_balance(user_id)
        
        if is_voter:
            # 已投票
            from datetime import datetime, timedelta
            last_vote_time = vote_info.get("last_vote_time", "")
            streak = vote_info.get("voter_streak", 0)
            
            try:
                last_vote = datetime.fromisoformat(last_vote_time)
                next_vote = last_vote + timedelta(hours=12)
                next_vote_ts = int(next_vote.timestamp())
                time_info = f"<t:{next_vote_ts}:R>"
            except Exception:
                time_info = "未知"
            
            msg = (
                f"✅ **投票状态: 已投票**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🔥 连续投票: {streak} 次\n"
                f"⏰ 下次可投票: {time_info}\n"
                f"🎟️ Token 余额: {token_balance:,}\n\n"
                f"感谢你的支持！"
            )
        else:
            # 未投票
            vote_url = topgg_webhook.get_vote_url(self._topgg_bot_id) if hasattr(self, '_topgg_bot_id') else ""
            
            msg = (
                f"❌ **投票状态: 未投票**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"🎟️ Token 余额: {token_balance:,}\n\n"
                f"**投票奖励:**\n"
                f"• 🎟️ {token_manager.vote_reward_tokens:,} AI Tokens\n"
                f"• ⏰ 有效期 {token_manager.vote_reward_expiry_hours} 小时\n"
                f"• 🎉 周末双倍奖励！\n\n"
            )
            if vote_url:
                msg += f"👉 [点击这里投票]({vote_url})"
            else:
                msg += "请在 Top.gg 为我们投票！"
        
        return event.plain_result(msg)
    
    @filter.command("chatbot_claim_vote")
    async def cmd_claim_vote(self, event: AstrMessageEvent):
        """手动领取投票奖励"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        # 检查是否是有效投票者
        if not topgg_webhook.is_voter(user_id):
            vote_url = topgg_webhook.get_vote_url(self._topgg_bot_id) if hasattr(self, '_topgg_bot_id') else ""
            msg = "❌ 你还没有投票，无法领取奖励\n\n"
            if vote_url:
                msg += f"👉 [点击这里投票]({vote_url})"
            return event.plain_result(msg)
        
        # 检查是否已领取
        vote_info = topgg_webhook.get_vote_info(user_id)
        last_vote_time = vote_info.get("last_vote_time")
        last_reward_time = vote_info.get("last_reward_time")
        
        if last_reward_time and last_vote_time:
            try:
                from datetime import datetime
                last_vote = datetime.fromisoformat(last_vote_time)
                last_reward = datetime.fromisoformat(last_reward_time)
                if last_reward >= last_vote:
                    return event.plain_result("⚠️ 你已经领取过本次投票奖励了，请下次投票后再来！")
            except Exception:
                pass
        
        # 发放奖励
        is_weekend = vote_info.get("is_weekend", False)
        multiplier = 2 if is_weekend else 1
        reward_tokens = token_manager.vote_reward_tokens * multiplier
        
        new_balance = token_manager.add_ai_tokens(
            user_id,
            reward_tokens,
            expires_in_hours=token_manager.vote_reward_expiry_hours
        )
        
        # 更新奖励时间
        from datetime import datetime
        topgg_webhook.voted_users[str(user_id)]["last_reward_time"] = datetime.now().isoformat()
        topgg_webhook._save_voted_users()
        
        weekend_bonus = " (周末双倍！)" if is_weekend else ""
        return event.plain_result(
            f"🎉 **投票奖励已领取！**{weekend_bonus}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"🎟️ 获得: {reward_tokens:,} AI Tokens\n"
            f"⏰ 有效期: {token_manager.vote_reward_expiry_hours} 小时\n"
            f"💰 当前余额: {new_balance:,} Tokens"
        )
    
    # ==================== 自定义角色 ====================
    
    @filter.command("chatbot_create_char")
    async def cmd_create_char(self, event: AstrMessageEvent, name: str = None, *, prompt: str = None):
        """创建自定义角色"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        if not name or not prompt:
            return event.plain_result(
                "❌ 用法: `/chatbot_create_char <名称> <prompt>`\n"
                "例如: `/chatbot_create_char 小助手 你是一个友好的助手...`"
            )
        
        success, message = character_manager.create_custom_character(user_id, name, prompt)
        if success:
            return event.plain_result(f"✅ {message}")
        else:
            return event.plain_result(f"❌ {message}")
    
    @filter.command("chatbot_delete_char")
    async def cmd_delete_char(self, event: AstrMessageEvent, name: str = None):
        """删除自定义角色"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        if not name:
            return event.plain_result("❌ 请指定要删除的角色名")
        
        success, message = character_manager.delete_custom_character(user_id, name)
        if success:
            return event.plain_result(f"✅ {message}")
        else:
            return event.plain_result(f"❌ {message}")
    
    @filter.command("chatbot_my_chars")
    async def cmd_my_chars(self, event: AstrMessageEvent):
        """查看我的自定义角色"""
        user_id = self._get_user_id(event)
        if not user_id:
            return
        
        customs = character_manager.get_user_custom_characters(user_id)
        
        if not customs:
            return event.plain_result(
                "📝 你还没有自定义角色\n"
                f"使用 `/chatbot_create_char <名称> <prompt>` 创建\n"
                f"最多可创建 {character_manager.max_custom_characters} 个"
            )
        
        char_list = "\n".join([f"• {name}" for name in customs.keys()])
        
        return event.plain_result(
            f"📝 **我的自定义角色** ({len(customs)}/{character_manager.max_custom_characters})\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{char_list}"
        )
    
    # ==================== 工具方法 ====================
    
    def _get_user_id(self, event: AstrMessageEvent) -> Optional[int]:
        """从事件中获取用户 ID"""
        try:
            # 尝试从 event 中获取用户 ID
            if hasattr(event, 'message_obj') and hasattr(event.message_obj, 'author'):
                return event.message_obj.author.id
            if hasattr(event, 'context') and hasattr(event.context, 'user_id'):
                return int(event.context.user_id)
            if hasattr(event, 'get_sender_id'):
                return int(event.get_sender_id())
        except Exception as e:
            logger.error(f"获取用户 ID 失败: {e}")
        return None
