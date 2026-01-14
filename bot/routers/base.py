from __future__ import annotations

from abc import ABC, abstractmethod
from telegram.ext import Application


class BaseRouter(ABC):
    """路由器基类"""

    @abstractmethod
    def register(self, app: Application) -> None:
        """注册所有处理器到应用"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """路由器名称"""
        pass
