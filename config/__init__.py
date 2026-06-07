"""
config 模块
"""

__all__ = ["settings"]


def __getattr__(name: str):
    if name == "settings":
        from config.settings import settings

        return settings
    raise AttributeError(name)
