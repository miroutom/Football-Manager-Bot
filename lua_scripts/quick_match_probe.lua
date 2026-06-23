-- quick_match_probe.lua (v2)
-- EA FC 24 — разведка статы после БЫСТРОГО матча (не карьера)
-- Запуск: Live Editor → Features → Lua Engine → Execute (на экране результата матча)
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local SCRIPT_VERSION = "v2"

-- Приоритетные таблицы из первого прогона + типичные кандидаты
local HOT_TABLES = {
    "career_playermatchratinghistory",
    "fixtures",
    "playofthematchssflink",
    "matchscenarios",
    "MatchIntensity",
    "bigmatchups",
    "career_calendar",
    "career_fixtures",
    "career_playermatchstats",
    "career_matchstats",
    "career_lastmatch",
    "career_playerlastmatch",
    "career_teamlastmatch",
    "career_playermatchrating",
    "matchstats",
    "playermatchstats",
    "matchresults",
    "teams",
    "players",
}

local PLUGIN_IDS = {
    { name = "MatchJournalInterface_CLSS", id = ENUM_djb2MatchJournalInterface_CLSS },
    { name = "ManOfTheMatchService_CLSS",  id = ENUM_djb2ManOfTheMatchService_CLSS },
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
        LOGGER:LogError("JSON encode failed for " .. path .. ": " .. tostring(encoded))
        return false, tostring(encoded)
    end
    local f = io.open(path, "w")
    if not f then return false, "cannot open file" end
    f:write(encoded)
    f:close()
    return true, nil
end

local function sorted_field_names(fields_map)
    local names = {}
    if not fields_map then return names end
    for fname, _ in pairs(fields_map) do
        names[#names + 1] = fname
    end
    table.sort(names)
    return names
end

local function get_table_field_names_v1(table_name)
    local names = {}
    local ok, fields = pcall(function() return GetDBTableFields(table_name) end)
    if not ok or not fields then return names end
    for i = 1, #fields do
        local n = fields[i].name or fields[i]["name"]
        if n then names[#names + 1] = n end
    end
    table.sort(names)
    return names
end

local function dump_table_v2(tbl, field_names, max_rows, tail_rows)
    if not tbl then
        return { exists = false, source = "LE.db" }
    end

    max_rows = max_rows or 20
    tail_rows = tail_rows or false
    local rows = {}

    local ok_first, first = pcall(function() return tbl:GetFirstRecord() end)
    if not ok_first or not first or first <= 0 then
        return {
            exists = true,
            source = "LE.db",
            field_names = field_names,
            row_count = 0,
            rows = rows,
        }
    end

    local buffer = {}
    local count = 0
    local current = first
    while current and current > 0 do
        local row = {}
        for _, fname in ipairs(field_names) do
            local ok_v, val = pcall(function()
                return tbl:GetRecordFieldValue(current, fname)
            end)
            if ok_v and val ~= nil then
                row[fname] = val
            end
        end
        buffer[#buffer + 1] = row
        count = count + 1

        local ok_next, next_rec = pcall(function() return tbl:GetNextValidRecord() end)
        if not ok_next then break end
        current = next_rec
    end

    if tail_rows and count > max_rows then
        local start = count - max_rows + 1
        for i = start, count do
            rows[#rows + 1] = buffer[i]
        end
    else
        for i = 1, math.min(count, max_rows) do
            rows[#rows + 1] = buffer[i]
        end
    end

    return {
        exists = true,
        source = "LE.db",
        field_names = field_names,
        total_rows = count,
        exported_rows = #rows,
        tail_export = tail_rows,
        rows = rows,
    }
end

local function row_to_plain_v1(row)
    local plain = {}
    for field_name, field_obj in pairs(row) do
        if type(field_obj) == "table" and field_obj.value ~= nil then
            plain[field_name] = field_obj.value
        else
            plain[field_name] = field_obj
        end
    end
    return plain
end

local function dump_table_v1(table_name, max_rows, tail_rows)
    local field_names = get_table_field_names_v1(table_name)
    if #field_names == 0 then
        return { exists = false, source = "GetDBTableRows", error = "no fields" }
    end

    local ok, all_rows = pcall(function() return GetDBTableRows(table_name) end)
    if not ok or not all_rows then
        return { exists = false, source = "GetDBTableRows", error = tostring(all_rows) }
    end

    local count = #all_rows
    local rows = {}
    if tail_rows and count > max_rows then
        for i = count - max_rows + 1, count do
            rows[#rows + 1] = row_to_plain_v1(all_rows[i])
        end
    else
        for i = 1, math.min(count, max_rows) do
            rows[#rows + 1] = row_to_plain_v1(all_rows[i])
        end
    end

    return {
        exists = true,
        source = "GetDBTableRows",
        field_names = field_names,
        total_rows = count,
        exported_rows = #rows,
        tail_export = tail_rows,
        rows = rows,
    }
end

local function dump_table(table_name, max_rows, tail_rows)
    local field_names = {}

    local tbl = nil
    local ok_tbl, tbl_res = pcall(function() return LE.db:GetTable(table_name) end)
    if ok_tbl then tbl = tbl_res end

    if tbl and tbl.fields then
        field_names = sorted_field_names(tbl.fields)
        if #field_names > 0 then
            return dump_table_v2(tbl, field_names, max_rows, tail_rows)
        end
    end

    field_names = get_table_field_names_v1(table_name)
    if #field_names > 0 then
        return dump_table_v1(table_name, max_rows, tail_rows)
    end

    return { exists = false, error = "table not found or no fields" }
end

local function dump_hot_tables(max_rows)
    local out = {}
    for _, name in ipairs(HOT_TABLES) do
        out[name] = dump_table(name, max_rows, true)
    end
    return out
end

local function list_match_related_tables()
    local out = safe_call("GetDBTablesNames", function()
        local names = GetDBTablesNames()
        table.sort(names)
        return names
    end)

    local filtered = {}
    if out.ok and type(out.result) == "table" then
        for _, name in ipairs(out.result) do
            local lname = string.lower(name)
            if string.find(lname, "match", 1, true)
                or string.find(lname, "fixture", 1, true)
                or string.find(lname, "result", 1, true)
                or string.find(lname, "rating", 1, true)
            then
                filtered[#filtered + 1] = name
            end
        end
    end

    return {
        all_tables_ok = out.ok,
        all_tables_error = out.error,
        match_related = filtered,
    }
end

local function memory_peek_block(base, bytes)
    local ints = {}
    local floats = {}
    if not base or base == 0 then
        return { base = base, ints = ints, floats = floats, score_candidates = {} }
    end

    local score_candidates = {}
    for off = 0, bytes - 4, 4 do
        local ok_i, iv = pcall(function() return MEMORY:ReadInt(base + off) end)
        if ok_i then
            ints[string.format("+0x%X", off)] = iv
            if iv >= 0 and iv <= 15 and off >= 4 then
                local ok_prev, prev = pcall(function() return MEMORY:ReadInt(base + off - 4) end)
                if ok_prev and prev >= 0 and prev <= 15 and (prev + iv > 0) then
                    score_candidates[#score_candidates + 1] = {
                        offset = string.format("+0x%X", off - 4),
                        home = prev,
                        away = iv,
                    }
                end
            end
        end
        local ok_f, fv = pcall(function() return MEMORY:ReadFloat(base + off) end)
        if ok_f and fv == fv and math.abs(fv) < 1000 then
            if math.abs(fv - math.floor(fv + 0.0001)) > 0.01 or (fv >= 0 and fv <= 10) then
                floats[string.format("+0x%X", off)] = fv
            end
        end
    end

    return {
        base = base,
        ints = ints,
        floats = floats,
        score_candidates = score_candidates,
    }
end

local function memory_deep_probe(base)
    local out = {
        root = memory_peek_block(base, 0x800),
        pointer_hops = {},
    }

    local hop_offsets = { 0x0, 0x8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50, 0x58, 0x60 }
    for _, off in ipairs(hop_offsets) do
        local ok, ptr = pcall(function() return MEMORY:ReadPointer(base + off) end)
        if ok and ptr and ptr ~= 0 and ptr ~= base then
            local key = string.format("ptr_at_+0x%X", off)
            out.pointer_hops[key] = memory_peek_block(ptr, 0x400)
        end
    end

    return out
end

local function probe_plugins()
    local out = {}
    for _, p in ipairs(PLUGIN_IDS) do
        out[p.name] = safe_call("GetPlugin(" .. p.name .. ")", function()
            local ptr = GetPlugin(p.id)
            return {
                plugin_id = p.id,
                pointer = ptr,
                deep = memory_deep_probe(ptr),
            }
        end)
    end
    return out
end

local function collect_players_stats()
    if IsInCM() then
        return safe_call("GetPlayersStats", function()
            local stats = GetPlayersStats()
            return { total = #stats }
        end)
    end
    return { ok = true, skipped = true, reason = "not in career mode" }
end

local function format_row_preview(row)
    if not row then return "" end
    local parts = {}
    local n = 0
    for k, v in pairs(row) do
        n = n + 1
        if n <= 12 then
            parts[#parts + 1] = string.format("%s=%s", k, tostring(v))
        end
    end
    return table.concat(parts, ", ")
end

-- MAIN
ensure_dir(OUT_DIR)

local payload = {
    meta = {
        source = "fc24_quick_match_probe",
        script_version = SCRIPT_VERSION,
        le_version = LE_VERSION or "unknown",
        is_in_career_mode = IsInCM(),
        current_date = safe_call("GetCurrentDate", GetCurrentDate).result,
        output_dir = OUT_DIR,
    },
    basic_api = {
        get_players_stats = collect_players_stats(),
        get_save_uid = IsInCM() and safe_call("GetSaveUID", GetSaveUID) or { ok = false, skipped = true },
        get_user_team_id = IsInCM() and safe_call("GetUserTeamID", GetUserTeamID) or { ok = false, skipped = true },
    },
    table_index = list_match_related_tables(),
    hot_tables = dump_hot_tables(30),
    memory_plugins = probe_plugins(),
}

local paths = {
    json_full = OUT_DIR .. "\\quick_match_probe.json",
    json_hot = OUT_DIR .. "\\quick_match_hot_tables.json",
    json_memory = OUT_DIR .. "\\quick_match_memory.json",
    txt = OUT_DIR .. "\\quick_match_probe_summary.txt",
}

local write_results = {
    full = write_json(paths.json_full, payload),
    hot = write_json(paths.json_hot, payload.hot_tables),
    memory = write_json(paths.json_memory, payload.memory_plugins),
    last = write_json(OUT_DIR .. "\\last_quick_match_probe.json", payload),
}

local f = io.open(paths.txt, "w")
if f then
    f:write("=== FC24 Quick Match Probe " .. SCRIPT_VERSION .. " ===\n")
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n")
    f:write("Output folder:\n  " .. OUT_DIR .. "\n\n")

    f:write("Files written:\n")
    f:write("  " .. paths.txt .. "\n")
    f:write("  " .. paths.json_full .. "\n")
    f:write("  " .. paths.json_hot .. "  (priority tables only)\n")
    f:write("  " .. paths.json_memory .. "  (memory plugins)\n\n")

    f:write("[GetPlayersStats]\n")
    local gs = payload.basic_api.get_players_stats
    if gs.skipped then
        f:write("  skipped (not career mode)\n")
    elseif gs.ok then
        f:write(string.format("  total rows: %s\n", tostring(gs.result and gs.result.total or 0)))
    else
        f:write("  FAILED: " .. tostring(gs.error) .. "\n")
    end

    f:write("\n[Hot tables — last rows exported]\n")
    for _, name in ipairs(HOT_TABLES) do
        local info = payload.hot_tables[name]
        if info and info.exists and (info.total_rows or 0) > 0 then
            f:write(string.format("\n%s (%d total, %d exported)\n", name, info.total_rows, info.exported_rows or 0))
            f:write("  fields: " .. table.concat(info.field_names or {}, ", ") .. "\n")
            local rows = info.rows or {}
            for i = 1, math.min(#rows, 3) do
                f:write("  row: " .. format_row_preview(rows[i]) .. "\n")
            end
        end
    end

    f:write("\n[Memory plugins]\n")
    for name, info in pairs(payload.memory_plugins) do
        if info.ok then
            local ptr = info.result.pointer
            f:write(string.format("  %s -> ptr %s\n", name, tostring(ptr)))
            local root = info.result.deep and info.result.deep.root
            if root and root.score_candidates then
                for _, sc in ipairs(root.score_candidates) do
                    f:write(string.format("    score? %s: %d-%d\n", sc.offset, sc.home, sc.away))
                end
            end
        else
            f:write(string.format("  %s -> FAIL %s\n", name, tostring(info.error)))
        end
    end

    f:write("\n[JSON write status]\n")
    for k, ok in pairs(write_results) do
        if type(ok) == "boolean" then
            f:write(string.format("  %s: %s\n", k, ok and "OK" or "FAILED"))
        end
    end

    f:close()
end

MessageBox(
    "Quick Match Probe " .. SCRIPT_VERSION,
    "Folder:\n" .. OUT_DIR .. "\n\n" ..
    "summary.txt\n" ..
    "quick_match_probe.json\n" ..
    "quick_match_hot_tables.json\n" ..
    "quick_match_memory.json\n\n" ..
    "IsInCM = " .. tostring(IsInCM())
)
LOGGER:LogInfo("Quick match probe " .. SCRIPT_VERSION .. " done -> " .. OUT_DIR)
