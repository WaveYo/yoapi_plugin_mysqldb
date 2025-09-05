"""
数据库迁移模块
提供表结构初始化、版本管理和迁移脚本执行功能
支持自动检测表结构变化和执行DDL操作
"""

import logging
import os
import json
from typing import Dict, List, Optional, Any, Set
from datetime import datetime
from pathlib import Path

from ..core.connection import connection_manager
from ..exceptions.database import (
    DatabaseMigrationError,
    DatabaseQueryError,
    TableCreationError
)

logger = logging.getLogger(__name__)


class TableManager:
    """表结构管理器，负责表的创建、修改和验证"""
    
    def __init__(self, database_name: str = "default"):
        self.database_name = database_name
        
    async def table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        try:
            sql = """
                SELECT COUNT(*) 
                FROM information_schema.tables 
                WHERE table_schema = DATABASE() AND table_name = %s
            """
            result = await connection_manager.execute_query(sql, (table_name,), self.database_name)
            return result[0][0] > 0 if result else False
        except Exception as e:
            raise DatabaseQueryError(f"Failed to check table existence: {e}")
            
    async def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """获取表的列信息"""
        try:
            sql = """
                SELECT 
                    column_name, 
                    data_type, 
                    is_nullable, 
                    column_default, 
                    column_key,
                    character_maximum_length,
                    numeric_precision,
                    numeric_scale
                FROM information_schema.columns 
                WHERE table_schema = DATABASE() AND table_name = %s
                ORDER BY ordinal_position
            """
            result = await connection_manager.execute_query(sql, (table_name,), self.database_name)
            return result
        except Exception as e:
            raise DatabaseQueryError(f"Failed to get table columns: {e}")
            
    async def create_table(self, table_name: str, columns: List[Dict[str, Any]], 
                         primary_key: Optional[List[str]] = None, 
                         indexes: Optional[List[Dict[str, Any]]] = None,
                         foreign_keys: Optional[List[Dict[str, Any]]] = None) -> bool:
        """
        创建表
        
        Args:
            table_name: 表名
            columns: 列定义列表
            primary_key: 主键字段列表
            indexes: 索引定义列表
            foreign_keys: 外键定义列表
            
        Returns:
            bool: 是否成功创建
        """
        try:
            column_definitions = []
            for column in columns:
                col_def = self._build_column_definition(column)
                column_definitions.append(col_def)
                
            # 构建主键
            if primary_key:
                column_definitions.append(f"PRIMARY KEY ({', '.join(primary_key)})")
                
            # 构建索引
            if indexes:
                for index in indexes:
                    index_def = self._build_index_definition(table_name, index)
                    column_definitions.append(index_def)
                    
            # 构建外键
            if foreign_keys:
                for fk in foreign_keys:
                    fk_def = self._build_foreign_key_definition(fk)
                    column_definitions.append(fk_def)
                    
            sql = f"CREATE TABLE IF NOT EXISTS {table_name} (\n    {',\n    '.join(column_definitions)}\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
            
            await connection_manager.execute_query(sql, None, self.database_name)
            logger.info(f"Table '{table_name}' created successfully")
            return True
            
        except Exception as e:
            raise TableCreationError(f"Failed to create table '{table_name}': {e}")
            
    def _build_column_definition(self, column: Dict[str, Any]) -> str:
        """构建列定义SQL"""
        name = column['name']
        data_type = column['type']
        nullable = "NULL" if column.get('nullable', True) else "NOT NULL"
        default = ""
        
        if 'default' in column:
            if column['default'] is None:
                default = "DEFAULT NULL"
            elif isinstance(column['default'], str):
                default = f"DEFAULT '{column['default']}'"
            else:
                default = f"DEFAULT {column['default']}"
                
        auto_increment = "AUTO_INCREMENT" if column.get('auto_increment', False) else ""
        
        return f"{name} {data_type} {nullable} {default} {auto_increment}".strip()
        
    def _build_index_definition(self, table_name: str, index: Dict[str, Any]) -> str:
        """构建索引定义SQL"""
        index_type = index.get('type', 'INDEX')
        index_name = index.get('name', f"idx_{table_name}_{'_'.join(index['columns'])}")
        columns = ', '.join(index['columns'])
        
        if index_type.upper() == 'UNIQUE':
            return f"UNIQUE KEY {index_name} ({columns})"
        else:
            return f"KEY {index_name} ({columns})"
            
    def _build_foreign_key_definition(self, fk: Dict[str, Any]) -> str:
        """构建外键定义SQL"""
        fk_name = fk.get('name', f"fk_{fk['table']}_{fk['columns'][0]}")
        columns = ', '.join(fk['columns'])
        ref_table = fk['ref_table']
        ref_columns = ', '.join(fk['ref_columns'])
        on_delete = fk.get('on_delete', 'RESTRICT')
        on_update = fk.get('on_update', 'RESTRICT')
        
        return f"CONSTRAINT {fk_name} FOREIGN KEY ({columns}) REFERENCES {ref_table} ({ref_columns}) ON DELETE {on_delete} ON UPDATE {on_update}"
        
    async def alter_table(self, table_name: str, changes: List[Dict[str, Any]]) -> bool:
        """
        修改表结构
        
        Args:
            table_name: 表名
            changes: 修改操作列表
            
        Returns:
            bool: 是否成功修改
        """
        try:
            sql_statements = []
            for change in changes:
                sql = self._build_alter_statement(table_name, change)
                sql_statements.append(sql)
                
            for sql in sql_statements:
                await connection_manager.execute_query(sql, None, self.database_name)
                
            logger.info(f"Table '{table_name}' altered successfully")
            return True
            
        except Exception as e:
            raise DatabaseMigrationError(f"Failed to alter table '{table_name}': {e}")
            
    def _build_alter_statement(self, table_name: str, change: Dict[str, Any]) -> str:
        """构建ALTER TABLE语句"""
        operation = change['operation']
        
        if operation == 'add_column':
            col_def = self._build_column_definition(change['column'])
            return f"ALTER TABLE {table_name} ADD COLUMN {col_def}"
            
        elif operation == 'drop_column':
            return f"ALTER TABLE {table_name} DROP COLUMN {change['column_name']}"
            
        elif operation == 'modify_column':
            col_def = self._build_column_definition(change['column'])
            return f"ALTER TABLE {table_name} MODIFY COLUMN {col_def}"
            
        elif operation == 'add_index':
            index_def = self._build_index_definition(table_name, change['index'])
            return f"ALTER TABLE {table_name} ADD {index_def}"
            
        elif operation == 'drop_index':
            return f"ALTER TABLE {table_name} DROP INDEX {change['index_name']}"
            
        elif operation == 'add_foreign_key':
            fk_def = self._build_foreign_key_definition(change['foreign_key'])
            return f"ALTER TABLE {table_name} ADD {fk_def}"
            
        elif operation == 'drop_foreign_key':
            return f"ALTER TABLE {table_name} DROP FOREIGN KEY {change['fk_name']}"
            
        else:
            raise DatabaseMigrationError(f"Unsupported alter operation: {operation}")


class MigrationManager:
    """数据库迁移管理器，负责版本控制和迁移脚本执行"""
    
    def __init__(self, migrations_dir: str = "migrations", database_name: str = "default"):
        self.migrations_dir = migrations_dir
        self.database_name = database_name
        self.table_manager = TableManager(database_name)
        
        # 确保迁移目录存在
        os.makedirs(migrations_dir, exist_ok=True)
        
    async def initialize_migration_table(self) -> None:
        """初始化迁移记录表"""
        try:
            if not await self.table_manager.table_exists("migrations"):
                columns = [
                    {"name": "id", "type": "INT", "nullable": False, "auto_increment": True},
                    {"name": "version", "type": "VARCHAR(50)", "nullable": False},
                    {"name": "name", "type": "VARCHAR(255)", "nullable": False},
                    {"name": "applied_at", "type": "DATETIME", "nullable": False},
                    {"name": "checksum", "type": "VARCHAR(64)", "nullable": True}
                ]
                await self.table_manager.create_table(
                    "migrations", 
                    columns, 
                    primary_key=["id"],
                    indexes=[{"columns": ["version"], "type": "UNIQUE"}]
                )
                logger.info("Migration table initialized")
        except Exception as e:
            raise DatabaseMigrationError(f"Failed to initialize migration table: {e}")
            
    async def get_applied_migrations(self) -> Set[str]:
        """获取已应用的迁移版本"""
        try:
            if not await self.table_manager.table_exists("migrations"):
                return set()
                
            sql = "SELECT version FROM migrations ORDER BY applied_at"
            result = await connection_manager.execute_query(sql, None, self.database_name)
            return {row[0] for row in result} if result else set()
        except Exception as e:
            raise DatabaseMigrationError(f"Failed to get applied migrations: {e}")
            
    async def apply_migration(self, version: str, name: str, sql: str) -> bool:
        """
        应用迁移脚本
        
        Args:
            version: 迁移版本号
            name: 迁移名称
            sql: 迁移SQL语句
            
        Returns:
            bool: 是否成功应用
        """
        try:
            # 执行迁移SQL
            await connection_manager.execute_query(sql, None, self.database_name)
            
            # 记录迁移历史
            insert_sql = """
                INSERT INTO migrations (version, name, applied_at, checksum) 
                VALUES (%s, %s, %s, %s)
            """
            checksum = self._calculate_checksum(sql)
            await connection_manager.execute_query(
                insert_sql, 
                (version, name, datetime.now(), checksum), 
                self.database_name
            )
            
            logger.info(f"Migration {version} - {name} applied successfully")
            return True
            
        except Exception as e:
            raise DatabaseMigrationError(f"Failed to apply migration {version}: {e}")
            
    def _calculate_checksum(self, sql: str) -> str:
        """计算SQL语句的校验和"""
        import hashlib
        return hashlib.sha256(sql.encode()).hexdigest()
        
    async def generate_migration(self, name: str, changes: Dict[str, Any]) -> str:
        """
        生成迁移脚本
        
        Args:
            name: 迁移名称
            changes: 结构变化描述
            
        Returns:
            str: 生成的迁移文件路径
        """
        try:
            version = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{version}_{name}.sql"
            filepath = os.path.join(self.migrations_dir, filename)
            
            sql_content = self._generate_sql_from_changes(changes)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"-- Migration: {name}\n")
                f.write(f"-- Version: {version}\n")
                f.write(f"-- Generated at: {datetime.now()}\n\n")
                f.write(sql_content)
                
            logger.info(f"Migration script generated: {filepath}")
            return filepath
            
        except Exception as e:
            raise DatabaseMigrationError(f"Failed to generate migration: {e}")
            
    def _generate_sql_from_changes(self, changes: Dict[str, Any]) -> str:
        """根据结构变化生成SQL语句"""
        sql_lines = []
        
        for table_name, table_changes in changes.items():
            if 'create' in table_changes:
                # 创建新表
                table_def = table_changes['create']
                sql_lines.append(self.table_manager._build_create_table_sql(table_name, table_def))
                
            elif 'alter' in table_changes:
                # 修改表结构
                for alter_op in table_changes['alter']:
                    sql_lines.append(self.table_manager._build_alter_statement(table_name, alter_op))
                    
            elif 'drop' in table_changes:
                # 删除表
                sql_lines.append(f"DROP TABLE IF EXISTS {table_name};")
                
        return "\n".join(sql_lines) + "\n"
        
    async def migrate(self) -> None:
        """执行所有未应用的迁移"""
        try:
            await self.initialize_migration_table()
            applied_migrations = await self.get_applied_migrations()
            
            # 获取所有迁移文件
            migration_files = []
            for filename in os.listdir(self.migrations_dir):
                if filename.endswith('.sql'):
                    version = filename.split('_')[0]
                    if version not in applied_migrations:
                        migration_files.append((version, filename))
                        
            # 按版本号排序
            migration_files.sort(key=lambda x: x[0])
            
            # 应用迁移
            for version, filename in migration_files:
                filepath = os.path.join(self.migrations_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    sql_content = f.read()
                    
                # 提取迁移名称（去掉版本号和扩展名）
                name = filename[len(version)+1:-4]
                
                await self.apply_migration(version, name, sql_content)
                
            logger.info(f"Applied {len(migration_files)} migrations")
            
        except Exception as e:
            raise DatabaseMigrationError(f"Migration failed: {e}")
            
    async def rollback(self, steps: int = 1) -> None:
        """
        回滚迁移
        
        Args:
            steps: 回滚的步数
        """
        try:
            # 获取最近应用的迁移
            sql = "SELECT version, name FROM migrations ORDER BY applied_at DESC LIMIT %s"
            migrations = await connection_manager.execute_query(sql, (steps,), self.database_name)
            
            for version, name in migrations:
                # 这里需要实现回滚逻辑，通常需要为每个迁移创建对应的回滚脚本
                logger.warning(f"Rollback not fully implemented for migration {version} - {name}")
                
            logger.info(f"Rolled back {len(migrations)} migrations")
            
        except Exception as e:
            raise DatabaseMigrationError(f"Rollback failed: {e}")


# 示例表结构定义
SAMPLE_TABLES = {
    "users": {
        "columns": [
            {"name": "id", "type": "INT", "nullable": False, "auto_increment": True},
            {"name": "username", "type": "VARCHAR(50)", "nullable": False},
            {"name": "email", "type": "VARCHAR(100)", "nullable": False},
            {"name": "password_hash", "type": "VARCHAR(255)", "nullable": False},
            {"name": "created_at", "type": "DATETIME", "nullable": False, "default": "CURRENT_TIMESTAMP"},
            {"name": "updated_at", "type": "DATETIME", "nullable": False, "default": "CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"}
        ],
        "primary_key": ["id"],
        "indexes": [
            {"columns": ["username"], "type": "UNIQUE"},
            {"columns": ["email"], "type": "UNIQUE"}
        ]
    },
    "user_profiles": {
        "columns": [
            {"name": "user_id", "type": "INT", "nullable": False},
            {"name": "first_name", "type": "VARCHAR(50)", "nullable": True},
            {"name": "last_name", "type": "VARCHAR(50)", "nullable": True},
            {"name": "avatar_url", "type": "VARCHAR(255)", "nullable": True},
            {"name": "bio", "type": "TEXT", "nullable": True}
        ],
        "primary_key": ["user_id"],
        "foreign_keys": [
            {
                "columns": ["user_id"],
                "ref_table": "users",
                "ref_columns": ["id"],
                "on_delete": "CASCADE"
            }
        ]
    }
}
