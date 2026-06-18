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

  it('resolves type via snake_case when profile and schema keys differ from original header', () => {
    const results = {
      health: { rows: 50, dtypes: { district: 'numeric' } },
      schema: { District: 'numeric' },
      column_profiles: {
        district: { missing_ratio: 0, datatype: 'numeric', cardinality: 3 },
      },
      column_normalization: [
        {
          original_name: 'District',
          normalized_name: 'district',
          canonical_name: 'district',
          display_name: 'District',
        },
      ],
    } as AnalysisResult;
    const stats = resolveColumnProfileStats('District', 'district', results);
    expect(stats.type).toBe('numeric');
  });

  it('falls back to profiling_summary when top-level profiles are absent', () => {
    const results = {
      profiling_summary: {
        health: { rows: 10, dtypes: { stratum: 'numeric' } },
        schema: { stratum: 'numeric' },
        column_profiles: {
          stratum: { missing_ratio: 0, datatype: 'numeric', cardinality: 2 },
        },
      },
      column_normalization: [
        {
          original_name: 'Stratum',
          canonical_name: 'stratum',
          normalized_name: 'stratum',
        },
      ],
    } as AnalysisResult;
    const stats = resolveColumnProfileStats('Stratum', 'stratum', results);
    expect(stats.type).toBe('numeric');
  });

  it('marks constant columns as auxiliary', () => {
    const results = {
      health: { rows: 100 },
      column_profiles: {
        survey_round: {
          missing_ratio: 0,
          datatype: 'numeric',
          cardinality: 1,
          is_auxiliary: true,
          constant_value: 68,
          top_values: [{ value: 68, count: 100 }],
        },
      },
      column_normalization: [
        {
          original_name: 'Round',
          canonical_name: 'survey_round',
          normalized_name: 'survey_round',
        },
      ],
    } as AnalysisResult;
    const stats = resolveColumnProfileStats('Round', 'survey_round', results);
    expect(stats.isAuxiliary).toBe(true);
    expect(stats.type).toBe('auxiliary');
    expect(stats.constantValue).toBe(68);
    expect(stats.storageType).toBe('numeric');
  });

  it('infers auxiliary from cardinality when flag is absent', () => {
    const results = {
      health: { rows: 50 },
      column_profiles: {
        state_code: {
          missing_ratio: 0,
          datatype: 'string',
          cardinality: 1,
          top_values: [{ value: 'DL', count: 50 }],
        },
      },
    } as AnalysisResult;
    const stats = resolveColumnProfileStats('state_code', 'state_code', results);
    expect(stats.isAuxiliary).toBe(true);
    expect(stats.type).toBe('auxiliary');
  });
});

describe('buildNormalizationPlan', () => {
  it('uses canonical_name as profileKey for API rows', () => {
    const plan = buildNormalizationPlan(fixtureResults());
    const pop = plan.find((p) => p.originalName === 'pop_cnt');
    expect(pop?.profileKey).toBe('population_count');
  });
});
