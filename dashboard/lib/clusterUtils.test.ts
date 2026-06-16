import { normalizeClusterGroup, normalizeDomainDistribution, formatDistributionPct } from '@/lib/clusterUtils';

describe('normalizeDomainDistribution', () => {
  it('normalizes vote counts to sum 100', () => {
    const result = normalizeDomainDistribution({
      survey_metadata: 7,
      demographic: 2,
      geography: 2,
    });
    const total = Object.values(result).reduce((a, b) => a + b, 0);
    expect(Math.round(total)).toBe(100);
    expect(result.survey_metadata).toBeCloseTo(63.636, 1);
  });

  it('uses fallback domain when distribution missing', () => {
    const result = normalizeDomainDistribution(undefined, 'demographic', 2);
    expect(result).toEqual({ demographic: 100 });
  });

  it('formats small percentages', () => {
    expect(formatDistributionPct(0.4)).toBe('<1%');
    expect(formatDistributionPct(54.6)).toBe('55%');
  });
});

describe('normalizeClusterGroup', () => {
  it('maps V2 cluster fields to UI shape', () => {
    const cl = normalizeClusterGroup({
      cluster_id: 'cluster_0',
      domain: '',
      support_score: 0,
      columns: ['age'],
      dominant_domain: 'demographic',
      purity: 0.9,
      cluster_confidence: 0.8,
      embedding_coherence: 0.75,
    } as never);
    expect(cl.domain).toBe('demographic');
    expect(cl.domain_purity).toBe(0.9);
    expect(cl.support_score).toBe(0.8);
    expect(cl.embedding_coherence).toBe(0.75);
  });
});
