# 采购知识图谱智能体

基于 Neo4j 图数据库的**采购领域数据治理与元数据管理**微服务，为 AI Agent 提供 Schema 搜索、数据血缘追踪、图算法洞察等能力。

## 特性

- **Excel 注册表驱动** — 以 Excel 作为元数据唯一真实来源（SSOT），管理域、实体、属性、关系
- **Neo4j 图同步** — 将注册表 Schema 自动同步至 Neo4j，构建 Domain → Entity → Property 层次图
- **SQL 关系挖掘** — 基于 `sqlglot` 静态解析 PostgreSQL 存储过程，提取 JOIN / 数据血缘 / 表共现关系
- **图算法分析** — 集成 Neo4j GDS，支持 PageRank、Betweenness、Louvain 社区发现、节点相似度、WCC
- **Agent 工具集** — 通过 FastAPI 暴露 7 个结构化工具供 AI Agent 调用

## 架构

```
[Excel Registry] ──> RegistryLoader ──> RegistryData
       │                                      │
       │                                 RegistryValidator
       │                                      │
       ├──────────────────────────────────────┤
       │                                      │
       ▼                                      ▼
GraphBuilder.sync_all()            RelationAggregator (SQL mining)
       │                                      │
       │                                 SqlParser (sqlglot)
       ▼                                      ▼
┌────────────────────────────────────────────────────────┐
│                    Neo4j Graph DB                        │
│  Domain ──IN_DOMAIN──> Entity ──HAS_PROPERTY──> Property │
│  Property ──REFERENCES──> Property                       │
│  Column ──JOINS_WITH──> Column / DERIVES_FROM / SIMILAR  │
└────────────────────────────────────────────────────────┘
       │
       ▼
  GDS Algorithms ──> Agent Tools ──> FastAPI Service
```

## 技术栈

| 技术 | 用途 |
|---|---|
| Python 3.12+ | 运行时 |
| FastAPI | Web 服务框架 |
| Neo4j + GDS | 图数据库与图算法 |
| PostgreSQL + asyncpg | 业务数据查询 |
| sqlglot | SQL 静态解析 |
| openpyxl | Excel 注册表读写 |
| minimal-harness | Agent Tool 框架 |

## 目录结构

```
├── main.py                # 服务入口，注册 7 个工具
├── pyproject.toml          # 项目配置
├── registry/               # Excel 注册表管理（加载/校验/写入）
├── builder/                # 注册表 → Neo4j 同步
├── mining/                 # SQL 关系挖掘（sqlglot 解析）
├── analysis/               # GDS 图算法（中心性/社区/相似度）
├── tools/                  # Agent 查询工具集
│   ├── query_tools/        # Schema 搜索 / 子图 / 血缘 / 联路 / SQL
│   └── insight_tools/      # 图洞察 / 风险检查
├── scripts/                # CLI 入口（同步/导出/分析）
├── packages/               # 内部库
│   ├── neo4j-client/       # Neo4j 客户端 + Mock
│   └── pg-client/          # PostgreSQL 客户端
└── tests/                  # pytest 测试
```

## 快速开始

### 前置条件

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) 包管理器（推荐）
- Neo4j 5+（含 GDS 插件）
- PostgreSQL（可选，用于 SQL 执行工具）

### 安装

```bash
uv sync
```

### 环境变量

配置 `.env` 文件：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `A20_NEO4J_SCHEMA_URI` | Neo4j Schema 库 URI | `neo4j://localhost:7687` |
| `A20_NEO4J_SCHEMA_USER` | Neo4j 用户名 | — |
| `A20_NEO4J_SCHEMA_PASSWORD` | Neo4j 密码 | — |
| `A20_PG_URI` | PostgreSQL JDBC URI | — |
| `A20_PG_USER` | PostgreSQL 用户名 | — |
| `A20_PG_PASSWORD` | PostgreSQL 密码 | — |
| `A20_NEO4J_MOCK` | 设为 `1` 启用 Mock 模式 | — |

> 设置 `A20_NEO4J_MOCK=1` 可无需真实 Neo4j 实例进行本地开发。

### 运行

```bash
# 启动服务
python -m main

# 同步注册表到 Neo4j
python -m scripts.sync_to_graph --xlsx registry/manual_registry.xlsx

# 运行图算法分析
python -m scripts.run_analysis --algo all

# 导出注册表
python -m scripts.export_registry -i registry/manual_registry.xlsx -o registry/export.xlsx
```

### 测试

```bash
python -m pytest tests/
```

## Agent 工具

| 工具 | 说明 |
|---|---|
| `schema_search` | 按关键词搜索表和列 |
| `subgraph_fetch` | 按领域提取完整子图 |
| `lineage_trace` | 字段级数据血缘追踪 |
| `join_path_find` | 表间最短 JOIN 路径 |
| `sql_executor` | PostgreSQL 只读查询 |
| `risk_check` | 孤立外键 / 跨域引用 / 缺失主键 |
| `graph_insight` | PageRank / Louvain 社区 / 图统计 |
