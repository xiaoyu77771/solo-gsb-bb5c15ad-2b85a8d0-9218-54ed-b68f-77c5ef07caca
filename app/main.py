"""两两决策台 (Pairwise Decision Desk)

FastAPI + SQLite 后端：
- 维护单轮评审（3~12 个候选项）
- 记录两两比较结果（A 胜 / B 胜 / 平局）
- 按 Schulze 最强路径法实时计算排名
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "deciders.db"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MIN_CANDIDATES = 3
MAX_CANDIDATES = 12

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="两两决策台", version="1.0.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# 数据库
# --------------------------------------------------------------------------- #
@contextmanager
def db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS rounds (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                status     TEXT NOT NULL DEFAULT 'active',  -- active / completed
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS candidates (
                round_id INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                idx      INTEGER NOT NULL,
                name     TEXT NOT NULL,
                PRIMARY KEY (round_id, idx)
            );
            CREATE TABLE IF NOT EXISTS comparisons (
                round_id   INTEGER NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
                a          INTEGER NOT NULL,
                b          INTEGER NOT NULL,
                winner     INTEGER,            -- NULL 表示平局
                created_at TEXT NOT NULL,
                PRIMARY KEY (round_id, a, b)
            );
            """
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_active_round(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM rounds WHERE status IN ('active', 'completed') "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()


# --------------------------------------------------------------------------- #
# Schulze 最强路径法
# --------------------------------------------------------------------------- #
def strongest_paths(d: List[List[int]], n: int) -> List[List[int]]:
    """由直接偏好矩阵 d 计算最强路径强度矩阵 p（Floyd-Warshall 变体）。"""
    p = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                p[i][j] = d[i][j]
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            for k in range(n):
                if j == k or i == k:
                    continue
                p[j][k] = max(p[j][k], min(p[j][i], p[i][k]))
    return p


def compute_standings(
    candidates: List[sqlite3.Row], comparisons: List[sqlite3.Row]
) -> Dict:
    n = len(candidates)
    d: List[List[int]] = [[0] * n for _ in range(n)]
    stats = [
        {"index": i, "name": candidates[i]["name"],
         "wins": 0, "losses": 0, "ties": 0}
        for i in range(n)
    ]
    judged: set[Tuple[int, int]] = set()
    decisive = 0
    tie_count = 0

    for c in comparisons:
        a, b, winner = c["a"], c["b"], c["winner"]
        judged.add((min(a, b), max(a, b)))
        if winner is None:
            stats[a]["ties"] += 1
            stats[b]["ties"] += 1
            tie_count += 1
        else:
            loser = b if winner == a else a
            d[winner][loser] = 1
            stats[winner]["wins"] += 1
            stats[loser]["losses"] += 1
            decisive += 1

    p = strongest_paths(d, n) if n else []

    # p[i][j] > p[j][i] ⇒ i 优于 j；Schulze 关系是弱序，按“击败人数”分组即并列组
    beaten = [
        sum(1 for j in range(n) if i != j and p[i][j] > p[j][i])
        for i in range(n)
    ]
    loses_to = [
        sum(1 for j in range(n) if i != j and p[j][i] > p[i][j])
        for i in range(n)
    ]
    rank_of: Dict[int, int] = {}
    groups: Dict[Tuple[int, int], List[int]] = {}
    for i in range(n):
        groups.setdefault((beaten[i], loses_to[i]), []).append(i)
    ordered_keys = sorted(groups, key=lambda key: (-key[0], key[1]))
    for rank, key in enumerate(ordered_keys, start=1):
        for i in groups[key]:
            rank_of[i] = rank

    ranked = sorted(
        stats,
        key=lambda s: (rank_of[s["index"]], -s["wins"], s["name"]),
    )
    for s in ranked:
        s["rank"] = rank_of[s["index"]]

    all_pairs = {(i, j) for i in range(n) for j in range(i + 1, n)}
    pending = sorted(all_pairs - judged)
    total = n * (n - 1) // 2

    return {
        "candidates": ranked,
        "comparisons": [
            {"a": c["a"], "b": c["b"], "winner": c["winner"],
             "created_at": c["created_at"]}
            for c in comparisons
        ],
        "pending": [[a, b] for a, b in pending],
        "matrix": {"d": d, "p": p},
        "totals": {
            "judged": len(judged),
            "total": total,
            "pct": round(100 * len(judged) / total) if total else 0,
            "decisive": decisive,
            "ties": tie_count,
        },
    }


def build_state(conn: sqlite3.Connection) -> Dict:
    row = get_active_round(conn)
    if row is None:
        return {"round": None, "candidates": [], "comparisons": [],
                "pending": [], "matrix": {"d": [], "p": []},
                "totals": {"judged": 0, "total": 0, "pct": 0,
                           "decisive": 0, "ties": 0}}
    candidates = conn.execute(
        "SELECT * FROM candidates WHERE round_id = ? ORDER BY idx",
        (row["id"],),
    ).fetchall()
    comparisons = conn.execute(
        "SELECT * FROM comparisons WHERE round_id = ? ORDER BY created_at, rowid",
        (row["id"],),
    ).fetchall()
    standings = compute_standings(candidates, comparisons)
    return {
        "round": {
            "id": row["id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        },
        **standings,
    }


def refresh_status(conn: sqlite3.Connection, round_id: int) -> None:
    n = conn.execute(
        "SELECT COUNT(*) FROM candidates WHERE round_id = ?", (round_id,)
    ).fetchone()[0]
    judged = conn.execute(
        "SELECT COUNT(*) FROM comparisons WHERE round_id = ?", (round_id,)
    ).fetchone()[0]
    total = n * (n - 1) // 2
    status = "completed" if n and judged == total else "active"
    conn.execute(
        "UPDATE rounds SET status = ?, updated_at = ? WHERE id = ?",
        (status, now_iso(), round_id),
    )


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class RoundIn(BaseModel):
    candidates: List[str] = Field(..., min_length=MIN_CANDIDATES,
                                  max_length=MAX_CANDIDATES)


class VoteIn(BaseModel):
    a: int
    b: int
    winner: Optional[int] = None


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #
@app.get("/api/state")
def get_state() -> Dict:
    with db() as conn:
        return build_state(conn)


@app.post("/api/round")
def create_round(payload: RoundIn) -> Dict:
    # 去空白、去空行、按出现顺序去重
    seen: set[str] = set()
    names: List[str] = []
    for raw in payload.candidates:
        name = raw.strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not (MIN_CANDIDATES <= len(names) <= MAX_CANDIDATES):
        raise HTTPException(
            status_code=422,
            detail=f"需要 {MIN_CANDIDATES}~{MAX_CANDIDATES} 个互不重复的候选项，"
                   f"当前有效项为 {len(names)} 个",
        )

    ts = now_iso()
    with db() as conn:
        # 单轮应用：开始新一轮时清空旧数据
        conn.execute("DELETE FROM comparisons")
        conn.execute("DELETE FROM candidates")
        conn.execute("DELETE FROM rounds")
        cur = conn.execute(
            "INSERT INTO rounds (status, created_at, updated_at) "
            "VALUES ('active', ?, ?)",
            (ts, ts),
        )
        round_id = cur.lastrowid
        conn.executemany(
            "INSERT INTO candidates (round_id, idx, name) VALUES (?, ?, ?)",
            [(round_id, i, name) for i, name in enumerate(names)],
        )
        return build_state(conn)


@app.post("/api/round/vote")
def vote(payload: VoteIn) -> Dict:
    with db() as conn:
        row = get_active_round(conn)
        if row is None:
            raise HTTPException(status_code=404, detail="尚未开始评审")
        round_id = row["id"]
        n = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE round_id = ?", (round_id,)
        ).fetchone()[0]

        a, b = payload.a, payload.b
        if not (0 <= a < n and 0 <= b < n) or a == b:
            raise HTTPException(status_code=422, detail="无效的候选项组合")
        if payload.winner is not None and payload.winner not in (a, b):
            raise HTTPException(status_code=422, detail="胜者必须是参与比较的一方，或为空表示平局")

        lo, hi = sorted((a, b))
        exists = conn.execute(
            "SELECT 1 FROM comparisons WHERE round_id = ? AND a = ? AND b = ?",
            (round_id, lo, hi),
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="该组合已经评判，请先撤销后再改判")

        conn.execute(
            "INSERT INTO comparisons (round_id, a, b, winner, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (round_id, lo, hi, payload.winner, now_iso()),
        )
        refresh_status(conn, round_id)
        return build_state(conn)


@app.post("/api/round/undo")
def undo() -> Dict:
    with db() as conn:
        row = get_active_round(conn)
        if row is None:
            raise HTTPException(status_code=404, detail="尚未开始评审")
        latest = conn.execute(
            "SELECT a, b FROM comparisons WHERE round_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        if latest is None:
            raise HTTPException(status_code=409, detail="没有可撤销的判断")
        conn.execute(
            "DELETE FROM comparisons WHERE round_id = ? AND a = ? AND b = ?",
            (row["id"], latest["a"], latest["b"]),
        )
        refresh_status(conn, row["id"])
        return build_state(conn)


@app.post("/api/round/reset")
def reset() -> Dict:
    with db() as conn:
        row = get_active_round(conn)
        if row is None:
            raise HTTPException(status_code=404, detail="尚未开始评审")
        conn.execute("DELETE FROM comparisons WHERE round_id = ?", (row["id"],))
        refresh_status(conn, row["id"])
        return build_state(conn)


# --------------------------------------------------------------------------- #
# 静态页面
# --------------------------------------------------------------------------- #
@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")),
          name="static")
