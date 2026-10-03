-- A scripted terrain node: the river layout, decided by our own script instead
-- of the stock random walk. Drop-in for gui/node_editor/river_points.node - it
-- publishes the same five point clouds, which river_map turns into a riverbed.
-- It also publishes a quad that tells the graph which layout it laid the river
-- out for and which way round, so the mountains and the sea can be put where
-- that layout wants them.
function data()
return {
	inputs = {
		{ key = "boundsMin", type = "Point", displayName = "Bounds Min", desc = "Minimum corner of the map" },
		{ key = "boundsMax", type = "Point", displayName = "Bounds Max", desc = "Maximum corner of the map" },
		{ key = "amount", type = "Float", displayName = "Tributary Amount", desc = "How densely tributaries join, between [0, 1]", optional = true },
		{ key = "lakes", type = "Float", displayName = "Lake Amount", desc = "How many lakes lie along the rivers, between [0, 1]", optional = true },
		{ key = "layout", type = "Float", displayName = "Layout", desc = "Where the mountains and the sea are: the Layout param's value, or 0 to pick one from the map seed", optional = true },
		{ key = "coast", type = "Float", displayName = "Coastline", desc = "How far the coastline wanders: the Coastline param's value, or 0 for the middle setting", optional = true },
		{ key = "islands", type = "Float", displayName = "Islands", desc = "How many islands lie off the coast: the Islands param's value, passed through to the graph as a map", optional = true },
		{ key = "axis", type = "Float", displayName = "Orientation", desc = "Which side of the map the layout runs along: the Orientation param's value", optional = true },
	},
	outputs = {
		{ key = "points", type = "PointCloud", displayName = "Points", desc = "Coordinates of the River" },
		{ key = "widths", type = "PointCloud", displayName = "Widths", desc = "Left/right Width of the River Relative to the Center" },
		{ key = "depthsTangent", type = "PointCloud", displayName = "Depth & Slope", desc = "Depth of the River and Slope of the river Bed" },
		{ key = "tangents", type = "PointCloud", displayName = "Direction", desc = "Tangents of the River at the Point" },
		{ key = "widthTangents", type = "PointCloud", displayName = "Width tangent", desc = "Tangent of the river Shore" },
		{ key = "layoutVertices", type = "PointCloud", displayName = "Layout Vertices", desc = "A quad over the whole map, to be rasterised with the layout atlas" },
		{ key = "layoutTexCoords", type = "PointCloud", displayName = "Layout Tex. Coords", desc = "Texture coordinates of the layout quad: the tile of the chosen layout" },
		{ key = "roughVertices", type = "PointCloud", displayName = "Roughness Vertices", desc = "A quad over the whole map, to be rasterised into a map of one value" },
		{ key = "roughTexCoords", type = "PointCloud", displayName = "Roughness Tex. Coords", desc = "Texture coordinates of the roughness quad: one texel of the ramp, holding how far the coastline wanders" },
		{ key = "islandVertices", type = "PointCloud", displayName = "Islands Vertices", desc = "A quad over the whole map, to be rasterised into a map of one value" },
		{ key = "islandTexCoords", type = "PointCloud", displayName = "Islands Tex. Coords", desc = "Texture coordinates of the islands quad: one texel of the ramp, holding the Islands param" },
	},
	params = { },
	def = {
		displayName = "Mapzilla River",
		category = "map_ridge_river",
		description = "One river and its tributaries, running the length of the map and fanning out into a delta",
		order = 1535,
	},
	applyScript = {
		fileName = "mapzilla_1::/mapzilla/nodes.script@river.applyFn",
		params = {}
	},
}
end
