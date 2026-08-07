/* global fetch */

let baselineHome = {};
let teams = [];
let dragPayload = null;
let dragScrollActive = false;
let currentWindow = "summer";
let currentMode = "clubs";
let selectedNation = "";
let maxIn = 5;
let maxOut = 5;
let dirty = false;
/** Клубы/FA с локальными правками, ещё не стянутыми с сервера. */
let dirtyTeams = new Set();
let windowLabels = { summer: "Лето", winter: "Зима" };
let injuryAsOfMonth = 6;
let injuryById = {};
let formationsCatalog = []; // [{id, label, key, slots}]
const BENCH_SLOTS = 7;
const EXTRA_RESERVE = 5;
const FA_TEAM = "Free Agent";

let freeAgents = [];
let nationalPools = null;
let nationalFilter = "";
let faFilter = "";
const nationalExpanded = new Set();
const poolFiltersEmpty = { ovrMin: "", ovrMax: "", position: "" };
let faPoolFilters = { ...poolFiltersEmpty, kind: "" };
let nationalPoolFilters = { ...poolFiltersEmpty };
let lastRosters = null;
let stateRevision = 0;
let clientIdentity = { id: "", name: "" };
let syncPollTimer = null;
let pendingRemoteMeta = null;
let liveSyncEnabled = false;
let autosaveTimer = null;
let autosaveInFlight = false;
let periodicAutosaveTimer = null;
const LIVE_SYNC_POLL_MS = 1000;
const LIVE_SYNC_DEBOUNCE_MS = 700;
const SYNC_POLL_MS = 2500;
const PERIODIC_AUTOSAVE_MS = 10 * 60 * 1000;
let undoStack = [];
let removedFromSquad = {};
let rostersSeason = null;
let rostersRevision = null;
let leaguesCatalog = [];
let nationsByConfederation = {};
let nationsList = [];
let positionsCatalog = [
  "ВРТ", "ЛЗ", "ПЗ", "ЦЗ", "ЛЦЗ", "ПЦЗ", "ЛФЗ", "ПФЗ",
  "ЦП", "ЦАП", "ЦОП", "ЛП", "ПП", "ЛЦП", "ПЦП",
  "ЛФА", "ПФА", "ФРВ", "ЦФД", "ЛФД", "ПФД",
];
let coachesCatalog = [];
let playerProfiles = {};

const SQUAD_TARGET = 32;
const SQUAD_START_TARGET = 11;
const SQUAD_RESERVE_TARGET = 21;
/** Замены вне старта: 21 = 7 в «Запасе» + 14 в «Резерве». */
const MIN_RESERVE_SLOTS = SQUAD_RESERVE_TARGET - BENCH_SLOTS;
const WC_TOTAL = 26;
const WC_START = 11;
const WC_BENCH = 7;
const WC_RESERVE = 8;
const WC_GK_TOTAL = 2;

function isNationsMode() {
  return currentMode === "nations";
}

function rostersLookLikeClubs(rosters) {
  const list = rosters?.teams || [];
  if (!list.length) return false;
  const sample = list.slice(0, 5);
  const clubish = sample.filter((t) => String(t.league || "").trim() !== "Сборная").length;
  return clubish >= Math.min(3, sample.length);
}

function assertNationsRosters(rosters) {
  if (!isNationsMode()) return true;
  if (rosters?.mode === "nations" && !rostersLookLikeClubs(rosters)) return true;
  const msg =
    "Сервер на :8765 устарел — отдаёт клубы вместо 48 сборных ЧМ.\n\n" +
    "Останови старый процесс и перезапусти:\n" +
    "  tools/transfer_window_app/run.sh\n\n" +
    "Или: lsof -ti :8765 | xargs kill -9 && ./run.sh";
  window.alert(msg);
  setStatus("⚠ перезапусти transfer app (run.sh) — нужен режим сборных ЧМ");
  return false;
}

function activeSquadTarget() {
  return isNationsMode() ? WC_TOTAL : SQUAD_TARGET;
}

function activeStartTarget() {
  return isNationsMode() ? WC_START : SQUAD_START_TARGET;
}

function activeBenchCount() {
  return isNationsMode() ? WC_BENCH : BENCH_SLOTS;
}

function activeReserveCount() {
  return isNationsMode() ? WC_RESERVE : null;
}

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
        const want = String(g.label || "").trim().toUpperCase();
        if (pos === want) {
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
      if (String(g.label || "").trim().toUpperCase() === pos) {
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
  if (isNationsMode()) return evaluateWcTeamSquad(team);

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
    missing_groups: missing,
    surplus_reserve: surplusAgg,
    group_status: groupStatus,
  };
}

function countGoalkeepers(players) {
  return (players || []).filter(
    (p) => p && p.id && String(p.position || "").trim().toUpperCase() === "ВРТ"
  ).length;
}

function evaluateWcTeamSquad(team) {
  const starters = (team.start || []).filter((p) => p && p.id);
  const bench = (team.bench || []).filter((p) => p && p.id);
  const reserve = (team.reserve || []).filter((p) => p && p.id);
  const all = [...starters, ...bench, ...reserve];
  const startMissing = (team.start || []).filter((s) => !(s && s.id)).length;
  const benchMissing = Math.max(0, WC_BENCH - bench.length);
  const reserveMissing = Math.max(0, WC_RESERVE - reserve.length);
  const total = all.length;
  const gkHave = countGoalkeepers(all);
  const gkStart = countGoalkeepers(starters);
  const gkMissing = Math.max(0, WC_GK_TOTAL - gkHave);
  const complete =
    startMissing === 0 &&
    benchMissing === 0 &&
    reserveMissing === 0 &&
    total === WC_TOTAL &&
    gkHave >= WC_GK_TOTAL &&
    gkStart >= 1;

  const missingReserve = [];
  if (benchMissing) missingReserve.push({ label: "запас", need: benchMissing });
  if (reserveMissing) missingReserve.push({ label: "резерв", need: reserveMissing });

  return {
    team: team.name,
    total,
    target: WC_TOTAL,
    start_filled: WC_START - startMissing,
    reserve_filled: bench.length + reserve.length,
    complete,
    missing_start: startMissing,
    missing_reserve: missingReserve,
    missing_groups: [],
    surplus_reserve: total > WC_TOTAL ? [{ label: "всего", extra: total - WC_TOTAL }] : [],
    group_status: [],
    gk_have: gkHave,
    gk_missing: gkMissing,
    gk_start: gkStart,
    wc_mode: true,
  };
}

function formatMissingHint(ev) {
  const target = ev.target ?? (ev.wc_mode || isNationsMode() ? WC_TOTAL : SQUAD_TARGET);
  const wc = !!(ev.wc_mode || target === WC_TOTAL);
  const parts = [];
  if (Number(ev.missing_start) > 0) {
    parts.push(wc ? `старт ×${ev.missing_start}` : `основа ×${ev.missing_start}`);
  }
  (ev.missing_groups || []).forEach((m) => {
    parts.push(`${m.label} ${Number(m.need || 0)}`);
  });
  if (!(ev.missing_groups || []).length) {
    (ev.missing_reserve || []).forEach((m) => parts.push(`${m.label} ×${m.need}`));
  }
  if (wc) {
    const gkMiss = Number(ev.gk_missing ?? 0);
    if (gkMiss > 0) parts.push(`вратари ×${WC_GK_TOTAL}`);
    else if (Number(ev.gk_start ?? 0) < 1) parts.push("вратарь в старте ×1");
  } else if (Number(ev.total) < target) {
    parts.push(`всего ${ev.total}/${target}`);
  }
  return parts;
}

function formatSurplusHint(ev) {
  const target = ev.target ?? (ev.wc_mode || isNationsMode() ? WC_TOTAL : SQUAD_TARGET);
  const wc = !!(ev.wc_mode || target === WC_TOTAL);
  const parts = [];
  (ev.surplus_reserve || []).forEach((s) => parts.push(`${s.label} ×${s.extra}`));
  if (!wc && Number(ev.total) > target && !(ev.surplus_reserve || []).length) {
    parts.push(`всего +${ev.total - target}`);
  } else if (wc && Number(ev.total) > target && !(ev.surplus_reserve || []).length) {
    parts.push(`всего +${ev.total - target}`);
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
  const tail = incomplete.length > 10 ? `\n… и ещё ${incomplete.length - 10}` : "";
  if (isNationsMode()) {
    return (
      `Нельзя выгрузить заявки ЧМ: нужно ${WC_TOTAL} игроков ` +
      `(11 старт + 7 запас + 8 резерв).\n\n${lines.join("\n")}${tail}`
    );
  }
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

function ensureClientIdentity() {
  let id = localStorage.getItem("tw_client_id");
  if (!id) {
    id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `p${Date.now()}`;
    localStorage.setItem("tw_client_id", id);
  }
  let name = localStorage.getItem("tw_client_name");
  if (!name) {
    const entered = window.prompt("Ваше имя для мультиплеера (видят напарники):", "") || "";
    name = entered.trim() || "игрок";
    localStorage.setItem("tw_client_name", name);
  }
  clientIdentity = { id, name };
  return clientIdentity;
}

function setLiveSyncEnabled(on) {
  liveSyncEnabled = !!on;
  const badge = document.getElementById("live-badge");
  if (badge) badge.hidden = !liveSyncEnabled;
  startSyncPoll();
}

function markDirty(...teamNames) {
  dirty = true;
  for (const raw of teamNames) {
    const name = String(raw || "").trim();
    if (name) dirtyTeams.add(name);
  }
  if (lastRosters && !isNationsMode()) repairBaselineHomeFromRosters(lastRosters);
  scheduleAutosave();
}

function snapshotDirtyTeams() {
  const snap = { teams: {}, fa: null };
  for (const name of dirtyTeams) {
    if (name === FA_TEAM) {
      snap.fa = JSON.parse(JSON.stringify(freeAgents));
      continue;
    }
    const t = teams.find((x) => x.name === name);
    if (t) snap.teams[name] = JSON.parse(JSON.stringify(t));
  }
  return snap;
}

function restoreDirtyTeamsSnapshot(snap) {
  if (!snap) return;
  for (const [name, t] of Object.entries(snap.teams || {})) {
    const idx = teams.findIndex((x) => x.name === name);
    if (idx >= 0) teams[idx] = t;
  }
  if (snap.fa) freeAgents = snap.fa;
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
}

/** Подтянуть с сервера всё, кроме клубов из dirtyTeams. */
async function pullRemoteStatePartial() {
  const url = isNationsMode()
    ? "/api/state?mode=nations"
    : `/api/state?window=${encodeURIComponent(currentWindow)}`;
  const res = await fetch(url);
  if (!res.ok) return false;
  const saved = await res.json();
  if (!lastRosters) return false;
  const kept = new Set(dirtyTeams);
  const snap = snapshotDirtyTeams();
  applySavedState(saved, lastRosters);
  if (kept.size) {
    restoreDirtyTeamsSnapshot(snap);
    dirtyTeams = kept;
    dirty = true;
  }
  hideSyncBanner();
  updateSyncBadge(saved);
  return true;
}

function scheduleAutosave() {
  if (!liveSyncEnabled || !dirty) return;
  if (autosaveTimer) clearTimeout(autosaveTimer);
  autosaveTimer = setTimeout(() => {
    autosaveTimer = null;
    flushAutosave();
  }, LIVE_SYNC_DEBOUNCE_MS);
}

async function flushAutosave() {
  if (!liveSyncEnabled || !dirty || autosaveInFlight) return;
  autosaveInFlight = true;
  try {
    await saveState({ silent: true, skipIncompleteConfirm: true });
  } finally {
    autosaveInFlight = false;
  }
}

function startPeriodicAutosave() {
  if (periodicAutosaveTimer) clearInterval(periodicAutosaveTimer);
  periodicAutosaveTimer = setInterval(async () => {
    if (!dirty || autosaveInFlight || dragPayload) return;
    autosaveInFlight = true;
    try {
      await saveState({ silent: true, skipIncompleteConfirm: true });
      setStatus(`⟳ автосейв · rev ${stateRevision}`);
    } finally {
      autosaveInFlight = false;
    }
  }, PERIODIC_AUTOSAVE_MS);
}

function updateSyncBadge(meta) {
  const el = document.getElementById("sync-badge");
  if (!el || !meta) return;
  const who = meta.updated_by ? ` · ${meta.updated_by}` : "";
  el.textContent = meta.revision ? `rev ${meta.revision}${who}` : "rev 0";
}

function updateSharePanel(mp) {
  const panel = document.getElementById("share-panel");
  const input = document.getElementById("share-url");
  if (!panel || !input || !mp) return;
  const url = mp.share_url || mp.tunnel_url || mp.tailscale_url || mp.lan_url;
  if (!url) {
    panel.hidden = true;
    lastShareUrl = "";
    return;
  }
  lastShareUrl = url;
  panel.hidden = false;
  input.value = url;
  input.title = mp.tunnel_url
    ? "Публичная ссылка — работает из любой квартиры (клик — выделить)"
    : mp.tailscale_url
      ? "Tailscale — из разных квартир, если оба в tailnet"
      : "LAN — только одна Wi‑Fi сеть (клик — выделить)";
}

let lastShareUrl = "";

function selectShareUrlInput(input) {
  if (!input?.value) return;
  input.focus();
  input.select();
  try {
    input.setSelectionRange(0, input.value.length);
  } catch (_) {
    /* Safari/old WebKit */
  }
}

async function copyTextToClipboard(text) {
  const s = String(text || "").trim();
  if (!s) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(s);
      return true;
    }
  } catch (_) {
    /* fallback below */
  }
  try {
    const ta = document.createElement("textarea");
    ta.value = s;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    ta.style.top = "0";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    ta.setSelectionRange(0, s.length);
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch (_) {
    return false;
  }
}

async function pollTunnelUrl() {
  for (let i = 0; i < 45; i += 1) {
    await new Promise((r) => setTimeout(r, 2000));
    try {
      const res = await fetch("/api/config");
      if (!res.ok) continue;
      const cfg = await res.json();
      const mp = cfg.multiplayer || {};
      if (mp.tunnel_url || mp.tunnel_error || !mp.tunnel_pending) {
        updateSharePanel(mp);
        if (mp.tunnel_url) setStatus("ссылка для друга готова — копируй из шапки");
        else if (mp.tunnel_error) setStatus("туннель: " + mp.tunnel_error);
        return;
      }
    } catch (_) {
      /* retry */
    }
  }
}

function setupSharePanel() {
  const input = document.getElementById("share-url");
  const btn = document.getElementById("btn-copy-share");
  input?.addEventListener("click", () => selectShareUrlInput(input));
  input?.addEventListener("focus", () => selectShareUrlInput(input));
  btn?.addEventListener("click", async () => {
    const url = lastShareUrl || input?.value || "";
    if (!url) {
      setStatus("ссылка ещё не готова");
      return;
    }
    selectShareUrlInput(input);
    const ok = await copyTextToClipboard(url);
    if (ok) {
      setStatus("ссылка скопирована");
      const prev = btn.textContent;
      btn.textContent = "Скопировано";
      setTimeout(() => {
        btn.textContent = prev;
      }, 1500);
    } else {
      setStatus("не удалось скопировать — выдели ссылку и Cmd+C");
    }
  });
}

function showSyncBanner(meta) {
  pendingRemoteMeta = meta;
  const who = meta.updated_by || "напарник";
  const msg =
    `${who} сохранил новее (rev ${meta.revision}). «Загрузить его» — его версия. «Оставить моё» — перезаписать вашей.`;
  const bar = document.getElementById("sync-banner");
  if (bar) {
    bar.hidden = false;
    const textEl = bar.querySelector(".sync-banner-text");
    if (textEl) textEl.textContent = msg;
  }
  document.body.classList.add("sync-banner-open");
  const tb = document.getElementById("sync-conflict-toolbar");
  const tbLabel = document.getElementById("sync-conflict-label");
  if (tb) tb.hidden = false;
  if (tbLabel) tbLabel.textContent = `${who} · rev ${meta.revision}`;
  setStatus(`⚠ конфликт: ${who} — кнопки «Загрузить его» / «Оставить моё» в шапке`);
}

function hideSyncBanner() {
  pendingRemoteMeta = null;
  const bar = document.getElementById("sync-banner");
  if (bar) bar.hidden = true;
  document.body.classList.remove("sync-banner-open");
  const tb = document.getElementById("sync-conflict-toolbar");
  if (tb) tb.hidden = true;
}

async function fetchRemoteMeta() {
  const url = isNationsMode()
    ? "/api/state/meta?mode=nations"
    : `/api/state/meta?window=${encodeURIComponent(currentWindow)}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error("meta");
  return res.json();
}

/** Перезаписать сервер локальной версией после конфликта с напарником. */
async function keepLocalVersion() {
  hideSyncBanner();
  try {
    const url = isNationsMode()
      ? "/api/state?mode=nations"
      : `/api/state?window=${encodeURIComponent(currentWindow)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("state");
    const saved = await res.json();
    stateRevision = Number(saved.revision) || stateRevision;
    if (dirtyTeams.size) {
      const kept = new Set(dirtyTeams);
      const snap = snapshotDirtyTeams();
      applySavedState(saved, lastRosters);
      restoreDirtyTeamsSnapshot(snap);
      dirtyTeams = kept;
      dirty = true;
    } else {
      dirty = true;
    }
    await saveState({ silent: true, skipIncompleteConfirm: true });
    setStatus(`сохранена ваша версия (rev ${stateRevision})`);
  } catch (e) {
    setStatus("не удалось сохранить вашу версию: " + (e.message || e));
  }
}

function buildFreshRosterIndexes(rosters) {
  const byId = new Map();
  const teamIds = new Map();
  for (const t of rosters?.teams || []) {
    const ids = new Set();
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of t[zone] || []) {
        if (!p?.id) continue;
        byId.set(p.id, { ...p, _team: t.name });
        ids.add(p.id);
      }
    }
    teamIds.set(t.name, ids);
  }
  return { byId, teamIds, baseline: rosters?.baseline_home || {} };
}

function clearTeamSlot(team, zone, index) {
  const slot = team[zone][index];
  if (zone === "start") {
    team[zone][index] = {
      id: null,
      name: null,
      position: null,
      overall: null,
      injured: false,
      slot: slot?.slot,
      x: slot?.x,
      y: slot?.y,
    };
  } else {
    team[zone][index] = { id: null, name: null, position: null, overall: null, injured: false };
  }
}

function copyInjuryFields(from, to) {
  if (!from || !to) return;
  to.injured = !!from.injured;
  if (from.injury_from != null) to.injury_from = from.injury_from;
  else delete to.injury_from;
  if (from.injury_until != null) to.injury_until = from.injury_until;
  else delete to.injury_until;
  if (from.injury_months != null) to.injury_months = from.injury_months;
  else delete to.injury_months;
}

function reconcileWithFreshRosters(rosters) {
  const { byId, baseline: freshBaseline } = buildFreshRosterIndexes(rosters);
  let ovr = 0;
  let removed = 0;

  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < (team[zone] || []).length; i++) {
        const p = team[zone][i];
        if (!p?.id || !p.name) continue;

        const home = baselineHome[p.id];
        const freshHome = freshBaseline[p.id];
        if (freshHome === FA_TEAM && home === team.name) {
          clearTeamSlot(team, zone, i);
          removed += 1;
          continue;
        }

        const fresh = byId.get(p.id);
        if (!fresh) continue;
        const prof = playerProfiles[playerProfileKey(p)];
        if (!prof?.overall && fresh.overall != null && Number(p.overall) !== Number(fresh.overall)) {
          p.overall = fresh.overall;
          ovr += 1;
        }
        if (!prof?.position && fresh.position && p.position !== fresh.position) p.position = fresh.position;
        copyInjuryFields(fresh, p);
      }
    }
  }

  syncFreeAgentsFromRosters(rosters);
  for (const [pid, home] of Object.entries(freshBaseline)) {
    if (baselineHome[pid] === undefined || baselineHome[pid] === home) {
      baselineHome[pid] = home;
    }
  }
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  if (rosters?.rosters_revision != null) {
    rostersRevision = rosters.rosters_revision;
  }
  repairBaselineHomeFromRosters(rosters);
  renderAll();
  return { ovr, removed, fa: freeAgents.length };
}

function applySavedState(saved, rosters) {
  const freshBaseline = rosters.baseline_home || {};
  baselineHome = saved.baseline_home && Object.keys(saved.baseline_home).length
    ? { ...saved.baseline_home }
    : { ...freshBaseline };
  teams = migrateSavedState(saved, rosters);
  if (Array.isArray(saved.free_agents) && saved.free_agents.length) {
    freeAgents = saved.free_agents.map((p) => ({ ...p, status: p.status || "bench", fired: !!p.fired }));
    initFaBaseline(freeAgents);
    if (rosters?.free_agents?.length) {
      mergeFreeAgentsWithDb(rosters.free_agents);
    }
  } else if (rosters && Array.isArray(rosters.free_agents) && rosters.free_agents.length) {
    syncFreeAgentsFromRosters(rosters);
  }
  removedFromSquad = saved.removed_from_squad || {};
  rekeyClubPlayersWithWrongIds();
  const baselineRepaired = repairBaselineHomeFromRosters(rosters);
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  stateRevision = Number(saved.revision) || 0;
  undoStack = [];
  updateUndoBtn();
  dirty = false;
  dirtyTeams = new Set();
  populateNationSelect();
  renderAll();
  updateSyncBadge(saved);
  if (baselineRepaired) {
    saveState({ silent: true, skipIncompleteConfirm: true }).then(() => {
      setStatus("baseline трансферов восстановлен из rosters · сейв обновлён");
    });
  }
}

async function pullRemoteState() {
  const url = isNationsMode()
    ? "/api/state?mode=nations"
    : `/api/state?window=${encodeURIComponent(currentWindow)}`;
  const res = await fetch(url);
  if (!res.ok) return false;
  const saved = await res.json();
  if (!lastRosters) return false;
  applySavedState(saved, lastRosters);
  hideSyncBanner();
  const who = saved.updated_by || "?";
  setStatus(
    liveSyncEnabled
      ? `⟳ обновлено от ${who} (rev ${stateRevision})`
      : `синхронизировано (rev ${stateRevision}, ${who})`
  );
  return true;
}

async function pollRemoteRevision() {
  try {
    const url = isNationsMode()
      ? "/api/state/meta?mode=nations"
      : `/api/state/meta?window=${encodeURIComponent(currentWindow)}`;
    const res = await fetch(url);
    if (!res.ok) return;
    const meta = await res.json();
    updateSyncBadge(meta);
    const remoteRev = Number(meta.revision) || 0;
    if (remoteRev <= stateRevision) return;
    if (dragPayload) return;
    if (liveSyncEnabled && (autosaveInFlight || autosaveTimer)) return;

    // Нет локальных правок — просто подтягиваем напарника.
    if (!dirty || !dirtyTeams.size) {
      await pullRemoteState();
      return;
    }

    // Правим разные клубы: подтянуть его изменения, сохранить свои.
    const who = meta.updated_by || "напарник";
    if (await pullRemoteStatePartial()) {
      setStatus(`⟳ ${who}: другие клубы обновлены · ваши: ${[...dirtyTeams].join(", ")}`);
      return;
    }
    showSyncBanner(meta);
  } catch (_) {
    /* offline */
  }
}

function startSyncPoll() {
  if (syncPollTimer) clearInterval(syncPollTimer);
  const ms = liveSyncEnabled ? LIVE_SYNC_POLL_MS : SYNC_POLL_MS;
  syncPollTimer = setInterval(pollRemoteRevision, ms);
}

function stopSyncPoll() {
  if (syncPollTimer) {
    clearInterval(syncPollTimer);
    syncPollTimer = null;
  }
}

function loadFreshFromRosters(rosters, msg) {
  baselineHome = { ...(rosters.baseline_home || {}) };
  teams = JSON.parse(JSON.stringify(rosters.teams || []));
  syncFreeAgentsFromRosters(rosters);
  removedFromSquad = {};
  undoStack = [];
  updateUndoBtn();
  rekeyClubPlayersWithWrongIds();
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  dirty = false;
  dirtyTeams = new Set();
  stateRevision = 0;
  rostersRevision = rosters.rosters_revision ?? null;
  populateNationSelect();
  updateTitle();
  renderAll();
  if (msg) setStatus(msg);
}

function resetToDbRosters() {
  const ok = window.confirm(
    isNationsMode()
      ? "Сбросить все изменения и загрузить сборные из national_rosters.json?"
      : "Сбросить все изменения и загрузить составы из rosters.json?\n" +
          "Текущие несохранённые трансферы будут потеряны."
  );
  if (!ok) return;
  fetch(`/api/rosters?mode=${encodeURIComponent(currentMode)}`)
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
  markDirty();
  renderAll();
  setStatus("отменено последнее действие");
  updateUndoBtn();
}

function initFaBaseline(list) {
  for (const p of list || []) {
    if (p && p.id) baselineHome[p.id] = FA_TEAM;
  }
}

function collectSquadIdentityKeys() {
  const keys = new Set();
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        const k = playerIdentityKey(p);
        if (k) keys.add(k);
        const npk = playerNamePosKey(p);
        if (npk) keys.add(`np:${npk}`);
        if (p?.id) keys.add(`id:${p.id}`);
      }
    }
  }
  return keys;
}

/** Убрать из пула FA тех, кто уже в составе клуба (person_id, имя+позиция, id). */
function purgeFreeAgentsInSquads() {
  const inSquads = collectSquadIdentityKeys();
  freeAgents = (freeAgents || []).filter((p) => {
    const k = playerIdentityKey(p);
    if (k && inSquads.has(k)) {
      delete baselineHome[p.id];
      return false;
    }
    const npk = playerNamePosKey(p);
    if (npk && inSquads.has(`np:${npk}`)) {
      delete baselineHome[p.id];
      return false;
    }
    if (p?.id && inSquads.has(`id:${p.id}`)) {
      delete baselineHome[p.id];
      return false;
    }
    return true;
  });
}

/** Перенести «домашний клуб» при смене id; не затирать исходный клуб трансфера. */
function migrateBaselineHome(oldId, newId, destTeamName, fallbackHome) {
  if (!newId) return newId;
  if (!oldId || oldId === newId) return newId;
  let home = baselineHome[oldId];
  delete baselineHome[oldId];
  if (home === undefined) home = fallbackHome;
  const oldPrefix = String(oldId).split("|")[0];
  if (oldPrefix === "Free Agent" && home === destTeamName) home = FA_TEAM;
  if (oldPrefix !== "Free Agent" && oldPrefix !== destTeamName && home === destTeamName) {
    home = oldPrefix;
  }
  if (home !== undefined) baselineHome[newId] = home;
  return newId;
}

/** Индекс «исходный клуб сезона» из rosters.json (до трансферного окна). */
function buildOriginalHomeIndex(rosters) {
  const byPersonId = new Map();
  const byNamePos = new Map();
  const baseline = rosters?.baseline_home || {};
  for (const [id, home] of Object.entries(baseline)) {
    const parts = String(id).split("|");
    if (parts.length >= 3) {
      const key = `${parts[1].trim().toLowerCase()}|${parts[2].trim().toUpperCase()}`;
      byNamePos.set(key, home);
    }
  }
  for (const team of rosters?.teams || []) {
    const tname = team.name;
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        if (!p?.name) continue;
        const pid = Number(p.person_id);
        const home = (p.id && baseline[p.id]) || tname;
        if (Number.isFinite(pid) && pid > 0) byPersonId.set(pid, home);
        const key = `${String(p.name).trim().toLowerCase()}|${String(p.position || "").trim().toUpperCase()}`;
        if (!byNamePos.has(key)) byNamePos.set(key, home);
      }
    }
  }
  return { byPersonId, byNamePos };
}

function lookupOriginalHome(p, rosters) {
  if (!p?.name || !rosters) return null;
  const { byPersonId, byNamePos } = buildOriginalHomeIndex(rosters);
  const pid = Number(p.person_id);
  if (Number.isFinite(pid) && pid > 0 && byPersonId.has(pid)) {
    return byPersonId.get(pid);
  }
  const key = `${String(p.name).trim().toLowerCase()}|${String(p.position || "").trim().toUpperCase()}`;
  return byNamePos.get(key) || null;
}

/** Починить baseline: «дом» = клуб из rosters, если игрок сейчас в другом месте. */
function repairBaselineHomeFromRosters(rosters) {
  if (isNationsMode() || !rosters) return false;
  let changed = false;
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        if (!p?.id || !p.name) continue;
        const orig = lookupOriginalHome(p, rosters);
        if (!orig || orig === team.name) continue;
        const cur = baselineHome[p.id];
        if (cur === undefined || cur === team.name) {
          baselineHome[p.id] = orig;
          changed = true;
        }
      }
    }
  }
  return changed;
}

/** Только FA-id в клубе → id с префиксом клуба. Трансферы между клубами id не меняем. */
function rekeyClubPlayersWithWrongIds() {
  if (isNationsMode()) return;
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (const p of team[zone] || []) {
        if (!p?.id) continue;
        const prefix = String(p.id).split("|")[0];
        if (prefix !== "Free Agent") continue;
        const oldId = p.id;
        const newId = playerIdFor(team.name, p.name, p.position);
        if (oldId === newId) continue;
        p.id = newId;
        migrateBaselineHome(oldId, newId, team.name, FA_TEAM);
      }
    }
  }
}

/** Добавить/обновить FA из free_agents.db (не терять «новых» после reload/save). */
function mergeFreeAgentsWithDb(dbList) {
  const inSquads = collectSquadIdentityKeys();
  const byId = new Map((freeAgents || []).map((p) => [p.id, p]));
  for (const raw of dbList || []) {
    if (!raw?.id) continue;
    const k = playerIdentityKey(raw);
    const npk = playerNamePosKey(raw);
    if ((k && inSquads.has(k)) || (npk && inSquads.has(`np:${npk}`)) || inSquads.has(`id:${raw.id}`)) continue;
    const prev = byId.get(raw.id);
    const merged = {
      ...(prev || {}),
      ...raw,
      status: raw.status || prev?.status || "bench",
      fired: !!raw.fired,
    };
    byId.set(raw.id, merged);
    baselineHome[raw.id] = FA_TEAM;
  }
  freeAgents = Array.from(byId.values()).sort(
    (a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0)
  );
  purgeFreeAgentsInSquads();
}

function syncFreeAgentsFromRosters(rosters) {
  mergeFreeAgentsWithDb(rosters.free_agents || []);
}

function findFaPlayer(id) {
  return freeAgents.find((p) => p.id === id) || null;
}

function findNationalPlayer(id) {
  for (const block of nationalPools?.nations || []) {
    const p = (block.players || []).find((x) => x.id === id);
    if (p) return p;
  }
  return null;
}

function squadIdsForTeam(teamName) {
  const team = teams.find((t) => t.name === teamName);
  const ids = new Set();
  if (!team) return ids;
  for (const zone of ["start", "bench", "reserve"]) {
    for (const p of team[zone] || []) {
      if (p?.id) ids.add(p.id);
    }
  }
  return ids;
}

function playerIdentityKey(p) {
  if (!p) return "";
  const pid = Number(p.person_id);
  if (Number.isFinite(pid) && pid > 0) return `pid:${pid}`;
  const nm = String(p.name || "").trim().toLowerCase();
  return nm ? `nm:${nm}` : "";
}

function playerNamePosKey(p) {
  if (!p?.name) return "";
  return `${String(p.name).trim().toLowerCase()}|${String(p.position || "").trim().toUpperCase()}`;
}

function squadIdentityKeysForTeam(teamName) {
  const team = teams.find((t) => t.name === teamName);
  const keys = new Set();
  if (!team) return keys;
  for (const zone of ["start", "bench", "reserve"]) {
    for (const p of team[zone] || []) {
      const k = playerIdentityKey(p);
      if (k) keys.add(k);
      if (p?.id) keys.add(`id:${p.id}`);
    }
  }
  return keys;
}

function isPlayerInNationalSquad(p, squadKeys) {
  if (!p || !squadKeys?.size) return false;
  const k = playerIdentityKey(p);
  if (k && squadKeys.has(k)) return true;
  if (p.id && squadKeys.has(`id:${p.id}`)) return true;
  return false;
}

function syncNationalPoolPlayer(oldId, patch) {
  if (!nationalPools?.nations?.length) return;
  const loc = oldId ? findPlayerGlobally(oldId) : null;
  const pid = Number(patch?.person_id || loc?.player?.person_id || 0);
  for (const block of nationalPools.nations) {
    for (let i = 0; i < (block.players || []).length; i++) {
      const p = block.players[i];
      const match =
        (oldId && p.id === oldId) ||
        (Number.isFinite(pid) && pid > 0 && Number(p.person_id) === pid);
      if (!match) continue;
      const team = p.team || (oldId || "").split("|")[0] || "";
      const isFa = !!(p.is_fa || team === FA_TEAM || patch?.is_fa);
      const nm = patch.name != null ? String(patch.name).trim() : p.name;
      const pos = patch.position != null ? String(patch.position).trim().toUpperCase() : p.position;
      const next = {
        ...p,
        ...patch,
        name: nm,
        position: pos,
        id:
          patch.id ||
          (isFa ? playerIdFor(FA_TEAM, nm, pos) : playerIdFor(team, nm, pos)),
      };
      block.players[i] = patchPlayerFromProfile(next);
    }
  }
  if (isNationsMode()) renderNationalPanel();
}

function playerProfileKey(p) {
  const pid = Number(p?.person_id);
  if (Number.isFinite(pid) && pid > 0) return String(pid);
  return "";
}

function propagatePlayerProfileEdit(playerId, patch) {
  const loc = findPlayerGlobally(playerId);
  let pid = playerProfileKey(loc?.player);
  if (!pid && patch.person_id) pid = String(Number(patch.person_id));
  if (!pid) {
    const poolPid = lookupPersonIdFromPools(playerId, loc?.player);
    if (poolPid) pid = String(poolPid);
  }
  if (!pid) return;
  const cur = { ...(playerProfiles[pid] || {}) };
  if (patch.name != null) cur.name = String(patch.name).trim();
  if (patch.position != null) cur.position = String(patch.position).trim().toUpperCase();
  if (patch.overall != null) cur.overall = Number(patch.overall);
  if (patch.nation != null) cur.nation = String(patch.nation).trim();
  if (patch.nickname != null || patch.nickname_set) {
    cur.nickname = String(patch.nickname || "").trim();
  }
  playerProfiles[pid] = cur;
  applyPlayerProfilesEverywhere();
  syncNationalPoolPlayer(playerId, {
    ...patch,
    person_id: Number(pid),
  });
  persistPlayerProfiles();
}

function lookupPersonIdFromPools(playerId, player) {
  if (player?.person_id) return Number(player.person_id);
  const parts = String(playerId || "").split("|");
  const team = parts[0] || player?.team || "";
  const name = player?.name || parts[1] || "";
  for (const block of nationalPools?.nations || []) {
    for (const p of block.players || []) {
      if (playerId && p.id === playerId) return p.person_id || null;
      if (name && p.name === name && (!team || p.team === team || team === FA_TEAM)) {
        return p.person_id || null;
      }
    }
  }
  return null;
}

async function persistPlayerProfiles() {
  try {
    await fetch("/api/player-profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profiles: playerProfiles }),
    });
  } catch (_) {
    /* offline */
  }
}

async function loadPlayerProfiles() {
  try {
    const res = await fetch("/api/player-profiles");
    const j = await res.json();
    if (res.ok && j.profiles && typeof j.profiles === "object") {
      playerProfiles = j.profiles;
    }
  } catch (_) {
    playerProfiles = {};
  }
}

function patchPlayerFromProfile(p) {
  if (!p?.person_id) return p;
  const prof = playerProfiles[playerProfileKey(p)];
  if (!prof) return p;
  const out = { ...p };
  if (prof.name) out.name = prof.name;
  if (prof.position) out.position = prof.position;
  if (prof.overall != null) out.overall = Number(prof.overall);
  if (prof.nation) out.nation = prof.nation;
  if ("nickname" in prof) out.nickname = prof.nickname || "";
  const home = baselineHome[p.id] || (String(p.id || "").split("|")[0] || "");
  if (home && out.name && out.position) {
    out.id = playerIdFor(home === FA_TEAM ? FA_TEAM : home, out.name, out.position);
  }
  return out;
}

function applyPlayerProfilesEverywhere() {
  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < (team[zone] || []).length; i++) {
        const p = team[zone][i];
        if (!p?.id) continue;
        team[zone][i] = patchPlayerFromProfile(p);
      }
    }
    recomputeAvgStart(team);
  }
  freeAgents = freeAgents.map((p) => patchPlayerFromProfile(p));
  syncAllNationalPoolsFromProfiles();
}

function syncAllNationalPoolsFromProfiles() {
  if (!nationalPools?.nations?.length) return;
  for (const block of nationalPools.nations) {
    block.players = (block.players || []).map((p) => patchPlayerFromProfile(p));
  }
}

function nationNamesMatch(a, b) {
  return String(a || "").trim().toLowerCase() === String(b || "").trim().toLowerCase();
}

function returnPlayerToNationalPool(playerId, teamName) {
  const loc = findPlayerGlobally(playerId);
  if (!loc?.player) return;
  const p = loc.player;
  if (teamName && selectedNation && !nationNamesMatch(teamName, selectedNation)) return;
  if (!window.confirm(`Вернуть ${p.name} (${p.position}, ${p.overall}) в пул?`)) return;
  pushUndo();
  removeAllInstancesOfId(playerId);
  markDirty();
  renderAll();
  setStatus(`в пуле: ${p.name}`);
}

function setupNationalPoolDrop(listEl) {
  if (!listEl || listEl.dataset.poolDropBound === "1") return;
  listEl.dataset.poolDropBound = "1";
  listEl.classList.add("national-pool-drop");
  listEl.addEventListener("dragover", (e) => {
    if (!isNationsMode() || !dragPayload?.id || dragPayload.fromNational) return;
    if (!nationNamesMatch(dragPayload.team, selectedNation)) return;
    e.preventDefault();
    listEl.classList.add("drag-over");
  });
  listEl.addEventListener("dragleave", (e) => {
    if (!listEl.contains(e.relatedTarget)) listEl.classList.remove("drag-over");
  });
  listEl.addEventListener("drop", (e) => {
    e.preventDefault();
    listEl.classList.remove("drag-over");
    if (!isNationsMode() || !dragPayload?.id || dragPayload.fromNational) return;
    if (!nationNamesMatch(dragPayload.team, selectedNation)) return;
    pushUndo();
    removeAllInstancesOfId(dragPayload.id);
    dragPayload = null;
    stopDragScroll();
    markDirty();
    renderAll();
    setStatus("вернули в пул");
  });
}

function parseFilterOvr(minStr, maxStr) {
  const minRaw = String(minStr ?? "").trim();
  const maxRaw = String(maxStr ?? "").trim();
  const min = minRaw === "" ? null : parseInt(minRaw, 10);
  const max = maxRaw === "" ? null : parseInt(maxRaw, 10);
  if (min != null && Number.isNaN(min)) return { min: null, max: null };
  if (max != null && Number.isNaN(max)) return { min: null, max: null };
  return { min, max };
}

function playerMatchesNameSearch(p, q) {
  const ql = (q || "").trim().toLowerCase();
  if (!ql) return true;
  const name = String(p.name || "").toLowerCase();
  const nick = String(p.nickname || "").toLowerCase();
  if (name.includes(ql) || nick.includes(ql)) return true;
  const parts = name.split(/\s+/).filter(Boolean);
  const surname = parts.length ? parts[parts.length - 1] : name;
  return surname.includes(ql) || surname.startsWith(ql);
}

function playerMatchesOvr(p, min, max) {
  const o = Number(p.overall) || 0;
  if (min != null && max != null) {
    if (min === max) return o === min;
    const lo = Math.min(min, max);
    const hi = Math.max(min, max);
    return o >= lo && o <= hi;
  }
  if (min != null) return o >= min;
  if (max != null) return o <= max;
  return true;
}

function playerMatchesPoolFilters(p, filters, { faKind = false } = {}) {
  const { min, max } = parseFilterOvr(filters.ovrMin, filters.ovrMax);
  if (!playerMatchesOvr(p, min, max)) return false;
  if (filters.position && p.position !== filters.position) return false;
  if (faKind && filters.kind === "fired" && !p.fired) return false;
  if (faKind && filters.kind === "new" && p.fired) return false;
  return true;
}

function poolFiltersActive(filters, { faKind = false } = {}) {
  return !!(filters.ovrMin || filters.ovrMax || filters.position || (faKind && filters.kind));
}

function fillPoolPositionSelect(selectEl) {
  if (!selectEl) return;
  const cur = selectEl.value || "";
  selectEl.innerHTML = '<option value="">все</option>';
  positionsCatalog.forEach((code) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code;
    selectEl.appendChild(opt);
  });
  selectEl.value = cur;
}

function readFaPoolFiltersFromDom() {
  faPoolFilters = {
    ovrMin: document.getElementById("fa-ovr-min")?.value || "",
    ovrMax: document.getElementById("fa-ovr-max")?.value || "",
    position: document.getElementById("fa-pos-filter")?.value || "",
    kind: document.getElementById("fa-kind-filter")?.value || "",
  };
}

function readNationalPoolFiltersFromDom() {
  nationalPoolFilters = {
    ovrMin: document.getElementById("national-ovr-min")?.value || "",
    ovrMax: document.getElementById("national-ovr-max")?.value || "",
    position: document.getElementById("national-pos-filter")?.value || "",
  };
}

function resetFaPoolFilters() {
  faPoolFilters = { ...poolFiltersEmpty, kind: "" };
  faFilter = "";
  const search = document.getElementById("fa-search");
  if (search) search.value = "";
  const ids = ["fa-ovr-min", "fa-ovr-max"];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const pos = document.getElementById("fa-pos-filter");
  const kind = document.getElementById("fa-kind-filter");
  if (pos) pos.value = "";
  if (kind) kind.value = "";
  renderFaPanel();
}

function resetNationalPoolFilters() {
  nationalPoolFilters = { ...poolFiltersEmpty };
  nationalFilter = "";
  const search = document.getElementById("national-search");
  if (search) search.value = "";
  ["national-ovr-min", "national-ovr-max"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.value = "";
  });
  const pos = document.getElementById("national-pos-filter");
  if (pos) pos.value = "";
  renderNationalPanel();
}

function setupPoolFilters() {
  fillPoolPositionSelect(document.getElementById("fa-pos-filter"));
  fillPoolPositionSelect(document.getElementById("national-pos-filter"));

  const faInputs = ["fa-ovr-min", "fa-ovr-max", "fa-pos-filter", "fa-kind-filter"];
  faInputs.forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => {
      readFaPoolFiltersFromDom();
      renderFaPanel();
    });
    document.getElementById(id)?.addEventListener("change", () => {
      readFaPoolFiltersFromDom();
      renderFaPanel();
    });
  });
  document.getElementById("fa-filters-reset")?.addEventListener("click", resetFaPoolFilters);

  const natInputs = ["national-ovr-min", "national-ovr-max", "national-pos-filter"];
  natInputs.forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => {
      readNationalPoolFiltersFromDom();
      renderNationalPanel();
    });
    document.getElementById(id)?.addEventListener("change", () => {
      readNationalPoolFiltersFromDom();
      renderNationalPanel();
    });
  });
  document.getElementById("national-filters-reset")?.addEventListener("click", resetNationalPoolFilters);
}

function formatPoolCount(shown, total, filtersActive) {
  if (filtersActive && total != null && shown !== total) return `${shown}/${total}`;
  return String(shown);
}

function setNationalPools(data) {
  if (data?.nations) {
    data = {
      ...data,
      nations: data.nations.map((block) => ({
        ...block,
        players: (block.players || []).map((p) => patchPlayerFromProfile(p)),
      })),
    };
  }
  nationalPools = data;
  nationalExpanded.clear();
  const panel = document.getElementById("national-panel");
  const cnt = document.getElementById("national-count");
  const showPanel = isNationsMode() ? !!selectedNation : !!(nationalPools?.nations?.length);
  if (panel) panel.hidden = !showPanel;
  if (cnt) {
    const block = isNationsMode() && selectedNation
      ? (nationalPools?.nations || []).find((b) => nationNamesMatch(b.name, selectedNation))
      : null;
    const inSquad = isNationsMode() && selectedNation ? squadIdentityKeysForTeam(selectedNation) : null;
    const poolCount = block
      ? (block.players || []).filter((p) => p?.id && !isPlayerInNationalSquad(p, inSquad)).length
      : null;
    cnt.textContent = String(
      poolCount ?? block?.players?.length ?? data?.player_count ?? nationalPools?.player_count ?? 0
    );
  }
  renderNationalPanel();
}

async function loadCoachesCatalog() {
  if (coachesCatalog.length) return coachesCatalog;
  try {
    const res = await fetch("/api/coaches");
    const j = await res.json();
    if (res.ok && Array.isArray(j.coaches) && j.coaches.length) {
      coachesCatalog = j.coaches;
      return coachesCatalog;
    }
  } catch (_) {
    /* offline or stale server */
  }
  try {
    const res = await fetch("/web/coaches.json");
    const j = await res.json();
    const list = Array.isArray(j) ? j : j.coaches;
    if (Array.isArray(list) && list.length) coachesCatalog = list;
  } catch (_) {
    /* no fallback */
  }
  return coachesCatalog;
}

async function loadNationalPoolsFromApi() {
  const res = await fetch("/api/national-pools");
  const j = await res.json();
  if (!res.ok || j.error) throw new Error(j.error || "нет данных сборных");
  setNationalPools(j);
  setStatus(`Сборные: ${j.nations?.length || 0} наций, ${j.player_count || 0} игроков`);
}

async function importNationalFromFile(file) {
  const text = await file.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (_) {
    throw new Error("нужен JSON (national_pools.json)");
  }
  const res = await fetch("/api/import-national-pools", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  setNationalPools(j);
  setStatus(`Сборные из файла: ${j.nations?.length || 0} наций, ${j.player_count || 0} игроков`);
}

function renderNationalPlayer(p) {
  const row = document.createElement("div");
  row.className = "national-row";
  const el = document.createElement("div");
  el.className = "player national-player";
  el.draggable = true;
  el.dataset.id = p.id;
  const clubLabel = p.is_fa || p.team === FA_TEAM ? "FA" : (p.team || "?");
  el.innerHTML =
    `<div class="player-main">` +
    `<span class="ovr">${p.overall}</span>` +
    `<span class="pos">${p.position}</span>` +
    `<span class="nm" title="${p.name}">${p.name}</span>` +
    `<span class="club" title="${clubLabel}">${clubLabel}</span>` +
    `</div>` +
    `<div class="player-actions">` +
    `<button type="button" class="edit-btn" title="Редактировать">✎</button>` +
    `</div>`;
  const team = p.is_fa || p.team === FA_TEAM ? FA_TEAM : (p.team || FA_TEAM);
  bindPlayerActionButton(el.querySelector(".edit-btn"), () => openPlayerEditModal(p, team));
  el.addEventListener("dragstart", (e) => {
    const isFa = !!(p.is_fa || p.team === FA_TEAM);
    dragPayload = {
      id: p.id,
      team: isFa ? FA_TEAM : p.team,
      fromFa: isFa,
      fromNational: true,
      name: p.name,
      position: p.position,
      overall: p.overall,
      person_id: p.person_id,
      club: p.team,
    };
    e.dataTransfer.effectAllowed = "copy";
    e.dataTransfer.setData("text/plain", p.id);
    startDragScroll();
  });
  el.addEventListener("dragend", stopDragScroll);
  row.appendChild(el);
  return row;
}

function renderNationalPanel() {
  const list = document.getElementById("national-list");
  const title = document.getElementById("national-panel-title");
  const panel = document.getElementById("national-panel");
  const hint = document.getElementById("national-hint");
  if (!list) return;
  list.innerHTML = "";
  if (hint && isNationsMode()) {
    hint.textContent = "В заявку — перетащи. Из состава — × или перетащи сюда, вернётся в пул.";
  }
  setupNationalPoolDrop(list);
  const blocks = nationalPools?.nations || [];
  if (!blocks.length) return;

  const q = nationalFilter.trim().toLowerCase();
  let shown = 0;
  let total = 0;
  const nationFilterName = isNationsMode() ? selectedNation : "";
  const inSquad = isNationsMode() && selectedNation ? squadIdentityKeysForTeam(selectedNation) : null;
  const natFiltersOn =
    poolFiltersActive(nationalPoolFilters) || !!q;

  blocks.forEach((block) => {
    const nation = block.name || "?";
    if (nationFilterName && !nationNamesMatch(nation, nationFilterName)) return;
    let players = (block.players || []).slice();
    if (inSquad) {
      players = players.filter((p) => p?.id && !isPlayerInNationalSquad(p, inSquad));
    }
    total += players.length;
    if (q) {
      players = players.filter(
        (p) =>
          String(p.name || "").toLowerCase().includes(q) ||
          String(p.team || "").toLowerCase().includes(q) ||
          String(p.position || "").toLowerCase().includes(q)
      );
    }
    players = players.filter((p) => playerMatchesPoolFilters(p, nationalPoolFilters));
    if (!players.length) return;

    shown += players.length;
    if (isNationsMode()) {
      if (title) title.textContent = `Пул · ${nation}`;
      players.forEach((p) => list.appendChild(renderNationalPlayer(p)));
      return;
    }

    const group = document.createElement("div");
    group.className = "national-group" + (nationalExpanded.has(nation) || q ? " expanded" : "");
    const hdr = document.createElement("div");
    hdr.className = "national-group-hdr";
    hdr.innerHTML = `<span>${nation}</span><span class="cnt">${players.length}</span>`;
    hdr.addEventListener("click", () => {
      if (nationalExpanded.has(nation)) nationalExpanded.delete(nation);
      else nationalExpanded.add(nation);
      group.classList.toggle("expanded");
    });
    const body = document.createElement("div");
    body.className = "national-group-body";
    players.forEach((p) => body.appendChild(renderNationalPlayer(p)));
    group.appendChild(hdr);
    group.appendChild(body);
    list.appendChild(group);
  });

  if (!shown) {
    const empty = document.createElement("div");
    empty.className = "fa-hint";
    empty.textContent = inSquad && nationFilterName
      ? natFiltersOn
        ? "Никого не найдено — ослабь фильтры"
        : "Все в заявке — верни × или перетащи сюда"
      : nationFilterName
        ? natFiltersOn
          ? "Никого не найдено — ослабь фильтры"
          : "Нет игроков в пуле"
        : "Никого не найдено";
    list.appendChild(empty);
  }
  const cnt = document.getElementById("national-count");
  if (cnt && isNationsMode() && nationFilterName) {
    cnt.textContent = formatPoolCount(shown, total, natFiltersOn);
  }
  if (panel && isNationsMode()) {
    panel.hidden = !nationFilterName || !blocks.length;
  }
}

function renderFaPanel() {
  const list = document.getElementById("fa-list");
  const cnt = document.getElementById("fa-count");
  if (!list) return;
  list.innerHTML = "";
  const sorted = freeAgents.slice().sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  const q = faFilter.trim().toLowerCase();
  let filtered = sorted.filter((p) => playerMatchesPoolFilters(p, faPoolFilters, { faKind: true }));
  if (q) filtered = filtered.filter((p) => playerMatchesNameSearch(p, q));
  const faFiltersOn = poolFiltersActive(faPoolFilters, { faKind: true }) || !!q;
  if (cnt) cnt.textContent = formatPoolCount(filtered.length, sorted.length, faFiltersOn);
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "fa-hint";
    const dbNew = sorted.filter((p) => !p.fired).length;
    if (sorted.length && faPoolFilters.kind === "new" && dbNew > 0) {
      empty.textContent = `Новых ${dbNew}, но фильтр скрывает — поставьте «Тип: все» или ↻ FA`;
    } else {
      empty.textContent = sorted.length
        ? "Никого не найдено — ослабь фильтры"
        : "Пул пуст — перетащи сюда или добавь нового";
    }
    list.appendChild(empty);
  }
  filtered.forEach((p) => {
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
      markDirty();
      setStatus("в пул свободных агентов");
    });
  }
}

function movePlayerToFa(src) {
  if (!src || !src.id) return;
  if (findFaPlayer(src.id)) return;
  const loc = findPlayerGlobally(src.id);
  if (!loc) return;
  const oldId = src.id;
  let p = { ...loc.player };
  const fromTeam = baselineHome[src.id] || loc.teamName;
  const fromClub = fromTeam && fromTeam !== FA_TEAM;
  if (!baselineHome[src.id]) baselineHome[src.id] = loc.teamName;
  removeAllInstancesOfId(src.id);
  const fired = fromClub ? true : !!p.fired;
  freeAgents.push({ ...p, status: "bench", fired });
  freeAgents.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  dedupeGlobally(teams);

  if (fromClub) {
    fetch("/api/fa/release", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: p.name,
        position: p.position,
        from_team: fromTeam,
        overall: p.overall,
      }),
    })
      .then((res) => res.json())
      .then((j) => {
        if (!j.ok || !j.player) return;
        const np = { ...j.player, status: "bench", fired: true };
        const idx = freeAgents.findIndex(
          (x) =>
            x.id === np.id ||
            (String(x.name || "").toLowerCase() === String(np.name || "").toLowerCase() &&
              String(x.position || "").toUpperCase() === String(np.position || "").toUpperCase())
        );
        if (idx < 0) return;
        if (baselineHome[oldId]) {
          baselineHome[np.id] = baselineHome[oldId];
          if (np.id !== oldId) delete baselineHome[oldId];
        }
        freeAgents[idx] = np;
        renderFaPanel();
      })
      .catch(() => {});
  }
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
  if (id === "modal-overlay") {
    resetNationPicker();
    ensureNationsLoaded();
  }
  if (id === "modal-edit-overlay") {
    ensureNationsLoaded();
  }
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) {
    el.classList.add("hidden");
    el.setAttribute("aria-hidden", "true");
  }
}

function rebuildNationsList() {
  const seen = new Set();
  nationsList = [];
  if (Array.isArray(window.__twNationsFlat) && window.__twNationsFlat.length) {
    for (const name of window.__twNationsFlat) {
      const s = String(name || "").trim();
      if (!s || seen.has(s)) continue;
      seen.add(s);
      nationsList.push(s);
    }
  } else {
    for (const list of Object.values(nationsByConfederation || {})) {
      if (!Array.isArray(list)) continue;
      for (const name of list) {
        const s = String(name || "").trim();
        if (!s || seen.has(s)) continue;
        seen.add(s);
        nationsList.push(s);
      }
    }
  }
  nationsList.sort((a, b) => a.localeCompare(b, "ru"));
}

function setNationsCatalog(byConf, flat) {
  if (byConf && typeof byConf === "object") nationsByConfederation = byConf;
  if (Array.isArray(flat) && flat.length) window.__twNationsFlat = flat;
  rebuildNationsList();
}

async function ensureNationsLoaded() {
  if (nationsList.length) return;
  try {
    const res = await fetch("/api/nations");
    const j = await res.json();
    if (j.ok) setNationsCatalog(j.nations_by_confederation, j.nations);
  } catch (_) {
    /* offline */
  }
  setupNationPicker();
}

function normNat(s) {
  let t = String(s || "")
    .trim()
    .toLowerCase()
    .replace(/ё/g, "е");
  t = t.replace(/[''`´ʻʼ’]/g, "'");
  return t.split(/\s+/).filter(Boolean).join(" ");
}

const NATION_ALIASES = {
  "босния и герцеговина": "Босния",
  "босния и герцеговна": "Босния",
  "д р конго": "ДР Конго",
  "д.р. конго": "ДР Конго",
  "др конго": "ДР Конго",
  "конго": "Конго",
  "коста рика": "Коста-Рика",
  "коста-рика": "Коста-Рика",
  "центральноафриканская республика": "ЦАР",
  "цар": "ЦАР",
  "тринидад и тобаго": "Тринидад и Тобаго",
  "юж корея": "Южная Корея",
  "юж. корея": "Южная Корея",
  "кот-д'ивуар": "Кот-д'Ивуар",
  "кот д'ивуар": "Кot-d'Иvuar",
  "котдивуар": "Кот-д'Ивуар",
  "франци": "Франция",
  "франйция": "Франция",
  "оаэ": "ОАЭ",
  "эмираты": "ОАЭ",
  "косово": "Косово",
};

function resolveCatalogNation(text) {
  const key = normNat(text);
  if (!key) return null;
  const alias = NATION_ALIASES[key];
  const lookup = alias ? normNat(alias) : key;
  for (const n of nationsList) {
    if (normNat(n) === lookup) return n;
  }
  return null;
}

function nationSuggestionMatches(raw) {
  const q = normNat(raw);
  if (!q) return nationsList.slice(0, 24);
  const starts = [];
  const contains = [];
  for (const n of nationsList) {
    const nk = normNat(n);
    if (nk.startsWith(q)) starts.push(n);
    else if (nk.includes(q)) contains.push(n);
  }
  return starts.concat(contains);
}

/** Любая страна: точное совпадение с каталогом ЧМ или произвольный текст. */
function commitNationPickerValue(input, hidden) {
  const raw = input.value.trim();
  const resolved = resolveCatalogNation(raw);
  input.classList.remove("invalid");
  hidden.value = resolved || raw;
  return true;
}

function appendNationSuggestionItems(list, input, hidden, raw, matches, onPick) {
  list.innerHTML = "";
  const q = normNat(raw);
  if (raw && !matches.some((n) => normNat(n) === q)) {
    const custom = document.createElement("li");
    custom.className = "nation-custom";
    custom.textContent = `Использовать «${raw}»`;
    custom.addEventListener("mousedown", (e) => {
      e.preventDefault();
      input.value = raw;
      commitNationPickerValue(input, hidden);
      list.classList.add("hidden");
      onPick?.();
    });
    list.appendChild(custom);
  }
  matches.slice(0, 16).forEach((n) => {
    const li = document.createElement("li");
    li.textContent = n;
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();
      input.value = n;
      commitNationPickerValue(input, hidden);
      list.classList.add("hidden");
      onPick?.();
    });
    list.appendChild(li);
  });
  if (list.childElementCount) list.classList.remove("hidden");
  else list.classList.add("hidden");
}

function resetNationPicker() {
  const input = document.getElementById("form-nation-input");
  const hidden = document.getElementById("form-nation-value");
  const list = document.getElementById("form-nation-suggestions");
  if (input) {
    input.value = "";
    input.classList.remove("invalid");
  }
  if (hidden) hidden.value = "";
  if (list) list.classList.add("hidden");
}

function setupNationPicker() {
  const input = document.getElementById("form-nation-input");
  const hidden = document.getElementById("form-nation-value");
  const list = document.getElementById("form-nation-suggestions");
  if (!input || !hidden || !list) return;

  const validateNation = () => commitNationPickerValue(input, hidden);

  const showSuggestions = () => {
    const raw = input.value.trim();
    const q = normNat(raw);
    const matches = nationSuggestionMatches(raw);
    if (matches.length === 1 && normNat(matches[0]) === q) {
      list.classList.add("hidden");
      validateNation();
      return;
    }
    appendNationSuggestionItems(list, input, hidden, raw, matches, validateNation);
  };

  if (!input.dataset.nationBound) {
    input.dataset.nationBound = "1";
    input.addEventListener("input", () => {
      validateNation();
      showSuggestions();
    });
    input.addEventListener("focus", showSuggestions);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") list.classList.add("hidden");
    });
    input.addEventListener("blur", () => {
      setTimeout(() => list.classList.add("hidden"), 150);
      validateNation();
    });
  }
  window.__twValidateNation = validateNation;
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
  setupNationPicker();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (window.__twValidateNation) window.__twValidateNation();
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
          fired: false,
        };
      }
      mergeFreeAgentsWithDb([player]);
      if (isNationsMode()) {
        try {
          await loadNationalPoolsFromApi();
        } catch (_) {
          /* offline */
        }
      }
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
    markDirty();
    closeModal("modal-overlay");
    form.reset();
    renderAll();
    setStatus(toFaOnly ? `добавлен FA: ${name}` : `новый игрок в ${team}: ${name}`);
  });
}

function bindPlayerActionButton(btn, handler) {
  if (!btn || typeof handler !== "function") return;
  btn.addEventListener("mousedown", (e) => {
    e.stopPropagation();
  });
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    handler(e);
  });
}

function resetEditNationPicker() {
  const input = document.getElementById("edit-nation-input");
  const hidden = document.getElementById("edit-nation-value");
  const list = document.getElementById("edit-nation-suggestions");
  if (input) {
    input.value = "";
    input.classList.remove("invalid");
  }
  if (hidden) hidden.value = "";
  if (list) list.classList.add("hidden");
}

function setupEditNationPicker() {
  const input = document.getElementById("edit-nation-input");
  const hidden = document.getElementById("edit-nation-value");
  const list = document.getElementById("edit-nation-suggestions");
  if (!input || !hidden || !list || input.dataset.bound === "1") return;
  input.dataset.bound = "1";

  const validateNation = () => commitNationPickerValue(input, hidden);

  const showSuggestions = () => {
    const raw = input.value.trim();
    const q = normNat(raw);
    const matches = nationSuggestionMatches(raw);
    if (matches.length === 1 && normNat(matches[0]) === q) {
      list.classList.add("hidden");
      validateNation();
      return;
    }
    appendNationSuggestionItems(list, input, hidden, raw, matches, validateNation);
  };

  input.addEventListener("input", () => {
    showSuggestions();
    validateNation();
  });
  input.addEventListener("focus", showSuggestions);
  input.addEventListener("blur", () => {
    setTimeout(() => list.classList.add("hidden"), 150);
    validateNation();
  });
  window.__twValidateEditNation = validateNation;
}

async function openPlayerEditModal(player, teamName) {
  if (!player?.name) return;
  try {
    await ensureNationsLoaded();
  } catch (_) {
    /* offline */
  }
  setupEditNationPicker();
  const team = teamName === FA_TEAM || player.is_fa ? FA_TEAM : (teamName || player.team || "");
  const pid = player.person_id || lookupPersonIdFromPools(player.id, player);
  const prof = pid ? playerProfiles[String(pid)] || {} : {};
  const setVal = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val == null ? "" : String(val);
  };
  setVal("edit-player-id", player.id || "");
  setVal("edit-team", team);
  setVal("edit-old-name", player.name);
  setVal("edit-old-position", player.position);
  setVal("edit-person-id", pid || "");
  setVal("edit-name", prof.name || player.name);
  setVal("edit-nickname", player.nickname || prof.nickname || "");
  setVal("edit-overall", prof.overall != null ? prof.overall : player.overall ?? 72);
  const posSel = document.getElementById("edit-position");
  if (posSel) {
    if (!posSel.options.length) {
      positionsCatalog.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        posSel.appendChild(opt);
      });
    }
    posSel.value = prof.position || player.position;
  }
  const ctx = document.getElementById("edit-context");
  if (ctx) ctx.textContent = team === FA_TEAM ? "Свободный агент" : `Клуб: ${team}`;
  resetEditNationPicker();
  const nat = prof.nation || player.nation || "";
  const natInput = document.getElementById("edit-nation-input");
  const natHidden = document.getElementById("edit-nation-value");
  if (natInput) natInput.value = nat;
  if (natHidden) natHidden.value = resolveCatalogNation(nat) || nat;
  openModal("modal-edit-overlay");
  document.getElementById("edit-name")?.focus();
}

function applyPlayerUpdateLocally(oldId, teamName, updated) {
  const p = updated || {};
  const newId = p.id || playerIdFor(teamName, p.name, p.position);
  const patch = {
    id: newId,
    name: p.name,
    position: p.position,
    overall: Number(p.overall),
    nation: p.nation || "",
    nickname: p.nickname || "",
    person_id: p.person_id,
  };

  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < (team[zone] || []).length; i++) {
        const slot = team[zone][i];
        if (slot?.id === oldId) {
          Object.assign(slot, patch);
          if (oldId !== newId) slot.id = newId;
        }
      }
    }
    recomputeAvgStart(team);
  }
  for (let i = 0; i < freeAgents.length; i++) {
    if (freeAgents[i].id === oldId) {
      freeAgents[i] = { ...freeAgents[i], ...patch, id: newId };
    }
  }
  if (oldId !== newId) {
    if (baselineHome[oldId] !== undefined) {
      baselineHome[newId] = baselineHome[oldId];
      delete baselineHome[oldId];
    }
    if (removedFromSquad[oldId]) {
      removedFromSquad[newId] = { ...removedFromSquad[oldId], ...patch, id: newId };
      delete removedFromSquad[oldId];
    }
  }
  syncNationalPoolPlayer(oldId, patch);
  if (p.person_id) {
    playerProfiles[String(p.person_id)] = {
      ...(playerProfiles[String(p.person_id)] || {}),
      name: patch.name,
      position: patch.position,
      overall: patch.overall,
      nation: patch.nation,
      nickname: patch.nickname,
    };
    applyPlayerProfilesEverywhere();
  }
}

function setupPlayerEditForm() {
  const form = document.getElementById("player-edit-form");
  if (!form || form.dataset.bound === "1") return;
  form.dataset.bound = "1";
  setupEditNationPicker();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (window.__twValidateEditNation) window.__twValidateEditNation();
    const oldId = document.getElementById("edit-player-id")?.value || "";
    const team = document.getElementById("edit-team")?.value || "";
    const oldName = document.getElementById("edit-old-name")?.value || "";
    const oldPos = document.getElementById("edit-old-position")?.value || "";
    const personId = document.getElementById("edit-person-id")?.value || "";
    const name = String(document.getElementById("edit-name")?.value || "").trim();
    const nickname = String(document.getElementById("edit-nickname")?.value || "").trim();
    const overall = Math.max(
      1,
      Math.min(99, parseInt(document.getElementById("edit-overall")?.value, 10) || 72)
    );
    const position = String(document.getElementById("edit-position")?.value || "")
      .trim()
      .toUpperCase();
    const nation = String(document.getElementById("edit-nation-value")?.value || "").trim();
    if (!name || !position) return;

    pushUndo();
    try {
      const res = await fetch("/api/player/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          team,
          name: oldName,
          position: oldPos,
          person_id: personId || undefined,
          new_name: name !== oldName ? name : undefined,
          new_position: position !== oldPos ? position : undefined,
          overall,
          nation,
          nickname,
        }),
      });
      const j = await res.json();
      if (!res.ok || !j.ok) throw new Error(j.error || "ошибка сохранения");
      if (j.profiles) playerProfiles = j.profiles;
      applyPlayerUpdateLocally(oldId, team, j.player || {});
      markDirty();
      closeModal("modal-edit-overlay");
      renderAll();
      setStatus(`сохранено: ${(j.player || {}).name || name} · ${overall}`);
    } catch (err) {
      undoStack.pop();
      updateUndoBtn();
      setStatus("правка: " + err.message);
    }
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
    markDirty();
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

function applyImportPayload(j) {
  pushUndo();
  if (Array.isArray(j.teams)) teams = j.teams;
  if (j.baseline_home) baselineHome = { ...j.baseline_home };
  if (Array.isArray(j.free_agents)) {
    freeAgents = j.free_agents.map((p) => ({
      ...p,
      status: p.status || "bench",
      fired: !!p.fired,
    }));
  }
  if (j.removed_from_squad) removedFromSquad = { ...j.removed_from_squad };
  if (j.window === "summer" || j.window === "winter") {
    currentWindow = j.window;
    localStorage.setItem("tw_window", currentWindow);
    updateTitle();
  }
  rekeyClubPlayersWithWrongIds();
  dedupeGlobally(teams);
  purgeFreeAgentsInSquads();
  for (const p of freeAgents) {
    if (p?.id) baselineHome[p.id] = FA_TEAM;
  }
  applyInjuryFlags(teams);
  markDirty();
  renderAll();
  const note = (j.notes || []).join("; ");
  const kind = j.full ? "полная загрузка" : "обновление карточек";
  const tr = j.transfers_count != null ? ` · трансферов: ${j.transfers_count}` : "";
  const fa = freeAgents.length ? ` · FA: ${freeAgents.length}` : "";
  setStatus(`${kind}${tr}${fa}${note ? ` · ${note}` : ""}`);
}

async function importSquadsFromFile(file) {
  const text = await file.text();
  const isJson = file.name.toLowerCase().endsWith(".json") || text.trimStart().startsWith("{");
  const url = isJson ? "/api/import-state" : "/api/import-squads";
  const body = isJson
    ? JSON.parse(text)
    : { text, teams, baseline_home: baselineHome, free_agents: freeAgents };
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  applyImportPayload(j);
}

async function importTransfersFromFile(file) {
  const text = await file.text();
  const res = await fetch("/api/import-transfers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      teams,
      baseline_home: baselineHome,
      free_agents: freeAgents,
      window: currentWindow,
    }),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  applyImportPayload(j);
}

function setFreeAgentsFromImport(players) {
  pushUndo();
  freeAgents = (players || []).map((p) => ({ ...p, status: p.status || "bench", fired: !!p.fired }));
  for (const p of freeAgents) {
    if (p && p.id) baselineHome[p.id] = FA_TEAM;
  }
  freeAgents.sort((a, b) => (Number(b.overall) || 0) - (Number(a.overall) || 0));
  markDirty();
  renderAll();
}

async function reloadFaFromDb() {
  const res = await fetch("/api/free-agents");
  const j = await res.json();
  if (!res.ok || j.error) throw new Error(j.error || "нет данных FA");
  setFreeAgentsFromImport(j.players || []);
  setStatus(`FA из БД: ${freeAgents.length} игроков`);
}

async function importFaFromFile(file) {
  const text = await file.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (_) {
    throw new Error("нужен JSON (free_agents.json из бота)");
  }
  const res = await fetch("/api/import-fa", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  setFreeAgentsFromImport(j.players || []);
  const note = (j.notes || []).length ? ` · ${j.notes.slice(0, 2).join("; ")}` : "";
  setStatus(`FA из бота: ${freeAgents.length} игроков${note}`);
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

function emptyStartFromFormation(fid, fallbackStart) {
  const form = formationById(fid);
  if (form && Array.isArray(form.slots) && form.slots.length) {
    return form.slots.map((slot) => ({
      id: null,
      name: null,
      position: null,
      overall: null,
      injured: false,
      slot: slot.slot_id,
      x: slot.x,
      y: slot.y,
    }));
  }
  return (fallbackStart || []).map((slot) => ({
    id: null,
    name: null,
    position: null,
    overall: null,
    injured: false,
    slot: slot.slot,
    x: slot.x,
    y: slot.y,
  }));
}

function mergeSavedStart(savedStart, fid, fallbackStart, freshBaseline) {
  const slots = emptyStartFromFormation(fid, fallbackStart);
  const bySlot = new Map();
  (savedStart || []).forEach((p, i) => {
    if (!p?.id) return;
    if (p.slot) bySlot.set(String(p.slot), p);
    bySlot.set(`__idx_${i}`, p);
  });
  return slots.map((slot, i) => {
    const src = bySlot.get(slot.slot) || bySlot.get(`__idx_${i}`);
    if (!src?.id) return slot;
    return {
      ...src,
      id: migrateId(src.id, freshBaseline),
      slot: slot.slot,
      x: slot.x,
      y: slot.y,
    };
  });
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

    const fid =
      savedTeam.formation_id != null
        ? Number(savedTeam.formation_id)
        : Number(tmpl.formation_id) || 1;

    const team = emptyTeamFromTemplate(tmpl);
    team.formation_id = fid;
    team.start = mergeSavedStart(savedTeam.start, fid, tmpl.start, freshBaseline);

    for (const zone of ["bench", "reserve"]) {
      const savedLen = (savedTeam[zone] || []).length;
      while (team[zone].length < savedLen) {
        team[zone].push({ id: null, name: null, position: null, overall: null });
      }
    }

    for (const zone of ["bench", "reserve"]) {
      (savedTeam[zone] || []).forEach((src, i) => {
        if (!src || !src.id || i >= team[zone].length) return;
        team[zone][i] = { ...src, id: migrateId(src.id, freshBaseline) };
      });
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
  const emptySlot = () => ({
    id: null,
    name: null,
    position: null,
    overall: null,
    injured: false,
  });
  if (isNationsMode()) {
    for (const team of teamList || []) {
      if (!Array.isArray(team.bench)) team.bench = [];
      while (team.bench.length < WC_BENCH) team.bench.push(emptySlot());
      if (!Array.isArray(team.reserve)) team.reserve = [];
      while (team.reserve.length < WC_RESERVE) team.reserve.push(emptySlot());
    }
    return;
  }
  /** Клубы: 7 запас + мин. 14 резерв (= 21 замена) + пустые ячейки для дропа. */
  for (const team of teamList || []) {
    if (!Array.isArray(team.bench)) team.bench = [];
    while (team.bench.length < BENCH_SLOTS) team.bench.push(emptySlot());

    if (!Array.isArray(team.reserve)) team.reserve = [];
    while (team.reserve.length < MIN_RESERVE_SLOTS) {
      team.reserve.push(emptySlot());
    }
    let trailingEmpty = 0;
    for (let i = team.reserve.length - 1; i >= 0; i--) {
      if (team.reserve[i] && team.reserve[i].id) break;
      trailingEmpty += 1;
    }
    while (trailingEmpty < EXTRA_RESERVE) {
      team.reserve.push(emptySlot());
      trailingEmpty += 1;
    }
  }
}

function removeFaPlayer(p) {
  if (!p || !p.id) return;
  const msg =
    `Удалить ${p.name} (${p.position}, ${p.overall}) из пула свободных агентов?\n\n` +
    "Игрок будет удалён из free_agents.db (не трансфер). " +
    "Отменить можно кнопкой ↩ до перезагрузки страницы.";
  if (!window.confirm(msg)) return;
  pushUndo();
  freeAgents = freeAgents.filter((x) => x.id !== p.id);
  delete baselineHome[p.id];
  markDirty();
  renderAll();
  fetch("/api/fa/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      id: p.id,
      name: p.name,
      position: p.position,
      person_id: p.person_id,
    }),
  })
    .then((res) => res.json())
    .then((j) => {
      if (!j.ok) {
        setStatus(`удалён локально (БД: ${j.error || "ошибка"})`);
        return;
      }
      setStatus(`удалён из FA: ${p.name}`);
    })
    .catch(() => setStatus(`удалён локально: ${p.name}`));
}

function removePlayerFromSquad(playerId, teamName) {
  if (isNationsMode() && nationNamesMatch(teamName, selectedNation)) {
    returnPlayerToNationalPool(playerId, teamName);
    return;
  }
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
  markDirty();
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
  if (isNationsMode()) return false;
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
  el.className =
    "player" +
    (inline ? " player-inline" : "") +
    (isIncoming(teamName, p) ? " incoming" : "") +
    (p.injured ? " injured" : "");
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
  const firedBadge =
    teamName === FA_TEAM && p.fired
      ? `<span class="fa-tag" title="Исключён из клуба">увол</span>`
      : "";
  const rmTitle =
    isNationsMode() && nationNamesMatch(teamName, selectedNation)
      ? "Вернуть в пул"
      : teamName === FA_TEAM
        ? "Удалить из FA"
        : "Убрать из заявки";
  const mainHtml = inline
    ? `${injuryBadge}${firedBadge}<span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="pos" title="Клик — изменить позицию">${p.position}</span><span class="nm" title="Клик — изменить имя">${p.name}</span>`
    : `${injuryBadge}${firedBadge}<span class="ovr" title="Клик — изменить рейтинг">${p.overall}</span><span class="nm" title="Клик — изменить имя">${p.name}</span><span class="pos" title="Клик — изменить позицию">${p.position}</span>`;
  el.innerHTML =
    `<div class="player-main">${mainHtml}</div>` +
    `<div class="player-actions">` +
    `<button type="button" class="edit-btn" title="Редактировать">✎</button>` +
    `<button type="button" class="rm-btn" title="${rmTitle}">×</button>` +
    `</div>`;
  bindPlayerActionButton(el.querySelector(".edit-btn"), () => openPlayerEditModal(p, teamName));
  bindPlayerActionButton(el.querySelector(".rm-btn"), () => {
    if (teamName === FA_TEAM) {
      removeFaPlayer(p);
    } else {
      removePlayerFromSquad(p.id, teamName);
    }
  });
  el.querySelector(".ovr")?.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    startOvrEdit(el.querySelector(".ovr"), p.id);
  });
  el.querySelector(".pos")?.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    startPosEdit(el.querySelector(".pos"), p.id, teamName);
  });
  el.querySelector(".nm")?.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    startNameEdit(el.querySelector(".nm"), p.id, teamName);
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
    recomputeAvgStart(team);
  }
  for (const p of freeAgents) {
    if (p.id === id) p.overall = value;
  }
  syncNationalPoolPlayer(id, { overall: value });
  propagatePlayerProfileEdit(id, { overall: value });
}

function playerIdFor(teamName, name, position) {
  const nm = String(name || "").trim();
  const pos = String(position || "").trim().toUpperCase();
  if (teamName === FA_TEAM) return `Free Agent|${nm}|${pos}`;
  return `${teamName}|${nm}|${pos}`;
}

function rekeyPlayer(oldId, teamName, name, position) {
  const newId = playerIdFor(teamName, name, position);
  if (!oldId || oldId === newId) return newId;
  const nm = String(name || "").trim();
  const pos = String(position || "").trim().toUpperCase();
  const loc = findPlayerGlobally(oldId);
  const personId = loc?.player?.person_id;

  for (const team of teams) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        const p = team[zone][i];
        if (p?.id === oldId) {
          p.id = newId;
          p.name = nm;
          p.position = pos;
        }
      }
    }
  }
  for (const p of freeAgents) {
    if (p.id === oldId) {
      p.id = newId;
      p.name = nm;
      p.position = pos;
    }
  }
  if (baselineHome[oldId] !== undefined) {
    baselineHome[newId] = baselineHome[oldId];
    delete baselineHome[oldId];
  }
  if (removedFromSquad[oldId]) {
    removedFromSquad[newId] = { ...removedFromSquad[oldId], id: newId, name: nm, position: pos };
    delete removedFromSquad[oldId];
  }
  syncNationalPoolPlayer(oldId, { id: newId, name: nm, position: pos, person_id: personId });
  propagatePlayerProfileEdit(oldId, { name: nm, position: pos });
  return newId;
}

function resolvePlayerTeamName(playerId, fallbackTeam) {
  if (fallbackTeam && fallbackTeam !== FA_TEAM) return fallbackTeam;
  const parts = String(playerId || "").split("|");
  if (parts.length >= 3 && parts[0] !== "Free Agent") return parts[0];
  return fallbackTeam || FA_TEAM;
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
    markDirty();
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

function startPosEdit(span, playerId, teamName) {
  if (!span || !playerId) return;
  const loc = findPlayerGlobally(playerId);
  const before = String(loc?.player?.position || span.textContent || "").trim().toUpperCase();
  const sel = document.createElement("select");
  sel.className = "pos-edit";
  positionsCatalog.forEach((code) => {
    const opt = document.createElement("option");
    opt.value = code;
    opt.textContent = code;
    if (code === before) opt.selected = true;
    sel.appendChild(opt);
  });
  span.replaceWith(sel);
  sel.focus();
  const commit = () => {
    const pos = String(sel.value || before).trim().toUpperCase();
    const nm = loc?.player?.name || "";
    const homeTeam = resolvePlayerTeamName(playerId, teamName);
    rekeyPlayer(playerId, homeTeam, nm, pos);
    markDirty();
    setStatus("позиция изменена (не сохранено)");
    renderAll();
  };
  sel.addEventListener("blur", commit);
  sel.addEventListener("change", commit);
  sel.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") {
      ev.preventDefault();
      renderAll();
    }
  });
}

function startNameEdit(span, playerId, teamName) {
  if (!span || !playerId) return;
  const loc = findPlayerGlobally(playerId);
  const before = String(loc?.player?.name || span.textContent || "").trim();
  const inp = document.createElement("input");
  inp.type = "text";
  inp.className = "nm-edit";
  inp.value = before;
  span.replaceWith(inp);
  inp.focus();
  inp.select();
  const commit = () => {
    const nm = String(inp.value || before).trim() || before;
    const pos = loc?.player?.position || "";
    const homeTeam = resolvePlayerTeamName(playerId, teamName);
    rekeyPlayer(playerId, homeTeam, nm, pos);
    markDirty();
    setStatus("имя изменено (не сохранено)");
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
    const srcTeam = dragPayload.team;
    pushUndo();
    movePlayer(dragPayload, teamName, zone, index);
    dragPayload = null;
    stopDragScroll();
    renderAll();
    markDirty(teamName);
    if (srcTeam && srcTeam !== teamName) markDirty(srcTeam);
    if (srcTeam === FA_TEAM || teamName === FA_TEAM) markDirty(FA_TEAM);
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

function zoneRankForDedupe(zone) {
  return { start: 3, bench: 2, reserve: 1 }[zone] || 0;
}

function dedupeByPersonId(list) {
  const byPid = new Map();
  for (const team of list) {
    for (const zone of ["start", "bench", "reserve"]) {
      for (let i = 0; i < team[zone].length; i++) {
        const p = team[zone][i];
        const pid = Number(p?.person_id);
        if (!Number.isFinite(pid) || pid <= 0 || !p?.id) continue;
        if (!byPid.has(pid)) byPid.set(pid, []);
        byPid.get(pid).push({ team, teamName: team.name, zone, index: i, id: p.id, player: p });
      }
    }
  }
  for (const [, locs] of byPid) {
    if (locs.length <= 1) continue;
    let keep = locs[0];
    let best = -1;
    for (const loc of locs) {
      const home = baselineHome[loc.id];
      const score =
        (home === loc.teamName ? 1000 : 0) +
        zoneRankForDedupe(loc.zone) * 100 +
        (home && home !== FA_TEAM ? 10 : 0);
      if (score > best) {
        best = score;
        keep = loc;
      }
    }
    for (const loc of locs) {
      if (loc === keep) continue;
      emptySlot(loc.team, loc.zone, loc.index);
    }
  }
}

function dedupeGlobally(list) {
  dedupeByPersonId(list);
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
  purgeFreeAgentsInSquads();
}

function movePlayer(src, destTeamName, destZone, destIndex) {
  if (destTeamName === FA_TEAM) {
    if (isNationsMode()) return;
    movePlayerToFa(src);
    return;
  }
  const destTeam = teams.find((t) => t.name === destTeamName);
  if (!destTeam) return;

  if (src.fromNational || (isNationsMode() && findNationalPlayer(src.id))) {
    const nat = findNationalPlayer(src.id);
    const moving = nat
      ? { ...nat }
      : {
          id: src.id,
          name: src.name,
          position: src.position,
          overall: src.overall,
          person_id: src.person_id,
        };
    if (isNationsMode() && destTeamName) {
      moving.id = playerIdFor(destTeamName, moving.name, moving.position);
    }
    const destSlot = destTeam[destZone][destIndex];
    const displaced = destSlot?.id && destSlot.id !== moving.id ? { ...destSlot } : null;
    const oldPoolId = nat?.id || src.id;
    removeAllInstancesOfId(moving.id);
    if (oldPoolId && oldPoolId !== moving.id) removeAllInstancesOfId(oldPoolId);
    placePlayer(destTeam, destZone, destIndex, moving);
    syncNationalPoolPlayer(oldPoolId, {
      id: moving.id,
      person_id: moving.person_id,
    });
    if (displaced) {
      if (isNationsMode() && nationNamesMatch(destTeamName, selectedNation)) {
        let placed = false;
        for (const z of ["bench", "reserve", "start"]) {
          for (let i = 0; i < destTeam[z].length; i++) {
            if (!destTeam[z][i]?.id) {
              placePlayer(destTeam, z, i, displaced);
              placed = true;
              break;
            }
          }
          if (placed) break;
        }
      } else {
        for (const z of ["bench", "reserve"]) {
          for (let i = 0; i < destTeam[z].length; i++) {
            if (!destTeam[z][i]?.id) {
              placePlayer(destTeam, z, i, displaced);
              dedupeGlobally(teams);
              return;
            }
          }
        }
      }
    }
    dedupeGlobally(teams);
    return;
  }

  if (src.fromFa || src.team === FA_TEAM) {
    let faPlayer = findFaPlayer(src.id);
    if (!faPlayer) {
      const nat = findNationalPlayer(src.id);
      if (nat && (nat.is_fa || nat.team === FA_TEAM)) {
        faPlayer = { ...nat, status: "bench" };
      }
    }
    if (!faPlayer) return;
    const oldFaId = src.id;
    const faKey = playerIdentityKey(faPlayer);
    freeAgents = freeAgents.filter((p) => {
      if (p.id === oldFaId) return false;
      const pk = playerIdentityKey(p);
      return !(faKey && pk && pk === faKey);
    });
    const newId = playerIdFor(destTeamName, faPlayer.name, faPlayer.position);
    migrateBaselineHome(oldFaId, newId, destTeamName, FA_TEAM);
    const moving = { ...faPlayer, id: newId };
    const destSlot = destTeam[destZone][destIndex];
    const displaced = destSlot?.id && destSlot.id !== moving.id ? { ...destSlot } : null;
    removeAllInstancesOfId(oldFaId);
    removeAllInstancesOfId(newId);
    placePlayer(destTeam, destZone, destIndex, moving);
    syncNationalPoolPlayer(oldFaId, {
      id: newId,
      person_id: moving.person_id,
      is_fa: false,
      team: destTeamName,
    });
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
  const oldId = moving.id;
  const displaced = destSlot?.id && destSlot.id !== moving.id ? { ...destSlot } : null;
  const vacated = { team: loc.team, zone: loc.zone, index: loc.index };

  removeAllInstancesOfId(oldId);
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
  const benchCount = activeBenchCount();
  const bench = [];
  for (let i = 0; i < benchCount; i++) {
    bench.push(remaining.length ? { ...remaining.shift() } : emptySlot());
  }
  let reserve;
  if (isNationsMode()) {
    reserve = [];
    for (let i = 0; i < WC_RESERVE; i++) {
      reserve.push(remaining.length ? { ...remaining.shift() } : emptySlot());
    }
  } else {
    reserve = remaining.map((p) => ({ ...p }));
    while (reserve.length < MIN_RESERVE_SLOTS) {
      reserve.push(emptySlot());
    }
    for (let i = 0; i < EXTRA_RESERVE; i++) {
      reserve.push(emptySlot());
    }
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
  markDirty(teamName);
  renderAll();
  setStatus(`схема ${team.formation} — не сохранено`);
}

function onCoachChange(teamName, coach) {
  const team = teams.find((t) => t.name === teamName);
  if (!team) return;
  team.coach = String(coach || "").trim();
  const form = formationById(team.formation_id);
  const label = form?.label || team.formation || "";
  team.formation = team.coach ? `${label} · ${team.coach}` : label;
  team.caption = team.formation;
  markDirty(teamName);
  renderAll();
  setStatus(`тренер ${team.coach || "—"} — не сохранено`);
}

function renderTeam(team) {
  const card = document.createElement("div");
  card.className = "team-card";
  card.dataset.team = team.name;
  if (!isNationsMode()) {
    const { inn, out } = countInOut(team);
    const overIn = inn > maxIn;
    const overOut = out > maxOut;
    if (overIn || overOut) card.classList.add("over-quota");
  }

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
  if (isNationsMode()) {
    const coachWrap = document.createElement("label");
    coachWrap.className = "formation-pick";
    coachWrap.textContent = " · Тренер ";
    const coachSel = document.createElement("select");
    coachSel.className = "coach-edit";
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.textContent = "—";
    coachSel.appendChild(emptyOpt);
    const curCoach = (team.coach || "").trim();
    const names = coachesCatalog.slice();
    if (curCoach && !names.includes(curCoach)) names.unshift(curCoach);
    names.forEach((name) => {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      if (name === curCoach) opt.selected = true;
      coachSel.appendChild(opt);
    });
    coachSel.addEventListener("change", (e) => onCoachChange(team.name, e.target.value));
    coachWrap.appendChild(coachSel);
    meta.appendChild(coachWrap);
  } else if (team.coach) {
    const coachSpan = document.createElement("span");
    coachSpan.textContent = ` · ${team.coach}`;
    meta.appendChild(coachSpan);
  }
  hdr.appendChild(meta);

  if (!isNationsMode()) {
    const { inn, out } = countInOut(team);
    const overIn = inn > maxIn;
    const overOut = out > maxOut;
    const counters = document.createElement("div");
    counters.className = "counters";
    counters.innerHTML = `
      <span class="in${overIn ? " over" : ""}">${inn}/${maxIn} IN</span>
      ·
      <span class="out${overOut ? " over" : ""}">${out}/${maxOut} OUT</span>
    `;
    hdr.appendChild(counters);
  }

  const squadEv = evaluateTeamSquad(team);
  if (!squadEv.complete) card.classList.add("squad-incomplete");

  const quota = document.createElement("div");
  quota.className = "squad-quota" + (squadEv.complete ? " ok" : " warn");
  const qHead = document.createElement("div");
  qHead.className = "squad-quota-head";
  const target = activeSquadTarget();
  if (isNationsMode()) {
    qHead.textContent = squadEv.complete
      ? `Заявка ${squadEv.total}/${target} ✓`
      : `Заявка ${squadEv.total}/${target} · старт ${squadEv.start_filled}/${WC_START} · зап+рез ${squadEv.reserve_filled}/${WC_BENCH + WC_RESERVE}`;
  } else {
    qHead.textContent = squadEv.complete
      ? `Заявка ${squadEv.total}/${target} ✓`
      : `Заявка ${squadEv.total}/${target} · замены ${squadEv.reserve_filled}/${SQUAD_RESERVE_TARGET}`;
  }
  quota.appendChild(qHead);
  if (!squadEv.complete) {
    const qMiss = document.createElement("div");
    qMiss.className = "squad-quota-miss";
    qMiss.textContent = formatSquadIssues(squadEv);
    quota.appendChild(qMiss);
  }
  if (!isNationsMode()) {
    const qGrid = document.createElement("div");
    qGrid.className = "squad-quota-grid";
    (squadEv.group_status || []).forEach((g) => {
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
          ? `Слот ${g.slot_id}: лишний на ${g.label} (нужно ${g.need}, в заявке ${g.have})`
          : `Слот ${g.slot_id}: замены с позицией ${g.label} — ${g.have}/${g.need}`;
      qGrid.appendChild(chip);
    });
    quota.appendChild(qGrid);
  }
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
  hBench.textContent = isNationsMode() ? `Запас (${WC_BENCH})` : "Запасные (в заявку 32)";
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
  hRes.textContent = isNationsMode() ? `Резерв (${WC_RESERVE})` : "Резерв (замены по позициям)";
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
  teams.forEach(recomputeAvgStart);
  if (!isNationsMode()) renderFaPanel();
  renderNationalPanel();
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  const visible = isNationsMode() && selectedNation
    ? teams.filter((t) => t.name === selectedNation)
    : teams;
  visible.forEach((t) => grid.appendChild(renderTeam(t)));
}

function populateNationSelect() {
  const sel = document.getElementById("nation-select");
  if (!sel) return;
  const prev = selectedNation;
  sel.innerHTML = "";
  teams.forEach((t) => {
    const opt = document.createElement("option");
    opt.value = t.name;
    opt.textContent = t.name;
    sel.appendChild(opt);
  });
  if (prev && teams.some((t) => t.name === prev)) {
    selectedNation = prev;
  } else if (teams.length) {
    selectedNation = teams[0].name;
  } else {
    selectedNation = "";
  }
  sel.value = selectedNation;
}

function updateModeUi() {
  document.querySelectorAll(".clubs-only").forEach((el) => {
    el.hidden = isNationsMode();
  });
  document.querySelectorAll(".nations-only").forEach((el) => {
    el.hidden = !isNationsMode();
  });
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === currentMode);
  });
  const faPanel = document.getElementById("fa-panel");
  if (faPanel) faPanel.hidden = isNationsMode();
  populateNationSelect();
  updateTitle();
  document.getElementById("layout")?.classList.toggle("nations-layout", isNationsMode());
}

function currentState() {
  return {
    mode: currentMode,
    window: currentWindow,
    season: rostersSeason,
    revision: stateRevision,
    rosters_revision: rostersRevision,
    client_id: clientIdentity.id,
    client_name: clientIdentity.name,
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
  if (isNationsMode()) {
    const n = selectedNation || `${teams.length} сборных`;
    const season = rostersSeason != null ? ` · сезон ${rostersSeason}` : "";
    document.getElementById("app-title").textContent = `Сборные ЧМ — ${n}${season}`;
    document.title = `Сборные ЧМ — ${n}`;
    return;
  }
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

async function importWcSquadsFromFile(file) {
  const text = await file.text();
  const res = await fetch("/api/import-wc-squads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  const j = await res.json();
  if (!j.ok) throw new Error(j.error || "import failed");
  pushUndo();
  const byName = new Map(teams.map((t) => [t.name, t]));
  for (const imported of j.teams || []) {
    byName.set(imported.name, imported);
  }
  teams = Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name, "ru"));
  dedupeGlobally(teams);
  applyInjuryFlags(teams);
  ensureExtraReserveSlots(teams);
  populateNationSelect();
  markDirty();
  renderAll();
  setStatus(`заявки ЧМ: ${j.count || 0} сборных`);
}

async function loadData() {
  ensureClientIdentity();
  const savedMode = localStorage.getItem("tw_mode");
  if (savedMode === "nations" || savedMode === "clubs") currentMode = savedMode;
  const [cfgRes, rostersRes] = await Promise.all([
    fetch("/api/config"),
    fetch(`/api/rosters?mode=${encodeURIComponent(currentMode)}`),
  ]);
  const cfg = await cfgRes.json();
  const rosters = await rostersRes.json();
  if (!rostersRes.ok || rosters.error) {
    throw new Error(rosters.error || `rosters HTTP ${rostersRes.status}`);
  }
  if (isNationsMode() && !assertNationsRosters(rosters)) {
    currentMode = "clubs";
    localStorage.setItem("tw_mode", currentMode);
    return loadData();
  }
  if (isNationsMode() && !cfg.modes?.nations) {
    window.alert(
      "Эта версия сервера не поддерживает «Сборные ЧМ». Перезапусти run.sh из tools/transfer_window_app."
    );
    currentMode = "clubs";
    localStorage.setItem("tw_mode", currentMode);
    return loadData();
  }
  lastRosters = rosters;
  rostersSeason = rosters.season ?? null;
  rostersRevision = rosters.rosters_revision ?? null;
  leaguesCatalog = Array.isArray(cfg.leagues) ? cfg.leagues : (rosters.leagues || []);
  nationsByConfederation = cfg.nations_by_confederation || {};
  setNationsCatalog(cfg.nations_by_confederation, cfg.nations);
  if (Array.isArray(cfg.positions)) {
    positionsCatalog = cfg.positions;
    fillPoolPositionSelect(document.getElementById("fa-pos-filter"));
    fillPoolPositionSelect(document.getElementById("national-pos-filter"));
  }
  if (Array.isArray(cfg.coaches) && cfg.coaches.length) {
    coachesCatalog = cfg.coaches;
  } else {
    await loadCoachesCatalog();
  }
  await loadPlayerProfiles();
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
  const modeRules = cfg.modes?.[currentMode]?.squad_rules;
  if (modeRules) squadRules = { ...squadRules, ...modeRules };
  else if (cfg.squad_rules) squadRules = { ...squadRules, ...cfg.squad_rules };
  localStorage.setItem("tw_window", currentWindow);
  localStorage.setItem("tw_mode", currentMode);
  injuryAsOfMonth = Number(rosters.injury_as_of_month) || 6;
  injuryById = buildInjuryIndex(rosters);
  formationsCatalog = Array.isArray(rosters.formations) ? rosters.formations : [];
  if (rosters.squad_rules) squadRules = { ...squadRules, ...rosters.squad_rules };
  updateModeUi();
  if (cfg.data_dir) {
    window.__twDataDir = cfg.data_dir;
  }
  if (cfg.multiplayer) {
    updateSharePanel(cfg.multiplayer);
    const mp = cfg.multiplayer;
    setLiveSyncEnabled(
      !!(mp.live_sync || mp.share_url || mp.lan_mode || mp.tunnel_url || mp.tunnel_mode)
    );
    if (cfg.multiplayer.tunnel_pending) pollTunnelUrl();
  }

  const freshBaseline = { ...(rosters.baseline_home || {}) };
  if (!isNationsMode()) syncFreeAgentsFromRosters(rosters);
  for (const pid of Object.keys(freshBaseline)) {
    if (!(pid in baselineHome) || baselineHome[pid] === undefined) {
      baselineHome[pid] = freshBaseline[pid];
    }
  }

  const stateUrl = isNationsMode()
    ? "/api/state?mode=nations"
    : `/api/state?window=${encodeURIComponent(currentWindow)}`;
  const stateRes = await fetch(stateUrl);
  if (stateRes.ok) {
    const saved = await stateRes.json();
    const savedSeason = saved.season != null ? Number(saved.season) : null;
    const curSeason = rostersSeason != null ? Number(rostersSeason) : null;
    if (savedSeason != null && curSeason != null && savedSeason !== curSeason) {
      loadFreshFromRosters(
        rosters,
        isNationsMode()
          ? `сезон ${curSeason}: старый сейв (${savedSeason}) сброшен`
          : `сезон ${curSeason}: старый сейв (${savedSeason}) сброшен — 0/${maxOut} OUT`
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
    applySavedState(saved, rosters);
    applyPlayerProfilesEverywhere();
    const savedRostersRev = saved.rosters_revision ?? null;
    const curRostersRev = rosters.rosters_revision ?? null;
    if (curRostersRev != null && savedRostersRev !== curRostersRev) {
      const stats = reconcileWithFreshRosters(rosters);
      await saveState({ silent: true, skipIncompleteConfirm: true });
      hideSyncBanner();
      setStatus(
        `БД → app: рейтинги ${stats.ovr}, снято ${stats.removed}, FA ${stats.fa}` +
          (saved.updated_by ? ` · сейв ${saved.updated_by}` : "")
      );
    } else {
      const injN = Object.keys(injuryById).length;
      const rmN = Object.keys(removedFromSquad).length;
      setStatus(
        isNationsMode()
          ? `загружено: сборные ЧМ · ${teams.length} наций` +
              (saved.updated_by ? ` · ${saved.updated_by}` : "")
          : `загружено: ${windowLabels[currentWindow] || currentWindow}` +
              (injN ? ` · травм на ${injuryAsOfMonth} мес.: ${injN}` : "") +
              (freeAgents.length ? ` · FA: ${freeAgents.length}` : "") +
              (rmN ? ` · убрано: ${rmN}` : "") +
              (saved.updated_by ? ` · ${saved.updated_by}` : "")
      );
    }
    startSyncPoll();
    startPeriodicAutosave();
    if (isNationsMode()) {
      loadNationalPoolsFromApi().catch(() => {}).then(() => renderNationalPanel());
    }
    return;
  }

  baselineHome = freshBaseline;
  loadFreshFromRosters(
    rosters,
    isNationsMode()
      ? `сезон ${rosters.season || "?"} — исходные заявки (${teams.length} сборных)`
      : `сезон ${rosters.season || "?"} — исходные составы (${windowLabels[currentWindow]})` +
          (Number(rosters.injured_count) || Object.keys(injuryById).length
            ? ` · травм: ${Number(rosters.injured_count) || Object.keys(injuryById).length}`
            : "") +
          (freeAgents.length ? ` · FA: ${freeAgents.length}` : "")
  );
  applyPlayerProfilesEverywhere();
  startSyncPoll();
  startPeriodicAutosave();
  if (isNationsMode()) {
    loadNationalPoolsFromApi().catch(() => {}).then(() => renderNationalPanel());
  }
}

async function switchMode(nextMode) {
  if (nextMode === currentMode) return;
  if (dirty) {
    const ok = window.confirm(
      "Есть несохранённые изменения. Переключить режим без сохранения?"
    );
    if (!ok) return;
  }
  currentMode = nextMode;
  localStorage.setItem("tw_mode", currentMode);
  nationalPools = null;
  await loadData();
  if (isNationsMode()) {
    try {
      await loadNationalPoolsFromApi();
    } catch (_) {
      /* optional */
    }
  }
}

async function switchWindow(next) {
  if (next === currentWindow) return;
  if (dirty) {
    if (liveSyncEnabled) {
      await flushAutosave();
    }
    if (dirty) {
      const ok = window.confirm(
        "Есть несохранённые изменения. Переключить окно без сохранения текущего?"
      );
      if (!ok) return;
    }
  }
  currentWindow = next;
  localStorage.setItem("tw_window", currentWindow);
  await loadData();
}

async function saveState(options = {}) {
  const { silent = false, skipIncompleteConfirm = false, mergeRetry = false } = options;
  const incomplete = findIncompleteSquads();
  if (incomplete.length && !skipIncompleteConfirm) {
    const hint = isNationsMode()
      ? `Нужно ${WC_TOTAL} игроков (11 старт + 7 запас + 8 резерв).`
      : `Нужно ${SQUAD_TARGET} игроков (11 основа + 21 замена).`;
    const ok = window.confirm(
      `Неполная заявка у ${incomplete.length} ${isNationsMode() ? "сборн(ых)" : "клуб(ов)"}.\n` +
        `${hint}\n\n` +
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
  if (res.status === 409 && j.conflict) {
    const who = j.updated_by || "напарник";
    stateRevision = Number(j.revision) || stateRevision;
    if (!mergeRetry && j.server_state && dirtyTeams.size && lastRosters) {
      const snap = snapshotDirtyTeams();
      applySavedState(j.server_state, lastRosters);
      restoreDirtyTeamsSnapshot(snap);
      dirty = true;
      await saveState({ silent: true, skipIncompleteConfirm: true, mergeRetry: true });
      setStatus(`⟳ сохранено: ваши клубы + ${who} (rev ${stateRevision})`);
      return;
    }
    showSyncBanner({ revision: j.revision, updated_by: who });
    if (silent) {
      setStatus(`${who} тоже сохранил — «Загрузить его» или «Оставить моё»`);
    } else {
      setStatus(`конфликт с ${who} (rev ${j.revision}) — выберите в плашке сверху`);
    }
    return;
  }
  if (j.ok) {
    dirty = false;
    dirtyTeams = new Set();
    stateRevision = Number(j.revision) || stateRevision;
    hideSyncBanner();
    updateSyncBadge(j);
    if (silent) {
      setStatus(`⟳ синхронизировано (rev ${stateRevision})`);
      return;
    }
    const over = teams.filter((t) => {
      const { inn, out } = countInOut(t);
      return inn > maxIn || out > maxOut;
    });
    const n = j.transfers_count != null ? j.transfers_count : "?";
    const path = j.path || window.__twDataDir || "";
    let msg = isNationsMode()
      ? `сохранено (сборные ЧМ), ${teams.length} наций`
      : `сохранено (${windowLabels[currentWindow]}), трансферов: ${n}`;
    if (path) msg += ` → ${path}`;
    if (over.length) {
      msg += ` · сверх лимита: ${over.map((t) => t.name).join(", ")}`;
    }
    setStatus(msg);
    return;
  }
  setStatus("ошибка сохранения");
}

async function exportFmt(fmt, { draft = false } = {}) {
  const incomplete = findIncompleteSquads();
  const q = draft ? "&draft=1" : "";
  let res;
  try {
    res = await fetch(`/api/export?fmt=${fmt}&kind=squads${q}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentState()),
    });
  } catch (e) {
    setStatus(`ошибка сети: ${e.message}`);
    return;
  }
  let j;
  try {
    j = await res.json();
  } catch {
    setStatus("ошибка: сервер упал при выгрузке — перезапусти main.py (git pull)");
    return;
  }
  let msg = j.ok ? `выгружено: ${j.path}` : `ошибка: ${j.error || "?"}`;
  if (j.ok && j.export_dir && !String(j.path || "").startsWith(j.export_dir)) {
    msg = `выгружено: ${j.path} (папка: ${j.export_dir})`;
  }
  if (j.ok && incomplete.length) {
    msg += ` · неполных клубов: ${incomplete.length} (черновик)`;
  } else if (j.ok && j.incomplete_teams) {
    msg += ` · неполных клубов: ${j.incomplete_teams}`;
  }
  setStatus(msg);
  if (!j.ok && j.error) window.alert(j.error);
}

async function exportTransfersFmt(fmt, { draft = false } = {}) {
  const q = draft ? "&draft=1" : "";
  const res = await fetch(`/api/export?fmt=${fmt}&kind=transfers${q}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(
    j.ok
      ? `${draft ? "черновик" : ""} трансферов ${j.count}: ${j.path}`.trim()
      : `ошибка: ${j.error || "?"}`
  );
}

async function exportDraftBundle() {
  const res = await fetch("/api/export?kind=draft-bundle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  if (!j.ok) {
    setStatus(`ошибка: ${j.error || "?"}`);
    if (j.error) window.alert(j.error);
    return;
  }
  const parts = (j.files || []).map((f) => f.path).join("\n");
  setStatus(
    `черновик: ${j.transfers_count} трансф., ${j.squad_players} игроков` +
      (j.incomplete_teams ? ` · неполных: ${j.incomplete_teams}` : "") +
      (parts ? `\n${parts}` : "")
  );
}

async function exportWcSquads() {
  const incomplete = findIncompleteSquads();
  if (incomplete.length) {
    window.alert(squadExportBlockedMessage(incomplete));
    setStatus(`экспорт блокирован: неполная заявка (${incomplete.length})`);
    return;
  }
  const res = await fetch("/api/export?fmt=txt&kind=wc-squads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(
    j.ok
      ? `заявки ЧМ: ${j.nations || 0} сборных → ${j.path}`
      : `ошибка: ${j.error || "?"}`
  );
  if (!j.ok && j.error) window.alert(j.error);
}

async function exportNationalFmt(fmt) {
  const res = await fetch(`/api/export?fmt=${encodeURIComponent(fmt)}&kind=national`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(currentState()),
  });
  const j = await res.json();
  setStatus(
    j.ok
      ? `сборные: ${j.nations} наций, ${j.count} игроков → ${j.path}`
      : `ошибка: ${j.error || "?"}`
  );
}

document.getElementById("btn-mode-clubs")?.addEventListener("click", () => switchMode("clubs"));
document.getElementById("btn-mode-nations")?.addEventListener("click", () => switchMode("nations"));
document.getElementById("nation-select")?.addEventListener("change", (e) => {
  selectedNation = e.target.value || "";
  updateTitle();
  setNationalPools(nationalPools || { nations: [] });
  renderAll();
});
document.getElementById("btn-export-wc-squads")?.addEventListener("click", () => exportWcSquads());
document.getElementById("btn-import-wc-squads")?.addEventListener("click", () => {
  document.getElementById("import-wc-squads-file")?.click();
});
document.getElementById("btn-import-national-nations")?.addEventListener("click", async () => {
  try {
    await loadNationalPoolsFromApi();
  } catch (err) {
    setStatus("пул: " + err.message);
  }
});
document.getElementById("import-wc-squads-file")?.addEventListener("change", async (e) => {
  const file = e.target.files?.[0];
  e.target.value = "";
  if (!file) return;
  try {
    await importWcSquadsFromFile(file);
  } catch (err) {
    setStatus("заявки ЧМ: " + err.message);
  }
});
document.getElementById("btn-save").addEventListener("click", saveState);
document.getElementById("btn-undo").addEventListener("click", undoLast);
document.getElementById("btn-export-txt").addEventListener("click", () => exportFmt("txt"));
document.getElementById("btn-export-xlsx").addEventListener("click", () => exportFmt("xlsx"));
document.getElementById("btn-export-transfers-txt").addEventListener("click", () => exportTransfersFmt("simple"));
document.getElementById("btn-export-transfers-xlsx").addEventListener("click", () => exportTransfersFmt("xlsx"));
document.getElementById("btn-export-draft-bundle")?.addEventListener("click", () => exportDraftBundle());
document.getElementById("btn-export-draft-squads")?.addEventListener("click", () => exportFmt("txt", { draft: true }));
document.getElementById("btn-export-draft-transfers")?.addEventListener("click", () => exportTransfersFmt("simple", { draft: true }));
document.getElementById("btn-summer").addEventListener("click", () => switchWindow("summer"));
document.getElementById("btn-winter").addEventListener("click", () => switchWindow("winter"));
document.getElementById("btn-new-player")?.addEventListener("click", () => openModal("modal-overlay"));
document.getElementById("modal-close")?.addEventListener("click", () => closeModal("modal-overlay"));
document.getElementById("modal-cancel")?.addEventListener("click", () => closeModal("modal-overlay"));
document.getElementById("modal-edit-close")?.addEventListener("click", () => closeModal("modal-edit-overlay"));
document.getElementById("modal-edit-cancel")?.addEventListener("click", () => closeModal("modal-edit-overlay"));
document.getElementById("modal-fa-close")?.addEventListener("click", () => closeModal("modal-fa-overlay"));
document.getElementById("modal-fa-cancel")?.addEventListener("click", () => closeModal("modal-fa-overlay"));
document.getElementById("btn-reset-rosters")?.addEventListener("click", () => {
  resetToDbRosters();
});
document.getElementById("btn-import-squads")?.addEventListener("click", () => {
  document.getElementById("import-squads-file")?.click();
});
document.getElementById("btn-import-transfers")?.addEventListener("click", () => {
  document.getElementById("import-transfers-file")?.click();
});
document.getElementById("import-transfers-file")?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  if (!f) return;
  try {
    await importTransfersFromFile(f);
  } catch (err) {
    setStatus("ошибка импорта трансферов: " + err.message);
  }
});
document.getElementById("btn-import-fa")?.addEventListener("click", () => {
  document.getElementById("import-fa-file")?.click();
});
document.getElementById("btn-import-national")?.addEventListener("click", async () => {
  try {
    await loadNationalPoolsFromApi();
  } catch (err) {
    setStatus("сборные: " + err.message);
  }
});
document.getElementById("btn-export-national-txt")?.addEventListener("click", () => exportNationalFmt("txt"));
document.getElementById("national-search")?.addEventListener("input", (e) => {
  nationalFilter = e.target.value || "";
  renderNationalPanel();
});
document.getElementById("fa-search")?.addEventListener("input", (e) => {
  faFilter = e.target.value || "";
  renderFaPanel();
});
document.getElementById("btn-reload-fa")?.addEventListener("click", async () => {
  try {
    await reloadFaFromDb();
  } catch (err) {
    setStatus("FA: " + err.message);
  }
});
document.getElementById("sync-apply")?.addEventListener("click", () => applyRemoteStateFromPartner());
document.getElementById("sync-apply-toolbar")?.addEventListener("click", () => applyRemoteStateFromPartner());
document.getElementById("sync-dismiss")?.addEventListener("click", () => keepLocalVersion());
document.getElementById("sync-dismiss-toolbar")?.addEventListener("click", () => keepLocalVersion());

async function applyRemoteStateFromPartner() {
  if (dirty) {
    const ok = window.confirm("Загрузить версию напарника? Ваши несохранённые правки пропадут.");
    if (!ok) return;
  }
  await pullRemoteState();
}
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
document.getElementById("import-fa-file")?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  if (!f) return;
  try {
    await importFaFromFile(f);
  } catch (err) {
    setStatus("ошибка FA: " + err.message);
  }
});
document.getElementById("import-national-file")?.addEventListener("change", async (e) => {
  const f = e.target.files?.[0];
  e.target.value = "";
  if (!f) return;
  try {
    await importNationalFromFile(f);
  } catch (err) {
    setStatus("ошибка сборных: " + err.message);
  }
});

loadData()
  .then(() => {
    setupPlayerForm();
    setupPlayerEditForm();
    setupPoolFilters();
    setupFaSignForm();
    setupSharePanel();
  })
  .catch((e) => setStatus("ошибка: " + e.message));
