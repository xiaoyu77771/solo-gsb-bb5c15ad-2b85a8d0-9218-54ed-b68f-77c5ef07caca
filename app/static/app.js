/* 两两决策台 — 原生前端 */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let state = null;
  let focusIdx = 0;      // 在 pending 数组中的位置
  let matrixMode = "d";  // d: 直接偏好  p: 最强路径
  let toastTimer = null;

  const api = async (path, options = {}) => {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `请求失败 (${res.status})`);
    return data;
  };

  const toast = (msg, isError = false) => {
    const el = $("toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.hidden = true; }, 2400);
  };

  const names = () => {
    const m = {};
    (state?.candidates || []).forEach((c) => { m[c.index] = c.name; });
    return m;
  };

  const pendingPairKey = (pair) => pair.join(",");

  // ------------------------------------------------------------------ 渲染
  function render() {
    const hasRound = !!(state && state.round);
    $("setup-view").hidden = hasRound;
    $("arena-view").hidden = !hasRound;
    if (!hasRound) return;

    renderStatus();
    renderFocus();
    renderRanking();
    renderPending();
    renderHistory();
    renderMatrix();
  }

  function renderStatus() {
    const t = state.totals;
    $("cand-count").textContent = state.candidates.length;
    $("judged-count").textContent = t.judged;
    $("total-count").textContent = t.total;
    $("dec-count").textContent = t.decisive;
    $("tie-count").textContent = t.ties;
    $("progress-bar").style.width = t.pct + "%";
    const done = state.round.status === "completed";
    $("complete-banner").hidden = !done;
    $("undo-btn").disabled = t.judged === 0;
  }

  function renderFocus() {
    const pending = state.pending;
    if (focusIdx >= pending.length) focusIdx = Math.max(0, pending.length - 1);
    const pair = pending[focusIdx];
    const nm = names();

    $("focus-pair").hidden = !pair;
    $("no-pending").hidden = !!pair;
    if (pair) {
      const [a, b] = pair;
      $("name-a").textContent = nm[a];
      $("name-b").textContent = nm[b];
    }
  }

  function renderRanking() {
    const ol = $("ranking");
    ol.innerHTML = "";
    // 并列组规模
    const groupSize = {};
    state.candidates.forEach((c) => {
      groupSize[c.rank] = (groupSize[c.rank] || 0) + 1;
    });
    state.candidates.forEach((c) => {
      const li = document.createElement("li");
      const badge = document.createElement("span");
      badge.className = "rank-badge";
      badge.textContent = c.rank;
      const palette = ["#4f8cff", "#8b6cf6", "#35d0a3", "#e8913a", "#e3608b",
        "#5ec8e8", "#c9a227", "#9aa7c2"];
      badge.style.background = palette[(c.rank - 1) % palette.length];

      const name = document.createElement("span");
      name.className = "rank-name";
      name.textContent = c.name;
      if (groupSize[c.rank] > 1) {
        const flag = document.createElement("span");
        flag.className = "tie-flag";
        flag.textContent = "并列";
        name.appendChild(flag);
      }

      const stat = document.createElement("span");
      stat.className = "rank-stat";
      stat.textContent = `胜 ${c.wins} · 负 ${c.losses} · 平 ${c.ties}`;

      li.append(badge, name, stat);
      ol.appendChild(li);
    });
  }

  function renderPending() {
    const box = $("pending-list");
    box.innerHTML = "";
    $("pending-num").textContent = state.pending.length;
    const nm = names();
    if (state.pending.length === 0) {
      box.innerHTML = '<span class="empty-note">全部组合均已评判 ✓</span>';
      return;
    }
    state.pending.forEach(([a, b], i) => {
      const chip = document.createElement("button");
      chip.className = "chip" + (i === focusIdx ? " current" : "");
      chip.textContent = `${nm[a]} ⇄ ${nm[b]}`;
      chip.addEventListener("click", () => { focusIdx = i; render(); });
      box.appendChild(chip);
    });
  }

  function renderHistory() {
    const ul = $("history-list");
    ul.innerHTML = "";
    const nm = names();
    $("history-num").textContent = state.comparisons.length;
    if (state.comparisons.length === 0) {
      ul.innerHTML = '<li class="empty-note">尚无判断记录</li>';
      return;
    }
    // 最近的在前
    [...state.comparisons].reverse().forEach((c) => {
      const li = document.createElement("li");
      if (c.winner === null) {
        li.innerHTML =
          `<span class="h-tie">平局</span>` +
          `<span class="h-loser">${escapeHtml(nm[c.a])} ＝ ${escapeHtml(nm[c.b])}</span>`;
      } else {
        const loserIdx = c.winner === c.a ? c.b : c.a;
        li.innerHTML =
          `<span class="h-winner">${escapeHtml(nm[c.winner])}</span>` +
          `<span class="h-loser">≻ ${escapeHtml(nm[loserIdx])}</span>`;
      }
      const time = document.createElement("span");
      time.className = "h-time";
      time.textContent = fmtTime(c.created_at);
      li.appendChild(time);
      ul.appendChild(li);
    });
  }

  function renderMatrix() {
    const table = $("matrix-table");
    table.innerHTML = "";
    const m = state.matrix[matrixMode];
    const nm = names();
    const ordered = state.candidates; // 已按名次排序

    $("matrix-hint").innerHTML = matrixMode === "d"
      ? "行优于列记 <strong>1</strong>，否则记 <strong>0</strong>；平局两侧均为 0。对角线为 —。"
      : "<code>p[i][j]</code> 为 i→j 的最强路径强度（路径各段最小强度的最大值）；" +
        "<code>p[i][j] &gt; p[j][i]</code> 表示 i 排在 j 前。";

    const caption = document.createElement("caption");
    caption.textContent = matrixMode === "d"
      ? "d[i][j]：直接偏好（1 = 行击败列）"
      : "p[i][j]：最强路径强度（Schulze）";
    table.appendChild(caption);

    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    headRow.appendChild(document.createElement("th"));
    ordered.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = short(c.name);
      th.title = c.name;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    ordered.forEach((rowCand) => {
      const tr = document.createElement("tr");
      const th = document.createElement("th");
      th.className = "row-head";
      th.textContent = short(rowCand.name);
      th.title = rowCand.name;
      tr.appendChild(th);

      ordered.forEach((colCand) => {
        const td = document.createElement("td");
        const i = rowCand.index, j = colCand.index;
        if (i === j) {
          td.textContent = "—";
          td.className = "diag";
        } else {
          const v = m[i][j];
          td.textContent = v;
          td.className = v > 0 ? "pos" : "zero";
        }
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
  }

  // ------------------------------------------------------------------ 动作
  async function castVote(a, b, winner) {
    try {
      state = await api("/api/round/vote", {
        method: "POST",
        body: JSON.stringify({ a, b, winner }),
      });
      // 该对从未决列表消失；focusIdx 自然指向下一对（末尾时已由 render 收敛）
      render();
      const left = state.pending.length;
      toast(left > 0 ? `已记录，还剩 ${left} 对` : "本轮全部完成 🎉");
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function undo() {
    if (!state || state.comparisons.length === 0) return;
    const last = state.comparisons[state.comparisons.length - 1];
    const undone = [Math.min(last.a, last.b), Math.max(last.a, last.b)];
    try {
      state = await api("/api/round/undo", { method: "POST" });
      // 撤销后把焦点定位到刚恢复的组合，便于改判
      const at = state.pending.findIndex(
        (p) => p[0] === undone[0] && p[1] === undone[1]
      );
      if (at >= 0) focusIdx = at;
      render();
      toast("已撤销最近一次判断");
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function resetRound() {
    if (!confirm("确定清空本轮全部判断吗？候选项保留，进度将从零开始。")) return;
    try {
      state = await api("/api/round/reset", { method: "POST" });
      focusIdx = 0;
      render();
      toast("本轮已重置");
    } catch (err) {
      toast(err.message, true);
    }
  }

  function newRound() {
    if (!confirm("返回录入页并开始新一轮？当前本轮数据将被清除。")) return;
    state = null;
    $("candidate-input").value = "";
    focusIdx = 0;
    render();
  }

  async function startRound() {
    const lines = $("candidate-input").value
      .split("\n").map((s) => s.trim()).filter(Boolean);
    const uniq = [...new Set(lines)];
    const errEl = $("setup-error");
    if (uniq.length < 3 || uniq.length > 12) {
      errEl.textContent = `需要 3～12 个互不重复的候选项（当前 ${uniq.length} 个）`;
      errEl.hidden = false;
      return;
    }
    errEl.hidden = true;
    try {
      state = await api("/api/round", {
        method: "POST",
        body: JSON.stringify({ candidates: uniq }),
      });
      focusIdx = 0;
      render();
    } catch (err) {
      toast(err.message, true);
    }
  }

  // ------------------------------------------------------------------ 工具
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[ch]));
  }
  function short(s) { return s.length > 8 ? s.slice(0, 7) + "…" : s; }
  function fmtTime(iso) {
    try { return new Date(iso).toLocaleTimeString("zh-CN", { hour12: false }); }
    catch { return iso; }
  }

  // ------------------------------------------------------------------ 事件
  $("start-btn").addEventListener("click", startRound);
  $("undo-btn").addEventListener("click", undo);
  $("reset-btn").addEventListener("click", resetRound);
  $("new-round-btn").addEventListener("click", newRound);
  $("pick-a").addEventListener("click", () => {
    const [a, b] = state.pending[focusIdx];
    castVote(a, b, a);
  });
  $("pick-b").addEventListener("click", () => {
    const [a, b] = state.pending[focusIdx];
    castVote(a, b, b);
  });
  $("pick-tie").addEventListener("click", () => {
    const [a, b] = state.pending[focusIdx];
    castVote(a, b, null);
  });
  document.querySelectorAll(".seg-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      matrixMode = btn.dataset.matrix;
      document.querySelectorAll(".seg-btn").forEach(
        (b) => b.classList.toggle("active", b === btn)
      );
      if (state) renderMatrix();
    });
  });
  document.addEventListener("keydown", (e) => {
    if (!state || !state.round) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
      e.preventDefault();
      undo();
      return;
    }
    if (state.pending.length === 0) return;
    if (e.key === "ArrowLeft") {
      const [a, b] = state.pending[focusIdx];
      castVote(a, b, a);
    } else if (e.key === "ArrowRight") {
      const [a, b] = state.pending[focusIdx];
      castVote(a, b, b);
    } else if (e.key.toLowerCase() === "t") {
      const [a, b] = state.pending[focusIdx];
      castVote(a, b, null);
    }
  });

  // 初始加载（刷新后恢复进度）
  (async () => {
    try {
      state = await api("/api/state");
      focusIdx = 0;
      render();
    } catch (err) {
      toast(err.message, true);
    }
  })();
})();
