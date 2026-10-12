const fs = require('node:fs');
const path = require('node:path');
const ts = require('../../frontend-v2/node_modules/typescript');
const base = path.resolve(__dirname, '../../frontend-v2/src');
const cache = new Map();
function load(filename) {
  filename = filename.startsWith('@/') ? path.join(base, filename.slice(2)) : filename;
  if (filename.endsWith('.json')) return JSON.parse(fs.readFileSync(filename,'utf8'));
  if (!filename.endsWith('.ts')) filename += '.ts';
  if (cache.has(filename)) return cache.get(filename).exports;
  const m = { exports: {} }; cache.set(filename, m);
  const code = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,esModuleInterop:true,target:ts.ScriptTarget.ES2022}}).outputText;
  const resolve = name => name.startsWith('@/') ? load(name) : name.startsWith('.') ? load(path.resolve(path.dirname(filename),name)) : require(name);
  new Function('require','module','exports',code)(resolve,m,m.exports);
  return m.exports;
}
module.exports = load;
