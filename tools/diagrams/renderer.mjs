// Render the maintained architecture JSON without machine-local dependencies.
import { createHash } from 'node:crypto';

const themes = {
  light: { bg: '#f6f8fb', panel: '#ffffff', text: '#17263d', muted: '#526477', border: '#c5d1df', line: '#61758b', accent: '#176ba0', region: '#eaf0f7' },
  dark: { bg: '#0c1624', panel: '#142238', text: '#e5edf7', muted: '#a8b8cb', border: '#37516d', line: '#8ca4be', accent: '#5ec4f3', region: '#101e30' },
};
const xml = (value) => String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' })[c]);
const finitePair = (value) => Array.isArray(value) && value.length === 2 && value.every(Number.isFinite);
const hash = (value) => createHash('sha256').update(value).digest('hex');

export function validateDiagram(data) {
  if (data.schema_version !== 1 || data.diagram_type !== 'architecture') throw new Error('Supported input: architecture schema 1.');
  if (!data.meta?.title || !Array.isArray(data.components) || !data.components.length) throw new Error('A title and components are required.');
  const ids = new Set();
  for (const node of data.components) {
    if (!/^[a-z][a-z0-9_-]*$/i.test(node.id) || ids.has(node.id)) throw new Error('Invalid or duplicate component ID.');
    if (!finitePair(node.pos) || !finitePair(node.size) || node.size.some((n) => n <= 0)) throw new Error('Invalid component geometry.');
    if (!node.label || !node.sublabel) throw new Error('Component label and sublabel are required.');
    ids.add(node.id);
  }
  for (const edge of data.connections ?? []) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) throw new Error('Connection references an unknown component.');
  }
  for (const boundary of data.boundaries ?? []) {
    if (!boundary.wraps?.length || boundary.wraps.some((id) => !ids.has(id))) throw new Error('Boundary references an unknown component.');
  }
}

function lines(text, length) {
  const output = [];
  let line = '';
  for (const word of String(text).split(/\s+/)) {
    if (line && line.length + word.length + 1 > length) { output.push(line); line = ''; }
    line += (line ? ' ' : '') + word;
  }
  if (line) output.push(line);
  return output;
}
function textAt(text, x, y, { size = 14, color, weight = 400, anchor = 'start' } = {}) {
  return `<text x="${x}" y="${y}" font-size="${size}" fill="${color}" font-weight="${weight}" text-anchor="${anchor}">${xml(text)}</text>`;
}
function edgeRoute(a, b) {
  const ac = [a.pos[0] + a.size[0] / 2, a.pos[1] + a.size[1] / 2];
  const bc = [b.pos[0] + b.size[0] / 2, b.pos[1] + b.size[1] / 2];
  if (Math.abs(bc[0] - ac[0]) >= Math.abs(bc[1] - ac[1])) {
    const s = [a.pos[0] + (bc[0] > ac[0] ? a.size[0] : 0), ac[1]];
    const e = [b.pos[0] + (bc[0] > ac[0] ? 0 : b.size[0]), bc[1]];
    const m = (s[0] + e[0]) / 2;
    return { d: `M${s} H${m} V${e[1]} H${e[0]}`, label: [m, (s[1] + e[1]) / 2 - 10] };
  }
  const s = [ac[0], a.pos[1] + (bc[1] > ac[1] ? a.size[1] : 0)];
  const e = [bc[0], b.pos[1] + (bc[1] > ac[1] ? 0 : b.size[1])];
  const m = (s[1] + e[1]) / 2;
  return { d: `M${s} V${m} H${e[0]} V${e[1]}`, label: [(s[0] + e[0]) / 2, m - 10] };
}

export function renderSvg(data, theme) {
  validateDiagram(data);
  const t = themes[theme];
  if (!t) throw new Error('Unknown theme.');
  const nodes = new Map(data.components.map((node) => [node.id, node]));
  const width = Math.max(1280, ...data.components.map((n) => n.pos[0] + n.size[0] + 60));
  const cardY = Math.max(...data.components.map((n) => n.pos[1] + n.size[1])) + 80;
  const cards = data.cards ?? [];
  const cardWidth = (width - 80 - 24 * (cards.length - 1)) / Math.max(1, cards.length);
  const cardLines = cards.map((card) => card.items.flatMap((item) => [...lines(item, Math.floor((cardWidth - 38) / 6.5)), '']));
  const cardHeight = Math.max(100, ...cardLines.map((items) => items.length * 17 + 65));
  const height = cardY + (cards.length ? cardHeight : 0) + 50;
  const out = [`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="title desc">`,
    `<title id="title">${xml(data.meta.title)}</title><desc id="desc">Generated from the versioned architecture JSON. Dashed connections identify optional or legacy paths.</desc>`,
    `<rect width="${width}" height="${height}" fill="${t.bg}"/><g font-family="Arial, Helvetica, sans-serif">`,
    `<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="${t.line}"/></marker></defs>`,
    textAt(data.meta.title, 40, 45, { size: 24, weight: 700, color: t.text }),
    textAt('Current M1 runtime and explicit later milestones', 40, 70, { size: 14, color: t.muted })];
  for (const region of data.boundaries ?? []) {
    const wrapped = region.wraps.map((id) => nodes.get(id));
    const x = Math.min(...wrapped.map((n) => n.pos[0])) - 24;
    const y = Math.min(...wrapped.map((n) => n.pos[1])) - 38;
    const right = Math.max(...wrapped.map((n) => n.pos[0] + n.size[0])) + 24;
    const bottom = Math.max(...wrapped.map((n) => n.pos[1] + n.size[1])) + 24;
    out.push(`<rect x="${x}" y="${y}" width="${right - x}" height="${bottom - y}" rx="12" fill="${t.region}" stroke="${t.border}" stroke-dasharray="5 4"/>`,
      textAt(region.label, x + 12, y + 22, { size: 13, color: t.muted }));
  }
  for (const edge of data.connections ?? []) {
    const route = edgeRoute(nodes.get(edge.from), nodes.get(edge.to));
    out.push(`<path d="${route.d}" fill="none" stroke="${t.line}" stroke-width="${edge.variant === 'emphasis' ? 2.4 : 1.5}" ${edge.variant === 'dashed' ? 'stroke-dasharray="6 4"' : ''} marker-end="url(#arrow)"/>`);
    const wrapped = lines(edge.label ?? '', 23);
    wrapped.forEach((label, i) => out.push(`<text x="${route.label[0]}" y="${route.label[1] + i * 15}" text-anchor="middle" font-size="12" fill="${t.muted}" stroke="${t.bg}" stroke-width="4" paint-order="stroke">${xml(label)}</text>`));
  }
  for (const node of data.components) {
    const [x, y] = node.pos; const [w, h] = node.size;
    out.push(`<g id="${xml(node.id)}"><rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="${t.panel}" stroke="${t.border}" stroke-width="1.5"/>`,
      `<rect x="${x}" y="${y + 10}" width="4" height="${h - 20}" rx="2" fill="${t.accent}"/>`,
      textAt(node.label, x + w / 2, y + 24, { size: 15, color: t.text, weight: 700, anchor: 'middle' }));
    lines(node.sublabel, Math.floor((w - 20) / 6.2)).forEach((line, i) => out.push(textAt(line, x + w / 2, y + 43 + i * 14, { size: 11.5, color: t.muted, anchor: 'middle' })));
    out.push('</g>');
  }
  cards.forEach((card, i) => {
    const x = 40 + i * (cardWidth + 24);
    out.push(`<rect x="${x}" y="${cardY}" width="${cardWidth}" height="${cardHeight}" rx="10" fill="${t.panel}" stroke="${t.border}"/>`,
      textAt(card.title, x + 16, cardY + 28, { size: 15, color: t.text, weight: 700 }));
    cardLines[i].forEach((line, j) => out.push(textAt(line, x + 16, cardY + 54 + j * 17, { size: 12.5, color: t.muted })));
  });
  out.push(textAt('Source: docs/diagrams/drawing2cad-overview.json | ADR 0014', 40, height - 20, { size: 11, color: t.muted }), '</g></svg>');
  return out.join('\n') + '\n';
}

export function renderHtml(data, variants) {
  const encoded = JSON.stringify(variants).replace(/</g, '\\u003c');
  return `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="drawing2cad-diagrams 1"><title>${xml(data.meta.title)}</title>
<style>body{margin:0;font-family:Arial,sans-serif;background:#0c1624;color:#e5edf7}header{position:sticky;top:0;padding:12px 20px;background:#142238;display:flex;gap:12px;align-items:center;z-index:1;flex-wrap:wrap}button{padding:7px 12px;cursor:pointer}main{overflow:auto;padding:16px}#diagram{margin:auto;min-width:800px}svg{display:block;width:100%;height:auto}label{display:flex;align-items:center;gap:8px}a{color:inherit}</style>
</head><body><header><strong>${xml(data.meta.title)}</strong><button id="theme">Switch theme</button><label>Zoom <input id="zoom" type="range" min="50" max="200" value="100"></label><button data-format="svg-light">Download light SVG</button><button data-format="svg-dark">Download dark SVG</button></header><main><div id="diagram"></div></main>
<script>
const variants=${encoded};
let theme=matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';
const diagram=document.getElementById('diagram');
function show(){diagram.innerHTML=variants[theme];document.body.style.background=theme==='dark'?'#0c1624':'#f6f8fb';}
document.getElementById('theme').onclick=()=>{theme=theme==='dark'?'light':'dark';show();};
document.getElementById('zoom').oninput=(event)=>{diagram.style.width=event.target.value+'%';};
document.querySelectorAll('[data-format]').forEach((button)=>button.onclick=()=>{const mode=button.dataset.format.slice(4);const url=URL.createObjectURL(new Blob([variants[mode]],{type:'image/svg+xml'}));const link=document.createElement('a');link.href=url;link.download='drawing2cad-overview.'+mode+'.svg';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
show();
</script></body></html>
`;
}

export function renderDiagram(data) {
  const light = renderSvg(data, 'light');
  const dark = renderSvg(data, 'dark');
  const html = renderHtml(data, { light, dark });
  return { light, dark, html, hashes: { light: hash(light), dark: hash(dark), html: hash(html) } };
}
