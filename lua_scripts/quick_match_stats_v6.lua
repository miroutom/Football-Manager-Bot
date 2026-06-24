-- quick_match_stats_v6.lua
-- EA FC 24 — счёт + командная стата quick match по ID команд
-- Задайте HOME/AWAY team id (позже можно подгружать из календаря бота)
-- Якорь: ищет HOME_TEAM_ID в MatchJournal root, читает статы по offset'ам
-- Калибровка: MU (11) vs City (12) — удары away +0x58, home +0x60 от якоря home id
-- Запуск: экран счёта ИЛИ экран статы → Live Editor → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\quick_match_stats_v6.json

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

-- ============ МАТЧ (задайте squad ID FC 24) ============
local HOME_TEAM_ID = 11       -- Manchester United
local AWAY_TEAM_ID = 10       -- Manchester City
-- Опционально: проверка ( -1 = не проверять )
local EXPECTED_HOME_SCORE = -1
local EXPECTED_AWAY_SCORE = -1
local EXPECTED_HOME_SHOTS = 14  -- с экрана статы MU; -1 если не знаете
local EXPECTED_AWAY_SHOTS = 12  -- City
-- =======================================================

local MATCH_CHILD_OFFSET = 0x20
local SCAN_BYTES = 0x400
local PAIR_MAX_DISTANCE = 0x120

-- От якоря (первое вхождение HOME_TEAM_ID в journal root)
local OFF_AWAY_SHOTS = 0x58
local OFF_HOME_SHOTS = 0x60

-- Счёт (если оба id в match_block+0x20, как Liverpool–Newcastle)
local OFF_AWAY_TEAM = 0x0C
local OFF_HOME_TEAM = 0x54
local OFF_AWAY_SCORE = 0x24
local OFF_HOME_SCORE = 0x9C

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local JSON_PATH = OUT_DIR .. "\\quick_match_stats_v6.json"
local TXT_PATH = OUT_DIR .. "\\quick_match_stats_v6.txt"
local HEX_PATH = OUT_DIR .. "\\quick_match_stats_v6_hex.txt"
local SCRIPT_VERSION = "v6"

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

local function write_json(path, data)
    local ok, encoded = pcall(function() return json.encode(data) end)
    if not ok then return false end
    local f = io.open(path, "w")
    if not f then return false end
    f:write(encoded)
    f:close()
    return true
end

local function is_plausible_ptr(ptr)
    if not ptr or ptr == 0 then return false end
    if ptr == 0xFFFFFFFF or ptr == 4294967295 then return false end
    if ptr < 0x10000 then return false end
    if ptr > 0x7FFFFFFFFFFF then return false end
    return true
end

local function safe_read_ptr(addr)
    if not is_plausible_ptr(addr) then return nil end
    local ok, v = pcall(function() return MEMORY:ReadPointer(addr) end)
    if ok and is_plausible_ptr(v) then return v end
    ok, v = pcall(function() return MEMORY:ReadInt(addr) end)
    if ok and is_plausible_ptr(v) then return v end
    return nil
end

local function safe_read_bytes(addr, count)
    if not is_plausible_ptr(addr) then return nil end
    local ok, result = pcall(function() return MEMORY:ReadBytes(addr, count) end)
    if ok and type(result) == "table" and #result >= 4 then return result end
    return nil
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

local function read_int32_addr(addr)
    local ok, v = pcall(function() return MEMORY:ReadInt(addr) end)
    if ok then return v end
    return nil
end

local function team_name(team_id)
    if not team_id or team_id <= 0 then return nil end
    local ok, name = pcall(function() return GetTeamName(team_id) end)
    if ok and name and name ~= "" then
        local lower = string.lower(name)
        if lower ~= "not found" and lower ~= "unknown" then return name end
    end
    return string.format("team_%d", team_id)
end

local function find_id_offsets(bytes, team_id)
    local offs = {}
    for rel = 0, #bytes - 4, 4 do
        if read_int32_le(bytes, rel + 1) == team_id then
            offs[#offs + 1] = rel
        end
    end
    return offs
end

local function find_pair_anchor(bytes, home_id, away_id)
    local home_offs = find_id_offsets(bytes, home_id)
    local away_offs = find_id_offsets(bytes, away_id)
    local best = nil
    for _, ho in ipairs(home_offs) do
        for _, ao in ipairs(away_offs) do
            local dist = math.abs(ho - ao)
            if dist > 0 and dist <= PAIR_MAX_DISTANCE then
                if not best or dist < best.distance then
                    best = {
                        home_offset = ho,
                        away_offset = ao,
                        distance = dist,
                    }
                end
            end
        end
    end
    return best, home_offs, away_offs
end

local function discovery_table(bytes, anchor, span)
    local out = {}
    local start_rel = math.max(0, anchor)
    local end_rel = math.min(#bytes - 4, anchor + span)
    for rel = start_rel, end_rel, 4 do
        local v = read_int32_le(bytes, rel + 1)
        if v ~= nil then
            out[#out + 1] = {
                offset = string.format("+0x%X", rel),
                rel = rel,
                value = v,
            }
        end
    end
    return out
end

local function bytes_to_hex_lines(bytes, max_bytes)
    max_bytes = max_bytes or #bytes
    local lines = {}
    local limit = math.min(#bytes, max_bytes)
    for i = 1, limit, 16 do
        local parts = {}
        for j = 0, 15 do
            local b = byte_at(bytes, i + j)
            if b then parts[#parts + 1] = string.format("%02X", b) end
        end
        lines[#lines + 1] = string.format("%04X: %s", i - 1, table.concat(parts, " "))
    end
    return table.concat(lines, "\n")
end

local function score_ok(v)
    return v ~= nil and v >= 0 and v <= 15
end

local function shots_ok(v)
    return v ~= nil and v >= 0 and v <= 60
end

ensure_dir(OUT_DIR)

local result = {
    ok = false,
    meta = {
        script = "quick_match_stats_v6",
        version = SCRIPT_VERSION,
        is_in_career_mode = IsInCM(),
        le_version = LE_VERSION or "unknown",
        home_team_id = HOME_TEAM_ID,
        away_team_id = AWAY_TEAM_ID,
        home_team_name = team_name(HOME_TEAM_ID),
        away_team_name = team_name(AWAY_TEAM_ID),
        output_dir = OUT_DIR,
    },
    match_journal_ptr = 0,
    match_block_ptr = 0,
    anchor = nil,
    score = {},
    stats = {},
    discovery = {},
    regions = {},
    error = nil,
}

local ok_plugin, mj_ptr = pcall(function() return GetPlugin(ENUM_djb2MatchJournalInterface_CLSS) end)
if not ok_plugin or not is_plausible_ptr(mj_ptr) then
    result.error = "MatchJournalInterface pointer invalid"
    write_json(JSON_PATH, result)
    MessageBox("Match Stats v6", "Error:\n" .. result.error)
    return
end

result.match_journal_ptr = mj_ptr

local block_ptr = safe_read_ptr(mj_ptr + MATCH_CHILD_OFFSET)
result.match_block_ptr = block_ptr or 0

local root_bytes = safe_read_bytes(mj_ptr, SCAN_BYTES)
local block_bytes = is_plausible_ptr(block_ptr) and safe_read_bytes(block_ptr, SCAN_BYTES) or nil

if root_bytes then
    local pair, home_offs, away_offs = find_pair_anchor(root_bytes, HOME_TEAM_ID, AWAY_TEAM_ID)
    result.regions.journal_root = {
        home_id_hits = home_offs,
        away_id_hits = away_offs,
        pair = pair,
    }

    local anchor = nil
    local anchor_source = nil

    if pair then
        anchor = pair.home_offset
        anchor_source = "journal_root_pair"
    elseif home_offs[1] then
        anchor = home_offs[1]
        anchor_source = "journal_root_home_id"
    elseif away_offs[1] then
        anchor = away_offs[1]
        anchor_source = "journal_root_away_id"
    end

    if anchor then
        result.anchor = {
            source = anchor_source,
            region = "journal_root",
            base = mj_ptr,
            team_offset = string.format("+0x%X", anchor),
            rel = anchor,
        }

        local away_shots = read_int32_le(root_bytes, anchor + OFF_AWAY_SHOTS + 1)
        local home_shots = read_int32_le(root_bytes, anchor + OFF_HOME_SHOTS + 1)

        result.stats.shots = {
            home = home_shots,
            away = away_shots,
            home_offset = string.format("+0x%X", anchor + OFF_HOME_SHOTS),
            away_offset = string.format("+0x%X", anchor + OFF_AWAY_SHOTS),
            source = "calibrated_from_anchor",
        }

        result.discovery = discovery_table(root_bytes, math.max(0, anchor - 0x10), 0xD0)

        write_text(HEX_PATH, string.format(
            "=== anchor @ journal_root %s (home id %d) ===\n%s\n",
            result.anchor.team_offset, HOME_TEAM_ID,
            bytes_to_hex_lines(root_bytes, math.min(#root_bytes, anchor + 0xE0))
        ), false)
    end
end

if block_bytes then
    local pair, home_offs, away_offs = find_pair_anchor(block_bytes, HOME_TEAM_ID, AWAY_TEAM_ID)
    result.regions.match_block = {
        home_id_hits = home_offs,
        away_id_hits = away_offs,
        pair = pair,
    }

    if pair then
        local bp = block_ptr
        local away_id = read_int32_addr(bp + pair.away_offset)
        local home_id = read_int32_addr(bp + pair.home_offset)
        if away_id == AWAY_TEAM_ID and home_id == HOME_TEAM_ID then
            result.score = {
                home = read_int32_addr(bp + OFF_HOME_SCORE),
                away = read_int32_addr(bp + OFF_AWAY_SCORE),
                home_offset = string.format("+0x%X", OFF_HOME_SCORE),
                away_offset = string.format("+0x%X", OFF_AWAY_SCORE),
                source = "match_block+0x20",
            }
        end
    end
end

local has_score = score_ok(result.score.home) and score_ok(result.score.away)
local has_shots = shots_ok(result.stats.shots and result.stats.shots.home)
    and shots_ok(result.stats.shots and result.stats.shots.away)

if has_score or has_shots then
    result.ok = true
else
    result.error = string.format(
        "No stats found for ids %d vs %d (home hits root=%s block=%s, away hits root=%s block=%s)",
        HOME_TEAM_ID, AWAY_TEAM_ID,
        tostring(result.regions.journal_root and #result.regions.journal_root.home_id_hits or 0),
        tostring(result.regions.match_block and #result.regions.match_block.home_id_hits or 0),
        tostring(result.regions.journal_root and #result.regions.journal_root.away_id_hits or 0),
        tostring(result.regions.match_block and #result.regions.match_block.away_id_hits or 0))
end

if result.ok and EXPECTED_HOME_SHOTS >= 0 then
    result.validation = result.validation or {}
    if result.stats.shots and result.stats.shots.home ~= EXPECTED_HOME_SHOTS then
        result.validation.home_shots_mismatch = {
            expected = EXPECTED_HOME_SHOTS, got = result.stats.shots.home }
    end
    if result.stats.shots and result.stats.shots.away ~= EXPECTED_AWAY_SHOTS then
        result.validation.away_shots_mismatch = {
            expected = EXPECTED_AWAY_SHOTS, got = result.stats.shots.away }
    end
end

write_json(JSON_PATH, result)
write_json(OUT_DIR .. "\\last_quick_match_stats_v6.json", result)

local f = io.open(TXT_PATH, "w")
if f then
    f:write("=== FC24 Match Stats " .. SCRIPT_VERSION .. " ===\n")
    f:write(string.format("%s (%d) vs %s (%d)\n",
        result.meta.home_team_name, HOME_TEAM_ID,
        result.meta.away_team_name, AWAY_TEAM_ID))
    if result.score.home then
        f:write(string.format("Score: %d : %d (%s)\n",
            result.score.home, result.score.away, result.score.source or "?"))
    end
    if result.stats.shots then
        f:write(string.format("Shots: %d : %d (anchor %s)\n",
            result.stats.shots.home, result.stats.shots.away,
            result.anchor and result.anchor.team_offset or "?"))
    end
    if result.error and not result.ok then
        f:write("ERROR: " .. result.error .. "\n")
    end
    f:write("\nDiscovery (int32 near anchor):\n")
    for i, row in ipairs(result.discovery) do
        if i <= 40 then
            f:write(string.format("  %s = %d\n", row.offset, row.value))
        end
    end
    f:write("\nJSON: " .. JSON_PATH .. "\n")
    f:write("HEX: " .. HEX_PATH .. "\n")
    f:close()
end

local msg = "Match Stats v6\n\n"
if result.ok then
    if has_score then
        msg = msg .. string.format("Score: %d:%d\n", result.score.home, result.score.away)
    end
    if has_shots then
        msg = msg .. string.format("Shots: %d:%d\n",
            result.stats.shots.home, result.stats.shots.away)
    end
    msg = msg .. "\n" .. OUT_DIR
else
    msg = msg .. tostring(result.error) .. "\n\n" .. OUT_DIR
end

MessageBox("Match Stats v6", msg)
LOGGER:LogInfo("quick_match_stats_v6 -> " .. JSON_PATH)
