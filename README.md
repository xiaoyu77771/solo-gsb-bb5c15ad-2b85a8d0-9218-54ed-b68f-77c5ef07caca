# 两两决策台（Pairwise Decision Desk）

逐对评审 3～12 个候选方案，按 **Schulze 最强路径法**实时计算排名的轻量 Web 应用。

- 粘贴候选项（每行一个），系统逐对展示，记录「A 胜 / B 胜 / 平局」
- 服务端按 Schulze 方法（Floyd–Warshall 最强路径）实时计算排名，明确显示**并列组**
- 显示**尚未比较的组合**（可点击直接切换）、**直接偏好矩阵 d** 与**最强路径矩阵 p**
- 支持**撤销最近一次判断**（按钮或 `Ctrl+Z`）、**重置本轮**、开始新一轮
- 进度保存在 SQLite，**刷新/重启浏览器后进度保留**（数据卷持久化）
- 技术栈：FastAPI + SQLite + 原生 HTML/CSS/JavaScript，无前端构建步骤

## 一条命令启动

```bash
docker compose up -d --build
```

该命令会：安装依赖 → 构建镜像 → 启动服务时自动建库（SQLite 表自动创建）→ 后台运行。

打开浏览器访问：

```
http://localhost:8000
```

停止：`docker compose down`；停止并删除数据：`docker compose down -v`。

## 配置

全部配置均为可选（默认值即可直接运行），通过环境变量或 `docker-compose.yml` 的 `environment` 段设置：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PORT` | `8000` | 服务监听端口（容器内） |
| `HOST` | `0.0.0.0` | 监听地址 |
| `DB_PATH` | `/app/data/deciders.db` | SQLite 数据库文件路径，目录不存在会自动创建 |

**网页地址与端口**：默认 `http://localhost:8000`。若宿主机端口冲突，修改
`docker-compose.yml` 中 `"8000:8000"` 的左侧端口，例如 `"8080:8000"` 后改用
`http://localhost:8080` 访问。

数据保存在 Docker 命名卷 `decider-data`（挂载到 `/app/data`），重建容器不丢失。

## 本地开发（不使用 Docker）

需要 Python 3.10+：

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

数据库默认创建在 `./data/deciders.db`（可用 `DB_PATH` 覆盖）。

## Schulze 排名说明

- 每对比较只保留一次判断；`d[i][j]` 为直接偏好：认为 i 优于 j 记 `1`，平局两侧记 `0`。
- 最强路径强度 `p[i][j] = max（所有 i→j 路径上“最弱一环”的强度）`，由 Floyd–Warshall 计算。
- `p[i][j] > p[j][i]` 时 i 排在 j 前面；彼此不可区分的候选项归入同一**并列组**，名次相同。
- 尚未评判的组合按「无偏好」参与计算，因此排名会随判断实时变化；全部组合评判完毕后即最终排名。

## API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/state` | 获取当前轮次、排名、矩阵、待判/已判列表 |
| POST | `/api/round` | 新建本轮（body: `{"candidates": ["…", "…"]}`，3～12 项） |
| POST | `/api/round/vote` | 提交一对判断（`a`、`b` 为下标；`winner` 为胜方下标，`null` 为平局） |
| POST | `/api/round/undo` | 撤销最近一次判断 |
| POST | `/api/round/reset` | 清空本轮全部判断，保留候选项 |

界面快捷键：`←` 左侧胜、`→` 右侧胜、`T` 平局、`Ctrl+Z` 撤销。
