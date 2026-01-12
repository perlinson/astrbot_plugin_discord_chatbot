# -*- coding: utf-8 -*-
"""
Top.gg Webhook 处理器
接收 Top.gg 投票事件并发放 token 奖励
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from aiohttp import web

from ..managers.token_manager import token_manager

logger = logging.getLogger(__name__)


class TopggWebhookHandler:
    """Top.gg Webhook 处理器"""
    
    def __init__(self):
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
        # 配置
        self.enabled = False
        self.webhook_path = "/topgg/webhook"
        self.webhook_port = 8080
        self.webhook_auth = ""
        
        # 投票记录文件
        self.data_dir = Path(__file__).resolve().parents[2] / "data"
        self.voted_users_file = self.data_dir / "voted_users.json"
        
        # 加载投票记录
        self.voted_users = self._load_voted_users()
    
    def configure(self, enabled: bool = None, webhook_path: str = None, 
                  webhook_port: int = None, webhook_auth: str = None):
        """配置 webhook"""
        if enabled is not None:
            self.enabled = enabled
        if webhook_path is not None:
            self.webhook_path = webhook_path
        if webhook_port is not None:
            self.webhook_port = webhook_port
        if webhook_auth is not None:
            self.webhook_auth = webhook_auth
    
    # ==================== 数据持久化 ====================
    
    def _load_voted_users(self) -> dict:
        """加载投票用户记录"""
        try:
            if self.voted_users_file.exists():
                with open(self.voted_users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"加载投票记录失败: {e}")
        return {}
    
    def _save_voted_users(self):
        """保存投票用户记录"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.voted_users_file, 'w', encoding='utf-8') as f:
                json.dump(self.voted_users, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存投票记录失败: {e}")
    
    # ==================== Webhook 处理 ====================
    
    async def handle_webhook(self, request: web.Request) -> web.Response:
        """处理 Top.gg webhook 请求"""
        # 验证认证
        if self.webhook_auth:
            auth_header = request.headers.get("Authorization", "")
            if auth_header != self.webhook_auth:
                logger.warning(f"Webhook 认证失败: {auth_header[:20]}...")
                return web.Response(status=401, text="Unauthorized")
        
        try:
            # 解析请求体
            data = await request.json()
            
            # Top.gg webhook 数据格式:
            # {
            #   "bot": "bot_id",
            #   "user": "user_id",
            #   "type": "upvote" | "test",
            #   "isWeekend": true | false,
            #   "query": "?..."  (可选)
            # }
            
            user_id = data.get("user")
            vote_type = data.get("type", "upvote")
            is_weekend = data.get("isWeekend", False)
            
            if not user_id:
                logger.warning("Webhook 缺少 user_id")
                return web.Response(status=400, text="Missing user_id")
            
            logger.info(f"收到 Top.gg 投票: user={user_id}, type={vote_type}, weekend={is_weekend}")
            
            # 处理投票
            if vote_type in ("upvote", "test"):
                await self.process_vote(user_id, is_weekend)
            
            return web.Response(status=200, text="OK")
            
        except json.JSONDecodeError:
            logger.error("Webhook JSON 解析失败")
            return web.Response(status=400, text="Invalid JSON")
        except Exception as e:
            logger.error(f"Webhook 处理失败: {e}")
            return web.Response(status=500, text="Internal Server Error")
    
    async def process_vote(self, user_id: str, is_weekend: bool = False):
        """
        处理投票并发放奖励
        
        Args:
            user_id: 用户 ID
            is_weekend: 是否周末（周末可能有双倍奖励）
        """
        user_id_str = str(user_id)
        current_time = datetime.now()
        
        # 获取用户现有记录
        existing = self.voted_users.get(user_id_str, {})
        if not isinstance(existing, dict):
            existing = {}
        
        # 检查是否是新的投票窗口（12小时）
        prev_vote_time = None
        prev_vote_time_raw = existing.get("last_vote_time")
        if prev_vote_time_raw:
            try:
                prev_vote_time = datetime.fromisoformat(prev_vote_time_raw)
            except Exception:
                prev_vote_time = None
        
        is_new_vote_window = False
        if prev_vote_time is None:
            is_new_vote_window = True
        else:
            from datetime import timedelta
            if (current_time - prev_vote_time) > timedelta(hours=12):
                is_new_vote_window = True
        
        # 更新连续投票次数
        streak = existing.get("voter_streak", 0)
        try:
            streak = int(streak)
        except Exception:
            streak = 0
        
        if is_new_vote_window:
            streak += 1
        
        # 更新投票记录
        vote_info = {
            "user_id": user_id_str,
            "is_voter": True,
            "voter_streak": streak,
            "is_weekend": is_weekend,
        }
        
        # 只在新投票窗口时更新时间
        if is_new_vote_window or not existing.get("last_vote_time"):
            vote_info["last_vote_time"] = current_time.isoformat()
        else:
            vote_info["last_vote_time"] = existing.get("last_vote_time")
        
        # 保留上次奖励时间
        if "last_reward_time" in existing:
            vote_info["last_reward_time"] = existing["last_reward_time"]
        
        self.voted_users[user_id_str] = vote_info
        self._save_voted_users()
        
        # 发放 token 奖励（只在新投票窗口时发放）
        if is_new_vote_window:
            # 检查是否已经发放过奖励
            last_reward_time = existing.get("last_reward_time")
            should_reward = True
            
            if last_reward_time and prev_vote_time_raw:
                try:
                    last_reward = datetime.fromisoformat(last_reward_time)
                    last_vote = datetime.fromisoformat(prev_vote_time_raw)
                    # 如果上次奖励时间在上次投票之后，说明已经领过了
                    if last_reward >= last_vote:
                        should_reward = False
                except Exception:
                    pass
            
            if should_reward:
                # 发放奖励
                multiplier = 2 if is_weekend else 1
                reward_tokens = token_manager.vote_reward_tokens * multiplier
                
                new_balance = token_manager.add_ai_tokens(
                    int(user_id),
                    reward_tokens,
                    expires_in_hours=token_manager.vote_reward_expiry_hours
                )
                
                # 更新奖励时间
                self.voted_users[user_id_str]["last_reward_time"] = current_time.isoformat()
                self._save_voted_users()
                
                logger.info(
                    f"发放投票奖励: user={user_id}, tokens={reward_tokens}, "
                    f"weekend={is_weekend}, streak={streak}, balance={new_balance}"
                )
            else:
                logger.info(f"用户 {user_id} 已领取过本次投票奖励")
        else:
            logger.info(f"用户 {user_id} 在同一投票窗口内重复投票，不重复发放奖励")
    
    # ==================== 服务器管理 ====================
    
    async def start(self):
        """启动 webhook 服务器"""
        if not self.enabled:
            logger.info("Top.gg webhook 未启用")
            return
        
        try:
            self.app = web.Application()
            self.app.router.add_post(self.webhook_path, self.handle_webhook)
            
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(self.runner, "0.0.0.0", self.webhook_port)
            await self.site.start()
            
            logger.info(f"Top.gg webhook 服务器已启动: http://0.0.0.0:{self.webhook_port}{self.webhook_path}")
        except Exception as e:
            logger.error(f"启动 webhook 服务器失败: {e}")
    
    async def stop(self):
        """停止 webhook 服务器"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Top.gg webhook 服务器已停止")
    
    # ==================== 投票状态查询 ====================
    
    def get_vote_info(self, user_id: int) -> dict:
        """获取用户投票信息"""
        user_id_str = str(user_id)
        return self.voted_users.get(user_id_str, {}).copy()
    
    def is_voter(self, user_id: int) -> bool:
        """检查用户是否是有效投票者（12小时内）"""
        vote_info = self.get_vote_info(user_id)
        if not vote_info.get("is_voter"):
            return False
        
        last_vote_time = vote_info.get("last_vote_time")
        if not last_vote_time:
            return False
        
        try:
            from datetime import timedelta
            last_vote = datetime.fromisoformat(last_vote_time)
            if datetime.now() < last_vote + timedelta(hours=12):
                return True
        except Exception:
            pass
        
        return False
    
    def get_vote_url(self, bot_id: str = "") -> str:
        """获取投票链接"""
        return f"https://top.gg/bot/{bot_id}/vote" if bot_id else ""


# 全局单例
topgg_webhook = TopggWebhookHandler()
