// Runs the river node's Lua outside the game and prints what it returns, as
// JSON. There is no Lua on the development machine and no way to see a river
// layout short of restarting the game, so this is how nodes.script.lua gets
// checked: a syntax error or a nil index shows up here, not in a crash dump.
//
// Needs fengari, a Lua VM for Node:   npm install --no-save fengari
// Usage:  node tools/run_river.js <seed> <map width m> <map height m> <rivers 0..1>
//                                  [lakes 0..1] [layout 0..1] [coast 0..1] [islands 0..1] [axis 0..1]
//
// fengari is Lua 5.3 and the game is not, so passing here does not prove the
// script uses nothing newer than the game's Lua - keep to plain 5.1.
const path = require("path");
const fs = require("fs");
const { lua, lauxlib, lualib, to_luastring, to_jsstring } = require("fengari");

const [seed, width, height, amount, lakes = 0.5, layout = 0, coast = 0, islands = 0.5,
	axis = 0.5] = process.argv.slice(2).map(Number);
const script = fs.readFileSync(
	path.join(__dirname, "..", "mod", "mapzilla_1", "content", "mapzilla", "nodes.script.lua"), "utf8");

// The harness: seed the generator the way the engine does before a node runs,
// call the node, and serialise the result with nothing but string.format.
const harness = `
local seed, width, height, amount, lakes, layout, coast, islands, axis = ...
math.randomseed(seed)
local result = data().river.applyFn({}, {
	boundsMin = { point = { x = -width / 2, y = -height / 2 } },
	boundsMax = { point = { x = width / 2, y = height / 2 } },
	amount = { value = amount },
	lakes = { value = lakes },
	layout = { value = layout },
	coast = { value = coast },
	islands = { value = islands },
	axis = { value = axis },
}, {})
local out = {}
for i, entry in ipairs(result) do
	local points = {}
	for j, p in ipairs(entry[2]) do
		points[j] = string.format("[%.2f,%.2f]", p[1], p[2])
	end
	out[i] = "[" .. table.concat(points, ",") .. "]"
end
return "[" .. table.concat(out, ",") .. "]"
`;

const L = lauxlib.luaL_newstate();
lualib.luaL_openlibs(L);

function check(status) {
	if (status !== lua.LUA_OK) {
		console.error(to_jsstring(lua.lua_tostring(L, -1)));
		process.exit(1);
	}
}

check(lauxlib.luaL_loadbuffer(L, to_luastring(script), null, to_luastring("nodes.script.lua")));
check(lua.lua_pcall(L, 0, 0, 0));
check(lauxlib.luaL_loadbuffer(L, to_luastring(harness), null, to_luastring("harness")));
for (const v of [seed, width, height, amount, lakes, layout, coast, islands, axis])
	lua.lua_pushnumber(L, v);
check(lua.lua_pcall(L, 9, 1, 0));
console.log(to_jsstring(lua.lua_tostring(L, -1)));
