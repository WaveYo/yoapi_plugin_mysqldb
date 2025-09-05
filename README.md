# yoapi-plugin-mysqldb

WaveYo-API MySQL 8.0+ 数据库插件

## 功能特性

- 🚀 **异步高性能** - 基于aiomysql的异步MySQL 8.0+连接
- 🏗️ **模块化架构** - 分层设计，职责分离，易于扩展
- 🔧 **多数据库支持** - 支持多数据库实例路由和负载均衡
- 📊 **连接池管理** - 智能连接池，支持连接复用和健康检查
- 🗃️ **自动迁移** - 数据库表结构初始化和版本控制
- ⚡ **CRUD操作** - 完整的增删改查和事务管理
- 🔄 **读写分离** - 支持主从复制和读写分离配置
- 🛡️ **异常处理** - 14种数据库异常类型，错误处理完善
- 💻️ **性能监控** - 数据库连接和查询性能监控分析
- 📝 **查询构建器** - 灵活的查询条件构建和分页支持
- 🔌 **内部API** - 插件内部公共接口，非HTTP API

## 安装

### 1. 通过git clone安装

1. 进入插件目录克隆插件
```bash
cd <your-WaveYo-API-project>/plugins
git clone https://github.com/WaveYo/yoapi-plugin-mysqldb.git
```

2. 运行 WaveYo-API 将自动安装依赖启用插件
参考 [WaveYo-API文档](https://github.com/WaveYo/WaveYo-API?tab=readme-ov-file#1-%E4%BC%A0%E7%BB%9F%E6%96%B9%E5%BC%8F)

插件会自动被WaveYo-API核心检测和加载。


### 2. 通过yoapi-cli安装

参考[yoapi-cli 文档](https://github.com/WaveYo/yoapi-cli?tab=readme-ov-file#%E6%8F%92%E4%BB%B6%E7%AE%A1%E7%90%86)

1. 安装插件

```bash
# 在你的项目根目录下载并安装插件
yoapi plugin download WaveYo/yoapi-plugin-mysqldb

# 检查插件是否安装
yoapi plugin list
```

2. 运行 WaveYo-API 将自动安装依赖启用插件
参考 [WaveYo-API文档](https://github.com/WaveYo/WaveYo-API?tab=readme-ov-file#1-%E4%BC%A0%E7%BB%9F%E6%96%B9%E5%BC%8F)

插件会自动被WaveYo-API核心检测和加载。

## 环境变量配置

在插件目录下创建 `.env` 文件配置环境变量：

```env
# 主数据库配置（必需）
MYSQL_MASTER_HOST=localhost
MYSQL_MASTER_PORT=3306
MYSQL_MASTER_USER=root
MYSQL_MASTER_PASSWORD=your_password
MYSQL_MASTER_DATABASE=your_database

# 从数据库配置（可选，用于读写分离）
MYSQL_SLAVE_HOST=slave.localhost
MYSQL_SLAVE_PORT=3306
MYSQL_SLAVE_USER=readonly_user
MYSQL_SLAVE_PASSWORD=readonly_password
MYSQL_SLAVE_DATABASE=your_database

# 连接池配置（可选）
MYSQL_POOL_MIN_SIZE=1
MYSQL_POOL_MAX_SIZE=10
MYSQL_POOL_RECYCLE=3600
MYSQL_CONNECT_TIMEOUT=30
MYSQL_READ_TIMEOUT=30
MYSQL_WRITE_TIMEOUT=30

# 其他配置
MYSQL_AUTO_MIGRATE=true
MYSQL_MIGRATION_DIR=migrations
MYSQL_LOAD_BALANCE_STRATEGY=round_robin
```

## 内部API接口

### 获取数据库服务

```python
# 在插件中通过依赖注入获取数据库服务
def register(app, **dependencies):
    # 获取内部API接口
    db_api = dependencies.get('db_api')
    # 获取配置管理器
    db_config_manager = dependencies.get('db_config_manager')
    
    # 使用数据库服务
    result = await db_api.execute("SELECT * FROM users WHERE id = %s", (1,))
```

### 可用方法

#### 基础操作
- `execute(query: str, params: Optional[Tuple] = None) -> Any` - 执行SQL查询
- `fetch_one(query: str, params: Optional[Tuple] = None) -> Dict` - 查询单条记录
- `fetch_all(query: str, params: Optional[Tuple] = None) -> List[Dict]` - 查询所有记录
- `insert(table: str, data: Dict) -> int` - 插入数据，返回插入ID
- `update(table: str, data: Dict, where: Dict) -> int` - 更新数据，返回影响行数
- `delete(table: str, where: Dict) -> int` - 删除数据，返回影响行数

#### 事务管理
- `begin_transaction()` - 开始事务
- `commit()` - 提交事务
- `rollback()` - 回滚事务
- `transaction()` - 事务上下文管理器

#### 迁移功能
- `migrate()` - 执行数据库迁移
- `get_migration_version()` - 获取当前迁移版本
- `create_migration(name: str)` - 创建新的迁移脚本

#### 多数据库操作
- `get_connection(db_alias: Optional[str] = None)` - 获取指定数据库连接
- `switch_database(db_alias: str)` - 切换到指定数据库
- `get_available_databases()` - 获取所有可用数据库


## 使用示例

### 在其他插件中使用数据库服务

```python
from fastapi import APIRouter, Depends
from .interfaces.internal_api import DatabaseAPI

router = APIRouter()

@router.get("/users/{user_id}")
async def get_user(user_id: int, db_api: DatabaseAPI = Depends()):
    user = await db_api.fetch_one(
        "SELECT * FROM users WHERE id = %s", 
        (user_id,)
    )
    return {"user": user}

@router.post("/users")
async def create_user(user_data: dict, db_api: DatabaseAPI = Depends()):
    user_id = await db_api.insert("users", user_data)
    return {"user_id": user_id, "message": "User created successfully"}
```

### 事务操作示例

```python
async def transfer_funds(from_user: int, to_user: int, amount: float, db_api: DatabaseAPI):
    async with db_api.transaction():
        # 扣除转出用户金额
        await db_api.execute(
            "UPDATE accounts SET balance = balance - %s WHERE user_id = %s",
            (amount, from_user)
        )
        
        # 增加转入用户金额
        await db_api.execute(
            "UPDATE accounts SET balance = balance + %s WHERE user_id = %s", 
            (amount, to_user)
        )
```

### 迁移脚本示例

在 `migrations/` 目录下创建迁移文件：

```sql
-- migrations/001_initial_schema.sql
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    balance DECIMAL(10, 2) DEFAULT 0.00,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

## 开发说明

### 项目结构

```
yoapi-plugin-mysqldb/
├── config/                 # 配置管理
│   ├── __init__.py
│   └── settings.py        # 数据库配置类
├── exceptions/            # 异常处理
│   ├── __init__.py
│   └── database.py       # 14种数据库异常
├── core/                  # 核心功能
│   ├── __init__.py
│   └── connection.py     # 连接池管理
├── services/             # 服务层
│   ├── __init__.py
│   └── crud.py          # CRUD操作服务
├── features/             # 特性模块
│   ├── __init__.py
│   ├── migration.py     # 数据库迁移
│   ├── monitor.py       # 数据库监控和性能分析
│   └── router.py        # 多数据库路由
├── interfaces/           # 接口层
│   ├── __init__.py
│   └── internal_api.py  # 内部公共API
├── models/               # 数据模型
│   └── __init__.py
├── utils/                # 工具函数
│   └── __init__.py
├── __init__.py          # 主插件文件
├── requirements.txt     # 依赖声明
├── .env.example        # 环境变量示例
├── plugin.json         # 插件元数据
└── README.md           # 完整文档
```

### 异常类型

插件定义了14种数据库异常：
- `DatabaseConnectionError` - 数据库连接错误
- `DatabaseQueryError` - 查询执行错误
- `DatabaseTransactionError` - 事务处理错误
- `DatabaseMigrationError` - 迁移执行错误
- `DatabaseConfigError` - 配置错误
- `DatabaseTimeoutError` - 超时错误
- `DatabaseIntegrityError` - 完整性约束错误
- `DatabaseNotFoundError` - 数据不存在错误
- `DatabaseDuplicateError` - 重复数据错误
- `DatabaseLockError` - 锁等待错误
- `DatabasePermissionError` - 权限错误
- `DatabaseRuntimeError` - 运行时错误
- `DatabaseRouterError` - 数据库路由错误
- `NoAvailableDatabaseError` - 无可用数据库错误

### 扩展开发

要扩展插件功能，可以在相应模块中添加新功能：

1. **添加新数据库类型** - 修改 `core/connection.py`
2. **添加新查询方法** - 修改 `services/crud.py` 
3. **添加新迁移功能** - 修改 `features/migration.py`
4. **添加新路由策略** - 修改 `features/router.py`
5. **添加新API接口** - 修改 `interfaces/internal_api.py`

## 故障排除

### 常见问题

1. **连接失败**
   - 检查MySQL服务是否运行
   - 验证用户名密码是否正确
   - 确认网络连接正常

2. **权限错误**
   - 确保数据库用户有足够权限
   - 检查数据库是否存在

3. **性能问题**
   - 调整连接池大小配置
   - 优化SQL查询语句

### 调试模式

启用调试日志查看详细错误信息：

```bash
LOG_LEVEL=DEBUG python main.py
```

## 许可证

[MIT-License](LICENSE)

## 支持

如有问题，请创建Issue或联系开发团队。


---

*版本: 0.1.2*
*最后更新: 2025-09-05*
