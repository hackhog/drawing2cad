// Build generated architecture artifacts from versioned JSON, or verify exact parity.
import { createHash } from 'node:crypto';
import { existsSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { renderDiagram } from './renderer.mjs';

const root = resolve(import.meta.dirname, '../..');
const directory = join(root, 'docs/diagrams');
const lockPath = join(directory, 'diagrams.lock.json');
const check = process.argv.includes('--check');
const hash = (text) => createHash('sha256').update(text).digest('hex');
const names = readdirSync(directory).filter((name) => name.endsWith('.json') && name !== 'diagrams.lock.json' && !name.includes('.delivery')).sort();
const previous = existsSync(lockPath) ? JSON.parse(readFileSync(lockPath, 'utf8')) : {};
const lock = {};
const errors = [];

for (const file of names) {
  const name = file.slice(0, -5);
  const source = readFileSync(join(directory, file), 'utf8');
  const rendered = renderDiagram(JSON.parse(source));
  const outputs = { html: rendered.html, 'light.svg': rendered.light, 'dark.svg': rendered.dark };
  lock[name] = { json: hash(source), html: rendered.hashes.html, light: rendered.hashes.light, dark: rendered.hashes.dark };
  for (const [extension, content] of Object.entries(outputs)) {
    const path = join(directory, name + '.' + extension);
    if (check) {
      if (!existsSync(path) || readFileSync(path, 'utf8') !== content) errors.push(name + '.' + extension + ' differs from generated output.');
    } else {
      writeFileSync(path, content, 'utf8');
    }
  }
  if (check && JSON.stringify(previous[name]) !== JSON.stringify(lock[name])) errors.push(name + ': source/output lock differs.');
}
if (check && Object.keys(previous).some((key) => !(key in lock))) errors.push('Lock contains a removed diagram.');
if (errors.length) {
  console.error(errors.join('\n') + '\nRun npm run build --prefix tools/diagrams and commit all diagram artifacts.');
  process.exitCode = 1;
} else if (check) {
  console.log(names.length + ' diagram(s) match the versioned source and renderer.');
} else {
  writeFileSync(lockPath, JSON.stringify(lock, null, 2) + '\n', 'utf8');
  console.log(names.length + ' diagram(s) generated from JSON.');
}
