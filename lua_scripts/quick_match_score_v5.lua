-- quick_match_score_v5.lua
-- EA FC 24 — чтение счёта quick match / турнир (НЕ карьера)
-- Фиксированная структура: MatchJournalInterface → ptr+0x20 → offsets из v4.3
-- Запуск: экран результата → Live Editor → Lua Engine → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\quick_match_score_v5.json

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

-- Опционально: проверка ID (-1 = не проверять, только прочитать)
local EXPECT_HOME_TEAM_ID = -1
local EXPECT_AWAY_TEAM_ID = -1

-- Offsets внутри блока MatchJournal+0x20 (проверено Liverpool 9 vs Newcastle 13, 3:1)
local MATCH_CHILD_OFFSET = 0x20
local OFF_AWAY_TEAM = 0x0C
local OFF_HOME_TEAM = 0x54
local OFF_AWAY_SCORE = 0x24
local OFF_HOME_SCORE = 0x9C
local READ_SIZE = 0x100

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local JSON_PATH = OUT_DIR .. "\\quick_match_score_v5.json"
local TXT_PATH = OUT_DIR .. "\\quick_match_score_v5.txt"
local SCRIPT_VERSION = "v5"

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

local function safe_read_int(addr)
    if not is_plausible_ptr(addr) then return nil end
    local ok, v = pcall(function() return MEMORY:ReadInt(addr) end)
    if ok then return v end
    return nil
end

local function team_name(team_id)
    local ok, name = pcall(function() return GetTeamName(team_id) end)
    if ok and name and name ~= "" then return name end
    return string.format("team_%d", team_id)
end

local function score_ok(v)
    return v ~= nil and v >= 0 and v <= 15
end

ensure_dir(OUT_DIR)

local result = {
    ok = false,
    meta = {
        script = "quick_match_score_v5",
        version = SCRIPT_VERSION,
        is_in_career_mode = IsInCM(),
        le_version = LE_VERSION or "unknown",
        output_dir = OUT_DIR,
        offsets = {
            match_child = string.format("+0x%X", MATCH_CHILD_OFFSET),
            away_team = string.format("+0x%X", OFF_AWAY_TEAM),
            home_team = string.format("+0x%X", OFF_HOME_TEAM),
            away_score = string.format("+0x%X", OFF_AWAY_SCORE),
            home_score = string.format("+0x%X", OFF_HOME_SCORE),
        },
    },
    match_journal_ptr = 0,
    match_block_ptr = 0,
    home_team_id = 0,
    away_team_id = 0,
    home_team_name = "",
    away_team_name = "",
    home_score = nil,
    away_score = nil,
    validation = {},
    error = nil,
}

local ok_plugin, mj_ptr = pcall(function() return GetPlugin(ENUM_djb2MatchJournalInterface_CLSS) end)
if not ok_plugin or not is_plausible_ptr(mj_ptr) then
    result.error = "MatchJournalInterface pointer invalid"
    write_json(JSON_PATH, result)
    write_json(OUT_DIR .. "\\last_quick_match_score_v5.json", result)
    MessageBox("Quick Match Score v5", "Error:\n" .. result.error)
    return
end

result.match_journal_ptr = mj_ptr

local block_ptr = safe_read_ptr(mj_ptr + MATCH_CHILD_OFFSET)
if not is_plausible_ptr(block_ptr) then
    result.error = string.format("Match block null at journal+0x%X", MATCH_CHILD_OFFSET)
    write_json(JSON_PATH, result)
    write_json(OUT_DIR .. "\\last_quick_match_score_v5.json", result)
    MessageBox("Quick Match Score v5", "Error:\n" .. result.error)
    return
end

result.match_block_ptr = block_ptr

local away_id = safe_read_int(block_ptr + OFF_AWAY_TEAM)
local home_id = safe_read_int(block_ptr + OFF_HOME_TEAM)
local away_score = safe_read_int(block_ptr + OFF_AWAY_SCORE)
local home_score = safe_read_int(block_ptr + OFF_HOME_SCORE)

result.away_team_id = away_id or 0
result.home_team_id = home_id or 0
result.away_score = away_score
result.home_score = home_score
result.home_team_name = team_name(home_id or 0)
result.away_team_name = team_name(away_id or 0)

if not score_ok(home_score) or not score_ok(away_score) then
    result.error = string.format("Invalid scores: home=%s away=%s", tostring(home_score), tostring(away_score))
elseif not home_id or home_id == 0 or not away_id or away_id == 0 then
    result.error = string.format("Invalid team ids: home=%s away=%s", tostring(home_id), tostring(away_id))
else
    result.ok = true
    if EXPECT_HOME_TEAM_ID >= 0 and home_id ~= EXPECT_HOME_TEAM_ID then
        result.validation.home_team_mismatch = {
            expected = EXPECT_HOME_TEAM_ID,
            got = home_id,
        }
    end
    if EXPECT_AWAY_TEAM_ID >= 0 and away_id ~= EXPECT_AWAY_TEAM_ID then
        result.validation.away_team_mismatch = {
            expected = EXPECT_AWAY_TEAM_ID,
            got = away_id,
        }
    end
end

write_json(JSON_PATH, result)
write_json(OUT_DIR .. "\\last_quick_match_score_v5.json", result)

local f = io.open(TXT_PATH, "w")
if f then
    f:write("=== FC24 Quick Match Score " .. SCRIPT_VERSION .. " ===\n")
    f:write("IsInCM: " .. tostring(result.meta.is_in_career_mode) .. "\n")
    f:write(string.format("Journal: %s\n", tostring(mj_ptr)))
    f:write(string.format("Block+0x20: %s\n\n", tostring(block_ptr)))
    if result.ok then
        f:write(string.format("%s (%d) %d : %d %s (%d)\n",
            result.home_team_name, home_id, home_score, away_score,
            result.away_team_name, away_id))
    else
        f:write("ERROR: " .. tostring(result.error) .. "\n")
    end
    f:write("\nJSON: " .. JSON_PATH .. "\n")
    f:close()
end

local msg
if result.ok then
    msg = string.format("%s %d : %d %s\n\n%s",
        result.home_team_name, home_score, away_score, result.away_team_name, OUT_DIR)
    if next(result.validation) then
        msg = msg .. "\nWarning: team id mismatch (check EXPECT_* in script)"
    end
else
    msg = "Failed:\n" .. tostring(result.error) .. "\n\n" .. OUT_DIR
end

MessageBox("Quick Match Score v5", msg)
LOGGER:LogInfo("quick_match_score_v5 -> " .. JSON_PATH)
