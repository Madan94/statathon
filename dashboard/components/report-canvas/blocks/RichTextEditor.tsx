'use client';
import { useEffect, useRef, useState } from 'react';
import { Bold, Italic, Superscript, Subscript, Link2, Asterisk, Check, X } from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════
   RichTextEditor (U2) — inline contentEditable editor with a floating
   formatting toolbar (Bold / Italic / Super / Sub / Footnote* / Link).

   • What you see is what prints — stores lightweight HTML.
   • Footnote button inserts an auto-marker superscript that the
     document footnote collector picks up (data-footnote attr).
   • Ctrl+Enter commits, Esc cancels, Ctrl+B/I format.
   ═══════════════════════════════════════════════════════════════════ */

interface Props {
  /** Initial HTML/text content of the block. */
  value: string;
  multiline?: boolean;
  onCommit: (html: string) => void;
  onCancel: () => void;
  /** Insert a footnote; returns the marker number to render. */
  onAddFootnote?: (text: string) => number;
}

function exec(cmd: string, arg?: string) {
  // execCommand is deprecated but remains the pragmatic path for inline
  // rich-text without pulling in a heavy editor dependency.
  document.execCommand(cmd, false, arg);
}

export function RichTextEditor({ value, multiline = true, onCommit, onCancel, onAddFootnote }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const promptInputRef = useRef<HTMLInputElement>(null);
  const savedRange = useRef<Range | null>(null);
  const [bar, setBar] = useState<{ x: number; y: number } | null>(null);
  const [prompt, setPrompt] = useState<{ kind: 'footnote' | 'link'; x: number; y: number } | null>(null);
  const [promptValue, setPromptValue] = useState('');

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = value || '';
    el.focus();
    // Place caret at end.
    const range = document.createRange();
    range.selectNodeContents(el);
    range.collapse(false);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
  }, [value]);

  // Show the floating toolbar above the current text selection.
  const updateBar = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !ref.current) { setBar(null); return; }
    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();
    const host = ref.current.getBoundingClientRect();
    setBar({ x: rect.left - host.left + rect.width / 2, y: rect.top - host.top - 8 });
  };

  const commit = () => { onCommit(ref.current?.innerHTML ?? ''); };

  const wrapSuper = (tag: 'sup' | 'sub') => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const text = sel.toString();
    const el = document.createElement(tag);
    el.textContent = text;
    const range = sel.getRangeAt(0);
    range.deleteContents();
    range.insertNode(el);
    setBar(null);
  };

  /** Save the current selection and open the inline popover for footnote/link. */
  const openPrompt = (kind: 'footnote' | 'link') => {
    const sel = window.getSelection();
    savedRange.current = sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null;
    setPromptValue('');
    setPrompt({ kind, x: bar?.x ?? 12, y: bar?.y ?? 0 });
    // Focus the popover input after it mounts.
    requestAnimationFrame(() => promptInputRef.current?.focus());
  };

  /** Restore the saved selection so an insert lands where the caret was. */
  const restoreSelection = () => {
    const sel = window.getSelection();
    if (sel && savedRange.current) { sel.removeAllRanges(); sel.addRange(savedRange.current); }
  };

  const insertFootnoteText = (note: string) => {
    if (!onAddFootnote || !ref.current) return;
    const n = onAddFootnote(note);
    const sup = document.createElement('sup');
    sup.textContent = String(n);
    sup.setAttribute('data-footnote', String(n));
    sup.className = 'text-blue-600 font-semibold';
    const sel = window.getSelection();
    if (sel && sel.rangeCount) sel.getRangeAt(0).insertNode(sup);
    else ref.current.appendChild(sup);
  };

  /** Apply the popover's value (footnote text or link URL) at the saved caret. */
  const confirmPrompt = () => {
    const kind = prompt?.kind;
    const val = promptValue.trim();
    setPrompt(null);
    ref.current?.focus();
    restoreSelection();
    if (!val) return;
    if (kind === 'footnote') insertFootnoteText(val);
    else if (kind === 'link') exec('createLink', val);
    setBar(null);
  };

  /** Commit on blur — unless focus moved into our own toolbar / popover. */
  const handleBlur = (e: React.FocusEvent) => {
    const next = e.relatedTarget as Node | null;
    if (next && wrapRef.current?.contains(next)) return;
    commit();
  };

  return (
    <div ref={wrapRef} className="relative" onPointerDown={e => e.stopPropagation()}>
      {/* Floating toolbar over the selection */}
      {bar && !prompt && (
        <div
          className="absolute z-[70] flex -translate-x-1/2 -translate-y-full items-center gap-0.5 rounded-md border border-slate-200 bg-white px-1 py-0.5 shadow-lg"
          style={{ left: bar.x, top: bar.y }}
        >
          <button onMouseDown={e => { e.preventDefault(); exec('bold'); }} title="Bold (Ctrl+B)" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Bold className="h-3 w-3" /></button>
          <button onMouseDown={e => { e.preventDefault(); exec('italic'); }} title="Italic (Ctrl+I)" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Italic className="h-3 w-3" /></button>
          <span className="mx-0.5 h-3 w-px bg-slate-200" />
          <button onMouseDown={e => { e.preventDefault(); wrapSuper('sup'); }} title="Superscript" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Superscript className="h-3 w-3" /></button>
          <button onMouseDown={e => { e.preventDefault(); wrapSuper('sub'); }} title="Subscript" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Subscript className="h-3 w-3" /></button>
          {onAddFootnote && (
            <button onMouseDown={e => { e.preventDefault(); openPrompt('footnote'); }} title="Insert footnote" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Asterisk className="h-3 w-3" /></button>
          )}
          <button onMouseDown={e => { e.preventDefault(); openPrompt('link'); }} title="Insert link" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Link2 className="h-3 w-3" /></button>
        </div>
      )}

      {/* Inline footnote / link popover (replaces window.prompt) */}
      {prompt && (
        <div
          className="absolute z-[80] flex -translate-x-1/2 -translate-y-full items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-1 shadow-lg"
          style={{ left: prompt.x, top: prompt.y }}
          onPointerDown={e => e.stopPropagation()}
        >
          <input
            ref={promptInputRef}
            value={promptValue}
            onChange={e => setPromptValue(e.target.value)}
            onKeyDown={e => {
              e.stopPropagation();
              if (e.key === 'Enter') { e.preventDefault(); confirmPrompt(); }
              if (e.key === 'Escape') { e.preventDefault(); setPrompt(null); ref.current?.focus(); restoreSelection(); }
            }}
            placeholder={prompt.kind === 'footnote' ? 'Footnote text…' : 'https://…'}
            aria-label={prompt.kind === 'footnote' ? 'Footnote text' : 'Link URL'}
            className="w-44 rounded border border-slate-200 px-1.5 py-0.5 text-[11px] text-slate-700 outline-none focus:border-blue-400"
          />
          <button onMouseDown={e => { e.preventDefault(); confirmPrompt(); }} title="Apply" className="rounded p-1 text-emerald-600 hover:bg-emerald-50"><Check className="h-3 w-3" /></button>
          <button onMouseDown={e => { e.preventDefault(); setPrompt(null); ref.current?.focus(); restoreSelection(); }} title="Cancel" className="rounded p-1 text-slate-400 hover:bg-slate-100"><X className="h-3 w-3" /></button>
        </div>
      )}

      <div
        ref={ref}
        contentEditable
        suppressContentEditableWarning
        role="textbox"
        aria-multiline={multiline}
        aria-label="Edit block text"
        onMouseUp={updateBar}
        onKeyUp={updateBar}
        onBlur={handleBlur}
        onKeyDown={e => {
          // Keep editing keystrokes local — never let Backspace/Delete/arrows
          // bubble up to the canvas shortcut handler while typing.
          e.stopPropagation();
          if (e.key === 'Escape') { e.preventDefault(); onCancel(); }
          if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); commit(); }
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') { e.preventDefault(); exec('bold'); }
          if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'i') { e.preventDefault(); exec('italic'); }
        }}
        className="min-h-[1.6em] w-full rounded bg-white px-2 py-1 text-[12px] leading-[1.7] text-slate-700 outline-none ring-2 ring-blue-400 ring-offset-1"
      />
    </div>
  );
}
