-- memory_scan_v4.lua
-- EA FC 24 — безопасный поиск счёта в RAM (quick match / турнир, НЕ карьера)
-- Перед запуском: укажите HOME_TEAM_ID и AWAY_TEAM_ID ниже.
-- Запуск: после матча, на экране результата → Live Editor → Lua Engine → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\memory_scan_v4.*

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

-- ============ НАСТРОЙКА ПОД МАТЧ ============
-- FC 24 squad IDs: Barcelona=241, Real Madrid=243
-- Если Реал дома — поменяйте HOME и AWAY местами
local HOME_TEAM_ID = 241      -- Barcelona (дом)
local AWAY_TEAM_ID = 243      -- Real Madrid (гости)
-- Если знаете счёт — укажите для фильтра (иначе -1)
local EXPECTED_HOME_SCORE = -1
local EXPECTED_AWAY_SCORE = -1
-- =============================================

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local SCRIPT_VERSION = "v4"

local WINDOW_BYTES = 0x100       -- сколько байт читать вокруг объекта
local MAX_HOP_POINTERS = 3       -- не больше 3 переходов по указателю
local HOP_OFFSETS = { 0x0, 0x8, 0x10, 0x18, 0x20, 0x28, 0x30 }
local MAX_CANDIDATES = 40

local function ensure_dir(path)
    os.execute(string.format('mkdir "%s" 2>nul', path))
end

local function write_json(path, data)
    local ok, encoded = pcall(function() return json.encode(data) end)
    if not ok then return false, encoded end
    local f = io.open(path, "w")
    if not f then return false, "io.open failed" end
    f:write(encoded)
    f:close()
    return true, nil
end

local function is_plausible_ptr(ptr)
    if not ptr or ptr == 0 then return false end
    if ptr < 0x10000 then return false end
    if ptr > 0x7FFFFFFFFFFF then return false end
    return true
end

local function safe_read_int(addr)
    if not is_plausible_ptr(addr) then return nil end
    local ok, v = pcall(function() return MEMORY:ReadInt(addr) end)
    if ok then return v end
    return nil
end

local function safe_read_char(addr)
    if not is_plausible_ptr(addr) then return nil end
    local ok, v = pcall(function() return MEMORY:ReadChar(addr) end)
    if ok then return v end
    return nil
end

local function int32_to_aob(id)
    local b1 = id % 256
    local b2 = math.floor(id / 256) % 256
    local b3 = math.floor(id / 65536) % 256
    local b4 = math.floor(id / 16777216) % 256
    return string.format("%02X %02X %02X %02X", b1, b2, b3, b4)
end

local function team_name(team_id)
    local ok, name = pcall(function() return GetTeamName(team_id) end)
    if ok and name and name ~= "" then return name end
    return string.format("team_%d", team_id)
end

local function score_pair_ok(h, a)
    if h == nil or a == nil then return false end
    if h < 0 or h > 15 or a < 0 or a > 15 then return false end
    if EXPECTED_HOME_SCORE >= 0 and h ~= EXPECTED_HOME_SCORE then return false end
    if EXPECTED_AWAY_SCORE >= 0 and a ~= EXPECTED_AWAY_SCORE then return false end
    return true
end

local function find_scores_near(base, rel_home_off, rel_away_off)
    local found = {}
    local scan_start = math.max(0, math.min(rel_home_off, rel_away_off) - 32)
    local scan_end = math.max(rel_home_off, rel_away_off) + 48

    for off = scan_start, scan_end do
        local h = safe_read_char(base + off)
        local a = safe_read_char(base + off + 1)
        if score_pair_ok(h, a) then
            found[#found + 1] = {
                score_offset = string.format("+0x%X", off),
                home_score = h,
                away_score = a,
            }
        end
        -- иногда счёт int32
        local hi = safe_read_int(base + off)
        if hi and hi >= 0 and hi <= 15 then
            local ai = safe_read_int(base + off + 4)
            if score_pair_ok(hi, ai) then
                found[#found + 1] = {
                    score_offset = string.format("+0x%X(i32)", off),
                    home_score = hi,
                    away_score = ai,
                }
            end
        end
    end
    return found
end

local function scan_window(base, source_label)
    local hits = {}
    if not is_plausible_ptr(base) then
        return hits
    end

    for off = 0, WINDOW_BYTES - 4, 4 do
        local v = safe_read_int(base + off)
        if v == HOME_TEAM_ID then
            for off2 = 0, WINDOW_BYTES - 4, 4 do
                if off2 ~= off then
                    local v2 = safe_read_int(base + off2)
                    if v2 == AWAY_TEAM_ID then
                        local scores = find_scores_near(base, off, off2)
                        hits[#hits + 1] = {
                            source = source_label,
                            base = base,
                            home_team_offset = string.format("+0x%X", off),
                            away_team_offset = string.format("+0x%X", off2),
                            scores = scores,
                        }
                    end
                end
            end
        end
    end
    return hits
end

local function collect_from_plugin(plugin_name, plugin_id)
    local out = {
        plugin = plugin_name,
        plugin_id = plugin_id,
        pointer = 0,
        hits = {},
        error = nil,
    }

    local ok, ptr = pcall(function() return GetPlugin(plugin_id) end)
    if not ok then
        out.error = tostring(ptr)
        return out
    end
    out.pointer = ptr
    if not is_plausible_ptr(ptr) then
        out.error = "invalid pointer"
        return out
    end

    -- Только плоское окно вокруг самого объекта
    for _, h in ipairs(scan_window(ptr, plugin_name .. "@root")) do
        out.hits[#out.hits + 1] = h
    end

    -- Один безопасный уровень: читаем указатель, но не уходим глубже
    local hops = 0
    for _, hop in ipairs(HOP_OFFSETS) do
        if hops >= MAX_HOP_POINTERS then break end
        local child = safe_read_int(ptr + hop)
        if is_plausible_ptr(child) and child ~= ptr then
            hops = hops + 1
            local label = string.format("%s@ptr%s", plugin_name, string.format("+0x%X", hop))
            for _, h in ipairs(scan_window(child, label)) do
                out.hits[#out.hits + 1] = h
            end
        end
    end

    return out
end

local function aob_scan_team_ids()
    local out = {
        home_pattern = int32_to_aob(HOME_TEAM_ID),
        away_pattern = int32_to_aob(AWAY_TEAM_ID),
        home_hits = {},
        away_hits = {},
    }

    local ok_home, addr_home = pcall(function()
        return MEMORY:AOBScanGameModule(int32_to_aob(HOME_TEAM_ID))
    end)
    if ok_home and addr_home and addr_home ~= 0 then
        out.home_hits[#out.home_hits + 1] = addr_home
        for _, h in ipairs(scan_window(addr_home, "AOB_home")) do
            out.near_home = out.near_home or {}
            out.near_home[#out.near_home + 1] = h
        end
    end

    local ok_away, addr_away = pcall(function()
        return MEMORY:AOBScanGameModule(int32_to_aob(AWAY_TEAM_ID))
    end)
    if ok_away and addr_away and addr_away ~= 0 then
        out.away_hits[#out.away_hits + 1] = addr_away
        for _, h in ipairs(scan_window(addr_away, "AOB_away")) do
            out.near_away = out.near_away or {}
            out.near_away[#out.near_away + 1] = h
        end
    end

    return out
end

local function try_fce_data_manager()
    local out = { attempted = true, fixtures = {}, error = nil }
    local ok, result = pcall(function()
        local iface = GetPlugin(ENUM_djb2IFCEInterface_CLSS)
        if not is_plausible_ptr(iface) then
            return { error = "IFCEInterface pointer invalid" }
        end
        local mgr = MEMORY:ReadMultilevelPointer(iface, { 0x18, 0x10, 0x08, 0x00 })
        if not is_plausible_ptr(mgr) then
            return { error = "FCEDataManager null (expected outside career)" }
        end

        local fixture_list = MEMORY:ReadPointer(mgr + 0x60)
        if not is_plausible_ptr(fixture_list) then
            return { error = "FixtureDataList null" }
        end

        local item_size = 0x18
        local m_begin = MEMORY:ReadPointer(fixture_list + 0x28)
        if not is_plausible_ptr(m_begin) then
            return { error = "fixture mBegin null" }
        end
        local max_items = safe_read_int(fixture_list + 0x1C)
        if not max_items or max_items <= 0 or max_items > 500 then
            return { error = "fixture count out of range" }
        end

        local fixtures = {}
        local limit = math.min(max_items - 1, 30)
        for i = 0, limit do
            local cur = m_begin + item_size * i
            local used = safe_read_char(cur + 0x14)
            if used and used ~= 0 then
                fixtures[#fixtures + 1] = {
                    mHomeScore = safe_read_char(cur + 0x0F),
                    mAwayScore = safe_read_char(cur + 0x11),
                    mGameCompletion = safe_read_char(cur + 0x13),
                    mCompObjId = safe_read_int(cur + 0x08),
                    mHomeStandingId = safe_read_int(cur + 0x0A),
                    mAwayStandingId = safe_read_int(cur + 0x0C),
                }
            end
        end
        return { fixtures = fixtures }
    end)

    if not ok then
        out.error = tostring(result)
        return out
    end
    if result.error then
        out.error = result.error
        return out
    end
    out.fixtures = result.fixtures or {}
    return out
end

local function rank_candidates(all_hits)
    local best = {}
    for _, h in ipairs(all_hits) do
        if h.scores and #h.scores > 0 then
            for _, s in ipairs(h.scores) do
                best[#best + 1] = {
                    source = h.source,
                    base = h.base,
                    home_team_offset = h.home_team_offset,
                    away_team_offset = h.away_team_offset,
                    home_score = s.home_score,
                    away_score = s.away_score,
                    score_offset = s.score_offset,
                }
            end
        end
    end
    return best
end

-- MAIN
ensure_dir(OUT_DIR)

local all_hits = {}

local mj = collect_from_plugin("MatchJournalInterface", ENUM_djb2MatchJournalInterface_CLSS)
for _, h in ipairs(mj.hits) do
    if #all_hits < MAX_CANDIDATES then all_hits[#all_hits + 1] = h end
end

local motm = collect_from_plugin("ManOfTheMatchService", ENUM_djb2ManOfTheMatchService_CLSS)
for _, h in ipairs(motm.hits) do
    if #all_hits < MAX_CANDIDATES then all_hits[#all_hits + 1] = h end
end

local aob = aob_scan_team_ids()
if aob.near_home then
    for _, h in ipairs(aob.near_home) do
        if #all_hits < MAX_CANDIDATES then all_hits[#all_hits + 1] = h end
    end
end
if aob.near_away then
    for _, h in ipairs(aob.near_away) do
        if #all_hits < MAX_CANDIDATES then all_hits[#all_hits + 1] = h end
    end
end

local ranked = rank_candidates(all_hits)

local payload = {
    meta = {
        script = "memory_scan_v4",
        version = SCRIPT_VERSION,
        is_in_career_mode = IsInCM(),
        le_version = LE_VERSION or "unknown",
        home_team_id = HOME_TEAM_ID,
        away_team_id = AWAY_TEAM_ID,
        home_team_name = team_name(HOME_TEAM_ID),
        away_team_name = team_name(AWAY_TEAM_ID),
        expected_score = {
            home = EXPECTED_HOME_SCORE,
            away = EXPECTED_AWAY_SCORE,
        },
        output_dir = OUT_DIR,
    },
    plugins = {
        match_journal = mj,
        motm_service = motm,
    },
    aob_scan = aob,
    fce_data_manager = try_fce_data_manager(),
    hits = all_hits,
    best_candidates = ranked,
}

local json_path = OUT_DIR .. "\\memory_scan_v4.json"
local txt_path = OUT_DIR .. "\\memory_scan_v4_summary.txt"

write_json(json_path, payload)
write_json(OUT_DIR .. "\\last_memory_scan_v4.json", payload)

local f = io.open(txt_path, "w")
if f then
    f:write("=== FC24 Memory Scan " .. SCRIPT_VERSION .. " ===\n")
    f:write(string.format("Match: %s (%d) vs %s (%d)\n",
        payload.meta.home_team_name, HOME_TEAM_ID,
        payload.meta.away_team_name, AWAY_TEAM_ID))
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n")
    f:write("Folder: " .. OUT_DIR .. "\n\n")

    f:write("[Plugins]\n")
    f:write(string.format("  MatchJournal ptr: %s (hits %d)\n",
        tostring(mj.pointer), #mj.hits))
    f:write(string.format("  ManOfTheMatch ptr: %s (hits %d)\n",
        tostring(motm.pointer), #motm.hits))

    f:write("\n[AOB in game module]\n")
    f:write(string.format("  home pattern: %s -> %s\n",
        aob.home_pattern, tostring(aob.home_hits[1] or "not found")))
    f:write(string.format("  away pattern: %s -> %s\n",
        aob.away_pattern, tostring(aob.away_hits[1] or "not found")))

    f:write("\n[FCEDataManager]\n")
    f:write("  " .. tostring(payload.fce_data_manager.error or
        string.format("%d fixtures", #(payload.fce_data_manager.fixtures or {}))) .. "\n")

    f:write("\n[Best score candidates]\n")
    if #ranked == 0 then
        f:write("  NONE — team ids not found near scores in scanned windows\n")
    else
        for i, c in ipairs(ranked) do
            f:write(string.format(
                "  #%d: %d:%d at %s (%s, score %s)\n",
                i, c.home_score, c.away_score, c.source, c.score_offset,
                tostring(c.base)))
        end
    end

    f:write("\nFiles:\n  " .. txt_path .. "\n  " .. json_path .. "\n")
    f:close()
end

local msg = "Memory scan v4 done\n\n" .. OUT_DIR .. "\n\n"
if #ranked > 0 then
    local c = ranked[1]
    msg = msg .. string.format("Best guess: %d:%d\n", c.home_score, c.away_score)
else
    msg = msg .. "No score found in memory\nEdit HOME/AWAY_TEAM_ID in script"
end
MessageBox("Memory Scan v4", msg)
LOGGER:LogInfo("memory_scan_v4 done -> " .. OUT_DIR)
