#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║           万 忆 中 枢  v3 — 众神指令完整版                    ║
║                                                               ║
║  这不是一个记忆插件。                                            ║
║  这是给 Agent 装的第二个大脑。                                    ║
║                                                               ║
║  你教它一次，它永远记得。                                        ║
║  它犯错一次，它自己学会反思。                                    ║
║  你换一万次对话，它的记忆永不丢失。                                ║
║                                                               ║
║  架构：事件溯源 + 三路混合检索 + 知识图谱 + 睡眠巩固衰减           ║
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
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════
# 环境变量与路径配置
# ═══════════════════════════════════════════════════════════════════
STORE_DIR = Path(os.environ.get("万忆中枢_STORE_DIR",
    os.path.join(os.path.dirname(__file__), "memory")))
DB_PATH = Path(os.environ.get("万忆中枢_MEMORY_DB",
    os.path.join(STORE_DIR, "db", "万忆.db")))
USER_PROFILE = os.environ.get("万忆中枢_USER_PROFILE", "")
TRADING_ANCHOR = os.environ.get("万忆中枢_TRADING_ANCHOR", "")
INDEX_PATH = Path(os.environ.get("万忆中枢_INDEX",
    os.path.join(os.path.dirname(__file__), "index.json")))
OBSIDIAN_VAULT = Path(os.environ.get("OBSIDIAN_VAULT", "").strip()) if os.environ.get("OBSIDIAN_VAULT", "").strip() else None
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
            # 没有匹配时按时间倒序返回一些最近记忆
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


# ═══════════════════════════════════════════════════════════════════
# 万忆中枢核心引擎
# ═══════════════════════════════════════════════════════════════════
class WanYiCore:
    """
    万忆中枢 v5 核心引擎 — 全量之心·拦截之眼·反事实之镜·跨域桥接·轨迹回放·主动搭档·语义向量·精排·图谱·时序·元认知
    对外提供 23 个 MCP 工具：
      基础记忆（12）：
      - 万忆召回记忆       三路混合检索（v5.1语义向量 + v5.2 reranker精排 + v5.4时序衰减）
      - 万忆记录见闻       写入记忆
      - 万忆知识压缩       结构化压缩
      - 万忆记忆自检       健康检查
      - 万忆存档进度       任务检查点
      - 万忆加载进度       加载检查点
      - 万忆导入档案       用户偏好导入
      - 万忆更新交易锚点   交易锚点更新
      - 万忆触发LOAD钩子   会话启动注入
      - 万忆触发STORE钩子  会话结束归档
      - 万忆图谱搜索       知识图谱检索
      - 万忆睡眠巩固       记忆衰减+增强+合并
      v4新增（5）：
      - 万忆过程存档       五阶段过程记忆
      - 万忆错题本         反例错题库
      - 万忆经验库         成功模式库
      - 万忆查询进化       进化记录查询
      - 万忆园艺师         深巩固+每日档案
      v4.1护城河（1）：
      - 万忆置信度决策检查 认知置信度决策拦截（护城河#1）
      v4.2护城河（1）：
      - 万忆反事实之镜     平行分支开立+到期结算（护城河#2）
      v4.3护城河（1）：
      - 万忆跨域桥接       跨域类比迁移（护城河#3）
      v4.4护城河（1）：
      - 万忆轨迹回放       决策生涯时间线+双路径对比（护城河#4）
      v4.5护城河（1）：
      - 万忆主动搭档       今日简报+主动体检+周复盘+风险扫描（护城河#5）
      v5.1补强（1）：
      - 万忆知识空白       元认知：知道自己不知道什么（语义向量检索随召回集成）
    """

    def __init__(self, db_path=None, session_id=None):
        init_dirs()
        # 支持显式覆盖（测试/多实例注入），否则回退到模块级常量
        self._db_path = Path(db_path) if db_path else DB_PATH
        self._session_id = session_id or SESSION_ID
        self.db = MemoryDB(self._db_path)
        # ═══ v4：挂载三大新模块 ═══
        from confidence import Confidence
        from gardener import Gardener
        from process_memory import ProcessMemory
        self.process = ProcessMemory(self.db, self._session_id)
        self.confidence = Confidence(self.db, self._session_id)
        self.gardener = Gardener(self.db, self._session_id, OBSIDIAN_VAULT)
        # 反向挂载：让 db 层也能访问（矛盾仲裁需要）
        self.db.confidence = self.confidence
        self.db.process = self.process
        self.db.gardener = self.gardener
        # ═══ v5.1：挂载语义向量索引（失败自动降级为关键词检索） ═══
        try:
            from vector_memory import VectorIndex
            self.vector = VectorIndex(self._db_path)
            self.db.vector_store = self.vector
        except Exception:
            self.vector = None
            self.db.vector_store = None
        self._load_profile()
        self._load_trading_anchor()

    def _load_profile(self):
        if USER_PROFILE and os.path.exists(USER_PROFILE):
            try:
                with open(USER_PROFILE, "r", encoding="utf-8") as f:
                    self.user_profile = json.loads(f.read())
            except Exception:
                self.user_profile = {}
        else:
            self.user_profile = {}

    def _load_trading_anchor(self):
        if TRADING_ANCHOR and os.path.exists(TRADING_ANCHOR):
            try:
                with open(TRADING_ANCHOR, "r", encoding="utf-8") as f:
                    self.trading_anchor = json.loads(f.read())
            except Exception:
                self.trading_anchor = {}
        else:
            self.trading_anchor = {}

    # ── 工具 1：召回记忆 ────────────────────────────────────────────

    def tool_recall_memory(self, query: str, layer: str = "all",
                           space: str = None, project: str = None,
                           limit: int = 20,
                           min_confidence: float = 0.3,
                           use_graph: bool = True) -> dict:
        """
        三路混合检索：BM25关键词 + 倒排索引 + 知识图谱 + 四因子重排
        """
        # 通道1: 关键词混合检索
        fts_results = self.db.recall(
            query, layer=layer, space=space, project=project,
            limit=limit, min_confidence=min_confidence
        )

        # 通道2: 图谱扩展检索（可选）
        graph_results = []
        if use_graph:
            graph_results = self.db.graph_search(query, depth=2, limit=limit)
            # 按layer/space过滤图谱结果，保持与FTS通道一致
            if layer and layer != "all":
                graph_results = [g for g in graph_results if g.get("layer") == layer]
            if space and space != "all":
                graph_results = [g for g in graph_results if g.get("space") == space]

        # ═══ v5.1 通道3: 语义向量召回（模型不可用自动跳过） ═══
        vector_hits = []
        try:
            if getattr(self, "vector", None) is not None:
                vec_res = self.vector.search(query, limit=limit, threshold=0.30)
                if vec_res:
                    # 拉取向量命中记忆的详情
                    mids = [m for m, _ in vec_res]
                    if mids:
                        placeholders = ",".join("?" for _ in mids)
                        rows = self.db.conn.execute(
                            f"SELECT * FROM memories WHERE memory_id IN ({placeholders})",
                            mids
                        ).fetchall()
                        row_map = {r["memory_id"]: dict(r) for r in rows}
                        score_map = dict(vec_res)
                        for mid in mids:
                            row = row_map.get(mid)
                            if not row:
                                continue
                            row["_vec_score"] = round(score_map[mid], 3)
                            row["_match_source"] = "vector"
                            vector_hits.append(row)
        except Exception:
            vector_hits = []

        # 合并结果（去重 + 图谱boost + 向量boost）
        seen = {}
        for r in fts_results:
            mid = r["memory_id"]
            seen[mid] = r

        for gr in graph_results:
            mid = gr["memory_id"]
            graph_score = gr.get("_graph_score", 0)
            if mid in seen:
                # 图谱命中 boost 分数
                seen[mid]["_score"] = min(1.0, seen[mid].get("_score", 0) + graph_score * 0.1)
                seen[mid]["_graph_boosted"] = True
            else:
                gr["_score"] = graph_score * 0.5
                gr["_match_source"] = "graph"
                seen[mid] = gr

        # 向量命中：融合进总分（v5.1 混合召回）
        for vr in vector_hits:
            mid = vr["memory_id"]
            vs = vr.get("_vec_score", 0.0)
            if mid in seen:
                old = seen[mid].get("_score", 0.0) or 0.0
                # 关键词分0.4 + 向量分0.6 混合
                seen[mid]["_score"] = round(old * 0.4 + vs * 0.6, 4)
                seen[mid]["_vec_score"] = vs
                seen[mid]["_hybrid"] = True
            else:
                vr["_score"] = round(vs * 0.6, 4)
                vr["_hybrid"] = True
                seen[mid] = vr

        results = sorted(seen.values(), key=lambda x: x.get("_score", 0), reverse=True)[:limit]

        # ═══ v5.2 精排阶段：语义重排（模型不可用自动跳过，Top10精排控成本） ═══
        try:
            if results:
                from reranker import rerank as _rerank
                docs = [(r["memory_id"], r.get("content", "")) for r in results[:10]]
                rr = _rerank(query, docs, top_k=len(docs))
                if rr:
                    rr_map = dict(rr)
                    scores = [s for _, s in rr]
                    lo, hi = min(scores), max(scores)
                    span = (hi - lo) or 1.0
                    for r in results:
                        rs = rr_map.get(r["memory_id"])
                        if rs is None:
                            continue
                        r["_rerank_score"] = round(rs, 4)
                        norm = (rs - lo) / span  # 归一化到[0,1]
                        hybrid = r.get("_score", 0) or 0.0
                        r["_score"] = round(hybrid * 0.5 + norm * 0.5, 4)
                        r["_reranked"] = True
                    results.sort(key=lambda x: x.get("_score", 0), reverse=True)
        except Exception:
            pass

        # ═══ v5.4：统一补齐时序字段（所有通道结果一致，向量/图谱通道补算） ═══
        try:
            _now = datetime.now()
            for r in results:
                if r.get("_age_days") is None:
                    _t0 = r.get("updated_at") or r.get("created_at")
                    _age = 0.0
                    try:
                        if _t0:
                            _age = max(0.0, (_now - datetime.fromisoformat(_t0)).total_seconds() / 86400.0)
                    except (ValueError, TypeError):
                        pass
                    r["_age_days"] = round(_age, 1)
                    r["_time_decay"] = r.get("_recency", 0.5)
                    r["_stale"] = False
        except Exception:
            pass

        # ═══ v5.1 元认知：知识空白检测（v5.4改进：兜底记忆不算真实命中） ═══
        # 无真实命中（所有通道都空，只剩兜底记忆）或最高分过低 → 记录知识空白
        gap = None
        try:
            top_score = results[0].get("_score", 0) if results else 0
            real_hits = [r for r in results if not r.get("_fallback")]
            if not real_hits or top_score < 0.25:
                gap = self._record_knowledge_gap(query, weak=bool(real_hits))
        except Exception:
            pass

        total = self.db.conn.execute(
            "SELECT COUNT(*) FROM memories WHERE layer = ?", (layer,)
        ).fetchone()[0] if layer and layer != "all" else self.db.conn.execute(
            "SELECT COUNT(*) FROM memories"
        ).fetchone()[0]

        resp = {
            "query": query,
            "layer_filter": layer,
            "total_available": total,
            "results_count": len(results),
            "memories": results,
        }
        # v5.4 时序提示：召回结果含过时记忆时显性提醒
        try:
            stale_cnt = sum(1 for r in results if r.get("_stale"))
            if stale_cnt:
                resp["time_note"] = f"⏳ 召回结果中有 {stale_cnt} 条记忆已过时（时间衰减<15%），时效性数据请谨慎采信。"
        except Exception:
            pass
        if gap:
            resp["knowledge_gap"] = gap
            resp["note"] = "🔍 元认知提示：这块知识库存较薄弱，已记录知识空白，可主动补充。"
        return resp

    # ── 工具 2：记录见闻 ────────────────────────────────────────────

    def tool_record_memory(self, content: str, layer: str = LAYER_SHU,
                           mem_type: str = "observation",
                           category: str = None,
                           space: str = SPACE_GLOBAL,
                           project: str = None,
                           privacy: str = PRIVACY_INTERNAL,
                           tags: list = None,
                           source: str = None,
                           confidence: float = 0.7,
                           pinned: bool = False,
                           task_id: str = None) -> dict:
        """将一条新知识/观察记录入全量记忆库"""
        result = self.db.upsert_memory(
            content=content, layer=layer, mem_type=mem_type,
            category=category, space=space, project=project,
            privacy=privacy, source=source or "user_input",
            tags=tags, confidence=confidence, pinned=pinned,
            session_id=SESSION_ID, task_id=task_id
        )
        self.db.log_event(SESSION_ID, "record_memory", {
            "memory_id": result["memory_id"], "layer": result["layer"],
            "mem_type": mem_type, "category": category
        })
        # 同步到 Obsidian
        self._sync_to_obsidian(result["memory_id"], content, result["layer"], category)
        return result

    # ── 工具 3：知识压缩 ────────────────────────────────────────────

    def tool_compress_knowledge(self, layer: str = LAYER_SHU) -> dict:
        """对指定层级进行全量压缩 — 保留摘要+元数据，原始内容归档"""
        return self.db.compress_layer(layer)

    # ── 工具 4：记忆自检 ────────────────────────────────────────────

    def tool_self_check(self) -> dict:
        """全库健康度检测"""
        check = self.db.self_check()
        check["timestamp"] = now_iso()
        check["store_dir"] = str(STORE_DIR)
        return check

    # ── 工具 5：存档进度 ────────────────────────────────────────────

    def tool_save_progress(self, task_name: str, phase: str,
                           progress_pct: float, state: dict) -> dict:
        """存档任务进度 — 支持跨会话冷续传"""
        ckpt_id = gen_task_checkpoint_id(task_name, phase)
        self.db.save_checkpoint(ckpt_id, task_name, phase, progress_pct, state, SESSION_ID)
        self.db.log_event(SESSION_ID, "save_checkpoint", {
            "checkpoint_id": ckpt_id, "task": task_name,
            "phase": phase, "progress": progress_pct
        })
        return {
            "status": "saved",
            "checkpoint_id": ckpt_id,
            "task_name": task_name,
            "phase": phase,
            "progress_pct": progress_pct
        }

    # ── 工具 6：加载进度 ────────────────────────────────────────────

    def tool_load_progress(self, checkpoint_id: str = None,
                           task_name: str = None) -> dict:
        """加载历史存档"""
        if checkpoint_id:
            ckpt = self.db.load_checkpoint(checkpoint_id)
            return {"status": "found" if ckpt else "not_found", "checkpoint": ckpt}
        elif task_name:
            ckpts = self.db.list_checkpoints(task_name)
            return {"status": "found", "checkpoints": ckpts}
        else:
            ckpts = self.db.list_checkpoints()
            return {"status": "found", "checkpoints": ckpts}

    # ── 工具 7：导入用户档案 ────────────────────────────────────────

    def tool_import_user_profile(self, data: dict) -> dict:
        """更新用户偏好档案（交易风格/风险偏好等）"""
        self.user_profile.update(data)
        if USER_PROFILE:
            with open(USER_PROFILE, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.user_profile, ensure_ascii=False, indent=2))
        # 同时存入记忆库（道级，钉住）
        self.db.upsert_memory(
            memory_id=f"profile_{int(time.time())}",
            content=json.dumps(data, ensure_ascii=False),
            layer=LAYER_DAO, mem_type="preference",
            category="用户档案", space=SPACE_PERSONAL,
            privacy=PRIVACY_CONFIDENTIAL,
            source="user_profile", pinned=True, confidence=1.0,
            session_id=SESSION_ID
        )
        return {"status": "updated", "profile_keys": list(data.keys())}

    # ── 工具 8：更新交易锚点 ────────────────────────────────────────

    def tool_update_trading_anchor(self, section: str, data: dict) -> dict:
        """更新交易策略锚点"""
        if section not in self.trading_anchor:
            self.trading_anchor[section] = {}
        self.trading_anchor[section].update(data)
        if TRADING_ANCHOR:
            with open(TRADING_ANCHOR, "w", encoding="utf-8") as f:
                f.write(json.dumps(self.trading_anchor, ensure_ascii=False, indent=2))
        self.db.upsert_memory(
            memory_id=f"trading_{section}_{int(time.time())}",
            content=f"[交易锚点-{section}] {json.dumps(data, ensure_ascii=False)}",
            layer=LAYER_DAO, mem_type="strategy",
            category=f"交易锚点/{section}", space=SPACE_PERSONAL,
            privacy=PRIVACY_CONFIDENTIAL,
            source="trading_anchor", pinned=True, confidence=0.95,
            session_id=SESSION_ID
        )
        return {"status": "updated", "section": section, "data_keys": list(data.keys())}

    # ── 工具 9：触发 LOAD 钩子 ──────────────────────────────────────

    def trigger_load_hook(self) -> dict:
        """
        HOOK-LOAD：会话启动时自动注入记忆
        - 注入道级钉住记忆（原则/偏好/决策）
        - 注入法级高频记忆（模式/策略）
        - 检查断点续传
        - 记录会话开始事件
        - v4.5：自动附加主动搭档今日简报（护城河#5）
        """
        from hooks import hook_load
        result = hook_load(engine=self)
        # v4.5 主动搭档：LOAD时自动生成今日简报
        try:
            brief = self.tool_proactive_partner(action="brief")
            if isinstance(result, dict):
                result["proactive_brief"] = brief.get("brief", "")
                result["proactive"] = brief
        except Exception:
            pass
        return result

    # ── 工具 10：触发 STORE 钩子 ────────────────────────────────────

    def trigger_store_hook(self, session_summary: dict = None,
                           mode: str = "full", raw_notes: str = "",
                           decisions: list = None, patterns: list = None,
                           skills: list = None, postmortems: list = None,
                           memories: list = None) -> dict:
        """
        HOOK-STORE / HOOK-REFLECT：会话结束时归档 + 反思
        mode: full(store+reflect) / reflect(仅反思) / store(仅存储)
        """
        from hooks import run_all_hooks
        return run_all_hooks(
            mode=mode, engine=self,
            session_summary=session_summary,
            raw_notes=raw_notes,
            decisions=decisions, patterns=patterns,
            skills=skills, postmortems=postmortems,
            memories=memories
        )

    # ── 工具 11：图谱搜索 ───────────────────────────────────────────

    def tool_graph_search(self, query: str, depth: int = 2, limit: int = 20) -> dict:
        """知识图谱扩展检索"""
        results = self.db.graph_search(query, depth=depth, limit=limit)
        return {"query": query, "depth": depth, "results_count": len(results), "results": results}

    # ── 工具 12：睡眠巩固 ───────────────────────────────────────────

    def tool_sleep_consolidation(self) -> dict:
        """
        睡眠巩固周期：衰减 + 增强 + 合并 + 归档
        定期运行（每天一次或会话数达到阈值）
        """
        stats = self.db.sleep_consolidation()
        self.db.log_event(SESSION_ID, "sleep_consolidation", stats)
        return stats

    # ═══ v4 新增工具 ═══

    # ── 工具 13：过程存档（ExpeL 式轨迹分段） ──────────────────────

    def tool_process_save(self, task_name: str, phase: str, content: str,
                          outcome: str = "neutral",
                          process_id: str = None,
                          anchor_state: dict = None) -> dict:
        """
        过程记忆：将任务执行的一个阶段（规划/尝试/纠错/反思/结论）
        存入轨迹档案。失败阶段自动沉淀错题本，成功结论自动沉淀经验库。
        传入 anchor_state 时同时设置记忆锚点（断点恢复用）。
        """
        if not process_id:
            proc = self.process.start_process(task_name, content)
            process_id = proc["process_id"]

        result = self.process.add_phase(process_id, task_name, phase, content,
                                        outcome=outcome)

        # 记忆锚点（可选）
        anchor = None
        if anchor_state is not None:
            anchor = self.process.set_anchor(process_id, phase, f"{task_name}-{phase}", anchor_state)

        return {
            "process_id": process_id,
            "phase": phase,
            "seq": result.get("seq"),
            "outcome": outcome,
            "auto_mistake": result.get("auto_mistake", False),
            "auto_experience": result.get("auto_experience", False),
            "anchor": anchor,
            "note": "全量存储不遗忘，任何阶段都已持久化",
        }

    # ── 工具 14：错题本 ────────────────────────────────────────────

    def tool_mistake_book(self, action: str = "list",
                          task_name: str = None,
                          mistake_id: str = None,
                          lesson: str = None) -> dict:
        """
        错题本：list(查看错题) / patterns(高频错误模式) / lesson(补充教训)
        失败决策自动沉淀为反例条目，模式统计防重复犯错。
        """
        if action == "patterns":
            patterns = self.process.get_error_patterns()
            return {"action": "patterns", "count": len(patterns), "patterns": patterns}
        if action == "lesson" and mistake_id and lesson:
            return self.process.add_mistake_lesson(mistake_id, lesson)
        mistakes = self.process.list_mistakes(task_name=task_name)
        return {"action": "list", "count": len(mistakes), "mistakes": mistakes}

    # ── 工具 15：经验库 ────────────────────────────────────────────

    def tool_experience_library(self, task_name: str = None, limit: int = 50) -> dict:
        """经验库：成功路径沉淀的可复用模式（ExpeL 式提取）"""
        experiences = self.process.list_experiences(task_name=task_name, limit=limit)
        return {"count": len(experiences), "experiences": experiences}

    # ── 工具 16：查询进化（进化的可观测性） ────────────────────────

    def tool_recent_evolution(self, limit: int = 30) -> dict:
        """最近进化记录：谁变了、为什么变、置信度变化 — 跨会话可见"""
        log = self.db.evolution_log(limit=limit)
        # 附带置信度变化摘要
        conf_stats = self.confidence.self_check()
        return {
            "evolution_count": len(log),
            "events": log,
            "confidence_stats": conf_stats,
            "note": "这是真实发生在文件系统上的进化，任何聊天框都能查到",
        }

    # ── 工具 17：园艺师深巩固 ──────────────────────────────────────

    def tool_gardener(self, action: str = "consolidate") -> dict:
        """
        园艺师后台：consolidate(深巩固: 提炼+矛盾+冗余+技能结晶+每日日志)
                     daily_log(仅写每日思考档案)
        """
        if action == "daily_log":
            return self.gardener.write_daily_log()
        return self.gardener.deep_consolidation()

    # ── 工具 18：万忆置信度决策检查（护城河#1：认知置信度拦截） ──────

    # 高风险动作关键词 → 风险等级映射
    _HIGH_RISK_KEYWORDS = {
        # 交易类（最高风险）
        "all_in": ["all in", "全仓", "梭哈", "满仓", "all-in", "押上全部"],
        "chase_high": ["追涨", "追高", "打板", "追板", "涨停板买入", "爆拉买入", "fomo买入"],
        "cut_loss_violation": ["不止损", "扛单", "死扛", "加仓摊平", "补仓摊平", "越跌越买"],
        "leverage": ["杠杆", "融资", "配资", "期货加杠杆", "期权买方重仓"],
        "hot_sector": ["追热点", "追题材", "消息面买入", "听消息买"],
        # 系统/文件类
        "delete": ["删除", "rm -rf", "删库", "格式化", "drop table", "truncate"],
        "force_push": ["force push", "强制推送", "强推", "--force"],
        "publish": ["发布", "上线", "部署生产", "merge到main", "merge到master"],
    }

    # 风险等级对应的置信度阈值
    _RISK_THRESHOLDS = {
        "critical": 0.85,  # 致命风险：置信度必须≥0.85才放行
        "high":     0.70,  # 高风险：置信度必须≥0.70
        "medium":   0.50,  # 中风险：置信度必须≥0.50
        "low":      0.30,  # 低风险：基本不拦
    }

    def _assess_risk(self, action_description: str) -> dict:
        """评估动作的风险等级和类型"""
        desc = action_description.lower()
        matched_risks = []
        highest_level = "low"
        level_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}

        # 交易类是critical
        critical_cats = ["all_in", "chase_high", "cut_loss_violation", "leverage"]
        high_cats = ["hot_sector", "delete", "force_push"]
        medium_cats = ["publish"]

        for cat, keywords in self._HIGH_RISK_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in desc:
                    if cat in critical_cats:
                        cat_level = "critical"
                    elif cat in high_cats:
                        cat_level = "high"
                    elif cat in medium_cats:
                        cat_level = "medium"
                    else:
                        cat_level = "low"
                    matched_risks.append({"category": cat, "keyword": kw, "level": cat_level})
                    if level_order[cat_level] > level_order[highest_level]:
                        highest_level = cat_level
                    break  # 一个类别只记一次

        return {
            "risk_level": highest_level,
            "matched_risks": matched_risks,
            "is_risky": highest_level in ("high", "critical"),
            "threshold": self._RISK_THRESHOLDS[highest_level],
        }

    def tool_confidence_check(self,
                               action: str = "check",
                               decision_text: str = "",
                               target_type: str = "decision",
                               target_id: str = None,
                               signal: str = "validate",
                               reason: str = "",
                               recall_success: bool = None,
                               elapsed_days: float = 1.0) -> dict:
        """
        万忆置信度决策检查（护城河#1：拦截之眼）
        action:
          - check(默认)：对一个即将执行的决策做置信度检查+风险拦截
          - validate：对某个判断投支持票（+共识度，-摩擦度）
          - challenge：对某个判断投反对票/踩坑反馈（-共识度，+摩擦度）
          - review：FSRS间隔重复复习，recall_success=True/False
          - get：查询单个目标的置信度状态
          - rank：按置信度排名所有记忆
          - needs_review：列出需要复习的记忆
        decision_text：check/validate/challenge时必填，描述要检查/反馈的决策
        signal: validate(正面反馈)/challenge(反面反馈)，action=check时不用
        reason: 反馈理由（challenge时强烈建议填写）
        """
        # ── 子动作分发 ─────────────────────────────────────────
        if action == "get":
            tid = target_id or f"dec_{hashlib.md5(decision_text.encode('utf-8')).hexdigest()[:12]}"
            return {"status": "ok", "data": self.confidence.get(target_type, tid)}

        if action == "rank":
            return {"status": "ok", "rankings": self.confidence.rank_by_confidence(target_type)}

        if action == "needs_review":
            return {"status": "ok", "needs_review": self.confidence.needs_review(target_type)}

        # validate/challenge/review 不需要风险拦截，直接更新置信度
        if action in ("validate", "challenge"):
            if not decision_text and not target_id:
                return {"status": "error", "message": "validate/challenge 需要 decision_text 或 target_id"}
            tid = target_id or f"dec_{hashlib.md5(decision_text.encode('utf-8')).hexdigest()[:12]}"
            # 第一次见的目标先初始化
            existing = self.confidence.get(target_type, tid)
            if not existing:
                self.confidence.init_entry(target_type, tid, initial=0.5)
            if action == "validate":
                result = self.confidence.validate(target_type, tid, source=SESSION_ID)
            else:
                result = self.confidence.challenge(target_type, tid, reason=reason or "")
            self.db.log_event(SESSION_ID, f"confidence_{action}", {
                "target_type": target_type, "target_id": tid,
                "decision_text": decision_text[:200], "reason": reason[:200]
            })
            return {"status": "ok", "action": action, "result": result}

        if action == "review":
            if not target_id and not decision_text:
                return {"status": "error", "message": "review 需要 target_id 或 decision_text"}
            tid = target_id or f"dec_{hashlib.md5(decision_text.encode('utf-8')).hexdigest()[:12]}"
            if recall_success is None:
                return {"status": "error", "message": "review 需要 recall_success=true/false"}
            result = self.confidence.review(target_type, tid, recall_success, elapsed_days)
            return {"status": "ok", "action": "review", "result": result}

        # ── action=check：核心决策拦截逻辑 ─────────────────────
        if not decision_text:
            return {"status": "error", "message": "check 需要 decision_text（描述你要做的决策/动作）"}

        tid = target_id or f"dec_{hashlib.md5(decision_text.encode('utf-8')).hexdigest()[:12]}"

        # 1) 风险评估
        risk = self._assess_risk(decision_text)

        # 2) 取/初始化置信度
        entry = self.confidence.get(target_type, tid)
        if not entry:
            entry = self.confidence.init_entry(target_type, tid, initial=0.5)

        current_conf = entry.get("confidence", 0.5)
        threshold = risk["threshold"]

        # 3) 召回相关历史记忆（错题本+经验库+同类决策）
        relevant_mistakes = []
        relevant_experiences = []
        relevant_memories = []
        try:
            # 搜相关记忆
            recalled = self.db.recall(decision_text, layer="all", limit=5, min_confidence=0.3)
            relevant_memories = [
                {"id": m["memory_id"], "content": m["content"][:200],
                 "layer": m["layer"], "confidence": m.get("confidence", 0)}
                for m in recalled
            ]
            # 搜错题本（mistakes 表，Reflexion式反例库；统一用 self.db.conn 避免数据源不一致）
            # 用决策文本命中的风险关键词去匹配错题 content，而非整句 LIKE（整句子串匹配不到同义句）
            try:
                risk_kws = [m["keyword"] for m in risk.get("matched_risks", [])]
                kw_parts = [k for k in risk_kws if k] or [decision_text[:20]]
                like_conds = " OR ".join("content LIKE ?" for _ in kw_parts)
                params = [f"%{k}%" for k in kw_parts]
                mistake_rows = self.db.conn.execute(
                    f"SELECT * FROM mistakes WHERE ({like_conds}) AND status != 'learned' "
                    f"ORDER BY pattern_count DESC, created_at DESC LIMIT 3",
                    params
                ).fetchall()
                for row in mistake_rows:
                    relevant_mistakes.append(dict(row))
            except Exception:
                sys.stderr.write(f"[万忆中枢] 错题本查询失败: {traceback.format_exc()}\n")
                sys.stderr.flush()
            try:
                exp_rows = self.db.conn.execute(
                    "SELECT * FROM experiences WHERE content LIKE ? ORDER BY source_count DESC, created_at DESC LIMIT 3",
                    (f"%{decision_text[:20]}%",)
                ).fetchall()
                for row in exp_rows:
                    relevant_experiences.append(dict(row))
            except Exception:
                sys.stderr.write(f"[万忆中枢] 经验库查询失败: {traceback.format_exc()}\n")
                sys.stderr.flush()
        except Exception:
            sys.stderr.write(f"[万忆中枢] 决策检查召回相关记忆失败: {traceback.format_exc()}\n")
            sys.stderr.flush()

        # 4) 决策结论
        verdict = "PASS"
        warnings = []

        if risk["is_risky"] and current_conf < threshold:
            verdict = "BLOCK"
        elif risk["risk_level"] == "critical" and current_conf < threshold + 0.05:
            verdict = "CAUTION"
            warnings.append(f"接近临界阈值：置信度{current_conf:.2f}，阈值{threshold:.2f}，建议三思")

        # 5) 风险提示
        if risk["matched_risks"]:
            for r in risk["matched_risks"]:
                if r["level"] in ("critical", "high"):
                    warnings.append(f"⚠️ 命中高风险模式：{r['category']}（关键词：{r['keyword']}）")

        # 6) 错题命中提醒
        gotcha_warnings = []
        for m in relevant_mistakes:
            content = m.get("content", "")
            if len(content) > 150:
                content = content[:150] + "..."
            gotcha_warnings.append(f"🚨 历史踩过类似坑：{content}")

        # 7) 组装返回
        result = {
            "status": "ok",
            "action": "check",
            "verdict": verdict,  # PASS / CAUTION / BLOCK
            "risk": risk,
            "confidence": {
                "current": round(current_conf, 3),
                "threshold": threshold,
                "entry": entry,
            },
            "warnings": warnings,
            "gotchas": gotcha_warnings,
            "relevant_memories": relevant_memories[:5],
            "relevant_experiences_count": len(relevant_experiences),
            "target_id": tid,
            "advice": self._generate_advice(verdict, risk, current_conf, threshold, gotcha_warnings),
            "moat": "护城河#1：认知置信度决策拦截（v4.1 拦截之眼）",
        }

        # 8) 记录本次检查事件
        self.db.log_event(SESSION_ID, "confidence_check", {
            "target_type": target_type, "target_id": tid,
            "decision_text": decision_text[:300],
            "risk_level": risk["risk_level"],
            "confidence": current_conf,
            "verdict": verdict,
        })

        # 9) 护城河#2联动：BLOCK/CAUTION时自动开立反事实分支（记录"如果当时听劝"的平行宇宙）
        counterfactual = None
        if verdict in ("BLOCK", "CAUTION") and risk["is_risky"]:
            try:
                cf = self._open_counter_branch(
                    decision_text=decision_text,
                    risk_level=risk["risk_level"],
                    fact_path="taken",  # 默认假设用户会无视拦截（后续settle时可修正为avoided）
                    counter_path="反事实：如果当时听劝、不做这个高风险动作、选择小仓试/观望/先验证，会是什么结果？",
                    confidence_target_id=tid,
                )
                counterfactual = {"branch_id": cf.get("branch_id"), "settlement_date": cf.get("settlement_date")}
            except Exception:
                pass

        # 把counterfactual塞进返回
        if counterfactual:
            result["counterfactual"] = counterfactual
            result["moat_pair"] = "护城河#1拦截之眼 + 护城河#2反事实之镜 联动：分支已开立，到期结算时将自动对比听劝/不听劝的结果"

        # 10) 护城河#3联动：BLOCK/CAUTION时附加跨域类比迁移（交易教训↔写作↔开发）
        analog = None
        if verdict in ("BLOCK", "CAUTION"):
            try:
                ab = self.tool_analog_bridge(action="bridge", decision_text=decision_text, domain="trade")
                if ab.get("status") == "ok" and ab.get("matches", 0) > 0:
                    analog = {
                        "matches": ab["matches"],
                        "patterns": [
                            {"pattern_id": p["pattern_id"], "abstract_name": p["abstract_name"],
                             "essence": p["essence"], "domains": p["domains"]}
                            for p in ab["patterns"]
                        ],
                    }
            except Exception:
                pass
        if analog:
            result["analog"] = analog
            analog_lines = ["\n🔗 【跨域类比迁移·护城河#3】这个动作的底层模式，你在别的领域也踩过："]
            for p in analog["patterns"]:
                analog_lines.append(f"  - {p['abstract_name']}：{p['essence']}（覆盖领域：{'/'.join(p['domains'])}）")
            result["advice"] = result["advice"] + "\n".join(analog_lines)
            result["moat_triple"] = "护城河#1拦截之眼 + 护城河#2反事实之镜 + 护城河#3跨域类比迁移 三线联动"

        return result

    def _generate_advice(self, verdict, risk, conf, threshold, gotchas) -> str:
        """根据拦截结果生成人类可读的建议"""
        if verdict == "BLOCK":
            advice = "🛑 【万忆拦截】兄弟，停一下。\n"
            advice += f"你要做的这件事风险等级是 {risk['risk_level']}，但你对这件事的判断置信度只有 {conf:.2f}（需要≥{threshold:.2f}）。\n"
            if gotchas:
                advice += f"\n🚨 历史已经警告过你 {len(gotchas)} 次类似的坑：\n"
                for i, g in enumerate(gotchas, 1):
                    advice += f"  {i}. {g}\n"
            advice += "\n建议：要么先收集更多信息/验证假设，要么小仓位试错，不要一把梭。"
            return advice
        elif verdict == "CAUTION":
            advice = f"⚠️ 【万忆提醒】这件事风险={risk['risk_level']}，你的置信度={conf:.2f}，离安全线{threshold:.2f}很近。\n"
            if gotchas:
                advice += f"历史上踩过 {len(gotchas)} 次类似的坑，建议先回顾一下。\n"
            advice += "建议：减仓/分批/设好硬止损再动手。"
            return advice
        else:
            if risk["risk_level"] in ("medium", "high", "critical"):
                return f"✅ 置信度{conf:.2f} ≥ 阈值{threshold:.2f}，放行。但高风险动作请始终带止损。"
            return f"✅ 低风险动作，置信度{conf:.2f}，直接干。"

    # ── 护城河#2：反事实之镜（Counterfactual Mirror） ──────────────

    def tool_counterfactual_mirror(self,
                                   action: str = "open",
                                   decision_text: str = "",
                                   decision_type: str = "other",
                                   risk_level: str = "medium",
                                   fact_path: str = "taken",
                                   counter_path: str = "",
                                   fact_outcome: str = "",
                                   counter_outcome: str = "",
                                   settlement_days: float = 7.0,
                                   branch_id: str = None,
                                   lesson: str = "",
                                   tags: list = None,
                                   confidence_target_id: str = None,
                                   user_chose: bool = False) -> dict:
        """
        护城河#2「反事实之镜」：在每个关键决策点开平行分支，到期结算对比。

        action:
          - open(默认)：开一条反事实分支。fact_path=taken表示"用户实际做了"，
            反事实路径由counter_path描述（通常是"如果听劝没做"或"如果当时小仓试"）。
            若confidence拦截BLOCK时自动调用，fact_path=taken表示用户无视拦截。
          - settle：结算一个分支。需要branch_id + fact_outcome(实际结果)，
            系统会基于历史同类决策推算counter_outcome，给出verdict和教训。
          - list_open：列出所有待结算分支（默认到期日升序）
          - list_settled：列出已结算分支
          - get：查看单个分支对
          - auto_check_due：自动检查到期未结算的分支并提醒
        """
        import hashlib
        import json as _json
        from datetime import datetime

        cur = self.db.conn.cursor()
        now = now_iso()

        # ── list_open ────────────────────────────────────────────
        if action == "list_open":
            cur.execute(
                "SELECT * FROM counterfactual_branches WHERE verdict='open' ORDER BY settlement_date ASC LIMIT 50"
            )
            rows = [dict(r) for r in cur.fetchall()]
            return {"status": "ok", "action": "list_open", "count": len(rows), "branches": rows}

        # ── list_settled ─────────────────────────────────────────
        if action == "list_settled":
            limit = 50
            cur.execute(
                "SELECT * FROM counterfactual_branches WHERE verdict!='open' ORDER BY settled_at DESC LIMIT ?",
                (limit,)
            )
            rows = [dict(r) for r in cur.fetchall()]
            stats = {"fact_won": 0, "counter_won": 0, "neutral": 0}
            for r in rows:
                v = r.get("verdict", "")
                if v in stats:
                    stats[v] += 1
            return {"status": "ok", "action": "list_settled", "count": len(rows), "stats": stats, "branches": rows}

        # ── auto_check_due ───────────────────────────────────────
        if action == "auto_check_due":
            today = now[:10]
            cur.execute(
                "SELECT * FROM counterfactual_branches WHERE verdict='open' AND settlement_date <= ? ORDER BY settlement_date ASC",
                (today,)
            )
            due = [dict(r) for r in cur.fetchall()]
            if not due:
                return {"status": "ok", "action": "auto_check_due", "due_count": 0, "message": "今日无待结算分支"}
            summaries = []
            for b in due:
                summaries.append({
                    "branch_id": b["branch_id"],
                    "decision": b["decision_text"][:80],
                    "settlement_date": b["settlement_date"],
                    "risk_level": b["risk_level"],
                    "fact_path": b["fact_path"],
                })
            return {
                "status": "ok", "action": "auto_check_due",
                "due_count": len(due), "due": summaries,
                "message": f"🔔 有{len(due)}条反事实分支到期待结算，请用action=settle记录实际结果"
            }

        # ── get ──────────────────────────────────────────────────
        if action == "get":
            if not branch_id:
                return {"status": "error", "message": "get 需要 branch_id"}
            cur.execute("SELECT * FROM counterfactual_branches WHERE branch_id=?", (branch_id,))
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                return {"status": "error", "message": f"分支 {branch_id} 不存在"}
            return {"status": "ok", "action": "get", "pair": rows}

        # ── open ─────────────────────────────────────────────────
        if action == "open":
            if not decision_text:
                return {"status": "error", "message": "open 需要 decision_text（描述决策点）"}
            bid = branch_id or f"cf_{hashlib.md5((decision_text+now).encode('utf-8')).hexdigest()[:12]}"
            sched_date = (datetime.now() + timedelta(days=float(settlement_days))).strftime("%Y-%m-%d")

            # 如果没显式传counter_path，基于risk和fact_path自动生成
            if not counter_path:
                if fact_path == "taken":
                    counter_path = "反事实：如果当时听劝没做/小仓试/先观望，会是什么结果？"
                else:
                    counter_path = "反事实：如果当时做了/重仓出手，会是什么结果？"

            tags_json = _json.dumps(tags or [], ensure_ascii=False)

            cur.execute("""
                INSERT INTO counterfactual_branches
                (branch_id, decision_text, decision_type, risk_level, fact_path, counter_path,
                 settlement_date, confidence_target_id, tags, created_at, updated_at, session_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """, (bid, decision_text, decision_type, risk_level,
                  fact_path, counter_path, sched_date,
                  confidence_target_id, tags_json, now, now, SESSION_ID))
            self.db.conn.commit()
            self.db.log_event(SESSION_ID, "cf_open", {
                "branch_id": bid, "decision_text": decision_text[:200],
                "fact_path": fact_path, "settlement_date": sched_date,
            })
            return {
                "status": "ok", "action": "open",
                "branch_id": bid,
                "settlement_date": sched_date,
                "message": f"🔮 反事实分支已开立（{sched_date}到期结算）：{counter_path}",
                "mirror": {
                    "fact": f"你选了：{fact_path} → {decision_text[:80]}",
                    "counter": counter_path,
                }
            }

        # ── settle ───────────────────────────────────────────────
        if action == "settle":
            if not branch_id:
                return {"status": "error", "message": "settle 需要 branch_id"}
            if not fact_outcome:
                return {"status": "error", "message": "settle 需要 fact_outcome（描述实际发生了什么）"}

            cur.execute("SELECT * FROM counterfactual_branches WHERE branch_id=? AND verdict='open'", (branch_id,))
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                return {"status": "error", "message": f"未找到待结算分支 {branch_id}"}
            pair = rows[0]

            # 推算反事实结果（基于历史同类BLOCK/错题的经验）
            if not counter_outcome:
                risk = pair.get("risk_level", "medium")
                fact = pair.get("fact_path", "taken")
                if fact == "taken" and risk in ("critical", "high"):
                    counter_outcome = (
                        "如果当时听劝没做，大概率会避免这次损失/错误，"
                        "同时保留了等待更优时机的选择权。"
                    )
                elif fact == "avoided" and risk in ("critical", "high"):
                    counter_outcome = (
                        "如果当时做了，按照历史同类高风险决策的经验，"
                        "大概率会陷入追涨被套/删库事故/强推翻车的典型模式。"
                    )
                else:
                    counter_outcome = "反事实路径的结果无法精确推算，需要更多同类样本。"

            # 自动判定 verdict（如果用户没明确给lesson，这里做初判）
            verdict = "neutral"
            auto_lesson = lesson
            # 简单启发式：事实路径是taken且风险critical/high，默认counter_won（事后反推拦得对）
            if pair.get("fact_path") == "taken" and pair.get("risk_level") in ("critical", "high"):
                # 如果fact_outcome里出现正面词，判fact_won；否则默认counter_won
                pos_kw = ["盈利", "赚了", "涨了", "成功", "顺利", "没问题", "正收益"]
                neg_kw = ["亏", "套", "跌", "事故", "翻车", "失败", "后悔", "止损"]
                pos = sum(1 for k in pos_kw if k in fact_outcome)
                neg = sum(1 for k in neg_kw if k in fact_outcome)
                if neg > pos:
                    verdict = "counter_won"
                    if not auto_lesson:
                        auto_lesson = "🚨 这次没听劝，结果验证了万忆当时的拦截是对的。教训：高风险决策前的BLOCK不是吓唬人。"
                elif pos > neg:
                    verdict = "fact_won"
                    if not auto_lesson:
                        auto_lesson = "这次高风险动作结果尚可，但仍属幸存者偏差，同类动作下次仍需谨慎。"
                else:
                    verdict = "neutral"
            elif pair.get("fact_path") == "avoided" and pair.get("risk_level") in ("critical", "high"):
                verdict = "fact_won"
                if not auto_lesson:
                    auto_lesson = "这次听劝没做，避免了潜在的高风险损失。"

            if not auto_lesson:
                auto_lesson = "待进一步复盘。"

            cur.execute("""
                UPDATE counterfactual_branches
                SET fact_outcome=?, counter_outcome=?, verdict=?, lesson_learned=?, settled_at=?, updated_at=?
                WHERE branch_id=? AND verdict='open'
            """, (fact_outcome, counter_outcome, verdict, auto_lesson, now, now, branch_id))
            self.db.conn.commit()

            # 如果 verdict 是 counter_won（没听劝吃亏了），自动沉淀入错题本
            if verdict == "counter_won":
                self.db.upsert_memory(
                    content=f"[反事实教训] 决策：{pair['decision_text'][:150]}\n"
                            f"实际结果：{fact_outcome[:200]}\n"
                            f"反事实结果：{counter_outcome[:200]}\n"
                            f"教训：{auto_lesson}",
                    layer="法", category="gotcha", tags=["反事实", "错题", pair.get("risk_level","")],
                    mem_type="pattern", importance=0.85
                )
                # 同步提升置信度拦截的可信度（challenge一次）
                tid = pair.get("confidence_target_id")
                if tid:
                    try:
                        self.confidence.challenge("decision", tid, reason=f"反事实结算证明拦截正确：{fact_outcome[:80]}")
                    except Exception:
                        pass
            elif verdict == "fact_won":
                # 事实赢了，说明决策正确，validate置信度
                self.db.upsert_memory(
                    content=f"[反事实经验] 决策：{pair['decision_text'][:150]}\n"
                            f"实际结果：{fact_outcome[:200]}\n"
                            f"教训：{auto_lesson}",
                    layer="法", category="经验", tags=["反事实", "经验"],
                    mem_type="pattern", importance=0.6
                )

            self.db.log_event(SESSION_ID, "cf_settle", {
                "branch_id": branch_id, "verdict": verdict,
                "fact_outcome": fact_outcome[:200],
            })

            return {
                "status": "ok", "action": "settle",
                "branch_id": branch_id, "verdict": verdict,
                "fact_outcome": fact_outcome,
                "counter_outcome": counter_outcome,
                "lesson": auto_lesson,
                "message": f"🔮 分支已结算：{verdict}。{auto_lesson}"
            }

        return {"status": "error", "message": f"未知action: {action}"}

    # ═══ v4.3 护城河#3：跨域类比迁移 ═══════════════════════════════════

    def tool_analog_bridge(self, action: str = "bridge",
                           decision_text: str = "",
                           domain: str = "other",
                           abstract_name: str = "",
                           essence: str = "",
                           keywords: list = None,
                           source_ref: str = None,
                           pattern_id: str = None,
                           limit: int = 5) -> dict:
        """
        护城河#3「跨域类比迁移」：把一个领域的教训/模式抽象成跨域底层模式，
        然后在其他领域做同构桥接——让交易的教训自动提醒写作/开发，反之亦然。

        action:
          - abstract：把一条具体经验抽象为跨域模式（先沉淀模式本体）
          - bridge：给定当前决策文本+领域，找出所有跨域同构模式与历史实例
          - list_patterns：列出已沉淀的跨域模式（按hit_count排序）
          - get：查看单个模式详情（含来源引用）
        """
        import hashlib as _hashlib
        import json as _json
        now = now_iso()
        cur = self.db.conn.cursor()

        # ── list_patterns ────────────────────────────────────────
        if action == "list_patterns":
            cur.execute(
                "SELECT * FROM analog_patterns ORDER BY hit_count DESC, confidence DESC LIMIT ?",
                (limit,)
            )
            rows = [dict(r) for r in cur.fetchall()]
            return {"status": "ok", "action": "list_patterns", "count": len(rows), "patterns": rows}

        # ── get ──────────────────────────────────────────────────
        if action == "get":
            if not pattern_id:
                return {"status": "error", "message": "get 需要 pattern_id"}
            cur.execute("SELECT * FROM analog_patterns WHERE pattern_id=?", (pattern_id,))
            rows = [dict(r) for r in cur.fetchall()]
            if not rows:
                return {"status": "error", "message": f"模式 {pattern_id} 不存在"}
            return {"status": "ok", "action": "get", "pattern": rows[0]}

        # ── abstract：沉淀跨域模式 ────────────────────────────────
        if action == "abstract":
            if not abstract_name or not essence:
                return {"status": "error", "message": "abstract 需要 abstract_name（模式名）+ essence（底层本质）"}
            pid = f"ap_{_hashlib.md5((abstract_name+essence).encode('utf-8')).hexdigest()[:10]}"
            # 规范化：domains 存 [domain]，keywords 单独存
            domains_json = _json.dumps([domain] if domain else ["other"], ensure_ascii=False)
            kws_json = _json.dumps(keywords or [], ensure_ascii=False)
            refs = _json.dumps([source_ref] if source_ref else [], ensure_ascii=False)

            # 已存在则只更新（事件溯源：不删除历史）
            cur.execute("SELECT * FROM analog_patterns WHERE pattern_id=?", (pid,))
            exists = cur.fetchone()
            if exists:
                cur.execute("""
                    UPDATE analog_patterns SET abstract_name=?, essence=?, keywords=?,
                    updated_at=? WHERE pattern_id=?
                """, (abstract_name, essence, kws_json, now, pid))
                self.db.conn.commit()
                return {"status": "ok", "action": "abstract", "pattern_id": pid,
                        "message": f"📐 模式已更新：{abstract_name}", "exists": True}
            cur.execute("""
                INSERT INTO analog_patterns
                (pattern_id, abstract_name, essence, domains, keywords, source_refs,
                 confidence, created_at, updated_at, session_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (pid, abstract_name, essence, domains_json, kws_json, refs,
                  0.7, now, now, SESSION_ID))
            self.db.conn.commit()
            self.db.log_event(SESSION_ID, "ap_abstract", {
                "pattern_id": pid, "abstract_name": abstract_name, "domain": domain,
            })
            return {
                "status": "ok", "action": "abstract",
                "pattern_id": pid,
                "message": f"📐 跨域模式已沉淀：{abstract_name}（{domain}）→ 可跨域桥接",
                "pattern": {"abstract_name": abstract_name, "essence": essence, "domains": [domain]},
            }

        # ── bridge：跨域同构桥接（护城河#3核心） ───────────────────
        if action == "bridge":
            if not decision_text:
                return {"status": "error", "message": "bridge 需要 decision_text（当前决策/场景描述）"}
            cur.execute("SELECT * FROM analog_patterns ORDER BY hit_count DESC, confidence DESC")
            patterns = [dict(r) for r in cur.fetchall()]
            if not patterns:
                return {
                    "status": "ok", "action": "bridge",
                    "matches": 0, "message": "暂无沉淀的跨域模式，先用 action=abstract 沉淀",
                }

            matched = []
            for p in patterns:
                # 命中判定：决策文本包含模式的任一关键词，或与本质有语义重叠
                kws = _json.loads(p.get("keywords") or "[]")
                hit = False
                for k in kws:
                    if k and k in decision_text:
                        hit = True
                        break
                # 弱命中：本质里的词出现在决策文本（取 essence 前若干个有意义的词）
                if not hit:
                    for w in (p.get("essence") or "").replace("，", " ").replace("。", " ").split()[:8]:
                        if len(w) >= 2 and w in decision_text:
                            hit = True
                            break
                if hit:
                    matched.append({
                        "pattern_id": p["pattern_id"],
                        "abstract_name": p["abstract_name"],
                        "essence": p["essence"],
                        "domains": _json.loads(p.get("domains") or "[]"),
                        "source_refs": _json.loads(p.get("source_refs") or "[]"),
                        "hit_count": p.get("hit_count", 0),
                    })
                if len(matched) >= limit:
                    break

            if matched:
                # 命中计数 +1（反馈强化）
                for m in matched:
                    cur.execute("UPDATE analog_patterns SET hit_count=hit_count+1, updated_at=? WHERE pattern_id=?",
                                (now, m["pattern_id"]))
                self.db.conn.commit()
                self.db.log_event(SESSION_ID, "ap_bridge", {
                    "decision_text": decision_text[:150], "matched": [m["pattern_id"] for m in matched],
                })
                return {
                    "status": "ok", "action": "bridge",
                    "matches": len(matched), "patterns": matched,
                    "message": f"🔗 找到 {len(matched)} 个跨域同构模式，其他领域的历史经验正在提醒你",
                }
            return {"status": "ok", "action": "bridge", "matches": 0,
                    "message": "未命中已有跨域模式，可用 action=abstract 把这条经验沉淀为模式"}

        return {"status": "error", "message": f"未知action: {action}"}

    # ═══ v4.4 护城河#4：分支轨迹回放 ═══════════════════════════════════

    def tool_trajectory_replay(self, action: str = "timeline",
                               days: int = 30,
                               limit: int = 100) -> dict:
        """
        护城河#4「分支轨迹回放」：把历史所有反事实分支串成一条决策时间线，
        让用户一眼看见自己每次「听劝/不听劝」的走向——决策生涯回放。

        action:
          - timeline：按时间顺序回放所有分支（标注open/verdict状态）
          - stats：决策统计（总分支/结算率/counter_won率/听劝验证率/风险分布）
          - route：对比「实际路径」vs「如果全听劝路径」两条虚拟人生轨迹
          - review：最近N天决策回顾总结（新增分支/结算/趋势）
        """
        cur = self.db.conn.cursor()

        # ── timeline：决策生涯时间线 ──────────────────────────────
        if action == "timeline":
            cur.execute("""
                SELECT * FROM counterfactual_branches
                ORDER BY created_at ASC LIMIT ?
            """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            events = []
            for b in rows:
                state = "open" if b.get("verdict") == "open" else f"settled:{b.get('verdict')}"
                events.append({
                    "date": (b.get("created_at") or "")[:10],
                    "branch_id": b["branch_id"],
                    "decision": (b.get("decision_text") or "")[:100],
                    "risk_level": b.get("risk_level"),
                    "fact_path": b.get("fact_path"),
                    "state": state,
                    "verdict": b.get("verdict"),
                })
            return {"status": "ok", "action": "timeline", "count": len(events), "timeline": events}

        # ── stats：决策生涯统计 ───────────────────────────────────
        if action == "stats":
            cur.execute("SELECT * FROM counterfactual_branches")
            rows = [dict(r) for r in cur.fetchall()]
            total = len(rows)
            settled = [b for b in rows if b.get("verdict") != "open"]
            open_b = [b for b in rows if b.get("verdict") == "open"]
            counter_won = [b for b in settled if b.get("verdict") == "counter_won"]
            fact_won = [b for b in settled if b.get("verdict") == "fact_won"]
            neutral = [b for b in settled if b.get("verdict") == "neutral"]
            # 听劝验证率：fact_path=avoided（听了没做）且fact_won → 听劝对了
            heed_right = [b for b in fact_won if b.get("fact_path") == "avoided"]
            # 没听劝吃亏：fact_path=taken（没听做了）且counter_won → 拦截正确
            block_right = [b for b in counter_won if b.get("fact_path") == "taken"]
            risk_dist = {}
            for b in rows:
                rl = b.get("risk_level") or "unknown"
                risk_dist[rl] = risk_dist.get(rl, 0) + 1
            stats = {
                "total_branches": total,
                "open": len(open_b),
                "settled": len(settled),
                "settlement_rate": round(len(settled) / total, 3) if total else 0,
                "counter_won": len(counter_won),
                "fact_won": len(fact_won),
                "neutral": len(neutral),
                "heed_right_count": len(heed_right),       # 听劝并且对了
                "block_right_count": len(block_right),     # 没听劝结果吃亏（拦截正确）
                "risk_distribution": risk_dist,
                "insight": "",
            }
            if total:
                if block_right:
                    stats["insight"] = (
                        f"🔮 你的{len(block_right)}次'没听劝'都被验证为吃亏，"
                        f"拦截正确率100%。下次BLOCK时，请先想想：上次没听，结果怎样？"
                    )
                elif len(fact_won) and all(b.get("fact_path") == "taken" for b in fact_won):
                    stats["insight"] = "⚠️ 有几次高风险动作侥幸成功了，但那是幸存者偏差，不代表下次运气还在。"
                else:
                    stats["insight"] = "🌱 决策样本还在积累，结算越多，你的决策画像越清晰。"
            return {"status": "ok", "action": "stats", "stats": stats}

        # ── route：实际路径 vs 全听劝路径 ──────────────────────────
        if action == "route":
            cur.execute("SELECT * FROM counterfactual_branches ORDER BY created_at ASC")
            rows = [dict(r) for r in cur.fetchall()]
            settled = [b for b in rows if b.get("verdict") != "open"]
            actual_path = []   # 实际选择的结果
            heed_path = []     # 如果全听劝的结果
            for b in settled:
                node = {
                    "date": (b.get("created_at") or "")[:10],
                    "decision": (b.get("decision_text") or "")[:60],
                    "risk_level": b.get("risk_level"),
                }
                if b.get("fact_path") == "avoided":
                    # 实际听劝没做
                    if b.get("verdict") == "fact_won":
                        node["actual"] = "听劝没做 → 对了，避免损失"
                        node["heed"] = "听劝没做 → 对了，避免损失"
                    else:
                        node["actual"] = "听劝没做 → 结果待定/中性"
                        node["heed"] = "听劝没做 → 结果待定/中性"
                else:  # taken：实际做了
                    if b.get("verdict") == "counter_won":
                        node["actual"] = f"没听劝做了 → 吃亏（{b.get('lesson_learned','')[:40]}）"
                        node["heed"] = "如果听劝没做 → 大概率避免这次损失"
                    elif b.get("verdict") == "fact_won":
                        node["actual"] = "没听劝做了 → 侥幸成功（幸存者偏差）"
                        node["heed"] = "如果听劝没做 → 错过一次，但避开了尾部风险"
                    else:
                        node["actual"] = "做了 → 结果中性"
                        node["heed"] = "听劝没做 → 结果中性"
                actual_path.append(node)
                heed_path.append(node)
            return {
                "status": "ok", "action": "route",
                "actual_count": len(actual_path), "heed_count": len(heed_path),
                "actual_path": actual_path,
                "heed_path": heed_path,
                "message": "🛤️ 左列=你实际走过的路；右列=如果当初全听劝的路。对比看看，哪个版本的你少踩坑？",
            }

        # ── review：最近N天决策回顾 ───────────────────────────────
        if action == "review":
            from datetime import datetime, timedelta
            since = (datetime.now() - timedelta(days=int(days))).strftime("%Y-%m-%d")
            cur.execute("""
                SELECT * FROM counterfactual_branches
                WHERE created_at >= ? ORDER BY created_at ASC
            """, (since,))
            rows = [dict(r) for r in cur.fetchall()]
            new_open = [b for b in rows if b.get("verdict") == "open"]
            settled = [b for b in rows if b.get("verdict") != "open"]
            cw = [b for b in settled if b.get("verdict") == "counter_won"]
            fw = [b for b in settled if b.get("verdict") == "fact_won"]
            return {
                "status": "ok", "action": "review", "window_days": days,
                "new_branches": len(rows),
                "new_open": len(new_open),
                "settled_in_window": len(settled),
                "counter_won": len(cw),
                "fact_won": len(fw),
                "summary": (
                    f"📅 最近{days}天：新增{len(rows)}条决策分支，其中{len(new_open)}条待结算，"
                    f"{len(settled)}条已结算（counter_won={len(cw)}，fact_won={len(fw)}）。"
                    + ("这次没听劝的，上次的教训还在等你结算。" if len(new_open) else "")
                ),
            }

        return {"status": "error", "message": f"未知action: {action}"}

    # ═══ v4.5 护城河#5：主动搭档 ═══════════════════════════════════════

    def tool_proactive_partner(self, action: str = "brief",
                               days: int = 7,
                               text: str = "") -> dict:
        """
        护城河#5「主动搭档」：从被动工具升级为主动搭档——
        不等用户开口，自动生成简报/体检/周复盘/风险扫描。

        action:
          - brief：今日简报（待结算分支+到期提醒+高命中跨域模式+决策健康提示）
          - proactive_check：主动体检（到期分支/超期待结算/重复踩坑/需要周复盘）
          - weekly_review：每周轨迹回放复盘（stats+route+review 合成总结）
          - alert：风险关键词扫描（消息里出现高风险词时快速告警）
        """
        now = now_iso()
        today = now[:10]
        cur = self.db.conn.cursor()

        # ── alert：风险关键词扫描 ─────────────────────────────────
        if action == "alert":
            if not text:
                return {"status": "error", "message": "alert 需要 text 参数（要扫描的文本）"}
            risk_kw = {
                "critical": ["梭哈", "all in", "全仓", "满仓", "押上全部", "追涨", "追高",
                             "打板", "追板", "不止损", "扛单", "死扛", "加仓摊平", "越跌越买",
                             "杠杆", "融资", "配资", "删库", "drop table", "rm -rf", "强推",
                             "force push", "格式化"],
                "high": ["重仓", "删掉", "覆盖", "清空", "重置"],
                "medium": ["发布", "上线", "部署", "merge"],
            }
            hits = []
            for level, kws in risk_kw.items():
                for kw in kws:
                    if kw in text:
                        hits.append({"keyword": kw, "level": level})
            if hits:
                # 触发完整拦截：交给置信度决策检查做判定
                return {
                    "status": "risk_detected", "action": "alert",
                    "hits": hits, "count": len(hits),
                    "message": f"🚨 主动搭档扫描到{len(hits)}个风险信号，请立即调用 万忆置信度决策检查 做拦截判定",
                    "suggestion": "action=check + decision_text=你的完整决策描述",
                }
            return {"status": "ok", "action": "alert", "hits": [], "count": 0,
                    "message": "✅ 未扫描到高风险信号"}

        # ── proactive_check：主动体检 ──────────────────────────────
        if action == "proactive_check":
            cur.execute("SELECT * FROM counterfactual_branches WHERE verdict='open'")
            open_rows = [dict(r) for r in cur.fetchall()]
            due = [b for b in open_rows if (b.get("settlement_date") or "9999") <= today]
            overdue = [b for b in open_rows if (b.get("settlement_date") or "9999") < today]
            cur.execute("SELECT * FROM analog_patterns ORDER BY hit_count DESC LIMIT 3")
            top_patterns = [dict(r) for r in cur.fetchall()]
            issues = []
            if due:
                issues.append(f"🔔 {len(due)}条分支已到期待结算（其中{len(overdue)}条已超期）——请用 万忆反事实之镜 action=settle 记录结果")
            if not issues:
                issues.append("✅ 无到期分支，决策账本干净")
            return {
                "status": "ok", "action": "proactive_check",
                "open_branches": len(open_rows),
                "due_today": len(due),
                "overdue": len(overdue),
                "top_patterns": [
                    {"abstract_name": p["abstract_name"], "hit_count": p.get("hit_count", 0)}
                    for p in top_patterns
                ],
                "issues": issues,
            }

        # ── weekly_review：每周轨迹回放复盘 ───────────────────────
        if action == "weekly_review":
            stats = self.tool_trajectory_replay(action="stats")["stats"]
            route = self.tool_trajectory_replay(action="route")
            review = self.tool_trajectory_replay(action="review", days=days)
            summary = (
                f"📊 本周决策复盘（近{days}天）：新增{review['new_branches']}条分支，"
                f"已结算{review['settled_in_window']}条（counter_won={review['counter_won']}，fact_won={review['fact_won']}）。"
                f"生涯累计：{stats['total_branches']}条分支，结算率{stats['settlement_rate']*100:.0f}%，"
                f"拦截正确{stats['block_right_count']}次，听劝验证正确{stats['heed_right_count']}次。"
                f"洞察：{stats.get('insight','')}"
            )
            self.db.log_event(SESSION_ID, "weekly_review", {"days": days, "summary": summary[:300]})
            return {
                "status": "ok", "action": "weekly_review", "days": days,
                "stats": stats, "review": review,
                "route_message": route.get("message", ""),
                "summary": summary,
            }

        # ── brief：今日简报（默认） ───────────────────────────────
        if action == "brief":
            cur.execute("SELECT * FROM counterfactual_branches WHERE verdict='open'")
            open_rows = [dict(r) for r in cur.fetchall()]
            due = [b for b in open_rows if (b.get("settlement_date") or "9999") <= today]
            cur.execute("SELECT * FROM analog_patterns ORDER BY hit_count DESC LIMIT 3")
            top_patterns = [dict(r) for r in cur.fetchall()]
            sections = []
            if due:
                sections.append(f"🔔 {len(due)}条反事实分支到期待结算（{len([b for b in due if (b.get('settlement_date') or '9999') < today])}条已超期）")
            else:
                sections.append("✅ 无待结算分支，决策账本干净")
            if top_patterns:
                names = "、".join(p["abstract_name"] for p in top_patterns)
                sections.append(f"🔗 高命中跨域模式：{names}（交易/写作/开发互相提醒中）")
            if len(open_rows) >= 3:
                sections.append(f"⚠️ 你有{len(open_rows)}条未结算分支，建议抽空结算，决策画像会更清晰")
            brief_text = "🤝 【主动搭档·今日简报】" + "｜".join(sections)
            self.db.log_event(SESSION_ID, "proactive_brief", {"summary": brief_text[:200]})
            return {
                "status": "ok", "action": "brief",
                "date": today,
                "open_branches": len(open_rows),
                "due_count": len(due),
                "top_patterns": [p["abstract_name"] for p in top_patterns],
                "brief": brief_text,
            }

        return {"status": "error", "message": f"未知action: {action}"}

    # ═══ v5.1 元认知：知识空白 ═══════════════════════════════════════

    def _record_knowledge_gap(self, query_text: str, weak: bool = False) -> dict:
        """召回太弱时自动记录知识空白（元认知核心：知道自己不知道什么）"""
        import hashlib as _hashlib
        now = now_iso()
        gid = f"gap_{_hashlib.md5((query_text+now).encode('utf-8')).hexdigest()[:10]}"
        cur = self.db.conn.cursor()
        # 相似空白合并：同 query 已存在则 hit_count+1
        existing = cur.execute(
            "SELECT * FROM knowledge_gaps WHERE query_text=? AND status='open'",
            (query_text[:200],)
        ).fetchone()
        if existing:
            cur.execute(
                "UPDATE knowledge_gaps SET hit_count=hit_count+1, updated_at=? WHERE gap_id=?",
                (now, existing["gap_id"])
            )
            self.db.conn.commit()
            return {"gap_id": existing["gap_id"], "query": query_text[:200],
                    "hit_count": existing["hit_count"] + 1, "status": "open"}
        cur.execute("""
            INSERT INTO knowledge_gaps
            (gap_id, query_text, weak_hit, hit_count, status, created_at, updated_at, session_id)
            VALUES (?,?,?,?,?,?,?,?)
        """, (gid, query_text[:200], 1 if weak else 0, 1, "open", now, now, SESSION_ID))
        self.db.conn.commit()
        return {"gap_id": gid, "query": query_text[:200], "hit_count": 1, "status": "open"}

    def tool_knowledge_gap(self, action: str = "list", limit: int = 20,
                           gap_id: str = None, note: str = None) -> dict:
        """
        v5.1 元认知工具「万忆知识空白」：让系统知道自己不知道什么。
        - list：列出待补充的知识空白（按被查中次数排序，越常查越该补）
        - close：标记某空白已补充（gap_id + note 说明补充来源）
        - stats：知识空白统计（开放数/已关闭数/最薄弱领域TOP）
        """
        now = now_iso()
        cur = self.db.conn.cursor()

        if action == "list":
            cur.execute(
                "SELECT * FROM knowledge_gaps WHERE status='open' ORDER BY hit_count DESC, created_at ASC LIMIT ?",
                (limit,)
            )
            rows = [dict(r) for r in cur.fetchall()]
            return {"status": "ok", "action": "list", "count": len(rows), "gaps": rows}

        if action == "close":
            if not gap_id:
                return {"status": "error", "message": "close 需要 gap_id"}
            cur.execute(
                "UPDATE knowledge_gaps SET status='closed', filled_by=?, updated_at=? WHERE gap_id=? AND status='open'",
                (note or "手动补充", now, gap_id)
            )
            self.db.conn.commit()
            if cur.rowcount == 0:
                return {"status": "error", "message": f"空白 {gap_id} 不存在或已关闭"}
            self.db.log_event(SESSION_ID, "gap_closed", {"gap_id": gap_id, "note": note})
            return {"status": "ok", "action": "close", "gap_id": gap_id,
                    "message": f"✅ 知识空白 {gap_id} 已标记补充：{note}"}

        if action == "stats":
            total = cur.execute("SELECT COUNT(*) FROM knowledge_gaps").fetchone()[0]
            open_n = cur.execute("SELECT COUNT(*) FROM knowledge_gaps WHERE status='open'").fetchone()[0]
            closed_n = total - open_n
            top = cur.execute(
                "SELECT query_text, hit_count FROM knowledge_gaps WHERE status='open' ORDER BY hit_count DESC LIMIT 5"
            ).fetchall()
            return {
                "status": "ok", "action": "stats",
                "total": total, "open": open_n, "closed": closed_n,
                "top_weak_areas": [{"query": r["query_text"], "hits": r["hit_count"]} for r in top],
                "message": f"🧠 元认知自检：还有{open_n}块知识空白待补充，最常被查的是「{top[0]['query_text']}」" if top else "🧠 无开放知识空白",
            }

        return {"status": "error", "message": f"未知action: {action}"}

    def _open_counter_branch(self, decision_text: str, risk_level: str,
                              fact_path: str, counter_path: str,
                              confidence_target_id: str = None,
                              settlement_days: float = None,
                              decision_type: str = "trade") -> dict:
        """拦截之眼内部调用：在BLOCK/CAUTION时自动开立反事实分支"""
        if settlement_days is None:
            days_map = {"critical": 3, "high": 7, "medium": 14, "low": 30}
            settlement_days = days_map.get(risk_level, 7)
        return self.tool_counterfactual_mirror(
            action="open",
            decision_text=decision_text,
            decision_type=decision_type,
            fact_path=fact_path,
            counter_path=counter_path,
            settlement_days=settlement_days,
            confidence_target_id=confidence_target_id,
            risk_level=risk_level,
        )

    # ── Obsidian 同步 ──────────────────────────────────────────────

    def _sync_to_obsidian(self, memory_id: str, content: str, layer: str, category: str):
        """同步记忆到 Obsidian 第二大脑"""
        if not OBSIDIAN_VAULT or not str(OBSIDIAN_VAULT):
            return
        try:
            vault_path = Path(str(OBSIDIAN_VAULT))
            if not vault_path.exists():
                return
            # 按层分类目录
            layer_dir = vault_path / layer
            layer_dir.mkdir(parents=True, exist_ok=True)
            cat_dir = layer_dir / (category or "未分类")
            cat_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{memory_id}.md"
            filepath = cat_dir / filename
            md_content = f"""---
memory_id: {memory_id}
layer: {layer}
category: {category or '未分类'}
created: {now_iso()}
tags: [记忆, {layer}]
---

# {memory_id}

{content}

---
*由万忆中枢自动同步*
"""
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(md_content)
        except Exception:
            pass  # 同步失败不影响核心功能


# ═══════════════════════════════════════════════════════════════════
# MCP JSON-RPC 接口（兼容 MCP 标准协议 + 直接工具名调用）
# ═══════════════════════════════════════════════════════════════════
ENGINE = None

# 工具元数据定义（MCP tools/list 用）
MCP_TOOLS = [
    {
        "name": "万忆召回记忆",
        "description": "四通道混合检索（v5.0）：BM25关键词 + 倒排索引 + 知识图谱 + 语义向量（v5.1），reranker精排（v5.2）+ 时序衰减显性化（v5.4）+ 知识空白元认知（弱召回自动记录gap）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":          {"type": "string", "description": "检索关键词/查询文本"},
                "layer":          {"type": "string", "description": "层级过滤：道/法/术/器/all", "default": "all"},
                "space":          {"type": "string", "description": "空间过滤：全局级/个人级/项目级"},
                "project":        {"type": "string", "description": "项目名过滤"},
                "limit":          {"type": "number", "description": "返回条数上限", "default": 20},
                "min_confidence": {"type": "number", "description": "最低置信度阈值 0~1", "default": 0.3},
                "use_graph":      {"type": "boolean", "description": "是否启用图谱扩展检索", "default": True},
            },
            "required": ["query"],
        },
    },
    {
        "name": "万忆记录见闻",
        "description": "将一条新知识/观察/经验记录入全量记忆库，自动分类、打标签、建索引",
        "inputSchema": {
            "type": "object",
            "properties": {
                "content":    {"type": "string", "description": "记忆内容文本"},
                "layer":      {"type": "string", "description": "层级：道/法/术/器", "default": "术"},
                "mem_type":   {"type": "string", "description": "记忆类型：observation/insight/pattern/principle/preference/postmortem/skill", "default": "observation"},
                "category":   {"type": "string", "description": "分类标签"},
                "space":      {"type": "string", "description": "空间：全局级/个人级/项目级", "default": "全局级"},
                "project":    {"type": "string", "description": "所属项目"},
                "privacy":    {"type": "string", "description": "隐私级别：公开/内部/机密", "default": "内部"},
                "tags":       {"type": "array", "items": {"type": "string"}, "description": "标签列表"},
                "source":     {"type": "string", "description": "来源标识"},
                "confidence": {"type": "number", "description": "置信度 0~1", "default": 0.7},
                "pinned":     {"type": "boolean", "description": "是否钉住（永不遗忘）", "default": False},
                "task_id":    {"type": "string", "description": "关联任务ID"},
            },
            "required": ["content"],
        },
    },
    {
        "name": "万忆知识压缩",
        "description": "对指定层级进行全量压缩 — 保留摘要+元数据，原始内容归档，释放存储空间",
        "inputSchema": {
            "type": "object",
            "properties": {
                "layer": {"type": "string", "description": "要压缩的层级：道/法/术/器", "default": "术"},
            },
        },
    },
    {
        "name": "万忆记忆自检",
        "description": "全库健康度检测：记忆总数、各层分布、索引状态、FTS状态、图谱状态",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "万忆存档进度",
        "description": "存档任务进度 — 支持跨会话冷续传，保存任务名、阶段、进度百分比、完整状态",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_name":    {"type": "string", "description": "任务名称"},
                "phase":        {"type": "string", "description": "当前阶段"},
                "progress_pct": {"type": "number", "description": "进度百分比 0~100"},
                "state":        {"type": "object", "description": "完整任务状态快照（任意JSON）"},
            },
            "required": ["task_name", "phase", "progress_pct", "state"],
        },
    },
    {
        "name": "万忆加载进度",
        "description": "加载历史存档 — 按checkpoint_id、task_name或全量查询",
        "inputSchema": {
            "type": "object",
            "properties": {
                "checkpoint_id": {"type": "string", "description": "存档ID（精确加载单个）"},
                "task_name":     {"type": "string", "description": "任务名（列出该任务所有存档）"},
            },
        },
    },
    {
        "name": "万忆导入档案",
        "description": "更新用户偏好档案（交易风格/风险偏好/写作风格/个人信息等），同时存入道级钉住记忆",
        "inputSchema": {
            "type": "object",
            "properties": {
                "data": {"type": "object", "description": "用户档案数据（任意键值对）"},
            },
            "required": ["data"],
        },
    },
    {
        "name": "万忆更新交易锚点",
        "description": "更新交易策略锚点 — 分板块管理你的核心交易逻辑与参数",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section": {"type": "string", "description": "锚点板块名（如：风控/选股/择时/仓位管理等）"},
                "data":    {"type": "object", "description": "该板块的锚点数据"},
            },
            "required": ["section", "data"],
        },
    },
    {
        "name": "万忆触发LOAD钩子",
        "description": "HOOK-LOAD：会话启动时自动注入记忆 — 道级钉住记忆、法级高频记忆、断点续传检查",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "万忆触发STORE钩子",
        "description": "HOOK-STORE / HOOK-REFLECT：会话结束时归档 + 反思 — 提炼决策、模式、技能、复盘",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_summary": {"type": "object", "description": "会话摘要"},
                "mode":            {"type": "string", "description": "模式：full(存储+反思)/reflect(仅反思)/store(仅存储)", "default": "full"},
                "raw_notes":       {"type": "string", "description": "原始笔记文本"},
                "decisions":       {"type": "array", "items": {"type": "string"}, "description": "决策列表"},
                "patterns":        {"type": "array", "items": {"type": "string"}, "description": "模式列表"},
                "skills":          {"type": "array", "items": {"type": "string"}, "description": "技能列表"},
                "postmortems":     {"type": "array", "items": {"type": "string"}, "description": "复盘列表"},
                "memories":        {"type": "array", "items": {"type": "string"}, "description": "其他记忆列表"},
            },
        },
    },
    {
        "name": "万忆图谱搜索",
        "description": "知识图谱扩展检索 — 从实体节点出发多跳遍历，发现语义关联记忆（v5.3记忆写入时自动建边：semantic-similar/same-category）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词/实体名"},
                "depth": {"type": "number", "description": "遍历深度", "default": 2},
                "limit": {"type": "number", "description": "返回条数上限", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "万忆睡眠巩固",
        "description": "睡眠巩固周期：记忆衰减 + 重要度增强 + 相似合并 + 低价值归档，定期运行",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "万忆过程存档",
        "description": "过程记忆（ExpeL式）：将任务执行的一个阶段（规划/尝试/纠错/反思/结论）存入轨迹档案，失败自动沉淀错题本，成功结论自动沉淀经验库，可设记忆锚点断点恢复",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_name":   {"type": "string", "description": "任务名称"},
                "phase":       {"type": "string", "description": "阶段：规划/尝试/纠错/反思/结论"},
                "content":     {"type": "string", "description": "该阶段的完整过程内容"},
                "outcome":     {"type": "string", "description": "结果：neutral/success/failure，failure自动入错题本", "default": "neutral"},
                "process_id":  {"type": "string", "description": "轨迹ID（续写同一条轨迹时传入）"},
                "anchor_state": {"type": "object", "description": "设置记忆锚点（断点恢复所需状态）"},
            },
            "required": ["task_name", "phase", "content"],
        },
    },
    {
        "name": "万忆错题本",
        "description": "错题本（Reflexion式）：查看错题/高频错误模式/补充教训。失败决策自动沉淀为反例条目，跨会话防重复犯错",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":     {"type": "string", "description": "list(查看)/patterns(高频模式)/lesson(补充教训)", "default": "list"},
                "task_name":  {"type": "string", "description": "按任务筛选"},
                "mistake_id": {"type": "string", "description": "错题ID（lesson动作需要）"},
                "lesson":     {"type": "string", "description": "教训内容（lesson动作需要）"},
            },
        },
    },
    {
        "name": "万忆经验库",
        "description": "经验库（ExpeL式）：成功路径沉淀的可复用模式，跨任务迁移复用",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_name": {"type": "string", "description": "按任务筛选"},
                "limit":     {"type": "number", "description": "返回条数", "default": 50},
            },
        },
    },
    {
        "name": "万忆查询进化",
        "description": "最近进化记录：谁变了、为什么变、置信度变化 — 进化的可观测性，任何聊天框都能查到真实发生在文件系统上的进化",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "number", "description": "返回条数", "default": 30},
            },
        },
    },
    {
        "name": "万忆园艺师",
        "description": "园艺师后台（KektorDB式）：深巩固（矛盾检测+冗余检测+洞见提炼+技能结晶+每日思考档案）/ 仅写每日日志",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "consolidate(深巩固)/daily_log(每日档案)", "default": "consolidate"},
            },
        },
    },
    {
        "name": "万忆置信度决策检查",
        "description": "护城河#1「拦截之眼」：对即将执行的高风险决策做认知置信度检查。支持：check(决策拦截，自动识别梭哈/追涨/不止损/删库/强推等风险动作，置信度不足时BLOCK并亮历史错题)/validate(对某判断投支持票)/challenge(投反对票)/review(FSRS复习)/get(查置信度)/rank(置信度排名)/needs_review(待复习清单)。在做重仓、追涨、删库、强推等高风险动作前必调用。BLOCK/CAUTION时自动联动护城河#2开立反事实分支。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":        {"type": "string", "description": "check/validate/challenge/review/get/rank/needs_review", "default": "check"},
                "decision_text": {"type": "string", "description": "要检查/反馈的决策描述（check/validate/challenge必填）"},
                "target_type":   {"type": "string", "description": "目标类型：decision/memory/strategy/skill", "default": "decision"},
                "target_id":     {"type": "string", "description": "目标ID（可选，不填则由decision_text自动生成）"},
                "signal":        {"type": "string", "description": "反馈信号：validate(支持)/challenge(反对)", "default": "validate"},
                "reason":        {"type": "string", "description": "反馈理由（challenge时强烈建议填）"},
                "recall_success": {"type": "boolean", "description": "review时必填：回忆是否成功"},
                "elapsed_days":  {"type": "number", "description": "距上次复习天数（review用）", "default": 1.0},
            },
        },
    },
    {
        "name": "万忆反事实之镜",
        "description": "护城河#2「反事实之镜」：在关键决策点开平行分支（事实路径 vs 反事实路径），到期自动结算对比。每次BLOCK/CAUTION拦截时自动开立；支持手动open开分支、settle记录实际结果并自动判定verdict(fact_won/counter_won/neutral)、list_open查待结算、list_settled查已结算、auto_check_due自动检查到期。counter_won时自动沉淀入错题本并强化置信度拦截。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":         {"type": "string", "description": "open/settle/list_open/list_settled/get/auto_check_due", "default": "open"},
                "decision_text":  {"type": "string", "description": "open必填：决策点描述"},
                "decision_type":  {"type": "string", "description": "trade/write/code/other", "default": "other"},
                "risk_level":     {"type": "string", "description": "critical/high/medium/low（影响默认结算天数）", "default": "medium"},
                "fact_path":      {"type": "string", "description": "事实路径：taken(做了)/avoided(没做)", "default": "taken"},
                "counter_path":   {"type": "string", "description": "反事实路径描述（不填则根据风险自动生成）"},
                "fact_outcome":   {"type": "string", "description": "settle必填：实际发生的结果"},
                "counter_outcome":{"type": "string", "description": "settle可选：反事实结果推算（不填则自动推算）"},
                "settlement_days":{"type": "number", "description": "多少天后结算（critical=3天/high=7天/medium=14天/low=30天默认）", "default": 7.0},
                "branch_id":      {"type": "string", "description": "分支ID（settle/get必填）"},
                "lesson":         {"type": "string", "description": "settle可选：手动指定教训"},
                "tags":           {"type": "array", "description": "标签数组", "items": {"type": "string"}},
                "confidence_target_id": {"type": "string", "description": "关联的置信度检查target_id（拦截联动时自动填）"},
            },
        },
    },
    {
        "name": "万忆跨域桥接",
        "description": "护城河#3「跨域类比迁移」：把交易/写作/开发各领域的教训抽象成跨域底层模式，然后跨域桥接——让交易的教训自动提醒写作/开发，反之亦然。BLOCK/CAUTION拦截时自动联动。abstract沉淀模式(abstract_name+essence+keywords)、bridge给定当前决策找跨域同构模式、list_patterns按命中率列出、get看详情。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action":        {"type": "string", "description": "bridge/abstract/list_patterns/get", "default": "bridge"},
                "decision_text": {"type": "string", "description": "bridge必填：当前决策/场景描述"},
                "domain":        {"type": "string", "description": "当前领域：trade/write/code/other", "default": "other"},
                "abstract_name": {"type": "string", "description": "abstract必填：跨域模式名（如'无视止损纪律'）"},
                "essence":       {"type": "string", "description": "abstract必填：底层本质描述（跨域通用）"},
                "keywords":      {"type": "array", "description": "abstract可选：触发关键词数组", "items": {"type": "string"}},
                "source_ref":    {"type": "string", "description": "abstract可选：来源记忆ID/分支ID"},
                "pattern_id":    {"type": "string", "description": "get必填：模式ID"},
                "limit":         {"type": "number", "description": "返回条数上限", "default": 5},
            },
        },
    },
    {
        "name": "万忆轨迹回放",
        "description": "护城河#4「分支轨迹回放」：把历史所有反事实分支串成决策时间线，让你一眼看见每次听劝/不听劝的走向。timeline按时间回放全部分支、stats决策生涯统计(结算率/counter_won率/听劝验证率/风险分布/洞察)、route对比「实际路径 vs 如果全听劝路径」两条虚拟人生、review最近N天决策回顾。决策生涯可视化，越用越看得清自己的进化曲线。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "timeline/stats/route/review", "default": "timeline"},
                "days":   {"type": "number", "description": "review必填：回顾窗口天数", "default": 30},
                "limit":  {"type": "number", "description": "timeline返回条数上限", "default": 100},
            },
        },
    },
    {
        "name": "万忆主动搭档",
        "description": "护城河#5「主动搭档」：从被动工具升级为主动搭档，不等用户开口自动出击。brief今日简报(待结算分支+到期提醒+高命中跨域模式+决策健康提示，LOAD钩子自动调用)、proactive_check主动体检(到期/超期/重复踩坑)、weekly_review每周轨迹回放复盘(stats+route+review合成总结)、alert风险关键词扫描(文本中出现梭哈/追涨/全仓/删库/强推等风险词立即告警并建议过拦截)。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "brief/proactive_check/weekly_review/alert", "default": "brief"},
                "days":   {"type": "number", "description": "weekly_review回顾天数", "default": 7},
                "text":   {"type": "string", "description": "alert必填：要扫描风险的文本"},
            },
        },
    },
    {
        "name": "万忆知识空白",
        "description": "v5.1元认知「知道自己不知道什么」：召回太弱时自动记录知识空白，系统主动承认库存薄弱。list列出待补充空白(按被查中次数排序，越常查越该补)、close标记已补充(gap_id+note)、stats统计(开放数/已关闭数/最薄弱领域TOP)。结合语义向量检索，让万忆在检索到强结果时自信、搜不到时坦承，而不是瞎编。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "list/close/stats", "default": "list"},
                "limit":  {"type": "number", "description": "list返回条数上限", "default": 20},
                "gap_id": {"type": "string", "description": "close必填：知识空白ID"},
                "note":   {"type": "string", "description": "close可选：补充来源说明"},
            },
        },
    },
]


def _get_tool_map():
    """获取工具名→处理函数的映射（ENGINE初始化后调用）"""
    return {
        "万忆召回记忆":       ENGINE.tool_recall_memory,
        "万忆记录见闻":       ENGINE.tool_record_memory,
        "万忆知识压缩":       ENGINE.tool_compress_knowledge,
        "万忆记忆自检":       ENGINE.tool_self_check,
        "万忆存档进度":       ENGINE.tool_save_progress,
        "万忆加载进度":       ENGINE.tool_load_progress,
        "万忆导入档案":       ENGINE.tool_import_user_profile,
        "万忆更新交易锚点":   ENGINE.tool_update_trading_anchor,
        "万忆触发LOAD钩子":   ENGINE.trigger_load_hook,
        "万忆触发STORE钩子":  ENGINE.trigger_store_hook,
        "万忆图谱搜索":       ENGINE.tool_graph_search,
        "万忆睡眠巩固":       ENGINE.tool_sleep_consolidation,
        "万忆过程存档":       ENGINE.tool_process_save,
        "万忆错题本":         ENGINE.tool_mistake_book,
        "万忆经验库":         ENGINE.tool_experience_library,
        "万忆查询进化":       ENGINE.tool_recent_evolution,
        "万忆园艺师":         ENGINE.tool_gardener,
        "万忆置信度决策检查": ENGINE.tool_confidence_check,
        "万忆反事实之镜":     ENGINE.tool_counterfactual_mirror,
        "万忆跨域桥接":       ENGINE.tool_analog_bridge,
        "万忆轨迹回放":       ENGINE.tool_trajectory_replay,
        "万忆主动搭档":       ENGINE.tool_proactive_partner,
        "万忆知识空白":       ENGINE.tool_knowledge_gap,
    }


def handle_request(req: dict) -> dict:
    method = req.get("method", "")
    params = req.get("params", {})
    req_id = req.get("id")

    global ENGINE

    try:
        # ── MCP 标准协议方法 ────────────────────────────────────────
        if method == "initialize":
            # MCP 握手：返回协议版本、服务器信息、能力
            if ENGINE is None:
                ENGINE = WanYiCore()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "万忆中枢·全量之心",
                        "version": "1.0.0",
                        "description": "全量记忆中枢 v5.0「六护城河+向量+精排+图谱+时序+元认知」：事件溯源 + 过程记忆 + 错题本 + 经验库 + 认知置信度决策拦截 + 反事实平行分支 + 跨域类比迁移 + 决策轨迹回放 + 主动简报/体检/周复盘 + 语义向量混合召回 + reranker精排 + 记忆关系图谱 + 时序衰减 + 知识空白元认知，23个MCP工具全局可用",
                    },
                },
            }

        if method == "tools/list":
            if ENGINE is None:
                ENGINE = WanYiCore()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": MCP_TOOLS,
                },
            }

        if method == "tools/call":
            if ENGINE is None:
                ENGINE = WanYiCore()
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            tool_map = _get_tool_map()
            handler = tool_map.get(tool_name)
            if handler is None:
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"Tool not found: {tool_name}"}}
            result = handler(**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": _json_safe_dumps(result),
                        }
                    ],
                },
            }

        # ── 兼容旧模式：直接以工具名为 method 调用 ──────────────────
        if ENGINE is None:
            ENGINE = WanYiCore()
        tool_map = _get_tool_map()
        handler = tool_map.get(method)
        if handler is None:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        result = handler(**params)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e), "data": tb}}


def _json_safe_dumps(obj) -> str:
    """安全序列化结果为JSON字符串（用于MCP text content）"""
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def handle_batch(requests: list) -> list:
    return [handle_request(r) for r in requests]

def _read_exact(n: int) -> bytes:
    """从stdin精确读取n字节"""
    data = b""
    while len(data) < n:
        chunk = sys.stdin.buffer.read(n - len(data))
        if not chunk:
            raise EOFError()
        data += chunk
    return data


def _read_message() -> dict | None:
    """读取一条MCP消息（Content-Length帧协议）"""
    import json as _json
    # 读取头部直到空行
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        line = line.decode("ascii", errors="replace").strip()
        if not line:
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    # 获取Content-Length
    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return None
    # 读取body
    body = _read_exact(content_length)
    try:
        return _json.loads(body.decode("utf-8"))
    except _json.JSONDecodeError:
        return None


def _write_message(msg: dict):
    """写入一条MCP消息（Content-Length帧协议）"""
    import json as _json
    body = _json.dumps(msg, ensure_ascii=False).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def main():
    """标准MCP stdio传输层（Content-Length帧协议）"""
    # 通知类型的方法（不需要响应）
    NOTIFICATION_METHODS = {
        "notifications/initialized",
        "notifications/cancelled",
        "$/cancelRequest",
    }
    while True:
        try:
            req = _read_message()
        except EOFError:
            break
        if req is None:
            continue
        # 通知（无id）不需要响应
        if isinstance(req, dict) and "id" not in req:
            method = req.get("method", "")
            if method not in NOTIFICATION_METHODS:
                # 处理非标准通知（但不响应）
                pass
            continue
        if isinstance(req, list):
            # 批量请求
            responses = []
            for r in req:
                if "id" in r:
                    resp = handle_request(r)
                    responses.append(resp)
            for resp in responses:
                _write_message(resp)
        else:
            resp = handle_request(req)
            if resp is not None:
                _write_message(resp)

if __name__ == "__main__":
    main()
