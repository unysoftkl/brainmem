"""brainmem · 仿脑记忆数据库 阶段1 记忆内核。

公开门面：from brainmem import Memory, load_config
"""
from brainmem.config import load_config, Config
from brainmem.interfaces.memory import Memory

__all__ = ["Memory", "load_config", "Config"]
__version__ = "0.1.0"
