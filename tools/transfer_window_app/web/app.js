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
let removedFromSquad = {};
let rostersSeason = null;
let leaguesCatalog = [];
let positionsCatalog = ["GK", "CB", "LB", "RB", "CDM", "CM", "CAM", "LW", "RW", "ST"];

const SQUAD_TARGET = 32;
const SQUAD_START_TARGET = 11;
const SQUAD_RESERVE_TARGET = 21;

const SLOT_RESERVE_LABEL = {
  GK: "ВРТ",
  LB: "ЛЗ",
  RB: "ПЗ",
  LCB: "ЦЗ",
  RCB: "ЦЗ",
  CB: "ЦЗ",
  LW: "ЛФА",
  ST: "ФРВ",
  RW: "ПФА",
  LCM: "ЦП",
  RCM: "ЦП",
  CAM: "ЦАП",
  CDM: "ЦОП",
  LM: "ЛП",
  RM: "ПП",
  STL: "ФРВ",
  STR: "ПФА",
  CCM: "ЦП",
};

let squadRules = {
  total: SQUAD_TARGET,
  start: SQUAD_START_TARGET,
  reserve: SQUAD_RESERVE_TARGET,
};

function formationById(fid) {
  const id = Number(fid) || 1;
  return formationsCatalog.find((f) => Number(f.id) === id) || null;
}

function primaryReserveLabel(slotId, allowed) {
  const pref = SLOT_RESERVE_LABEL[slotId];
  if (pref && allowed.includes(pref)) return pref;
  return allowed.length ? allowed.slice().sort()[0] : slotId || "?";
}

function reserveGroupsForFormation(form) {
  if (!form || !Array.isArray(form.slots)) return [];
  return form.slots.map((slot) => {
    const sid = String(slot.slot_id || "").trim();
    const allowed = (slot.allowed_positions || []).map((p) => String(p).trim().toUpperCase()).filter(Boolean);
    return {
      slot_id: sid,
      label: primaryReserveLabel(sid, allowed),
      allowed,
      need: sid === "GK" ? 1 : 2,
    };
  });
}

function assignSubstitutesToGroups(players, groups) {
  const pool = (players || []).filter((p) => p && p.name && String(p.position || "").trim());
  const assigned = groups.map(() => 0);
  const used = pool.map(() => false);

  const order = groups
    .map((g, i) => i)
    .sort((a, b) => {
      const ga = groups[a];
      const gb = groups[b];
      return ga.allowed.length - gb.allowed.length || gb.need - ga.need || ga.slot_id.localeCompare(gb.slot_id);
    });

  for (const gi of order) {
    const g = groups[gi];
    for (let n = 0; n < g.need; n += 1) {
      let picked = -1;
      for (let pi = 0; pi < pool.length; pi += 1) {
        if (used[pi]) continue;
        const pos = String(pool[pi].position || "").trim().toUpperCase();
        if (g.allowed.includes(pos)) {
          picked = pi;
          break;
        }
      }
      if (picked < 0) break;
      used[picked] = true;
      assigned[gi] += 1;
    }
  }

  const missing = [];
  groups.forEach((g, i) => {
    const short = g.need - assigned[i];
    if (short > 0) missing.push({ slot_id: g.slot_id, label: g.label, need: short });
  });

  const surplus = [];
  pool.forEach((p, pi) => {
    if (used[pi]) return;
    const pos = String(p.position || "").trim().toUpperCase();
    let label = pos;
    for (const g of groups) {
      if (g.allowed.includes(pos)) {
        label = g.label;
        break;
      }
    }
    surplus.push({ name: p.name, position: pos, label });
  });

  return { assigned, missing, surplus };
}

function aggregateSurplus(surplus) {
  const agg = {};
  (surplus || []).forEach((s) => {
    const lab = s.label || s.position || "?";
    agg[lab] = (agg[lab] || 0) + 1;
  });
  return Object.keys(agg)
    .sort()
    .map((label) => ({ label, extra: agg[label] }));
}

function labelStatsFromSubs(subs, groups) {
  const map = {};
  groups.forEach((g) => {
    if (!map[g.label]) map[g.label] = { label: g.label, need: 0, allowed: new Set() };
    map[g.label].need += g.need;
    g.allowed.forEach((p) => map[g.label].allowed.add(p));
  });
  return Object.values(map)
    .map((v) => {
      const have = subs.filter((p) =>
        v.allowed.has(String(p.position || "").trim().toUpperCase())
      ).length;
      return { label: v.label, need: v.need, have, extra: Math.max(0, have - v.need) };
    })
    .sort((a, b) => a.label.localeCompare(b.label, "ru"));
}

function aggregateMissing(missing) {
  const agg = {};
  (missing || []).forEach((m) => {
    agg[m.label] = (agg[m.label] || 0) + Number(m.need || 0);
  });
  return Object.keys(agg)
    .sort()
    .map((label) => ({ label, need: agg[label] }));
}

function aggregateGroupStatus(groupStatus) {
  const agg = {};
  (groupStatus || []).forEach((g) => {
    if (!agg[g.label]) agg[g.label] = { label: g.label, need: 0, have: 0 };
    agg[g.label].need += Number(g.need || 0);
    agg[g.label].have += Number(g.have || 0);
  });
  return Object.values(agg).sort((a, b) => a.label.localeCompare(b.label, "ru"));
}

function evaluateTeamSquad(team) {
  const form = formationById(team.formation_id);
  const groups = reserveGroupsForFormation(form);
  const starters = (team.start || []).filter((p) => p && p.id);
  const subs = [];
  ["bench", "reserve"].forEach((zone) => {
    (team[zone] || []).forEach((p) => {
      if (p && p.id) subs.push(p);
    });
  });

  const startSlots = team.start || [];
  const startMissing = startSlots.filter((s) => !(s && s.id)).length;
  const { assigned, missing, surplus } = assignSubstitutesToGroups(subs, groups);
  const missingAgg = aggregateMissing(missing);
  const surplusAgg = aggregateSurplus(surplus);

  const groupStatus = groups.map((g, i) => ({
    slot_id: g.slot_id,
    label: g.label,
    need: g.need,
    have: assigned[i],
    allowed: g.allowed,
  }));

  const total = starters.length + subs.length;
  const complete =
    startMissing === 0 &&
    missing.length === 0 &&
    surplus.length === 0 &&
    total === SQUAD_TARGET &&
    startSlots.length === SQUAD_START_TARGET;

  return {
    team: team.name,
    total,
    target: SQUAD_TARGET,
    start_filled: SQUAD_START_TARGET - startMissing,
    reserve_filled: SQUAD_RESERVE_TARGET - missing.reduce((s, m) => s + m.need, 0),
    complete,
    missing_start: startMissing,
    missing_reserve: missingAgg,
    surplus_reserve: surplusAgg,
    group_status: groupStatus,
    label_stats: labelStatsFromSubs(subs, groups),
  };
}

function formatMissingHint(ev) {
  const parts = [];
  if (Number(ev.missing_start) > 0) parts.push(`основа ×${ev.missing_start}`);
  (ev.missing_reserve || []).forEach((m) => parts.push(`${m.label} ×${m.need}`));
  if (Number(ev.total) < SQUAD_TARGET) parts.push(`всего ${ev.total}/${SQUAD_TARGET}`);
  return parts;
}

function formatSurplusHint(ev) {
  const parts = [];
  (ev.surplus_reserve || []).forEach((s) => parts.push(`${s.label} ×${s.extra}`));
  if (Number(ev.total) > SQUAD_TARGET && !(ev.surplus_reserve || []).length) {
    parts.push(`всего +${ev.total - SQUAD_TARGET}`);
  }
  return parts;
}

function formatSquadIssues(ev) {
  const miss = formatMissingHint(ev);
  const extra = formatSurplusHint(ev);
  const chunks = [];
  if (miss.length) chunks.push(`не хватает: ${miss.join(" · ")}`);
  if (extra.length) chunks.push(`лишние: ${extra.join(" · ")}`);
  return chunks.length ? chunks.join(" · ") : "OK";
}

function findIncompleteSquads() {
  return teams
    .map((t) => evaluateTeamSquad(t))
    .filter((ev) => !ev.complete);
}

function squadExportBlockedMessage(incomplete) {
  const lines = incomplete.slice(0, 10).map((ev) => `${ev.team}: ${formatSquadIssues(ev)}`);
  const tail = incomplete.length > 10 ? `\n… и ещё ${incomplete.length - 10} клубов` : "";
  return (
    "Нельзя выгрузить составы: заявка должна быть 32 игрока " +
    `(11 основа + 21 замена по слотам схемы, у вратаря 1).\n\n${lines.join("\n")}${tail}`
  );
}

function pushUndo() {
  undoStack.push({
    teams: JSON.parse(JSON.stringify(teams)),
    freeAgents: JSON.parse(JSON.stringify(freeAgents)),
    baselineHome: { ...baselineHome },
    removedFromSquad: JSON.parse(JSON.stringify(removedFromSquad)),
  });
  if (undoStack.length > 50) undoStack.shift();
  updateUndoBtn();
}

function updateUndoBtn() {
  const btn = document.getElementById("btn-undo");
  if (btn) btn.disabled = undoStack.length === 0;
}

function loadFreshFromRosters(rosters, msg) {
  baselineHome = { ...(rosters.baseline_home || {}) };
  syncFreeAgentsFromRosters(rosters);
  teams = JSON.parse(JSON.stringify(rosters.teams || []));
  freeAgents = (rosters.free_agents || []).map((p) => ({ ...p, status: p.status || "bench" }));
  initFaBaseline(freeAgents);
  removedFromSquad = {};
  undoStack = [];
  updateUndoBtn();
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  dirty = false;
  renderAll();
  if (msg) setStatus(msg);
}

function resetToDbRosters() {
  const ok = window.confirm(
    "Сбросить все изменения и загрузить составы из rosters.json?\n" +
      "Текущие несохранённые трансферы будут потеряны."
  );
  if (!ok) return;
  fetch("/api/rosters")
    .then((r) => r.json())
    .then(async (rosters) => {
      rostersSeason = rosters.season ?? rostersSeason;
      loadFreshFromRosters(
        rosters,
        `сброс → сезон ${rosters.season || "?"} (${windowLabels[currentWindow]})`
      );
      await saveState();
    })
    .catch((e) => setStatus("ошибка сброса: " + e.message));
}

function undoLast() {
  const snap = undoStack.pop();
  if (!snap) return;
  teams = snap.teams;
  freeAgents = snap.freeAgents;
  baselineHome = snap.baselineHome;
  removedFromSquad = snap.removedFromSquad || {};
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

function removePlayerFromSquad(playerId, teamName) {
  const loc = findPlayerGlobally(playerId);
  if (!loc || !loc.player) return;
  const p = loc.player;
  const home = baselineHome[playerId] || loc.teamName;
  const msg =
    `Убрать ${p.name} (${p.position}, ${p.overall}) из заявки?\n\n` +
    `Клуб: ${home}\n` +
    "Игрок исчезнет из состава сезона — это не трансфер. " +
    "В БД останется история (person_id, прошлые сезоны).\n\n" +
    "Отменить можно кнопкой ↩ до закрытия приложения.";
  if (!window.confirm(msg)) return;
  pushUndo();
  removedFromSquad[playerId] = {
    id: playerId,
    name: p.name,
    position: p.position,
    overall: p.overall,
    home_team: home,
    removed_from: teamName || loc.teamName,
  };
  delete baselineHome[playerId];
  removeAllInstancesOfId(playerId);
  freeAgents = freeAgents.filter((x) => x.id !== playerId);
  dedupeGlobally(teams);
  dirty = true;
  renderAll();
  setStatus(`убран из заявки: ${p.name} (не трансфер)`);
}

function countInOut(team) {
  const ids = new Set();
  const collect = (arr) => arr.forEach((p) => { if (p && p.id) ids.add(p.id); });
  collect(team.start);
  collect(team.bench);
  collect(team.reserve);
  let inn = 0;
  ids.forEach((id) => {
    if (removedFromSquad[id]) return;
    if (baselineHome[id] !== team.name) inn += 1;
  });
  let out = 0;
  Object.entries(baselineHome).forEach(([id, home]) => {
    if (removedFromSquad[id]) return;
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
    ? `${injuryBadge}<button type="button" class="rm-btn" title="Убрать из заявки">×</button><span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="pos">${p.position}</span><span class="nm">${p.name}</span>`
    : `${injuryBadge}<button type="button" class="rm-btn" title="Убрать из заявки">×</button><span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="nm">${p.name}</span><span class="pos">${p.position}</span>`;
  el.querySelector(".rm-btn")?.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    removePlayerFromSquad(p.id, teamName);
  });
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

  const squadEv = evaluateTeamSquad(team);
  if (!squadEv.complete) card.classList.add("squad-incomplete");

  const quota = document.createElement("div");
  quota.className = "squad-quota" + (squadEv.complete ? " ok" : " warn");
  const qHead = document.createElement("div");
  qHead.className = "squad-quota-head";
  qHead.textContent = squadEv.complete
    ? `Заявка ${squadEv.total}/${SQUAD_TARGET} ✓`
    : `Заявка ${squadEv.total}/${SQUAD_TARGET} · замены ${squadEv.reserve_filled}/${SQUAD_RESERVE_TARGET}`;
  quota.appendChild(qHead);
  if (!squadEv.complete) {
    const qMiss = document.createElement("div");
    qMiss.className = "squad-quota-miss";
    qMiss.textContent = formatSquadIssues(squadEv);
    quota.appendChild(qMiss);
  }
  const qGrid = document.createElement("div");
  qGrid.className = "squad-quota-grid";
  (squadEv.label_stats || aggregateGroupStatus(squadEv.group_status)).forEach((g) => {
    const chip = document.createElement("span");
    let cls = "sq-chip";
    if (g.have > g.need) cls += " over";
    else if (g.have >= g.need) cls += " done";
    else if (g.have > 0) cls += " part";
    chip.className = cls;
    chip.textContent =
      g.have > g.need ? `${g.label} ${g.have}/${g.need} (+${g.have - g.need})` : `${g.label} ${g.have}/${g.need}`;
    chip.title =
      g.have > g.need
        ? `Лишний игрок на позицию ${g.label}: нужно ${g.need}, в заявке ${g.have}`
        : `Замены на позицию ${g.label}: нужно ${g.need}`;
    qGrid.appendChild(chip);
  });
  quota.appendChild(qGrid);
  hdr.appendChild(quota);

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
  hBench.textContent = "Запасные (в заявку 32)";
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
  hRes.textContent = "Резерв (замены по позициям)";
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
  return {
    window: currentWindow,
    season: rostersSeason,
    baseline_home: baselineHome,
    teams,
    free_agents: freeAgents,
    removed_from_squad: removedFromSquad,
    formations: formationsCatalog,
  };
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
  rostersSeason = rosters.season ?? null;
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
  if (cfg.squad_rules) squadRules = { ...squadRules, ...cfg.squad_rules };
  localStorage.setItem("tw_window", currentWindow);
  injuryAsOfMonth = Number(rosters.injury_as_of_month) || 6;
  injuryById = buildInjuryIndex(rosters);
  formationsCatalog = Array.isArray(rosters.formations) ? rosters.formations : [];
  if (rosters.squad_rules) squadRules = { ...squadRules, ...rosters.squad_rules };
  if (cfg.data_dir) {
    window.__twDataDir = cfg.data_dir;
  }

  const freshBaseline = { ...(rosters.baseline_home || {}) };
  syncFreeAgentsFromRosters(rosters);
  for (const pid of Object.keys(freshBaseline)) {
    if (!(pid in baselineHome) || baselineHome[pid] === undefined) {
      baselineHome[pid] = freshBaseline[pid];
    }
  }

  const stateRes = await fetch(`/api/state?window=${encodeURIComponent(currentWindow)}`);
  if (stateRes.ok) {
    const saved = await stateRes.json();
    const savedSeason = saved.season != null ? Number(saved.season) : null;
    const curSeason = rostersSeason != null ? Number(rostersSeason) : null;
    if (savedSeason != null && curSeason != null && savedSeason !== curSeason) {
      loadFreshFromRosters(
        rosters,
        `сезон ${curSeason}: старый сейв (${savedSeason}) сброшен — 0/${maxOut} OUT`
      );
      await saveState();
      return;
    }
    if (savedSeason == null && curSeason != null) {
      loadFreshFromRosters(
        rosters,
        `сезон ${curSeason}: устаревший сейв сброшен (не было метки сезона)`
      );
      await saveState();
      return;
    }
    baselineHome = saved.baseline_home && Object.keys(saved.baseline_home).length
      ? { ...saved.baseline_home }
      : freshBaseline;
    teams = migrateSavedState(saved, rosters);
    if (Array.isArray(saved.free_agents) && saved.free_agents.length) {
      freeAgents = saved.free_agents.map((p) => ({ ...p }));
      initFaBaseline(freeAgents);
    }
    removedFromSquad = saved.removed_from_squad || {};
    dedupeGlobally(teams);
    applyInjuryFlags(teams);
    ensureExtraReserveSlots(teams);
    undoStack = [];
    updateUndoBtn();
    dirty = false;
    const injN = Object.keys(injuryById).length;
    const rmN = Object.keys(removedFromSquad).length;
    setStatus(
      `загружено: ${windowLabels[currentWindow] || currentWindow}` +
        (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "") +
        (freeAgents.length ? ` · FA: ${freeAgents.length}` : "") +
        (rmN ? ` · убрано: ${rmN}` : "")
    );
    renderAll();
    return;
  }

  baselineHome = freshBaseline;
  loadFreshFromRosters(
    rosters,
    `сезон ${rosters.season || "?"} — исходные составы (${windowLabels[currentWindow]})` +
      (Number(rosters.injured_count) || Object.keys(injuryById).length
        ? ` · травм: ${Number(rosters.injured_count) || Object.keys(injuryById).length}`
        : "") +
      (freeAgents.length ? ` · FA: ${freeAgents.length}` : "")
  );
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
  const incomplete = findIncompleteSquads();
  if (incomplete.length) {
    const ok = window.confirm(
      `Неполная заявка у ${incomplete.length} клуб(ов).\n` +
        `Нужно ${SQUAD_TARGET} игроков (11 основа + 21 замена).\n\n` +
        `Пример: ${incomplete[0].team} — ${formatSquadIssues(incomplete[0])}\n\n` +
        "Всё равно сохранить черновик?"
    );
    if (!ok) return;
  }
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
  const incomplete = findIncompleteSquads();
  if (incomplete.length) {
    window.alert(squadExportBlockedMessage(incomplete));
    setStatus(`экспорт блокирован: неполная заявка (${incomplete.length} клубов)`);
    return;
  }
  const res = await fetch(`/api/export?fmt=${fmt}&kind=squads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(j.ok ? `выгружено: ${j.path}` : `ошибка: ${j.error || "?"}`);
  if (!j.ok && j.error) window.alert(j.error);
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
document.getElementById("btn-reset-rosters")?.addEventListener("click", () => {
  resetToDbRosters();
});
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
