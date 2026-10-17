import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { renderDiagram, validateDiagram } from './renderer.mjs';

const data = JSON.parse(readFileSync(new URL('../../docs/diagrams/drawing2cad-overview.json', import.meta.url), 'utf8'));

test('current source renders deterministically with both themes', () => {
  const first = renderDiagram(data);
  assert.deepEqual(first, renderDiagram(structuredClone(data)));
  assert.notEqual(first.light, first.dark);
  for (const node of data.components) assert.ok(first.light.includes('id="' + node.id + '"'));
});

test('reject missing connection endpoints and duplicate IDs', () => {
  const missing = structuredClone(data);
  missing.connections[0].to = 'unknown';
  assert.throws(() => validateDiagram(missing), /unknown component/);
  const duplicate = structuredClone(data);
  duplicate.components.push(duplicate.components[0]);
  assert.throws(() => validateDiagram(duplicate), /duplicate component/);
});

test('source labels cannot inject XML or close the embedded script', () => {
  const injected = structuredClone(data);
  injected.meta.title = 'Test </script><script>bad()</script> & "value"';
  injected.components[0].label = '<image href="unsafe"/>';
  const result = renderDiagram(injected);
  assert.ok(result.light.includes('&lt;image href=&quot;unsafe&quot;/&gt;'));
  assert.ok(!result.light.includes('<image href='));
  assert.equal((result.html.match(/<script>/g) ?? []).length, 1);
  assert.equal((result.html.match(/<\/script>/g) ?? []).length, 1);
});

test('reject unsupported input and invalid geometry', () => {
  assert.throws(() => validateDiagram({ ...data, diagram_type: 'unknown' }), /Supported input/);
  const invalid = structuredClone(data);
  invalid.components[0].size = [0, 40];
  assert.throws(() => validateDiagram(invalid), /geometry/);
});
