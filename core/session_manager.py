"""
core/session_manager.py
──────────────────────
管理多轮对话历史。
保留最近 N 轮对话以供 Dify 上下文参考。

Sprint 2 🔵
"""

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Turn:
    """单轮对话"""
    role: str                           # "user" 或 "assistant"
    content: str                        # 对话内容
    code: str = ""                      # 生成的代码（如果是 assistant）
    timestamp: str = ""                 # ISO 格式时间戳

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class SessionManager:
    """会话/对话历史管理器"""

    def __init__(self, max_turns: int = 10) -> None:
        """
        初始化会话管理器。
        
        Args:
            max_turns: 保留的最大对话轮数（用户 + 助手 = 2 轮）
        """
        self.history: list[Turn] = []
        self.max_turns = max_turns
        self.current_file: Optional[str] = None  # 当前分析的文件

    def add_user_turn(self, query: str) -> None:
        """
        添加用户对话。
        
        Args:
            query: 用户输入
        """
        self.history.append(Turn(role="user", content=query))
        self._trim_history()

    def add_assistant_turn(self, response: str, code: str = "") -> None:
        """
        添加助手回应。
        
        Args:
            response: 助手的回应（通常是执行结果）
            code: 生成的 Python 代码
        """
        self.history.append(
            Turn(role="assistant", content=response, code=code)
        )
        self._trim_history()

    def get_history(self) -> list[dict]:
        """
        获取对话历史（用于发送给 Dify）。
        
        Returns:
            对话列表，格式：[{"role": "user"/"assistant", "content": "..."}]
        """
        return [
            {"role": turn.role, "content": turn.content}
            for turn in self.history
        ]

    def get_last_code(self) -> Optional[str]:
        """
        获取最后一次生成的代码。
        
        Returns:
            代码字符串，或 None 如果没有
        """
        for turn in reversed(self.history):
            if turn.role == "assistant" and turn.code:
                return turn.code
        return None

    def get_turn_count(self) -> int:
        """获取总对话轮数"""
        return len(self.history)

    def clear(self) -> None:
        """清空所有历史"""
        self.history.clear()
        self.current_file = None

    def set_current_file(self, file_name: str) -> None:
        """
        设置当前分析的文件。
        切换文件时应清空历史。
        
        Args:
            file_name: Excel 文件名
        """
        if self.current_file != file_name:
            self.clear()
            self.current_file = file_name

    def get_summary(self) -> str:
        """
        获取对话摘要（用于 UI 显示）。
        
        Returns:
            人类可读的摘要文本
        """
        if not self.history:
            return "无历史记录"

        user_turns = sum(1 for t in self.history if t.role == "user")
        return f"当前文件: {self.current_file or '无'} | {user_turns} 个问题"

    def _trim_history(self) -> None:
        """
        保持历史长度在限制内。
        当超出 max_turns 时，删除最早的对话。
        """
        max_items = self.max_turns * 2  # 每轮 2 个对话（user + assistant）
        if len(self.history) > max_items:
            self.history = self.history[-max_items:]

    def export_to_markdown(self) -> str:
        """
        将对话导出为 Markdown 格式。
        
        Sprint 3：用于生成报告
        
        Returns:
            Markdown 文本
        """
        lines = []
        
        for turn in self.history:
            if turn.role == "user":
                lines.append(f"## 用户\n\n{turn.content}\n")
            else:
                lines.append(f"## 助手\n\n{turn.content}\n")
                if turn.code:
                    lines.append(f"```python\n{turn.code}\n```\n")

        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"SessionManager("
            f"turns={len(self.history)}, "
            f"file={self.current_file})"
        )