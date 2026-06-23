-- quick_match_probe.lua (v3 — safe)
-- EA FC 24 — разведка статы после БЫСТРОГО матча (не карьера)
-- v3: без чтения произвольной памяти, без полного скана больших таблиц
-- Запуск: Live Editor → Lua Engine → Execute (на экране результата матча)

require 'imports/career_mode/helpers'
require 'imports/other/helpers'

local json = require 'imports/external/json'

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local SCRIPT_VERSION = "v3-safe"

-- Небольшие «горячие» таблицы. players/teams убраны — их полный скан вешал игру.
local HOT_TABLES = {
    "career_playermatchratinghistory",
    "playofthematchssflink",
    "matchscenarios",
    "MatchIntensity",
    "career_calendar",
    "career_fixtures",
    "career_playermatchstats",
    "career_matchstats",
    "career_lastmatch",
    "career_playerlastmatch",
    "career_teamlastmatch",
    "career_playermatchrating",
}

local MAX_EXPORT_ROWS = 10      -- сколько строк писать в JSON
local MAX_SCAN_ROWS = 120       -- макс. итераций по таблице (rolling buffer)
local ENABLE_MEMORY_PROBE = false  -- true только если v3-safe стабилен и нужен эксперимент

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
        return false
    end
    local f = io.open(path, "w")
    if not f then return false end
    f:write(encoded)
    f:close()
    return true
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

local function read_row(tbl, record_addr, field_names)
    local row = {}
    for _, fname in ipairs(field_names) do
        local ok_v, val = pcall(function()
            return tbl:GetRecordFieldValue(record_addr, fname)
        end)
        if ok_v and val ~= nil then
            row[fname] = val
        end
    end
    return row
end

local function dump_table_safe(table_name, max_export, max_scan)
    local result = {
        table = table_name,
        exists = false,
        error = nil,
        field_names = {},
        total_rows_scanned = 0,
        truncated = false,
        exported_rows = 0,
        rows = {},
    }

    local ok_all, dump = pcall(function()
        local tbl = LE.db:GetTable(table_name)
        if not tbl then
            return { exists = false, error = "LE.db:GetTable returned nil" }
        end

        local field_names = sorted_field_names(tbl.fields)
        if #field_names == 0 then
            return { exists = true, error = "no fields", field_names = {} }
        end

        local ok_first, first = pcall(function() return tbl:GetFirstRecord() end)
        if not ok_first or not first or first <= 0 then
            return {
                exists = true,
                field_names = field_names,
                total_rows_scanned = 0,
                rows = {},
            }
        end

        -- rolling buffer: держим только последние max_export строк
        local ring = {}
        local count = 0
        local truncated = false
        local current = first

        while current and current > 0 do
            count = count + 1
            if count > max_scan then
                truncated = true
                break
            end

            local row = read_row(tbl, current, field_names)
            ring[#ring + 1] = row
            if #ring > max_export then
                table.remove(ring, 1)
            end

            local ok_next, next_rec = pcall(function() return tbl:GetNextValidRecord() end)
            if not ok_next or not next_rec or next_rec <= 0 then
                break
            end
            current = next_rec
        end

        return {
            exists = true,
            field_names = field_names,
            total_rows_scanned = count,
            truncated = truncated,
            exported_rows = #ring,
            rows = ring,
        }
    end)

    if not ok_all then
        result.error = tostring(dump)
        return result
    end

    for k, v in pairs(dump) do
        result[k] = v
    end
    return result
end

local function dump_hot_tables()
    local out = {}
    for _, name in ipairs(HOT_TABLES) do
        out[name] = safe_call("dump:" .. name, function()
            return dump_table_safe(name, MAX_EXPORT_ROWS, MAX_SCAN_ROWS)
        end)
        -- unwrap safe_call for cleaner JSON
        if out[name].ok then
            out[name] = out[name].result
        else
            out[name] = { exists = false, error = out[name].error }
        end
    end
    return out
end

local function list_match_tables_safe()
    return safe_call("GetDBTablesNames", function()
        local names = GetDBTablesNames()
        table.sort(names)
        local filtered = {}
        for _, name in ipairs(names) do
            local lname = string.lower(name)
            if string.find(lname, "match", 1, true)
                or string.find(lname, "fixture", 1, true)
                or string.find(lname, "rating", 1, true)
            then
                filtered[#filtered + 1] = name
            end
        end
        return { count = #names, match_related = filtered }
    end)
end

local function probe_memory_safe()
    if not ENABLE_MEMORY_PROBE then
        return { skipped = true, reason = "disabled in v3-safe (caused crashes in v2)" }
    end
    return { skipped = true }
end

local function format_row_preview(row)
    if not row then return "" end
    local parts = {}
    local n = 0
    for k, v in pairs(row) do
        n = n + 1
        if n <= 14 then
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
        limits = {
            max_export_rows = MAX_EXPORT_ROWS,
            max_scan_rows = MAX_SCAN_ROWS,
            memory_probe = ENABLE_MEMORY_PROBE,
        },
    },
    table_index = list_match_tables_safe(),
    hot_tables = dump_hot_tables(),
    memory_plugins = probe_memory_safe(),
}

local paths = {
    json_full = OUT_DIR .. "\\quick_match_probe.json",
    json_hot = OUT_DIR .. "\\quick_match_hot_tables.json",
    txt = OUT_DIR .. "\\quick_match_probe_summary.txt",
}

write_json(paths.json_full, payload)
write_json(paths.json_hot, payload.hot_tables)
write_json(OUT_DIR .. "\\last_quick_match_probe.json", payload)

local f = io.open(paths.txt, "w")
if f then
    f:write("=== FC24 Quick Match Probe " .. SCRIPT_VERSION .. " ===\n")
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n")
    f:write("NOTE: v3-safe — memory probe OFF, big tables skipped\n")
    f:write("Folder: " .. OUT_DIR .. "\n\n")

    f:write("Files:\n")
    f:write("  " .. paths.txt .. "\n")
    f:write("  " .. paths.json_full .. "\n")
    f:write("  " .. paths.json_hot .. "\n\n")

    f:write("[Hot tables]\n")
    for _, name in ipairs(HOT_TABLES) do
        local info = payload.hot_tables[name]
        if info and info.exists and (info.exported_rows or 0) > 0 then
            f:write(string.format("\n%s (scanned %d", name, info.total_rows_scanned or 0))
            if info.truncated then f:write(", truncated") end
            f:write(string.format(", exported %d)\n", info.exported_rows or 0))
            f:write("  fields: " .. table.concat(info.field_names or {}, ", ") .. "\n")
            for i, row in ipairs(info.rows or {}) do
                f:write(string.format("  [%d] %s\n", i, format_row_preview(row)))
            end
        elseif info and info.exists then
            f:write(string.format("\n%s (empty)\n", name))
        elseif info and info.error then
            f:write(string.format("\n%s ERROR: %s\n", name, tostring(info.error)))
        end
    end

    if payload.table_index.ok then
        f:write("\n[Match-related table names in DB]\n")
        for _, n in ipairs(payload.table_index.result.match_related or {}) do
            f:write("  " .. n .. "\n")
        end
    end

    f:close()
end

MessageBox(
    "Quick Match Probe " .. SCRIPT_VERSION,
    "Saved (safe mode):\n" .. OUT_DIR .. "\n\n" ..
    "summary.txt\nquick_match_probe.json\n\n" ..
    "IsInCM = " .. tostring(IsInCM())
)
LOGGER:LogInfo("Quick match probe " .. SCRIPT_VERSION .. " done")
