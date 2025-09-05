"""
核心模块 - 数据库连接和基础功能
提供异步MySQL连接池管理、连接获取和基础查询执行功能
"""

from .connection import DatabaseConnectionManager, AsyncConnectionPool

__all__ = ['DatabaseConnectionManager', 'AsyncConnectionPool']
