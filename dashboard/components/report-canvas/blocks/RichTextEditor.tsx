'use client';
import { useEffect, useRef, useState } from 'react';
import { Bold, Italic, Superscript, Subscript, Link2, Asterisk } from 'lucide-react';

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
  const [bar, setBar] = useState<{ x: number; y: number } | null>(null);

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

  const insertFootnote = () => {
    if (!onAddFootnote || !ref.current) return;
    const note = window.prompt('Footnote text:');
    if (!note) return;
    const n = onAddFootnote(note);
    const sup = document.createElement('sup');
    sup.textContent = String(n);
    sup.setAttribute('data-footnote', String(n));
    sup.className = 'text-blue-600 font-semibold';
    const sel = window.getSelection();
    if (sel && sel.rangeCount) {
      sel.getRangeAt(0).insertNode(sup);
    } else {
      ref.current.appendChild(sup);
    }
  };

  const insertLink = () => {
    const url = window.prompt('Link URL:');
    if (url) exec('createLink', url);
  };

  return (
    <div className="relative" onPointerDown={e => e.stopPropagation()}>
      {/* Floating toolbar over the selection */}
      {bar && (
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
            <button onMouseDown={e => { e.preventDefault(); insertFootnote(); }} title="Insert footnote" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Asterisk className="h-3 w-3" /></button>
          )}
          <button onMouseDown={e => { e.preventDefault(); insertLink(); }} title="Insert link" className="rounded p-1 text-slate-600 hover:bg-slate-100"><Link2 className="h-3 w-3" /></button>
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
        onBlur={commit}
        onKeyDown={e => {
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
