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
const FA_TEAM = "Free Agent";

let freeAgents = [];
let undoStack = [];
let leaguesCatalog = [];
let positionsCatalog = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"];

function pushUndo() {
  undoStack.push({
    teams: JSON.parse(JSON.stringify(teams)),
    freeAgents: JSON.parse(JSON.stringify(freeAgents)),
    baselineHome: { ...baselineHome },
  });
  if (undoStack.length > 50) undoStack.shift();
  updateUndoBtn();
}

function updateUndoBtn() {
  const btn = document.getElementById("btn-undo");
  if (btn) btn.disabled = undoStack.length === 0;
}

function undoLast() {
  const snap = undoStack.pop();
  if (!snap) return;
  teams = snap.teams;
  freeAgents = snap.freeAgents;
  baselineHome = snap.baselineHome;
  dirty = true;
  renderAll();
  setStatus("отменено последнее действие");
  updateUndoBtn();
}

function initFaBaseline(list) {
  for (const p of list || []) {
    if (p && p.id) baselineHome[p.id] = FA_TEAM;
  }
}

function syncFreeAgentsFromRosters(rosters) {
  const raw = rosters.free_agents || [];
  freeAgents = raw.map((p) => ({ ...p, status: p.status || "bench" }));
  initFaBaseline(freeAgents);
}

function findFaPlayer(id) {
  return freeAgents.find((p) => p.id === id) || null;
}

function renderFaPanel() {
  const list = document.getElementById("fa-list");
  const cnt = document.getElementById("fa-count");
  if (!list) return;
  list.innerHTML = "";
  if (cnt) cnt.textContent = String(freeAgents.length);
  const sorted = freeAgents.slice().sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  if (!sorted.length) {
    const empty = document.createElement("div");
    empty.className = "fa-hint";
    empty.textContent = "Пул пуст — перетащи сюда или добавь нового";
    list.appendChild(empty);
  }
  sorted.forEach((p) => {
    const el = renderPlayer(FA_TEAM, p, true);
    el.dataset.fromFa = "1";
    el.addEventListener("dragstart", (e) => {
      dragPayload = {
        id: p.id,
        team: FA_TEAM,
        fromFa: true,
        name: p.name,
        position: p.position,
        overall: p.overall,
      };
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", p.id);
      startDragScroll();
    });
    list.appendChild(el);
  });
  if (!list.dataset.faDropBound) {
    list.dataset.faDropBound = "1";
    list.addEventListener("dragover", (e) => {
      e.preventDefault();
      list.classList.add("drag-over");
    });
    list.addEventListener("dragleave", () => list.classList.remove("drag-over"));
    list.addEventListener("drop", (e) => {
      e.preventDefault();
      list.classList.remove("drag-over");
      if (!dragPayload) return;
      pushUndo();
      movePlayerToFa(dragPayload);
      dragPayload = null;
      stopDragScroll();
      renderAll();
      dirty = true;
      setStatus("в пул свободных агентов");
    });
  }
}

function movePlayerToFa(src) {
  if (!src || !src.id) return;
  if (findFaPlayer(src.id)) return;
  const loc = findPlayerGlobally(src.id);
  if (!loc) return;
  const p = { ...loc.player };
  if (!baselineHome[src.id]) baselineHome[src.id] = loc.teamName;
  removeAllInstancesOfId(src.id);
  freeAgents.push({ ...p, status: "bench" });
  freeAgents.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  dedupeGlobally(teams);
}

function placeNewPlayer(teamName, zone, player) {
  const team = teams.find((t) => t.name === teamName);
  if (!team) return false;
  let idx = -1;
  for (let i = 0; i < team[zone].length; i++) {
    if (!team[zone][i]?.id) {
      idx = i;
      break;
    }
  }
  if (idx < 0 && zone === "reserve") {
    team.reserve.push({ id: null, name: null, position: null, overall: null });
    idx = team.reserve.length - 1;
  }
  if (idx < 0) return false;
  placePlayer(team, zone, idx, player);
  return true;
}

function fillLeagueSelect(sel, selectedCode) {
  if (!sel) return;
  sel.innerHTML = "";
  leaguesCatalog.forEach((lg) => {
    const opt = document.createElement("option");
    opt.value = lg.code;
    opt.textContent = lg.name;
    if (lg.code === selectedCode) opt.selected = true;
    sel.appendChild(opt);
  });
}

function teamsForLeague(code) {
  const lg = leaguesCatalog.find((l) => l.code === code);
  return lg ? lg.teams.slice() : [];
}

function fillTeamSelect(sel, leagueCode, selectedTeam) {
  if (!sel) return;
  sel.innerHTML = "";
  teamsForLeague(leagueCode).forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t;
    opt.textContent = t;
    if (t === selectedTeam) opt.selected = true;
    sel.appendChild(opt);
  });
}

function openModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.remove("hidden");
    el.setAttribute("aria-hidden", "false");
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("hidden");
    el.setAttribute("aria-hidden", "true");
  }
}

function setupPlayerForm() {
  const form = document.getElementById("player-form");
  const posSel = document.getElementById("form-position");
  const lgSel = document.getElementById("form-league");
  const tmSel = document.getElementById("form-team");
  const toFa = document.getElementById("form-to-fa");
  if (!form || !posSel) return;

  posSel.innerHTML = "";
  positionsCatalog.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    posSel.appendChild(opt);
  });
  fillLeagueSelect(lgSel, leaguesCatalog[0]?.code);
  fillTeamSelect(tmSel, leaguesCatalog[0]?.code, teamsForLeague(leaguesCatalog[0]?.code)[0]);
  lgSel?.addEventListener("change", () => fillTeamSelect(tmSel, lgSel.value, teamsForLeague(lgSel.value)[0]));
  toFa?.addEventListener("change", () => {
    const disabled = !!toFa.checked;
    lgSel.disabled = disabled;
    tmSel.disabled = disabled;
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const name = String(fd.get("name") || "").trim();
    const nickname = String(fd.get("nickname") || "").trim();
    const overall = Math.max(1, Math.min(99, parseInt(fd.get("overall"), 10) || 72));
    const position = String(fd.get("position") || "").trim().toUpperCase();
    const nation = String(fd.get("nation") || "").trim();
    const toFaOnly = !!fd.get("to_fa");
    const team = String(fd.get("team") || "").trim();
    const status = String(fd.get("status") || "bench");
    if (!name || !position) return;

    pushUndo();
    let player;
    if (toFaOnly) {
      try {
        const res = await fetch("/api/fa/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, nickname, overall, position, nation, status }),
        });
        const j = await res.json();
        if (!j.ok) throw new Error(j.error || "ошибка FA");
        player = j.player;
      } catch (err) {
        player = {
          id: `${FA_TEAM}|${name}|${position}`,
          name,
          position,
          overall,
          nation,
          nickname,
          status,
        };
      }
      baselineHome[player.id] = FA_TEAM;
      freeAgents.push({ ...player, status });
      freeAgents.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
    } else {
      const id = `${team}|${name}|${position}`;
      player = { id, name, position, overall, nation, nickname, status };
      baselineHome[id] = team;
      const zone = status === "start" ? "reserve" : status;
      if (!placeNewPlayer(team, zone, player)) {
        undoStack.pop();
        updateUndoBtn();
        setStatus(`нет места в ${team} (${zone})`);
        return;
      }
      try {
        await fetch("/api/fa/apply-to-db", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, nickname, overall, position, nation, team, status }),
        });
      } catch (_) {
        /* offline bundle — только state */
      }
    }
    dirty = true;
    closeModal("modal-overlay");
    form.reset();
    renderAll();
    setStatus(toFaOnly ? `добавлен FA: ${name}` : `новый игрок в ${team}: ${name}`);
  });
}

function setupFaSignForm() {
  const form = document.getElementById("fa-sign-form");
  const pSel = document.getElementById("fa-sign-player");
  const lgSel = document.getElementById("fa-sign-league");
  const tmSel = document.getElementById("fa-sign-team");
  if (!form || !pSel) return;

  const refreshPlayers = () => {
    pSel.innerHTML = "";
    freeAgents
      .slice()
      .sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0))
      .forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = `${p.overall} ${p.position} ${p.name}`;
        pSel.appendChild(opt);
      });
  };
  fillLeagueSelect(lgSel, leaguesCatalog[0]?.code);
  fillTeamSelect(tmSel, leaguesCatalog[0]?.code, teamsForLeague(leaguesCatalog[0]?.code)[0]);
  lgSel?.addEventListener("change", () => fillTeamSelect(tmSel, lgSel.value, teamsForLeague(lgSel.value)[0]));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const pid = pSel.value;
    const team = tmSel.value;
    const status = form.status.value || "bench";
    const p = findFaPlayer(pid);
    if (!p || !team) return;
    pushUndo();
    freeAgents = freeAgents.filter((x) => x.id !== pid);
    if (!baselineHome[pid]) baselineHome[pid] = FA_TEAM;
    if (!placeNewPlayer(team, status === "start" ? "bench" : status, { ...p, status })) {
      freeAgents.push(p);
      undoStack.pop();
      updateUndoBtn();
      setStatus(`нет места в ${team}`);
      return;
    }
    dirty = true;
    closeModal("modal-fa-overlay");
    renderAll();
    setStatus(`${p.name} → ${team}`);
  });

  document.getElementById("btn-fa-sign")?.addEventListener("click", () => {
    refreshPlayers();
    if (!freeAgents.length) {
      setStatus("нет свободных агентов");
      return;
    }
    openModal("modal-fa-overlay");
  });
}

async function importSquadsFromFile(file) {
  const text = await file.text();
  const res = await fetch("/api/import-squads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, teams }),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  pushUndo();
  teams = j.teams;
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  dirty = true;
  renderAll();
  const note = (j.notes || []).join("; ");
  setStatus(note || "составы обновлены из бота");
}

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
    ? `${injuryBadge}<span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="pos">${p.position}</span><span class="nm">${p.name}</span>`
    : `${injuryBadge}<span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="nm">${p.name}</span><span class="pos">${p.position}</span>`;
  el.querySelector(".ovr")?.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    startOvrEdit(el.querySelector(".ovr"), p.id);
  });
  el.addEventListener("dragstart", onDragStart);
  el.addEventListener("dragend", stopDragScroll);
  return el;
}

function syncPlayerOverall(id, value) {
  if (!id) return;
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        const slot = team[zone][i];
        if (slot?.id === id) slot.overall = value;
      }
    }
  }
}

function startOvrEdit(span, playerId) {
  if (!span || !playerId) return;
  const inp = document.createElement("input");
  inp.type = "number";
  inp.min = "1";
  inp.max = "99";
  inp.className = "ovr-edit";
  const before = parseInt(span.textContent || "0", 10) || 72;
  inp.value = String(before);
  span.replaceWith(inp);
  inp.focus();
  inp.select();
  const commit = () => {
    const raw = parseInt(inp.value, 10);
    const v = Number.isFinite(raw) ? Math.max(1, Math.min(99, raw)) : before;
    syncPlayerOverall(playerId, v);
    dirty = true;
    setStatus("рейтинг изменён (не сохранено)");
    renderAll();
  };
  inp.addEventListener("blur", commit);
  inp.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      inp.blur();
    }
    if (ev.key === "Escape") {
      ev.preventDefault();
      renderAll();
    }
  });
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
    pushUndo();
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
  if (destTeamName === FA_TEAM) {
    movePlayerToFa(src);
    return;
  }
  const destTeam = teams.find((t) => t.name === destTeamName);
  if (!destTeam) return;

  if (src.fromFa || src.team === FA_TEAM) {
    const faPlayer = findFaPlayer(src.id);
    if (!faPlayer) return;
    freeAgents = freeAgents.filter((p) => p.id !== src.id);
    if (!baselineHome[src.id]) baselineHome[src.id] = FA_TEAM;
    const destSlot = destTeam[destZone][destIndex];
    const moving = { ...faPlayer };
    const displaced = destSlot?.id && destSlot.id !== moving.id ? { ...destSlot } : null;
    removeAllInstancesOfId(moving.id);
    placePlayer(destTeam, destZone, destIndex, moving);
    if (displaced) {
      if (baselineHome[displaced.id] === FA_TEAM) {
        freeAgents.push({ ...displaced, status: "bench" });
      } else {
        const home = baselineHome[displaced.id] || destTeamName;
        const homeTeam = teams.find((t) => t.name === home);
        if (homeTeam) {
          let placed = false;
          for (const z of ["bench", "reserve"]) {
            for (let i = 0; i < homeTeam[z].length; i++) {
              if (!homeTeam[z][i]?.id) {
                placePlayer(homeTeam, z, i, displaced);
                placed = true;
                break;
              }
            }
            if (placed) break;
          }
        }
      }
    }
    dedupeGlobally(teams);
    return;
  }

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
  renderFaPanel();
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  teams.forEach((t) => grid.appendChild(renderTeam(t)));
}

function currentState() {
  return { window: currentWindow, baseline_home: baselineHome, teams, free_agents: freeAgents };
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
  leaguesCatalog = Array.isArray(cfg.leagues) ? cfg.leagues : (rosters.leagues || []);
  if (Array.isArray(cfg.positions)) positionsCatalog = cfg.positions;
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

  const freshBaseline = { ...(rosters.baseline_home || {}) };
  syncFreeAgentsFromRosters(rosters);
  Object.assign(freshBaseline, baselineHome);

  const stateRes = await fetch(`/api/state?window=${encodeURIComponent(currentWindow)}`);
  if (stateRes.ok) {
    const saved = await stateRes.json();
    baselineHome = { ...freshBaseline, ...(saved.baseline_home || {}) };
    teams = migrateSavedState(saved, rosters);
    if (Array.isArray(saved.free_agents) && saved.free_agents.length) {
      freeAgents = saved.free_agents.map((p) => ({ ...p }));
      initFaBaseline(freeAgents);
    }
    dedupeGlobally(teams);
    applyInjuryFlags(teams);
    ensureExtraReserveSlots(teams);
    undoStack = [];
    updateUndoBtn();
    dirty = false;
    const injN = Object.keys(injuryById).length;
    setStatus(
      `загружено: ${windowLabels[currentWindow] || currentWindow}` +
        (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "") +
        (freeAgents.length ? ` · FA: ${freeAgents.length}` : "")
    );
    renderAll();
    return;
  }

  baselineHome = freshBaseline;
  teams = JSON.parse(JSON.stringify(rosters.teams || []));
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  undoStack = [];
  updateUndoBtn();
  dirty = false;
  const injN = Number(rosters.injured_count) || Object.keys(injuryById).length;
  setStatus(
    `сезон ${rosters.season || "?"} — исходные составы (${windowLabels[currentWindow]})` +
      (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "") +
      (freeAgents.length ? ` · FA: ${freeAgents.length}` : "")
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
document.getElementById("btn-undo").addEventListener("click", undoLast);
document.getElementById("btn-export-txt").addEventListener("click", () => exportFmt("txt"));
document.getElementById("btn-export-xlsx").addEventListener("click", () => exportFmt("xlsx"));
document.getElementById("btn-export-transfers-txt").addEventListener("click", () => exportTransfersFmt("simple"));
document.getElementById("btn-export-transfers-xlsx").addEventListener("click", () => exportTransfersFmt("xlsx"));
document.getElementById("btn-summer").addEventListener("click", () => switchWindow("summer"));
document.getElementById("btn-winter").addEventListener("click", () => switchWindow("winter"));
document.getElementById("btn-new-player")?.addEventListener("click", () => openModal("modal-overlay"));
document.getElementById("modal-close")?.addEventListener("click", () => closeModal("modal-overlay"));
document.getElementById("modal-cancel")?.addEventListener("click", () => closeModal("modal-overlay"));
document.getElementById("modal-fa-close")?.addEventListener("click", () => closeModal("modal-fa-overlay"));
document.getElementById("modal-fa-cancel")?.addEventListener("click", () => closeModal("modal-fa-overlay"));
document.getElementById("btn-import-squads")?.addEventListener("click", () => {
  document.getElementById("import-squads-file")?.click();
});
document.getElementById("import-squads-file")?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  if (!f) return;
  try {
    await importSquadsFromFile(f);
  } catch (err) {
    setStatus("ошибка импорта: " + err.message);
  }
});

loadData()
  .then(() => {
    setupPlayerForm();
    setupFaSignForm();
  })
  .catch((e) => setStatus("ошибка: " + e.message));
