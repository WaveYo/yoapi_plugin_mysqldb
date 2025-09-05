"""
数据库连接管理模块
提供异步MySQL连接池管理、连接获取和基础查询执行功能
支持连接池配置、健康检查、自动重连等功能
"""

import asyncio
import logging
from typing import Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager

import aiomysql
from asyncmy import connect as asyncmy_connect
from asyncmy.connection import Connection as AsyncmyConnection

from config import DatabaseConfig, get_database_config
from exceptions.database import (
    DatabaseConnectionError,
    DatabaseQueryError,
    ConnectionPoolExhaustedError,
    DatabaseTimeoutError
)

logger = logging.getLogger(__name__)


class AsyncConnectionPool:
    """异步MySQL连接池管理类"""
    
    def __init__(self, config: DatabaseConfig, pool_size: int = 10, max_overflow: int = 5):
        """
        初始化连接池
        
        Args:
            config: 数据库配置
            pool_size: 连接池大小
            max_overflow: 最大溢出连接数
        """
        self.config = config
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self._pool: asyncio.Queue = None
        self._current_connections = 0
        self._is_initialized = False
        
    async def initialize(self) -> None:
        """初始化连接池"""
        if self._is_initialized:
            return
            
        self._pool = asyncio.Queue(maxsize=self.pool_size + self.max_overflow)
        
        # 预先创建最小连接数
        initial_connections = min(3, self.pool_size)
        for _ in range(initial_connections):
            try:
                connection = await self._create_connection()
                await self._pool.put(connection)
                self._current_connections += 1
            except Exception as e:
                logger.warning(f"Failed to create initial connection: {e}")
                
        self._is_initialized = True
        logger.info(f"Connection pool initialized with {self._current_connections} connections")
    
    async def _create_connection(self) -> Any:
        """创建新的数据库连接"""
        try:
            if self.config.driver == "aiomysql":
                connection = await aiomysql.connect(
                    host=self.config.host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    db=self.config.database,
                    charset='utf8mb4',
                    autocommit=True,
                    connect_timeout=self.config.connect_timeout
                )
            elif self.config.driver == "asyncmy":
                connection = await asyncmy_connect(
                    host=self.config.host,
                    port=self.config.port,
                    user=self.config.username,
                    password=self.config.password,
                    database=self.config.database,
                    charset='utf8mb4',
                    connect_timeout=self.config.connect_timeout
                )
            else:
                raise DatabaseConnectionError(f"Unsupported database driver: {self.config.driver}")
                
            return connection
        except Exception as e:
            raise DatabaseConnectionError(f"Failed to create database connection: {e}")
    
    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[Any, None]:
        """
        获取数据库连接上下文管理器
        
        Yields:
            Any: 数据库连接对象
            
        Raises:
            ConnectionPoolExhaustedError: 连接池耗尽
            DatabaseConnectionError: 连接创建失败
        """
        if not self._is_initialized:
            await self.initialize()
            
        connection = None
        try:
            # 尝试从池中获取连接
            try:
                connection = await asyncio.wait_for(
                    self._pool.get(), 
                    timeout=self.config.connect_timeout
                )
            except asyncio.QueueEmpty:
                # 队列为空，尝试创建新连接
                if self._current_connections < self.pool_size + self.max_overflow:
                    connection = await self._create_connection()
                    self._current_connections += 1
                else:
                    raise ConnectionPoolExhaustedError("Connection pool exhausted")
            except asyncio.TimeoutError:
                raise DatabaseTimeoutError("Timeout waiting for database connection")
                
            yield connection
            
        except Exception as e:
            # 处理获取连接过程中的异常
            if isinstance(e, (ConnectionPoolExhaustedError, DatabaseTimeoutError)):
                raise
            raise DatabaseConnectionError(f"Failed to get database connection: {e}")
            
        finally:
            # 将连接返回到池中
            if connection:
                try:
                    # 检查连接是否仍然有效
                    if await self._is_connection_valid(connection):
                        await self._pool.put(connection)
                    else:
                        # 连接无效，创建新连接替换
                        self._current_connections -= 1
                        try:
                            new_connection = await self._create_connection()
                            await self._pool.put(new_connection)
                            self._current_connections += 1
                        except Exception:
                            # 创建新连接失败，减少计数但不添加
                            pass
                except Exception:
                    # 处理连接返回过程中的异常
                    self._current_connections -= 1
    
    async def _is_connection_valid(self, connection: Any) -> bool:
        """检查连接是否有效"""
        try:
            if self.config.driver == "aiomysql":
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    return True
            elif self.config.driver == "asyncmy":
                async with connection.cursor() as cursor:
                    await cursor.execute("SELECT 1")
                    return True
            return False
        except Exception:
            return False
    
    async def close(self) -> None:
        """关闭连接池中的所有连接"""
        if not self._is_initialized:
            return
            
        while not self._pool.empty():
            try:
                connection = self._pool.get_nowait()
                await connection.close()
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
                
        self._is_initialized = False
        self._current_connections = 0
        logger.info("Connection pool closed")
    
    async def health_check(self) -> bool:
        """执行健康检查"""
        try:
            async with self.get_connection() as conn:
                if self.config.driver == "aiomysql":
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT 1")
                        result = await cursor.fetchone()
                        return result[0] == 1
                elif self.config.driver == "asyncmy":
                    async with conn.cursor() as cursor:
                        await cursor.execute("SELECT 1")
                        result = await cursor.fetchone()
                        return result[0] == 1
            return False
        except Exception:
            return False
    
    @property
    def stats(self) -> Dict[str, Any]:
        """获取连接池统计信息"""
        return {
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "current_connections": self._current_connections,
            "available_connections": self._pool.qsize() if self._pool else 0,
            "is_initialized": self._is_initialized
        }


class DatabaseConnectionManager:
    """数据库连接管理器"""
    
    def __init__(self):
        self._pools: Dict[str, AsyncConnectionPool] = {}
        self._default_pool: Optional[AsyncConnectionPool] = None
        
    async def initialize(self, config: Optional[DatabaseConfig] = None) -> None:
        """
        初始化默认数据库连接
        
        Args:
            config: 数据库配置，如果为None则使用默认配置
        """
        if config is None:
            config = get_database_config()
            
        pool = AsyncConnectionPool(
            config=config,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow
        )
        await pool.initialize()
        
        self._default_pool = pool
        self._pools["default"] = pool
        logger.info(f"Default database connection initialized for {config.database}")
    
    async def add_database(self, name: str, config: DatabaseConfig) -> None:
        """
        添加额外的数据库连接
        
        Args:
            name: 数据库名称标识
            config: 数据库配置
        """
        if name in self._pools:
            raise DatabaseConnectionError(f"Database '{name}' already exists")
            
        pool = AsyncConnectionPool(
            config=config,
            pool_size=config.pool_size,
            max_overflow=config.max_overflow
        )
        await pool.initialize()
        
        self._pools[name] = pool
        logger.info(f"Database '{name}' connection initialized for {config.database}")
    
    @asynccontextmanager
    async def get_connection(self, database_name: str = "default") -> AsyncGenerator[Any, None]:
        """
        获取数据库连接
        
        Args:
            database_name: 数据库名称标识，默认为"default"
            
        Yields:
            Any: 数据库连接对象
            
        Raises:
            DatabaseConnectionError: 数据库未找到或连接失败
        """
        if database_name not in self._pools:
            raise DatabaseConnectionError(f"Database '{database_name}' not found")
            
        async with self._pools[database_name].get_connection() as connection:
            yield connection
    
    async def execute_query(self, query: str, params: Optional[tuple] = None, 
                          database_name: str = "default") -> Any:
        """
        执行SQL查询
        
        Args:
            query: SQL查询语句
            params: 查询参数
            database_name: 数据库名称标识
            
        Returns:
            Any: 查询结果
            
        Raises:
            DatabaseQueryError: 查询执行失败
        """
        try:
            async with self.get_connection(database_name) as conn:
                if isinstance(conn, aiomysql.Connection):
                    async with conn.cursor() as cursor:
                        await cursor.execute(query, params)
                        if query.strip().upper().startswith("SELECT"):
                            return await cursor.fetchall()
                        else:
                            return cursor.lastrowid
                elif isinstance(conn, AsyncmyConnection):
                    async with conn.cursor() as cursor:
                        await cursor.execute(query, params)
                        if query.strip().upper().startswith("SELECT"):
                            return await cursor.fetchall()
                        else:
                            return cursor.lastrowid
        except Exception as e:
            raise DatabaseQueryError(f"Failed to execute query: {e}")
    
    async def health_check(self, database_name: str = "default") -> bool:
        """执行健康检查"""
        if database_name not in self._pools:
            return False
            
        return await self._pools[database_name].health_check()
    
    async def close_all(self) -> None:
        """关闭所有数据库连接"""
        for name, pool in self._pools.items():
            try:
                await pool.close()
                logger.info(f"Database '{name}' connection closed")
            except Exception as e:
                logger.error(f"Error closing database '{name}' connection: {e}")
                
        self._pools.clear()
        self._default_pool = None
    
    def get_pool_stats(self, database_name: str = "default") -> Optional[Dict[str, Any]]:
        """获取连接池统计信息"""
        if database_name in self._pools:
            return self._pools[database_name].stats
        return None


# 全局连接管理器实例
connection_manager = DatabaseConnectionManager()
