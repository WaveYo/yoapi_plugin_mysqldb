"""
CRUD服务模块
提供基础的数据库增删改查操作、事务管理和高级查询功能
支持批量操作、条件查询、分页查询等高级功能
"""

import logging
from typing import Any, Dict, List, Optional, Tuple, Union, TypeVar, Generic
from contextlib import asynccontextmanager
from datetime import datetime

from core.connection import connection_manager
from exceptions.database import (
    DatabaseQueryError,
    DatabaseInsertError,
    DatabaseUpdateError,
    DatabaseDeleteError,
    TransactionError
)

logger = logging.getLogger(__name__)
T = TypeVar('T')


class QueryBuilder:
    """查询构建器，支持链式调用构建复杂查询"""
    
    def __init__(self, table_name: str):
        self.table_name = table_name
        self._conditions: List[str] = []
        self._params: List[Any] = []
        self._order_by: List[str] = []
        self._limit: Optional[int] = None
        self._offset: Optional[int] = None
        self._fields: List[str] = ["*"]
        self._joins: List[str] = []
        self._group_by: List[str] = []
        self._having: List[str] = []
        
    def select(self, fields: Union[str, List[str]]) -> 'QueryBuilder':
        """选择查询字段"""
        if isinstance(fields, str):
            self._fields = [fields]
        else:
            self._fields = fields
        return self
        
    def where(self, condition: str, *params) -> 'QueryBuilder':
        """添加WHERE条件"""
        self._conditions.append(condition)
        self._params.extend(params)
        return self
        
    def and_where(self, condition: str, *params) -> 'QueryBuilder':
        """添加AND WHERE条件"""
        return self.where(condition, *params)
        
    def or_where(self, condition: str, *params) -> 'QueryBuilder':
        """添加OR WHERE条件"""
        if self._conditions:
            self._conditions[-1] = f"({self._conditions[-1]} OR {condition})"
        else:
            self._conditions.append(condition)
        self._params.extend(params)
        return self
        
    def order_by(self, field: str, direction: str = "ASC") -> 'QueryBuilder':
        """添加排序条件"""
        self._order_by.append(f"{field} {direction}")
        return self
        
    def limit(self, limit: int) -> 'QueryBuilder':
        """设置查询限制"""
        self._limit = limit
        return self
        
    def offset(self, offset: int) -> 'QueryBuilder':
        """设置查询偏移"""
        self._offset = offset
        return self
        
    def join(self, table: str, condition: str) -> 'QueryBuilder':
        """添加JOIN条件"""
        self._joins.append(f"JOIN {table} ON {condition}")
        return self
        
    def left_join(self, table: str, condition: str) -> 'QueryBuilder':
        """添加LEFT JOIN条件"""
        self._joins.append(f"LEFT JOIN {table} ON {condition}")
        return self
        
    def group_by(self, fields: Union[str, List[str]]) -> 'QueryBuilder':
        """添加GROUP BY条件"""
        if isinstance(fields, str):
            self._group_by.append(fields)
        else:
            self._group_by.extend(fields)
        return self
        
    def having(self, condition: str, *params) -> 'QueryBuilder':
        """添加HAVING条件"""
        self._having.append(condition)
        self._params.extend(params)
        return self
        
    def build(self) -> Tuple[str, List[Any]]:
        """构建SQL查询语句和参数"""
        sql_parts = ["SELECT", ", ".join(self._fields), "FROM", self.table_name]
        
        if self._joins:
            sql_parts.extend(self._joins)
            
        if self._conditions:
            sql_parts.append("WHERE")
            sql_parts.append(" AND ".join(self._conditions))
            
        if self._group_by:
            sql_parts.append("GROUP BY")
            sql_parts.append(", ".join(self._group_by))
            
        if self._having:
            sql_parts.append("HAVING")
            sql_parts.append(" AND ".join(self._having))
            
        if self._order_by:
            sql_parts.append("ORDER BY")
            sql_parts.append(", ".join(self._order_by))
            
        if self._limit is not None:
            sql_parts.append(f"LIMIT {self._limit}")
            
        if self._offset is not None:
            sql_parts.append(f"OFFSET {self._offset}")
            
        sql = " ".join(sql_parts)
        return sql, self._params
        
    async def execute(self, database_name: str = "default") -> List[Dict[str, Any]]:
        """执行查询并返回结果"""
        sql, params = self.build()
        try:
            result = await connection_manager.execute_query(sql, params, database_name)
            return result
        except Exception as e:
            raise DatabaseQueryError(f"Failed to execute query: {e}")


class TransactionManager:
    """事务管理器，支持事务的提交和回滚"""
    
    def __init__(self, database_name: str = "default"):
        self.database_name = database_name
        self._connection = None
        self._in_transaction = False
        
    @asynccontextmanager
    async def begin(self):
        """开始事务上下文管理器"""
        if self._in_transaction:
            raise TransactionError("Already in transaction")
            
        try:
            async with connection_manager.get_connection(self.database_name) as conn:
                self._connection = conn
                self._in_transaction = True
                
                # 开始事务
                if hasattr(conn, 'begin'):
                    await conn.begin()
                else:
                    await conn.autocommit(False)
                    
                try:
                    yield self
                    # 提交事务
                    await conn.commit()
                except Exception:
                    # 回滚事务
                    await conn.rollback()
                    raise
                finally:
                    self._in_transaction = False
                    self._connection = None
                    
        except Exception as e:
            raise TransactionError(f"Transaction failed: {e}")
            
    async def execute(self, query: str, params: Optional[tuple] = None) -> Any:
        """在事务中执行查询"""
        if not self._in_transaction or not self._connection:
            raise TransactionError("Not in active transaction")
            
        try:
            if hasattr(self._connection, 'cursor'):
                async with self._connection.cursor() as cursor:
                    await cursor.execute(query, params)
                    if query.strip().upper().startswith("SELECT"):
                        return await cursor.fetchall()
                    else:
                        return cursor.lastrowid
            else:
                raise TransactionError("Unsupported connection type for transaction")
        except Exception as e:
            raise DatabaseQueryError(f"Failed to execute query in transaction: {e}")


class CRUDService(Generic[T]):
    """基础的CRUD操作服务"""
    
    def __init__(self, table_name: str, database_name: str = "default"):
        self.table_name = table_name
        self.database_name = database_name
        
    async def create(self, data: Dict[str, Any]) -> int:
        """
        创建新记录
        
        Args:
            data: 要插入的数据字典
            
        Returns:
            int: 插入记录的主键ID
            
        Raises:
            DatabaseInsertError: 插入失败
        """
        try:
            fields = list(data.keys())
            placeholders = ["%s"] * len(fields)
            values = list(data.values())
            
            sql = f"INSERT INTO {self.table_name} ({', '.join(fields)}) VALUES ({', '.join(placeholders)})"
            result = await connection_manager.execute_query(sql, values, self.database_name)
            return result
        except Exception as e:
            raise DatabaseInsertError(f"Failed to create record in {self.table_name}: {e}")
            
    async def create_many(self, data_list: List[Dict[str, Any]]) -> int:
        """
        批量创建记录
        
        Args:
            data_list: 要插入的数据字典列表
            
        Returns:
            int: 插入的记录数量
            
        Raises:
            DatabaseInsertError: 插入失败
        """
        if not data_list:
            return 0
            
        try:
            fields = list(data_list[0].keys())
            placeholders = ["%s"] * len(fields)
            values = []
            
            for data in data_list:
                values.extend([data[field] for field in fields])
                
            value_placeholders = ", ".join([f"({', '.join(placeholders)})" for _ in data_list])
            sql = f"INSERT INTO {self.table_name} ({', '.join(fields)}) VALUES {value_placeholders}"
            
            result = await connection_manager.execute_query(sql, values, self.database_name)
            return len(data_list)
        except Exception as e:
            raise DatabaseInsertError(f"Failed to create multiple records in {self.table_name}: {e}")
            
    async def get_by_id(self, id: Any, id_field: str = "id") -> Optional[Dict[str, Any]]:
        """
        根据ID获取记录
        
        Args:
            id: 记录ID
            id_field: ID字段名，默认为"id"
            
        Returns:
            Optional[Dict]: 记录数据，如果不存在则返回None
            
        Raises:
            DatabaseQueryError: 查询失败
        """
        try:
            sql = f"SELECT * FROM {self.table_name} WHERE {id_field} = %s"
            result = await connection_manager.execute_query(sql, (id,), self.database_name)
            return result[0] if result else None
        except Exception as e:
            raise DatabaseQueryError(f"Failed to get record by ID from {self.table_name}: {e}")
            
    async def get_all(self, limit: Optional[int] = None, offset: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取所有记录
        
        Args:
            limit: 限制返回数量
            offset: 偏移量
            
        Returns:
            List[Dict]: 记录列表
            
        Raises:
            DatabaseQueryError: 查询失败
        """
        try:
            sql = f"SELECT * FROM {self.table_name}"
            params = []
            
            if limit is not None:
                sql += " LIMIT %s"
                params.append(limit)
                
            if offset is not None:
                sql += " OFFSET %s"
                params.append(offset)
                
            result = await connection_manager.execute_query(sql, params, self.database_name)
            return result
        except Exception as e:
            raise DatabaseQueryError(f"Failed to get all records from {self.table_name}: {e}")
            
    async def update(self, id: Any, data: Dict[str, Any], id_field: str = "id") -> bool:
        """
        更新记录
        
        Args:
            id: 记录ID
            data: 要更新的数据字典
            id_field: ID字段名，默认为"id"
            
        Returns:
            bool: 是否成功更新
            
        Raises:
            DatabaseUpdateError: 更新失败
        """
        try:
            set_clause = ", ".join([f"{field} = %s" for field in data.keys()])
            values = list(data.values()) + [id]
            
            sql = f"UPDATE {self.table_name} SET {set_clause} WHERE {id_field} = %s"
            result = await connection_manager.execute_query(sql, values, self.database_name)
            return result > 0
        except Exception as e:
            raise DatabaseUpdateError(f"Failed to update record in {self.table_name}: {e}")
            
    async def delete(self, id: Any, id_field: str = "id") -> bool:
        """
        删除记录
        
        Args:
            id: 记录ID
            id_field: ID字段名，默认为"id"
            
        Returns:
            bool: 是否成功删除
            
        Raises:
            DatabaseDeleteError: 删除失败
        """
        try:
            sql = f"DELETE FROM {self.table_name} WHERE {id_field} = %s"
            result = await connection_manager.execute_query(sql, (id,), self.database_name)
            return result > 0
        except Exception as e:
            raise DatabaseDeleteError(f"Failed to delete record from {self.table_name}: {e}")
            
    async def count(self, condition: Optional[str] = None, params: Optional[tuple] = None) -> int:
        """
        统计记录数量
        
        Args:
            condition: WHERE条件
            params: 条件参数
            
        Returns:
            int: 记录数量
            
        Raises:
            DatabaseQueryError: 查询失败
        """
        try:
            sql = f"SELECT COUNT(*) FROM {self.table_name}"
            if condition:
                sql += f" WHERE {condition}"
                
            result = await connection_manager.execute_query(sql, params, self.database_name)
            return result[0][0] if result else 0
        except Exception as e:
            raise DatabaseQueryError(f"Failed to count records in {self.table_name}: {e}")
            
    async def exists(self, condition: str, params: Optional[tuple] = None) -> bool:
        """
        检查记录是否存在
        
        Args:
            condition: WHERE条件
            params: 条件参数
            
        Returns:
            bool: 是否存在
            
        Raises:
            DatabaseQueryError: 查询失败
        """
        try:
            sql = f"SELECT EXISTS(SELECT 1 FROM {self.table_name} WHERE {condition})"
            result = await connection_manager.execute_query(sql, params, self.database_name)
            return bool(result[0][0]) if result else False
        except Exception as e:
            raise DatabaseQueryError(f"Failed to check existence in {self.table_name}: {e}")
            
    def query(self) -> QueryBuilder:
        """创建查询构建器"""
        return QueryBuilder(self.table_name)
        
    def transaction(self) -> TransactionManager:
        """创建事务管理器"""
        return TransactionManager(self.database_name)
        
    async def execute_raw(self, sql: str, params: Optional[tuple] = None) -> Any:
        """
        执行原始SQL查询
        
        Args:
            sql: SQL语句
            params: 查询参数
            
        Returns:
            Any: 查询结果
            
        Raises:
            DatabaseQueryError: 查询失败
        """
        try:
            return await connection_manager.execute_query(sql, params, self.database_name)
        except Exception as e:
            raise DatabaseQueryError(f"Failed to execute raw SQL: {e}")


# 示例使用方式
async def example_usage():
    """CRUD服务使用示例"""
    # 创建用户服务
    user_service = CRUDService("users")
    
    # 创建新用户
    user_id = await user_service.create({
        "username": "john_doe",
        "email": "john@example.com",
        "created_at": datetime.now()
    })
    
    # 根据ID获取用户
    user = await user_service.get_by_id(user_id)
    
    # 更新用户信息
    await user_service.update(user_id, {"email": "john.doe@example.com"})
    
    # 使用查询构建器
    users = await user_service.query() \
        .select(["id", "username", "email"]) \
        .where("username LIKE %s", "john%") \
        .order_by("created_at", "DESC") \
        .limit(10) \
        .execute()
    
    # 使用事务
    async with user_service.transaction().begin() as tx:
        await tx.execute("UPDATE users SET status = %s WHERE id = %s", ("active", user_id))
        await tx.execute("INSERT INTO user_logs (user_id, action) VALUES (%s, %s)", (user_id, "status_updated"))
