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
--
-- tools/run_river.js runs this file outside the game and tools/preview_river.py
-- draws the result, so the layout can be judged without a restart.

local LOG = "[mapzilla] "

-- Lua 5.1 / LuaJIT has math.atan2; newer Luas fold it into math.atan.
local atan2 = math.atan2 or math.atan

-- Spacing of the points a river's course is planned on, in metres. Stock
-- temperate ends up at 500 (1000m segments, subdivided once).
local STEP = 450
-- Each planned segment is cut into this many pieces before the meanders are
-- put in, so there are enough points to bend: 150m apart.
local SUBDIVISIONS = 3

-- The river's course in the river frame, where u runs from where the land is
-- highest (0) to past where the water is (1). tools/build.py places the coast
-- at COAST, so the delta opens a little before it.
local SOURCE_AT = 0.05
local DELTA_AT = 0.66
local RIVER_END = 1.03
-- On a radial layout the end of the frame is a point, not a line: a river that
-- reaches it off to one side is still short of the middle, by as much as it
-- stands to the side. So those run on a little further, or the last of a mouth
-- can be left on the landward side of a coast that has wandered outwards.
local RADIAL_END_EXTRA = 0.06
local COAST = 0.80          -- must match RIVER_TO_SEA["coast"] in tools/build.py

-- How far the layout quad overhangs the map on every side, as a fraction of
-- the map. Its edges - where a texture wraps and filters badly - then lie
-- outside the map. tools/build.py bakes the same overhang into every tile of
-- the layout atlas (LAYOUT_MARGIN).
local LAYOUT_MARGIN = 0.1

-- Where the mountains and the sea are. The node graph cannot be told: a script
-- returns points, never a map. So it is told in a picture instead - the quad
-- below, rasterised with one tile of tex/layouts.tga, which gives the graph a
-- map of u, 0 deep in the mountains and 1 out at sea. tools/build.py bakes the
-- tiles from this very table and refuses to build if its copy and this one
-- have drifted apart, so there is one set of numbers, written twice.
--
--   kind    how u measures distance in the map frame, where `a` runs along the
--           map's longer side and `b` across it, both 0..1:
--           "along"  `a` itself - mountains at one end, sea at the other
--           "across" |2b - 1|, the distance from the map's centre line: a
--                    fold, with the same land mirrored on both sides
--           "radial" the distance from the centre of the map, 1 at the middle
--                    of an edge
--   d0, d1  the distances at which u is 0 and 1. The river runs between them
--           along the map's centre line, so these fix the frame it is laid out
--           in: how long it is, which way it points, and where it starts. A
--           distance above 1 is off the map, and then so is that end of the
--           river - which is no odder than the mouth, which has always run a
--           little past the edge.
--   spread  how far the delta may reach sideways, as a fraction of the map
--           across the river, where mountains on the flanks leave it less room
--           than the open coast.
--   band    the share of the map across the river that the rivers themselves
--           may use, centred on the middle. A layout whose flanks are sea or
--           mountains all the way down has less of it, and a river laid out
--           there would start in the water or behind a ridge.
local LAYOUTS = {
	{ key = "shore",      kind = "along",  d0 = 0.00, d1 = 1.00, spread = 1.00, band = 1.00 },
	{ key = "island",     kind = "radial", d0 = 0.00, d1 = 1.00, spread = 1.00, band = 1.00 },
	{ key = "inland_sea", kind = "radial", d0 = 1.09, d1 = 0.31, spread = 1.00, band = 1.00 },
	{ key = "isthmus",    kind = "across", d0 = 0.06, d1 = 0.86, spread = 1.00, band = 1.00 },
	{ key = "strait",     kind = "across", d0 = 0.96, d1 = 0.07, spread = 1.00, band = 1.00 },
	{ key = "peninsula",  kind = "along",  d0 = 0.00, d1 = 1.00, spread = 1.00, band = 0.45 },
	{ key = "bay",        kind = "along",  d0 = 0.00, d1 = 1.00, spread = 0.25, band = 0.50 },
}

-- How far the coastline wanders in and out of the straight line a layout
-- would otherwise draw, at the five settings of the Coastline param, as a
-- fraction of the map along the layout - so a given setting moves the coast by
-- the same number of metres whichever layout it is used on. The middle one is
-- what every map had before the param existed. The graph multiplies its coast
-- noise by whichever of these we hand it, so these are in units of u.
local ROUGHNESS = { 0.012, 0.028, 0.05, 0.10, 0.18 }
-- A layout that folds the map puts the whole of u into half its width, so the
-- same fraction of the map is a much larger slice of u, and on those the top
-- settings run into this ceiling together.
--
-- The ceiling is not taste but arithmetic: u stops at 1, so out past the end
-- of the frame - the corners of a radial layout, the last of the map on any
-- other - the whole sea reads exactly 1. The graph calls a place sea where
-- u plus the noise passes COAST, so a wobble of 1 - COAST or more would turn
-- that outermost water back into land wherever the noise dipped, which is to
-- say it would strew the open sea with islands. That puts the hard limit just
-- under 0.195; the ceiling sits below it, with room to spare, and the top
-- setting is now the ceiling itself on every layout.
local ROUGHNESS_MAX = 0.18

-- A radial layout is a wedge, not a strip: a step sideways near the centre of
-- the map covers far less ground than the same step out at the coast. Lateral
-- offsets are scaled by the distance from the centre, reaching their full size
-- at RADIAL_LATERAL_FULL, so that a source at the centre is a point and a
-- delta reaching the centre is not a tangle. They are never scaled below
-- RADIAL_LATERAL_MIN, though: squeezed to nothing, a stream near the centre
-- comes out as a straight radial line with its meanders pressed flat.
-- Everything is still planned on a plain rectangle; only the last step onto
-- the map knows about any of this.
local RADIAL_LATERAL_FULL = 0.5
local RADIAL_LATERAL_MIN = 0.35
-- On a radial layout a trunk is a radius, and wandering off it costs twice:
-- it is further from the centre at the source, where the massif is, and
-- further from the middle at the mouth, where the water is. So a trunk keeps
-- closer to its lane there than it would on a layout that runs down the map.
-- Only the trunk: tributaries and meanders are what the floor above protects.
local RADIAL_TRUNK_WANDER = 0.5

-- How many separate river systems a map gets, at the two ends of the Rivers
-- slider, per 16km of map across the rivers - a wide map has room for more.
-- Each one is a trunk with its own tributaries and its own delta, and they run
-- side by side in lanes, so the count is also limited by how narrow a lane may
-- get: a system with nothing but its trunk in it is not worth having.
local SYSTEMS_SPARSE = 1
local SYSTEMS_PACKED = 5
local SYSTEMS_MAX = 6
local LANE_MIN = 2500
-- How much of its own lane a delta may spread across, so that two side by side
-- do not run into one another.
local DELTA_LANE = 0.40

-- Tributaries. A river of order 0 is the trunk, 1 joins the trunk, 2 joins
-- an order-1 river.
local MAX_ORDER = 2
-- Metres of parent river per confluence, at the Rivers slider's two ends.
local SPACING_SPARSE = 5400
local SPACING_PACKED = 2200
-- No two rivers come closer than this, except where one joins another.
local MIN_SEPARATION = 1150
-- A tributary's first points are next to its parent by construction, so they
-- are not checked against the parent - only, at a shorter distance, against
-- everything else, or neighbouring tributaries cross each other on the way out.
local EXEMPT_POINTS = 4
local NEAR_SEPARATION = 500
-- How many points a tributary must have to be worth keeping. Where the map is
-- shared between several river systems there is less room sideways, and a
-- stream has to be allowed to be shorter or there would be none at all.
local MIN_POINTS = 7
local MIN_POINTS_NARROW = 4

-- Half-width in metres from discharge: width grows with the square root of
-- what the river carries, as real channels roughly do. Discharge is counted
-- in kilometres of channel upstream.
local WIDTH_PER_SQRT_Q = 15
local WIDTH_MIN = 9
local WIDTH_MAX = 140
local SOURCE_Q = 0.5

-- Meanders. A river swings from side to side with a wavelength that follows
-- its width - real meanders run to ten or fourteen widths - so the trunk
-- makes broader loops than a brook. The minimum is what small streams get,
-- and it is set long so that the upper courses bend only now and then. How
-- far the river swings is the curviness: a fraction of the wavelength, low
-- in the highland and rising to the lowland value over the given stretch of
-- the course (in u). A first attempt swung the tangent at every point, as
-- stock does; at these strengths that is a 900m zigzag, with loops running
-- into each other in the delta.
local MEANDER_WAVELENGTH_PER_WIDTH = 13
local MEANDER_WAVELENGTH_MIN = 1500
local MEANDER_WAVELENGTH_MAX = 3200
local CURVINESS_HIGHLAND = 0.06
local CURVINESS_LOWLAND = 0.21
-- No two bends alike: every bend - each half wave - draws its own length and
-- its own reach, as multiples of what the width alone would give. Without
-- this the bends come at a perfectly even beat and the river reads as a sine.
local BEND_LENGTH_MIN = 0.55
local BEND_LENGTH_MAX = 1.9
local BEND_REACH_MIN = 0.35
local BEND_REACH_MAX = 1.2
local MEANDER_FROM = 0.20
local MEANDER_TO = 0.65

-- Lakes on the rivers: a stretch where the river widens into a long lake
-- and narrows again, the way a valley lake sits on the river that feeds and
-- drains it. They belong to the river, so the valley shaping in the node
-- graph gives them their shores for free.
-- How many a 16km map gets at the two ends of the Lakes slider.
local LAKES_SPARSE = 1
local LAKES_PACKED = 7
-- Length in planned points (450m each) and the widest half-width, in metres.
local LAKE_POINTS_MIN = 3
local LAKE_POINTS_MAX = 7
local LAKE_WIDTH_MIN = 170
local LAKE_WIDTH_MAX = 420
-- Lakes keep out of the delta, and this many points away from a river's ends.
local LAKE_END_MARGIN = 3

local function rand(a, b)
	return a + math.random() * (b - a)
end

local function clamp(x, lo, hi)
	return math.max(lo, math.min(hi, x))
end

local function smoothstep(t)
	t = clamp(t, 0, 1)
	return t * t * (3 - 2 * t)
end

local function halfWidth(q)
	return clamp(WIDTH_PER_SQRT_Q * math.sqrt(q), WIDTH_MIN, WIDTH_MAX)
end

-- One river as parallel lists, the way river_map wants them.
local function newRiver()
	return { points = {}, widths = {}, depths = {}, tangents = {}, widthTangents = {} }
end

-- Build a river from a centreline of { x, y, leftWidth, rightWidth } points
-- in map coordinates. The river narrows to nothing at its last point.
local function fromCentreline(line)
	local river = newRiver()
	local n = #line
	for i = 1, n do
		local a = line[math.max(i - 1, 1)]
		local b = line[math.min(i + 1, n)]
		local span = (i > 1 and i < n) and 2 or 1
		local left, right = line[i][3], line[i][4]
		local width = (left + right) / 2
		river.points[i] = { line[i][1], line[i][2] }
		-- Hermite tangent: direction of travel, one segment long.
		river.tangents[i] = { (b[1] - a[1]) / span, (b[2] - a[2]) / span }
		-- A little jitter on each bank, so the shores are not ruled lines. It
		-- is a share of the width only up to a point: on a lake that would
		-- be a ragged, saw-toothed shore.
		local jitter = math.min(width, 70)
		river.widths[i] = { left + jitter * rand(-0.1, 0.15), right + jitter * rand(-0.1, 0.15) }
		river.widthTangents[i] = { 0, 0 }
		-- Wider rivers are deeper; stock rivers are 7 to 9 deep.
		-- A lake - anything much wider than a river gets - is deeper still.
		river.depths[i] = { 4 + 5 * clamp(width / 90, 0, 1)
			+ 14 * clamp((width - WIDTH_MAX) / 200, 0, 1), 0 }
	end
	-- Stock ends a river with width 0 and a width tangent of -1000 for a
	-- "pointy tip". Widths are hermite-interpolated, and a tangent that steep
	-- overshoots: between the last two points the river swells by about 150m
	-- before it closes. Stock rivers are 60m wide and mostly end off the map,
	-- so it passes there; on a 9m stream it is a round pond at every source.
	-- A flat tangent closes the river with no bulge.
	river.widths[n] = { 0, 0 }
	river.widthTangents[n] = { 0, 0 }
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

-- Cut every segment of a course into SUBDIVISIONS pieces along a smooth
-- curve through its points. `pts` is { U, V } and `width` the half-width at
-- each; `fixed` marks the points that must not move. The planned points stay
-- exactly where they were, at every SUBDIVISIONS-th place of the result.
-- `still` is 0..1: how much of a lake each point is, which stills the meanders.
-- `fixed.lean` is how far the water is shifted to the left bank, in metres.
local function subdivide(pts, width, fixed, still)
	local fine = {}
	local n = #pts
	local function tangent(i)
		local a, b = pts[math.max(i - 1, 1)], pts[math.min(i + 1, n)]
		local span = (i > 1 and i < n) and 2 or 1
		return (b[1] - a[1]) / span, (b[2] - a[2]) / span
	end
	for i = 1, n - 1 do
		local p0, p1 = pts[i], pts[i + 1]
		local m0U, m0V = tangent(i)
		local m1U, m1V = tangent(i + 1)
		for k = 0, SUBDIVISIONS - 1 do
			local t = k / SUBDIVISIONS
			local h00 = 2 * t * t * t - 3 * t * t + 1
			local h10 = t * t * t - 2 * t * t + t
			local h01 = -2 * t * t * t + 3 * t * t
			local h11 = t * t * t - t * t
			fine[#fine + 1] = {
				U = h00 * p0[1] + h10 * m0U + h01 * p1[1] + h11 * m1U,
				V = h00 * p0[2] + h10 * m0V + h01 * p1[2] + h11 * m1V,
				width = width[i] + (width[i + 1] - width[i]) * t,
				fixed = (k == 0) and fixed[i] or false,
				still = still[i] + (still[i + 1] - still[i]) * t,
				lean = fixed.lean[i] + (fixed.lean[i + 1] - fixed.lean[i]) * t,
			}
		end
	end
	fine[#fine + 1] = { U = pts[n][1], V = pts[n][2], width = width[n],
		fixed = fixed[n] or false, still = still[n], lean = fixed.lean[n] }
	return fine
end

-- Bend a subdivided course into meanders, in place. Each point is pushed
-- sideways by a sine of the distance travelled, one bend per half wave, each
-- bend with a length and reach of its own. The swing dies away towards every
-- fixed point, so confluences and ends stay put and rivers still meet where
-- they were planned to.
local function meander(fine, curvinessAt)
	local n = #fine
	local s = { 0 }
	for i = 2, n do
		local dU, dV = fine[i].U - fine[i - 1].U, fine[i].V - fine[i - 1].V
		s[i] = s[i - 1] + math.sqrt(dU * dU + dV * dV)
	end

	-- Distance along the river to the nearest fixed point, either way.
	local toFixed = {}
	local last = -math.huge
	for i = 1, n do
		if fine[i].fixed then last = s[i] end
		toFixed[i] = s[i] - last
	end
	last = math.huge
	for i = n, 1, -1 do
		if fine[i].fixed then last = s[i] end
		toFixed[i] = math.min(toFixed[i], last - s[i])
	end

	local phase = rand(0, 2 * math.pi)
	local bend = math.floor(phase / math.pi)
	local stretch = rand(BEND_LENGTH_MIN, BEND_LENGTH_MAX)
	local reach = rand(BEND_REACH_MIN, BEND_REACH_MAX)
	local moved = {}
	for i = 1, n do
		-- A lake is no wider a river for meandering purposes.
		local wavelength = stretch * clamp(
			MEANDER_WAVELENGTH_PER_WIDTH * 2 * math.min(fine[i].width, WIDTH_MAX),
			MEANDER_WAVELENGTH_MIN, MEANDER_WAVELENGTH_MAX)
		if i > 1 then
			phase = phase + 2 * math.pi * (s[i] - s[i - 1]) / wavelength
		end
		-- A new bend starts where the sine crosses zero, so changing its
		-- length and reach there leaves no kink in the river.
		if math.floor(phase / math.pi) ~= bend then
			bend = math.floor(phase / math.pi)
			stretch = rand(BEND_LENGTH_MIN, BEND_LENGTH_MAX)
			reach = rand(BEND_REACH_MIN, BEND_REACH_MAX)
		end
		local a, b = fine[math.max(i - 1, 1)], fine[math.min(i + 1, n)]
		local dU, dV = b.U - a.U, b.V - a.V
		local len = math.sqrt(dU * dU + dV * dV)
		local swing = reach * curvinessAt(fine[i].U) * wavelength * math.sin(phase)
			* smoothstep(toFixed[i] / (0.5 * wavelength)) * (1 - fine[i].still)
		if len > 0 then
			moved[i] = { fine[i].U - dV / len * swing, fine[i].V + dU / len * swing }
		else
			moved[i] = { fine[i].U, fine[i].V }
		end
	end
	for i = 1, n do
		fine[i].U, fine[i].V = moved[i][1], moved[i][2]
	end
end

local function riverApplyFn(params, inputs, captureParams)
	local minX, minY = inputs.boundsMin.point.x, inputs.boundsMin.point.y
	local maxX, maxY = inputs.boundsMax.point.x, inputs.boundsMax.point.y
	local sizeX, sizeY = maxX - minX, maxY - minY

	-- The Rivers slider, 0..1. Absent when the node is used without it.
	local amount = 0.5
	if inputs.amount and inputs.amount.value then
		amount = clamp(inputs.amount.value, 0, 1)
	end

	-- The Lakes slider, 0..1.
	local lakeAmount = 0.5
	if inputs.lakes and inputs.lakes.value then
		lakeAmount = clamp(inputs.lakes.value, 0, 1)
	end

	-- The layout. 0 is the dropdown's "Random", and also what a generator
	-- that never got the param falls back on, so either way the map seed
	-- picks one.
	local choice = 0
	if inputs.layout and inputs.layout.value then
		choice = math.floor(clamp(inputs.layout.value, 0, 1) * #LAYOUTS + 0.5)
	end
	if choice < 1 then choice = math.random(1, #LAYOUTS) end
	local layout = LAYOUTS[choice]

	-- The Islands param, passed straight through to the graph below as a map.
	-- What each setting means is build.py's business - it bends the slider
	-- into island sizes with a pwlerp_map - so there is nothing to decide
	-- here. Without the param, the middle setting.
	local islands = 0.5
	if inputs.islands and inputs.islands.value then
		islands = clamp(inputs.islands.value, 0, 1)
	end

	-- The Coastline param, 1 to 5. Its first setting is 0, so unlike the
	-- layout a 0 here means Straight and not "choose for me"; what stands in
	-- for the param where there is none is the middle setting, which is the
	-- dummy build.py gives the param_number that reads it.
	local rough = ROUGHNESS[3]
	if inputs.coast and inputs.coast.value then
		rough = ROUGHNESS[clamp(math.floor(inputs.coast.value * (#ROUGHNESS - 1) + 1.5),
			1, #ROUGHNESS)]
	end

	-- The Orientation param: which of the map's two sides the layout runs
	-- along - the one the land changes down, so the one a shore layout's river
	-- runs the length of and an isthmus's range lies across. 1 is random, 2
	-- the long side, which is what every map did before the param, and 3 the
	-- short side. On a square map there is nothing to choose.
	local axis = 2
	if inputs.axis and inputs.axis.value then
		axis = clamp(math.floor(inputs.axis.value * 2 + 1.5), 1, 3)
	end
	if axis == 1 then axis = math.random(2, 3) end

	-- The map frame: `a` runs along that side of the map, `b` across it, both
	-- 0..1. Which way round is up to the seed; a square map allows all four
	-- turns, since both of its sides are the long one.
	local turn = math.random(1, 4)
	local alongX
	if sizeX == sizeY then
		alongX = turn <= 2
	else
		alongX = ((sizeX > sizeY) == (axis == 2))
	end
	if alongX then
		turn = (turn <= 2) and turn or (turn - 2)
	else
		turn = (turn >= 3) and turn or (turn + 2)
	end
	local sizeA = (turn <= 2) and sizeX or sizeY
	local sizeB = (turn <= 2) and sizeY or sizeX
	local function toMapAB(a, b)
		if turn == 1 then return minX + a * sizeX, minY + b * sizeY end
		if turn == 2 then return maxX - a * sizeX, minY + b * sizeY end
		if turn == 3 then return minX + b * sizeX, minY + a * sizeY end
		return minX + b * sizeX, maxY - a * sizeY
	end

	-- The river frame: U runs from where the land is highest (0) to past the
	-- water (length), V is the position across, both in metres. It is the
	-- stretch of the map between the layout's two distances, along the map's
	-- centre line - so for a fold the river runs across the map and spreads
	-- along its length, and for a radial layout it is a radius out from the
	-- centre, or in towards it. `facing` is which of the two symmetrical
	-- halves a river system drains; each system sets it, and it stays set
	-- while that system is planned and again while it is finished, because
	-- toMap reads it.
	local firstFacing = (math.random() < 0.5) and 1 or -1
	local facing = firstFacing
	local dspan = layout.d1 - layout.d0
	local length, across
	if layout.kind == "along" then
		length, across = math.abs(dspan) * sizeA, sizeB
	elseif layout.kind == "radial" then
		-- A distance is |2a - 1|, so a span of it covers half as much map.
		length, across = math.abs(dspan) / 2 * sizeA, sizeB
	else
		length, across = math.abs(dspan) / 2 * sizeB, sizeA
	end
	-- A layout that folds, or runs out from the centre, gives the river less
	-- than half the map to run down, and confluences counted in metres would
	-- leave it nearly bare. The land it drains does not shrink with it, though
	-- - the frame is as wide as ever - so the spacing is pulled in by the root
	-- of what the river lost, which is between the two. A layout that runs the
	-- length of the map, as every map did before there were layouts, scales
	-- by exactly 1 and is left alone.
	local frameFull = (layout.kind == "across") and sizeB or sizeA
	local confluenceScale = math.sqrt(length / frameFull)

	-- u runs 0 to 1 over the length of the river's frame, whatever fraction of
	-- the map that is, so a wobble of a given number of metres is that many
	-- more units of u on a layout whose frame is short. Scaling by it is what
	-- makes one setting of the param mean the same thing on every layout -
	-- which is the whole point, the folded layouts being the ones whose
	-- coastlines looked ruled.
	rough = math.min(rough * frameFull / length, ROUGHNESS_MAX)
	local riverEnd = RIVER_END + ((layout.kind == "radial") and RADIAL_END_EXTRA or 0)

	local function toMap(U, V)
		local u = U / length
		local d = layout.d0 + u * dspan
		local off = (V / across - 0.5)
		if layout.kind == "radial" then
			off = off * (RADIAL_LATERAL_MIN + (1 - RADIAL_LATERAL_MIN)
				* clamp(d / RADIAL_LATERAL_FULL, 0, 1))
		end
		if layout.kind == "along" then
			return toMapAB(d, 0.5 + off)
		elseif layout.kind == "radial" then
			return toMapAB(0.5 + facing * d / 2, 0.5 + off)
		end
		return toMapAB(0.5 + off, 0.5 + facing * d / 2)
	end

	-- How many river systems, and how wide a lane each gets. The Rivers
	-- slider sets both this and how densely tributaries join below.
	local bandWidth = layout.band * across
	local systemCount = (SYSTEMS_SPARSE + (SYSTEMS_PACKED - SYSTEMS_SPARSE) * amount)
		* bandWidth / 16000
	systemCount = math.floor(systemCount + 0.5)
	systemCount = math.max(1, math.min(systemCount, SYSTEMS_MAX,
		math.floor(bandWidth / LANE_MIN)))
	local laneWidth = layout.band / systemCount
	local laneMetres = laneWidth * across
	local du = STEP / length

	-- A tributary aims to stay inside its system's lane, so a narrow lane
	-- makes for shorter streams - down to MIN_POINTS_NARROW, below which it
	-- is a stub and not a river.
	local minPoints = clamp(math.floor(laneMetres / STEP / 2),
		MIN_POINTS_NARROW, MIN_POINTS)

	-- Every river is a list of { U, V } running UPSTREAM, mouth first and
	-- source last - the order stock uses. `children` are the rivers that
	-- join it.
	--
	-- Rivers are kept apart in map metres rather than in the frame, because
	-- the frame is not the map: two systems draining opposite sides of a fold
	-- share a (U, V) and are half a map apart, and a step sideways near the
	-- centre of a radial layout is a much smaller step on the ground. Points
	-- are therefore turned into map coordinates as they are claimed.
	local occupied = {}
	local function occupy(river, from)
		for k = from, #river.pts do
			local x, y = toMap(river.pts[k][1], river.pts[k][2])
			occupied[#occupied + 1] = { x, y, river }
		end
	end
	-- Is (U, V) within `separation` of any river other than `except`?
	local function tooClose(U, V, separation, except)
		local x, y = toMap(U, V)
		for _, p in ipairs(occupied) do
			if p[3] ~= except then
				local dx = p[1] - x
				if dx > -separation and dx < separation then
					local dy = p[2] - y
					if dx * dx + dy * dy < separation * separation then
						return true
					end
				end
			end
		end
		return false
	end

	-- One tributary, marched upstream from point `index` of its parent. It
	-- leaves at a shallow angle - so it joins pointing downstream, as real
	-- confluences do - and bends further away as it climbs. Returns nil if
	-- there is no room for it.
	local function makeTributary(parent, index, side, order)
		local pts = parent.pts
		local a = pts[math.max(index - 1, 1)]
		local b = pts[math.min(index + 1, #pts)]
		local upstream = atan2(b[2] - a[2], b[1] - a[1])

		local reach
		if order == 1 then
			reach = math.max(rand(0.40, 0.80) * math.min(length, laneMetres),
				(minPoints + 1) * STEP)
		else
			reach = rand(0.45, 0.80) * (#pts * STEP)
		end
		local steps = math.floor(reach / STEP)
		local leave, climb = math.rad(rand(35, 50)), math.rad(rand(60, 85))
		local phase = rand(0, 2 * math.pi)

		local line = { { pts[index][1], pts[index][2] } }
		local U, V = pts[index][1], pts[index][2]
		for k = 1, steps do
			local t = k / steps
			local heading = upstream + side * (leave + (climb - leave) * smoothstep(t))
				+ 0.35 * math.sin(2 * math.pi * 1.5 * t + phase) * t
			U = U + STEP * math.cos(heading)
			V = V + STEP * math.sin(heading)
			-- Never into the sea, never far off the map, never into another river.
			if U > (COAST - 0.06) * length then break end
			if U < -400 or V < -400 or V > across + 400 then break end
			if k > EXEMPT_POINTS then
				if tooClose(U, V, MIN_SEPARATION, nil) then break end
			elseif tooClose(U, V, NEAR_SEPARATION, parent) then
				break
			end
			line[#line + 1] = { U, V }
		end
		if #line < minPoints then
			return nil
		end
		return { pts = line, children = {}, order = order }
	end

	-- Hang tributaries along a river, then along each of those.
	local function grow(parent, first, last)
		local spacing = (SPACING_SPARSE + (SPACING_PACKED - SPACING_SPARSE) * amount)
			* confluenceScale
		local side = (math.random() < 0.5) and 1 or -1
		local index = first + math.floor(rand(0, 0.6) * spacing / STEP)
		while index <= last do
			local child
			for attempt = 1, 4 do
				child = makeTributary(parent, index, side, parent.order + 1)
				if child then break end
				if attempt == 2 then side = -side end
			end
			if child then
				-- The first point is the parent's own; the rest are new ground.
				occupy(child, 2)
				parent.children[#parent.children + 1] = { index = index, river = child }
			end
			-- Mostly alternate banks, like a real drainage tree.
			if math.random() < 0.75 then side = -side end
			index = index + math.max(2, math.floor(rand(0.7, 1.3) * spacing / STEP))
		end
		if parent.order + 1 < MAX_ORDER then
			for _, c in ipairs(parent.children) do
				grow(c.river, 4, #c.river.pts - 3)
			end
		end
	end

	-- Discharge at every point: what the river has collected from its own
	-- length upstream, plus everything its tributaries bring in.
	local function discharge(river)
		local n = #river.pts
		local joining = {}
		for _, c in ipairs(river.children) do
			discharge(c.river)
			joining[c.index] = (joining[c.index] or 0) + c.river.q[1]
		end
		river.q = {}
		river.q[n] = SOURCE_Q
		for i = n - 1, 1, -1 do
			local dU = river.pts[i][1] - river.pts[i + 1][1]
			local dV = river.pts[i][2] - river.pts[i + 1][2]
			river.q[i] = river.q[i + 1] + math.sqrt(dU * dU + dV * dV) / 1000 + (joining[i] or 0)
		end
	end

	local allRivers = {}
	local function collect(river)
		allRivers[#allRivers + 1] = river
		river.lake = {}
		river.lean = {}
		for _, c in ipairs(river.children) do
			collect(c.river)
		end
	end

	-- One river system: a trunk down the middle of its own lane, with its
	-- tributaries. Planned only - the lakes are placed across all the systems
	-- afterwards, and the whole lot is finished after that.
	local function planSystem(index)
		-- Which half of a fold, or which way out from the centre, this one
		-- drains. Successive systems take the two in turn, so an isthmus is
		-- drained to both of its seas and an island on both of its flanks.
		-- A layout that simply runs down the map has only one side, and
		-- toMap ignores this.
		facing = (index % 2 == 1) and firstFacing or -firstFacing

		-- The trunk: a slow wander plus a faster one, about the middle of its
		-- lane and swinging by a share of the lane's width, so that one system
		-- never wanders into the next.
		-- Which lane. Two systems that drain opposite sides of a radial
		-- layout are already as far apart as the map can put them, and
		-- giving them lanes on top of that only drags their sources off the
		-- summit and their mouths away from the middle - both of which are
		-- the one point the whole layout turns around. So there, lanes are
		-- counted within each side. A fold's two sides lie along the length
		-- of the map, where there is room to spread, and keep their lanes.
		local slot, slots = index, systemCount
		if layout.kind == "radial" then
			slot = math.floor((index - 1) / 2) + 1
			slots = ((index % 2) == 1) and math.ceil(systemCount / 2)
				or math.floor(systemCount / 2)
		end
		local wander = laneWidth
			* ((layout.kind == "radial") and RADIAL_TRUNK_WANDER or 1)
		local v0 = 0.5 - layout.band / 2 + (slot - 0.5) * (layout.band / slots)
			+ rand(-0.15, 0.15) * wander
		local p1, p2 = rand(0, 2 * math.pi), rand(0, 2 * math.pi)
		local function trunkV(u)
			return (v0 + (0.09 * math.sin(2 * math.pi * 0.9 * u + p1)
				+ 0.025 * math.sin(2 * math.pi * 3.7 * u + p2)) * wander) * across
		end

		local trunk = { pts = {}, children = {}, order = 0 }
		local u = riverEnd
		while u >= SOURCE_AT do
			trunk.pts[#trunk.pts + 1] = { u * length, trunkV(u) }
			u = u - du
		end
		occupy(trunk, 1)

		-- On the trunk, tributaries join between the mountains and the delta.
		local firstIndex, lastIndex, deltaIndex = #trunk.pts, 1, 1
		for i, p in ipairs(trunk.pts) do
			local uu = p[1] / length
			if uu <= DELTA_AT - 0.05 and uu >= 0.12 then
				firstIndex = math.min(firstIndex, i)
				lastIndex = math.max(lastIndex, i)
			end
			if uu >= DELTA_AT then deltaIndex = i end
		end
		grow(trunk, firstIndex, lastIndex)
		discharge(trunk)
		collect(trunk)
		return { trunk = trunk, trunkV = trunkV, deltaIndex = deltaIndex,
			facing = facing }
	end

	local systems = {}
	for index = 1, systemCount do
		systems[index] = planSystem(index)
	end

	-- Lakes, over every system there is. Each try picks a river and a stretch
	-- of it; a stretch that would reach the delta, a river's end or another
	-- lake is simply dropped, so the number is a target and short rivers get
	-- fewer.
	local lakeCount = 0
	local wanted = (LAKES_SPARSE + (LAKES_PACKED - LAKES_SPARSE) * lakeAmount)
		* math.sqrt(length * across) / 16000
	for attempt = 1, math.floor(wanted * 4 + 0.5) do
		if lakeCount >= math.floor(wanted + 0.5) then break end
		local river = allRivers[math.random(1, #allRivers)]
		local span = math.random(LAKE_POINTS_MIN, LAKE_POINTS_MAX)
		local first = LAKE_END_MARGIN + 1
		local last = #river.pts - LAKE_END_MARGIN - span
		if last >= first then
			local from = math.random(first, last)
			local free = true
			for i = from - 1, from + span + 1 do
				if river.lake[i] or river.pts[i][1] / length > DELTA_AT - 0.08 then
					free = false
				end
			end
			if free then
				-- No two lakes the same shape: each has its own fullness, its
				-- widest point somewhere along its length rather than always
				-- in the middle, and it lies more to one bank than the other.
				local widest = rand(LAKE_WIDTH_MIN, LAKE_WIDTH_MAX)
				local fullness = rand(0.45, 1.0)
				local skew = rand(0.6, 1.6)
				local lean = rand(-0.55, 0.55)
				for i = from, from + span do
					local t = ((i - from) / span) ^ skew
					local extra = math.sin(math.pi * t) ^ fullness * widest
					river.lake[i] = extra
					river.lean[i] = extra * lean
				end
				lakeCount = lakeCount + 1
			end
		end
	end

	local function curvinessAt(U)
		local t = smoothstep((U / length - MEANDER_FROM) / (MEANDER_TO - MEANDER_FROM))
		-- Just below the split the three delta channels run side by side, and
		-- full loops there swing into one another. Let them spread first.
		local calm = 0.25 + 0.75 * smoothstep((U / length - DELTA_AT) / (COAST - DELTA_AT))
		if U / length < DELTA_AT then calm = 1 end
		return (CURVINESS_HIGHLAND + (CURVINESS_LOWLAND - CURVINESS_HIGHLAND) * t) * calm
	end

	-- Turn a planned course into a finished river: subdivide, meander, and
	-- move from the layout frame onto the map.
	local rivers = {}
	local function finish(pts, width, fixed, still)
		local fine = subdivide(pts, width, fixed, still)
		meander(fine, curvinessAt)
		local line = {}
		for i, p in ipairs(fine) do
			local x, y = toMap(p.U, p.V)
			line[i] = { x, y, p.width + p.lean, p.width - p.lean }
		end
		rivers[#rivers + 1] = fromCentreline(line)
	end

	-- Flatten the tree into river_map's lists, parents before children. A
	-- river is held still where it joins its parent and where its own
	-- tributaries join it.
	local count = { 0, 0, 0 }
	local function emit(sys, river)
		local width, fixed, still = {}, { lean = {} }, {}
		for i = 1, #river.pts do
			local lake = river.lake[i] or 0
			width[i] = halfWidth(river.q[i]) + lake
			still[i] = clamp(lake / LAKE_WIDTH_MIN, 0, 1)
			fixed.lean[i] = river.lean[i] or 0
		end
		fixed[1] = true
		for _, c in ipairs(river.children) do
			fixed[c.index] = true
		end
		if river.order == 0 then
			fixed[sys.deltaIndex] = true
		end
		finish(river.pts, width, fixed, still)
		count[river.order + 1] = count[river.order + 1] + 1
		for _, c in ipairs(river.children) do
			emit(sys, c.river)
		end
	end

	-- The delta: two distributaries leave the trunk and spread away from it
	-- on either side, each taking a share of the flow. They keep inside the
	-- system's own lane, and inside whatever room the layout leaves between
	-- the flanks.
	local function distributary(sys, side)
		local trunk, trunkV = sys.trunk, sys.trunkV
		local splitWidth = 0.6 * halfWidth(trunk.q[sys.deltaIndex])
		local pts, width, fixed, still = {}, {}, { true, lean = {} }, {}
		local spread = math.min(rand(0.16, 0.24) * length, layout.spread * across,
			DELTA_LANE * laneMetres) * side
		local phase = rand(0, 2 * math.pi)
		local ub = trunk.pts[sys.deltaIndex][1] / length
		while ub <= riverEnd do
			local t = (ub - DELTA_AT) / (1 - DELTA_AT)
			-- Eased, so the branch leaves the trunk at a shallow angle.
			local away = spread * smoothstep(t)
			local wobble = 0.012 * length * math.sin(2 * math.pi * 2.5 * t + phase) * t
			pts[#pts + 1] = { ub * length, trunkV(ub) + away + wobble }
			width[#width + 1] = splitWidth
			still[#still + 1] = 0
			fixed.lean[#fixed.lean + 1] = 0
			ub = ub + du
		end
		finish(pts, width, fixed, still)
	end

	-- Finishing is where the frame becomes the map, so each system has to put
	-- its own side back in place first.
	for _, sys in ipairs(systems) do
		facing = sys.facing
		emit(sys, sys.trunk)
		distributary(sys, 1)
		distributary(sys, -1)
	end

	local all = join(rivers)

	-- The layout quad: one textured rectangle over the whole map, two
	-- triangles like the stock random_quads emits, in the map frame rather
	-- than the river's. Its texture coordinates pick out the tile of the
	-- layout we chose - the tiles lie side by side in tex/layouts.tga - and
	-- rasterising it gives the graph the map of u it cannot work out for
	-- itself.
	local lo, hi = -LAYOUT_MARGIN, 1 + LAYOUT_MARGIN
	local corners = { { 0, 0 }, { 1, 0 }, { 1, 1 }, { 0, 0 }, { 1, 1 }, { 0, 1 } }
	local vertices, texCoords = {}, {}
	for i, c in ipairs(corners) do
		local x, y = toMapAB(lo + c[1] * (hi - lo), lo + c[2] * (hi - lo))
		vertices[i] = { x, y }
		texCoords[i] = { (choice - 1 + c[1]) / #LAYOUTS, c[2] }
	end

	-- A number as a map: the same rectangle again, but with every corner
	-- pointing at one single texel, so that rasterising it fills the map with
	-- that one value. It is how a number on this side of the node - something
	-- a script works out, or a param only a script is given - reaches the side
	-- of the graph that speaks only in maps.
	--
	-- The texel is a point on the first tile, which is the plain ramp of the
	-- "shore" layout: its value is the map coordinate it stands for, clamped
	-- to 0..1, so asking it for a number between 0 and 1 is a matter of
	-- reading that ramp backwards. tools/build.py keeps the tile first and
	-- plain, and reads the value back out of these coordinates to check it.
	local function valueQuad(value)
		local s = (value + LAYOUT_MARGIN) / (1 + 2 * LAYOUT_MARGIN) / #LAYOUTS
		local quadVertices, quadTexCoords = {}, {}
		for i, c in ipairs(corners) do
			local x, y = toMapAB(lo + c[1] * (hi - lo), lo + c[2] * (hi - lo))
			quadVertices[i] = { x, y }
			quadTexCoords[i] = { s, 0.5 }
		end
		return quadVertices, quadTexCoords
	end
	local roughVertices, roughTexCoords = valueQuad(rough)
	local islandVertices, islandTexCoords = valueQuad(islands)

	-- Proof in stdout.txt that our script, not the stock one, laid the rivers.
	if log and log.message then
		log.message(LOG .. "river node: layout " .. layout.key .. ", " .. count[1]
			.. " rivers + " .. count[2] .. " tributaries + " .. count[3]
			.. " of theirs, " .. lakeCount .. " lakes, " .. #all.points
			.. " points, mouth discharge " .. math.floor(systems[1].trunk.q[1])
			.. ", frame " .. turn .. "/" .. firstFacing
			.. ", coast " .. string.format("%.3f", rough)
			.. ", islands " .. string.format("%.2f", islands)
			.. ", axis " .. axis)
	end

	return {
		{ 3, all.points },
		{ 3, all.widths },
		{ 3, all.depths },
		{ 3, all.tangents },
		{ 3, all.widthTangents },
		{ 3, vertices },
		{ 3, texCoords },
		{ 3, roughVertices },
		{ 3, roughTexCoords },
		{ 3, islandVertices },
		{ 3, islandTexCoords },
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
