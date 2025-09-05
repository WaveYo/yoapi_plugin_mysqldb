"""
yoapi-plugin-mysqldb - MySQL 8.0+ 数据库插件
提供完整的MySQL数据库支持，包括多数据库配置、CRUD操作、事务管理和迁移功能
"""

import os
import asyncio
from typing import Dict, Any, Optional
from dotenv import load_dotenv
from fastapi import Depends

from plugins.log import get_log_service
from core.env_validator import get_env_validator, EnvVarType

# 导入内部模块
from config.settings import DatabaseConfig, DatabaseConfigManager, get_database_config_manager
from interfaces.internal_api import DatabaseInternalAPI, init_internal_api
from exceptions.database import DatabaseError

# 加载环境变量
env_path = os.path.join(os.path.dirname(__file__), '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)

# 全局数据库API实例
_db_api: Optional[DatabaseInternalAPI] = None


async def get_database_api() -> DatabaseInternalAPI:
    """
    获取数据库API实例依赖项
    
    Returns:
        DatabaseInternalAPI: 数据库内部API实例
    """
    global _db_api
    if _db_api is None:
        raise DatabaseError("数据库API未初始化")
    return _db_api


def register(app, **dependencies):
    """
    插件注册函数
    初始化数据库连接和内部API
    """
    logger = get_log_service().get_logger(__name__)
    
    try:
        # 定义环境变量模式
        env_schema = {
            "MYSQL_HOST": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL服务器主机地址"
            },
            "MYSQL_PORT": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 3306,
                "description": "MySQL服务器端口"
            },
            "MYSQL_USER": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL用户名"
            },
            "MYSQL_PASSWORD": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL密码"
            },
            "MYSQL_DATABASE": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "默认数据库名称"
            },
            "MYSQL_POOL_SIZE": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 10,
                "description": "连接池大小"
            },
            "MYSQL_MAX_OVERFLOW": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 5,
                "description": "最大溢出连接数"
            },
            "MYSQL_POOL_TIMEOUT": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 30,
                "description": "连接池超时时间（秒）"
            },
            "MYSQL_POOL_RECYCLE": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 3600,
                "description": "连接回收时间（秒）"
            }
        }
        
        # 验证环境变量
        validator = get_env_validator()
        env_vars = validator.validate_env_vars("mysqldb", env_schema)
        
        # 创建默认数据库配置
        default_config = DatabaseConfig(
            host=env_vars["MYSQL_HOST"],
            port=env_vars["MYSQL_PORT"],
            user=env_vars["MYSQL_USER"],
            password=env_vars["MYSQL_PASSWORD"],
            database=env_vars["MYSQL_DATABASE"],
            pool_size=env_vars["MYSQL_POOL_SIZE"],
            max_overflow=env_vars["MYSQL_MAX_OVERFLOW"],
            pool_timeout=env_vars["MYSQL_POOL_TIMEOUT"],
            pool_recycle=env_vars["MYSQL_POOL_RECYCLE"]
        )
        
        # 初始化配置管理器
        config_manager = DatabaseConfigManager()
        config_manager.add_config("default", default_config)
        
        # 初始化内部API
        global _db_api
        _db_api = init_internal_api(config_manager)
        
        logger.info("MySQL数据库插件已成功注册")
        logger.info(f"数据库配置: {env_vars['MYSQL_HOST']}:{env_vars['MYSQL_PORT']}/{env_vars['MYSQL_DATABASE']}")
        
        # 将数据库API添加到依赖项中
        dependencies['db_api'] = _db_api
        dependencies['db_config_manager'] = config_manager
        
    except Exception as e:
        logger.error(f"MySQL数据库插件注册失败: {e}")
        raise


async def shutdown():
    """插件关闭时的清理操作"""
    global _db_api
    if _db_api:
        await _db_api.close()
        logger = get_log_service().get_logger(__name__)
        logger.info("MySQL数据库插件已关闭，连接池已清理")
