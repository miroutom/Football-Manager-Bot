-- quick_match_probe.lua
-- EA FC 24 — разведка статы после БЫСТРОГО матча (не карьера)
-- Запуск: Live Editor → Features → Lua Engine → Execute (на экране результата матча)

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))

local GUESS_TABLES = {
    "teams", "teamplayerlinks", "players", "leagues", "leagueteamlinks",
    "career_users", "career_calendar", "career_fixtures", "career_standings",
    "career_playerstats", "career_teamstats", "career_playermatchstats",
    "career_matchstats", "career_lastmatch", "career_playerlastmatch",
    "career_teamlastmatch", "career_matchrating", "career_playermatchrating",
    "matchstats", "playermatchstats", "fixture", "fixtures", "matchresults",
}

local PLUGIN_IDS = {
    { name = "MatchJournalInterface_CLSS", id = ENUM_djb2MatchJournalInterface_CLSS },
    { name = "MatchJournalInterface_IF",   id = ENUM_djb2MatchJournalInterface_INTERFACE },
    { name = "ManOfTheMatchService_CLSS",  id = ENUM_djb2ManOfTheMatchService_CLSS },
    { name = "ManOfTheMatchService_IF",    id = ENUM_djb2ManOfTheMatchService_INTERFACE },
}

local function ensure_dir(path)
    os.execute(string.format('mkdir "%s" 2>nul', path))
end

local function safe_call(label, fn)
    local ok, res = pcall(fn)
    return {
        ok = ok,
        label = label,
        result = ok and res or nil,
        error = ok and nil or tostring(res),
    }
end

local function write_json(path, data)
    local ok, encoded = pcall(function() return json.encode(data) end)
    if not ok then
        LOGGER:LogError("JSON encode failed: " .. tostring(encoded))
        return false
    end
    local f = io.open(path, "w")
    if not f then return false end
    f:write(encoded)
    f:close()
    return true
end

local function dump_table_rows(tbl, max_rows)
    if not tbl then return { exists = false } end

    local fields = {}
    if tbl.GetFields then
        local ok, f = pcall(function() return tbl:GetFields() end)
        if ok and f then
            for i = 1, #f do
                table.insert(fields, f[i].name or f[i]["name"] or tostring(f[i]))
            end
        end
    end

    local rows = {}
    local count = 0
    local ok, first = pcall(function() return tbl:GetFirstRecord() end)
    if not ok or not first or first <= 0 then
        return { exists = true, row_count = 0, fields = fields, rows = rows }
    end

    local current = first
    while current and current > 0 and count < max_rows do
        local row = {}
        if #fields == 0 then
            for _, fname in ipairs({
                "teamid", "playerid", "teamname", "overallrating", "potential",
                "homegoals", "awaygoals", "homescore", "awayscore", "score",
                "rating", "goals", "assists", "fixtureid", "matchid",
                "hometeamid", "awayteamid", "compobjid", "day", "month", "year",
            }) do
                local ok2, val = pcall(function()
                    return tbl:GetRecordFieldValue(current, fname)
                end)
                if ok2 and val ~= nil then row[fname] = val end
            end
        else
            for _, fname in ipairs(fields) do
                local ok2, val = pcall(function()
                    return tbl:GetRecordFieldValue(current, fname)
                end)
                if ok2 then row[fname] = val end
            end
        end
        table.insert(rows, row)
        count = count + 1
        local ok3, next_rec = pcall(function() return tbl:GetNextValidRecord() end)
        if not ok3 then break end
        current = next_rec
    end

    return { exists = true, row_count = count, fields = fields, rows = rows }
end

local function probe_db_tables(max_rows)
    local out = { via_get_db_table_names = nil, tables = {} }

    out.via_get_db_table_names = safe_call("GetDBTablesNames", function()
        local names = GetDBTablesNames()
        table.sort(names)
        return names
    end)

    local names_to_try = {}
    local seen = {}

    if out.via_get_db_table_names.ok and type(out.via_get_db_table_names.result) == "table" then
        for _, n in ipairs(out.via_get_db_table_names.result) do
            if not seen[n] then names_to_try[#names_to_try + 1] = n; seen[n] = true end
        end
    end
    for _, n in ipairs(GUESS_TABLES) do
        if not seen[n] then names_to_try[#names_to_try + 1] = n; seen[n] = true end
    end

    for _, name in ipairs(names_to_try) do
        local lname = string.lower(name)
        if string.find(lname, "match", 1, true)
            or string.find(lname, "fixture", 1, true)
            or string.find(lname, "result", 1, true)
            or string.find(lname, "career", 1, true)
            or name == "teams"
            or name == "players"
        then
            local entry = safe_call("LE.db:GetTable(" .. name .. ")", function()
                local tbl = LE.db:GetTable(name)
                return dump_table_rows(tbl, max_rows)
            end)
            if entry.ok and entry.result and entry.result.exists and entry.result.row_count > 0 then
                out.tables[name] = entry.result
            elseif entry.ok and entry.result and entry.result.exists then
                out.tables[name] = { exists = true, row_count = 0 }
            end
        end
    end

    return out
end

local function memory_peek(base, bytes)
    local ints = {}
    local floats = {}
    if not base or base == 0 then return { base = base, ints = ints, floats = floats } end

    for off = 0, bytes - 4, 4 do
        local ok_i, iv = pcall(function() return MEMORY:ReadInt(base + off) end)
        if ok_i then ints[string.format("+0x%X", off)] = iv end
        local ok_f, fv = pcall(function() return MEMORY:ReadFloat(base + off) end)
        if ok_f and fv == fv and math.abs(fv) < 100000 then
            floats[string.format("+0x%X", off)] = fv
        end
    end
    return { base = base, ints = ints, floats = floats }
end

local function probe_plugins()
    local out = {}
    for _, p in ipairs(PLUGIN_IDS) do
        local entry = safe_call("GetPlugin(" .. p.name .. ")", function()
            local ptr = GetPlugin(p.id)
            return {
                plugin_id = p.id,
                pointer = ptr,
                peek = memory_peek(ptr, 0x200),
            }
        end)
        out[p.name] = entry
    end
    return out
end

local function collect_players_stats()
    return safe_call("GetPlayersStats", function()
        local stats = GetPlayersStats()
        local out = {}
        for i = 1, math.min(#stats, 500) do
            local s = stats[i]
            out[#out + 1] = {
                playerid = s.playerid,
                playername = safe_call("GetPlayerName", function()
                    return GetPlayerName(s.playerid)
                end).result,
                teamid = s.teamid,
                teamname = safe_call("GetTeamName", function()
                    return GetTeamName(s.teamid)
                end).result,
                app = s.app,
                goals = s.goals,
                assists = s.assists,
                avg_raw = s.avg,
                yellow = s.yellow,
                red = s.red,
            }
        end
        return { total = #stats, exported = #out, rows = out }
    end)
end

ensure_dir(OUT_DIR)

local payload = {
    meta = {
        source = "fc24_quick_match_probe",
        le_version = LE_VERSION or "unknown",
        is_in_career_mode = IsInCM(),
        current_date = safe_call("GetCurrentDate", GetCurrentDate).result,
        note = "Quick Match probe — most career APIs expected empty/fail",
    },
    basic_api = {
        get_players_stats = collect_players_stats(),
        get_save_uid = safe_call("GetSaveUID", GetSaveUID),
        get_user_team_id = safe_call("GetUserTeamID", GetUserTeamID),
    },
    db_probe = probe_db_tables(50),
    memory_plugins = probe_plugins(),
}

local out_json = OUT_DIR .. "\\quick_match_probe.json"
local out_txt  = OUT_DIR .. "\\quick_match_probe_summary.txt"

write_json(out_json, payload)
write_json(OUT_DIR .. "\\last_quick_match_probe.json", payload)

local f = io.open(out_txt, "w")
if f then
    f:write("=== FC24 Quick Match Probe ===\n")
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n\n")

    f:write("[GetPlayersStats]\n")
    local gs = payload.basic_api.get_players_stats
    if gs.ok then
        f:write(string.format("  total rows: %d\n", gs.result.total or 0))
    else
        f:write("  FAILED: " .. tostring(gs.error) .. "\n")
    end

    f:write("\n[DB tables with data]\n")
    for name, info in pairs(payload.db_probe.tables) do
        if info.row_count and info.row_count > 0 then
            f:write(string.format("  %s -> %d rows\n", name, info.row_count))
        end
    end

    f:write("\n[Plugins]\n")
    for name, info in pairs(payload.memory_plugins) do
        if info.ok then
            f:write(string.format("  %s -> ptr %s\n", name, tostring(info.result.pointer)))
        else
            f:write(string.format("  %s -> FAIL %s\n", name, tostring(info.error)))
        end
    end
    f:close()
end

MessageBox(
    "Quick Match Probe",
    "Saved to Desktop\\fm_bot_probe\\\n\n" ..
    "IsInCM = " .. tostring(IsInCM()) .. "\n" ..
    "Open quick_match_probe_summary.txt"
)
LOGGER:LogInfo("Quick match probe done")
