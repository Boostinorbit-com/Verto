// Pure-logic tests for the VERTO extension core — runnable off the editor:
//   npm run compile && npm run test:core
import * as assert from 'assert';
import * as core from './core';

let passed = 0;
function test(name: string, fn: () => void): void {
  try {
    fn();
    passed++;
    console.log(`  ok  ${name}`);
  } catch (e) {
    console.error(`  FAIL ${name}\n       ${e instanceof Error ? e.message : e}`);
    process.exitCode = 1;
  }
}

// A Verdict shaped like real `verto … --json` output (one reserve() win).
const UDIFF =
  '--- a/route.cpp\n+++ b/route.cpp\n' +
  '@@ -10,6 +10,7 @@\n' +
  ' std::vector<int> route_costs(std::size_t n) {\n' +
  '     std::vector<int> out;\n' +
  '+    out.reserve(n);\n' +
  '     for (std::size_t i = 0; i < n; ++i)\n' +
  '-        out.push_back(point_weight(i) + (int)i);\n' +
  '+        out.emplace_back(point_weight(i) + (int)i);\n' +
  '     return out;\n }\n';

const VERDICT: core.Verdict = {
  accepted: true,
  reason: 'accepted',
  candidate: { transform: 'reserve_before_pushback', rationale: 'vector grown by push_back with no prior reserve()' },
  correctness: { rung: 3, witness: { sanitizer: 'clean', inputs_run: 1010 } },
  performance: { vector: { p50: 4.85, p50_before: 10.06, p50_delta_pct: 51.8 }, pareto_pass: true },
  diff: UDIFF,
  udiff: UDIFF,
};

test('parseReport reads a single-file Verdict[]', () => {
  const vs = core.parseReport(JSON.stringify([VERDICT]));
  assert.strictEqual(vs.length, 1);
  assert.strictEqual(vs[0].accepted, true);
});

test('parseReport reads the codebase {file,verdicts} form', () => {
  const payload = [{ file: 'a.cpp', verdicts: [VERDICT] }, { file: 'b.cpp', verdicts: [] }];
  const vs = core.parseReport(JSON.stringify(payload));
  assert.strictEqual(vs.length, 1);
});

test('acceptedFindings filters', () => {
  const rejected: core.Verdict = { accepted: false, reason: 'not_faster' };
  assert.strictEqual(core.acceptedFindings([VERDICT, rejected]).length, 1);
});

test('speedupLabel rounds the p50 delta', () => {
  assert.strictEqual(core.speedupLabel(VERDICT), '−52%');
});

test('anchorLine is the first hunk old-start', () => {
  assert.strictEqual(core.anchorLine(VERDICT), 10);
});

test('coversLine matches inside the hunk, not outside', () => {
  assert.ok(core.coversLine(VERDICT, 12));
  assert.ok(!core.coversLine(VERDICT, 3));
});

test('applyUdiff produces the reserved version (new side only)', () => {
  const src =
    'int point_weight(int);\n'.repeat(9) + // lines 1..9 (filler so line 10 is the fn)
    'std::vector<int> route_costs(std::size_t n) {\n' +
    '    std::vector<int> out;\n' +
    '    for (std::size_t i = 0; i < n; ++i)\n' +
    '        out.push_back(point_weight(i) + (int)i);\n' +
    '    return out;\n}\n';
  const out = core.applyUdiff(src, UDIFF);
  assert.ok(out.includes('out.reserve(n);'), 'reserve inserted');
  assert.ok(out.includes('out.emplace_back(point_weight'), 'push_back → emplace_back');
  assert.ok(!out.includes('out.push_back(point_weight'), 'old push_back removed');
});

test('proofMarkdown shows the trust triplet', () => {
  const md = core.proofMarkdown(VERDICT);
  assert.ok(md.includes('1,010 fuzzed inputs'));
  assert.ok(md.includes('Rung 3'));
  assert.ok(md.includes('−52%'));
  assert.ok(md.includes('10.06 ms → 4.85 ms'));
});

console.log(`\n${passed} passed`);
