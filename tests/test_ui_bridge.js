const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/luatools.js'), 'utf8');
const start = source.lastIndexOf("Millennium.callServerMethod('luatools', 'HasLuaToolsForApp'");
const end = source.indexOf('                } else {', start);
const code = source.slice(start, end);
(async () => {
    const appended = [];
    const context = vm.createContext({
        Millennium: { callServerMethod: () => Promise.reject(new TypeError('Failed to fetch')) },
        window: { __LuaToolsPresenceCheckInFlight: true },
        document: { querySelector: () => null },
        steamdbContainer: { appendChild: value => appended.push(value) },
        mainWrapper: {}, appid: 480,
    });
    await vm.runInContext(code, context);
    assert.equal(context.window.__LuaToolsPresenceCheckInFlight, false);
    assert.equal(context.window.__LuaToolsButtonInserted, true);
    assert.equal(appended.length, 1);
    console.log('Bridge outage: Add button remains available and pending state is cleared');
})().catch(error => { console.error(error); process.exitCode = 1; });
