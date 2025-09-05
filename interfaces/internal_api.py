"""
内部公共API接口模块
提供插件内部使用的非HTTP公共接口，支持数据库多种功能
"""

import asyncio
from typing import Dict, List, Optional, Any, Union, Callable
from contextlib import asynccontextmanager

from ..config.settings import DatabaseConfig, config_manager
from ..core.connection import AsyncConnectionPool
from ..services.crud import CRUDService, TransactionManager, QueryBuilder
from ..features.migration import MigrationManager, TableManager
from ..features.router import MultiDatabaseManager, DatabaseRouter, get_multi_database_manager, init_multi_database_manager
from ..exceptions.database import (
    DatabaseError,
    DatabaseConnectionError,
    DatabaseQueryError,
    DatabaseTransactionError,
    DatabaseMigrationError
)


class DatabaseInternalAPI:
    """
    数据库内部公共API接口
    提供统一的内部接口来访问数据库功能
    """
    
    def __init__(self):
        self._multi_db_manager: Optional[MultiDatabaseManager] = None
        self._crud_services: Dict[str, CRUDService] = {}
        self._migration_manager: Optional[MigrationManager] = None
    
    async def initialize(self, config_manager=None) -> None:
        """
        初始化API接口
        
        Args:
            config_manager: 配置管理器实例，如果为None则使用全局实例
        """
        if config_manager is None:
            # 使用全局配置管理器实例
            from ..config.settings import config_manager
            config_manager = config_manager
        
        # 初始化多数据库管理器
        self._multi_db_manager = init_multi_database_manager()
        
        # 为每个数据库配置创建CRUD服务
        db_configs = config_manager.get_all_configs()
        for db_name, config in db_configs.items():
            pool = AsyncConnectionPool(config)
            crud_service = CRUDService(pool)
            self._crud_services[db_name] = crud_service
            
            # 添加到多数据库管理器
            role = self._get_database_role(config)
            self._multi_db_manager.add_database_instance(db_name, config, role)
        
        # 初始化迁移管理器
        self._migration_manager = MigrationManager()
    
    def _get_database_role(self, config: DatabaseConfig) -> Any:
        """根据配置获取数据库角色"""
        from ..features.router import DatabaseRole
        
        # 根据配置中的角色标识确定角色
        role_str = getattr(config, 'role', 'master').lower()
        if role_str in ['replica', 'slave', 'read']:
            return DatabaseRole.REPLICA
        elif role_str in ['readonly', 'read_only']:
            return DatabaseRole.READ_ONLY
        elif role_str in ['writeonly', 'write_only']:
            return DatabaseRole.WRITE_ONLY
        else:
            return DatabaseRole.MASTER
    
    # ========== 数据库连接管理 ==========
    
    @asynccontextmanager
    async def get_connection(self, 
                           database_name: Optional[str] = None,
                           operation_type: str = "read",
                           auto_commit: bool = True):
        """
        获取数据库连接（上下文管理器）
        
        Args:
            database_name: 数据库名称，如果为None则自动选择
            operation_type: 操作类型 ('read' 或 'write')
            auto_commit: 是否自动提交事务
            
        Yields:
            Any: 数据库连接对象
        """
        if self._multi_db_manager is None:
            raise DatabaseConnectionError("多数据库管理器未初始化")
        
        connection = None
        try:
            connection = await self._multi_db_manager.get_connection(
                operation_type, database_name
            )
            yield connection
            if auto_commit and operation_type == "write":
                await connection.commit()
        except Exception as e:
            if connection:
                await connection.rollback()
            raise DatabaseConnectionError(f"数据库连接操作失败: {e}") from e
        finally:
            if connection:
                await connection.close()
    
    async def health_check(self, database_name: Optional[str] = None) -> Dict[str, Any]:
        """
        执行健康检查
        
        Args:
            database_name: 指定的数据库名称，如果为None则检查所有数据库
            
        Returns:
            Dict[str, Any]: 健康检查结果
        """
        if self._multi_db_manager is None:
            raise DatabaseConnectionError("多数据库管理器未初始化")
        
        if database_name:
            # 检查单个数据库
            node = self._multi_db_manager.router.get_database(database_name)
            if not node:
                return {database_name: False}
            
            try:
                async with node.pool.acquire() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT 1")
                        await cursor.fetchone()
                return {database_name: True}
            except Exception:
                return {database_name: False}
        else:
            # 检查所有数据库
            return await self._multi_db_manager.health_check()
    
    # ========== CRUD 操作接口 ==========
    
    async def execute_query(self, 
                          sql: str, 
                          params: Optional[list] = None,
                          database_name: Optional[str] = None) -> Any:
        """
        执行SQL查询
        
        Args:
            sql: SQL语句
            params: 参数列表
            database_name: 数据库名称
            
        Returns:
            Any: 查询结果
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            # 自动选择服务
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "read") as conn:
            return await service.execute_query(conn, sql, params)
    
    async def execute_write(self, 
                          sql: str, 
                          params: Optional[list] = None,
                          database_name: Optional[str] = None) -> int:
        """
        执行写操作
        
        Args:
            sql: SQL语句
            params: 参数列表
            database_name: 数据库名称
            
        Returns:
            int: 影响的行数
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "write") as conn:
            return await service.execute_write(conn, sql, params)
    
    async def insert(self, 
                   table: str, 
                   data: Dict[str, Any],
                   database_name: Optional[str] = None) -> int:
        """
        插入数据
        
        Args:
            table: 表名
            data: 数据字典
            database_name: 数据库名称
            
        Returns:
            int: 插入的行ID
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "write") as conn:
            return await service.insert(conn, table, data)
    
    async def batch_insert(self, 
                         table: str, 
                         data_list: List[Dict[str, Any]],
                         database_name: Optional[str] = None) -> int:
        """
        批量插入数据
        
        Args:
            table: 表名
            data_list: 数据字典列表
            database_name: 数据库名称
            
        Returns:
            int: 插入的行数
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "write") as conn:
            return await service.batch_insert(conn, table, data_list)
    
    async def update(self, 
                   table: str, 
                   data: Dict[str, Any],
                   where: Dict[str, Any],
                   database_name: Optional[str] = None) -> int:
        """
        更新数据
        
        Args:
            table: 表名
            data: 要更新的数据
            where: 条件字典
            database_name: 数据库名称
            
        Returns:
            int: 影响的行数
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "write") as conn:
            return await service.update(conn, table, data, where)
    
    async def delete(self, 
                   table: str, 
                   where: Dict[str, Any],
                   database_name: Optional[str] = None) -> int:
        """
        删除数据
        
        Args:
            table: 表名
            where: 条件字典
            database_name: 数据库名称
            
        Returns:
            int: 删除的行数
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "write") as conn:
            return await service.delete(conn, table, where)
    
    async def select(self, 
                   table: str, 
                   columns: Optional[List[str]] = None,
                   where: Optional[Dict[str, Any]] = None,
                   order_by: Optional[str] = None,
                   limit: Optional[int] = None,
                   offset: Optional[int] = None,
                   database_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        查询数据
        
        Args:
            table: 表名
            columns: 要查询的列
            where: 条件字典
            order_by: 排序字段
            limit: 限制条数
            offset: 偏移量
            database_name: 数据库名称
            
        Returns:
            List[Dict[str, Any]]: 查询结果
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with self.get_connection(database_name, "read") as conn:
            return await service.select(conn, table, columns, where, order_by, limit, offset)
    
    # ========== 事务管理接口 ==========
    
    @asynccontextmanager
    async def transaction(self, database_name: Optional[str] = None):
        """
        事务上下文管理器
        
        Args:
            database_name: 数据库名称
            
        Yields:
            Any: 事务连接对象
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        async with service.transaction() as conn:
            yield conn
    
    async def begin_transaction(self, database_name: Optional[str] = None) -> Any:
        """
        开始事务
        
        Args:
            database_name: 数据库名称
            
        Returns:
            Any: 事务连接对象
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        return await service.begin_transaction()
    
    async def commit_transaction(self, conn: Any) -> None:
        """
        提交事务
        
        Args:
            conn: 事务连接对象
        """
        await conn.commit()
    
    async def rollback_transaction(self, conn: Any) -> None:
        """
        回滚事务
        
        Args:
            conn: 事务连接对象
        """
        await conn.rollback()
    
    # ========== 数据库迁移接口 ==========
    
    async def initialize_tables(self, 
                              table_definitions: Dict[str, str],
                              database_name: Optional[str] = None) -> Dict[str, bool]:
        """
        初始化表结构
        
        Args:
            table_definitions: 表定义字典 {表名: SQL定义}
            database_name: 数据库名称
            
        Returns:
            Dict[str, bool]: 各表的初始化结果
        """
        if self._migration_manager is None:
            raise DatabaseMigrationError("迁移管理器未初始化")
        
        results = {}
        for table_name, table_sql in table_definitions.items():
            try:
                table_manager = TableManager(table_name, table_sql)
                if database_name:
                    # 在指定数据库上执行
                    async with self.get_connection(database_name, "write") as conn:
                        success = await table_manager.initialize_table(conn)
                else:
                    # 在所有数据库上执行
                    success = await table_manager.initialize_table_on_all(self._multi_db_manager)
                
                results[table_name] = success
            except Exception as e:
                results[table_name] = False
        
        return results
    
    async def migrate(self, 
                    migration_script: str,
                    database_name: Optional[str] = None) -> bool:
        """
        执行迁移脚本
        
        Args:
            migration_script: 迁移脚本
            database_name: 数据库名称
            
        Returns:
            bool: 迁移是否成功
        """
        if self._migration_manager is None:
            raise DatabaseMigrationError("迁移管理器未初始化")
        
        try:
            if database_name:
                # 在指定数据库上执行
                async with self.get_connection(database_name, "write") as conn:
                    return await self._migration_manager.execute_migration(conn, migration_script)
            else:
                # 在所有数据库上执行
                return await self._migration_manager.execute_migration_on_all(
                    self._multi_db_manager, migration_script
                )
        except Exception:
            return False
    
    # ========== 多数据库操作接口 ==========
    
    async def execute_on_all_databases(self, 
                                     sql: str, 
                                     params: Optional[list] = None) -> Dict[str, Any]:
        """
        在所有数据库上执行SQL语句
        
        Args:
            sql: SQL语句
            params: 参数列表
            
        Returns:
            Dict[str, Any]: 各数据库的执行结果
        """
        if self._multi_db_manager is None:
            raise DatabaseError("多数据库管理器未初始化")
        
        return await self._multi_db_manager.execute_on_all(sql, params)
    
    async def switch_database(self, database_name: str) -> bool:
        """
        切换当前数据库
        
        Args:
            database_name: 数据库名称
            
        Returns:
            bool: 切换是否成功
        """
        if self._multi_db_manager is None:
            return False
        
        try:
            self._multi_db_manager.set_default_database(database_name)
            return True
        except Exception:
            return False
    
    def get_current_database(self) -> Optional[str]:
        """
        获取当前数据库名称
        
        Returns:
            Optional[str]: 当前数据库名称
        """
        if self._multi_db_manager is None:
            return None
        
        return self._multi_db_manager.get_default_database()
    
    def list_databases(self) -> List[str]:
        """
        获取所有数据库名称列表
        
        Returns:
            List[str]: 数据库名称列表
        """
        if self._multi_db_manager is None:
            return []
        
        return list(self._multi_db_manager.router._databases.keys())
    
    # ========== 工具方法 ==========
    
    def get_query_builder(self, database_name: Optional[str] = None) -> QueryBuilder:
        """
        获取查询构建器
        
        Args:
            database_name: 数据库名称
            
        Returns:
            QueryBuilder: 查询构建器实例
        """
        if database_name and database_name in self._crud_services:
            service = self._crud_services[database_name]
        else:
            service = next(iter(self._crud_services.values()))
        
        return service.query_builder()
    
    async def close(self) -> None:
        """关闭所有数据库连接"""
        if self._multi_db_manager:
            await self._multi_db_manager.close()
        
        # 关闭所有CRUD服务的连接池
        for service in self._crud_services.values():
            await service.close()


# 全局内部API实例
_internal_api: Optional[DatabaseInternalAPI] = None


def get_internal_api() -> DatabaseInternalAPI:
    """
    获取全局内部API实例
    
    Returns:
        DatabaseInternalAPI: 内部API实例
        
    Raises:
        DatabaseError: 如果API未初始化
    """
    global _internal_api
    if _internal_api is None:
        raise DatabaseError("数据库内部API未初始化")
    return _internal_api


def init_internal_api(config_manager=None) -> DatabaseInternalAPI:
    """
    初始化全局内部API
    
    Args:
        config_manager: 配置管理器实例
        
    Returns:
        DatabaseInternalAPI: 初始化的内部API实例
    """
    global _internal_api
    _internal_api = DatabaseInternalAPI()
    
    # 异步初始化
    async def _async_init():
        await _internal_api.initialize(config_manager)
    
    # 在当前事件循环中运行初始化
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 如果事件循环正在运行，创建任务异步初始化
            asyncio.create_task(_async_init())
        else:
            # 否则同步运行
            loop.run_until_complete(_async_init())
    except Exception:
        # 如果获取事件循环失败，使用新的事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_async_init())
    
    return _internal_api
