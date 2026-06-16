import { buildNormalizationPlan, resolveColumnProfileStats } from '@/lib/columnNormalization';
import type { AnalysisResult } from '@/lib/api';

function fixtureResults(): AnalysisResult {
  return {
    health: {
      rows: 100,
      missing_per_column: {
        population_count: 5,
        region_code: 0,
      },
    },
    schema: {
      population_count: 'int64',
      region_code: 'object',
    },
    column_profiles: {
      population_count: { missing_ratio: 0.05, datatype: 'int64' },
      region_code: { missing_ratio: 0, datatype: 'object' },
    },
    column_normalization: [
      {
        original_name: 'pop_cnt',
        normalized_name: 'Population Count',
        canonical_name: 'population_count',
        display_name: 'Population Count',
      },
      {
        original_name: 'region',
        normalized_name: 'Region Code',
        canonical_name: 'region_code',
        display_name: 'Region Code',
      },
    ],
  } as AnalysisResult;
}

describe('resolveColumnProfileStats', () => {
  it('resolves missing ratio via canonical_name when original header differs', () => {
    const results = fixtureResults();
    const stats = resolveColumnProfileStats('pop_cnt', 'population_count', results);
    expect(stats.missingRatio).toBeCloseTo(0.05, 5);
    expect(stats.missingCount).toBe(5);
  });

  it('matches Step 1 when health reports zero but profile has missing_ratio', () => {
    const results = fixtureResults();
    results.health = {
      rows: 100,
      missing_per_column: {
        population_count: 5,
        region_code: 0,
      },
    };
    results.column_profiles = {
      ...results.column_profiles,
      region_code: { missing_ratio: 0.03, datatype: 'object' },
    };
    const stats = resolveColumnProfileStats('region', 'region_code', results);
    expect(stats.missingRatio).toBeCloseTo(0.03, 5);
    expect(stats.missingCount).toBe(3);
  });
});

describe('buildNormalizationPlan', () => {
  it('uses canonical_name as profileKey for API rows', () => {
    const plan = buildNormalizationPlan(fixtureResults());
    const pop = plan.find((p) => p.originalName === 'pop_cnt');
    expect(pop?.profileKey).toBe('population_count');
  });
});
