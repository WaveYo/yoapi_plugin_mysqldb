"""
多数据库路由和负载均衡模块
提供多数据库配置、路由选择、负载均衡和读写分离功能
"""

import asyncio
import random
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
from enum import Enum
from contextvars import ContextVar

from ..config.settings import DatabaseConfig
from ..core.connection import AsyncConnectionPool
from ..exceptions.database import (
    DatabaseConnectionError,
    DatabaseRouterError,
    NoAvailableDatabaseError
)


class DatabaseRole(Enum):
    """数据库角色枚举"""
    MASTER = "master"
    REPLICA = "replica"
    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"


class LoadBalanceStrategy(Enum):
    """负载均衡策略枚举"""
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    WEIGHTED = "weighted"
    LEAST_CONNECTIONS = "least_connections"


@dataclass
class DatabaseNode:
    """数据库节点信息"""
    name: str
    config: DatabaseConfig
    pool: AsyncConnectionPool
    role: DatabaseRole
    weight: int = 1
    is_healthy: bool = True
    connection_count: int = 0


class DatabaseRouter:
    """
    数据库路由器
    负责根据操作类型和负载均衡策略选择合适的数据库节点
    """
    
    def __init__(self):
        self._databases: Dict[str, DatabaseNode] = {}
        self._current_index: Dict[DatabaseRole, int] = {}
        self._default_strategy = LoadBalanceStrategy.ROUND_ROBIN
        
    def add_database(self, name: str, config: DatabaseConfig, 
                    role: DatabaseRole = DatabaseRole.MASTER,
                    weight: int = 1) -> DatabaseNode:
        """
        添加数据库节点
        
        Args:
            name: 数据库名称
            config: 数据库配置
            role: 数据库角色
            weight: 权重（用于加权负载均衡）
            
        Returns:
            DatabaseNode: 创建的数据库节点
        """
        if name in self._databases:
            raise DatabaseRouterError(f"数据库 '{name}' 已存在")
            
        pool = AsyncConnectionPool(config)
        node = DatabaseNode(
            name=name,
            config=config,
            pool=pool,
            role=role,
            weight=weight
        )
        
        self._databases[name] = node
        return node
    
    def remove_database(self, name: str) -> None:
        """移除数据库节点"""
        if name in self._databases:
            # 关闭连接池
            asyncio.create_task(self._databases[name].pool.close())
            del self._databases[name]
    
    def get_database(self, name: str) -> Optional[DatabaseNode]:
        """获取指定名称的数据库节点"""
        return self._databases.get(name)
    
    def get_databases_by_role(self, role: DatabaseRole) -> List[DatabaseNode]:
        """根据角色获取数据库节点列表"""
        return [node for node in self._databases.values() if node.role == role]
    
    def get_available_databases(self, role: Optional[DatabaseRole] = None) -> List[DatabaseNode]:
        """
        获取可用的数据库节点
        
        Args:
            role: 指定的数据库角色，如果为None则返回所有可用节点
            
        Returns:
            List[DatabaseNode]: 可用的数据库节点列表
        """
        available_nodes = []
        for node in self._databases.values():
            if node.is_healthy:
                if role is None or node.role == role:
                    available_nodes.append(node)
        
        return available_nodes
    
    async def select_database(self, 
                            operation_type: str = "read",
                            strategy: Optional[LoadBalanceStrategy] = None,
                            preferred_role: Optional[DatabaseRole] = None) -> DatabaseNode:
        """
        选择数据库节点
        
        Args:
            operation_type: 操作类型 ('read' 或 'write')
            strategy: 负载均衡策略
            preferred_role: 首选数据库角色
            
        Returns:
            DatabaseNode: 选择的数据库节点
            
        Raises:
            NoAvailableDatabaseError: 没有可用的数据库节点
        """
        # 确定目标角色
        if preferred_role:
            target_role = preferred_role
        elif operation_type.lower() == "write":
            target_role = DatabaseRole.MASTER
        else:
            # 读操作优先选择副本节点
            replica_nodes = self.get_available_databases(DatabaseRole.REPLICA)
            if replica_nodes:
                target_role = DatabaseRole.REPLICA
            else:
                target_role = DatabaseRole.MASTER
        
        # 获取可用节点
        available_nodes = self.get_available_databases(target_role)
        if not available_nodes:
            # 如果没有指定角色的节点，尝试使用主节点
            if target_role != DatabaseRole.MASTER:
                available_nodes = self.get_available_databases(DatabaseRole.MASTER)
            
            if not available_nodes:
                raise NoAvailableDatabaseError(
                    f"没有可用的 {target_role.value} 数据库节点"
                )
        
        # 使用指定的负载均衡策略或默认策略
        effective_strategy = strategy or self._default_strategy
        
        if effective_strategy == LoadBalanceStrategy.ROUND_ROBIN:
            return self._round_robin_selection(available_nodes, target_role)
        elif effective_strategy == LoadBalanceStrategy.RANDOM:
            return self._random_selection(available_nodes)
        elif effective_strategy == LoadBalanceStrategy.WEIGHTED:
            return self._weighted_selection(available_nodes)
        elif effective_strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
            return self._least_connections_selection(available_nodes)
        else:
            return self._round_robin_selection(available_nodes, target_role)
    
    def _round_robin_selection(self, nodes: List[DatabaseNode], role: DatabaseRole) -> DatabaseNode:
        """轮询选择"""
        if role not in self._current_index:
            self._current_index[role] = 0
        
        index = self._current_index[role]
        selected_node = nodes[index % len(nodes)]
        
        self._current_index[role] = (index + 1) % len(nodes)
        return selected_node
    
    def _random_selection(self, nodes: List[DatabaseNode]) -> DatabaseNode:
        """随机选择"""
        return random.choice(nodes)
    
    def _weighted_selection(self, nodes: List[DatabaseNode]) -> DatabaseNode:
        """加权选择"""
        total_weight = sum(node.weight for node in nodes)
        rand_val = random.uniform(0, total_weight)
        
        current = 0
        for node in nodes:
            current += node.weight
            if rand_val <= current:
                return node
        
        return nodes[-1]  # 兜底返回最后一个节点
    
    def _least_connections_selection(self, nodes: List[DatabaseNode]) -> DatabaseNode:
        """最少连接数选择"""
        return min(nodes, key=lambda node: node.connection_count)
    
    async def health_check(self) -> Dict[str, bool]:
        """执行健康检查"""
        results = {}
        for name, node in self._databases.items():
            try:
                # 尝试获取连接来检查数据库健康状态
                async with node.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT 1")
                        await cursor.fetchone()
                node.is_healthy = True
                results[name] = True
            except Exception:
                node.is_healthy = False
                results[name] = False
        
        return results
    
    async def close_all(self) -> None:
        """关闭所有数据库连接池"""
        for node in self._databases.values():
            await node.pool.close()


class MultiDatabaseManager:
    """
    多数据库管理器
    提供统一的接口来管理多个数据库实例
    """
    
    def __init__(self):
        self.router = DatabaseRouter()
        self._current_db: ContextVar[Optional[str]] = ContextVar('current_db', default=None)
    
    def add_database_instance(self, name: str, config: DatabaseConfig, 
                            role: DatabaseRole = DatabaseRole.MASTER,
                            weight: int = 1) -> DatabaseNode:
        """
        添加数据库实例
        
        Args:
            name: 实例名称
            config: 数据库配置
            role: 数据库角色
            weight: 权重
            
        Returns:
            DatabaseNode: 创建的数据库节点
        """
        return self.router.add_database(name, config, role, weight)
    
    def set_default_database(self, name: str) -> None:
        """设置默认数据库"""
        if name not in self.router._databases:
            raise DatabaseRouterError(f"数据库 '{name}' 不存在")
        self._current_db.set(name)
    
    def get_default_database(self) -> Optional[str]:
        """获取默认数据库名称"""
        return self._current_db.get()
    
    async def get_connection(self, 
                           operation_type: str = "read",
                           database_name: Optional[str] = None,
                           strategy: Optional[LoadBalanceStrategy] = None) -> Any:
        """
        获取数据库连接
        
        Args:
            operation_type: 操作类型 ('read' 或 'write')
            database_name: 指定的数据库名称
            strategy: 负载均衡策略
            
        Returns:
            Any: 数据库连接对象
        """
        if database_name:
            # 使用指定的数据库
            node = self.router.get_database(database_name)
            if not node:
                raise DatabaseRouterError(f"数据库 '{database_name}' 不存在")
            if not node.is_healthy:
                raise DatabaseConnectionError(f"数据库 '{database_name}' 不可用")
        else:
            # 自动选择数据库
            node = await self.router.select_database(operation_type, strategy)
        
        # 更新连接计数
        node.connection_count += 1
        
        try:
            connection = await node.pool.acquire()
            return connection
        except Exception as e:
            node.connection_count -= 1
            raise DatabaseConnectionError(f"获取数据库连接失败: {e}") from e
        finally:
            # 使用上下文管理器确保连接计数正确减少
            pass
    
    async def execute_on_all(self, sql: str, params: Optional[list] = None) -> Dict[str, Any]:
        """
        在所有数据库上执行SQL语句
        
        Args:
            sql: SQL语句
            params: 参数列表
            
        Returns:
            Dict[str, Any]: 各数据库的执行结果
        """
        results = {}
        for name, node in self.router._databases.items():
            if node.is_healthy:
                try:
                    async with node.pool.acquire() as conn:
                        async with conn.cursor() as cursor:
                            await cursor.execute(sql, params)
                            if sql.strip().lower().startswith('select'):
                                result = await cursor.fetchall()
                            else:
                                result = cursor.rowcount
                            results[name] = result
                except Exception as e:
                    results[name] = f"Error: {str(e)}"
            else:
                results[name] = "Database unavailable"
        
        return results
    
    async def health_check(self) -> Dict[str, bool]:
        """执行健康检查"""
        return await self.router.health_check()
    
    async def close(self) -> None:
        """关闭所有数据库连接"""
        await self.router.close_all()


# 全局多数据库管理器实例
_multi_db_manager: Optional[MultiDatabaseManager] = None


def get_multi_database_manager() -> MultiDatabaseManager:
    """
    获取全局多数据库管理器实例
    
    Returns:
        MultiDatabaseManager: 多数据库管理器实例
        
    Raises:
        DatabaseRouterError: 如果管理器未初始化
    """
    global _multi_db_manager
    if _multi_db_manager is None:
        raise DatabaseRouterError("多数据库管理器未初始化")
    return _multi_db_manager


def init_multi_database_manager() -> MultiDatabaseManager:
    """
    初始化全局多数据库管理器
    
    Returns:
        MultiDatabaseManager: 初始化的多数据库管理器实例
    """
    global _multi_db_manager
    _multi_db_manager = MultiDatabaseManager()
    return _multi_db_manager
