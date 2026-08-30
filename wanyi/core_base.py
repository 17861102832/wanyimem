#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║        万 忆 中 枢 · 核 心 底 座 (core_base)                 ║
║                                                               ║
║  这不是一个记忆插件。                                            ║
║  这是给 Agent 装的第二个大脑。                                    ║
║                                                               ║
║  你教它一次，它永远记得。                                        ║
║  它犯错一次，它自己学会反思。                                    ║
║  你换一万次对话，它的记忆永不丢失。                                ║
║                                                               ║
║  架构：事件溯源 + 三路混合检索 + 知识图谱 + 睡眠巩固衰减           ║
║  模块：core_base(本文件·数据层) / engine(引擎+23工具)            ║
║        / transport(MCP标准stdio) — 1.1.0 自 memory_core 拆分    ║
║  存储：SQLite 单文件（FTS5 + 向量 + 图谱 + 事件日志）             ║
║  层级：道(原则) / 法(模式) / 术(原始) 三层全量记忆                ║
║  空间：项目级 / 个人级 / 全局级 三级记忆隔离                       ║
║  隐私：四级隐私分级（公开/内部/机密/绝密）                         ║
╚══════════════════════════════════════════════════════════════════╝
"""
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from env_compat import get_env  # v1.1：中文优先/英文兜底

# ═══════════════════════════════════════════════════════════════════
# 环境变量与路径配置
# ═══════════════════════════════════════════════════════════════════
STORE_DIR = Path(get_env("万忆中枢_STORE_DIR", "WANYI_STORE_DIR",
    os.path.join(os.path.dirname(__file__), "memory")))
DB_PATH = Path(get_env("万忆中枢_MEMORY_DB", "WANYI_MEMORY_DB",
    os.path.join(STORE_DIR, "db", "万忆.db")))
USER_PROFILE = get_env("万忆中枢_USER_PROFILE", "WANYI_USER_PROFILE", "")
TRADING_ANCHOR = get_env("万忆中枢_TRADING_ANCHOR", "WANYI_TRADING_ANCHOR", "")
INDEX_PATH = Path(get_env("万忆中枢_INDEX", "WANYI_INDEX",
    os.path.join(os.path.dirname(__file__), "index.json")))
OBSIDIAN_VAULT = Path(get_env("OBSIDIAN_VAULT", "OBSIDIAN_VAULT", "").strip()) if get_env("OBSIDIAN_VAULT", "OBSIDIAN_VAULT", "").strip() else None
SESSION_ID = os.environ.get("TRAECN_SESSION_ID", "unknown")
EVENT_LOG_DIR = STORE_DIR / "event_logs"

# 三层记忆层级
LAYER_DAO = "道"   # 原则、偏好、决策哲学 — 每会话自动注入
LAYER_FA = "法"    # 模式、策略、方法论 — 条件注入
LAYER_SHU = "术"   # 原始观察、具体事实 — 按需召回

# 三级记忆空间
SPACE_PROJECT = "项目级"   # 具体项目上下文
SPACE_PERSONAL = "个人级"  # 用户偏好、习惯
SPACE_GLOBAL = "全局级"    # 通用知识、跨项目

# 四级隐私分级
PRIVACY_PUBLIC = "公开"
PRIVACY_INTERNAL = "内部"
PRIVACY_CONFIDENTIAL = "机密"
PRIVACY_TOP_SECRET = "绝密"

# 记忆类型（借鉴 Engram 认知科学分类 + 咱们的道法术）
MEMORY_TYPES = {
    "decision":   {"layer": LAYER_DAO, "decay_halflife_days": 0,   "pin": True,  "name": "决策"},
    "preference": {"layer": LAYER_DAO, "decay_halflife_days": 0,   "pin": True,  "name": "偏好"},
    "principle":  {"layer": LAYER_DAO, "decay_halflife_days": 0,   "pin": True,  "name": "原则"},
    "pattern":    {"layer": LAYER_FA,  "decay_halflife_days": 60,  "pin": False, "name": "模式"},
    "strategy":   {"layer": LAYER_FA,  "decay_halflife_days": 90,  "pin": False, "name": "策略"},
    "concept":    {"layer": LAYER_FA,  "decay_halflife_days": 120, "pin": False, "name": "概念"},
    "fact":       {"layer": LAYER_SHU, "decay_halflife_days": 30,  "pin": False, "name": "事实"},
    "observation":{"layer": LAYER_SHU, "decay_halflife_days": 15,  "pin": False, "name": "观察"},
    "event":      {"layer": LAYER_SHU, "decay_halflife_days": 7,   "pin": False, "name": "事件"},
}

# 四因子检索权重（借鉴 MemX 四因子模型）
RETRIEVAL_WEIGHTS = {
    "semantic":   0.45,   # 语义相似度
    "recency":    0.25,   # 近因（时间接近度）
    "frequency":  0.10,   # 频率（访问次数）
    "importance": 0.20,   # 重要性（层+类型+pin）
}


# ═══════════════════════════════════════════════════════════════════
# 目录初始化
# ═══════════════════════════════════════════════════════════════════
def init_dirs():
    for sub in ["db", "event_logs", "compressed", "sleep_consolidation"]:
        (STORE_DIR / sub).mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════
def gen_memory_id(layer: str, content: str) -> str:
    prefix = layer[0] if layer else "M"
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    t = int(time.time())
    return f"{prefix}_{t}_{h}"

def gen_task_checkpoint_id(task_name: str, phase: str) -> str:
    t = int(time.time())
    return f"CKPT_{task_name[:20]}_{phase[:10]}_{t}"

def now_iso() -> str:
    return datetime.now().isoformat()

def safe_json_loads(s, default=None):
    if not s:
        return default if default is not None else {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else {}


# ═══════════════════════════════════════════════════════════════════
# 简单中文分词（用于 FTS5 关键词搜索的查询预处理）
# ═══════════════════════════════════════════════════════════════════
_CJK_RE = re.compile(r'[\u4e00-\u9fff]+')
_EN_RE = re.compile(r'[a-zA-Z0-9_]+')

def tokenize_cn(text: str) -> list[str]:
    """极简中文分词：2-4字滑动窗口 + 英文数字整词"""
    tokens = []
    # 英文/数字整词
    for m in _EN_RE.finditer(text):
        w = m.group()
        if len(w) >= 2:
            tokens.append(w.lower())
    # 中文 2-3-4字滑窗（模拟 n-gram，配合 SQLite FTS 的 unicode61 tokenizer）
    for m in _CJK_RE.finditer(text):
        s = m.group()
        if len(s) >= 2:
            for i in range(len(s) - 1):
                tokens.append(s[i:i+2])
            if len(s) >= 3:
                for i in range(len(s) - 2):
                    tokens.append(s[i:i+3])
    return tokens


# ═══════════════════════════════════════════════════════════════════
# 记忆评分：四因子模型（借鉴 MemX + KektorDB）
# ═══════════════════════════════════════════════════════════════════
def calc_recency_factor(last_accessed: str, halflife_days: float) -> float:
    """指数衰减近因因子：2^(-days/halflife)，halflife=0 表示永不衰减"""
    if halflife_days == 0:
        return 1.0
    if not last_accessed:
        return 0.5
    try:
        last = datetime.fromisoformat(last_accessed)
    except (ValueError, TypeError):
        return 0.5
    days = (datetime.now() - last).total_seconds() / 86400.0
    if days < 0:
        return 1.0
    return 2.0 ** (-days / halflife_days)

def calc_frequency_factor(access_count: int) -> float:
    """对数归一化频率因子：min(1, ln(count+1)/5)"""
    if access_count <= 0:
        return 0.0
    return min(1.0, math.log(access_count + 1) / 5.0)

def calc_importance_factor(layer: str, mem_type: str, pinned: bool) -> float:
    """重要性因子：层级 + 类型 + pin 状态"""
    if pinned:
        return 1.0
    layer_score = {LAYER_DAO: 1.0, LAYER_FA: 0.7, LAYER_SHU: 0.4}.get(layer, 0.3)
    type_info = MEMORY_TYPES.get(mem_type, {})
    type_bonus = 0.2 if type_info.get("pin") else 0.0
    return min(1.0, layer_score + type_bonus)

def calc_composite_score(semantic: float, recency: float,
                         frequency: float, importance: float,
                         weights: dict = None) -> float:
    """四因子复合评分（z-score 简化版，直接加权求和）"""
    w = weights or RETRIEVAL_WEIGHTS
    total = (w["semantic"] * semantic +
             w["recency"] * recency +
             w["frequency"] * frequency +
             w["importance"] * importance)
    return total


# ═══════════════════════════════════════════════════════════════════
# 数据库引擎
# ═══════════════════════════════════════════════════════════════════
class MemoryDB:
    """
    万忆中枢数据库引擎
    - 主记忆表 memories（道法术三层 + 事件溯源）
    - FTS5 全文索引
    - 知识图谱（节点 + 边）
    - 会话事件日志
    - 任务检查点
    - 压缩快照
    """

    def __init__(self, db_path: Path):
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()
        self._migrate_schema()  # 自动迁移旧版数据库
        self._init_fts()
        self._init_graph()

    def _init_schema(self):
        """建所有表（不含索引，索引在迁移后统一建）"""
        cur = self.conn.cursor()
        cur.executescript("""
            -- 主记忆表（事件溯源式 append-only，通过 version 区分版本）
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT UNIQUE NOT NULL,
                content TEXT NOT NULL,
                layer TEXT NOT NULL DEFAULT '术',
                category TEXT,
                source TEXT,
                tags TEXT DEFAULT '[]',
                confidence REAL DEFAULT 0.7,
                created_at TEXT,
                updated_at TEXT,
                duplicate_hash TEXT,
                metadata TEXT DEFAULT '{}',
                session_id TEXT,
                task_id TEXT
            );

            -- 会话事件日志（append-only 事件溯源）
            CREATE TABLE IF NOT EXISTS session_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                event_type TEXT,
                event_data TEXT DEFAULT '{}',
                timestamp TEXT
            );

            -- 任务检查点
            CREATE TABLE IF NOT EXISTS task_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_id TEXT UNIQUE NOT NULL,
                task_name TEXT,
                phase TEXT,
                progress_pct REAL DEFAULT 0,
                state TEXT DEFAULT '{}',
                created_at TEXT,
                session_id TEXT
            );

            -- 压缩快照
            CREATE TABLE IF NOT EXISTS compression_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                layer TEXT,
                source_count INTEGER,
                compressed_count INTEGER,
                summary TEXT,
                created_at TEXT
            );

            -- 记忆索引（关键词倒排加速）
            CREATE TABLE IF NOT EXISTS memory_index (
                keyword TEXT,
                memory_id TEXT,
                tf REAL DEFAULT 1.0,
                PRIMARY KEY(keyword, memory_id)
            );

            -- ═══ v4 新增：过程记忆（ExpeL 式轨迹分段） ═══
            -- 一个长程任务的完整思考轨迹，按阶段分段存储，可恢复可回看
            CREATE TABLE IF NOT EXISTS process_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_id TEXT NOT NULL,
                task_name TEXT,
                phase TEXT NOT NULL,
                phase_seq INTEGER DEFAULT 0,
                content TEXT NOT NULL,
                outcome TEXT DEFAULT 'neutral',
                anchor TEXT,
                metadata TEXT DEFAULT '{}',
                timestamp TEXT,
                session_id TEXT
            );

            -- ═══ v4 新增：错题本（Reflexion/reflect 式） ═══
            CREATE TABLE IF NOT EXISTS mistakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mistake_id TEXT UNIQUE NOT NULL,
                task_name TEXT,
                content TEXT NOT NULL,
                lesson TEXT,
                pattern TEXT,
                pattern_count INTEGER DEFAULT 1,
                confidence REAL DEFAULT 0.5,
                status TEXT DEFAULT 'open',
                tags TEXT DEFAULT '[]',
                ref_process_id TEXT,
                created_at TEXT,
                updated_at TEXT,
                session_id TEXT
            );

            -- ═══ v4 新增：经验库（ExpeL 式提炼） ═══
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experience_id TEXT UNIQUE NOT NULL,
                task_name TEXT,
                content TEXT NOT NULL,
                mem_type TEXT DEFAULT 'pattern',
                layer TEXT DEFAULT '法',
                confidence REAL DEFAULT 0.5,
                source_count INTEGER DEFAULT 1,
                tags TEXT DEFAULT '[]',
                ref_process_ids TEXT DEFAULT '[]',
                created_at TEXT,
                updated_at TEXT,
                session_id TEXT
            );

            -- ═══ v4 新增：认知置信度（KektorDB 三分量） ═══
            CREATE TABLE IF NOT EXISTS confidence (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                consensus REAL DEFAULT 0.5,
                stability REAL DEFAULT 0.5,
                friction REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.5,
                validations INTEGER DEFAULT 0,
                contradictions INTEGER DEFAULT 0,
                last_updated TEXT,
                metadata TEXT DEFAULT '{}',
                UNIQUE(target_type, target_id)
            );

            -- ═══ v4.2 新增：反事实之镜（护城河#2） ═══════════════════
            -- 每个决策点开两条平行分支：fact(实际选的) / counter(反事实)
            -- 到期结算对比，把"如果当时听劝"的教训写进错题本/经验库
            CREATE TABLE IF NOT EXISTS counterfactual_branches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                branch_id TEXT UNIQUE NOT NULL,           -- 分支对ID（两个分支共享）
                decision_text TEXT NOT NULL,              -- 决策点描述
                decision_type TEXT DEFAULT 'trade',       -- trade/write/code/other
                risk_level TEXT DEFAULT 'medium',         -- critical/high/medium/low
                fact_path TEXT NOT NULL,                  -- 事实路径：taken(实际做了)/avoided(实际没做)
                counter_path TEXT NOT NULL,               -- 反事实路径描述
                fact_outcome TEXT,                        -- 事实结果（settle时填）
                counter_outcome TEXT,                     -- 反事实结果（settle时推算）
                verdict TEXT DEFAULT 'open',              -- open/fact_won/counter_won/neutral
                settlement_date TEXT,                     -- 预定结算日期
                settled_at TEXT,                          -- 实际结算时间
                confidence_target_id TEXT,                -- 关联置信度check的target_id
                tags TEXT DEFAULT '[]',                   -- JSON数组
                lesson_learned TEXT,                      -- 结算后提炼的教训
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_cf_branch ON counterfactual_branches(branch_id);
            CREATE INDEX IF NOT EXISTS idx_cf_settlement ON counterfactual_branches(settlement_date, verdict);

            -- ═══ v4.3 新增：跨域类比迁移（护城河#3） ═══════════════════
            -- 把不同领域踩坑/成功的底层模式抽象成跨域模式，
            -- 交易/写作/开发之间互相桥接："这个模式你在另一个领域也踩过"
            CREATE TABLE IF NOT EXISTS analog_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_id TEXT UNIQUE NOT NULL,          -- ap_xxxx
                abstract_name TEXT NOT NULL,              -- 模式名（如"无视止损纪律"）
                essence TEXT NOT NULL,                    -- 底层本质描述（跨域通用）
                domains TEXT DEFAULT '[]',                -- JSON数组：覆盖领域 trade/write/code/other
                keywords TEXT DEFAULT '[]',               -- JSON数组：触发关键词
                source_refs TEXT DEFAULT '[]',            -- JSON数组：来源记忆/分支ID
                hit_count INTEGER DEFAULT 0,              -- 被桥接命中次数
                confidence REAL DEFAULT 0.7,              -- 模式置信度
                tags TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ap_pattern ON analog_patterns(pattern_id);
            CREATE INDEX IF NOT EXISTS idx_ap_hit ON analog_patterns(hit_count DESC);

            -- ═══ v5.1 新增：元认知知识空白（知道自己不知道什么） ═══════
            -- 召回太弱时自动记录"这块知识库存薄弱"，可主动补充
            CREATE TABLE IF NOT EXISTS knowledge_gaps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gap_id TEXT UNIQUE NOT NULL,              -- gap_xxxx
                query_text TEXT NOT NULL,                 -- 没搜到的查询
                weak_hit INTEGER DEFAULT 0,               -- 1=有结果但分低, 0=完全没结果
                hit_count INTEGER DEFAULT 1,              -- 被查中次数（越查越该补）
                status TEXT DEFAULT 'open',               -- open(待补)/closed(已补)
                filled_by TEXT,                           -- 补充来源（记忆ID/说明）
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                session_id TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_gap_status ON knowledge_gaps(status, hit_count DESC);
        """)
        self.conn.commit()

    def _migrate_schema(self):
        """自动迁移旧版数据库到 v3 schema（幂等安全）"""
        cur = self.conn.cursor()

        # 获取 memories 表现有列
        existing_cols = set(
            r["name"] for r in cur.execute("PRAGMA table_info(memories)").fetchall()
        )

        # v3 需要的列及默认值（老库没有就补上）
        v3_columns = {
            "mem_type": "TEXT DEFAULT 'observation'",
            "space": "TEXT DEFAULT '全局级'",
            "project": "TEXT",
            "privacy": "TEXT DEFAULT '内部'",
            "importance": "REAL DEFAULT 0.5",
            "pinned": "INTEGER DEFAULT 0",
            "version": "INTEGER DEFAULT 1",
            "last_accessed_at": "TEXT",
            "access_count": "INTEGER DEFAULT 0",
            "retrieval_count": "INTEGER DEFAULT 0",
        }

        added = []
        for col, definition in v3_columns.items():
            if col not in existing_cols:
                cur.execute(f"ALTER TABLE memories ADD COLUMN {col} {definition}")
                added.append(col)

        # 旧数据补全：给所有旧记忆设合理默认值（按 layer 推断类型和重要性）
        if added:
            # 给旧记忆分配 mem_type（根据 layer 推断）
            cur.execute("UPDATE memories SET mem_type = 'principle' WHERE layer = '道'")
            cur.execute("UPDATE memories SET mem_type = 'pattern' WHERE layer = '法'")
            # 术级保持 observation 默认值

            # 给旧记忆计算 importance
            cur.execute("""
                UPDATE memories SET importance = CASE
                    WHEN layer = '道' THEN 0.9
                    WHEN layer = '法' THEN 0.7
                    ELSE 0.5
                END
            """)

            # 给旧记忆钉住：道级 + postmortem 类型
            cur.execute("UPDATE memories SET pinned = 1 WHERE layer = '道'")
            cur.execute("UPDATE memories SET pinned = 1 WHERE mem_type = 'postmortem'")

        # memory_index 表迁移：旧版可能缺 tf 列
        mi_cols = set(
            r["name"] for r in cur.execute("PRAGMA table_info(memory_index)").fetchall()
        )
        if "tf" not in mi_cols:
            cur.execute("ALTER TABLE memory_index ADD COLUMN tf REAL DEFAULT 1.0")

        # 旧数据补全后再重建关键词索引
        if added or "tf" not in mi_cols:
            self._rebuild_keyword_index()

        # 统一建索引（在列都补齐后）
        index_stmts = [
            "CREATE INDEX IF NOT EXISTS idx_memories_layer ON memories(layer)",
            "CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(mem_type)",
            "CREATE INDEX IF NOT EXISTS idx_memories_space ON memories(space)",
            "CREATE INDEX IF NOT EXISTS idx_memories_privacy ON memories(privacy)",
            "CREATE INDEX IF NOT EXISTS idx_memories_pinned ON memories(pinned)",
            "CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_session ON session_events(session_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_type ON session_events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_events_time ON session_events(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_ckpt_task ON task_checkpoints(task_name)",
            # v4 新增索引
            "CREATE INDEX IF NOT EXISTS idx_proc_pid ON process_events(process_id)",
            "CREATE INDEX IF NOT EXISTS idx_proc_task ON process_events(task_name)",
            "CREATE INDEX IF NOT EXISTS idx_proc_time ON process_events(timestamp)",
            "CREATE INDEX IF NOT EXISTS idx_mistake_pattern ON mistakes(pattern)",
            "CREATE INDEX IF NOT EXISTS idx_mistake_task ON mistakes(task_name)",
            "CREATE INDEX IF NOT EXISTS idx_exp_task ON experiences(task_name)",
            "CREATE INDEX IF NOT EXISTS idx_exp_layer ON experiences(layer)",
            "CREATE INDEX IF NOT EXISTS idx_conf_target ON confidence(target_type, target_id)",
        ]
        for stmt in index_stmts:
            try:
                cur.execute(stmt)
            except Exception:
                pass  # 索引已存在就跳过

        # ═══ v4：session_events 升级为 L0 真相源（补 scope 列） ═══
        ev_cols = set(
            r["name"] for r in cur.execute("PRAGMA table_info(session_events)").fetchall()
        )
        if "scope" not in ev_cols:
            cur.execute("ALTER TABLE session_events ADD COLUMN scope TEXT DEFAULT '对话'")
            cur.execute("ALTER TABLE session_events ADD COLUMN event_seq INTEGER DEFAULT 0")

        self.conn.commit()
        if added:
            # v4.6.1 修复：MCP server 的 stdout 必须纯净，日志改走 stderr
            sys.stderr.write(f"[万忆中枢] 数据库迁移完成，新增列: {', '.join(added)}\n")
            sys.stderr.flush()

    def _rebuild_keyword_index(self):
        """重建关键词倒排索引（用于迁移旧数据）"""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM memory_index")
        rows = cur.execute("SELECT memory_id, content FROM memories").fetchall()
        for row in rows:
            self._update_keyword_index(row["memory_id"], row["content"])

    def _init_fts(self):
        """初始化 FTS5 全文索引（BM25 关键词搜索）"""
        cur = self.conn.cursor()
        # 使用 unicode61 tokenizer 支持中文
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS fts_memories USING fts5(
                content,
                content='memories',
                content_rowid='id',
                tokenize = 'unicode61 remove_diacritics 0'
            )
        """)
        # 触发器：保持 FTS 与主表同步
        cur.executescript("""
            CREATE TRIGGER IF NOT EXISTS trg_memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO fts_memories(rowid, content) VALUES (new.id, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS trg_memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO fts_memories(fts_memories, rowid, content) VALUES('delete', old.id, old.content);
            END;
            CREATE TRIGGER IF NOT EXISTS trg_memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO fts_memories(fts_memories, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO fts_memories(rowid, content) VALUES (new.id, new.content);
            END;
        """)
        self.conn.commit()

    def _init_graph(self):
        """初始化知识图谱（SQLite 三表模式）"""
        cur = self.conn.cursor()
        cur.executescript("""
            -- 图谱节点（实体/概念）
            CREATE TABLE IF NOT EXISTS graph_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                node_type TEXT DEFAULT 'concept',
                description TEXT,
                layer TEXT DEFAULT '法',
                space TEXT DEFAULT '全局级',
                importance REAL DEFAULT 0.5,
                created_at TEXT,
                updated_at TEXT,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON graph_nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_name ON graph_nodes(name);

            -- 图谱边（关系）
            CREATE TABLE IF NOT EXISTS graph_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                edge_id TEXT UNIQUE NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                confidence REAL DEFAULT 0.7,
                created_at TEXT,
                metadata TEXT DEFAULT '{}',
                FOREIGN KEY(source_id) REFERENCES graph_nodes(node_id),
                FOREIGN KEY(target_id) REFERENCES graph_nodes(node_id)
            );
            CREATE INDEX IF NOT EXISTS idx_edges_src ON graph_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_tgt ON graph_edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_rel ON graph_edges(relation);

            -- 记忆-节点关联（记忆中提到了哪些实体）
            CREATE TABLE IF NOT EXISTS memory_node_links (
                memory_id TEXT,
                node_id TEXT,
                weight REAL DEFAULT 0.8,
                PRIMARY KEY(memory_id, node_id)
            );
        """)
        self.conn.commit()

    # ── 记忆读写 ────────────────────────────────────────────────────

    def upsert_memory(self, content: str, layer: str = LAYER_SHU,
                      mem_type: str = "observation",
                      category: str | None = None,
                      space: str = SPACE_GLOBAL,
                      project: str | None = None,
                      privacy: str = PRIVACY_INTERNAL,
                      source: str | None = None,
                      tags: list[str] | None = None,
                      confidence: float = 0.7,
                      importance: float | None = None,
                      pinned: bool = False,
                      memory_id: str | None = None,
                      session_id: str | None = None,
                      task_id: str | None = None,
                      metadata: dict | None = None) -> dict:
        """
        写入或更新一条记忆。
        如果 memory_id 已存在则版本+1（事件溯源，旧版本不删除）。
        """
        now = now_iso()
        if not memory_id:
            memory_id = gen_memory_id(layer, content)

        type_info = MEMORY_TYPES.get(mem_type, {})
        auto_layer = type_info.get("layer", layer)
        actual_layer = layer if layer != LAYER_SHU or mem_type == "observation" else auto_layer
        actual_pinned = 1 if (pinned or type_info.get("pin", False)) else 0

        if importance is None:
            importance = calc_importance_factor(actual_layer, mem_type, bool(actual_pinned))

        tags_str = json.dumps(tags or [], ensure_ascii=False)
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)
        dup_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

        existing = self.conn.execute(
            "SELECT memory_id, version FROM memories WHERE memory_id = ?",
            (memory_id,)
        ).fetchone()

        if existing:
            # 版本+1（事件溯源：保留历史，最新版本 active）
            new_version = existing["version"] + 1
            self.conn.execute("""
                UPDATE memories SET content=?, layer=?, mem_type=?, category=?,
                space=?, project=?, privacy=?, source=?, tags=?, importance=?,
                pinned=?, confidence=?, version=?, updated_at=?,
                metadata=?, session_id=?, task_id=?, duplicate_hash=?
                WHERE memory_id=?
            """, (content, actual_layer, mem_type, category, space, project,
                  privacy, source, tags_str, importance, actual_pinned, confidence,
                  new_version, now, meta_str, session_id, task_id, dup_hash, memory_id))
            status = "updated"
        else:
            self.conn.execute("""
                INSERT INTO memories (memory_id, content, layer, mem_type, category,
                space, project, privacy, source, tags, importance, pinned, confidence,
                created_at, updated_at, metadata, session_id, task_id, duplicate_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (memory_id, content, actual_layer, mem_type, category, space, project,
                  privacy, source, tags_str, importance, actual_pinned, confidence,
                  now, now, meta_str, session_id, task_id, dup_hash))
            status = "inserted"

        # 更新关键词索引
        self._update_keyword_index(memory_id, content)

        # ═══ v4：写入口分级路由 + L0 真相源 ═══
        # 全量落库（无拒收），只做分级路由和暴露控制
        route_scope = "对话"
        if actual_layer == LAYER_DAO:
            route_scope = "决策" if mem_type in ("decision", "preference") else "进化"
        elif actual_layer == LAYER_FA:
            route_scope = "进化"
        elif mem_type in ("observation", "event"):
            route_scope = "过程"
        elif source in ("correction", "纠错", "mistake"):
            route_scope = "纠错"

        # 写 L0 事件日志（append-only 真相源）
        self.log_event(
            session_id=session_id or SESSION_ID,
            event_type=f"memory_{status}",
            event_data={
                "memory_id": memory_id,
                "layer": actual_layer,
                "mem_type": mem_type,
                "importance": importance,
                "pinned": actual_pinned,
                "category": category,
                "project": project,
                "space": space,
                "tags": tags or [],
            },
            scope=route_scope
        )

        self.conn.commit()

        # ═══ v5.1：写入后同步到语义向量库（模型不可用时自动跳过） ═══
        try:
            if hasattr(self, "vector_store") and self.vector_store is not None:
                self.vector_store.store(memory_id, content)
        except Exception:
            pass

        # ═══ v5.3：写入后自动建图边（语义相似+同层同类，轻量防爆炸） ═══
        try:
            self.auto_graph_link(memory_id, content, actual_layer, category)
        except Exception:
            pass

        return {"status": status, "memory_id": memory_id, "layer": actual_layer,
                "routed_scope": route_scope}

    def _update_keyword_index(self, memory_id: str, content: str):
        """更新关键词倒排索引（用于快速关键词匹配和图谱实体发现）"""
        self.conn.execute("DELETE FROM memory_index WHERE memory_id = ?", (memory_id,))
        tokens = tokenize_cn(content)
        freq = {}
        for t in tokens:
            freq[t] = freq.get(t, 0) + 1
        if not freq:
            return
        max_freq = max(freq.values())
        rows = []
        for kw, count in freq.items():
            if len(kw) >= 2:
                tf = 0.5 + 0.5 * count / max_freq
                rows.append((kw, memory_id, tf))
        if rows:
            self.conn.executemany(
                "INSERT OR IGNORE INTO memory_index(keyword, memory_id, tf) VALUES (?, ?, ?)",
                rows
            )

    def get_memory(self, memory_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM memories WHERE memory_id = ?", (memory_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def recall(self, query: str, layer: str = "all",
               space: str = None, project: str = None,
               privacy_max: str = PRIVACY_TOP_SECRET,
               limit: int = 20, min_confidence: float = 0.3) -> list[dict]:
        """
        三路混合检索：FTS5(BM25) 关键词 + 关键词倒排 + 四因子重排
        返回 Top-K 相关记忆
        """
        # 隐私分级过滤阈值
        privacy_levels = [PRIVACY_PUBLIC, PRIVACY_INTERNAL, PRIVACY_CONFIDENTIAL, PRIVACY_TOP_SECRET]
        max_idx = privacy_levels.index(privacy_max) if privacy_max in privacy_levels else 3
        allowed_privacy = privacy_levels[:max_idx + 1]

        # 通道 1: FTS5 BM25 关键词搜索
        fts_results = {}
        try:
            # 构造 FTS 查询（用 AND 连接关键词，支持中文 2-gram 匹配）
            fts_query = self._build_fts_query(query)
            if fts_query:
                rows = self.conn.execute(f"""
                    SELECT m.memory_id, fts.rank as bm25_rank,
                           m.content, m.layer, m.mem_type, m.category,
                           m.space, m.project, m.privacy, m.importance,
                           m.pinned, m.tags, m.confidence, m.updated_at,
                           m.last_accessed_at, m.access_count, m.retrieval_count
                    FROM fts_memories fts
                    JOIN memories m ON m.id = fts.rowid
                    WHERE fts_memories MATCH ?
                      AND m.privacy IN ({','.join('?'*len(allowed_privacy))})
                    ORDER BY bm25_rank
                    LIMIT 50
                """, [fts_query] + allowed_privacy).fetchall()
                for rank, row in enumerate(rows, 1):
                    mid = row["memory_id"]
                    fts_results[mid] = {
                        "row": self._row_to_dict(row),
                        "fts_rank": rank,
                        "fts_score": 1.0 / (60 + rank)  # RRF 分数
                    }
        except Exception:
            pass  # FTS 失败时回退到倒排

        # 通道 2: 关键词倒排索引（FTS 不中时的补充）
        kw_results = {}
        if not fts_results or len(fts_results) < 5:
            keywords = tokenize_cn(query)
            if keywords:
                placeholders = ",".join("?" * min(len(keywords), 20))
                rows = self.conn.execute(f"""
                    SELECT mi.memory_id, SUM(mi.tf) as total_tf,
                           m.content, m.layer, m.mem_type, m.category,
                           m.space, m.project, m.privacy, m.importance,
                           m.pinned, m.tags, m.confidence, m.updated_at,
                           m.last_accessed_at, m.access_count, m.retrieval_count
                    FROM memory_index mi
                    JOIN memories m ON m.memory_id = mi.memory_id
                    WHERE mi.keyword IN ({placeholders})
                      AND m.privacy IN ({','.join('?'*len(allowed_privacy))})
                    GROUP BY mi.memory_id
                    ORDER BY total_tf DESC
                    LIMIT 50
                """, keywords[:20] + allowed_privacy).fetchall()
                for rank, row in enumerate(rows, 1):
                    mid = row["memory_id"]
                    kw_results[mid] = {
                        "row": self._row_to_dict(row),
                        "kw_rank": rank,
                        "kw_score": 1.0 / (60 + rank)
                    }

        # 合并两通道结果（RRF 融合）
        all_ids = set(fts_results.keys()) | set(kw_results.keys())
        if not all_ids:
            # 无任何关键词命中。
            # v1.1：区分「空查询」与「无匹配的非空查询」——
            #   - 空查询（如 hook_load 道/法级注入）→ 按时间倒序返回最近记忆（_fallback，供注入）
            #   - 非空查询却无匹配 → 诚实返回空，触发知识空白（绝不硬凑答案）
            if query.strip():
                return []
            extra_where = []
            extra_params = []
            if layer and layer != "all":
                extra_where.append("layer = ?")
                extra_params.append(layer)
            if space:
                extra_where.append("space = ?")
                extra_params.append(space)
            if project:
                extra_where.append("project = ?")
                extra_params.append(project)
            where_clause = (" AND " + " AND ".join(extra_where)) if extra_where else ""
            rows = self.conn.execute(f"""
                SELECT * FROM memories
                WHERE privacy IN ({','.join('?'*len(allowed_privacy))})
                {where_clause}
                ORDER BY updated_at DESC LIMIT ?
            """, allowed_privacy + extra_params + [limit]).fetchall()
            # v5.4：兜底记忆标记低相关（防止误当相关召回，也让知识空白检测生效）
            out = []
            for r in rows:
                d = self._row_to_dict(r)
                # v1.1：空查询兜底路径按 min_confidence 过滤（hook_load 道/法级注入意图）
                conf = float(d.get("confidence") or 0.0)
                if conf < min_confidence:
                    continue
                d["_score"] = 0.1
                d["_fallback"] = True
                out.append(d)
            return out

        # 四因子重排
        scored = []
        for mid in all_ids:
            fts_info = fts_results.get(mid, {})
            kw_info = kw_results.get(mid, {})
            row = fts_info.get("row") or kw_info.get("row")
            if not row:
                continue

            # 语义分（从 RRF 融合得出）
            sem_score = fts_info.get("fts_score", 0) + kw_info.get("kw_score", 0)
            sem_norm = min(1.0, sem_score / 0.033)  # 归一化（RRF k=60 时 top1 约 0.016）

            # 近因因子（v5.4：半衰期按层可配 + 显性时间字段）
            type_info = MEMORY_TYPES.get(row.get("mem_type", ""), {})
            halflife = type_info.get("decay_halflife_days", 30)
            if row.get("pinned"):
                halflife = 0
            _t0 = row.get("updated_at") or row.get("created_at")
            recency = calc_recency_factor(row.get("last_accessed_at") or _t0, halflife)
            # v5.4：显性时间衰减字段（记忆年龄 / 衰减值 / 过时标记）
            _age_days = 0.0
            try:
                if _t0:
                    _age_days = max(0.0, (datetime.now() - datetime.fromisoformat(_t0)).total_seconds() / 86400.0)
            except (ValueError, TypeError):
                pass
            _stale = bool(halflife > 0 and recency < 0.15)  # 衰减<15%≈过2.7个半衰期

            # 频率因子
            freq = calc_frequency_factor(row.get("access_count", 0) + row.get("retrieval_count", 0))

            # 重要性因子
            importance = float(row.get("importance", 0.5))

            # 复合评分
            composite = calc_composite_score(sem_norm, recency, freq, importance)

            scored.append({
                **row,
                "_semantic": round(sem_norm, 4),
                "_recency": round(recency, 4),
                "_frequency": round(freq, 4),
                "_importance": round(importance, 4),
                "_age_days": round(_age_days, 1),
                "_time_decay": round(recency, 4),
                "_stale": _stale,
                "_score": round(composite, 6),
                "_match_source": "fts" if mid in fts_results else "keyword"
            })

        # 层级过滤
        if layer and layer != "all":
            scored = [s for s in scored if s.get("layer") == layer]

        # 空间过滤
        if space:
            scored = [s for s in scored if s.get("space") == space]
        if project:
            scored = [s for s in scored if s.get("project") == project]

        scored.sort(key=lambda x: x["_score"], reverse=True)
        top = scored[:limit]

        # 标记为已访问
        for item in top:
            self._mark_accessed(item["memory_id"])

        return top

    def _build_fts_query(self, query: str) -> str:
        """构造 FTS5 查询：英文整词 + 中文 2-gram AND 连接"""
        parts = []
        # 英文/数字词
        for m in _EN_RE.finditer(query):
            w = m.group()
            if len(w) >= 2:
                parts.append(f'"{w}"')
        # 中文 2-gram
        for m in _CJK_RE.finditer(query):
            s = m.group()
            if len(s) >= 2:
                grams = [s[i:i+2] for i in range(min(len(s) - 1, 3))]
                for g in grams:
                    parts.append(f'"{g}"')
        if not parts:
            return ""
        # 用 OR 连接（任意匹配一个即可），FTS 会按 BM25 排序
        return " OR ".join(parts[:10])

    def _mark_accessed(self, memory_id: str):
        """标记记忆被访问（更新时间和计数，用于衰减计算）"""
        now = now_iso()
        self.conn.execute("""
            UPDATE memories SET
                last_accessed_at = ?,
                access_count = access_count + 1,
                retrieval_count = retrieval_count + 1,
                updated_at = ?
            WHERE memory_id = ?
        """, (now, now, memory_id))
        self.conn.commit()

    def _row_to_dict(self, row) -> dict:
        d = dict(row)
        d["tags"] = safe_json_loads(d.get("tags"), [])
        d["metadata"] = safe_json_loads(d.get("metadata"), {})
        d["pinned"] = bool(d.get("pinned", 0))
        return d

    # ── 事件日志（L0 真相源） ──────────────────────────────────────

    def log_event(self, session_id: str, event_type: str, event_data: dict = None,
                  scope: str = "对话"):
        """
        L0 事件日志：append-only 真相源（WAL 思想）
        一切记忆先写日志，永不覆盖、永不删除；物化视图从日志回放生成。
        scope: 对话 / 决策 / 过程 / 纠错 / 进化 / 系统
        """
        now = now_iso()
        # 计算事件序列号（幂等：同 session 单调递增）
        row = self.conn.execute(
            "SELECT COALESCE(MAX(event_seq), 0) + 1 AS seq FROM session_events WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        seq = row["seq"] if row else 1
        self.conn.execute("""
            INSERT INTO session_events (session_id, event_type, event_data, timestamp, scope, event_seq)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session_id, event_type, json.dumps(event_data or {}, ensure_ascii=False),
              now, scope, seq))
        self.conn.commit()
        return {"event_seq": seq, "timestamp": now}

    def list_events(self, session_id: str = None, event_type: str = None,
                    scope: str = None, limit: int = 100) -> list[dict]:
        sql = "SELECT * FROM session_events WHERE 1=1"
        params = []
        if session_id:
            sql += " AND session_id = ?"
            params.append(session_id)
        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        sql += " ORDER BY event_seq DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r, event_data=safe_json_loads(r["event_data"])) for r in rows]

    def replay_events(self, since_seq: int = 0, scope: str = None) -> list[dict]:
        """
        事件回放：从日志重建物化视图（事件溯源 / CQRS 思想）
        崩溃恢复、跨会话续传、进化追溯都靠它。
        """
        sql = "SELECT * FROM session_events WHERE event_seq > ?"
        params = [since_seq]
        if scope:
            sql += " AND scope = ?"
            params.append(scope)
        sql += " ORDER BY event_seq ASC"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r, event_data=safe_json_loads(r["event_data"])) for r in rows]

    def evolution_log(self, limit: int = 50) -> list[dict]:
        """最近进化记录（谁变了、为什么变、置信度变化）— 进化的可观测性"""
        rows = self.conn.execute("""
            SELECT * FROM session_events
            WHERE scope IN ('进化', '决策', '纠错', '过程')
            ORDER BY timestamp DESC LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r, event_data=safe_json_loads(r["event_data"])) for r in rows]

    # ── 检查点 ──────────────────────────────────────────────────────

    def save_checkpoint(self, ckpt_id: str, task_name: str, phase: str,
                        progress_pct: float, state: dict, session_id: str = None):
        now = now_iso()
        self.conn.execute("""
            INSERT OR REPLACE INTO task_checkpoints
            (checkpoint_id, task_name, phase, progress_pct, state, created_at, session_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (ckpt_id, task_name, phase, progress_pct,
              json.dumps(state, ensure_ascii=False), now, session_id))
        self.conn.commit()

    def load_checkpoint(self, ckpt_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM task_checkpoints WHERE checkpoint_id = ?", (ckpt_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["state"] = safe_json_loads(d["state"])
        return d

    def list_checkpoints(self, task_name: str = None) -> list[dict]:
        if task_name:
            rows = self.conn.execute("""
                SELECT * FROM task_checkpoints WHERE task_name = ?
                ORDER BY created_at DESC
            """, (task_name,)).fetchall()
        else:
            rows = self.conn.execute("""
                SELECT * FROM task_checkpoints ORDER BY created_at DESC LIMIT 50
            """).fetchall()
        return [dict(r, state=safe_json_loads(r["state"])) for r in rows]

    # ── 知识图谱 ────────────────────────────────────────────────────

    def add_node(self, name: str, node_type: str = "concept",
                 description: str = "", layer: str = LAYER_FA,
                 space: str = SPACE_GLOBAL, importance: float = 0.5,
                 metadata: dict = None) -> str:
        """添加或更新图谱节点"""
        # 先查是否已存在（同名同类型合并）
        existing = self.conn.execute("""
            SELECT node_id FROM graph_nodes WHERE name = ? AND node_type = ?
        """, (name, node_type)).fetchone()
        now = now_iso()
        node_id = existing["node_id"] if existing else f"N_{uuid.uuid4().hex[:10]}"
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)

        if existing:
            self.conn.execute("""
                UPDATE graph_nodes SET description=?, layer=?, space=?,
                importance=?, updated_at=?, metadata=? WHERE node_id=?
            """, (description, layer, space, importance, now, meta_str, node_id))
        else:
            self.conn.execute("""
                INSERT INTO graph_nodes (node_id, name, node_type, description,
                layer, space, importance, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (node_id, name, node_type, description, layer, space,
                  importance, now, now, meta_str))
        self.conn.commit()
        return node_id

    def add_edge(self, source_id: str, target_id: str, relation: str,
                 weight: float = 1.0, confidence: float = 0.7,
                 metadata: dict = None) -> str:
        """添加或更新图谱边"""
        existing = self.conn.execute("""
            SELECT edge_id FROM graph_edges
            WHERE source_id = ? AND target_id = ? AND relation = ?
        """, (source_id, target_id, relation)).fetchone()
        now = now_iso()
        edge_id = existing["edge_id"] if existing else f"E_{uuid.uuid4().hex[:10]}"
        meta_str = json.dumps(metadata or {}, ensure_ascii=False)

        if existing:
            self.conn.execute("""
                UPDATE graph_edges SET weight=?, confidence=?, metadata=?
                WHERE edge_id=?
            """, (weight, confidence, meta_str, edge_id))
        else:
            self.conn.execute("""
                INSERT INTO graph_edges (edge_id, source_id, target_id, relation,
                weight, confidence, created_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (edge_id, source_id, target_id, relation,
                  weight, confidence, now, meta_str))
        self.conn.commit()
        return edge_id

    def get_neighbors(self, node_id: str, depth: int = 1,
                      relation: str = None, limit: int = 50) -> list[dict]:
        """获取节点邻居（支持多跳）"""
        if depth <= 1:
            sql = """
                SELECT n.*, e.relation, e.weight as edge_weight
                FROM graph_edges e
                JOIN graph_nodes n ON n.node_id = e.target_id
                WHERE e.source_id = ?
            """
            params = [node_id]
            if relation:
                sql += " AND e.relation = ?"
                params.append(relation)
            sql += " ORDER BY e.weight DESC LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        else:
            # 递归 CTE 多跳
            sql = """
                WITH RECURSIVE traverse(node_id, depth, path) AS (
                    SELECT target_id, 1, source_id || '->' || target_id
                    FROM graph_edges WHERE source_id = ?
                    UNION ALL
                    SELECT e.target_id, t.depth + 1, t.path || '->' || e.target_id
                    FROM graph_edges e
                    JOIN traverse t ON e.source_id = t.node_id
                    WHERE t.depth < ?
                )
                SELECT DISTINCT n.*, t.depth, t.path
                FROM traverse t
                JOIN graph_nodes n ON n.node_id = t.node_id
                ORDER BY t.depth, n.importance DESC
                LIMIT ?
            """
            rows = self.conn.execute(sql, (node_id, depth, limit)).fetchall()
            return [dict(r) for r in rows]

    def link_memory_to_node(self, memory_id: str, node_id: str, weight: float = 0.8):
        """关联记忆和图谱节点"""
        self.conn.execute("""
            INSERT OR REPLACE INTO memory_node_links(memory_id, node_id, weight)
            VALUES (?, ?, ?)
        """, (memory_id, node_id, weight))
        self.conn.commit()

    # ── v5.3 记忆关系图谱：写入后自动建边 ───────────────────────────

    def auto_graph_link(self, memory_id: str, content: str,
                        layer: str, category: str | None,
                        max_links: int = 5):
        """
        写入记忆后自动建边（记忆作为图谱节点）：
        1. semantic-similar 边：向量库语义相似记忆（阈值0.55）
        2. same-category 边：同层同类的最近记忆
        每条新记忆最多 max_links 条边，防边爆炸。
        """
        try:
            # 记忆自身作为图谱节点（name=memory_id，node_type=memory）
            self.add_node(name=memory_id, node_type="memory",
                          description=(content or "")[:120], layer=layer)
            self_node = self.conn.execute(
                "SELECT node_id FROM graph_nodes WHERE name=? AND node_type='memory'",
                (memory_id,)
            ).fetchone()
            if not self_node:
                return
            self_id = self_node["node_id"]
            # v1.1 修复：把记忆挂接到它自己的图谱节点。
            # graph_search 靠 memory_node_links 取记忆，若不在此挂接，
            # 则「记录记忆→查图谱」恒为 0（真架构缺口，非"数据不够"）。
            self.link_memory_to_node(memory_id, self_id, weight=1.0)
            created = 0

            # 1. 语义相似边
            vs = getattr(self, "vector_store", None)
            if vs is not None and created < max_links:
                try:
                    sims = vs.search(content, limit=max_links - created, threshold=0.55)
                    for other_id, score in sims:
                        if other_id == memory_id:
                            continue
                        other_node = self.conn.execute(
                            "SELECT node_id FROM graph_nodes WHERE name=? AND node_type='memory'",
                            (other_id,)
                        ).fetchone()
                        if not other_node:
                            continue
                        self.add_edge(self_id, other_node["node_id"],
                                      "semantic-similar",
                                      weight=round(float(score), 3),
                                      confidence=0.8,
                                      metadata={"auto": True, "kind": "semantic"})
                        created += 1
                except Exception:
                    pass

            # 2. 同层同类边（最近的同类记忆，补到 max_links 上限）
            if created < max_links and category:
                try:
                    rows = self.conn.execute("""
                        SELECT memory_id FROM memories
                        WHERE layer=? AND category=? AND memory_id != ?
                        ORDER BY updated_at DESC LIMIT ?
                    """, (layer, category, memory_id, max_links - created)).fetchall()
                    for r in rows:
                        other_node = self.conn.execute(
                            "SELECT node_id FROM graph_nodes WHERE name=? AND node_type='memory'",
                            (r["memory_id"],)
                        ).fetchone()
                        if not other_node:
                            continue
                        self.add_edge(self_id, other_node["node_id"],
                                      "same-category",
                                      weight=0.6,
                                      confidence=0.7,
                                      metadata={"auto": True, "kind": "category"})
                        created += 1
                except Exception:
                    pass
        except Exception:
            pass

    def graph_search(self, query: str, depth: int = 2, limit: int = 20) -> list[dict]:
        """
        图谱扩展检索：从查询中提取实体 → 多跳遍历 → 返回关联记忆
        """
        # 从记忆关键词索引中找最匹配的节点
        keywords = tokenize_cn(query)
        if not keywords:
            return []

        # 找匹配的节点名
        placeholders = ",".join("?" * min(len(keywords), 15))
        rows = self.conn.execute(f"""
            SELECT n.node_id, n.name, n.node_type, n.importance,
                   COUNT(mi.keyword) as match_count
            FROM graph_nodes n
            JOIN memory_index mi ON mi.memory_id = n.name
            WHERE mi.keyword IN ({placeholders})
            GROUP BY n.node_id
            ORDER BY match_count DESC, n.importance DESC
            LIMIT 10
        """, keywords[:15]).fetchall()

        if not rows:
            return []

        # 从 top 节点做多跳遍历
        seed_nodes = [r["node_id"] for r in rows[:3]]
        all_memories = {}
        for seed in seed_nodes:
            neighbors = self.get_neighbors(seed, depth=depth, limit=30)
            node_ids = [seed] + [n["node_id"] for n in neighbors]
            # 找这些节点关联的记忆
            placeholders2 = ",".join("?" * len(node_ids))
            mem_rows = self.conn.execute(f"""
                SELECT m.*, l.weight as link_weight
                FROM memory_node_links l
                JOIN memories m ON m.memory_id = l.memory_id
                WHERE l.node_id IN ({placeholders2})
                ORDER BY l.weight DESC
                LIMIT 50
            """, node_ids).fetchall()
            for mr in mem_rows:
                mid = mr["memory_id"]
                if mid not in all_memories:
                    all_memories[mid] = self._row_to_dict(mr)
                    all_memories[mid]["_graph_score"] = mr["link_weight"]
                else:
                    all_memories[mid]["_graph_score"] = max(
                        all_memories[mid]["_graph_score"], mr["link_weight"]
                    )

        result = sorted(all_memories.values(), key=lambda x: x.get("_graph_score", 0), reverse=True)
        return result[:limit]

    # ── 睡眠巩固（记忆衰减 + 增强 + 合并） ────────────────────────

    def sleep_consolidation(self) -> dict:
        """
        睡眠巩固周期（借鉴 Engram + KektorDB）：
        1. Decay: 重新计算所有记忆的强度
        2. Boost: 高频访问记忆增强
        3. Merge: 近重复记忆合并
        4. Archive: 低于阈值的记忆移到归档（不删除，只是降低检索优先级）
        """
        now = now_iso()
        stats = {"decayed": 0, "boosted": 0, "merged": 0, "archived": 0}

        # 1. 扫描所有非钉住记忆，更新 access_count 衰减后的 importance
        rows = self.conn.execute("""
            SELECT memory_id, mem_type, last_accessed_at, access_count,
                   importance, pinned, layer
            FROM memories WHERE pinned = 0
        """).fetchall()

        for row in rows:
            type_info = MEMORY_TYPES.get(row["mem_type"], {})
            halflife = type_info.get("decay_halflife_days", 30)
            if halflife == 0:
                continue
            recency = calc_recency_factor(row["last_accessed_at"], halflife)
            freq = calc_frequency_factor(row["access_count"])
            base_imp = float(row["importance"])
            # 时间衰减影响（缓慢降低）
            new_imp = max(0.1, base_imp * (0.7 + 0.3 * recency))
            # 频率提升
            if freq > 0.5:
                new_imp = min(1.0, new_imp + freq * 0.15)
                stats["boosted"] += 1
            if abs(new_imp - base_imp) > 0.01:
                self.conn.execute("""
                    UPDATE memories SET importance = ?, updated_at = ?
                    WHERE memory_id = ?
                """, (new_imp, now, row["memory_id"]))
                stats["decayed"] += 1

        # 2. 检测近重复记忆（相同 category，content 哈希前缀相同）
        dup_rows = self.conn.execute("""
            SELECT GROUP_CONCAT(memory_id) as ids, COUNT(*) as cnt,
                   category, MIN(importance) as min_imp
            FROM memories
            WHERE pinned = 0
            GROUP BY duplicate_hash, category
            HAVING cnt > 1
        """).fetchall()
        for dr in dup_rows:
            if dr["cnt"] >= 2:
                ids = dr["ids"].split(",")
                # 保留最重要的那个，其他标记为 merged
                keep_id = ids[0]
                for mid in ids[1:]:
                    self.conn.execute("""
                        UPDATE memories SET metadata = json_set(metadata, '$.merged_into', ?),
                        updated_at = ? WHERE memory_id = ?
                    """, (keep_id, now, mid))
                    stats["merged"] += 1

        # 3. 记录巩固日志
        self.conn.execute("""
            INSERT INTO compression_snapshots (layer, source_count, compressed_count, summary, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, ("all", stats["decayed"], stats["merged"],
              f"睡眠巩固：衰减{stats['decayed']}条, 增强{stats['boosted']}条, 合并{stats['merged']}条",
              now))

        self.conn.commit()
        stats["timestamp"] = now
        return stats

    # ── 健康检查 ────────────────────────────────────────────────────

    def self_check(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        by_layer = {}
        for row in self.conn.execute("""
            SELECT layer, COUNT(*) as c FROM memories GROUP BY layer
        """):
            by_layer[row["layer"]] = row["c"]
        by_type = {}
        for row in self.conn.execute("""
            SELECT mem_type, COUNT(*) as c FROM memories GROUP BY mem_type
        """):
            by_type[row["mem_type"]] = row["c"]
        pinned = self.conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE pinned = 1"
        ).fetchone()["c"]
        events = self.conn.execute(
            "SELECT COUNT(*) as c FROM session_events"
        ).fetchone()["c"]
        checkpoints = self.conn.execute(
            "SELECT COUNT(*) as c FROM task_checkpoints"
        ).fetchone()["c"]
        nodes = self.conn.execute(
            "SELECT COUNT(*) as c FROM graph_nodes"
        ).fetchone()["c"]
        edges = self.conn.execute(
            "SELECT COUNT(*) as c FROM graph_edges"
        ).fetchone()["c"]

        # 简单健康评分
        health = 100
        if total == 0:
            health = 50  # 空库也是正常的
        if nodes > 0 and edges == 0:
            health -= 10

        return {
            "health_score": health,
            "health_report": {
                "total": total,
                "by_layer": by_layer,
                "by_type": by_type,
                "pinned": pinned,
                "events": events,
                "checkpoints": checkpoints,
                "graph_nodes": nodes,
                "graph_edges": edges,
            },
            "db_path": str(self.db_path)
        }

    # ── 压缩 ────────────────────────────────────────────────────────

    def compress_layer(self, layer: str = LAYER_SHU) -> dict:
        """对指定层进行结构化压缩（统计+摘要，不删除原始）"""
        rows = self.conn.execute("""
            SELECT category, COUNT(*) as cnt, GROUP_CONCAT(content, ' ||| ') as contents
            FROM memories WHERE layer = ?
            GROUP BY category ORDER BY cnt DESC LIMIT 20
        """, (layer,)).fetchall()
        now = now_iso()
        summary_lines = []
        total = 0
        for r in rows:
            cat = r["category"] or "未分类"
            cnt = r["cnt"]
            total += cnt
            # 取前 3 条做代表
            samples = r["contents"].split(" ||| ")[:3]
            summary_lines.append(f"[{cat}] {cnt}条：" + "；".join(s[:30] for s in samples))

        summary = "\n".join(summary_lines) if summary_lines else f"{layer}层暂无记忆"
        self.conn.execute("""
            INSERT INTO compression_snapshots (layer, source_count, compressed_count, summary, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (layer, total, len(rows), summary, now))
        self.conn.commit()
        return {"layer": layer, "total_memories": total,
                "categories": len(rows), "summary": summary}


