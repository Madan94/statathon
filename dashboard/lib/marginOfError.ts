/**
 * Weighted margin-of-error statistics — a faithful, dependency-free port of the
 * officer reference (Python):
 *
 *   ws = DescrStatsW(data=values, weights=weights, ddof=1)
 *   weighted_mean  = ws.mean
 *   standard_error = ws.std_mean
 *   moe            = stats.norm.ppf(0.975) * standard_error          # z-based
 *   lower, upper   = ws.tconfint_mean(alpha=0.05)                    # t-based
 *
 * Validated against statsmodels for the textbook example
 *   income = [50000, 60000, 45000, 80000], survey_weight = [100, 250, 150, 50]
 *   → mean 55909.0909 · SE 425.0223 · MoE(z) ±833.0285 · MoE(t,df=549) ±834.8690
 *   → 95% CI [55074.2219, 56743.9599] · RSE 0.7602% · Kish nₑff 3.1026
 *
 * Algebra note: DescrStatsW's standard error of the weighted mean reduces to
 *   SE = √( Σwᵢ(xᵢ − x̄_w)² / ( N·(N−1) ) ),  N = Σwᵢ
 * (identical for ddof 0/1), with the t-interval using df = N − 1. This is the
 * "frequency weight" interpretation (each weight = number of population units a
 * row represents). For survey *sampling* weights, where uncertainty is driven by
 * the number of sampled rows, we also expose a design-based (Hájek linearization)
 * standard error so officers can see the more conservative estimate.
 */

// ── Confidence levels offered in the UI ──────────────────────────────────────
export const CONFIDENCE_LEVELS = [0.9, 0.95, 0.99] as const;
export type ConfidenceLevel = (typeof CONFIDENCE_LEVELS)[number];

export type WeightMode = 'frequency' | 'sampling';

// ── Quality bands (relative standard error) ──────────────────────────────────
// Standard official-statistics convention (e.g. ABS/NSO): RSE < 16.6% reliable,
// 16.6–33.3% use with caution, > 33.3% too unreliable for general use.
export type QualityKey = 'good' | 'caution' | 'unreliable' | 'unknown';

export interface QualityBand {
  key: QualityKey;
  label: string;
  description: string;
  color: string;
}

export const QUALITY_BANDS: Record<QualityKey, QualityBand> = {
  good: {
    key: 'good',
    label: 'Reliable',
    description: 'Relative standard error below 16.6% — suitable for general use.',
    color: '#16a34a',
  },
  caution: {
    key: 'caution',
    label: 'Use with caution',
    description: 'Relative standard error 16.6%–33.3% — interpret carefully.',
    color: '#d97706',
  },
  unreliable: {
    key: 'unreliable',
    label: 'Unreliable',
    description: 'Relative standard error above 33.3% — too imprecise for general use.',
    color: '#e11d48',
  },
  unknown: {
    key: 'unknown',
    label: 'Not assessable',
    description: 'Quality could not be assessed (estimate is zero or undefined).',
    color: '#64748b',
  },
};

export function qualityFromRse(rse: number): QualityBand {
  if (!Number.isFinite(rse)) return QUALITY_BANDS.unknown;
  if (rse < 0.166) return QUALITY_BANDS.good;
  if (rse <= 0.333) return QUALITY_BANDS.caution;
  return QUALITY_BANDS.unreliable;
}

// ── Distribution quantiles ───────────────────────────────────────────────────

/** Inverse standard-normal CDF (Acklam's rational approximation, |err| < 1.2e-9). */
export function inverseNormalCdf(p: number): number {
  if (p <= 0) return -Infinity;
  if (p >= 1) return Infinity;
  const a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.38357751867269e2, -3.066479806614716e1, 2.506628277459239];
  const b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1];
  const c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
  const d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416];
  const pLow = 0.02425;
  const pHigh = 1 - pLow;
  if (p < pLow) {
    const q = Math.sqrt(-2 * Math.log(p));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
      ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (p <= pHigh) {
    const q = p - 0.5;
    const r = q * q;
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q /
      (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }
  const q = Math.sqrt(-2 * Math.log(1 - p));
  return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) /
    ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
}

/**
 * Inverse Student-t CDF via the Cornish–Fisher expansion of the normal quantile
 * (4 correction terms). Accurate to ≲0.2% for df ≥ 3 and converges to the normal
 * quantile as df → ∞. Adequate for confidence-interval critical values.
 */
export function inverseStudentT(p: number, df: number): number {
  const z = inverseNormalCdf(p);
  if (!Number.isFinite(z) || df <= 0) return z;
  if (df > 2000) return z; // t ≈ z for large df
  const z2 = z * z;
  const z3 = z2 * z;
  const z5 = z3 * z2;
  const z7 = z5 * z2;
  const z9 = z7 * z2;
  const g1 = (z3 + z) / 4;
  const g2 = (5 * z5 + 16 * z3 + 3 * z) / 96;
  const g3 = (3 * z7 + 19 * z5 + 17 * z3 - 15 * z) / 384;
  const g4 = (79 * z9 + 776 * z7 + 1482 * z5 - 1920 * z3 - 945 * z) / 92160;
  return z + g1 / df + g2 / (df * df) + g3 / (df * df * df) + g4 / (df * df * df * df);
}

// ── Core computation ─────────────────────────────────────────────────────────

export interface MoEResult {
  valid: boolean;
  reason?: string;
  mode: WeightMode;
  confidence: ConfidenceLevel;

  rowsUsed: number;
  rowsSkipped: number;
  nonPositiveWeights: number;
  uniformWeights: boolean;

  sumWeights: number; // N = Σw
  weightedMean: number; // estimate
  unweightedMean: number;
  weightedStd: number; // σ̂ (ddof = 1)

  standardError: number; // SE for the active mode
  df: number; // degrees of freedom for the active mode
  zCritical: number; // normal critical value
  tCritical: number; // t critical value (active df)

  marginOfError: number; // t-based ± half-width (primary, matches tconfint_mean)
  marginOfErrorZ: number; // z-based ± half-width (matches the reference `moe`)
  lower: number; // weightedMean − marginOfError
  upper: number; // weightedMean + marginOfError

  rse: number; // relative standard error = SE / |mean|
  relativeMoE: number; // marginOfError / |mean|
  cv: number; // coefficient of variation = std / |mean|
  effectiveSampleSize: number; // Kish nₑff = (Σw)² / Σ(w²)
  designEffect: number; // rowsUsed / nₑff

  /** Frequency-weight SE (always computed, for the cross-check panel). */
  seFrequency: number;
  /** Design-based Hájek SE (always computed, for the cross-check panel). */
  seSampling: number;

  quality: QualityBand;
}

export interface MoEPair {
  value: number | null;
  weight: number | null;
}

/**
 * Compute the weighted estimate and its margin of error for one value column
 * against one weight/multiplier column.
 */
export function computeWeightedMoE(
  pairs: MoEPair[],
  confidence: ConfidenceLevel,
  mode: WeightMode = 'frequency',
): MoEResult {
  const alpha = 1 - confidence;
  const zCritical = inverseNormalCdf(1 - alpha / 2);

  const base: MoEResult = {
    valid: false,
    mode,
    confidence,
    rowsUsed: 0,
    rowsSkipped: 0,
    nonPositiveWeights: 0,
    uniformWeights: false,
    sumWeights: 0,
    weightedMean: NaN,
    unweightedMean: NaN,
    weightedStd: NaN,
    standardError: NaN,
    df: 0,
    zCritical,
    tCritical: NaN,
    marginOfError: NaN,
    marginOfErrorZ: NaN,
    lower: NaN,
    upper: NaN,
    rse: NaN,
    relativeMoE: NaN,
    cv: NaN,
    effectiveSampleSize: NaN,
    designEffect: NaN,
    seFrequency: NaN,
    seSampling: NaN,
    quality: QUALITY_BANDS.unknown,
  };

  // 1. Keep only rows with a finite value and a strictly positive finite weight.
  const xs: number[] = [];
  const ws: number[] = [];
  let skipped = 0;
  let nonPositive = 0;
  for (const { value, weight } of pairs) {
    if (value == null || weight == null || !Number.isFinite(value) || !Number.isFinite(weight)) {
      skipped += 1;
      continue;
    }
    if (weight <= 0) {
      skipped += 1;
      nonPositive += 1;
      continue;
    }
    xs.push(value);
    ws.push(weight);
  }
  base.rowsUsed = xs.length;
  base.rowsSkipped = skipped;
  base.nonPositiveWeights = nonPositive;

  if (xs.length === 0) {
    return { ...base, reason: 'No rows have both a numeric value and a positive weight.' };
  }

  // 2. Weighted mean and dispersion.
  const N = ws.reduce((s, w) => s + w, 0);
  const weightedSum = xs.reduce((s, x, i) => s + x * ws[i], 0);
  const rawSum = xs.reduce((s, x) => s + x, 0);
  const mean = weightedSum / N;
  const unweightedMean = rawSum / xs.length;
  base.sumWeights = N;
  base.weightedMean = mean;
  base.unweightedMean = unweightedMean;

  const uniform = ws.every((w) => w === ws[0]);
  base.uniformWeights = uniform;

  if (xs.length < 2) {
    return { ...base, reason: 'At least two valid rows are required to estimate a margin of error.' };
  }
  if (N <= 1) {
    return { ...base, reason: 'The sum of weights must exceed 1 to estimate variance.' };
  }

  const ss = xs.reduce((s, x, i) => s + ws[i] * (x - mean) ** 2, 0); // Σ w (x − x̄)²
  const variance = ss / (N - 1); // weighted sample variance (ddof = 1)
  const weightedStd = Math.sqrt(variance);
  base.weightedStd = weightedStd;

  // Kish effective sample size & design effect.
  const sumW2 = ws.reduce((s, w) => s + w * w, 0);
  const nEff = (N * N) / sumW2;
  base.effectiveSampleSize = nEff;
  base.designEffect = nEff > 0 ? xs.length / nEff : NaN;

  // 3a. Frequency-weight SE (statsmodels DescrStatsW): SE = √( SS / (N·(N−1)) ), df = N − 1.
  const seFrequency = Math.sqrt(ss / (N * (N - 1)));
  // 3b. Design-based Hájek linearization SE: √( n/(n−1) · Σ (wᵢ/N)² (xᵢ − x̄)² ), df = n − 1.
  const n = xs.length;
  const seSamplingSq = (n / (n - 1)) * xs.reduce((s, x, i) => s + (ws[i] / N) ** 2 * (x - mean) ** 2, 0);
  const seSampling = Math.sqrt(seSamplingSq);
  base.seFrequency = seFrequency;
  base.seSampling = seSampling;

  // 4. Select the active mode.
  const standardError = mode === 'sampling' ? seSampling : seFrequency;
  const df = mode === 'sampling' ? n - 1 : N - 1;
  const tCritical = inverseStudentT(1 - alpha / 2, df);
  base.standardError = standardError;
  base.df = df;
  base.tCritical = tCritical;

  const marginOfError = tCritical * standardError; // t-based (primary)
  const marginOfErrorZ = zCritical * standardError; // z-based (reference parity)
  base.marginOfError = marginOfError;
  base.marginOfErrorZ = marginOfErrorZ;
  base.lower = mean - marginOfError;
  base.upper = mean + marginOfError;

  // 5. Relative measures & quality band.
  const absMean = Math.abs(mean);
  const rse = absMean > 0 ? standardError / absMean : NaN;
  base.rse = rse;
  base.relativeMoE = absMean > 0 ? marginOfError / absMean : NaN;
  base.cv = absMean > 0 ? weightedStd / absMean : NaN;
  base.quality = qualityFromRse(rse);

  base.valid = true;
  return base;
}

// ── Worked textbook example (also used by the "Load example" affordance) ─────
export const MOE_EXAMPLE = {
  valueColumn: 'income',
  weightColumn: 'survey_weight',
  headers: ['income', 'survey_weight'],
  rows: [
    ['50000', '100'],
    ['60000', '250'],
    ['45000', '150'],
    ['80000', '50'],
  ] as string[][],
};
