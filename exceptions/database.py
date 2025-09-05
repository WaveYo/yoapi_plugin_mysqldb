"""数据库异常模块"""

from typing import Optional


class DatabaseError(Exception):
    """数据库基础异常类"""
    
    def __init__(self, message: str, original_error: Optional[Exception] = None):
        self.message = message
        self.original_error = original_error
        super().__init__(message)


class DatabaseConnectionError(DatabaseError):
    """数据库连接错误"""
    pass


class DatabaseQueryError(DatabaseError):
    """查询执行错误"""
    pass


class DatabaseTransactionError(DatabaseError):
    """事务处理错误"""
    pass


class DatabaseMigrationError(DatabaseError):
    """迁移执行错误"""
    pass


class DatabaseConfigError(DatabaseError):
    """配置错误"""
    pass


class DatabaseTimeoutError(DatabaseError):
    """超时错误"""
    pass


class DatabaseIntegrityError(DatabaseError):
    """完整性约束错误"""
    
    def __init__(self, message: str, constraint: Optional[str] = None):
        self.constraint = constraint
        super().__init__(message)


class DatabaseNotFoundError(DatabaseError):
    """数据不存在错误"""
    pass


class DatabaseDuplicateError(DatabaseError):
    """重复数据错误"""
    
    def __init__(self, message: str, key: Optional[str] = None):
        self.key = key
        super().__init__(message)


class DatabaseLockError(DatabaseError):
    """锁等待错误"""
    pass


class DatabasePermissionError(DatabaseError):
    """权限错误"""
    pass


class DatabaseRuntimeError(DatabaseError):
    """运行时错误"""
    pass
