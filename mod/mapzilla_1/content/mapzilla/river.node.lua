-- A scripted terrain node: the river layout, decided by our own script instead
-- of the stock random walk. Drop-in for gui/node_editor/river_points.node - it
-- publishes the same five point clouds, which river_map turns into a riverbed.
-- It also publishes a quad that tells the graph which way the river runs, so
-- the mountains and the sea can be put at the right ends of the map.
function data()
return {
	inputs = {
		{ key = "boundsMin", type = "Point", displayName = "Bounds Min", desc = "Minimum corner of the map" },
		{ key = "boundsMax", type = "Point", displayName = "Bounds Max", desc = "Maximum corner of the map" },
	},
	outputs = {
		{ key = "points", type = "PointCloud", displayName = "Points", desc = "Coordinates of the River" },
		{ key = "widths", type = "PointCloud", displayName = "Widths", desc = "Left/right Width of the River Relative to the Center" },
		{ key = "depthsTangent", type = "PointCloud", displayName = "Depth & Slope", desc = "Depth of the River and Slope of the river Bed" },
		{ key = "tangents", type = "PointCloud", displayName = "Direction", desc = "Tangents of the River at the Point" },
		{ key = "widthTangents", type = "PointCloud", displayName = "Width tangent", desc = "Tangent of the river Shore" },
		{ key = "layoutVertices", type = "PointCloud", displayName = "Layout Vertices", desc = "A quad over the whole map, running from the mountain end to the sea end" },
		{ key = "layoutTexCoords", type = "PointCloud", displayName = "Layout Tex. Coords", desc = "Texture coordinates of the layout quad" },
	},
	params = { },
	def = {
		displayName = "Mapzilla River",
		category = "map_ridge_river",
		description = "One river across the map that fans out into a delta",
		order = 1535,
	},
	applyScript = {
		fileName = "mapzilla_1::/mapzilla/nodes.script@river.applyFn",
		params = {}
	},
}
end
