// Build and check the diagrams in docs/diagrams (ADR 0011).
//
//   node diagrams.mjs          for each <name>.json: archify finalize -> <name>.html,
//                              then SVG export light/dark and diagrams.lock.json
//   node diagrams.mjs --check  (CI) checks without archify that JSON and HTML agree
//                              with the lock file and that the SVG export of the
//                              committed HTML is byte-identical
//
// The JSON file is always the source. Never edit the HTML by hand.
// archify is a locally installed skill (not in the repository). Set its path
// with ARCHIFY_BIN. The SVG export uses the export dialog of the
// archify viewer itself and is deterministic.
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { homedir, tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright-core';

const repoRoot = resolve(import.meta.dirname, '../..');
const diagramDir = join(repoRoot, 'docs/diagrams');
const lockPath = join(diagramDir, 'diagrams.lock.json');
const variants = ['light', 'dark'];
const check = process.argv.includes('--check');

const sha256 = (path) => createHash('sha256').update(readFileSync(path)).digest('hex');
const rel = (path) => path.slice(repoRoot.length + 1);

const names = readdirSync(diagramDir)
  .filter((f) => f.endsWith('.json') && f !== 'diagrams.lock.json' && !f.includes('.delivery'))
  .map((f) => f.slice(0, -'.json'.length))
  .sort();

function render(name) {
  const archify = process.env.ARCHIFY_BIN ?? join(homedir(), '.claude/skills/archify/bin/archify.mjs');
  if (!existsSync(archify)) throw new Error(`archify not found (${archify}), set ARCHIFY_BIN`);
  const type = JSON.parse(readFileSync(join(diagramDir, `${name}.json`), 'utf8')).diagram_type;
  const evidence = join('.archify', `${name}-${new Date().toISOString().replace(/[:.]/g, '-')}`);
  console.log(`archify finalize ${name} (${type}), evidence in ${evidence}`);
  execFileSync(
    process.execPath,
    [archify, 'finalize', type, `docs/diagrams/${name}.json`, `docs/diagrams/${name}.html`,
      '--repo-root', '.', '--quality', 'showcase', '--out-dir', evidence, '--receipt', join(evidence, 'finalize.json')],
    { cwd: repoRoot, stdio: ['ignore', 'ignore', 'inherit'] },
  );
}

async function exportSvgs(browser, name, outDir) {
  const page = await browser.newPage({ acceptDownloads: true, viewport: { width: 1600, height: 1000 } });
  await page.goto(pathToFileURL(join(diagramDir, `${name}.html`)).href);
  const files = {};
  for (const variant of variants) {
    // The export menu of the viewer opens with the E key
    await page.keyboard.press('e');
    const button = page.locator(`[data-format="svg-${variant}"]`).first();
    const [download] = await Promise.all([page.waitForEvent('download', { timeout: 30_000 }), button.click()]);
    files[variant] = join(outDir, `${name}.${variant}.svg`);
    await download.saveAs(files[variant]);
  }
  await page.close();
  return files;
}

const problems = [];
const lock = check && existsSync(lockPath) ? JSON.parse(readFileSync(lockPath, 'utf8')) : {};
const tmp = mkdtempSync(join(tmpdir(), 'diagrams-'));
const browser = await chromium.launch({ channel: 'chrome' });
try {
  for (const name of names) {
    const json = join(diagramDir, `${name}.json`);
    const html = join(diagramDir, `${name}.html`);
    if (!check) render(name);
    if (!existsSync(html)) {
      problems.push(`${rel(html)} is missing`);
      continue;
    }
    const entry = lock[name];
    if (check) {
      if (!entry) problems.push(`${name}: missing in ${rel(lockPath)}`);
      else {
        if (entry.json !== sha256(json)) problems.push(`${rel(json)} changed, but was not rebuilt`);
        if (entry.html !== sha256(html)) problems.push(`${rel(html)} does not agree with the source (edited by hand?)`);
      }
    }
    const exported = await exportSvgs(browser, name, check ? tmp : diagramDir);
    if (check) {
      for (const variant of variants) {
        const committed = join(diagramDir, `${name}.${variant}.svg`);
        if (!existsSync(committed) || sha256(committed) !== sha256(exported[variant])) {
          problems.push(`${rel(committed)} does not agree with ${rel(html)}`);
        }
      }
    } else {
      lock[name] = { json: sha256(json), html: sha256(html) };
      for (const variant of variants) lock[name][variant] = sha256(exported[variant]);
      console.log(`${name}: ${variants.map((v) => `${name}.${v}.svg`).join(', ')}`);
    }
  }
} finally {
  await browser.close();
  rmSync(tmp, { recursive: true, force: true });
}

if (!check) {
  writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`);
} else if (problems.length) {
  console.error(problems.map((p) => `✗ ${p}`).join('\n'));
  console.error('→ run "npm run diagrams --prefix tools/diagrams" locally, then commit all files in docs/diagrams');
  process.exit(1);
} else {
  console.log(`✓ ${names.length} diagrams up to date (${names.join(', ')})`);
}
