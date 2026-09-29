/* 剪辑素材授权覆盖台 —— 原生 JavaScript 前端 */
"use strict";

const state = {
  projects: [],
  currentId: null,
  timeline: null,   // 归一化后的时间线
  auths: [],
  result: null,
  selectedViol: null,
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// 通用
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    let msg = `HTTP ${resp.status}`;
    try { msg = (await resp.json()).detail || msg; } catch (_) { /* ignore */ }
    throw new Error(msg);
  }
  return resp.status === 204 ? null : resp.json();
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 3200);
}

function fmt(n) { return Number(n).toLocaleString("en-US"); }

function timecode(frame, fps) {
  frame = Math.max(0, Math.floor(frame));
  const h = Math.floor(frame / (fps * 3600));
  const m = Math.floor((frame % (fps * 3600)) / (fps * 60));
  const s = Math.floor((frame % (fps * 60)) / fps);
  const f = frame % fps;
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}.${pad(f)}`;
}

function todayISO(offsetDays = 0) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return d.toISOString().slice(0, 10);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ---------------------------------------------------------------------------
// 工程
// ---------------------------------------------------------------------------

async function loadProjects(selectId = null) {
  state.projects = (await api("GET", "/api/projects")).projects;
  const list = $("projectList");
  if (!state.projects.length) {
    list.innerHTML = '<div class="muted" style="padding:6px 2px">还没有工程</div>';
  } else {
    list.innerHTML = "";
    for (const p of state.projects) {
      const div = document.createElement("div");
      div.className = "proj-item" + (p.id === state.currentId ? " active" : "");
      div.innerHTML =
        `<span title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</span>` +
        `<span class="del" title="删除工程">✕</span>`;
      div.querySelector("span").onclick = () => selectProject(p.id);
      div.querySelector(".del").onclick = async (e) => {
        e.stopPropagation();
        if (!confirm(`确定删除工程「${p.name}」？授权与时间线一并删除。`)) return;
        await api("DELETE", `/api/projects/${p.id}`);
        if (state.currentId === p.id) {
          state.currentId = null;
          showIntro();
        }
        await loadProjects();
        toast("工程已删除");
      };
      list.appendChild(div);
    }
  }
  if (selectId) await selectProject(selectId);
}

async function newProject() {
  const name = prompt("新工程名称", `工程 ${state.projects.length + 1}`);
  if (!name || !name.trim()) return;
  const p = await api("POST", "/api/projects", { name: name.trim() });
  await loadProjects(p.id);
  toast("工程已创建，请导入时间线");
}

async function selectProject(id) {
  state.currentId = id;
  state.result = null;
  state.selectedViol = null;
  const p = await api("GET", `/api/projects/${id}`);
  state.timeline = p.timeline;
  state.auths = p.authorizations;
  $("introPanel").style.display = "none";
  $("workArea").style.display = "";
  $("verifyPanel").style.display = "";
  $("timelineInput").value = p.timeline
    ? JSON.stringify(stripTimeline(p.timeline), null, 2)
    : "";
  if (p.last_verify) {
    state.result = p.last_verify;
    const sel = state.result.selection || {};
    if (sel.date) $("selDate").value = sel.date;
    if (sel.region) $("selRegion").value = sel.region;
    if (sel.channel) $("selChannel").value = sel.channel;
  } else if (!$("selDate").value) {
    $("selDate").value = todayISO();
    $("authDateFrom").value = todayISO(-30);
    $("authDateTo").value = todayISO(365);
  }
  if (!$("authDateFrom").value) {
    $("authDateFrom").value = todayISO(-30);
    $("authDateTo").value = todayISO(365);
  }
  renderTimelineMeta();
  renderMaterialSelect();
  renderAuthTable();
  renderResult();
  await loadProjects();
}

function showIntro() {
  $("introPanel").style.display = "";
  $("workArea").style.display = "none";
  $("verifyPanel").style.display = "none";
}

function stripTimeline(tl) {
  // 展示给用户的：把内部 p/q 还原为 speed 字段
  return {
    fps: tl.fps,
    materials: tl.materials.map((m) => ({
      id: m.id,
      total_frames: m.total_frames,
      segments: m.segments.map((s) => ({
        id: s.id, in: s.in, out: s.out, origin: s.origin,
        speed: s.q === 1 ? s.p : `${s.p}/${s.q}`,
      })),
    })),
  };
}

// ---------------------------------------------------------------------------
// 时间线
// ---------------------------------------------------------------------------

async function importTimeline() {
  let data;
  try {
    data = JSON.parse($("timelineInput").value);
  } catch (e) {
    toast("JSON 解析失败: " + e.message, true);
    return;
  }
  try {
    await api("PUT", `/api/projects/${state.currentId}/timeline`, { timeline: data });
    const p = await api("GET", `/api/projects/${state.currentId}`);
    state.timeline = p.timeline;
    state.auths = p.authorizations; // 授权随素材可能失效，重新拉取
    state.result = null;
    $("timelineInput").value = JSON.stringify(stripTimeline(p.timeline), null, 2);
    renderTimelineMeta();
    renderMaterialSelect();
    renderAuthTable();
    renderResult();
    toast("时间线已导入（此前核验结果已失效，请重新核验）");
  } catch (e) {
    toast(e.message, true);
  }
}

function reformatTimeline() {
  try {
    const data = JSON.parse($("timelineInput").value);
    $("timelineInput").value = JSON.stringify(data, null, 2);
  } catch (e) {
    toast("JSON 解析失败: " + e.message, true);
  }
}

function renderTimelineMeta() {
  const tl = state.timeline;
  if (!tl) { $("timelineMeta").textContent = "尚未导入"; return; }
  const segCount = tl.materials.reduce((n, m) => n + m.segments.length, 0);
  const maxOut = tl.materials.reduce(
    (mx, m) => Math.max(mx, ...m.segments.map((s) => s.out)), 0);
  $("timelineMeta").innerHTML =
    `已导入：<b>${tl.materials.length}</b> 个素材、<b>${segCount}</b> 个片段、` +
    `输出时间线 <b>${fmt(maxOut)}</b> 帧（fps=${tl.fps}，时长 ${timecode(maxOut, tl.fps)}）`;
}

// ---------------------------------------------------------------------------
// 授权
// ---------------------------------------------------------------------------

function renderMaterialSelect() {
  const sel = $("authMaterial");
  sel.innerHTML = "";
  if (!state.timeline) return;
  for (const m of state.timeline.materials) {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.id}（共 ${fmt(m.total_frames)} 帧）`;
    sel.appendChild(opt);
  }
}

async function addAuth() {
  const body = {
    material_id: $("authMaterial").value,
    src_lo: parseInt($("authLo").value, 10),
    src_hi: parseInt($("authHi").value, 10),
    date_from: $("authDateFrom").value,
    date_to: $("authDateTo").value,
    region: $("authRegion").value.trim(),
    channel: $("authChannel").value.trim(),
    note: $("authNote").value.trim(),
  };
  try {
    await api("POST", `/api/projects/${state.currentId}/authorizations`, body);
    state.auths = (await api("GET",
      `/api/projects/${state.currentId}/authorizations`)).authorizations;
    renderAuthTable();
    toast("授权已添加，请重新核验查看最新覆盖结果");
  } catch (e) {
    toast(e.message, true);
  }
}

async function deleteAuth(id) {
  if (!confirm("删除该授权？")) return;
  await api("DELETE", `/api/projects/${state.currentId}/authorizations/${id}`);
  state.auths = (await api("GET",
    `/api/projects/${state.currentId}/authorizations`)).authorizations;
  renderAuthTable();
  toast("授权已删除，请重新核验");
}

function renderAuthTable() {
  const tbody = $("authTable");
  if (!state.auths.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">尚未登记任何授权</td></tr>';
    return;
  }
  tbody.innerHTML = "";
  for (const a of state.auths) {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td>${escapeHtml(a.material_id)}</td>` +
      `<td class="mono">[${fmt(a.src_lo)}, ${fmt(a.src_hi)})<br>` +
      `<span class="muted">${fmt(a.src_hi - a.src_lo)} 帧</span></td>` +
      `<td class="mono">${a.date_from}<br><span class="muted">至 ${a.date_to}</span></td>` +
      `<td>${escapeHtml(a.region)}</td><td>${escapeHtml(a.channel)}</td>` +
      `<td>${escapeHtml(a.note || "")}</td>` +
      `<td><button class="small danger" onclick="deleteAuth(${a.id})">删</button></td>`;
    tbody.appendChild(tr);
  }
}

// ---------------------------------------------------------------------------
// 核验
// ---------------------------------------------------------------------------

async function runVerify() {
  const body = {
    date: $("selDate").value,
    region: $("selRegion").value.trim(),
    channel: $("selChannel").value.trim(),
  };
  if (!body.date) { toast("请选择播出日期", true); return; }
  if (!body.region || !body.channel) { toast("地区和渠道不能为空", true); return; }
  try {
    state.result = await api("POST",
      `/api/projects/${state.currentId}/verify`, body);
    state.selectedViol = null;
    renderResult();
  } catch (e) {
    toast(e.message, true);
  }
}

function mismatchLabel(list) {
  const map = { date: "日期不符", region: "地区不符", channel: "渠道不符" };
  return list.map((x) => map[x] || x).join("、");
}

function renderResult() {
  const summary = $("verifySummary");
  const viz = $("timelineViz");
  const list = $("violationList");
  if (!state.result) {
    summary.innerHTML = '<div class="empty">选择播出日期 / 地区 / 渠道后点击「执行核验」</div>';
    viz.innerHTML = "";
    list.innerHTML = "";
    return;
  }
  const r = state.result;
  const fps = r.fps;

  if (r.status === "rejected") {
    summary.innerHTML =
      `<div class="row" style="align-items:flex-start">
        <span class="badge bad">核验被拒绝</span>
        <span>${escapeHtml(r.reason)}</span>
      </div>`;
    list.innerHTML = r.violations_out_of_bounds.map((v) => `
      <div class="vio-card">
        <b>片段 ${escapeHtml(v.segment_id)}</b>（素材 ${escapeHtml(v.material_id)}）
        源帧越界
        <div class="piece">
          输出帧 <span class="mono">[${fmt(v.out)}, ${fmt(v.out_end)})</span>
          映射源帧 <span class="mono">[${fmt(v.src_min)}, ${fmt(v.src_max)}]</span>，
          合法源帧为 <span class="mono">[0, ${fmt(v.total_frames - 1)}]</span><br>
          ${escapeHtml(v.reason)}
        </div>
      </div>`).join("");
    viz.innerHTML = "";
    return;
  }

  const clean = r.violating_frames === 0;
  summary.innerHTML = `
    <div class="row" style="align-items:center">
      <span class="badge ${clean ? "ok" : "bad"}">
        ${clean ? "✓ 全部活动帧已获授权覆盖" : "✗ 存在授权缺口"}
      </span>
      <span class="muted">
        维度：${r.selection.date} · ${escapeHtml(r.selection.region)} ·
        ${escapeHtml(r.selection.channel)}
      </span>
    </div>
    <div class="stats">
      <span class="stat">活动帧 <b>${fmt(r.active_frames)}</b></span>
      <span class="stat">空白帧 <b>${fmt(r.blank_frames)}</b>（不计违规）</span>
      <span class="stat" style="color:${clean ? "var(--ok)" : "var(--bad)"}">
        违规帧 <b>${fmt(r.violating_frames)}</b></span>
      <span class="stat">连续违规段 <b>${fmt(r.violation_run_count)}</b></span>
      <span class="stat">片段数 <b>${fmt(r.segment_count)}</b></span>
    </div>`;

  renderTimelineViz();

  if (clean) {
    list.innerHTML = '<div class="empty" style="color:var(--ok)">' +
      '所有活动输出帧的每个活动片段源帧均有匹配授权，可以发布。</div>';
    return;
  }
  list.innerHTML = r.violations.map((v, idx) => {
    const selected = state.selectedViol === idx ? " selected" : "";
    const pieces = v.segments.map((s) => `
      <div class="piece">
        <b>片段 ${escapeHtml(s.segment_id)}</b>
        （素材 ${escapeHtml(s.material_id)}，速度
          <span class="mono">${s.speed}</span>，origin=<span class="mono">${fmt(s.origin)}</span>）<br>
        输出帧 <span class="mono">[${fmt(s.out)}, ${fmt(s.out_end)})</span>
        （${timecode(s.out, fps)} – ${timecode(s.out_end, fps)}）→
        源帧 <span class="mono">[${fmt(s.src_lo)}, ${fmt(s.src_hi)})</span><br>
        <span class="tag ${s.reason_code === "NO_LICENSE" ? "warn" : "bad"}">
          ${s.reason_code === "NO_LICENSE" ? "无授权" : "维度不匹配"}</span>
        ${escapeHtml(s.reason)}
        ${s.candidates.length ? `<details><summary>重叠但不匹配的授权（${s.candidates.length}）</summary>
          <p class="cand">${s.candidates.map((c) =>
            `<span class="mono">#${c.id} [${fmt(c.src_lo)},${fmt(c.src_hi)})</span> ` +
            `${c.date_from}~${c.date_to} · ${escapeHtml(c.region)} · ${escapeHtml(c.channel)}` +
            `（${mismatchLabel(c.mismatch)}）`).join("<br>")}</p></details>` : ""}
      </div>`).join("");
    return `
      <div class="vio-card${selected}" id="vio-${idx}" onclick="focusViolation(${idx})">
        <div class="row">
          <b>缺口 #${idx + 1}</b>
          <span class="mono">输出帧 [${fmt(v.out)}, ${fmt(v.out_end)})</span>
          <span class="tag bad">${fmt(v.frames)} 帧</span>
          <span class="spacer"></span>
          <span class="muted mono">${timecode(v.out, fps)} – ${timecode(v.out_end, fps)}</span>
        </div>
        ${pieces}
      </div>`;
  }).join("");
}

// ---------------------------------------------------------------------------
// 时间轴可视化
// ---------------------------------------------------------------------------

function renderTimelineViz() {
  const r = state.result;
  const tl = state.timeline;
  const wrap = $("timelineViz");
  const start = r.timeline_start || 0;
  const end = r.timeline_end || 0;
  const span = Math.max(end - start, 1);
  // 让时间轴宽度与帧数成比例，超长时间线可横向滚动
  const width = Math.max(320, Math.min(span / 4, 200000));

  const x = (frame) => ((frame - start) / span) * width;

  // 刻度：取约 10 档的“整秒/整十帧”位置
  const fps = r.fps;
  const tickCount = 12;
  const rough = span / tickCount;
  const niceSteps = [1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000,
    10000, 25000, 50000, 100000, 250000, 500000, 1000000,
    fps * 1, fps * 5, fps * 10, fps * 30, fps * 60, fps * 300,
    fps * 600, fps * 1800, fps * 3600];
  const step = niceSteps.find((s) => s >= rough) || rough;
  let ticks = "";
  for (let f = Math.ceil(start / step) * step; f < end; f += step) {
    ticks += `<div class="tick" style="left:${x(f)}px">` +
      `${fmt(f)}<br>${timecode(f, fps)}</div>`;
  }

  // 每个素材一条片段泳道；另加一条违规泳道
  let lanes = "";
  tl.materials.forEach((m) => {
    let blocks = "";
    m.segments.forEach((s) => {
      const w = x(s.out) - x(s.in);
      if (w < 0.5) return;
      blocks += `<div class="tl-seg ${s.p < 0 ? "neg" : ""}" ` +
        `style="left:${x(s.in)}px;width:${Math.max(w, 2)}px" ` +
        `title="${escapeHtml(s.id)} 输出[${fmt(s.in)},${fmt(s.out)}) → ` +
        `origin=${fmt(s.origin)} 速度=${s.p}/${s.q}"></div>`;
    });
    lanes += `<div class="tl-lane">` +
      `<div class="tl-lane-label" title="${escapeHtml(m.id)}">${escapeHtml(m.id)}</div>` +
      `<div class="tl-track" style="width:${width}px">${blocks}</div></div>`;
  });

  let violBlocks = "";
  if (r.status === "ok") {
    r.violations.forEach((v, idx) => {
      const w = Math.max(x(v.out_end) - x(v.out), 2);
      violBlocks += `<div class="tl-viol ${state.selectedViol === idx ? "selected" : ""}"` +
        ` style="left:${x(v.out)}px;width:${w}px" data-idx="${idx}"` +
        ` title="缺口 #${idx + 1} [${fmt(v.out)},${fmt(v.out_end)}) ${fmt(v.frames)}帧"></div>`;
    });
  }

  wrap.innerHTML = `
    <div class="timeline-wrap" id="timelineWrap">
      <div class="tl-ruler" style="width:${width}px">${ticks}</div>
      ${lanes}
      <div class="tl-lane">
        <div class="tl-lane-label">违规缺口</div>
        <div class="tl-track" style="width:${width}px">${violBlocks}</div>
      </div>
    </div>
    <p class="muted" style="margin:6px 0 0">
      蓝/紫块为正/倒放片段，红色斜纹为授权缺口（跨片段连续的缺口已合并）；
      点击红色缺口可在下方定位对应片段与原因。
    </p>`;

  wrap.querySelectorAll(".tl-viol").forEach((el) => {
    el.onclick = (e) => {
      e.stopPropagation();
      focusViolation(parseInt(el.dataset.idx, 10));
    };
  });
}

function focusViolation(idx) {
  state.selectedViol = idx;
  renderResult();
  const card = $(`vio-${idx}`);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  const r = state.result;
  const v = r.violations[idx];
  const wrapEl = $("timelineWrap");
  if (wrapEl) {
    const span = Math.max(r.timeline_end - r.timeline_start, 1);
    const width = Math.max(320, Math.min(span / 4, 200000));
    const xFrame = (f) => ((f - r.timeline_start) / span) * width;
    const center = xFrame(Math.floor((v.out + v.out_end) / 2));
    wrapEl.scrollLeft = Math.max(0, center - wrapEl.clientWidth / 2);
  }
}

// ---------------------------------------------------------------------------
// 示例数据
// ---------------------------------------------------------------------------

function loadDemo() {
  const demo = {
    fps: 25,
    materials: [
      {
        id: "MAT-A",
        total_frames: 10000,
        segments: [
          { id: "S1", in: 0,    out: 200,  origin: 100,  speed: 1 },
          { id: "S2", in: 200,  out: 350,  origin: 9000, speed: "-1/2" },
          { id: "S3", in: 350,  out: 600,  origin: 5000, speed: "3/2" }
        ]
      },
      {
        id: "MAT-B",
        total_frames: 4000,
        segments: [
          { id: "S4", in: 300, out: 450, origin: 0, speed: 2 }
        ]
      }
    ]
  };
  $("timelineInput").value = JSON.stringify(demo, null, 2);
  toast("已载入示例时间线：点击「导入时间线」后再登记授权");
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

(async function init() {
  $("selDate").value = todayISO();
  $("authDateFrom").value = todayISO(-30);
  $("authDateTo").value = todayISO(365);
  try {
    await loadProjects();
  } catch (e) {
    toast("后端连接失败: " + e.message, true);
  }
})();
