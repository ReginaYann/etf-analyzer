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

function renderWatchlist(items) {
  const tbody = $("#tbl-watchlist tbody");
  const empty = $("#watchlist-empty");
  const table = $("#tbl-watchlist");
  tbody.innerHTML = "";
  if (!items.length) {
    empty.classList.remove("hidden");
    table.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  table.classList.remove("hidden");
  for (const it of items) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><strong>${escapeHtml(it.code)}</strong></td>
      <td>${escapeHtml(it.name || "—")}</td>
      <td>${escapeHtml(it.asset_type || "auto")}</td>
      <td class="actions">
        <button type="button" class="btn-sm analyze" data-code="${escapeAttr(it.code)}">分析</button>
        <button type="button" class="btn-sm btn-danger remove" data-code="${escapeAttr(it.code)}">删除</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
  tbody.querySelectorAll("button.analyze").forEach((btn) => {
    btn.addEventListener("click", () => runAnalyze(btn.dataset.code));
  });
  tbody.querySelectorAll("button.remove").forEach((btn) => {
    btn.addEventListener("click", () => removeItem(btn.dataset.code));
  });
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

async function loadWatchlist() {
  const data = await api("/api/watchlist");
  renderWatchlist(data.items || []);
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

async function runAnalyze(code) {
  const pre = $("#analysis-json");
  const stepsWrap = $("#analysis-steps-wrap");
  const stepsPre = $("#analysis-steps");
  $("#analysis-placeholder").classList.add("hidden");
  pre.classList.remove("hidden");
  pre.textContent = "分析中…";
  stepsWrap.classList.add("hidden");
  try {
    const data = await api(`/api/analyze/${encodeURIComponent(code)}`, {
      method: "POST",
    });
    if (!data.success) {
      pre.textContent = JSON.stringify(
        { error: data.error || "failed", steps: data.steps },
        null,
        2
      );
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
      },
      null,
      2
    );
    stepsPre.textContent = JSON.stringify(data.steps, null, 2);
    stepsWrap.classList.remove("hidden");
  } catch (e) {
    pre.textContent = String(e.message || e);
  }
}

$("#form-add").addEventListener("submit", addItem);
$("#btn-refresh").addEventListener("click", loadWatchlist);
loadWatchlist().catch((e) => {
  console.error(e);
  alert("无法加载自选：" + e);
});
