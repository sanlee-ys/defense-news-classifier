/**
 * Browser-side inference for the ADR-017 classical baseline.
 *
 * Dependency-free ES module. Pair it with `web/baseline_export.json`, produced by
 * `scripts/export_baseline.py` from the same fit that ADR-017 measured. The whole
 * model is a vocabulary, an idf vector, and one coefficient matrix per axis, so
 * "run the classical baseline" is a few hundred multiply-adds — fast enough to
 * classify on every keystroke.
 *
 * This file reimplements scikit-learn's `TfidfVectorizer` transform path by hand.
 * That is the risky part, and it is not trusted: `scripts/parity_check.mjs` runs
 * this module over the 54-row gold set and asserts the labels and decision scores
 * match sklearn's own to 1e-6. CI fails closed if they drift.
 *
 * The pipeline, in sklearn's order:
 *   1. lowercase (if configured)
 *   2. tokenize with `token_pattern` — the default `(?u)\b\w\w+\b` is every run
 *      of word characters of length >= 2
 *   3. drop stop words — this happens BEFORE n-grams are built, so bigrams join
 *      tokens that were only adjacent after the stop words were removed
 *      ("strike on the carrier" -> "strike carrier"). Getting this wrong is the
 *      classic silent-mismatch bug, which is why the exact list ships in the JSON
 *      rather than being guessed at here.
 *   4. count n-grams that are in the vocabulary (unknown terms are dropped)
 *   5. multiply by idf, then L2-normalise — normalisation comes AFTER the idf
 *      weighting, not before
 *   6. per axis: scores = coef · x + intercept, label = argmax
 *
 * @module baseline_infer
 */

/**
 * Build a reusable inference context from a loaded export.
 *
 * Doing this once avoids rebuilding the stop-word set and the token regex on
 * every call, which matters if the caller classifies as the user types.
 *
 * @param {object} model Parsed `baseline_export.json`.
 * @returns {object} Opaque context for {@link classify}.
 */
export function prepare(model) {
  const cfg = model.vectorizer;
  if (cfg.analyzer !== "word") {
    throw new Error(`unsupported analyzer: ${cfg.analyzer}`);
  }
  if (cfg.strip_accents) {
    throw new Error(`unsupported strip_accents: ${cfg.strip_accents}`);
  }
  if (cfg.norm !== "l2" && cfg.norm !== null) {
    throw new Error(`unsupported norm: ${cfg.norm}`);
  }
  return {
    model,
    cfg,
    stopWords: new Set(cfg.stop_words || []),
    tokenRe: tokenRegex(cfg.token_pattern),
  };
}

/**
 * Translate a Python token pattern into an equivalent JS regex.
 *
 * Only the sklearn default is supported, deliberately: JS `\w` is ASCII-only
 * while Python's is Unicode-aware, so a blind translation would silently split
 * non-ASCII text differently. The default is rewritten to an explicit
 * Unicode-property class; anything else is rejected loudly rather than
 * approximated.
 *
 * @param {string} pattern The `token_pattern` recorded in the export.
 * @returns {RegExp} A global regex whose matches are the tokens.
 */
function tokenRegex(pattern) {
  if (pattern !== "(?u)\\b\\w\\w+\\b") {
    throw new Error(`unsupported token_pattern: ${pattern}`);
  }
  // `\b\w\w+\b` is greedy and anchored on both sides by word boundaries, so it
  // matches exactly the maximal runs of word characters of length >= 2 (runs of
  // length 1 produce no match at all).
  return /[\p{L}\p{N}_]{2,}/gu;
}

/**
 * Tokenize, drop stop words, and emit the configured n-grams.
 *
 * @param {string} text Raw input text.
 * @param {object} ctx Context from {@link prepare}.
 * @returns {string[]} The n-grams, in document order.
 */
export function analyze(text, ctx) {
  const { cfg, stopWords, tokenRe } = ctx;
  const source = cfg.lowercase ? String(text).toLowerCase() : String(text);
  tokenRe.lastIndex = 0;
  const tokens = [];
  let match;
  while ((match = tokenRe.exec(source)) !== null) {
    if (!stopWords.has(match[0])) tokens.push(match[0]);
  }
  const [minN, maxN] = cfg.ngram_range;
  const grams = [];
  for (let n = minN; n <= maxN; n += 1) {
    if (n === 1) {
      for (const t of tokens) grams.push(t);
      continue;
    }
    for (let i = 0; i + n <= tokens.length; i += 1) {
      grams.push(tokens.slice(i, i + n).join(" "));
    }
  }
  return grams;
}

/**
 * Build the sparse tf-idf feature vector for one document.
 *
 * @param {string} text Raw input text.
 * @param {object} ctx Context from {@link prepare}.
 * @returns {Map<number, number>} Feature index -> weight (zeros omitted).
 */
export function vectorize(text, ctx) {
  const { model, cfg } = ctx;
  const counts = new Map();
  for (const gram of analyze(text, ctx)) {
    const index = model.vocabulary[gram];
    if (index === undefined) continue;
    counts.set(index, (counts.get(index) || 0) + 1);
  }

  const weights = new Map();
  for (const [index, count] of counts) {
    let tf = count;
    if (cfg.binary) tf = 1;
    else if (cfg.sublinear_tf) tf = 1 + Math.log(tf);
    // smooth_idf is already baked into the exported idf vector; there is nothing
    // to recompute here, which is precisely why the vector is exported.
    const weight = cfg.use_idf ? tf * model.idf[index] : tf;
    if (weight !== 0) weights.set(index, weight);
  }

  if (cfg.norm === "l2") {
    let sumsq = 0;
    for (const w of weights.values()) sumsq += w * w;
    const norm = Math.sqrt(sumsq);
    // An all-unknown document normalises to the zero vector, exactly as sklearn
    // leaves it — the prediction then falls out of the intercepts alone.
    if (norm > 0) {
      for (const [index, w] of weights) weights.set(index, w / norm);
    }
  }
  return weights;
}

/**
 * Classify raw text on every axis in the export.
 *
 * @param {string} text The headline or snippet to classify.
 * @param {object} model Parsed `baseline_export.json`, or a context from
 *   {@link prepare} (pass the context when classifying repeatedly).
 * @returns {object} Axis name -> `{label, scores, probabilities}` where `scores`
 *   are the raw decision-function values (sklearn's `decision_function`) and
 *   `probabilities` are their softmax (the multinomial fit's `predict_proba`).
 *   Both are plain objects keyed by class label.
 */
export function classify(text, model) {
  const ctx = model.cfg ? model : prepare(model);
  const weights = vectorize(text, ctx);
  const out = {};
  for (const [axis, block] of Object.entries(ctx.model.axes)) {
    const raw = block.coef.map((row, k) => {
      let acc = block.intercept[k];
      for (const [index, w] of weights) acc += row[index] * w;
      return acc;
    });
    let best = 0;
    for (let k = 1; k < raw.length; k += 1) if (raw[k] > raw[best]) best = k;

    const scores = {};
    block.classes.forEach((label, k) => {
      scores[label] = raw[k];
    });
    out[axis] = {
      label: block.classes[best],
      scores,
      probabilities: softmax(block.classes, raw),
    };
  }
  return out;
}

/**
 * Numerically stable softmax over the decision scores.
 *
 * @param {string[]} labels Class labels, in the export's order.
 * @param {number[]} raw Decision-function values in the same order.
 * @returns {object} Label -> probability.
 */
function softmax(labels, raw) {
  const max = Math.max(...raw);
  const exps = raw.map((v) => Math.exp(v - max));
  const total = exps.reduce((a, b) => a + b, 0);
  const out = {};
  labels.forEach((label, k) => {
    out[label] = exps[k] / total;
  });
  return out;
}

export default classify;
