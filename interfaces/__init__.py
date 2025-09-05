"""
接口模块初始化文件
导出内部公共API接口和相关功能
"""

from .internal_api import (
    DatabaseInternalAPI,
    get_internal_api,
    init_internal_api
)

__all__ = [
    'DatabaseInternalAPI',
    'get_internal_api',
    'init_internal_api'
]
