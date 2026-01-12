# -*- coding: utf-8 -*-
"""
角色管理器
- 加载系统角色
- 用户角色切换
- 自定义角色管理
"""
import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


class CharacterManager:
    """角色管理器"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls, base_dir: Path = None):
        if cls._instance is None:
            cls._instance = super(CharacterManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, base_dir: Path = None):
        if self._initialized:
            return
        
        # 默认目录
        if base_dir is None:
            base_dir = Path(__file__).resolve().parents[2]
        
        self.base_dir = base_dir
        self.characters_dir = base_dir / "characters"
        self.data_dir = base_dir / "data"
        
        # 确保目录存在
        self.characters_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 数据文件
        self.user_characters_file = self.data_dir / "user_characters.json"
        self.custom_characters_file = self.data_dir / "custom_characters.json"
        
        # 配置
        self.default_character = "Nova"
        self.max_custom_characters = 5
        
        # 加载数据
        self.user_characters = self._load_json(self.user_characters_file, {"user_characters": {}})
        self.custom_characters = self._load_json(self.custom_characters_file, {})
        
        # 加载系统角色
        self.system_characters = self._load_system_characters()
        
        self._initialized = True
    
    def configure(self, default_character: str = None, max_custom: int = None):
        """配置管理器参数"""
        if default_character is not None:
            self.default_character = default_character
        if max_custom is not None:
            self.max_custom_characters = max_custom
    
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
        return default.copy()
    
    def _save_json(self, file_path: Path, data: dict):
        """保存 JSON 文件"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"保存文件失败 {file_path}: {e}")
    
    # ==================== 系统角色 ====================
    
    def _load_system_characters(self) -> Dict[str, str]:
        """加载系统角色"""
        characters = {}
        
        if not self.characters_dir.exists():
            return characters
        
        for file_path in self.characters_dir.glob("*.txt"):
            try:
                # 从文件名提取角色名（去掉 .txt 后缀）
                char_name = file_path.stem
                with open(file_path, 'r', encoding='utf-8') as f:
                    prompt = f.read().strip()
                characters[char_name] = prompt
                logger.debug(f"加载角色: {char_name}")
            except Exception as e:
                logger.error(f"加载角色文件失败 {file_path}: {e}")
        
        logger.info(f"共加载 {len(characters)} 个系统角色")
        return characters
    
    def get_system_characters(self) -> List[str]:
        """获取所有系统角色名称列表"""
        return list(self.system_characters.keys())
    
    def reload_system_characters(self):
        """重新加载系统角色"""
        self.system_characters = self._load_system_characters()
    
    # ==================== 用户角色 ====================
    
    def get_user_character(self, user_id: int) -> str:
        """获取用户当前使用的角色名"""
        user_id_str = str(user_id)
        char = self.user_characters.get("user_characters", {}).get(user_id_str)
        return char if char else self.default_character
    
    def set_user_character(self, user_id: int, character_name: str) -> bool:
        """
        设置用户角色
        
        Args:
            user_id: 用户 ID
            character_name: 角色名称
            
        Returns:
            是否设置成功
        """
        # 检查角色是否存在
        if not self.character_exists(character_name, user_id):
            return False
        
        user_id_str = str(user_id)
        if "user_characters" not in self.user_characters:
            self.user_characters["user_characters"] = {}
        
        self.user_characters["user_characters"][user_id_str] = character_name
        self._save_json(self.user_characters_file, self.user_characters)
        
        logger.info(f"用户 {user_id} 切换角色为: {character_name}")
        return True
    
    # ==================== 角色 Prompt ====================
    
    def get_character_prompt(self, character_name: str, user_id: int = None) -> Optional[str]:
        """
        获取角色的 prompt
        
        Args:
            character_name: 角色名称
            user_id: 用户 ID（用于查找自定义角色）
            
        Returns:
            角色 prompt，不存在返回 None
        """
        # 先检查用户自定义角色
        if user_id is not None:
            user_id_str = str(user_id)
            user_customs = self.custom_characters.get(user_id_str, {})
            if character_name in user_customs:
                return user_customs[character_name]
        
        # 再检查系统角色
        if character_name in self.system_characters:
            return self.system_characters[character_name]
        
        return None
    
    def get_user_character_prompt(self, user_id: int) -> Optional[str]:
        """获取用户当前角色的 prompt"""
        char_name = self.get_user_character(user_id)
        return self.get_character_prompt(char_name, user_id)
    
    def character_exists(self, character_name: str, user_id: int = None) -> bool:
        """检查角色是否存在"""
        # 检查系统角色
        if character_name in self.system_characters:
            return True
        
        # 检查用户自定义角色
        if user_id is not None:
            user_id_str = str(user_id)
            user_customs = self.custom_characters.get(user_id_str, {})
            if character_name in user_customs:
                return True
        
        return False
    
    # ==================== 自定义角色 ====================
    
    def get_user_custom_characters(self, user_id: int) -> Dict[str, str]:
        """获取用户的所有自定义角色"""
        user_id_str = str(user_id)
        return self.custom_characters.get(user_id_str, {}).copy()
    
    def create_custom_character(self, user_id: int, name: str, prompt: str) -> tuple:
        """
        创建自定义角色
        
        Args:
            user_id: 用户 ID
            name: 角色名称
            prompt: 角色 prompt
            
        Returns:
            (success: bool, message: str)
        """
        user_id_str = str(user_id)
        
        # 检查名称是否与系统角色冲突
        if name in self.system_characters:
            return False, f"角色名 '{name}' 与系统角色冲突"
        
        # 获取用户自定义角色
        if user_id_str not in self.custom_characters:
            self.custom_characters[user_id_str] = {}
        
        user_customs = self.custom_characters[user_id_str]
        
        # 检查数量限制（更新不算新增）
        if name not in user_customs and len(user_customs) >= self.max_custom_characters:
            return False, f"已达到自定义角色上限 ({self.max_custom_characters})"
        
        # 保存角色
        user_customs[name] = prompt
        self.custom_characters[user_id_str] = user_customs
        self._save_json(self.custom_characters_file, self.custom_characters)
        
        logger.info(f"用户 {user_id} 创建/更新自定义角色: {name}")
        return True, f"角色 '{name}' 已保存"
    
    def delete_custom_character(self, user_id: int, name: str) -> tuple:
        """
        删除自定义角色
        
        Args:
            user_id: 用户 ID
            name: 角色名称
            
        Returns:
            (success: bool, message: str)
        """
        user_id_str = str(user_id)
        
        if user_id_str not in self.custom_characters:
            return False, f"角色 '{name}' 不存在"
        
        user_customs = self.custom_characters[user_id_str]
        
        if name not in user_customs:
            return False, f"角色 '{name}' 不存在"
        
        # 删除角色
        del user_customs[name]
        self.custom_characters[user_id_str] = user_customs
        self._save_json(self.custom_characters_file, self.custom_characters)
        
        # 如果用户当前使用的是这个角色，切换回默认
        if self.get_user_character(user_id) == name:
            self.set_user_character(user_id, self.default_character)
        
        logger.info(f"用户 {user_id} 删除自定义角色: {name}")
        return True, f"角色 '{name}' 已删除"
    
    # ==================== 角色列表 ====================
    
    def get_all_characters(self, user_id: int = None) -> List[str]:
        """
        获取所有可用角色（系统 + 用户自定义）
        
        Args:
            user_id: 用户 ID（用于包含自定义角色）
            
        Returns:
            角色名称列表
        """
        characters = list(self.system_characters.keys())
        
        if user_id is not None:
            user_customs = self.get_user_custom_characters(user_id)
            characters.extend(user_customs.keys())
        
        return sorted(set(characters))


# 全局单例
character_manager = CharacterManager()
