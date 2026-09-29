// 剪辑素材授权覆盖台 — 原生 JS 核验界面

const API = "";
let currentProject = null;
let currentProjectId = null;
let currentViolations = null;

// ---------- helpers ----------

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg =
      (data.detail && (data.detail.errors ? data.detail.errors.join("; ") : data.detail)) ||
      "请求失败";
    throw new Error(msg);
  }
  return data;
}

function $(sel) {
  return document.querySelector(sel);
}

function showToast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  setTimeout(() => t.classList.add("hidden"), 3000);
}

function fmtFrames(n) {
  return n.toLocaleString("zh-CN");
}

// ---------- project list ----------

async function loadProjects() {
  const projects = await api("/api/projects");
  const list = $("#project-list");
  list.innerHTML = "";
  if (projects.length === 0) {
    list.innerHTML = '<li class="meta" style="cursor:default">暂无工程</li>';
    return;
  }
  for (const p of projects) {
    const li = document.createElement("li");
    li.dataset.id = p.id;
    li.innerHTML = `
      <div class="pname">${escapeHtml(p.name)}</div>
      <div class="pmeta">${fmtFrames(p.total_frames)} 帧 · ${p.clip_count} 片段</div>
    `;
    li.addEventListener("click", () => selectProject(p.id));
    list.appendChild(li);
  }
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

async function selectProject(pid) {
  try {
    currentProject = await api(`/api/projects/${pid}`);
    currentProjectId = pid;
    currentViolations = null;
    document.querySelectorAll("#project-list li").forEach((li) => {
      li.classList.toggle("active", li.dataset.id === pid);
    });
    $("#empty-state").classList.add("hidden");
    $("#project-view").classList.remove("hidden");
    $("#project-name").textContent = currentProject.name;
    $("#project-meta").textContent =
      `创建于 ${new Date(currentProject.created_at).toLocaleString("zh-CN")}`;
    renderTimeline();
    await loadAuthorizations();
    $("#verify-results").classList.add("hidden");
    switchTab("timeline");
  } catch (e) {
    showToast(e.message, true);
  }
}

// ---------- timeline tab ----------

function renderTimeline() {
  const tl = currentProject.timeline;
  $("#tl-total-frames").textContent = fmtFrames(tl.total_frames);
  const body = $("#clips-body");
  body.innerHTML = "";
  for (const clip of tl.clips) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(clip.name)}</td>
      <td>[${fmtFrames(clip.output_start)}, ${fmtFrames(clip.output_end)})</td>
      <td>${fmtFrames(clip.source_start)}</td>
      <td>${escapeHtml(String(clip.speed))}</td>
    `;
    body.appendChild(tr);
  }
}

// ---------- authorizations tab ----------

async function loadAuthorizations() {
  const auths = await api(`/api/projects/${currentProjectId}/authorizations`);
  $("#auth-count").textContent = `(${auths.length})`;
  const body = $("#auths-body");
  body.innerHTML = "";
  if (auths.length === 0) {
    body.innerHTML = '<tr><td colspan="5" class="meta">暂无授权</td></tr>';
    return;
  }
  for (const a of auths) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>[${fmtFrames(a.source_start)}, ${fmtFrames(a.source_end)})</td>
      <td>${a.valid_from} ~ ${a.valid_to}</td>
      <td>${escapeHtml(a.region)}</td>
      <td>${escapeHtml(a.channel)}</td>
      <td><button class="btn btn-danger btn-sm" data-id="${a.id}">删除</button></td>
    `;
    tr.querySelector("button").addEventListener("click", async () => {
      try {
        await api(`/api/authorizations/${a.id}`, { method: "DELETE" });
        showToast("授权已删除");
        await loadAuthorizations();
      } catch (e) {
        showToast(e.message, true);
      }
    });
    body.appendChild(tr);
  }
}

$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    source_start: parseInt($("#auth-source-start").value, 10),
    source_end: parseInt($("#auth-source-end").value, 10),
    valid_from: $("#auth-valid-from").value,
    valid_to: $("#auth-valid-to").value,
    region: $("#auth-region").value.trim(),
    channel: $("#auth-channel").value.trim(),
  };
  try {
    await api(`/api/projects/${currentProjectId}/authorizations`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    showToast("授权已添加");
    $("#auth-form").reset();
    await loadAuthorizations();
  } catch (e) {
    showToast(e.message, true);
  }
});

// ---------- verify tab ----------

$("#verify-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    date: $("#verify-date").value,
    region: $("#verify-region").value.trim(),
    channel: $("#verify-channel").value.trim(),
  };
  try {
    const result = await api(`/api/projects/${currentProjectId}/verify`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    currentViolations = result;
    renderResults(result);
  } catch (e) {
    showToast(e.message, true);
    $("#verify-results").classList.add("hidden");
  }
});

function renderResults(result) {
  $("#verify-results").classList.remove("hidden");
  const violations = result.violations;
  const timelineLen = getTimelineLength();
  $("#sum-segments").textContent = violations.length;
  $("#sum-frames").textContent = fmtFrames(result.total_violation_frames);
  $("#sum-total").textContent = fmtFrames(timelineLen);
  drawCanvas(violations, timelineLen);
  renderViolationList(violations);
}

function getTimelineLength() {
  const clips = currentProject.timeline.clips;
  return Math.max(...clips.map((c) => c.output_end));
}

function getActiveRanges() {
  const clips = currentProject.timeline.clips;
  const ranges = clips.map((c) => [c.output_start, c.output_end]);
  ranges.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [s, e] of ranges) {
    if (merged.length && s <= merged[merged.length - 1][1]) {
      merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], e);
    } else {
      merged.push([s, e]);
    }
  }
  return merged;
}

function drawCanvas(violations, timelineLen) {
  const canvas = $("#timeline-canvas");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  canvas.width = width * dpr;
  canvas.height = 60 * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, 60);

  const total = timelineLen;
  const toX = (f) => (f / total) * width;

  // 背景：空白帧（灰色）
  ctx.fillStyle = "#e5e6eb";
  ctx.fillRect(0, 10, width, 40);

  // 已覆盖区域（蓝色）：有活动片段且非违规
  const activeRanges = getActiveRanges();
  ctx.fillStyle = "#4a7dff";
  for (const [s, e] of activeRanges) {
    ctx.fillRect(toX(s), 10, toX(e) - toX(s), 40);
  }

  // 违规区域（红色）
  ctx.fillStyle = "#e5484d";
  for (const v of violations) {
    const x0 = toX(v.start);
    const x1 = toX(v.end);
    ctx.fillRect(x0, 10, Math.max(x1 - x0, 1), 40);
  }
}

function renderViolationList(violations) {
  const list = $("#violation-list");
  list.innerHTML = "";
  if (violations.length === 0) {
    list.innerHTML = '<p class="meta">未发现违规，所有片段均有授权覆盖。</p>';
    return;
  }
  for (const v of violations) {
    const seg = document.createElement("div");
    seg.className = "violation-segment";
    const duration = v.end - v.start;
    let reasonsHtml = "";
    for (const r of v.reasons) {
      reasonsHtml += `
        <div class="reason-item">
          <span class="reason-clip">${escapeHtml(r.clip_name)}</span>
          输出帧 <span class="reason-frames">[${fmtFrames(r.output_start)}, ${fmtFrames(r.output_end)})</span>
          · 源帧 <span class="reason-frames">[${fmtFrames(r.source_start)}, ${fmtFrames(r.source_end)})</span>
          缺少授权覆盖
        </div>
      `;
    }
    seg.innerHTML = `
      <div>
        <span class="seg-range">[${fmtFrames(v.start)}, ${fmtFrames(v.end)})</span>
        <span class="seg-duration">${fmtFrames(duration)} 帧</span>
      </div>
      <div class="reason-list">${reasonsHtml}</div>
    `;
    list.appendChild(seg);
  }
}

// ---------- tabs ----------

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name)
  );
  document.querySelectorAll(".tab-panel").forEach((p) =>
    p.classList.toggle("active", p.id === "tab-" + name)
  );
}

// ---------- new project modal ----------

$("#new-project-btn").addEventListener("click", () => {
  $("#modal-title").textContent = "新建工程";
  $("#modal-name").value = "";
  $("#modal-timeline").value = "";
  $("#modal").classList.remove("hidden");
  setTimeout(() => $("#modal-name").focus(), 50);
});

$("#modal-cancel").addEventListener("click", () => {
  $("#modal").classList.add("hidden");
});

$("#modal-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#modal-name").value.trim();
  const timelineRaw = $("#modal-timeline").value.trim();
  let timeline;
  try {
    timeline = JSON.parse(timelineRaw);
  } catch {
    showToast("时间线 JSON 格式错误", true);
    return;
  }
  try {
    const proj = await api("/api/projects", {
      method: "POST",
      body: JSON.stringify({ name, timeline }),
    });
    $("#modal").classList.add("hidden");
    showToast("工程已创建");
    await loadProjects();
    selectProject(proj.id);
  } catch (e) {
    showToast(e.message, true);
  }
});

// ---------- init ----------

loadProjects().catch((e) => showToast(e.message, true));
