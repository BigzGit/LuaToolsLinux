const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../public/luatools.js'), 'utf8');
const nodes = [];
function element() {
    const node = { style: {}, children: [], appendChild(child) { this.children.push(child); }, addEventListener() {}, remove() {} };
    nodes.push(node);
    return node;
}
const context = vm.createContext({ document: { querySelector() { return null; }, createElement: element, body: element() }, closeSettingsOverlay() {}, ensureLuaToolsStyles() {}, lt(value) { return value; } });
const escape = source.slice(source.indexOf('    function escapeHtml'), source.indexOf('    // Fallback RPC bridge'));
const confirm = source.slice(source.indexOf('    function showLuaToolsConfirm'), source.indexOf('    // Ensure consistent spacing'));
vm.runInContext(escape + confirm, context);
const hostile = '<img src=x onerror="alert(1)">&\'';
assert.equal(context.escapeHtml(hostile), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&amp;&#39;');
context.showLuaToolsConfirm('title', hostile);
assert(nodes.some(n => n.textContent === hostile));
assert(!nodes.some(n => n.innerHTML === hostile));
const warning = '<b>Permanent deletion</b>';
context.showLuaToolsConfirm('warning', { trustedHtml: warning });
assert(nodes.some(n => n.innerHTML === warning));
console.log('UI security: escaping, text confirmations and static warning markup pass');
