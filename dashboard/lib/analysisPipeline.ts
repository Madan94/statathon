/** Hub steps 1–5 live on `/analysis/[id]`; steps 6–8 are dedicated routes. */

export const HUB_STEP_COUNT = 5;

export function analysisRoutes(analysisId: number) {
  return {
    hub: `/analysis/${analysisId}`,
    hubStep: (step: number) => `/analysis/${analysisId}?step=${step}`,
    validation: `/analysis/${analysisId}/validation`,
    columns: `/analysis/${analysisId}/columns`,
    weights: `/analysis/${analysisId}/weights`,
    review: `/analysis/${analysisId}/review`,
  };
}

function sessionKey(analysisId: number) {
  return `analysis-step-${analysisId}`;
}

export function saveHubStep(analysisId: number, step: number) {
  if (typeof window === 'undefined') return;
  const clamped = Math.min(Math.max(step, 1), HUB_STEP_COUNT);
  sessionStorage.setItem(sessionKey(analysisId), String(clamped));
}

export function loadHubStep(analysisId: number): number {
  if (typeof window === 'undefined') return 1;
  const raw = sessionStorage.getItem(sessionKey(analysisId));
  const n = raw ? parseInt(raw, 10) : 1;
  return n >= 1 && n <= HUB_STEP_COUNT ? n : 1;
}

export function stepHref(analysisId: number, stepId: number): string {
  const routes = analysisRoutes(analysisId);
  if (stepId <= HUB_STEP_COUNT) return routes.hubStep(stepId);
  if (stepId === 6) return routes.validation;
  if (stepId === 7) return routes.columns;
  if (stepId === 8) return routes.weights;
  return routes.review;
}
