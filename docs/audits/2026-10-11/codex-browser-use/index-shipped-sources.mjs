// Index shipped code without executing it. Offsets bind findings to exact bytes.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';

const require = createRequire(process.env.REA_PACKAGE_JSON ||
  '/Users/fjw/.local/share/rea/node_modules/rea-agents/package.json');
const {parse} = require('@babel/parser');
const base = '/Applications/ChatGPT.app/Contents/Resources/cua_node/lib/node_modules/@oai';
const files = [
  ['cua-repl/dist/lib/js/oai_js_cua_repl/src/launch.js', ['function E()']],
  ['cua/dist/lib/js/oai_js_cua/src/tinysky_alt/create_browser_api.js', ['function t(', 'function n(']],
  ['cua/dist/lib/js/oai_js_cua/src/tinysky_alt/bind_tab.js', ['function n(', 'function u(', 'function c(']],
  ['cua/dist/lib/js/oai_js_cua/src/tinysky_alt/tab_reference.js', ['function r(', 'function t(']],
  ['browser-desktop/scripts/browser-service.mjs', [
    'async performPointerAction(', 'async resolvePointerActionTarget(',
    'async prepareLocatorFill(', 'async function r_(', 'function Ff(',
    'function HO(', 'function DJ(', 'async function IJ(',
    'querySelectorStrictWithVisibleFallback(injected, parsedSelector, root',
    'computer_use_browser_wasm_revision_create(d,',
  ]],
];

const entries = [];
for (const [relative, anchors] of files) {
  const file = path.join(base, relative);
  const bytes = fs.readFileSync(file);
  const text = bytes.toString('utf8');
  const ast = parse(text, {sourceType: 'unambiguous'});
  const scopes = [];
  const visit = node => {
    if (!node || typeof node !== 'object') return;
    if (/Function|Method|VariableDeclarator/.test(node.type || '')) scopes.push(node);
    for (const [key, value] of Object.entries(node)) {
      if (['loc', 'comments', 'tokens'].includes(key)) continue;
      if (Array.isArray(value)) value.forEach(visit);
      else if (value && typeof value === 'object') visit(value);
    }
  };
  visit(ast.program);
  const findings = anchors.map(anchor => {
    const offset = text.indexOf(anchor);
    if (offset < 0) throw new Error(`Anchor not found: ${relative}: ${anchor}`);
    const scopesAt = scopes.filter(n => n.start <= offset && n.end >= offset + anchor.length);
    scopesAt.sort((a, b) => (a.end - a.start) - (b.end - b.start));
    const scope = scopesAt[0];
    if (!scope) throw new Error(`AST scope missing: ${anchor}`);
    return {
      anchor, ast_type: scope.type,
      symbol: scope.id?.name || scope.key?.name || null,
      line: scope.loc.start.line,
      source_start_utf16: scope.start, source_end_utf16: scope.end,
      source_start_byte: Buffer.byteLength(text.slice(0, scope.start)),
      source_end_byte: Buffer.byteLength(text.slice(0, scope.end)),
      scope_sha256: crypto.createHash('sha256').update(text.slice(scope.start, scope.end)).digest('hex'),
    };
  });
  entries.push({file, bytes: bytes.length,
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'), findings});
}
const output = path.join(import.meta.dirname, 'evidence', 'shipped-source-index.json');
fs.writeFileSync(output, JSON.stringify({target_version:'26.1007.21159',
  method:'Babel AST scopes and SHA-256 over inert shipped files', entries}, null, 2));
console.log(`Indexed ${entries.length} files into ${output}`);
