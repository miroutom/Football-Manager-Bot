/* global fetch */

let baselineHome = {};
let teams = [];
let dragPayload = null;
let dragScrollActive = false;
let currentWindow = "summer";
let maxIn = 5;
let maxOut = 5;
let dirty = false;
let windowLabels = { summer: "Лето", winter: "Зима" };
let injuryAsOfMonth = 6;
let injuryById = {};
let formationsCatalog = []; // [{id, label, key, slots}]
const BENCH_SLOTS = 7;
const EXTRA_RESERVE = 5;

const DRAG_SCROLL_MARGIN = 72;
const DRAG_SCROLL_SPEED = 18;

const ZONE_RANK = { start: 0, bench: 1, reserve: 2 };

function migrateId(id, baseline) {
  if (!id) return id;
  const parts = id.split("|");
  if (parts.length >= 3) return id;
  if (parts.length === 2) {
    const [name, pos] = parts;
    for (const bid of Object.keys(baseline || {})) {
      const bp = bid.split("|");
      if (bp.length >= 3 && bp[bp.length - 2] === name && bp[bp.length - 1] === pos) {
        return bid;
      }
    }
    return id;
  }
  return id;
}

function emptyTeamFromTemplate(tmpl) {
  return {
    ...JSON.parse(JSON.stringify(tmpl)),
    formation_id: tmpl.formation_id || 1,
    start: tmpl.start.map((slot) => ({
      id: null,
      name: null,
      position: null,
      overall: null,
      slot: slot.slot,
      x: slot.x,
      y: slot.y,
    })),
    bench: tmpl.bench.map(() => ({ id: null, name: null, position: null, overall: null })),
    reserve: tmpl.reserve.map(() => ({ id: null, name: null, position: null, overall: null })),
  };
}

function migrateSavedState(saved, rosters) {
  const savedByName = Object.fromEntries((saved.teams || []).map((t) => [t.name, t]));
  const freshBaseline = rosters.baseline_home || {};
  const out = [];

  for (const tmpl of rosters.teams || []) {
    const savedTeam = savedByName[tmpl.name];
    if (!savedTeam) {
      out.push(JSON.parse(JSON.stringify(tmpl)));
      continue;
    }

    const team = emptyTeamFromTemplate(tmpl);
    for (const zone of ["bench", "reserve"]) {
      const savedLen = (savedTeam[zone] || []).length;
      while (team[zone].length < savedLen) {
        team[zone].push({ id: null, name: null, position: null, overall: null });
      }
    }

    for (const zone of ["start", "bench", "reserve"]) {
      (savedTeam[zone] || []).forEach((src, i) => {
        if (!src || !src.id || i >= team[zone].length) return;
        const migrated = { ...src, id: migrateId(src.id, freshBaseline) };
        if (zone === "start") {
          placePlayerOnTeam(team, zone, i, migrated);
        } else {
          team[zone][i] = migrated;
        }
      });
    }
    if (savedTeam.formation_id != null) {
      team.formation_id = Number(savedTeam.formation_id);
    }
    if (savedTeam.formation) team.formation = savedTeam.formation;
    if (savedTeam.caption) team.caption = savedTeam.caption;
    if (savedTeam.coach != null) team.coach = savedTeam.coach;
    out.push(team);
  }
  return out;
}

function placePlayerOnTeam(team, zone, index, player) {
  const slot = team[zone][index];
  if (zone === "start") {
    team[zone][index] = {
      ...player,
      slot: slot.slot,
      x: slot.x,
      y: slot.y,
    };
  } else {
    team[zone][index] = { ...player };
  }
}

function onDragScroll(e) {
  if (!dragScrollActive) return;
  const y = e.clientY;
  if (y < DRAG_SCROLL_MARGIN) {
    window.scrollBy(0, -DRAG_SCROLL_SPEED);
  } else if (y > window.innerHeight - DRAG_SCROLL_MARGIN) {
    window.scrollBy(0, DRAG_SCROLL_SPEED);
  }
}

function startDragScroll() {
  if (dragScrollActive) return;
  dragScrollActive = true;
  document.addEventListener("dragover", onDragScroll);
}

function stopDragScroll() {
  if (!dragScrollActive) return;
  dragScrollActive = false;
  document.removeEventListener("dragover", onDragScroll);
}

function playerKey(p) {
  if (!p || !p.id) return null;
  return p.id;
}

function clonePlayer(p) {
  return p ? { ...p } : null;
}

function buildInjuryIndex(rosters) {
  const map = {};
  for (const team of rosters.teams || []) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        if (!p || !p.id) continue;
        if (p.injured) {
          map[p.id] = {
            injured: true,
            injury_from: p.injury_from ?? null,
            injury_until: p.injury_until ?? null,
            injury_months: p.injury_months ?? null,
          };
        }
      }
    }
  }
  return map;
}

function applyInjuryFlags(teamList) {
  for (const team of teamList) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        if (!p || !p.id) continue;
        const info = injuryById[p.id];
        if (info) {
          p.injured = true;
          p.injury_from = info.injury_from;
          p.injury_until = info.injury_until;
          p.injury_months = info.injury_months;
        } else {
          p.injured = false;
          delete p.injury_from;
          delete p.injury_until;
          delete p.injury_months;
        }
      }
    }
  }
}

function ensureExtraReserveSlots(teamList) {
  /** В конце резерва всегда EXTRA_RESERVE пустых ячеек для дропа. */
  for (const team of teamList || []) {
    if (!Array.isArray(team.reserve)) team.reserve = [];
    let trailingEmpty = 0;
    for (let i = team.reserve.length - 1; i >= 0; i--) {
      if (team.reserve[i] && team.reserve[i].id) break;
      trailingEmpty += 1;
    }
    while (trailingEmpty < EXTRA_RESERVE) {
      team.reserve.push({
        id: null,
        name: null,
        position: null,
        overall: null,
        injured: false,
      });
      trailingEmpty += 1;
    }
  }
}

function countInOut(team) {
  const ids = new Set();
  const collect = (arr) => arr.forEach((p) => { if (p && p.id) ids.add(p.id); });
  collect(team.start);
  collect(team.bench);
  collect(team.reserve);
  let inn = 0;
  ids.forEach((id) => {
    if (baselineHome[id] !== team.name) inn += 1;
  });
  let out = 0;
  Object.entries(baselineHome).forEach(([id, home]) => {
    if (home === team.name && !ids.has(id)) out += 1;
  });
  return { inn, out };
}

function isIncoming(teamName, player) {
  if (!player || !player.id) return false;
  return baselineHome[player.id] !== teamName;
}

function injuryTipText(p) {
  if (!p || !p.injured) return "";
  const from = p.injury_from != null ? p.injury_from : "?";
  const until = p.injury_until != null ? p.injury_until : "?";
  const months = p.injury_months != null ? p.injury_months : null;
  let tip = `Травма: с ${from} по ${until} мес.`;
  if (months != null) tip += ` (${months} мес.)`;
  tip += ` · сейчас ${injuryAsOfMonth}-й`;
  return tip;
}

function renderPlayer(teamName, p, inline) {
  if (!p || !p.id) {
    const el = document.createElement("div");
    el.className = "empty-slot";
    el.textContent = "—";
    el.dataset.empty = "1";
    return el;
  }
  const el = document.createElement("div");
  el.className = "player" + (isIncoming(teamName, p) ? " incoming" : "") + (p.injured ? " injured" : "");
  el.draggable = true;
  el.dataset.id = p.id;
  el.dataset.team = teamName;
  const tip = injuryTipText(p);
  if (tip) {
    el.dataset.tip = tip;
    el.setAttribute("aria-label", tip);
  }
  const injuryBadge = p.injured
    ? `<span class="inj" aria-hidden="true">🏥</span>`
    : "";
  el.innerHTML = inline
    ? `${injuryBadge}<span class="ovr">${p.overall}</span><span class="pos">${p.position}</span><span class="nm">${p.name}</span>`
    : `${injuryBadge}<span class="ovr">${p.overall}</span><span class="nm">${p.name}</span><span class="pos">${p.position}</span>`;
  el.addEventListener("dragstart", onDragStart);
  el.addEventListener("dragend", stopDragScroll);
  return el;
}

function onDragStart(e) {
  const el = e.currentTarget;
  dragPayload = {
    id: el.dataset.id,
    team: el.dataset.team,
    name: el.querySelector(".nm")?.textContent,
    position: el.querySelector(".pos")?.textContent,
    overall: parseInt(el.querySelector(".ovr")?.textContent || "0", 10),
  };
  e.dataTransfer.effectAllowed = "move";
  e.dataTransfer.setData("text/plain", dragPayload.id);
  startDragScroll();
}

function setupDrop(el, teamName, zone, index) {
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    el.classList.add("drag-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
  el.addEventListener("drop", (e) => {
    e.preventDefault();
    el.classList.remove("drag-over");
    if (!dragPayload) return;
    movePlayer(dragPayload, teamName, zone, index);
    dragPayload = null;
    stopDragScroll();
    renderAll();
    dirty = true;
    setStatus("изменено (не сохранено)");
  });
}

function emptySlot(team, zone, index) {
  const p = team[zone][index];
  if (zone === "start") {
    team[zone][index] = {
      id: null,
      name: null,
      position: null,
      overall: null,
      slot: p.slot,
      x: p.x,
      y: p.y,
    };
  } else {
    team[zone][index] = { id: null, name: null, position: null, overall: null };
  }
}

function placePlayer(team, zone, index, player) {
  placePlayerOnTeam(team, zone, index, player);
}

function findPlayerGlobally(id) {
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        if (team[zone][i]?.id === id) {
          return {
            team,
            teamName: team.name,
            zone,
            index: i,
            player: team[zone][i],
          };
        }
      }
    }
  }
  return null;
}

function removeAllInstancesOfId(id) {
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        if (team[zone][i]?.id === id) {
          emptySlot(team, zone, i);
        }
      }
    }
  }
}

function pickBestPlacement(locs) {
  return locs
    .slice()
    .sort((a, b) => {
      const zd = (ZONE_RANK[a.zone] ?? 9) - (ZONE_RANK[b.zone] ?? 9);
      if (zd !== 0) return zd;
      return a.index - b.index;
    })[0];
}

function pickKeepPlacement(id, locs) {
  const home = baselineHome[id];
  const atHome = locs.filter((l) => l.teamName === home);
  const away = locs.filter((l) => l.teamName !== home);

  if (away.length === 0) {
    return pickBestPlacement(locs);
  }
  if (atHome.length === 0) {
    return pickBestPlacement(away);
  }

  const bestAway = pickBestPlacement(away);
  const bestHome = pickBestPlacement(atHome);
  const awayRank = ZONE_RANK[bestAway.zone] ?? 9;
  const homeRank = ZONE_RANK[bestHome.zone] ?? 9;
  if (awayRank < homeRank) return bestAway;
  if (awayRank > homeRank) return bestHome;
  return bestHome;
}

function dedupeGlobally(list) {
  const byId = new Map();
  for (const team of list) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        const p = team[zone][i];
        if (!p?.id) continue;
        if (!byId.has(p.id)) byId.set(p.id, []);
        byId.get(p.id).push({ team, teamName: team.name, zone, index: i, id: p.id });
      }
    }
  }

  for (const [id, locs] of byId) {
    if (locs.length <= 1) continue;
    const keep = pickKeepPlacement(id, locs);
    for (const loc of locs) {
      if (loc.teamName === keep.teamName && loc.zone === keep.zone && loc.index === keep.index) {
        continue;
      }
      emptySlot(loc.team, loc.zone, loc.index);
    }
  }
}

function movePlayer(src, destTeamName, destZone, destIndex) {
  const destTeam = teams.find((t) => t.name === destTeamName);
  if (!destTeam) return;

  const loc = findPlayerGlobally(src.id);
  if (!loc) return;

  if (loc.teamName === destTeamName && loc.zone === destZone && loc.index === destIndex) {
    return;
  }

  const destSlot = destTeam[destZone][destIndex];
  const moving = { ...loc.player };
  const displaced = destSlot?.id && destSlot.id !== moving.id ? { ...destSlot } : null;
  const vacated = { team: loc.team, zone: loc.zone, index: loc.index };

  removeAllInstancesOfId(moving.id);
  placePlayer(destTeam, destZone, destIndex, moving);

  if (displaced) {
    placePlayer(vacated.team, vacated.zone, vacated.index, displaced);
  }
  dedupeGlobally(teams);
}

function formationById(fid) {
  const id = Number(fid);
  return formationsCatalog.find((f) => Number(f.id) === id) || null;
}

function collectTeamPlayers(team) {
  const out = [];
  for (const zone of ["start", "bench", "reserve"]) {
    for (const p of team[zone] || []) {
      if (p && p.id) out.push({ ...p });
    }
  }
  return out;
}

function recomputeAvgStart(team) {
  const ovrs = (team.start || []).map((s) => s.overall).filter((x) => x != null);
  team.avg_start = ovrs.length
    ? Math.round((ovrs.reduce((a, b) => a + b, 0) / ovrs.length) * 10) / 10
    : 0;
}

function applyFormationToTeam(team, fid) {
  const form = formationById(fid);
  if (!form) return false;
  const players = collectTeamPlayers(team);
  const remaining = players.slice();
  const newStart = form.slots.map((slot) => {
    const allowed = new Set(slot.allowed_positions || []);
    let bestIdx = -1;
    let bestOvr = -1;
    for (let i = 0; i < remaining.length; i++) {
      const p = remaining[i];
      const pos = (p.position || "").trim();
      if (!allowed.has(pos)) continue;
      const ovr = Number(p.overall) || 0;
      if (ovr > bestOvr) {
        bestOvr = ovr;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) {
      return {
        id: null,
        name: null,
        position: null,
        overall: null,
        injured: false,
        slot: slot.slot_id,
        x: slot.x,
        y: slot.y,
      };
    }
    const picked = remaining.splice(bestIdx, 1)[0];
    return {
      ...picked,
      slot: slot.slot_id,
      x: slot.x,
      y: slot.y,
    };
  });

  // Незанятые слоты: заполнить сильнейшими оставшимися
  for (let i = 0; i < newStart.length; i++) {
    if (newStart[i].id || !remaining.length) continue;
    remaining.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
    const picked = remaining.shift();
    newStart[i] = {
      ...picked,
      slot: form.slots[i].slot_id,
      x: form.slots[i].x,
      y: form.slots[i].y,
    };
  }

  remaining.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  const emptySlot = () => ({
    id: null,
    name: null,
    position: null,
    overall: null,
    injured: false,
  });
  const bench = [];
  for (let i = 0; i < BENCH_SLOTS; i++) {
    bench.push(remaining.length ? { ...remaining.shift() } : emptySlot());
  }
  // Как в export_rosters: все оставшиеся в резерве + всегда EXTRA_RESERVE пустых ячеек
  const reserve = remaining.map((p) => ({ ...p }));
  for (let i = 0; i < EXTRA_RESERVE; i++) {
    reserve.push(emptySlot());
  }

  const label = form.label;
  const coach = (team.coach || "").trim();
  team.formation_id = Number(form.id);
  team.formation = coach ? `${label} · ${coach}` : label;
  team.caption = team.formation;
  team.start = newStart;
  team.bench = bench;
  team.reserve = reserve;
  recomputeAvgStart(team);
  return true;
}

function onFormationChange(teamName, fid) {
  const team = teams.find((t) => t.name === teamName);
  if (!team) return;
  if (!applyFormationToTeam(team, fid)) return;
  dirty = true;
  renderAll();
  setStatus(`схема ${team.formation} — не сохранено`);
}

function renderTeam(team) {
  const card = document.createElement("div");
  card.className = "team-card";
  card.dataset.team = team.name;
  const { inn, out } = countInOut(team);
  const overIn = inn > maxIn;
  const overOut = out > maxOut;
  if (overIn || overOut) card.classList.add("over-quota");

  const hdr = document.createElement("div");
  hdr.className = "team-hdr";
  const nameEl = document.createElement("div");
  nameEl.className = "name";
  nameEl.textContent = team.name;
  hdr.appendChild(nameEl);

  const meta = document.createElement("div");
  meta.className = "meta";
  const formWrap = document.createElement("label");
  formWrap.className = "formation-pick";
  formWrap.textContent = "Схема ";
  const sel = document.createElement("select");
  const curFid = Number(team.formation_id) || 1;
  if (!formationsCatalog.length) {
    const opt = document.createElement("option");
    opt.textContent = team.formation || "?";
    sel.appendChild(opt);
    sel.disabled = true;
  } else {
    formationsCatalog.forEach((f) => {
      const opt = document.createElement("option");
      opt.value = String(f.id);
      opt.textContent = `${f.id}. ${f.label}`;
      if (Number(f.id) === curFid) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.addEventListener("change", (e) => {
      onFormationChange(team.name, e.target.value);
    });
  }
  formWrap.appendChild(sel);
  meta.appendChild(formWrap);
  const avgSpan = document.createElement("span");
  avgSpan.textContent = ` · ср. старт ${team.avg_start}`;
  meta.appendChild(avgSpan);
  if (team.coach) {
    const coachSpan = document.createElement("span");
    coachSpan.textContent = ` · ${team.coach}`;
    meta.appendChild(coachSpan);
  }
  hdr.appendChild(meta);

  const counters = document.createElement("div");
  counters.className = "counters";
  counters.innerHTML = `
    <span class="in${overIn ? " over" : ""}">${inn}/${maxIn} IN</span>
    ·
    <span class="out${overOut ? " over" : ""}">${out}/${maxOut} OUT</span>
  `;
  hdr.appendChild(counters);

  const body = document.createElement("div");
  body.className = "team-body";

  const pitch = document.createElement("div");
  pitch.className = "pitch";
  team.start.forEach((slot, i) => {
    const wrap = document.createElement("div");
    wrap.className = "slot drop-zone";
    wrap.style.left = `${slot.x * 100}%`;
    wrap.style.top = `${slot.y * 100}%`;
    const lbl = document.createElement("div");
    lbl.className = "slot-label";
    lbl.textContent = slot.slot || "";
    wrap.appendChild(lbl);
    wrap.appendChild(renderPlayer(team.name, slot.id ? slot : null, false));
    setupDrop(wrap, team.name, "start", i);
    pitch.appendChild(wrap);
  });

  const side = document.createElement("div");
  side.className = "sidebar";
  const hBench = document.createElement("h3");
  hBench.textContent = "Запасные";
  side.appendChild(hBench);
  const benchList = document.createElement("div");
  benchList.className = "side-list";
  team.bench.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "side-row drop-zone";
    row.appendChild(renderPlayer(team.name, p.id ? p : null, true));
    setupDrop(row, team.name, "bench", i);
    benchList.appendChild(row);
  });
  side.appendChild(benchList);
  const hRes = document.createElement("h3");
  hRes.textContent = "Резерв";
  side.appendChild(hRes);
  const resList = document.createElement("div");
  resList.className = "side-list";
  team.reserve.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "reserve-row drop-zone";
    row.appendChild(renderPlayer(team.name, p.id ? p : null, true));
    setupDrop(row, team.name, "reserve", i);
    resList.appendChild(row);
  });
  side.appendChild(resList);

  body.appendChild(pitch);
  body.appendChild(side);
  card.appendChild(hdr);
  card.appendChild(body);
  return card;
}

function renderAll() {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  teams.forEach((t) => grid.appendChild(renderTeam(t)));
}

function currentState() {
  return { window: currentWindow, baseline_home: baselineHome, teams };
}

function setStatus(msg) {
  document.getElementById("status").textContent = msg;
}

function updateTitle() {
  const label = windowLabels[currentWindow] || currentWindow;
  document.getElementById("app-title").textContent =
    `Трансферное окно (${label} ${maxIn}/${maxOut}) — 40 клубов`;
  document.title = `Трансферное окно — ${label}`;
  document.querySelectorAll(".win-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.window === currentWindow);
  });
}

function applyWindowQuotas(cfg, windowKey) {
  currentWindow = windowKey;
  const w = (cfg.windows || {})[windowKey] || {};
  maxIn = Number(w.max_in) || (windowKey === "winter" ? 2 : 5);
  maxOut = Number(w.max_out) || (windowKey === "winter" ? 2 : 5);
  if (w.label) windowLabels[windowKey] = w.label;
  updateTitle();
}

async function loadData() {
  const [cfgRes, rostersRes] = await Promise.all([
    fetch("/api/config"),
    fetch("/api/rosters"),
  ]);
  const cfg = await cfgRes.json();
  const rosters = await rostersRes.json();
  if (cfg.windows) {
    Object.entries(cfg.windows).forEach(([k, v]) => {
      if (v && v.label) windowLabels[k] = v.label;
    });
  }
  const savedWin = localStorage.getItem("tw_window");
  if (savedWin === "summer" || savedWin === "winter") {
    currentWindow = savedWin;
  }
  applyWindowQuotas(cfg, currentWindow || cfg.default_window || "summer");
  localStorage.setItem("tw_window", currentWindow);
  injuryAsOfMonth = Number(rosters.injury_as_of_month) || 6;
  injuryById = buildInjuryIndex(rosters);
  formationsCatalog = Array.isArray(rosters.formations) ? rosters.formations : [];
  if (cfg.data_dir) {
    window.__twDataDir = cfg.data_dir;
  }

  const freshBaseline = rosters.baseline_home || {};
  const stateRes = await fetch(`/api/state?window=${encodeURIComponent(currentWindow)}`);
  if (stateRes.ok) {
    const saved = await stateRes.json();
    baselineHome = freshBaseline;
    teams = migrateSavedState(saved, rosters);
    dedupeGlobally(teams);
    applyInjuryFlags(teams);
    ensureExtraReserveSlots(teams);
    dirty = false;
    const injN = Object.keys(injuryById).length;
    setStatus(
      `загружено: ${windowLabels[currentWindow] || currentWindow}` +
        (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "")
    );
    renderAll();
    return;
  }

  baselineHome = freshBaseline;
  teams = JSON.parse(JSON.stringify(rosters.teams || []));
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  dirty = false;
  const injN = Number(rosters.injured_count) || Object.keys(injuryById).length;
  setStatus(
    `сезон ${rosters.season || "?"} — исходные составы (${windowLabels[currentWindow]})` +
      (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "")
  );
  renderAll();
}

async function switchWindow(next) {
  if (next === currentWindow) return;
  if (dirty) {
    const ok = window.confirm(
      "Есть несохранённые изменения. Переключить окно без сохранения текущего?"
    );
    if (!ok) return;
  }
  currentWindow = next;
  localStorage.setItem("tw_window", currentWindow);
  await loadData();
}

async function saveState() {
  const res = await fetch("/api/save", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  if (j.ok) {
    dirty = false;
    const over = teams.filter((t) => {
      const { inn, out } = countInOut(t);
      return inn > maxIn || out > maxOut;
    });
    const n = j.transfers_count != null ? j.transfers_count : "?";
    const path = j.path || window.__twDataDir || "";
    let msg = `сохранено (${windowLabels[currentWindow]}), трансферов: ${n}`;
    if (path) msg += ` → ${path}`;
    if (over.length) {
      msg += ` · сверх лимита: ${over.map((t) => t.name).join(", ")}`;
    }
    setStatus(msg);
    return;
  }
  setStatus("ошибка сохранения");
}

async function exportFmt(fmt) {
  const res = await fetch(`/api/export?fmt=${fmt}&kind=squads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(j.ok ? `выгружено: ${j.path}` : `ошибка: ${j.error || "?"}`);
}

async function exportTransfersFmt(fmt) {
  const res = await fetch(`/api/export?fmt=${fmt}&kind=transfers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(j.ok ? `трансферов ${j.count}: ${j.path}` : `ошибка: ${j.error || "?"}`);
}

document.getElementById("btn-save").addEventListener("click", saveState);
document.getElementById("btn-export-txt").addEventListener("click", () => exportFmt("txt"));
document.getElementById("btn-export-xlsx").addEventListener("click", () => exportFmt("xlsx"));
document.getElementById("btn-export-transfers-txt").addEventListener("click", () => exportTransfersFmt("simple"));
document.getElementById("btn-export-transfers-xlsx").addEventListener("click", () => exportTransfersFmt("xlsx"));
document.getElementById("btn-summer").addEventListener("click", () => switchWindow("summer"));
document.getElementById("btn-winter").addEventListener("click", () => switchWindow("winter"));

loadData().catch((e) => setStatus("ошибка: " + e.message));
