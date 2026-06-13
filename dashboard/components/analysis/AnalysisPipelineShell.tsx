'use client';

import WorkflowStepper from '@/components/layout/WorkflowStepper';
import AnalysisStepper from '@/components/analysis/AnalysisStepper';
import PageHeader from '@/components/layout/PageHeader';

interface Props {
  analysisId: number;
  currentStep: number;
  title: string;
  description?: string;
  children: React.ReactNode;
}

export default function AnalysisPipelineShell({
  analysisId,
  currentStep,
  title,
  description,
  children,
}: Props) {
  return (
    <div className="pb-12">
      <WorkflowStepper currentStep={3} className="mb-5" />
      <AnalysisStepper
        analysisId={analysisId}
        currentStep={currentStep}
        className="mb-8"
      />
      <PageHeader title={title} description={description} />
      {children}
    </div>
  );
}
