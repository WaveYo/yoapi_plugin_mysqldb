"""简化的环境变量验证器，用于插件隔离环境"""

import os
from enum import Enum
from typing import Dict, Any, Optional


class EnvVarType(Enum):
    """环境变量类型枚举"""
    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"


class SimpleEnvValidator:
    """简化的环境变量验证器"""
    
    def validate_env_vars(self, plugin_name: str, env_schema: Dict[str, dict]) -> Dict[str, Any]:
        """
        验证插件的环境变量
        
        Args:
            plugin_name: 插件名称
            env_schema: 环境变量模式定义
            
        Returns:
            验证后的环境变量字典
        """
        validated_vars = {}
        
        for var_name, var_config in env_schema.items():
            value = os.getenv(var_name)
            
            # 如果变量未设置但有默认值，使用默认值
            if value is None and 'default' in var_config:
                value = var_config['default']
            
            # 检查必需变量
            if var_config.get('required', False) and value is None:
                raise ValueError(f"必需环境变量 {var_name} 未设置")
            
            # 如果变量为None，跳过验证
            if value is None:
                continue
            
            # 验证变量类型
            var_type = var_config.get('type', EnvVarType.STRING)
            
            try:
                if var_type == EnvVarType.STRING:
                    validated_value = self._validate_string(value, var_config)
                elif var_type == EnvVarType.INTEGER:
                    validated_value = self._validate_integer(value, var_config)
                elif var_type == EnvVarType.FLOAT:
                    validated_value = self._validate_float(value, var_config)
                elif var_type == EnvVarType.BOOLEAN:
                    validated_value = self._validate_boolean(value, var_config)
                else:
                    validated_value = value
                
                validated_vars[var_name] = validated_value
            except ValueError as e:
                raise ValueError(f"环境变量 {var_name} 验证失败: {e}")
        
        return validated_vars
    
    def _validate_string(self, value: str, config: dict) -> str:
        """验证字符串类型环境变量"""
        if not isinstance(value, str):
            raise ValueError(f"应为字符串类型，实际为 {type(value).__name__}")
        
        # 检查枚举值
        if 'enum' in config and value not in config['enum']:
            raise ValueError(f"值 '{value}' 不在允许的枚举值中: {config['enum']}")
        
        return value
    
    def _validate_integer(self, value: str, config: dict) -> int:
        """验证整数类型环境变量"""
        try:
            int_value = int(value)
        except ValueError:
            raise ValueError(f"无法转换为整数: '{value}'")
        
        # 检查最小/最大值
        min_val = config.get('min')
        max_val = config.get('max')
        
        if min_val is not None and int_value < min_val:
            raise ValueError(f"值不能小于 {min_val}")
        
        if max_val is not None and int_value > max_val:
            raise ValueError(f"值不能大于 {max_val}")
        
        return int_value
    
    def _validate_float(self, value: str, config: dict) -> float:
        """验证浮点数类型环境变量"""
        try:
            float_value = float(value)
        except ValueError:
            raise ValueError(f"无法转换为浮点数: '{value}'")
        
        # 检查最小/最大值
        min_val = config.get('min')
        max_val = config.get('max')
        
        if min_val is not None and float_value < min_val:
            raise ValueError(f"值不能小于 {min_val}")
        
        if max_val is not None and float_value > max_val:
            raise ValueError(f"值不能大于 {max_val}")
        
        return float_value
    
    def _validate_boolean(self, value: str, config: dict) -> bool:
        """验证布尔类型环境变量"""
        value_lower = value.lower()
        if value_lower in ('true', '1', 'yes', 'on'):
            return True
        elif value_lower in ('false', '0', 'no', 'off'):
            return False
        else:
            raise ValueError(f"无法转换为布尔值: '{value}'")


# 全局验证器实例
_env_validator = SimpleEnvValidator()


def get_env_validator() -> SimpleEnvValidator:
    """获取环境变量验证器实例"""
    return _env_validator
