"""数据库配置设置模块"""

import os
from typing import Dict, Any, Optional
from dataclasses import dataclass
from ..utils.env_validator import get_env_validator, EnvVarType


@dataclass
class DatabaseConfig:
    """数据库配置数据类"""
    host: str
    port: int
    user: str
    password: str
    database: str
    pool_size: int = 10
    max_overflow: int = 20
    charset: str = "utf8mb4"
    collation: str = "utf8mb4_unicode_ci"
    autocommit: bool = True
    
    @property
    def connection_url(self) -> str:
        """生成数据库连接URL"""
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}?charset={self.charset}"


class DatabaseConfigManager:
    """数据库配置管理器"""
    
    def __init__(self):
        self.validator = get_env_validator()
        self._default_config: Optional[DatabaseConfig] = None
        self._secondary_configs: Dict[str, DatabaseConfig] = {}
    
    def get_env_schema(self, prefix: str = "") -> Dict[str, Any]:
        """获取环境变量验证模式"""
        base_schema = {
            f"{prefix}HOST": {
                "type": EnvVarType.STRING,
                "required": True,
                "default": "localhost",
                "description": "MySQL数据库主机地址"
            },
            f"{prefix}PORT": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 3306,
                "min": 1,
                "max": 65535,
                "description": "MySQL数据库端口"
            },
            f"{prefix}USER": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL数据库用户名"
            },
            f"{prefix}PASSWORD": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL数据库密码"
            },
            f"{prefix}DATABASE": {
                "type": EnvVarType.STRING,
                "required": True,
                "description": "MySQL数据库名称"
            },
            f"{prefix}POOL_SIZE": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 10,
                "min": 1,
                "max": 100,
                "description": "连接池大小"
            },
            f"{prefix}MAX_OVERFLOW": {
                "type": EnvVarType.INTEGER,
                "required": False,
                "default": 20,
                "min": 0,
                "max": 100,
                "description": "最大溢出连接数"
            },
            f"{prefix}CHARSET": {
                "type": EnvVarType.STRING,
                "required": False,
                "default": "utf8mb4",
                "description": "数据库字符集"
            },
            f"{prefix}COLLATION": {
                "type": EnvVarType.STRING,
                "required": False,
                "default": "utf8mb4_unicode_ci",
                "description": "数据库排序规则"
            }
        }
        return base_schema
    
    def load_config(self, prefix: str = "MYSQL_") -> DatabaseConfig:
        """加载数据库配置"""
        env_schema = self.get_env_schema(prefix)
        env_vars = self.validator.validate_env_vars("mysqldb", env_schema)
        
        return DatabaseConfig(
            host=env_vars[f"{prefix}HOST"],
            port=env_vars[f"{prefix}PORT"],
            user=env_vars[f"{prefix}USER"],
            password=env_vars[f"{prefix}PASSWORD"],
            database=env_vars[f"{prefix}DATABASE"],
            pool_size=env_vars[f"{prefix}POOL_SIZE"],
            max_overflow=env_vars[f"{prefix}MAX_OVERFLOW"],
            charset=env_vars[f"{prefix}CHARSET"],
            collation=env_vars[f"{prefix}COLLATION"]
        )
    
    def get_default_config(self) -> DatabaseConfig:
        """获取默认数据库配置"""
        if self._default_config is None:
            self._default_config = self.load_config("MYSQL_")
        return self._default_config
    
    def get_secondary_config(self, name: str) -> DatabaseConfig:
        """获取次要数据库配置"""
        if name not in self._secondary_configs:
            prefix = f"MYSQL_{name.upper()}_"
            self._secondary_configs[name] = self.load_config(prefix)
        return self._secondary_configs[name]
    
    def get_all_configs(self) -> Dict[str, DatabaseConfig]:
        """获取所有数据库配置"""
        configs = {"default": self.get_default_config()}
        
        # 检测并加载所有次要数据库配置
        for key in os.environ:
            if key.startswith("MYSQL_") and key.endswith("_HOST") and not key.startswith("MYSQL_"):
                config_name = key.replace("MYSQL_", "").replace("_HOST", "").lower()
                if config_name != "mysql":
                    configs[config_name] = self.get_secondary_config(config_name)
        
        return configs


# 全局配置管理器实例
config_manager = DatabaseConfigManager()
