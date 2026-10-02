-- Apply functions for Mapzilla's scripted terrain nodes.
--
-- Modelled on ::/gui/node_editor/layer_nodes.script, which is how the stock
-- scripted nodes (river_points, random_quads, ...) are implemented. A function
-- gets the node's inputs by key - .value, .point, .pointCloud or .map depending
-- on the declared type - and returns one { typeCode, value } per declared
-- output, in order. Type codes: 1 number, 2 point, 3 point cloud.
--
-- Plain Lua, not Teal: there is no toolchain to type-check against, and a Teal
-- type error would only surface as a failed map generation. Failures here are
-- logged to stdout.txt as a "Lua error" naming this file and the node.

local LOG = "[mapzilla] "

-- Spacing of river points in metres. Stock temperate ends up at 500 (1000m
-- segments, subdivided once).
local STEP = 450

-- The river's course in the layout frame, where u runs from the mountain end
-- of the map (0) to the sea end (1). tools/build.py places the coast around
-- u = 0.8, so the delta opens a little before it.
local SOURCE_AT = 0.05
local DELTA_AT = 0.66
local RIVER_END = 1.03

-- How far the layout quad overhangs the map on every side, as a fraction of
-- the map. Its edges - where a texture wraps and filters badly - then lie
-- outside the map. tools/build.py undoes the same number (LAYOUT_MARGIN).
local LAYOUT_MARGIN = 0.1

-- One river as parallel lists, the way river_map wants them.
local function newRiver()
	return { points = {}, widths = {}, depths = {}, tangents = {}, widthTangents = {} }
end

-- Build a river from a centreline of { x, y, u } points. widthAt(u) is the
-- half-width in metres at that point of the course.
local function fromCentreline(line, widthAt, depth)
	local river = newRiver()
	local n = #line
	for i = 1, n do
		local a = line[math.max(i - 1, 1)]
		local b = line[math.min(i + 1, n)]
		local span = (i > 1 and i < n) and 2 or 1
		local width = widthAt(line[i][3])
		river.points[i] = { line[i][1], line[i][2] }
		-- Hermite tangent: direction of travel, one segment long.
		river.tangents[i] = { (b[1] - a[1]) / span, (b[2] - a[2]) / span }
		-- A little jitter on each bank, so the shores are not ruled lines.
		river.widths[i] = { width * (1 + math.random() * 0.25), width * (1 + math.random() * 0.25) }
		river.widthTangents[i] = { 0, 0 }
		river.depths[i] = { depth, 0 }
	end
	-- Stock closes every river with a pointed tip.
	river.widths[n] = { 0, 0 }
	river.widthTangents[n] = { -1000, -1000 }
	return river
end

-- river_map takes all rivers as one list; stock separates them by repeating
-- the last point of the previous one.
local function join(rivers)
	local all = newRiver()
	for index, river in ipairs(rivers) do
		for key, list in pairs(all) do
			if index > 1 then
				list[#list + 1] = list[#list]
			end
			for _, v in ipairs(river[key]) do
				list[#list + 1] = v
			end
		end
	end
	return all
end

local function smoothstep(t)
	t = math.max(0, math.min(1, t))
	return t * t * (3 - 2 * t)
end

local function riverApplyFn(params, inputs, captureParams)
	local minX, minY = inputs.boundsMin.point.x, inputs.boundsMin.point.y
	local maxX, maxY = inputs.boundsMax.point.x, inputs.boundsMax.point.y
	local sizeX, sizeY = maxX - minX, maxY - minY

	-- The layout frame: u runs from the mountains (0) to the sea (1), v is
	-- the position across. It is turned one of four ways onto the map.
	local turn = math.random(1, 4)
	local function toMap(u, v)
		if turn == 1 then return minX + u * sizeX, minY + v * sizeY end
		if turn == 2 then return maxX - u * sizeX, minY + v * sizeY end
		if turn == 3 then return minX + v * sizeX, minY + u * sizeY end
		return minX + v * sizeX, maxY - u * sizeY
	end
	local length = (turn <= 2) and sizeX or sizeY
	local across = (turn <= 2) and sizeY or sizeX
	local du = STEP / length

	-- The trunk: a slow wander plus a faster one.
	local v0 = 0.35 + math.random() * 0.3
	local p1, p2 = math.random() * 2 * math.pi, math.random() * 2 * math.pi
	local function trunkV(u)
		return v0 + 0.09 * math.sin(2 * math.pi * 0.9 * u + p1)
			+ 0.025 * math.sin(2 * math.pi * 3.7 * u + p2)
	end

	local trunk = {}
	local u = SOURCE_AT
	while u <= RIVER_END do
		local x, y = toMap(u, trunkV(u))
		trunk[#trunk + 1] = { x, y, u }
		u = u + du
	end

	-- The delta: two distributaries leave the trunk and spread away from it
	-- on either side, each with a wander of its own.
	local function distributary(side)
		local line = {}
		local spread = (0.16 + math.random() * 0.08) * side
		local phase = math.random() * 2 * math.pi
		local ub = DELTA_AT
		while ub <= RIVER_END do
			local t = (ub - DELTA_AT) / (1 - DELTA_AT)
			-- Eased, so the branch leaves the trunk at a shallow angle.
			local away = spread * smoothstep(t)
			local wobble = 0.012 * math.sin(2 * math.pi * 2.5 * t + phase) * t
			local x, y = toMap(ub, trunkV(ub) + (away + wobble) * length / across)
			line[#line + 1] = { x, y, ub }
			ub = ub + du
		end
		return line
	end

	-- A stream at the source that grows into a river, and widens again as it
	-- nears the sea.
	local function trunkWidth(uu)
		local grow = 0.2 + 0.8 * smoothstep((uu - SOURCE_AT) / 0.3)
		local mouth = 1 + 0.5 * smoothstep((uu - DELTA_AT) / (1 - DELTA_AT))
		return 75 * grow * mouth
	end
	local function branchWidth(uu)
		return 50
	end

	local rivers = {
		fromCentreline(trunk, trunkWidth, 8),
		fromCentreline(distributary(1), branchWidth, 7),
		fromCentreline(distributary(-1), branchWidth, 7),
	}
	local all = join(rivers)

	-- The layout quad: one textured rectangle over the whole map, two
	-- triangles like the stock random_quads emits. Rasterised with a
	-- left-to-right gradient it becomes a map of u, which is how the node
	-- graph learns which end of the map is which - a script cannot return a
	-- map itself.
	local lo, hi = -LAYOUT_MARGIN, 1 + LAYOUT_MARGIN
	local corners = { { 0, 0 }, { 1, 0 }, { 1, 1 }, { 0, 0 }, { 1, 1 }, { 0, 1 } }
	local vertices, texCoords = {}, {}
	for i, c in ipairs(corners) do
		local x, y = toMap(lo + c[1] * (hi - lo), lo + c[2] * (hi - lo))
		vertices[i] = { x, y }
		texCoords[i] = { c[1], c[2] }
	end

	-- Proof in stdout.txt that our script, not the stock one, laid the river.
	if log and log.message then
		log.message(LOG .. "river node: " .. #trunk .. " trunk points, " .. #all.points
			.. " points in all, frame " .. turn)
	end

	return {
		{ 3, all.points },
		{ 3, all.widths },
		{ 3, all.depths },
		{ 3, all.tangents },
		{ 3, all.widthTangents },
		{ 3, vertices },
		{ 3, texCoords },
	}
end

-- A .script.lua publishes its functions through data(), unlike a .script.tl,
-- which returns the table directly. Without it the engine reports
-- "function data() not defined" for the node and generation fails.
function data()
return {
	river = {
		applyFn = riverApplyFn,
	},
}
end
