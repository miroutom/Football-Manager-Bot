-- memory_scan_v4.lua
-- EA FC 24 — безопасный поиск счёта в RAM (quick match / турнир, НЕ карьера)
-- v4.1: один ReadBytes на плагин, чекпоинты после каждого шага (переживает краш)
-- Перед запуском: укажите HOME_TEAM_ID и AWAY_TEAM_ID ниже.
-- Запуск: после матча, на экране результата → Live Editor → Lua Engine → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\memory_scan_v4.*

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

-- ============ НАСТРОЙКА ПОД МАТЧ ============
-- FC 24 squad IDs: Bayer Leverkusen=32, Hoffenheim=10029
-- Бавария (Bayern) = 5 — не путать с Байером (Leverkusen)
-- Если Хоффенхайм дома — поменяйте HOME и AWAY местами
local HOME_TEAM_ID = 32       -- Bayer Leverkusen / Байер (дом)
local AWAY_TEAM_ID = 10029    -- TSG Hoffenheim / Хоффенхайм (гости)
-- Если знаете счёт — укажите для фильтра (иначе -1)
local EXPECTED_HOME_SCORE = -1
local EXPECTED_AWAY_SCORE = -1
-- Второй плагин (может крашить) — включите только если MatchJournal отработал
local SCAN_MOTM = false
-- =============================================

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local SCRIPT_VERSION = "v4.1"
local WINDOW_BYTES = 0x200   -- один блок ReadBytes (512 байт)

local PROGRESS_PATH = OUT_DIR .. "\\memory_scan_v4_progress.txt"
local PARTIAL_JSON_PATH = OUT_DIR .. "\\memory_scan_v4_partial.json"
local JSON_PATH = OUT_DIR .. "\\memory_scan_v4.json"
local TXT_PATH = OUT_DIR .. "\\memory_scan_v4_summary.txt"

local function ensure_dir(path)
    os.execute(string.format('mkdir "%s" 2>nul', path))
end

local function write_text(path, content, append)
    local mode = append and "a" or "w"
    local f = io.open(path, mode)
    if not f then return false end
    f:write(content)
    f:close()
    return true
end

local function checkpoint(msg)
    write_text(PROGRESS_PATH, os.date("%H:%M:%S") .. " " .. msg .. "\n", true)
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

local function flush_partial(payload, step)
    payload.meta.last_step = step
    payload.meta.updated_at = os.date("%Y-%m-%d %H:%M:%S")
    write_json(PARTIAL_JSON_PATH, payload)
    write_json(JSON_PATH, payload)
end

local function is_plausible_ptr(ptr)
    if not ptr or ptr == 0 then return false end
    if ptr < 0x10000 then return false end
    if ptr > 0x7FFFFFFFFFFF then return false end
    return true
end

local function byte_at(bytes, idx)
    local v = bytes[idx]
    if v == nil then return nil end
    if v < 0 then v = v + 256 end
    return v % 256
end

local function read_int32_le(bytes, idx)
    local b1 = byte_at(bytes, idx)
    local b2 = byte_at(bytes, idx + 1)
    local b3 = byte_at(bytes, idx + 2)
    local b4 = byte_at(bytes, idx + 3)
    if not b1 or not b2 or not b3 or not b4 then return nil end
    return b1 + b2 * 256 + b3 * 65536 + b4 * 16777216
end

local function safe_read_bytes(addr, count)
    if not is_plausible_ptr(addr) then return nil, "invalid pointer" end
    if count <= 0 or count > 0x400 then return nil, "count out of range" end
    local ok, result = pcall(function() return MEMORY:ReadBytes(addr, count) end)
    if not ok then return nil, tostring(result) end
    if type(result) ~= "table" or #result < 4 then return nil, "empty bytes" end
    return result, nil
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

local function find_scores_in_bytes(bytes, rel_home_off, rel_away_off)
    local found = {}
    local scan_start = math.max(0, math.min(rel_home_off, rel_away_off) - 32)
    local scan_end = math.min(#bytes - 2, math.max(rel_home_off, rel_away_off) + 48)

    for off = scan_start, scan_end do
        local h = byte_at(bytes, off + 1)
        local a = byte_at(bytes, off + 2)
        if score_pair_ok(h, a) then
            found[#found + 1] = {
                score_offset = string.format("+0x%X", off),
                home_score = h,
                away_score = a,
            }
        end
        local hi = read_int32_le(bytes, off + 1)
        if hi and hi >= 0 and hi <= 15 then
            local ai = read_int32_le(bytes, off + 5)
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

local function scan_bytes_for_match(bytes, source_label, base_addr)
    local hits = {}
    local limit = #bytes - 3

    for off = 1, limit, 4 do
        local v = read_int32_le(bytes, off)
        if v == HOME_TEAM_ID then
            for off2 = 1, limit, 4 do
                if off2 ~= off then
                    local v2 = read_int32_le(bytes, off2)
                    if v2 == AWAY_TEAM_ID then
                        local rel_home = off - 1
                        local rel_away = off2 - 1
                        local scores = find_scores_in_bytes(bytes, rel_home, rel_away)
                        hits[#hits + 1] = {
                            source = source_label,
                            base = base_addr,
                            home_team_offset = string.format("+0x%X", rel_home),
                            away_team_offset = string.format("+0x%X", rel_away),
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
        bytes_read = 0,
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

    local bytes, err = safe_read_bytes(ptr, WINDOW_BYTES)
    if not bytes then
        out.error = err or "ReadBytes failed"
        return out
    end
    out.bytes_read = #bytes

    out.hits = scan_bytes_for_match(bytes, plugin_name .. "@root", ptr)
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
write_text(PROGRESS_PATH, "=== memory_scan " .. SCRIPT_VERSION .. " started " .. os.date() .. " ===\n", false)
checkpoint("init ok, no memory touched yet")

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
        scan_motm = SCAN_MOTM,
        window_bytes = WINDOW_BYTES,
    },
    plugins = {},
    hits = {},
    best_candidates = {},
}
flush_partial(payload, "init")
checkpoint("partial json written (meta only)")

checkpoint("reading MatchJournalInterface")
local mj = collect_from_plugin("MatchJournalInterface", ENUM_djb2MatchJournalInterface_CLSS)
payload.plugins.match_journal = mj
for _, h in ipairs(mj.hits) do
    payload.hits[#payload.hits + 1] = h
end
flush_partial(payload, "match_journal")
checkpoint(string.format("MatchJournal ptr=%s bytes=%s hits=%d err=%s",
    tostring(mj.pointer), tostring(mj.bytes_read), #mj.hits, tostring(mj.error or "none")))

local motm = { skipped = true }
if SCAN_MOTM then
    checkpoint("reading ManOfTheMatchService")
    motm = collect_from_plugin("ManOfTheMatchService", ENUM_djb2ManOfTheMatchService_CLSS)
    for _, h in ipairs(motm.hits) do
        payload.hits[#payload.hits + 1] = h
    end
    flush_partial(payload, "motm")
    checkpoint(string.format("MOTM ptr=%s bytes=%s hits=%d err=%s",
        tostring(motm.pointer), tostring(motm.bytes_read), #motm.hits, tostring(motm.error or "none")))
end
payload.plugins.motm_service = motm

local ranked = rank_candidates(payload.hits)
payload.best_candidates = ranked
flush_partial(payload, "done")
checkpoint(string.format("finished, best_candidates=%d", #ranked))

write_json(OUT_DIR .. "\\last_memory_scan_v4.json", payload)

local f = io.open(TXT_PATH, "w")
if f then
    f:write("=== FC24 Memory Scan " .. SCRIPT_VERSION .. " ===\n")
    f:write(string.format("Match: %s (%d) vs %s (%d)\n",
        payload.meta.home_team_name, HOME_TEAM_ID,
        payload.meta.away_team_name, AWAY_TEAM_ID))
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n")
    f:write("Folder: " .. OUT_DIR .. "\n\n")

    f:write("[Plugins]\n")
    f:write(string.format("  MatchJournal ptr: %s bytes: %s hits: %d err: %s\n",
        tostring(mj.pointer), tostring(mj.bytes_read), #mj.hits, tostring(mj.error or "none")))
    if SCAN_MOTM then
        f:write(string.format("  ManOfTheMatch ptr: %s bytes: %s hits: %d err: %s\n",
            tostring(motm.pointer), tostring(motm.bytes_read), #motm.hits, tostring(motm.error or "none")))
    else
        f:write("  ManOfTheMatch: skipped (SCAN_MOTM=false)\n")
    end

    f:write("\n[Best score candidates]\n")
    if #ranked == 0 then
        f:write("  NONE — team ids not found near scores in scanned window\n")
        f:write("  Check HOME/AWAY_TEAM_ID or set EXPECTED_HOME/AWAY_SCORE\n")
    else
        for i, c in ipairs(ranked) do
            f:write(string.format(
                "  #%d: %d:%d at %s (%s, base %s)\n",
                i, c.home_score, c.away_score, c.source, c.score_offset,
                tostring(c.base)))
        end
    end

    f:write("\n[Checkpoint log]\n  " .. PROGRESS_PATH .. "\n")
    f:write("\nFiles:\n  " .. TXT_PATH .. "\n  " .. JSON_PATH .. "\n  " .. PARTIAL_JSON_PATH .. "\n")
    f:close()
end

checkpoint("summary txt written")

local msg = "Memory scan " .. SCRIPT_VERSION .. " done\n\n" .. OUT_DIR .. "\n\n"
if #ranked > 0 then
    local c = ranked[1]
    msg = msg .. string.format("Best guess: %d:%d\n", c.home_score, c.away_score)
elseif mj.error then
    msg = msg .. "MatchJournal read failed:\n" .. mj.error .. "\n"
else
    msg = msg .. "No score found in memory\nEdit HOME/AWAY_TEAM_ID in script"
end
if not SCAN_MOTM then
    msg = msg .. "\n\nMOTM scan disabled (safer)"
end
MessageBox("Memory Scan v4.1", msg)
LOGGER:LogInfo("memory_scan_v4 done -> " .. OUT_DIR)
