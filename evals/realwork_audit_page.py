#!/usr/bin/env python3
"""The page the maintainer labels REPORT §4al's audit pairs on, built from the private sample.

Reads evals/bench/private/realwork/audit-pairs.json (written by `realwork_audit.py sample`) and
writes audit.html beside it: each pair's change (the PR's title, issue, files and diff) and its
lesson, with four answers under the judge's own definitions, and, once realwork_suggest.py has
run, the suggested answer to accept or change (decoys included, unmarked). The page holds no judge verdict and
no stratum, and shows the pairs in their shuffled order. Labels are saved, one document per pair,
to the artifact's db collection `labels`; they are read back with ArtifactData and scored by
`realwork_audit.py score`. The page stays private: it is published as a private artifact.

    python3 evals/realwork_audit_page.py
"""
from __future__ import annotations

import json
from pathlib import Path

PRIVATE = Path(__file__).resolve().parent / "bench" / "private" / "realwork"

PAGE = r"""<title>Lesson Judge Audit</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">
<style>
/* Layout: a two-pane review desk, the change on the left and the lesson pinned on the right, the verdict bar under the lesson; one column on a phone. */
:root {
  --bg: #f6f7f6; --panel: #ffffff; --ink: #1d2422; --muted: #5d6a66; --line: #d9dfdc;
  --accent: #1f6f63; --add: #e5f3ea; --addink: #1e5b37; --del: #fbe9e7; --delink: #8a2a1e; --hunk: #eef1f0;
  --needed: #b4532a; --related: #2f5f9e; --no: #5d6a66; --unsure: #7a4fa0;
  --display: "IBM Plex Serif", Georgia, serif; --body: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #121615; --panel: #1a201e; --ink: #e3e9e6; --muted: #98a6a1; --line: #2c3532;
  --accent: #5cc0ae; --add: #173323; --addink: #9fdcb4; --del: #3a1a16; --delink: #f0aa9e; --hunk: #202826;
  --needed: #e58a5f; --related: #7ea7e0; --no: #98a6a1; --unsure: #b894dc; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #121615; --panel: #1a201e; --ink: #e3e9e6; --muted: #98a6a1; --line: #2c3532;
  --accent: #5cc0ae; --add: #173323; --addink: #9fdcb4; --del: #3a1a16; --delink: #f0aa9e; --hunk: #202826;
  --needed: #e58a5f; --related: #7ea7e0; --no: #98a6a1; --unsure: #b894dc; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font: 15px/1.55 var(--body); }
.wrap { max-width: 1400px; margin: 0 auto; padding-block: 20px 48px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 16px; }
header { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: baseline; justify-content: space-between; }
h1 { font: 600 1.45rem/1.2 var(--display); margin: 0; text-wrap: balance; }
.sub { color: var(--muted); margin: 4px 0 0; max-width: 70ch; }
.progress { display: grid; gap: 6px; min-width: 220px; font-variant-numeric: tabular-nums; }
.bar { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; }
.bar > i { display: block; height: 100%; background: var(--accent); width: 0; transition: width .2s; }
.note { color: var(--muted); font-size: .85rem; }
.note.warn { color: var(--needed); }
details.rubric { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 10px 14px; }
details.rubric summary { cursor: pointer; font-weight: 600; }
.rubric dl { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; margin: 10px 0 0; }
.rubric dt { font-weight: 600; } .rubric dd { margin: 0; color: var(--muted); }
.desk { display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(0, 1fr); gap: 16px; align-items: start; }
@media (max-width: 900px) { .desk { grid-template-columns: minmax(0, 1fr); } }
section.pane { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px 16px; min-width: 0; display: grid; gap: 10px; }
.lesson-pane { position: sticky; top: calc(env(safe-area-inset-top, 0px) + 12px); }
@media (max-width: 900px) { .lesson-pane { position: static; } }
.eyebrow { font: 500 .72rem/1 var(--body); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
h2 { font: 600 1.1rem/1.3 var(--display); margin: 0; text-wrap: balance; }
.meta { display: flex; flex-wrap: wrap; gap: 6px 14px; color: var(--muted); font-size: .85rem; }
.meta a { color: var(--accent); }
.issue { white-space: pre-wrap; font-size: .9rem; max-height: 14em; overflow: auto; border-left: 3px solid var(--line); padding-left: 10px; }
.paths { font: .8rem/1.5 var(--mono); color: var(--muted); max-height: 7em; overflow: auto; }
.diff { font: .78rem/1.45 var(--mono); max-height: 62vh; overflow: auto; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); }
.diff div { white-space: pre; padding: 0 10px; }
.diff .a { background: var(--add); color: var(--addink); } .diff .d { background: var(--del); color: var(--delink); }
.diff .h { background: var(--hunk); color: var(--muted); } .diff .f { font-weight: 500; color: var(--ink); background: var(--hunk); padding-top: 6px; }
.chip { display: inline-block; font: 500 .72rem/1 var(--body); letter-spacing: .04em; text-transform: uppercase; padding: 4px 7px; border-radius: 4px; border: 1px solid var(--line); color: var(--muted); }
.field { display: grid; gap: 2px; } .field b { font-size: .75rem; color: var(--muted); font-weight: 500; text-transform: uppercase; letter-spacing: .06em; }
.field p { margin: 0; white-space: pre-wrap; }
.verdicts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
@media (max-width: 480px) { .verdicts { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
.verdicts button { font: 600 .9rem var(--body); padding: 10px 6px; border-radius: 6px; border: 1.5px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; }
.verdicts button kbd { font: .72rem var(--mono); color: var(--muted); margin-left: 4px; }
.verdicts button:focus-visible, .nav button:focus-visible, .dots button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.verdicts button[data-v="needed"].on { border-color: var(--needed); color: var(--needed); }
.verdicts button[data-v="related"].on { border-color: var(--related); color: var(--related); }
.verdicts button[data-v="no"].on { border-color: var(--no); color: var(--no); }
.verdicts button[data-v="unsure"].on { border-color: var(--unsure); color: var(--unsure); }
.verdicts button:disabled { opacity: .5; cursor: not-allowed; }
.verdicts button.sugg { border-style: dashed; border-color: var(--accent); }
.suggest { border: 1px dashed var(--accent); border-radius: 6px; padding: 10px 12px; display: grid; gap: 6px; }
.suggest .head { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: baseline; justify-content: space-between; }
.suggest .ans { font-weight: 600; } .suggest .line { font: .78rem/1.4 var(--mono); color: var(--muted); white-space: pre-wrap; overflow-wrap: anywhere; }
.suggest button { font: 600 .85rem var(--body); padding: 6px 12px; border-radius: 6px; border: 1.5px solid var(--accent); background: var(--panel); color: var(--accent); cursor: pointer; }
.suggest button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.warnline { color: var(--needed); font-weight: 500; }
.nav { display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; }
.nav button { font: 500 .85rem var(--body); padding: 7px 12px; border-radius: 6px; border: 1px solid var(--line); background: var(--panel); color: var(--ink); cursor: pointer; }
.dots { display: flex; flex-wrap: wrap; gap: 4px; }
.dots button { width: 22px; height: 22px; border-radius: 4px; border: 1px solid var(--line); background: var(--panel); font: .6rem var(--mono); color: var(--muted); cursor: pointer; padding: 0; }
.dots button.done { background: var(--accent); border-color: var(--accent); color: var(--panel); }
.dots button.here { outline: 2px solid var(--ink); outline-offset: 1px; }
@media (prefers-reduced-motion: reduce) { .bar > i { transition: none; } }
</style>
<div class="wrap">
  <header>
    <div>
      <h1>Lesson judge audit</h1>
      <p class="sub">For each pair, decide whether this change needed the lesson. Each pair comes with a suggested answer from a model; accept it or change it. Your answers are then checked against a different model judge, which you do not see.</p>
      <p class="sub warnline">Some suggestions are deliberately wrong, to check that the review is yours. Read each one against the change before accepting it.</p>
    </div>
    <div class="progress"><span id="count">0 of 0 labelled</span><div class="bar"><i id="fill"></i></div><span id="status" class="note">Connecting to saved labels…</span></div>
  </header>
  <details class="rubric" open>
    <summary>What each answer means</summary>
    <dl>
      <dt>Needed</dt><dd>Following the lesson would change this code, or the lesson warns of a defect this change has or risks. It applies to what the change does, even if the two share no words.</dd>
      <dt>Related</dt><dd>The lesson is about the same subject, but nothing in this change would differ for it.</dd>
      <dt>No</dt><dd>It does not apply to this change. Sharing words does not make a lesson needed.</dd>
      <dt>Unsure</dt><dd>You cannot decide from what is shown.</dd>
    </dl>
    <p class="sub">A change that does the thing a lesson is about counts as needed even when it already gets it right: the lesson applied to it.</p>
  </details>
  <details class="rubric">
    <summary>How to decide one pair, in four steps</summary>
    <ol class="sub">
      <li>Read the lesson on the right first: what does it tell you to do, or to avoid? Put it in a few words of your own.</li>
      <li>Look at the files changed. If the change plainly never touches that kind of thing (another stack, another part of the system), answer No.</li>
      <li>Otherwise skim the diff for that thing. If the change does it (right or wrong), answer Needed. If it is only the same topic and nothing here would change, answer Related.</li>
      <li>If deciding would mean reading code outside this diff, answer Unsure and move on.</li>
    </ol>
  </details>
  <div class="desk">
    <section class="pane" aria-label="The change">
      <span class="eyebrow" id="pairtag"></span>
      <h2 id="prtitle"></h2>
      <div class="meta" id="prmeta"></div>
      <div id="issuebox"></div>
      <div class="paths" id="paths"></div>
      <div class="diff" id="diff"></div>
    </section>
    <section class="pane lesson-pane" aria-label="The lesson">
      <span class="eyebrow">The lesson</span>
      <div><span class="chip" id="ltype"></span></div>
      <h2 id="ltitle"></h2>
      <div class="field" id="lsymptom"><b>Symptom</b><p></p></div>
      <div class="field" id="lfix"><b>Fix</b><p></p></div>
      <div class="field" id="lbody"><b>Body</b><p></p></div>
      <div class="suggest" id="suggest">
        <div class="head"><span>Suggested: <span class="ans" id="sans"></span></span><button type="button" id="accept">Accept <kbd>Enter</kbd></button></div>
        <div id="sreason"></div>
        <div class="line" id="sline"></div>
      </div>
      <div class="verdicts" id="verdicts">
        <button type="button" data-v="needed">Needed<kbd>1</kbd></button>
        <button type="button" data-v="related">Related<kbd>2</kbd></button>
        <button type="button" data-v="no">No<kbd>3</kbd></button>
        <button type="button" data-v="unsure">Unsure<kbd>4</kbd></button>
      </div>
      <div class="nav">
        <button type="button" id="prev">← Previous</button>
        <button type="button" id="nextopen">Next unlabelled</button>
        <button type="button" id="next">Next →</button>
      </div>
      <div class="dots" id="dots" aria-label="All pairs"></div>
    </section>
  </div>
</div>
<script id="data" type="application/json">__DATA__</script>
<script>
const DATA = JSON.parse(document.getElementById('data').textContent);
const pairs = DATA.pairs, tasks = DATA.tasks;
let labels = {}, at = 0, db = null, canWrite = true;
const $ = (id) => document.getElementById(id);

function diffView(text) {
  const box = $('diff'); box.replaceChildren();
  for (const line of text.split('\n')) {
    const d = document.createElement('div');
    d.className = line.startsWith('diff --git') ? 'f' : line.startsWith('@@') ? 'h'
      : (line.startsWith('+') && !line.startsWith('+++')) ? 'a' : (line.startsWith('-') && !line.startsWith('---')) ? 'd' : '';
    d.textContent = line || ' ';
    box.appendChild(d);
  }
}
function field(id, text) { const el = $(id); el.hidden = !text; el.querySelector('p').textContent = text || ''; }
function render() {
  const p = pairs[at], t = tasks[String(p.pr)], L = p.lesson;
  $('pairtag').textContent = `Pair ${at + 1} of ${pairs.length} · ${p.id}`;
  $('prtitle').textContent = t.title;
  const meta = $('prmeta'); meta.replaceChildren();
  // No link to the pull request: its page shows the review and the later fixes, which the judge
  // never saw. Both judge the change as it was first written.
  meta.append(Object.assign(document.createElement('span'), {textContent: `PR #${p.pr}, as first written, before review`}),
              Object.assign(document.createElement('span'), {textContent: `${t.paths.length} files changed`}));
  const ib = $('issuebox'); ib.replaceChildren();
  for (const i of t.issues) {
    const h = document.createElement('div'); h.className = 'eyebrow'; h.textContent = `Issue #${i.number}: ${i.title}`;
    const b = document.createElement('div'); b.className = 'issue'; b.textContent = i.body;
    ib.append(h, b);
  }
  $('paths').textContent = t.paths.join('\n');
  diffView(t.diff);
  $('ltype').textContent = L.type || 'Lesson';
  $('ltitle').textContent = L.title || '';
  field('lsymptom', L.symptom); field('lfix', L.fix); field('lbody', L.body);
  const mine = labels[p.id];
  const sg = (DATA.suggestions || {})[p.id];
  $('suggest').hidden = !sg;
  if (sg) {
    $('sans').textContent = {needed: 'Needed', related: 'Related', no: 'No', unsure: 'Unsure'}[sg.answer] || sg.answer;
    $('sreason').textContent = sg.reason || '';
    $('sline').textContent = sg.line ? `rests on: ${sg.line}` : '';
    $('accept').disabled = !db || !canWrite;
  }
  for (const b of $('verdicts').querySelectorAll('button')) {
    b.classList.toggle('on', b.dataset.v === mine); b.classList.toggle('sugg', !!sg && b.dataset.v === sg.answer);
    b.disabled = !db || !canWrite;
  }
  const done = pairs.filter((q) => labels[q.id]).length;
  $('count').textContent = `${done} of ${pairs.length} labelled`;
  $('fill').style.width = `${(100 * done / pairs.length).toFixed(1)}%`;
  const dots = $('dots'); dots.replaceChildren();
  pairs.forEach((q, k) => {
    const b = document.createElement('button'); b.type = 'button'; b.textContent = k + 1;
    b.className = (labels[q.id] ? 'done' : '') + (k === at ? ' here' : '');
    b.setAttribute('aria-label', `Pair ${k + 1}${labels[q.id] ? ', labelled' : ''}`);
    b.onclick = () => go(k); dots.appendChild(b);
  });
}
function go(k) { at = Math.max(0, Math.min(pairs.length - 1, k)); render(); $('diff').scrollTop = 0; window.scrollTo({top: 0}); }
function nextOpen() { for (let s = 1; s <= pairs.length; s++) { const k = (at + s) % pairs.length; if (!labels[pairs[k].id]) return go(k); } }
async function choose(v) {
  if (!db || !canWrite) return;
  const p = pairs[at]; labels[p.id] = v; render();
  try {
    const sg = (DATA.suggestions || {})[p.id];
    await db.collection('labels').doc(p.id).set({verdict: v, suggested: sg ? sg.answer : null,
      kept: sg ? v === sg.answer : null, at: new Date().toISOString()});
    $('status').textContent = 'Saved'; $('status').className = 'note';
    nextOpen();
  } catch (e) {
    $('status').textContent = e && e.code === 'invalid_argument' ? 'This view cannot save labels.' : 'Not saved: the store did not answer. Try again.';
    $('status').className = 'note warn';
    if (e && e.code === 'invalid_argument') { canWrite = false; render(); }
  }
}
$('verdicts').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) choose(b.dataset.v); });
$('accept').onclick = () => { const sg = (DATA.suggestions || {})[pairs[at].id]; if (sg) choose(sg.answer); };
$('prev').onclick = () => go(at - 1); $('next').onclick = () => go(at + 1); $('nextopen').onclick = nextOpen;
document.addEventListener('keydown', (e) => {
  if (e.target.closest('input, textarea')) return;
  const map = {'1': 'needed', '2': 'related', '3': 'no', '4': 'unsure'};
  if (map[e.key]) choose(map[e.key]);
  else if (e.key === 'Enter' && !e.target.closest('button')) { const sg = (DATA.suggestions || {})[pairs[at].id]; if (sg) choose(sg.answer); }
  else if (e.key === 'ArrowRight') go(at + 1);
  else if (e.key === 'ArrowLeft') go(at - 1);
});
render();
(async () => {
  db = await claude.use('db');
  if (!db) { $('status').textContent = 'Labels cannot be saved in this view. Open the artifact in claude.ai while signed in.'; $('status').className = 'note warn'; render(); return; }
  const timer = setTimeout(() => { $('status').textContent = 'Saved labels have not loaded yet.'; $('status').className = 'note warn'; }, 10000);
  db.collection('labels').onSnapshot((snap) => {
    labels = {}; snap.docs.forEach((d) => { const v = d.data()?.verdict; if (v) labels[d.id] = v; });
    if (!snap.metadata.fromCache) { clearTimeout(timer); $('status').textContent = 'Saved labels loaded'; $('status').className = 'note'; }
    render();
  }, (err) => { clearTimeout(timer); $('status').textContent = 'Saved labels could not be read.'; $('status').className = 'note warn'; });
  render();
})();
</script>
"""


def main() -> int:
    """Write audit.html from the private sample."""
    data = json.loads((PRIVATE / "audit-pairs.json").read_text())
    sugg = PRIVATE / "audit-suggestions.json"
    if sugg.exists():
        data["suggestions"] = json.loads(sugg.read_text())
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    (PRIVATE / "audit.html").write_text(PAGE.replace("__DATA__", blob))
    print(f"wrote {PRIVATE / 'audit.html'} · {len(data['pairs'])} pairs · {len(blob) // 1024} KiB of data")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
