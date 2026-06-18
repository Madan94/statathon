import {
  isVariableAnalysisColumn,
  orderedVariableColumns,
  resolveAnalysisRole,
  skippedColumnSummary,
} from '@/lib/columnAnalysisUtils';
import type { AnalysisResult } from '@/lib/api';

function fixtureResults(): AnalysisResult {
  return {
    health: { rows: 100, missing_per_column: { expense: 2, district: 0, survey_round: 0 } },
    schema: {
      district: 'object',
      expense: 'float64',
      survey_round: 'int64',
    },
    column_profiles: {
      district: { missing_ratio: 0, datatype: 'object', cardinality: 10 },
      expense: { missing_ratio: 0.02, datatype: 'float64', cardinality: 50 },
      survey_round: {
        missing_ratio: 0,
        datatype: 'int64',
        cardinality: 1,
        is_auxiliary: true,
        constant_value: 68,
      },
    },
    semantic_mapping: [
      { column: 'district', domain: 'geography', analysis_role: 'identifier' },
      { column: 'expense', domain: 'food_expenditure', analysis_role: 'variable' },
      { column: 'survey_round', domain: 'metadata', analysis_role: 'variable' },
    ],
  } as AnalysisResult;
}

describe('columnAnalysisUtils', () => {
  it('resolves identifier vs variable roles', () => {
    const results = fixtureResults();
    expect(resolveAnalysisRole('district', results)).toBe('identifier');
    expect(resolveAnalysisRole('expense', results)).toBe('variable');
    expect(resolveAnalysisRole('unknown_col', results)).toBe('variable');
  });

  it('excludes identifiers and auxiliary columns from variable analysis', () => {
    const results = fixtureResults();
    expect(isVariableAnalysisColumn('district', results)).toBe(false);
    expect(isVariableAnalysisColumn('survey_round', results)).toBe(false);
    expect(isVariableAnalysisColumn('expense', results)).toBe(true);
  });

  it('orders variable columns by domain', () => {
    const results = fixtureResults();
    expect(orderedVariableColumns(results)).toEqual(['expense']);
  });

  it('summarizes skipped identifier and auxiliary columns', () => {
    const results = fixtureResults();
    const summary = skippedColumnSummary(results);
    expect(summary.identifiers).toEqual(['district']);
    expect(summary.auxiliary).toEqual(['survey_round']);
    expect(summary.skippedCount).toBe(2);
  });

  it('matches semantic rows via snake_case alias', () => {
    const results = fixtureResults();
    results.semantic_mapping = [
      { column: 'District Code', domain: 'geography', analysis_role: 'identifier' },
    ];
    results.schema = { district_code: 'object' };
    results.column_profiles = {
      district_code: { missing_ratio: 0, datatype: 'object', cardinality: 5 },
    };
    expect(resolveAnalysisRole('district_code', results)).toBe('identifier');
    expect(isVariableAnalysisColumn('district_code', results)).toBe(false);
  });
});
