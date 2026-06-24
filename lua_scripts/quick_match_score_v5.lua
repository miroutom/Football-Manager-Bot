-- quick_match_score_v5.lua
-- EA FC 24 — АВТО чтение матча из RAM (quick match / турнир, НЕ карьера)
-- v5.1: сканирует блок памяти, ищет любые команды через GetTeamName + счёт рядом
-- Ничего настраивать не нужно (ни ID, ни счёт)
-- Запуск: экран результата → Live Editor → Lua Engine → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\quick_match_score_v5.json

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

local MATCH_CHILD_OFFSET = 0x20
local SCAN_BYTES = 0x400
local SCORE_SEARCH_RADIUS = 0xA0
local IDEAL_TEAM_GAP = 0x48

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local JSON_PATH = OUT_DIR .. "\\quick_match_score_v5.json"
local TXT_PATH = OUT_DIR .. "\\quick_match_score_v5.txt"
local SCRIPT_VERSION = "v5.1"

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

local function is_real_team_name(name)
    if not name or name == "" then return false end
    if name:match("^team_%d+$") then return false end
    local lower = string.lower(name)
    if lower == "not found" or lower == "unknown" then return false end
    return true
end

local function team_name(team_id)
    if not team_id or team_id <= 0 then return nil end
    local ok, name = pcall(function() return GetTeamName(team_id) end)
    if ok and is_real_team_name(name) then return name end
    return nil
end

local function score_ok(v)
    return v ~= nil and v >= 0 and v <= 15
end

local function collect_named_teams(bytes, source_label)
    local by_id = {}
    local limit = #bytes - 3
    for rel = 0, limit - 1, 4 do
        local id = read_int32_le(bytes, rel + 1)
        if id and id > 0 and id < 600000 then
            local name = team_name(id)
            if name then
                if not by_id[id] then
                    by_id[id] = {
                        id = id,
                        name = name,
                        min_offset = rel,
                        offsets = {},
                        source = source_label,
                    }
                end
                by_id[id].offsets[#by_id[id].offsets + 1] = string.format("+0x%X", rel)
                if rel < by_id[id].min_offset then
                    by_id[id].min_offset = rel
                end
            end
        end
    end
    return by_id
end

local function teams_to_sorted_list(by_id)
    local list = {}
    for _, t in pairs(by_id) do
        list[#list + 1] = t
    end
    table.sort(list, function(a, b) return a.min_offset < b.min_offset end)
    return list
end

local function nearest_score(bytes, team_off, skip_off)
    local best_val, best_off, best_dist = nil, nil, SCORE_SEARCH_RADIUS + 1
    for rel = 0, #bytes - 4, 4 do
        if rel ~= team_off and rel ~= skip_off then
            local v = read_int32_le(bytes, rel + 1)
            if score_ok(v) then
                local d = math.abs(rel - team_off)
                if d > 0 and d <= SCORE_SEARCH_RADIUS and d < best_dist then
                    best_dist = d
                    best_val = v
                    best_off = rel
                end
            end
        end
    end
    return best_val, best_off
end

local function pick_team_pair(teams_list)
    if #teams_list < 2 then return nil, nil end
    if #teams_list == 2 then
        local away = teams_list[1]
        local home = teams_list[2]
        return away, home
    end

    local best_away, best_home, best_rank = nil, nil, -999999
    for i = 1, #teams_list do
        for j = i + 1, #teams_list do
            local a, b = teams_list[i], teams_list[j]
            local lo = a.min_offset < b.min_offset and a or b
            local hi = a.min_offset < b.min_offset and b or a
            if lo.min_offset < 0x140 and hi.min_offset < 0x180 then
                local gap = hi.min_offset - lo.min_offset
                local rank = 200 - math.abs(gap - IDEAL_TEAM_GAP)
                rank = rank - lo.min_offset * 0.1
                if rank > best_rank then
                    best_rank = rank
                    best_away = lo
                    best_home = hi
                end
            end
        end
    end
    return best_away, best_home
end

local function scan_region(bytes, source_label)
    local by_id = collect_named_teams(bytes, source_label)
    local teams_list = teams_to_sorted_list(by_id)
    local away_t, home_t = pick_team_pair(teams_list)
    if not away_t or not home_t then
        return {
            source = source_label,
            teams_found = teams_list,
            ok = false,
            error = string.format("need 2+ named teams, found %d", #teams_list),
        }
    end

    local away_score, away_score_off = nearest_score(bytes, away_t.min_offset, home_t.min_offset)
    local home_score, home_score_off = nearest_score(bytes, home_t.min_offset, away_t.min_offset)

    if not score_ok(away_score) or not score_ok(home_score) then
        return {
            source = source_label,
            teams_found = teams_list,
            away_team = away_t,
            home_team = home_t,
            ok = false,
            error = string.format("scores not found near teams (away=%s home=%s)",
                tostring(away_score), tostring(home_score)),
        }
    end

    return {
        source = source_label,
        ok = true,
        teams_found = teams_list,
        away_team_id = away_t.id,
        away_team_name = away_t.name,
        away_team_offset = string.format("+0x%X", away_t.min_offset),
        home_team_id = home_t.id,
        home_team_name = home_t.name,
        home_team_offset = string.format("+0x%X", home_t.min_offset),
        away_score = away_score,
        home_score = home_score,
        away_score_offset = string.format("+0x%X", away_score_off),
        home_score_offset = string.format("+0x%X", home_score_off),
    }
end

local function merge_team_maps(a, b)
    for id, t in pairs(b) do
        if not a[id] then
            a[id] = t
        else
            for _, off in ipairs(t.offsets) do
                a[id].offsets[#a[id].offsets + 1] = off
            end
            if t.min_offset < a[id].min_offset then
                a[id].min_offset = t.min_offset
            end
        end
    end
    return a
end

ensure_dir(OUT_DIR)

local result = {
    ok = false,
    method = "auto_scan",
    meta = {
        script = "quick_match_score_v5",
        version = SCRIPT_VERSION,
        is_in_career_mode = IsInCM(),
        le_version = LE_VERSION or "unknown",
        output_dir = OUT_DIR,
        scan_bytes = SCAN_BYTES,
    },
    match_journal_ptr = 0,
    match_block_ptr = 0,
    home_team_id = 0,
    away_team_id = 0,
    home_team_name = "",
    away_team_name = "",
    home_score = nil,
    away_score = nil,
    teams_found = {},
    scan_regions = {},
    error = nil,
}

local ok_plugin, mj_ptr = pcall(function() return GetPlugin(ENUM_djb2MatchJournalInterface_CLSS) end)
if not ok_plugin or not is_plausible_ptr(mj_ptr) then
    result.error = "MatchJournalInterface pointer invalid"
    write_json(JSON_PATH, result)
    write_json(OUT_DIR .. "\\last_quick_match_score_v5.json", result)
    MessageBox("Quick Match Score v5.1", "Error:\n" .. result.error)
    return
end

result.match_journal_ptr = mj_ptr

local block_ptr = safe_read_ptr(mj_ptr + MATCH_CHILD_OFFSET)
result.match_block_ptr = block_ptr or 0

local block_bytes = is_plausible_ptr(block_ptr) and safe_read_bytes(block_ptr, SCAN_BYTES) or nil
local root_bytes = safe_read_bytes(mj_ptr, SCAN_BYTES)

if block_bytes then
    local scan = scan_region(block_bytes, "match_block+0x20")
    result.scan_regions[#result.scan_regions + 1] = scan
    if scan.ok then
        result.ok = true
        result.away_team_id = scan.away_team_id
        result.home_team_id = scan.home_team_id
        result.away_team_name = scan.away_team_name
        result.home_team_name = scan.home_team_name
        result.away_score = scan.away_score
        result.home_score = scan.home_score
        result.away_team_offset = scan.away_team_offset
        result.home_team_offset = scan.home_team_offset
        result.away_score_offset = scan.away_score_offset
        result.home_score_offset = scan.home_score_offset
        result.teams_found = scan.teams_found
        result.matched_source = scan.source
    end
end

if not result.ok and root_bytes then
    local scan = scan_region(root_bytes, "match_journal_root")
    result.scan_regions[#result.scan_regions + 1] = scan
    if scan.ok then
        result.ok = true
        result.away_team_id = scan.away_team_id
        result.home_team_id = scan.home_team_id
        result.away_team_name = scan.away_team_name
        result.home_team_name = scan.home_team_name
        result.away_score = scan.away_score
        result.home_score = scan.home_score
        result.away_team_offset = scan.away_team_offset
        result.home_team_offset = scan.home_team_offset
        result.away_score_offset = scan.away_score_offset
        result.home_score_offset = scan.home_score_offset
        result.teams_found = scan.teams_found
        result.matched_source = scan.source
    end
end

if not result.ok then
    local all_teams = {}
    if block_bytes then
        all_teams = merge_team_maps(all_teams, collect_named_teams(block_bytes, "block"))
    end
    if root_bytes then
        all_teams = merge_team_maps(all_teams, collect_named_teams(root_bytes, "root"))
    end
    result.teams_found = teams_to_sorted_list(all_teams)
    if #result.teams_found == 0 then
        result.error = "No named teams in RAM — FC did not write this match to MatchJournal"
    elseif #result.teams_found == 1 then
        result.error = string.format("Only 1 team in RAM: %s (%d)",
            result.teams_found[1].name, result.teams_found[1].id)
    else
        result.error = string.format("Found %d teams but could not pair score (see teams_found in JSON)",
            #result.teams_found)
    end
    if result.scan_regions[1] and result.scan_regions[1].error then
        result.error = result.error .. " | " .. result.scan_regions[1].error
    end
end

write_json(JSON_PATH, result)
write_json(OUT_DIR .. "\\last_quick_match_score_v5.json", result)

local f = io.open(TXT_PATH, "w")
if f then
    f:write("=== FC24 Quick Match Score " .. SCRIPT_VERSION .. " (auto) ===\n")
    f:write("IsInCM: " .. tostring(result.meta.is_in_career_mode) .. "\n")
    f:write(string.format("Journal: %s\n", tostring(mj_ptr)))
    f:write(string.format("Block+0x20: %s\n\n", tostring(block_ptr)))
    if result.ok then
        f:write(string.format("%s (%d) %d : %d %s (%d)\n",
            result.home_team_name, result.home_team_id,
            result.home_score, result.away_score,
            result.away_team_name, result.away_team_id))
        f:write(string.format("Source: %s\n", tostring(result.matched_source)))
        f:write(string.format("Offsets: home %s score %s | away %s score %s\n",
            result.home_team_offset or "?", result.home_score_offset or "?",
            result.away_team_offset or "?", result.away_score_offset or "?"))
    else
        f:write("ERROR: " .. tostring(result.error) .. "\n")
        f:write("\nTeams seen in RAM:\n")
        for i, t in ipairs(result.teams_found) do
            f:write(string.format("  #%d %s (%d) at %s\n",
                i, t.name, t.id, table.concat(t.offsets, ", ")))
        end
    end
    f:write("\nJSON: " .. JSON_PATH .. "\n")
    f:close()
end

local msg
if result.ok then
    msg = string.format("[auto] %s (%d) %d : %d %s (%d)\n\n%s",
        result.home_team_name, result.home_team_id,
        result.home_score, result.away_score,
        result.away_team_name, result.away_team_id, OUT_DIR)
else
    msg = "Auto scan failed:\n" .. tostring(result.error) .. "\n\n"
    if #result.teams_found > 0 then
        msg = msg .. "Teams in RAM:\n"
        for i = 1, math.min(4, #result.teams_found) do
            local t = result.teams_found[i]
            msg = msg .. string.format("  %s (%d)\n", t.name, t.id)
        end
    end
    msg = msg .. "\n" .. OUT_DIR
end

MessageBox("Quick Match Score v5.1", msg)
LOGGER:LogInfo("quick_match_score_v5 -> " .. JSON_PATH)
