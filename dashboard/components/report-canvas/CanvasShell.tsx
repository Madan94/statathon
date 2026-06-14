'use client';
import { useEffect } from 'react';
import { generatePhaseApi } from '@/lib/api';
import { useCanvasState } from './engine/useCanvasState';
import { useGeneration } from './engine/useGeneration';
import { TopNavBar } from './toolbar/TopNavBar';
import { FormatRibbon } from './toolbar/FormatRibbon';
import { A4Page } from './viewport/A4Page';
import { PageNavigator } from './viewport/PageNavigator';
import { LeftPanel } from './panels/LeftPanel';
import { RightPanel } from './panels/RightPanel';

/* ═══════════════════════════════════════════════════════════════════
   CanvasShell — main layout orchestrator.
   Composes: TopNav + FormatRibbon + [Left | Viewport | Right]
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  templateId: string;
  signature: string;
}

export function CanvasShell({ templateId, signature }: Props) {
  const state = useCanvasState(templateId, signature);
  const { phase, setPhase, queue, setQueue, pages, currentPage, panel, togglePanel,
    addPage, goToPage, nextPage, prevPage, addBlockToPage, updateBlock,
    currentPageBlocks, selectedBlock, setSelectedBlockId, selectedBlockId,
    doneBlocks, totalBlocks, progress, setGenerating, getPageBlocks } = state;

  const generation = useGeneration({
    templateId, signature, queue, addBlockToPage, updateBlock,
    pages, addPage, setPhase: setPhase as (p: 'generating' | 'paused' | 'complete') => void,
    setGenerating,
  });

  // Load queue on mount
  useEffect(() => {
    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then(q => { setQueue(q || []); setPhase('ready'); })
      .catch(() => setPhase('ready'));
  }, [templateId, signature, setQueue, setPhase]);

  const reportTitle = templateId.replace(/^tpl_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#f0f2f5]">
      {/* Toolbar rows */}
      <TopNavBar
        title={reportTitle}
        progress={progress}
        doneCount={doneBlocks}
        totalCount={totalBlocks || queue.length}
        phase={phase}
        panel={panel}
        onTogglePanel={togglePanel}
        onAutoGenerate={generation.autoGenerate}
        onPause={generation.pause}
        onResume={generation.resume}
        pdfUrl={generatePhaseApi.reportPdfUrl(templateId, signature)}
      />
      <FormatRibbon />

      {/* Main area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel */}
        {panel === 'left' && (
          <LeftPanel pages={pages} currentPage={currentPage} onGoToPage={goToPage} getPageBlocks={getPageBlocks} />
        )}

        {/* Center: Page viewport */}
        <div className="flex flex-1 flex-col items-center justify-center overflow-hidden p-4">
          <div className="flex-1 flex items-center justify-center w-full overflow-hidden">
            <A4Page
              blocks={currentPageBlocks}
              pageNumber={currentPage + 1}
              totalPages={pages.length}
              selectedBlockId={selectedBlockId}
              onSelectBlock={setSelectedBlockId}
              onGenerate={(idx) => generation.generateOne(idx)}
            />
          </div>
          <PageNavigator
            current={currentPage}
            total={pages.length}
            onPrev={prevPage}
            onNext={nextPage}
            onAddPage={addPage}
          />
        </div>

        {/* Right panel */}
        {panel === 'right' && (
          <RightPanel
            selectedBlock={selectedBlock}
            onClose={() => togglePanel('right')}
            onRegenerate={(idx) => generation.generateOne(idx)}
          />
        )}
      </div>
    </div>
  );
}
