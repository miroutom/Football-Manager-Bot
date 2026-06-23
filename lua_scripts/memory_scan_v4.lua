-- memory_scan_v4.lua
-- EA FC 24 — безопасный поиск счёта в RAM (quick match / турнир, НЕ карьера)
-- v4.2: hex-дамп, поиск счёта без ID, один уровень указателей (+ ReadBytes)
-- Перед запуском: укажите HOME_TEAM_ID и AWAY_TEAM_ID ниже.
-- Запуск: после матча, на экране результата → Live Editor → Lua Engine → Execute
-- Вывод: %USERPROFILE%\Desktop\fm_bot_probe\memory_scan_v4.*

require 'imports/career_mode/helpers'
require 'imports/other/helpers'
require 'imports/services/enums'

local json = require 'imports/external/json'

-- ============ НАСТРОЙКА ПОД МАТЧ ============
-- FC 24 squad IDs: Liverpool=9, Newcastle United=13
-- Если Ньюкасл дома — поменяйте HOME и AWAY местами
local HOME_TEAM_ID = 9        -- Liverpool / Ливерпуль (дом)
local AWAY_TEAM_ID = 13       -- Newcastle United / Ньюкасл (гости)
-- Если знаете счёт — укажите для фильтра (иначе -1)
local EXPECTED_HOME_SCORE = 3   -- Ливерпуль (дом)
local EXPECTED_AWAY_SCORE = 1   -- Ньюкасл (гости)
-- Второй плагин (может крашить) — включите только если MatchJournal отработал
local SCAN_MOTM = false
-- =============================================

local OUT_DIR = string.format("%s\\Desktop\\fm_bot_probe", os.getenv("USERPROFILE"))
local SCRIPT_VERSION = "v4.2"
local WINDOW_BYTES = 0x200   -- один блок ReadBytes (512 байт)
local HOP_OFFSETS = { 0x8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40 }
local MAX_HOP_READS = 6

local PROGRESS_PATH = OUT_DIR .. "\\memory_scan_v4_progress.txt"
local PARTIAL_JSON_PATH = OUT_DIR .. "\\memory_scan_v4_partial.json"
local JSON_PATH = OUT_DIR .. "\\memory_scan_v4.json"
local TXT_PATH = OUT_DIR .. "\\memory_scan_v4_summary.txt"
local HEX_PATH = OUT_DIR .. "\\memory_scan_v4_hex.txt"

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

local function safe_read_ptr(addr)
    if not is_plausible_ptr(addr) then return nil end
    local ok, v = pcall(function() return MEMORY:ReadPointer(addr) end)
    if ok and is_plausible_ptr(v) then return v end
    ok, v = pcall(function() return MEMORY:ReadInt(addr) end)
    if ok and is_plausible_ptr(v) then return v end
    return nil
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

local function bytes_to_hex_lines(bytes, max_bytes)
    max_bytes = max_bytes or #bytes
    local lines = {}
    local limit = math.min(#bytes, max_bytes)
    for i = 1, limit, 16 do
        local parts = {}
        for j = 0, 15 do
            local b = byte_at(bytes, i + j)
            if b then
                parts[#parts + 1] = string.format("%02X", b)
            end
        end
        lines[#lines + 1] = string.format("%04X: %s", i - 1, table.concat(parts, " "))
    end
    return table.concat(lines, "\n")
end

local function find_team_ids_in_bytes(bytes)
    local home_offsets = {}
    local away_offsets = {}
    local limit = #bytes - 3
    for off = 1, limit, 4 do
        local v = read_int32_le(bytes, off)
        if v == HOME_TEAM_ID then
            home_offsets[#home_offsets + 1] = string.format("+0x%X", off - 1)
        end
        if v == AWAY_TEAM_ID then
            away_offsets[#away_offsets + 1] = string.format("+0x%X", off - 1)
        end
    end
    return {
        home_count = #home_offsets,
        away_count = #away_offsets,
        home_offsets = home_offsets,
        away_offsets = away_offsets,
    }
end

local function find_bare_scores_in_bytes(bytes, source_label, base_addr)
    local found = {}
    for off = 0, #bytes - 2 do
        local h = byte_at(bytes, off + 1)
        local a = byte_at(bytes, off + 2)
        if score_pair_ok(h, a) then
            found[#found + 1] = {
                kind = "u8_pair",
                source = source_label,
                base = base_addr,
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
                    kind = "i32_pair",
                    source = source_label,
                    base = base_addr,
                    score_offset = string.format("+0x%X(i32)", off),
                    home_score = hi,
                    away_score = ai,
                }
            end
        end
    end
    return found
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

local function scan_region(base_addr, label)
    local out = {
        label = label,
        base = base_addr,
        bytes_read = 0,
        error = nil,
        team_ids = {},
        bare_scores = {},
        match_hits = {},
        hex_preview = nil,
    }

    local bytes, err = safe_read_bytes(base_addr, WINDOW_BYTES)
    if not bytes then
        out.error = err or "ReadBytes failed"
        return out, nil
    end

    out.bytes_read = #bytes
    out.team_ids = find_team_ids_in_bytes(bytes)
    out.bare_scores = find_bare_scores_in_bytes(bytes, label, base_addr)
    out.match_hits = scan_bytes_for_match(bytes, label, base_addr)
    out.hex_preview = bytes_to_hex_lines(bytes, 128)
    return out, bytes
end

local function collect_from_plugin(plugin_name, plugin_id, hex_writer)
    local out = {
        plugin = plugin_name,
        plugin_id = plugin_id,
        pointer = 0,
        regions = {},
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

    local root_label = plugin_name .. "@root"
    local root_region, root_bytes = scan_region(ptr, root_label)
    out.regions[#out.regions + 1] = root_region
    if hex_writer and root_bytes then
        hex_writer(root_label, ptr, root_bytes)
    end

    if root_region.error then
        out.error = root_region.error
        return out
    end

    local hop_reads = 0
    for _, hop in ipairs(HOP_OFFSETS) do
        if hop_reads >= MAX_HOP_READS then break end
        local child = safe_read_ptr(ptr + hop)
        if child and child ~= ptr then
            hop_reads = hop_reads + 1
            local hop_label = string.format("%s@ptr+0x%X", plugin_name, hop)
            local hop_region, hop_bytes = scan_region(child, hop_label)
            hop_region.hop_offset = string.format("+0x%X", hop)
            hop_region.child_ptr = child
            out.regions[#out.regions + 1] = hop_region
            if hex_writer and hop_bytes then
                hex_writer(hop_label, child, hop_bytes)
            end
        end
    end

    return out
end

local function flatten_plugin_results(plugin_result)
    local hits = {}
    local bare_scores = {}
    for _, region in ipairs(plugin_result.regions or {}) do
        for _, h in ipairs(region.match_hits or {}) do
            hits[#hits + 1] = h
        end
        for _, s in ipairs(region.bare_scores or {}) do
            bare_scores[#bare_scores + 1] = s
        end
    end
    return hits, bare_scores
end

local function rank_candidates(match_hits, bare_scores)
    local best = {}

    for _, h in ipairs(match_hits) do
        if h.scores and #h.scores > 0 then
            for _, s in ipairs(h.scores) do
                best[#best + 1] = {
                    rank = 1,
                    kind = "team_ids+score",
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

    for _, s in ipairs(bare_scores) do
        best[#best + 1] = {
            rank = 2,
            kind = s.kind or "bare_score",
            source = s.source,
            base = s.base,
            home_score = s.home_score,
            away_score = s.away_score,
            score_offset = s.score_offset,
        }
    end

    table.sort(best, function(a, b)
        if a.rank ~= b.rank then return a.rank < b.rank end
        return tostring(a.source) < tostring(b.source)
    end)

    return best
end

-- MAIN
ensure_dir(OUT_DIR)
write_text(PROGRESS_PATH, "=== memory_scan " .. SCRIPT_VERSION .. " started " .. os.date() .. " ===\n", false)
write_text(HEX_PATH, "=== FC24 Memory Scan hex dump " .. SCRIPT_VERSION .. " ===\n", false)
checkpoint("init ok, no memory touched yet")

local hex_sections = 0
local function append_hex(label, base_addr, bytes)
    hex_sections = hex_sections + 1
    write_text(HEX_PATH, string.format(
        "\n--- [%d] %s @ %s (%d bytes) ---\n%s\n",
        hex_sections, label, tostring(base_addr), #bytes, bytes_to_hex_lines(bytes)
    ), true)
end

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
        max_hop_reads = MAX_HOP_READS,
    },
    plugins = {},
    regions = {},
    hits = {},
    bare_scores = {},
    best_candidates = {},
}
flush_partial(payload, "init")
checkpoint("partial json written (meta only)")

checkpoint("reading MatchJournalInterface (root + pointer hops)")
local mj = collect_from_plugin("MatchJournalInterface", ENUM_djb2MatchJournalInterface_CLSS, append_hex)
payload.plugins.match_journal = mj
payload.regions = mj.regions or {}

local mj_hits, mj_bare = flatten_plugin_results(mj)
for _, h in ipairs(mj_hits) do payload.hits[#payload.hits + 1] = h end
for _, s in ipairs(mj_bare) do payload.bare_scores[#payload.bare_scores + 1] = s end
flush_partial(payload, "match_journal")
checkpoint(string.format("MatchJournal ptr=%s regions=%d hits=%d bare_scores=%d err=%s hex=%s",
    tostring(mj.pointer), #(mj.regions or {}), #mj_hits, #mj_bare,
    tostring(mj.error or "none"), HEX_PATH))

local motm = { skipped = true }
if SCAN_MOTM then
    checkpoint("reading ManOfTheMatchService")
    motm = collect_from_plugin("ManOfTheMatchService", ENUM_djb2ManOfTheMatchService_CLSS, append_hex)
    local motm_hits, motm_bare = flatten_plugin_results(motm)
    for _, h in ipairs(motm_hits) do payload.hits[#payload.hits + 1] = h end
    for _, s in ipairs(motm_bare) do payload.bare_scores[#payload.bare_scores + 1] = s end
    flush_partial(payload, "motm")
    checkpoint(string.format("MOTM ptr=%s regions=%d bare_scores=%d err=%s",
        tostring(motm.pointer), #(motm.regions or {}), #motm_bare, tostring(motm.error or "none")))
end
payload.plugins.motm_service = motm

local ranked = rank_candidates(payload.hits, payload.bare_scores)
payload.best_candidates = ranked
flush_partial(payload, "done")
checkpoint(string.format("finished, best_candidates=%d bare_scores=%d hex_sections=%d",
    #ranked, #payload.bare_scores, hex_sections))

write_json(OUT_DIR .. "\\last_memory_scan_v4.json", payload)

local f = io.open(TXT_PATH, "w")
if f then
    f:write("=== FC24 Memory Scan " .. SCRIPT_VERSION .. " ===\n")
    f:write(string.format("Match: %s (%d) vs %s (%d)\n",
        payload.meta.home_team_name, HOME_TEAM_ID,
        payload.meta.away_team_name, AWAY_TEAM_ID))
    f:write(string.format("Expected score: %s:%s\n",
        EXPECTED_HOME_SCORE >= 0 and tostring(EXPECTED_HOME_SCORE) or "?",
        EXPECTED_AWAY_SCORE >= 0 and tostring(EXPECTED_AWAY_SCORE) or "?"))
    f:write("IsInCM: " .. tostring(payload.meta.is_in_career_mode) .. "\n")
    f:write("Folder: " .. OUT_DIR .. "\n\n")

    f:write("[MatchJournal regions]\n")
    for i, region in ipairs(mj.regions or {}) do
        f:write(string.format("  #%d %s @ %s\n", i, region.label, tostring(region.base)))
        f:write(string.format("      bytes=%s err=%s home_id_hits=%d away_id_hits=%d bare_scores=%d match_hits=%d\n",
            tostring(region.bytes_read), tostring(region.error or "none"),
            (region.team_ids and region.team_ids.home_count) or 0,
            (region.team_ids and region.team_ids.away_count) or 0,
            #(region.bare_scores or {}), #(region.match_hits or {})))
        if region.team_ids and (region.team_ids.home_count > 0 or region.team_ids.away_count > 0) then
            f:write(string.format("      home offsets: %s\n",
                table.concat(region.team_ids.home_offsets or {}, ", ")))
            f:write(string.format("      away offsets: %s\n",
                table.concat(region.team_ids.away_offsets or {}, ", ")))
        end
    end

    if SCAN_MOTM and motm.regions then
        f:write("\n[ManOfTheMatch regions]\n")
        for i, region in ipairs(motm.regions) do
            f:write(string.format("  #%d %s bare_scores=%d\n",
                i, region.label, #(region.bare_scores or {})))
        end
    else
        f:write("\n[ManOfTheMatch] skipped (SCAN_MOTM=false)\n")
    end

    f:write("\n[Bare score hits (no team id required)]\n")
    if #payload.bare_scores == 0 then
        f:write("  NONE\n")
    else
        for i, s in ipairs(payload.bare_scores) do
            f:write(string.format("  #%d: %d:%d at %s %s base %s\n",
                i, s.home_score, s.away_score, s.source, s.score_offset, tostring(s.base)))
        end
    end

    f:write("\n[Best candidates]\n")
    if #ranked == 0 then
        f:write("  NONE — score not found in scanned regions\n")
        f:write("  See hex dump: " .. HEX_PATH .. "\n")
    else
        for i, c in ipairs(ranked) do
            f:write(string.format("  #%d [%s] %d:%d at %s %s\n",
                i, c.kind, c.home_score, c.away_score, c.source,
                c.score_offset or ""))
        end
    end

    f:write("\n[Files]\n  " .. TXT_PATH .. "\n  " .. JSON_PATH .. "\n  " .. HEX_PATH .. "\n")
    f:close()
end

checkpoint("summary txt written")

local msg = "Memory scan " .. SCRIPT_VERSION .. " done\n\n" .. OUT_DIR .. "\n\n"
if #ranked > 0 then
    local c = ranked[1]
    msg = msg .. string.format("Best: %d:%d (%s)\n", c.home_score, c.away_score, c.kind)
elseif mj.error then
    msg = msg .. "MatchJournal read failed:\n" .. mj.error .. "\n"
else
    msg = msg .. string.format("No score found\nRegions: %d\nHex: memory_scan_v4_hex.txt\n",
        #(mj.regions or {}))
end
MessageBox("Memory Scan v4.2", msg)
LOGGER:LogInfo("memory_scan_v4 done -> " .. OUT_DIR)
