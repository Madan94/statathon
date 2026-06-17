'use client';
import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { generatePhaseApi, authApi, type CanvasDraftSummary } from '@/lib/api';
import type { GeneratedSectionBlock, ReportSectionRequest } from '@/lib/report-section';
import { useCanvasState } from './engine/useCanvasState';
import { useGeneration } from './engine/useGeneration';
import { useCanvasAgent } from './engine/useCanvasAgent';
import { useLayoutPersistence } from './engine/useLayoutPersistence';
import { useDocumentModel } from './engine/useDocumentModel';
import { useBundleModel } from './engine/useBundleModel';
import { useReviewModel } from './engine/useReviewModel';
import { computeLayoutDigest } from './engine/paginationEngine';
import { buildSuggestions } from './engine/assistantOrchestrator';
import { rowMarkers } from './engine/statMarkers';
import { DEFAULT_TYPOGRAPHY, toCSSVars, TYPOGRAPHY_PRESETS, type TypographyConfig } from './engine/typography';
import type { PageBlock } from './engine/useCanvasState';
import { CommandBar } from './toolbar/CommandBar';
import { CanvasViewBar, type Density } from './toolbar/CanvasViewBar';
import { StatusBar } from './toolbar/StatusBar';
import { A4Page, type PageSize } from './viewport/A4Page';
import { CoverPage, ContentsPage } from './viewport/FrontMatter';
import { LeftPanel } from './panels/LeftPanel';
import { RightPanel } from './panels/RightPanel';
import { ControlPanel } from './panels/ControlPanel';
import { ReviewPanel } from './panels/ReviewPanel';
import { CanvasDraftPicker } from './panels/CanvasDraftPicker';
import { TypographyPanel } from './panels/TypographyPanel';
import { CommandPalette, type PaletteCommand } from './panels/CommandPalette';
import { SectionWorkflowModal } from './section-workflow/SectionWorkflowModal';

/* ═══════════════════════════════════════════════════════════════════
   CanvasShell — main layout orchestrator.
   Composes: CommandBar + [Left navigator | Viewport | Co-pilot] + StatusBar
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  templateId: string;
  signature: string;
}

/** Front-matter sheets (cover + contents) precede the content pages. */
const FRONT_MATTER_PAGES = 2;

export function CanvasShell({ templateId, signature }: Props) {
  const state = useCanvasState();
  const { phase, setPhase, queue, setQueue, pages, currentPage, panel, togglePanel,
    addPage, goToPage, addBlockToPage, updateBlock, removeBlock, moveBlock, reorderBlock, setFloating, resizeBlock, blocks,
    selectedBlock, setSelectedBlockId, selectedBlockId,
    setGenerating, getPageBlocks, setBlocks, order, setOrder, tableSplits, setLayoutMetrics } = state;

  const [pageSize, setPageSize] = useState<PageSize>('a4');
  const [zoom, setZoom] = useState(100);
  const [showFrontMatter, setShowFrontMatter] = useState(true);
  const [showControlPanel, setShowControlPanel] = useState(false);
  const [showReviewPanel, setShowReviewPanel] = useState(false);
  const [showTypography, setShowTypography] = useState(false);
  const [showSectionWorkflow, setShowSectionWorkflow] = useState(false);
  const [showDraftPicker, setShowDraftPicker] = useState(true);
  const [activeDraft, setActiveDraft] = useState<CanvasDraftSummary | null>(null);
  const [restoredDraftKey, setRestoredDraftKey] = useState('');
  const [restoredCanvasOwnedCount, setRestoredCanvasOwnedCount] = useState(0);
  const [viewMode, setViewMode] = useState<'paged' | 'scroll'>('scroll');
  const [showPalette, setShowPalette] = useState(false);
  const [showCheatsheet, setShowCheatsheet] = useState(false);
  /** Drives the book page-turn animation in paged mode (bumped on each turn). */
  const [flip, setFlip] = useState<{ key: number; dir: 'next' | 'prev' }>({ key: 0, dir: 'next' });
  /** In paged mode the whole document is ONE sheet sequence: Cover (0),
   *  Contents (1), then content pages. `pagedIndex` selects the visible sheet. */
  const [pagedIndex, setPagedIndex] = useState(0);
  const [density, setDensity] = useState<Density>('comfortable');
  const [focusMode, setFocusMode] = useState(false);
  /** Document typography (T6) — separate from the app UI font. */
  const [typography, setTypography] = useState<TypographyConfig>(DEFAULT_TYPOGRAPHY);
  const docStyle = useMemo(() => toCSSVars(typography), [typography]);
  // Keep page packing in sync with the live type-scale / line-height so tables
  // and text reflow onto the right pages when the officer changes typography.
  useEffect(() => {
    setLayoutMetrics(typography.typeScale, typography.lineHeight);
  }, [typography.typeScale, typography.lineHeight, setLayoutMetrics]);
  /** Authenticated officer name for the cover page (not hardcoded). */
  const [officerName, setOfficerName] = useState('');
  /** Scroll-spy: the section anchor currently at the top of the viewport.
   *  Drives the outline "you are here" so it tracks the actual heading on
   *  screen (page-granular tracking mis-highlights when sections share a page). */
  const [activeAnchor, setActiveAnchor] = useState<string | undefined>(undefined);
  /** Footnotes collected from rich-text editing (U2): global running list. */
  const [footnotes, setFootnotes] = useState<Array<{ n: number; blockId: string; text: string }>>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  /** Suppress the scroll-spy briefly after an outline click so the smooth-scroll
   *  settle doesn't override the section the officer just selected. */
  const spyLockRef = useRef(0);
  /** Stable handle to the latest nav fn + index (for the keyboard handler). */
  const navRef = useRef<{ goTo: (i: number) => void; current: number }>({ goTo: () => {}, current: 0 });
  const topicBootRef = useRef(false);
  const activeDraftKey = activeDraft ? `${templateId}::${signature}::${activeDraft.draftId}` : '';

  useEffect(() => {
    topicBootRef.current = false;
    setRestoredDraftKey('');
    setRestoredCanvasOwnedCount(0);
  }, [activeDraftKey]);

  // Add a footnote → assign the next running number, store it, return the number.
  const addFootnote = (blockId: string, text: string): number => {
    const n = footnotes.length + 1;
    setFootnotes(prev => [...prev, { n, blockId, text }]);
    return n;
  };

  // Resolve the signed-in officer for the cover page + sign-off audit.
  useEffect(() => {
    let cancelled = false;
    authApi.me()
      .then(u => { if (!cancelled) setOfficerName(u.full_name || u.email || ''); })
      .catch(() => { /* unauthenticated preview — leave blank */ });
    return () => { cancelled = true; };
  }, []);

  // Document statistics for the status bar (words / tables / figures).
  const docStats = useMemo(() => {
    let words = 0, tables = 0, figures = 0;
    for (const b of blocks.values()) {
      if (b.content) words += b.content.trim().split(/\s+/).filter(Boolean).length;
      if (b.kind === 'table') tables += 1;
      if (b.kind === 'chart') figures += 1;
    }
    return { words, tables, figures };
  }, [blocks]);

  // Derive the publication structure (numbering, captions, TOC, chapter labels).
  const docModel = useDocumentModel(order, blocks, pages);
  // Queue-based bundle progress (S2) — the honest plan truth, not block count.
  const bundle = useBundleModel(queue, blocks);
  // Editorial review layer (U4): comments, flags, status, sign-off gate.
  const review = useReviewModel();

  const generation = useGeneration({
    templateId,
    signature,
    queue,
    blocks,
    appendBlockAuto: state.appendBlockAuto,
    updateBlock,
    setPhase: setPhase as (p: 'generating' | 'paused' | 'complete') => void,
    setGenerating,
  });

  // Live page-capacity digest for the layout-aware assistant (D-L5).
  const layoutDigest = useMemo(() => {
    const ordered = order.map(id => blocks.get(id)).filter(Boolean) as PageBlock[];
    return computeLayoutDigest(ordered);
  }, [order, blocks]);

  const agent = useCanvasAgent({
    templateId, signature, queue, blocks, updateBlock, removeBlock, selectedBlock,
    regenerate: (idx) => generation.generateOne(idx),
    insertBlock: (block) => addBlockToPage(block, currentPage),
    layout: layoutDigest,
    repack: state.repack,
    goToPage,
    generateTopic: (topic) => generation.autoGenerateTopic(topic),
    retryFailed: () => generation.generateIndices(bundle.failedIndices),
  });

  // Proactive suggestions (S3 ③) — derived from live bundle + layout + tables.
  const suggestions = useMemo(() => {
    const pendingTopics = bundle.topics
      .filter(t => t.done < t.total)
      .map(t => ({ topic: t.topic, pending: t.total - t.done }));
    const unreliableTables = Object.entries(docModel.tableCaptions)
      .filter(([id]) => {
        const b = blocks.get(id);
        if (!b?.tableData) return false;
        const rows = (b.tableData.items || b.tableData.rankingData || b.tableData.aggregationData || b.tableData.rows || []) as Array<Record<string, unknown>>;
        return rows.some(r => {
          const m = rowMarkers(r, r.value as number);
          return m.used.includes('caution');
        });
      })
      .map(([, cap]) => cap);
    const emptiest = layoutDigest.pages.find(p => p.page === layoutDigest.emptiestPage);
    return buildSuggestions({
      pendingTopics,
      failedCount: bundle.failed,
      emptiestPage: emptiest ? { page: emptiest.page, fillPct: emptiest.fillPct } : undefined,
      unreliableTables,
      totalPending: bundle.pending,
    });
  }, [bundle, docModel.tableCaptions, blocks, layoutDigest]);

  // Autosave the officer's free-placement layout + restore it on reload.
  useLayoutPersistence({
    templateId,
    signature,
    draftId: activeDraft?.draftId || null,
    enabled: Boolean(activeDraft),
    blocks,
    pages,
    order,
    setBlocks,
    setOrder: state.setOrder,
    repack: state.repack,
    onRestored: (info) => {
      setRestoredCanvasOwnedCount(info.restoredCanvasOwnedBlocks);
      setRestoredDraftKey(activeDraftKey);
    },
  });

  // Load queue on mount
  useEffect(() => {
    generatePhaseApi.getGenerationQueue(templateId, signature)
      .then(q => { setQueue(q || []); setPhase('ready'); })
      .catch(() => setPhase('ready'));
  }, [templateId, signature, setQueue, setPhase]);

  // Officer default: opening this canvas auto-builds Topic 1 into a draft,
  // preserving hierarchy (Topic > Chapter > Section) across pages.
  useEffect(() => {
    if (topicBootRef.current) return;
    if (!activeDraft) return;
    if (restoredDraftKey !== activeDraftKey) return;
    // A legacy draft can contain only spatial entries for generated queue blocks
    // (block-0, block-1, ...). Those entries do not restore content, so they must
    // not suppress the first auto-build. Only content-bearing canvas-owned blocks
    // restored from the draft mean "this draft already has authored content".
    if (restoredCanvasOwnedCount > 0) return;
    if (phase !== 'ready') return;
    if (!queue.length) return;

    const bootKey = `canvas:autoBoot:${activeDraftKey}`;
    if (typeof window !== 'undefined' && window.sessionStorage.getItem(bootKey)) return;

    const topicOne = queue[0]?.section_path?.[0];
    if (!topicOne) return;

    const topicQueueCount = queue.filter(q => q.section_path?.[0] === topicOne).length;
    const topicBlocks = Array.from(blocks.values()).filter(b => b.index >= 0 && b.sectionPath?.[0] === topicOne);
    const topicDone = topicBlocks.filter(b => b.status === 'done').length;
    const topicNeedsRepair = topicBlocks.some(b => b.status === 'error' || b.status === 'pending');
    const topicAlreadyComplete = topicQueueCount > 0 && topicDone >= topicQueueCount && !topicNeedsRepair;
    if (topicAlreadyComplete) return;

    topicBootRef.current = true;
    if (typeof window !== 'undefined') window.sessionStorage.setItem(bootKey, '1');
    void generation.autoGenerateTopic(topicOne);
  }, [phase, queue, blocks, generation, activeDraft, activeDraftKey, restoredDraftKey, restoredCanvasOwnedCount]);

  const reportTitle = templateId.replace(/^tpl_/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());

  // Issuing organisation — single source for the cover crest, the cover band
  // and the running footer (no per-component hardcoding; ready for a future
  // multi-ministry settings feed).
  const reportOrg = useMemo(() => ({
    crest: 'GoI',
    ministry: 'Ministry of Statistics & Programme Implementation',
    parentBody: 'Government of India',
    footer: 'MoSPI · Government of India',
  }), []);

  // Reference period inferred from the report title if it carries a year/version,
  // else the current calendar year (never a hardcoded year).
  const referencePeriod = useMemo(() => {
    const m = reportTitle.match(/\b(19|20)\d{2}\b/);
    return m ? m[0] : String(new Date().getFullYear());
  }, [reportTitle]);

  // ── Unified viewport navigation (S5 / paged-fix) ───────────────────────
  // Paged mode treats the document as a single sheet sequence:
  //   sheet 0 = Cover, sheet 1 = Contents, sheet 2+ = content pages.
  // Scroll mode keeps the front matter as a prefix and scrolls content pages.
  const fmCount = showFrontMatter ? FRONT_MATTER_PAGES : 0;
  const totalSheets = fmCount + pages.length;
  const navCurrent = viewMode === 'paged' ? pagedIndex : currentPage;
  const navTotal = viewMode === 'paged' ? totalSheets : pages.length;
  // The active CONTENT page (0-based) for outline/thumbnail highlighting.
  // On front-matter sheets (cover/contents) there is no active section → -1.
  const activeContentPage = viewMode === 'paged'
    ? (pagedIndex >= fmCount ? pagedIndex - fmCount : -1)
    : currentPage;

  // Scroll-spy — the outline highlight follows the heading actually at the top
  // of the viewport (page-granular tracking mis-fires when several sections
  // share one page). Recomputes on scroll, resize, view-mode + sheet changes.
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const anchors = docModel.toc.map(t => t.anchor);
    if (anchors.length === 0) { setActiveAnchor(undefined); return; }
    let raf = 0;
    const compute = () => {
      raf = 0;
      if (Date.now() - spyLockRef.current < 900) return; // respect a recent click
      const rootTop = root.getBoundingClientRect().top;
      const line = rootTop + 60 * (zoom / 100); // probe scales with zoom
      let best: string | undefined;
      let bestTop = -Infinity;
      let firstAnchor: string | undefined;
      let firstTop = Infinity;
      for (const a of anchors) {
        const el = document.getElementById(a);
        if (!el) continue;
        const top = el.getBoundingClientRect().top;
        if (top < firstTop) { firstTop = top; firstAnchor = a; }
        if (top <= line && top > bestTop) { bestTop = top; best = a; }
      }
      setActiveAnchor(best ?? firstAnchor);
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(compute); };
    root.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onScroll);
    compute();
    return () => { root.removeEventListener('scroll', onScroll); window.removeEventListener('resize', onScroll); if (raf) cancelAnimationFrame(raf); };
  }, [docModel.toc, viewMode, pagedIndex, zoom]);

  /** Navigate the viewport. In paged mode this flips a single sheet (Cover →
   *  Contents → content) left-to-right; in scroll mode it scrolls to a page. */
  const navGoTo = useCallback((idx: number) => {
    if (viewMode === 'paged') {
      const total = (showFrontMatter ? FRONT_MATTER_PAGES : 0) + pages.length;
      const target = Math.max(0, Math.min(idx, total - 1));
      setPagedIndex(prev => {
        if (target !== prev) setFlip(f => ({ key: f.key + 1, dir: target > prev ? 'next' : 'prev' }));
        return target;
      });
      const fm = showFrontMatter ? FRONT_MATTER_PAGES : 0;
      if (target >= fm) goToPage(target - fm); // sync content page for breadcrumb/status
      return;
    }
    // Scroll mode → smooth-scroll to the content page.
    const target = Math.max(0, Math.min(idx, pages.length - 1));
    goToPage(target);
    requestAnimationFrame(() => {
      document.getElementById(`canvas-page-${target}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, [viewMode, showFrontMatter, pages.length, goToPage]);

  // Scroll to a section anchor (used by the TOC deep-links). Finds which page
  // the anchored block sits on and navigates there, then scrolls into view.
  const jumpToAnchor = useCallback((anchor: string) => {
    const entry = docModel.toc.find(t => t.anchor === anchor);
    if (!entry) return;
    setActiveAnchor(anchor); // highlight the clicked section immediately
    spyLockRef.current = Date.now(); // hold it through the smooth-scroll settle
    const contentPage = entry.page - 1;
    if (viewMode === 'paged') {
      // Flip directly to the content sheet (offset by the front matter).
      navGoTo((showFrontMatter ? FRONT_MATTER_PAGES : 0) + contentPage);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      });
      return;
    }
    goToPage(contentPage);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    });
  }, [docModel.toc, viewMode, showFrontMatter, navGoTo, goToPage]);

  // Navigate to a CONTENT page index (LeftPanel thumbnails, review jumps).
  // In paged mode this offsets past the front-matter sheets.
  const goToContentPage = (pi: number) => navGoTo(viewMode === 'paged' ? fmCount + pi : pi);

  // Switch view mode. Entering paged mode starts at the Cover (sheet 1) when
  // front matter is shown — the officer flips through the document from page 1.
  const changeViewMode = useCallback((v: 'paged' | 'scroll') => {
    if (v === 'paged') {
      setPagedIndex(0);
      setFlip(f => ({ key: f.key + 1, dir: 'next' }));
    }
    setViewMode(v);
  }, []);

  // Keep the keyboard handler's nav fresh without re-subscribing every render.
  // Updated in an effect (not during render) so refs are never written mid-render.
  useEffect(() => {
    navRef.current = { goTo: navGoTo, current: navCurrent };
  });

  // Insert a fresh, editable block of the given kind onto the current page —
  // wires the FormatRibbon element buttons so clicking Text/Table/Chart/Metric
  // actually adds a block to the canvas.
  const insertBlankBlock = (kind: PageBlock['kind']) => {
    const labels: Record<string, string> = {
      heading: 'New Heading', narrative: 'New Paragraph', table: 'New Table',
      chart: 'New Chart', metric: 'New Metric', key_finding: 'Key Finding',
      source_note: 'Source', divider: 'Divider',
    };
    const id = `block-manual-${Date.now()}`;
    addBlockToPage({
      id, index: -1, kind,
      title: labels[kind] || 'New Block',
      content: kind === 'narrative' ? '' : '',
      sectionPath: [], status: 'done', pageIndex: currentPage,
    }, currentPage);
    setSelectedBlockId(id);
  };

  // Duplicate a block next to its source (offset so it's visible if positioned).
  const duplicateBlock = (id: string) => {
    const src = blocks.get(id);
    if (!src) return;
    const newId = `block-copy-${Date.now()}`;
    const offset = src.x !== undefined && src.y !== undefined
      ? { x: (src.x ?? 0) + 16, y: (src.y ?? 0) + 16 }
      : {};
    addBlockToPage({ ...src, id: newId, ...offset }, currentPage);
    setSelectedBlockId(newId);
  };

  const appendGeneratedSectionBlocks = useCallback((generatedBlocks: GeneratedSectionBlock[], request: ReportSectionRequest) => {
    if (!generatedBlocks.length) return;
    const slug = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80) || 'section';
    const chapterTitle = request.target.chapter?.title || reportTitle;
    const sectionTitle = request.target.section?.title || request.description.text || 'Generated Section';
    const targetPath = [chapterTitle, sectionTitle].filter(Boolean);
    const chapterId = request.target.chapter?.id || `sectiongen-ch-${slug(chapterTitle)}`;
    const sectionId = request.target.section?.id || `sectiongen-sec-${slug(chapterTitle)}-${slug(sectionTitle)}`;

    setBlocks(prev => {
      const next = new Map(prev);
      const sequence: string[] = [];
      const hasChapter = Array.from(next.values()).some(b => b.kind === 'heading' && b.title === chapterTitle && b.sectionPath[0] === chapterTitle);
      if (!hasChapter && request.target.chapter?.create !== false) {
        next.set(chapterId, {
          id: chapterId,
          index: -1,
          kind: 'heading',
          title: chapterTitle,
          content: chapterTitle,
          sectionPath: [chapterTitle],
          status: 'done',
          pageIndex: currentPage,
        });
        sequence.push(chapterId);
      }

      const hasSection = Array.from(next.values()).some(b => b.kind === 'heading' && b.title === sectionTitle && b.sectionPath.join('\u001f') === targetPath.join('\u001f'));
      if (!hasSection && request.target.section?.create !== false) {
        next.set(sectionId, {
          id: sectionId,
          index: -1,
          kind: 'heading',
          title: sectionTitle,
          content: sectionTitle,
          sectionPath: targetPath,
          status: 'done',
          pageIndex: currentPage,
        });
        sequence.push(sectionId);
      }

      for (const block of generatedBlocks) {
        const normalized: PageBlock = {
          ...block,
          sectionPath: targetPath,
          pageIndex: currentPage,
        } as PageBlock;
        next.set(normalized.id, normalized);
        sequence.push(normalized.id);
      }

      setOrder(prevOrder => {
        const clean = prevOrder.filter(id => next.has(id));
        const additions = sequence.filter(id => !clean.includes(id));
        if (!additions.length) return clean;
        const explicitIndex = request.target.insertAfterBlockId ? clean.indexOf(request.target.insertAfterBlockId) : -1;
        let insertAt = explicitIndex;
        if (insertAt < 0) {
          insertAt = -1;
          clean.forEach((id, idx) => {
            const b = next.get(id);
            if (b && targetPath.every((part, i) => b.sectionPath[i] === part)) insertAt = idx;
          });
        }
        const out = [...clean];
        out.splice(insertAt + 1, 0, ...additions);
        return out;
      });

      return next;
    });

    const firstGenerated = generatedBlocks[0]?.id || sectionId || chapterId;
    setSelectedBlockId(firstGenerated);
    requestAnimationFrame(() => state.repack());
  }, [currentPage, reportTitle, setBlocks, setOrder, setSelectedBlockId, state]);

  // Global keyboard shortcuts (U5) — undo/redo, palette, page nav, focus,
  // delete, duplicate, cheatsheet. Typing in a field is never hijacked.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      const editingField = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable;
      const mod = e.metaKey || e.ctrlKey;

      // ⌘K — command palette (works even while typing)
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setShowPalette(v => !v); return; }

      if (editingField) return; // don't hijack text editing for the rest

      // Undo / redo
      if (mod && !e.shiftKey && e.key.toLowerCase() === 'z') { e.preventDefault(); state.undo(); return; }
      if (mod && (e.shiftKey && e.key.toLowerCase() === 'z' || e.key.toLowerCase() === 'y')) { e.preventDefault(); state.redo(); return; }
      // Duplicate selected
      if (mod && e.key.toLowerCase() === 'd' && selectedBlockId) { e.preventDefault(); duplicateBlock(selectedBlockId); return; }
      // Page navigation
      if (mod && e.key === 'ArrowLeft') { e.preventDefault(); navRef.current.goTo(navRef.current.current - 1); return; }
      if (mod && e.key === 'ArrowRight') { e.preventDefault(); navRef.current.goTo(navRef.current.current + 1); return; }
      // Focus mode
      if (mod && e.key === '.') { e.preventDefault(); setFocusMode(f => !f); return; }
      // Shortcut cheatsheet
      if (e.key === '?' || (e.shiftKey && e.key === '/')) { e.preventDefault(); setShowCheatsheet(v => !v); return; }
      // Block selection nav (Word-like) — Arrow Up/Down move between blocks.
      if (!mod && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && selectedBlockId) {
        const idx = order.indexOf(selectedBlockId);
        if (idx !== -1) {
          const next = e.key === 'ArrowDown' ? order[idx + 1] : order[idx - 1];
          if (next) { e.preventDefault(); setSelectedBlockId(next); }
        }
        return;
      }
      // Delete a selected block. Delete always removes; Backspace only removes an
      // EMPTY block — so selecting a block and pressing Backspace can no longer
      // destroy real content by accident (the old footgun).
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedBlockId) {
        const b = blocks.get(selectedBlockId);
        const emptyish = !b || (!(b.content && b.content.trim()) && !b.tableData && !b.metricValue);
        if (e.key === 'Backspace' && !emptyish) return;   // protect non-empty blocks
        e.preventDefault();
        removeBlock(selectedBlockId);
        setSelectedBlockId(null);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedBlockId, removeBlock, setSelectedBlockId, state, currentPage]); // eslint-disable-line react-hooks/exhaustive-deps

  // Build the ⌘K command list: actions + section jumps + component generation.
  const paletteCommands = useMemo<PaletteCommand[]>(() => {
    const cmds: PaletteCommand[] = [
      { id: 'auto', label: 'Auto-Generate report', group: 'Actions', hint: 'all topics', run: () => generation.autoGenerate() },
      { id: 'remaining', label: `Generate remaining (${bundle.remainingIndices.length})`, group: 'Actions', run: () => generation.generateIndices(bundle.remainingIndices) },
      { id: 'control', label: 'Open Control Panel', group: 'Actions', run: () => setShowControlPanel(true) },
      { id: 'review', label: 'Open Review & sign-off', group: 'Actions', run: () => setShowReviewPanel(true) },
      { id: 'undo', label: 'Undo', group: 'Actions', hint: '⌘Z', run: () => state.undo() },
      { id: 'redo', label: 'Redo', group: 'Actions', hint: '⇧⌘Z', run: () => state.redo() },
      { id: 'repack', label: 'Repack / balance layout', group: 'Actions', run: () => state.repack() },
      { id: 'copilot', label: 'Open Co-Pilot', group: 'Actions', run: () => { if (panel !== 'right') togglePanel('right'); } },
      { id: 'view', label: `Switch to ${viewMode === 'scroll' ? 'paged' : 'scroll'} view`, group: 'Actions', run: () => changeViewMode(viewMode === 'scroll' ? 'paged' : 'scroll') },
      { id: 'focus', label: 'Toggle Focus mode', group: 'Actions', hint: '⌘.', run: () => setFocusMode(f => !f) },
      { id: 'fm', label: 'Toggle front matter', group: 'Actions', run: () => setShowFrontMatter(v => !v) },
      { id: 'keys', label: 'Keyboard shortcuts', group: 'Actions', hint: '?', run: () => setShowCheatsheet(true) },
    ];
    for (const t of docModel.toc) {
      cmds.push({ id: `jump-${t.anchor}`, label: `${t.number} ${t.label}`, hint: `page ${t.page + FRONT_MATTER_PAGES}`, group: 'Sections', run: () => jumpToAnchor(t.anchor) });
    }
    for (const it of bundle.items) {
      cmds.push({
        id: `comp-${it.index}`,
        label: `${it.status === 'done' ? 'Redo' : 'Generate'} — ${it.title}`,
        hint: it.chapter || it.topic,
        group: 'Components',
        run: () => generation.generateOne(it.index),
      });
    }
    return cmds;
  }, [generation, bundle, state, panel, togglePanel, viewMode, docModel.toc, jumpToAnchor, changeViewMode]);

  // ── Shared sheet renderers (used by both scroll + paged modes) ──────────
  const renderCover = () => (
    <CoverPage pageSize={pageSize} zoom={zoom} title={reportTitle} referencePeriod={referencePeriod} officer={officerName} pageNumber={1}
      crest={reportOrg.crest} ministry={reportOrg.ministry} parentBody={reportOrg.parentBody} />
  );
  const renderContents = () => (
    <ContentsPage pageSize={pageSize} zoom={zoom} model={docModel} pageOffset={FRONT_MATTER_PAGES} onJump={jumpToAnchor} pageNumber={FRONT_MATTER_PAGES} />
  );
  const renderContentSheet = (pi: number, pageNumber: number, totalPagesNum: number) => (
    <A4Page
      blocks={getPageBlocks(pi)}
      pageNumber={pageNumber}
      totalPages={totalPagesNum}
      selectedBlockId={selectedBlockId}
      onSelectBlock={setSelectedBlockId}
      onGenerate={(idx) => generation.generateOne(idx)}
      onMoveBlock={moveBlock}
      onReorderBlock={reorderBlock}
      onSetFloating={setFloating}
      onUpdateBlock={updateBlock}
      onDeleteBlock={(id) => { removeBlock(id); setSelectedBlockId(null); }}
      onDuplicateBlock={duplicateBlock}
      onResizeBlock={resizeBlock}
      pageSize={pageSize}
      zoom={zoom}
      numbering={docModel.numbering}
      tableCaptions={docModel.tableCaptions}
      tableSplits={tableSplits}
      chapterLabel={docModel.chapterByPage[pi]}
      reportTitle={reportTitle}
      footerOrg={reportOrg.footer}
      onAskBlock={(b) => { setSelectedBlockId(b.id); if (panel !== 'right') togglePanel('right'); agent.send(`explain ${b.index >= 0 ? b.index : ''}`.trim()); }}
      onAddFootnote={addFootnote}
      onCommentBlock={(b) => {
        const text = window.prompt(`Comment on "${b.title}":`);
        if (text) review.addComment(b.id, officerName, text);
      }}
      onFlagBlock={review.toggleFlag}
      commentCount={review.commentCount}
      isFlagged={(id) => review.flags.has(id)}
      numerals={typography.numerals}
      onReportHeights={state.reportHeights}
    />
  );

  // Are we viewing a content sheet (vs cover/contents) — drives the breadcrumb.
  const onContentSheet = viewMode !== 'paged' || pagedIndex >= fmCount;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#f0f2f5]" role="application" aria-label={`Report canvas — ${reportTitle}`}>
      {/* Unified command bar (U3) — replaces TopNav + FormatRibbon + viewport toolbar */}
      {!focusMode && (
        <div className="relative z-30 shrink-0 shadow-sm">
        <CommandBar
          title={reportTitle}
          bundle={bundle}
          phase={phase}
          panel={panel}
          onTogglePanel={togglePanel}
          onAutoGenerate={generation.autoGenerate}
          onPause={generation.pause}
          onResume={generation.resume}
          onOpenControlPanel={() => setShowControlPanel(true)}
          pdfUrl={generatePhaseApi.reportPdfUrl(templateId, signature)}
          exportLabel={review.status === 'approved' ? 'Final' : 'Draft'}
          onOpenReview={() => setShowReviewPanel(true)}
          reviewStatus={review.status}
          reviewOpenIssues={review.openComments + review.openFlags}
          activeDraftName={activeDraft?.name}
          onOpenDrafts={() => setShowDraftPicker(true)}
          onOpenSectionGenerator={() => setShowSectionWorkflow(true)}
          onInsertBlock={insertBlankBlock}
          onToggleFocus={() => setFocusMode(f => !f)}
          onUndo={state.undo}
          onRedo={state.redo}
          canUndo={state.canUndo}
          canRedo={state.canRedo}
        />
        <CanvasViewBar
          pageSize={pageSize}
          onPageSizeChange={setPageSize}
          density={density}
          onDensityChange={setDensity}
          typographyPreset={typography.preset}
          typographyPresets={TYPOGRAPHY_PRESETS}
          onTypographyPresetChange={(id) => {
            const p = TYPOGRAPHY_PRESETS.find(x => x.id === id);
            if (p) setTypography({ preset: p.id, ...p.config });
          }}
          onOpenTypography={() => setShowTypography(true)}
          viewMode={viewMode}
          onViewModeChange={changeViewMode}
          showFrontMatter={showFrontMatter}
          onToggleFrontMatter={() => setShowFrontMatter(v => !v)}
          zoom={zoom}
          onZoomChange={setZoom}
          currentPage={navCurrent}
          totalPages={navTotal}
          onGoToPage={navGoTo}
          onAddPage={addPage}
        />
        </div>
      )}

      {/* Main area */}
      <div className="relative flex flex-1 overflow-hidden">
        {/* Left panel */}
        {panel === 'left' && !focusMode && (
          <LeftPanel pages={pages} currentPage={activeContentPage} onGoToPage={goToContentPage} getPageBlocks={getPageBlocks} onInsertBlock={insertBlankBlock} toc={docModel.toc} onJumpToAnchor={jumpToAnchor} activeAnchor={activeAnchor} />
        )}

        {/* Center: Page viewport (paged ⇄ scroll, S5) */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {focusMode && (
            <button onClick={() => setFocusMode(false)} className="absolute right-4 top-4 z-50 rounded-full bg-slate-800/80 px-3 py-1.5 text-[11px] font-medium text-white shadow-lg hover:bg-slate-900">
              Exit Focus
            </button>
          )}
          {/* Breadcrumb (U1) — Report › Chapter › current page section */}
          {!focusMode && onContentSheet && docModel.chapterByPage[currentPage] && (
            <div className="flex items-center gap-1.5 border-b border-slate-100 bg-white px-4 py-1.5 text-[11px] text-slate-500">
              <span className="font-medium text-slate-700">{reportTitle}</span>
              <span className="text-slate-300">›</span>
              <span className="text-slate-700">{docModel.chapterByPage[currentPage]}</span>
            </div>
          )}
          <div ref={scrollRef} className="relative z-0 flex-1 w-full overflow-auto px-3 py-5">
            <div className={`doc-type mx-auto flex min-h-full w-fit max-w-full flex-col items-center page-flip-perspective ${density === 'compact' ? 'gap-3' : 'gap-5'}`} style={docStyle}>
              {viewMode === 'scroll' ? (
                // SCROLL — front matter as a prefix, then all content pages stacked.
                <>
                  {showFrontMatter && (<>{renderCover()}{renderContents()}</>)}
                  {pages.map((_, pi) => (
                    <div key={pi} id={`canvas-page-${pi}`} className="w-full flex justify-center">
                      {renderContentSheet(pi, pi + 1 + fmCount, totalSheets)}
                    </div>
                  ))}
                </>
              ) : (
                // PAGED — ONE sheet at a time (Cover 1 · Contents 2 · content 3+),
                // turning left→right like a book on each navigation.
                (() => {
                  const idx = Math.max(0, Math.min(pagedIndex, totalSheets - 1));
                  const isCover = fmCount > 0 && idx === 0;
                  const isContents = fmCount > 0 && idx === 1;
                  const contentIdx = idx - fmCount;
                  return (
                    <div key={`flip-${flip.key}`} className={`w-full flex justify-center ${flip.dir === 'next' ? 'page-flip-next' : 'page-flip-prev'}`}>
                      {isCover ? renderCover()
                        : isContents ? renderContents()
                        : renderContentSheet(contentIdx, idx + 1, totalSheets)}
                    </div>
                  );
                })()
              )}
            </div>
          </div>
        </div>

        {/* Right panel */}
        {panel === 'right' && !focusMode && (
          <RightPanel
            selectedBlock={selectedBlock}
            messages={agent.messages}
            busy={agent.busy}
            onSend={agent.send}
            onClose={() => togglePanel('right')}
            onRegenerate={(idx) => generation.generateOne(idx)}
            onInsert={(text) => agent.insertNarrative(text)}
            suggestions={suggestions}
          />
        )}
      </div>

      {/* Status bar (U3) — fills previously-empty bottom space */}
      {!focusMode && (
        <>
          {footnotes.length > 0 && (
            <div className="max-h-16 shrink-0 overflow-auto border-t border-slate-100 bg-amber-50/40 px-4 py-1">
              <p className="mb-0.5 text-[8px] font-bold uppercase tracking-wide text-amber-600">Footnotes</p>
              {footnotes.map(f => (
                <p key={f.n} className="text-[9px] leading-snug text-slate-500">
                  <sup className="font-semibold text-blue-600">{f.n}</sup> {f.text}
                </p>
              ))}
            </div>
          )}
          <StatusBar
            sectionLabel={onContentSheet ? docModel.chapterByPage[currentPage] : undefined}
            pageNumber={viewMode === 'paged' ? pagedIndex + 1 : currentPage + 1 + FRONT_MATTER_PAGES}
            totalPages={totalSheets}
            wordCount={docStats.words}
            tableCount={docStats.tables}
            figureCount={docStats.figures}
            saveState={phase === 'generating' ? 'saving' : 'saved'}
          />
        </>
      )}

      {/* Control Panel popup (S2) — generation mission-control */}
      {showControlPanel && (
        <ControlPanel
          bundle={bundle}
          onClose={() => setShowControlPanel(false)}
          onGenerateIndex={(idx) => generation.generateOne(idx)}
          onGenerateTopic={(topic) => generation.autoGenerateTopic(topic)}
          onGenerateRemaining={() => generation.generateIndices(bundle.remainingIndices)}
          onRetryFailed={() => generation.generateIndices(bundle.failedIndices)}
          onInspect={(idx) => { setShowControlPanel(false); togglePanel('right'); agent.send(`inspect ${idx}`); }}
        />
      )}

      {/* Command palette (S4) — global ⌘K launcher */}
      <CommandPalette open={showPalette} onClose={() => setShowPalette(false)} commands={paletteCommands} />

      {/* Keyboard shortcut cheatsheet (U5) — press ? */}
      {showCheatsheet && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-slate-900/30 backdrop-blur-sm" onClick={() => setShowCheatsheet(false)}>
          <div className="w-[380px] rounded-xl bg-white p-5 shadow-2xl" onClick={e => e.stopPropagation()}>
            <h2 className="mb-3 text-[14px] font-semibold text-slate-800">Keyboard shortcuts</h2>
            <div className="space-y-1.5 text-[11px]">
              {[
                ['⌘K', 'Command palette'],
                ['⌘Z / ⇧⌘Z', 'Undo / Redo'],
                ['⌘D', 'Duplicate selected block'],
                ['Delete', 'Remove selected block'],
                ['⌘← / ⌘→', 'Previous / Next page'],
                ['⌘.', 'Toggle Focus mode'],
                ['Double-click', 'Edit a block'],
                ['Ctrl+Enter', 'Save edit · B/I bold/italic'],
                ['?', 'This cheatsheet'],
              ].map(([k, d]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-slate-600">{d}</span>
                  <kbd className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-500">{k}</kbd>
                </div>
              ))}
            </div>
            <button onClick={() => setShowCheatsheet(false)} className="mt-4 w-full rounded-md bg-slate-100 py-1.5 text-[11px] font-medium text-slate-600 hover:bg-slate-200">Close</button>
          </div>
        </div>
      )}

      {/* Review & sign-off popup (U4) */}
      {showReviewPanel && (
        <ReviewPanel
          review={review}
          officer={officerName}
          onClose={() => setShowReviewPanel(false)}
          onJumpToBlock={(id) => {
            const b = blocks.get(id);
            if (b) { setShowReviewPanel(false); goToContentPage(b.pageIndex); setSelectedBlockId(id); }
          }}
          blockTitle={(id) => blocks.get(id)?.title || 'Block'}
        />
      )}
      {/* Typography settings popup (T6) */}
      {showTypography && (
        <TypographyPanel config={typography} onChange={setTypography} onClose={() => setShowTypography(false)} />
      )}

      {showSectionWorkflow && (
        <SectionWorkflowModal
          templateId={templateId}
          signature={signature}
          onClose={() => setShowSectionWorkflow(false)}
          onAppendBlocks={appendGeneratedSectionBlocks}
        />
      )}
      <CanvasDraftPicker
        templateId={templateId}
        signature={signature}
        open={showDraftPicker || !activeDraft}
        currentDraftId={activeDraft?.draftId || null}
        onSelect={(draft) => { setActiveDraft(draft); setShowDraftPicker(false); }}
        onClose={() => setShowDraftPicker(false)}
      />
    </div>
  );
}
