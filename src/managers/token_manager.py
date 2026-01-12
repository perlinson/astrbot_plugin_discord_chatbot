# -*- coding: utf-8 -*-
"""
AI Token 计量管理器
- 每天 N 条免费消息（可配置）
- 点赞获得 12 小时有效的 3000 token
"""
import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class TokenManager:
    """AI Token 计量管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, data_dir: Path = None):
        if cls._instance is None:
            cls._instance = super(TokenManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, data_dir: Path = None):
        if self._initialized:
            return
            
        # 默认数据目录
        if data_dir is None:
            data_dir = Path(__file__).resolve().parents[2] / "data"
        
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 配置（可从外部配置文件加载）
        self.free_messages_daily = 5          # 每天免费消息数
        self.vote_reward_tokens = 3000        # 点赞奖励 token
        self.vote_reward_expiry_hours = 12    # 点赞奖励有效期（小时）
        
        # 数据文件路径
        self.user_limits_file = self.data_dir / "user_message_limits.json"
        self.ai_tokens_file = self.data_dir / "ai_tokens.json"
        
        # 线程锁
        self._file_lock = threading.RLock()
        
        # 加载数据
        self.user_limits = self._load_json(self.user_limits_file, {})
        self.ai_tokens = self._load_json(self.ai_tokens_file, {})
        
        self._initialized = True
    
    def configure(self, free_messages: int = None, vote_tokens: int = None, vote_expiry_hours: int = None):
        """配置管理器参数"""
        if free_messages is not None:
            self.free_messages_daily = free_messages
        if vote_tokens is not None:
            self.vote_reward_tokens = vote_tokens
        if vote_expiry_hours is not None:
            self.vote_reward_expiry_hours = vote_expiry_hours
    
    # ==================== 文件操作 ====================
    
    def _load_json(self, file_path: Path, default: dict) -> dict:
        """加载 JSON 文件"""
        try:
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else default
        except Exception as e:
            logger.error(f"加载文件失败 {file_path}: {e}")
        return default
    
    def _save_json(self, file_path: Path, data: dict):
        """保存 JSON 文件（原子写入）"""
        try:
            with self._file_lock:
                tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, file_path)
        except Exception as e:
            logger.error(f"保存文件失败 {file_path}: {e}")
    
    # ==================== 日期工具 ====================
    
    def _get_today_key(self) -> str:
        """获取今天的日期键"""
        return datetime.now().date().isoformat()
    
    # ==================== 免费消息管理 ====================
    
    def _get_user_data(self, user_id: int) -> dict:
        """获取用户数据，如果不存在则创建"""
        user_id_str = str(user_id)
        today = self._get_today_key()
        
        if user_id_str not in self.user_limits:
            self.user_limits[user_id_str] = {
                "message_count": 0,
                "last_reset_date": today
            }
            self._save_json(self.user_limits_file, self.user_limits)
        
        user_data = self.user_limits[user_id_str]
        
        # 检查是否需要每日重置
        if user_data.get("last_reset_date") != today:
            user_data["message_count"] = 0
            user_data["last_reset_date"] = today
            self.user_limits[user_id_str] = user_data
            self._save_json(self.user_limits_file, self.user_limits)
        
        return user_data
    
    def get_free_messages_remaining(self, user_id: int) -> int:
        """获取用户剩余免费消息数"""
        user_data = self._get_user_data(user_id)
        count = user_data.get("message_count", 0)
        remaining = self.free_messages_daily - count
        return max(0, remaining)
    
    def is_within_free_messages(self, user_id: int) -> bool:
        """检查用户是否还在免费消息额度内"""
        return self.get_free_messages_remaining(user_id) > 0
    
    def get_message_count(self, user_id: int) -> int:
        """获取用户今日消息计数"""
        user_data = self._get_user_data(user_id)
        return user_data.get("message_count", 0)
    
    def increment_message_count(self, user_id: int) -> int:
        """增加用户消息计数，返回新计数"""
        user_data = self._get_user_data(user_id)
        count = user_data.get("message_count", 0) + 1
        user_data["message_count"] = count
        self.user_limits[str(user_id)] = user_data
        self._save_json(self.user_limits_file, self.user_limits)
        return count
    
    # ==================== AI Token 管理 ====================
    
    def _clean_expired_tokens(self, user_id: str) -> int:
        """清理过期的 token，返回当前有效余额"""
        with self._file_lock:
            entries = self.ai_tokens.get(user_id, [])
            if not isinstance(entries, list):
                entries = []
            
            now_ts = int(time.time())
            valid_entries = []
            total = 0
            
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                tokens = entry.get("tokens", 0)
                expires_at = entry.get("expires_at")
                
                # 跳过过期的
                if expires_at is not None and expires_at <= now_ts:
                    continue
                # 跳过无效的
                if tokens <= 0:
                    continue
                
                valid_entries.append({"tokens": tokens, "expires_at": expires_at})
                total += tokens
            
            self.ai_tokens[user_id] = valid_entries
            self._save_json(self.ai_tokens_file, self.ai_tokens)
            return total
    
    def get_ai_token_balance(self, user_id: int) -> int:
        """获取用户 AI token 余额"""
        return self._clean_expired_tokens(str(user_id))
    
    def add_ai_tokens(self, user_id: int, tokens: int, expires_in_hours: int = None) -> int:
        """
        添加 AI tokens
        
        Args:
            user_id: 用户 ID
            tokens: token 数量
            expires_in_hours: 过期时间（小时），None 表示永不过期
            
        Returns:
            新的 token 余额
        """
        with self._file_lock:
            uid = str(user_id)
            if tokens <= 0:
                return self._clean_expired_tokens(uid)
            
            # 计算过期时间
            expires_at = None
            if expires_in_hours is not None:
                expires_at = int(time.time()) + int(expires_in_hours) * 3600
            
            # 获取现有条目
            entries = self.ai_tokens.get(uid, [])
            if not isinstance(entries, list):
                entries = []
            
            # 清理过期条目
            now_ts = int(time.time())
            valid_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                t = entry.get("tokens", 0)
                exp = entry.get("expires_at")
                if exp is not None and exp <= now_ts:
                    continue
                if t <= 0:
                    continue
                valid_entries.append({"tokens": t, "expires_at": exp})
            
            # 添加新条目
            valid_entries.append({"tokens": tokens, "expires_at": expires_at})
            
            self.ai_tokens[uid] = valid_entries
            self._save_json(self.ai_tokens_file, self.ai_tokens)
            
            logger.info(f"用户 {uid} 获得 {tokens} AI tokens，有效期 {expires_in_hours} 小时")
            return self._clean_expired_tokens(uid)
    
    def spend_ai_tokens(self, user_id: int, tokens: int) -> int:
        """
        消费 AI tokens（优先消费即将过期的）
        
        Args:
            user_id: 用户 ID
            tokens: 消费数量
            
        Returns:
            剩余 token 余额
        """
        with self._file_lock:
            uid = str(user_id)
            if tokens <= 0:
                return self._clean_expired_tokens(uid)
            
            entries = self.ai_tokens.get(uid, [])
            if not isinstance(entries, list):
                entries = []
            
            # 清理并排序（优先消费即将过期的）
            now_ts = int(time.time())
            valid_entries = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                t = entry.get("tokens", 0)
                exp = entry.get("expires_at")
                if exp is not None and exp <= now_ts:
                    continue
                if t <= 0:
                    continue
                valid_entries.append({"tokens": t, "expires_at": exp})
            
            # 按过期时间排序（None 排最后，即永不过期的最后消费）
            valid_entries.sort(key=lambda x: (x["expires_at"] is None, x["expires_at"] or 0))
            
            # 消费 tokens
            remaining_to_spend = tokens
            new_entries = []
            for entry in valid_entries:
                if remaining_to_spend <= 0:
                    new_entries.append(entry)
                    continue
                t = entry["tokens"]
                if t <= remaining_to_spend:
                    remaining_to_spend -= t
                    continue
                entry["tokens"] = t - remaining_to_spend
                remaining_to_spend = 0
                new_entries.append(entry)
            
            self.ai_tokens[uid] = new_entries
            self._save_json(self.ai_tokens_file, self.ai_tokens)
            
            return self._clean_expired_tokens(uid)
    
    # ==================== 点赞奖励 ====================
    
    def grant_vote_reward(self, user_id: int) -> int:
        """
        发放点赞奖励
        
        Returns:
            新的 token 余额
        """
        return self.add_ai_tokens(
            user_id, 
            self.vote_reward_tokens, 
            expires_in_hours=self.vote_reward_expiry_hours
        )
    
    def has_recent_vote_reward(self, user_id: int, window_seconds: int = 120) -> bool:
        """
        检查用户是否在最近时间窗口内已获得点赞奖励（防重复发放）
        
        Args:
            user_id: 用户 ID
            window_seconds: 检查窗口（秒）
            
        Returns:
            是否已有最近的奖励
        """
        uid = str(user_id)
        entries = self.ai_tokens.get(uid, [])
        if not isinstance(entries, list):
            return False
        
        now_ts = int(time.time())
        expected_expiry = now_ts + self.vote_reward_expiry_hours * 3600
        
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tokens = entry.get("tokens", 0)
            exp = entry.get("expires_at")
            
            # 检查是否是点赞奖励（相同 token 数量，且过期时间接近）
            if tokens == self.vote_reward_tokens and exp is not None:
                if abs(exp - expected_expiry) <= window_seconds:
                    return True
        
        return False
    
    # ==================== 检查是否可以发送消息 ====================
    
    def can_send_message(self, user_id: int, estimated_tokens: int = 0) -> tuple:
        """
        检查用户是否可以发送消息
        
        Args:
            user_id: 用户 ID
            estimated_tokens: 预估需要的 token 数
            
        Returns:
            (can_send: bool, reason: str, details: dict)
        """
        # 检查免费消息
        if self.is_within_free_messages(user_id):
            return True, "free", {
                "remaining_free": self.get_free_messages_remaining(user_id)
            }
        
        # 检查 AI token 余额
        balance = self.get_ai_token_balance(user_id)
        if balance >= estimated_tokens:
            return True, "tokens", {
                "balance": balance,
                "estimated_cost": estimated_tokens
            }
        
        # 无法发送
        return False, "insufficient", {
            "balance": balance,
            "estimated_cost": estimated_tokens,
            "free_messages_used": self.free_messages_daily
        }
    
    def estimate_tokens(self, text: str, chars_per_token: int = 4) -> int:
        """估算文本的 token 数"""
        if not text:
            return 0
        return max(1, len(text) // chars_per_token)


# 全局单例
token_manager = TokenManager()
