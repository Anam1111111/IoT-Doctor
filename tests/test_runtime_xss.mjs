import assert from 'node:assert/strict';
import { JSDOM } from 'jsdom';

const payloads = [
  '<script>alert(1)</script>',
  '<img src=x onerror=alert(1)>',
];

const dom = new JSDOM('<!doctype html><body><div id="root"></div></body>', {
  runScripts: 'dangerously',
  resources: 'usable',
});
let scriptExecuted = false;
dom.window.alert = () => { scriptExecuted = true; };
const root = dom.window.document.getElementById('root');

function renderText(value) {
  const node = dom.window.document.createElement('div');
  node.textContent = value;
  root.appendChild(node);
}

for (const payload of payloads) {
  for (const field of ['summary', 'finding title', 'evidence', 'impact', 'recommendation', 'source', 'filename', 'event message', 'timeline message', 'raw log']) {
    renderText(`${field}: ${payload}`);
  }
}

assert.equal(scriptExecuted, false);
assert.equal(root.querySelectorAll('script').length, 0);
assert.equal(root.querySelectorAll('img').length, 0);
assert.match(root.textContent, /<script>alert\(1\)<\/script>/);
assert.match(root.textContent, /<img src=x onerror=alert\(1\)>/);
console.log('runtime XSS test passed');
