const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...opts.headers },
    ...opts,
  });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const msg = data?.detail ?? data?.message ?? res.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/'/g, "&#39;");
}

function numOrNull(s) {
  const t = String(s ?? "").trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function linesToList(textarea) {
  return String(textarea.value || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
}

function listToLines(arr) {
  if (!arr || !arr.length) return "";
  return arr.join("\n");
}

function renderWatchlist(items) {
  const tbody = $("#tbl-watchlist tbody");
  const empty = $("#watchlist-empty");
  const table = $("#tbl-watchlist");
  const holdHint = $("#watchlist-holding-hint");
  tbody.innerHTML = "";
  if (!items.length) {
    empty.classList.remove("hidden");
    table.classList.add("hidden");
    holdHint.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  table.classList.remove("hidden");
  holdHint.classList.remove("hidden");
  for (const it of items) {
    const m = it.cached_meta;
    const sn = m && m.security_name ? m.security_name : "—";
    const ind = m && m.industry ? m.industry : "—";
    const sec = m && m.sector ? m.sector : "—";
    const costStr =
      it.position_cost != null && it.position_cost !== ""
        ? String(it.position_cost)
        : "";
    const qtyStr =
      it.position_quantity != null && it.position_quantity !== ""
        ? String(it.position_quantity)
        : "";

    const tr1 = document.createElement("tr");
    tr1.className = "watchlist-main-row";
    tr1.innerHTML = `
      <td><strong>${escapeHtml(it.code)}</strong></td>
      <td>${escapeHtml(it.name || "—")}</td>
      <td>${escapeHtml(it.asset_type || "auto")}</td>
      <td class="cell-meta">${escapeHtml(sn)}</td>
      <td class="cell-meta">${escapeHtml(ind)}</td>
      <td class="cell-meta">${escapeHtml(sec)}</td>
      <td class="actions">
        <button type="button" class="btn-sm analyze" data-code="${escapeAttr(it.code)}">分析</button>
        <button type="button" class="btn-sm btn-danger remove" data-code="${escapeAttr(it.code)}">删除</button>
      </td>
    `;
    tbody.appendChild(tr1);

    const tr2 = document.createElement("tr");
    tr2.className = "watchlist-holding-row";
    tr2.dataset.code = it.code;
    tr2.innerHTML = `
      <td colspan="7" class="holding-cell">
        <div class="holding-grid">
          <label class="holding-field">持仓成本（元/股或份）
            <input type="text" class="inp-cost" inputmode="decimal" value="${escapeAttr(costStr)}" placeholder="可选" />
          </label>
          <label class="holding-field">持仓数量（股/份）
            <input type="text" class="inp-qty" inputmode="decimal" value="${escapeAttr(qtyStr)}" placeholder="可选" />
          </label>
          <label class="holding-field holding-notes">备注
            <input type="text" class="inp-notes" value="${escapeAttr(it.notes || "")}" placeholder="分析时交给模型" />
          </label>
          <button type="button" class="btn-sm save-holding" data-code="${escapeAttr(it.code)}">保存持仓</button>
        </div>
      </td>
    `;
    tbody.appendChild(tr2);
  }
  tbody.querySelectorAll("button.analyze").forEach((btn) => {
    btn.addEventListener("click", () => runAnalyze(btn.dataset.code));
  });
  tbody.querySelectorAll("button.remove").forEach((btn) => {
    btn.addEventListener("click", () => removeItem(btn.dataset.code));
  });
  tbody.querySelectorAll("button.save-holding").forEach((btn) => {
    btn.addEventListener("click", () => saveHolding(btn));
  });
}

async function saveHolding(btn) {
  const row = btn.closest("tr.watchlist-holding-row");
  if (!row) return;
  const code = row.dataset.code;
  const cost = row.querySelector(".inp-cost");
  const qty = row.querySelector(".inp-qty");
  const notes = row.querySelector(".inp-notes");
  const prev = btn.textContent;
  btn.disabled = true;
  btn.textContent = "保存中…";
  try {
    await api(`/api/watchlist/${encodeURIComponent(code)}/holding`, {
      method: "PUT",
      body: JSON.stringify({
        position_cost: numOrNull(cost.value),
        position_quantity: numOrNull(qty.value),
        notes: notes.value.trim(),
      }),
    });
    btn.textContent = "已保存";
    setTimeout(() => {
      btn.textContent = prev;
    }, 1200);
  } catch (e) {
    alert("保存失败：" + (e.message || e));
    btn.textContent = prev;
  } finally {
    btn.disabled = false;
  }
}

async function loadWatchlist() {
  const data = await api("/api/watchlist");
  renderWatchlist(data.items || []);
}

async function loadTradingPreferences() {
  const { preferences: p } = await api("/api/trading-preferences");
  $("#tp-risk").value = p.risk_tolerance || "";
  $("#tp-horizon").value = p.investment_horizon || "";
  $("#tp-maxpct").value =
    p.max_single_position_pct != null && p.max_single_position_pct !== ""
      ? String(p.max_single_position_pct)
      : "";
  $("#tp-avoid-ind").value = listToLines(p.avoid_industries);
  $("#tp-avoid-kw").value = listToLines(p.avoid_keywords);
  $("#tp-focus").value = listToLines(p.focus_themes);
  $("#tp-must").value = p.must_follow_text || "";
}

async function saveTradingPreferences(ev) {
  ev.preventDefault();
  const maxRaw = $("#tp-maxpct").value.trim();
  let maxPct = null;
  if (maxRaw !== "") {
    const n = Number(maxRaw);
    maxPct = Number.isFinite(n) ? n : null;
  }
  try {
    await api("/api/trading-preferences", {
      method: "PUT",
      body: JSON.stringify({
        risk_tolerance: $("#tp-risk").value.trim(),
        investment_horizon: $("#tp-horizon").value.trim(),
        max_single_position_pct: maxPct,
        avoid_industries: linesToList($("#tp-avoid-ind")),
        avoid_keywords: linesToList($("#tp-avoid-kw")),
        focus_themes: linesToList($("#tp-focus")),
        must_follow_text: $("#tp-must").value,
      }),
    });
    alert("交易偏好已保存。");
    await loadTradingPreferences();
  } catch (e) {
    alert("保存失败：" + (e.message || e));
  }
}

async function addItem(ev) {
  ev.preventDefault();
  const code = $("#inp-code").value.trim();
  const name = $("#inp-name").value.trim();
  const asset_type = $("#inp-type").value;
  if (!code) return;
  await api("/api/watchlist", {
    method: "POST",
    body: JSON.stringify({ code, name, asset_type }),
  });
  $("#inp-code").value = "";
  $("#inp-name").value = "";
  await loadWatchlist();
}

async function removeItem(code) {
  if (!confirm(`从自选删除 ${code}？`)) return;
  await api(`/api/watchlist/${encodeURIComponent(code)}`, { method: "DELETE" });
  await loadWatchlist();
}

function clearAnalysisIssues() {
  const wrap = $("#analysis-issues");
  wrap.innerHTML = "";
  wrap.classList.add("hidden");
}

function renderAnalysisIssues(issues) {
  const wrap = $("#analysis-issues");
  wrap.innerHTML = "";
  if (!issues || !issues.length) {
    wrap.classList.add("hidden");
    return;
  }
  wrap.classList.remove("hidden");
  for (const it of issues) {
    const div = document.createElement("div");
    const level = it.level === "error" ? "error" : "warn";
    div.className = `issue-item issue-${level}`;
    const strong = document.createElement("strong");
    strong.textContent = it.title || it.code || "提示";
    const p = document.createElement("p");
    p.textContent = it.detail || "";
    div.appendChild(strong);
    div.appendChild(p);
    wrap.appendChild(div);
  }
}

async function runAnalyze(code) {
  const pre = $("#analysis-json");
  const stepsWrap = $("#analysis-steps-wrap");
  const stepsPre = $("#analysis-steps");
  $("#analysis-placeholder").classList.add("hidden");
  clearAnalysisIssues();
  pre.classList.remove("hidden");
  pre.textContent = "分析中…";
  stepsWrap.classList.add("hidden");
  try {
    const data = await api(`/api/analyze/${encodeURIComponent(code)}`, {
      method: "POST",
    });
    renderAnalysisIssues(data.issues);
    if (!data.success) {
      pre.textContent = JSON.stringify(
        { error: data.error || "failed", steps: data.steps },
        null,
        2
      );
      if (data.steps && data.steps.length) {
        stepsPre.textContent = JSON.stringify(data.steps, null, 2);
        stepsWrap.classList.remove("hidden");
      }
      return;
    }
    const syn = data.synthesis || {};
    pre.textContent = JSON.stringify(
      {
        decision: syn.decision,
        confidence: syn.confidence,
        reason: syn.reason,
        etf_code: syn.etf_code,
        rule_signals: syn.rule_signals,
        llm_explain_degraded: syn.llm_explain_degraded,
        llm_refine_failed: syn.llm_refine_failed,
      },
      null,
      2
    );
    stepsPre.textContent = JSON.stringify(data.steps, null, 2);
    stepsWrap.classList.remove("hidden");
  } catch (e) {
    renderAnalysisIssues([
      {
        level: "error",
        code: "network",
        title: "请求失败（网络或服务未启动）",
        detail: String(e.message || e),
      },
    ]);
    pre.textContent = JSON.stringify({ error: String(e.message || e) }, null, 2);
  }
}

async function refreshSymbolMeta() {
  const btn = $("#btn-refresh-meta");
  const prev = btn?.textContent;
  if (btn) {
    btn.disabled = true;
    btn.textContent = "拉取中…";
  }
  try {
    await api("/api/symbol-meta/refresh", {
      method: "POST",
      body: JSON.stringify({}),
    });
    await loadWatchlist();
  } catch (e) {
    alert("刷新资料失败：" + (e.message || e));
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = prev || "刷新资料";
    }
  }
}

$("#form-add").addEventListener("submit", addItem);
$("#form-prefs").addEventListener("submit", saveTradingPreferences);
$("#btn-refresh").addEventListener("click", loadWatchlist);
$("#btn-refresh-meta").addEventListener("click", () => {
  refreshSymbolMeta().catch((e) => console.error(e));
});

Promise.all([loadWatchlist(), loadTradingPreferences()]).catch((e) => {
  console.error(e);
  alert("无法加载页面数据：" + e);
});
