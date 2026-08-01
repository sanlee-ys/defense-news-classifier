/**
 * Parity gate: the browser port must reproduce scikit-learn exactly.
 *
 * Runs `web/baseline_infer.js` over the same texts sklearn was run over in
 * `scripts/generate_parity_fixture.py` and asserts, for every row and every axis,
 * that the predicted label is identical and every decision score matches within
 * the fixture's tolerance. Exits 1 on the first disagreement (after reporting all
 * of them), so CI fails closed.
 *
 * Deliberately zero-dependency and runnable with bare `node` — no package.json,
 * no install step. That keeps the gate cheap enough to leave wired into every PR.
 *
 * Run:
 *     node scripts/parity_check.mjs
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { classify, prepare, vectorize } from "../web/baseline_infer.js";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const EXPORT_PATH = join(REPO_ROOT, "web", "baseline_export.json");
const FIXTURE_PATH = join(REPO_ROOT, "tests", "fixtures", "baseline_parity.json");

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf-8"));
}

function main() {
  const model = readJson(EXPORT_PATH);
  const fixture = readJson(FIXTURE_PATH);
  const tolerance = fixture.tolerance ?? 1e-6;

  // A fixture generated from a different fit would compare two unrelated models
  // and could pass or fail for the wrong reason. Pin them to the same training
  // content before comparing anything.
  if (
    fixture.export_train_content_sha256 !==
    model.metadata.train_content_sha256
  ) {
    console.error(
      "FAIL: fixture and export disagree on the training content hash.\n" +
        `  fixture: ${fixture.export_train_content_sha256}\n` +
        `  export : ${model.metadata.train_content_sha256}\n` +
        "  Re-run scripts/export_baseline.py then scripts/generate_parity_fixture.py.",
    );
    process.exit(1);
  }

  const ctx = prepare(model);
  const failures = [];
  let comparisons = 0;
  // A gate is only as good as its coverage. An earlier draft of this check ran on
  // the 54 gold rows alone, and perturbing a coefficient for a term none of them
  // contained left it green — the check could not fail. The fixture now carries
  // the training texts too, and this set proves it: every vocabulary column must
  // be exercised by at least one row, or the gate is lying about what it covers.
  const touched = new Set();

  for (const row of fixture.rows) {
    for (const index of vectorize(row.text, ctx).keys()) touched.add(index);
    const actual = classify(row.text, ctx);
    for (const [axis, expected] of Object.entries(row.expected)) {
      const got = actual[axis];
      if (!got) {
        failures.push(`${row.id} / ${axis}: axis missing from the export`);
        continue;
      }
      if (got.label !== expected.label) {
        failures.push(
          `${row.id} / ${axis}: label ${JSON.stringify(got.label)} != ${JSON.stringify(expected.label)}`,
        );
      }
      const classes = fixture.axes[axis];
      if (classes.length !== expected.scores.length) {
        failures.push(`${row.id} / ${axis}: class-count mismatch`);
        continue;
      }
      classes.forEach((label, k) => {
        const delta = Math.abs(got.scores[label] - expected.scores[k]);
        comparisons += 1;
        if (!(delta <= tolerance)) {
          failures.push(
            `${row.id} / ${axis} / ${label}: score ${got.scores[label]} != ${expected.scores[k]} (delta ${delta.toExponential(3)})`,
          );
        }
      });
    }
  }

  const vocabSize = Object.keys(model.vocabulary).length;
  if (touched.size !== vocabSize) {
    failures.push(
      `coverage: only ${touched.size}/${vocabSize} vocabulary terms are exercised ` +
        "by the fixture — a coefficient change on an untouched term could not be caught",
    );
  }

  if (failures.length > 0) {
    console.error(`PARITY FAILED: ${failures.length} disagreement(s)`);
    for (const line of failures.slice(0, 40)) console.error(`  ${line}`);
    if (failures.length > 40) {
      console.error(`  ... and ${failures.length - 40} more`);
    }
    process.exit(1);
  }

  console.log(
    `parity OK: ${fixture.rows.length} rows x ${Object.keys(fixture.axes).length} axes, ` +
      `${comparisons} scores within ${tolerance}; ` +
      `${touched.size}/${vocabSize} vocabulary terms exercised`,
  );
}

main();
