'use client';

/**
 * ReportDocumentCanvas — Continuous-flow A4 document editor (MS Word style).
 *
 * Unlike fixed page-count splitting, this uses a SINGLE continuous scrollable
 * document surface at A4 width. Content flows naturally — no forced page breaks.
 * Visual page indicators appear at 297mm intervals purely as visual guides.
 *
 * Architecture: Google Docs model — one white surface, infinite vertical scroll,
 * A4 width constraint, natural content height. The cover page is the only
 * discrete page element. All content blocks flow in a single continuous stream.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, BarChart3, Bold, Check, ChevronDown, ChevronUp,
  Copy, FileText, FunctionSquare, GripVertical, Hash, Italic,
  Loader2, MessageSquare, Minus, MoreHorizontal, Pencil, Plus,
  Settings, Table2, Trash2, TrendingUp, Type, Underline,
} from 'lucide-react';

/* ═══════════════════════════════════════════════════════════════════════════
   TYPES
   ═══════════════════════════════════════════════════════════════════════════ */

export interface DocBlock {
  id: string;
  kind: 'heading' | 'narrative' | 'key_finding' | 'chart' | 'table' | 'metric'
      | 'source_note' | 'methodology_note' | 'data_caveat' | 'footnote'
      | 'glossary_term' | 'divider' | 'spacer';
  content: string;
  title?: string;
  level?: number;
  chartConfig?: Record<string, unknown>;
  tableData?: Record<string, unknown>;
  metricValue?: string;
  metricUnit?: string;
  status: 'pending' | 'generating' | 'done' | 'error';
  planId?: string;
  componentIndex?: number;
}

interface ReportDocumentCanvasProps {
  blocks: DocBlock[];
  onUpdateBlock?: (id: string, updates: Partial<DocBlock>) => void;
  onReorderBlock?: (id: string, direction: 'up' | 'down') => void;
  onDeleteBlock?: (id: string) => void;
  onInsertBlock?: (afterId: string, kind: DocBlock['kind']) => void;
  readOnly?: boolean;
  className?: string;
  reportTitle?: string;
  reportSubtitle?: string;
}

/* ═══════════════════════════════════════════════════════════════════════════
   UTILITIES
   ═══════════════════════════════════════════════════════════════════════════ */

const TEXT_KINDS = new Set<string>(['heading','narrative','key_finding','source_note','methodology_note','data_caveat','footnote','glossary_term']);

function blockLabel(kind: string) { return kind.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase()); }

function fmtNum(n: string|number|undefined|null): string {
  if (n == null || n === '') return '—';
  const v = typeof n === 'string' ? parseFloat(n) : n;
  if (v == null || isNaN(v)) return String(n ?? '—');
  if (Math.abs(v)>=1e7) return (v/1e7).toFixed(2)+' Cr';
  if (Math.abs(v)>=1e5) return (v/1e5).toFixed(2)+' L';
  if (Math.abs(v)>=1000) return v.toLocaleString('en-IN',{maximumFractionDigits:1});
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function wordCount(blocks: DocBlock[]|undefined|null) { return (blocks||[]).reduce((n,b)=>n+((b?.content)||'').split(/\s+/).filter(Boolean).length,0); }
function readTime(w: number|undefined|null) { const n=w||0; return `${Math.max(1,Math.ceil(n/200))} min`; }

function extractToc(blocks: DocBlock[]|undefined|null) {
  return (blocks||[]).filter(b=>b.kind==='heading'&&b.status==='done'&&b.content).map(b=>({id:b.id,text:b.content,level:b.level||2}));
}

interface RankItem { rank?:number; key?:Record<string,string>; value?:number; rowIds?:string[] }
interface AggRow { [k:string]:string|number|null }

function parseRankItems(b: DocBlock): RankItem[] {
  const d = (b.tableData||b) as Record<string,unknown>;
  const items = (d.items||d.rankingData||d.rows||[]) as RankItem[];
  return Array.isArray(items)?items:[];
}
function parseAggRows(b: DocBlock): AggRow[] {
  const d = (b.tableData||b) as Record<string,unknown>;
  const rows = (d.rows||d.aggregationData||d.items||[]) as AggRow[];
  return Array.isArray(rows)?rows:[];
}

/* ═══════════════════════════════════════════════════════════════════════════
   TOOLBAR + INLINE EDITOR
   ═══════════════════════════════════════════════════════════════════════════ */

function FloatingToolbar({ onClose }: { onClose:()=>void }) {
  const exec = (c:string) => document.execCommand(c);
  return (
    <div className="absolute -top-10 left-0 z-50 flex items-center gap-0.5 rounded-md border border-slate-200/80 bg-white px-1 py-0.5 shadow-lg print:hidden">
      {([['bold',Bold,'B'],['italic',Italic,'I'],['underline',Underline,'U']] as const).map(([cmd,Icon,k])=>(
        <button key={cmd} type="button" title={`${cmd} (Ctrl+${k})`} className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={()=>exec(cmd)}><Icon className="h-3 w-3"/></button>
      ))}
      <span className="mx-px h-3.5 w-px bg-slate-200"/>
      <button type="button" title="Clear" className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700" onClick={()=>exec('removeFormat')}><Type className="h-3 w-3"/></button>
      <span className="mx-px h-3.5 w-px bg-slate-200"/>
      <button type="button" className="rounded px-2 py-1 text-[10px] font-medium text-emerald-600 hover:bg-emerald-50" onClick={onClose}><Check className="mr-0.5 inline h-2.5 w-2.5"/>Done</button>
    </div>
  );
}

function InlineEditor({value,onChange,onBlur,level}:{value:string;onChange:(v:string)=>void;onBlur:()=>void;level?:number}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(()=>{
    if(!ref.current) return;
    ref.current.focus();
    const r=document.createRange(),s=window.getSelection();
    r.selectNodeContents(ref.current);r.collapse(false);
    s?.removeAllRanges();s?.addRange(r);
  },[]);
  const sz = level===1?'text-[20px] font-bold':level===2?'text-[16px] font-bold':level===3?'text-[14px] font-semibold':'text-[13px]';
  return (
    <div className="relative">
      <FloatingToolbar onClose={onBlur}/>
      <div ref={ref} contentEditable suppressContentEditableWarning
        className={`min-h-[1.5em] rounded px-0.5 outline-none ring-2 ring-blue-200/60 ${sz} leading-[1.7] text-slate-800`}
        onInput={e=>onChange((e.target as HTMLDivElement).innerText)}
        onBlur={onBlur} onKeyDown={e=>{if(e.key==='Escape')onBlur();}}
        dangerouslySetInnerHTML={{__html:value}}/>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   INSERT MENU
   ═══════════════════════════════════════════════════════════════════════════ */

function InsertMenu({onInsert,onClose}:{onInsert:(k:DocBlock['kind'])=>void;onClose:()=>void}) {
  const items:[DocBlock['kind'],string,typeof FileText][] = [
    ['narrative','Paragraph',FileText],['heading','Heading',Type],
    ['key_finding','Key finding',TrendingUp],['chart','Chart',BarChart3],
    ['table','Table',Table2],['metric','Metric',FunctionSquare],
    ['source_note','Source note',MessageSquare],['divider','Divider',Minus],
  ];
  return (
    <div className="absolute left-1/2 z-50 -translate-x-1/2 rounded-lg border border-slate-200/80 bg-white p-1 shadow-xl print:hidden" onClick={e=>e.stopPropagation()}>
      <div className="grid grid-cols-4 gap-0.5">
        {items.map(([kind,label,Icon])=>(
          <button key={kind} type="button" onClick={()=>{onInsert(kind);onClose();}}
            className="flex flex-col items-center gap-1 rounded-md px-2 py-2 text-center transition-colors hover:bg-slate-50 active:bg-slate-100">
            <Icon className="h-3.5 w-3.5 text-slate-400"/><span className="text-[9px] font-medium text-slate-600">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SHIMMER (TYPE-AWARE)
   ═══════════════════════════════════════════════════════════════════════════ */

function BlockShimmer({title,kind}:{title?:string;kind:string}) {
  const k = kind;
  return (
    <div className="py-1.5">
      <div className="mb-2 flex items-center gap-1.5">
        <span className="relative flex h-2 w-2"><span className="absolute inset-0 animate-ping rounded-full bg-blue-400/40"/><span className="relative inline-flex h-2 w-2 rounded-full bg-blue-500"/></span>
        <span className="text-[10px] font-medium text-blue-600/80">{title||blockLabel(kind)}</span>
      </div>
      {k==='chart'?(
        <div className="flex h-28 items-end gap-[3%] rounded bg-slate-50/50 px-4 pb-3 pt-4">
          {[35,60,45,75,40,82,50,65,70,48].map((h,i)=><div key={i} className="flex-1 animate-pulse rounded-t bg-blue-100/50" style={{height:`${h}%`,animationDelay:`${i*60}ms`}}/>)}
        </div>
      ):k==='table'?(
        <div className="space-y-px rounded border border-slate-100 overflow-hidden">
          <div className="flex gap-px bg-slate-50">{[1,2,3,4].map(i=><div key={i} className="h-5 flex-1 animate-pulse bg-slate-100/60"/>)}</div>
          {[1,2,3].map(r=><div key={r} className="flex gap-px">{[1,2,3,4].map(c=><div key={c} className="h-4 flex-1 animate-pulse bg-slate-50/80" style={{animationDelay:`${(r*4+c)*25}ms`}}/>)}</div>)}
        </div>
      ):k==='metric'?(
        <div className="flex items-end gap-2 py-1"><div className="h-7 w-20 animate-pulse rounded bg-blue-50/60"/><div className="h-2.5 w-8 animate-pulse rounded bg-slate-100"/></div>
      ):(
        <div className="space-y-1">{[100,92,80].map((w,i)=><div key={i} className="h-[9px] animate-pulse rounded-sm bg-slate-100/70" style={{width:`${w}%`,animationDelay:`${i*50}ms`}}/>)}</div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DATA TABLES
   ═══════════════════════════════════════════════════════════════════════════ */

function RankingTable({items,title,measure}:{items:RankItem[];title?:string;measure?:string}) {
  if(!items.length) return null;
  const keys = items[0]?.key?Object.keys(items[0].key):[];
  const total = items.reduce((s,i)=>s+(i.value||0),0);
  return (
    <div className="my-3 overflow-hidden rounded border border-slate-200/50">
      {title&&<div className="border-b border-slate-100 bg-slate-50/40 px-4 py-1.5"><p className="text-[10px] font-semibold text-slate-600">{title}</p></div>}
      <table className="w-full text-[10.5px]">
        <thead><tr className="border-b border-slate-200/60 bg-slate-50/30 text-[9px]">
          <th className="w-8 px-2.5 py-1.5 text-center font-semibold text-slate-400">#</th>
          {keys.map(k=><th key={k} className="px-2.5 py-1.5 text-left font-semibold text-slate-500">{k}</th>)}
          <th className="px-2.5 py-1.5 text-right font-semibold text-slate-500">{measure||'Value'}</th>
          {total>0&&<th className="w-16 px-2.5 py-1.5 text-right font-semibold text-slate-400">%</th>}
          {total>0&&<th className="w-20 px-2.5 py-1.5"/>}
        </tr></thead>
        <tbody>{items.map((item,i)=>{
          const pct = total>0&&item.value?(item.value/total)*100:0;
          return (
            <tr key={i} className="border-b border-slate-100/60 last:border-b-0 hover:bg-blue-50/20 transition-colors">
              <td className="px-2.5 py-[5px] text-center tabular-nums text-slate-400">{item.rank??i+1}</td>
              {keys.map(k=><td key={k} className="px-2.5 py-[5px] text-slate-700">{item.key?.[k]??'—'}</td>)}
              <td className="px-2.5 py-[5px] text-right tabular-nums font-medium text-slate-800">{fmtNum(item.value)}</td>
              {total>0&&<td className="px-2.5 py-[5px] text-right tabular-nums text-slate-400">{pct.toFixed(1)}</td>}
              {total>0&&<td className="px-2.5 py-[5px]"><div className="h-[4px] w-full rounded-full bg-slate-100 overflow-hidden"><div className="h-full rounded-full bg-blue-300/60" style={{width:`${Math.min(pct,100)}%`}}/></div></td>}
            </tr>
          );
        })}</tbody>
        {total>0&&<tfoot><tr className="border-t border-slate-200/50 bg-slate-50/20">
          <td className="px-2.5 py-[5px]"/>
          {keys.map((k,i)=><td key={k} className="px-2.5 py-[5px] text-[9px] font-semibold text-slate-500">{i===0?'Total':''}</td>)}
          <td className="px-2.5 py-[5px] text-right tabular-nums text-[9px] font-bold text-slate-700">{fmtNum(total)}</td>
          <td className="px-2.5 py-[5px] text-right tabular-nums text-[9px] text-slate-400">100.0</td>
          <td/>
        </tr></tfoot>}
      </table>
    </div>
  );
}

function AggTable({rows,title}:{rows:AggRow[];title?:string}) {
  if(!rows.length) return null;
  const cols = Object.keys(rows[0]).filter(k=>k!=='__rowId');
  return (
    <div className="my-3 overflow-hidden rounded border border-slate-200/50">
      {title&&<div className="border-b border-slate-100 bg-slate-50/40 px-4 py-1.5"><p className="text-[10px] font-semibold text-slate-600">{title}</p></div>}
      <table className="w-full text-[10.5px]">
        <thead><tr className="border-b border-slate-200/60 bg-slate-50/30 text-[9px]">
          {cols.map(c=><th key={c} className="px-2.5 py-1.5 text-left font-semibold text-slate-500">{c}</th>)}
        </tr></thead>
        <tbody>{rows.slice(0,12).map((row,i)=>(
          <tr key={i} className="border-b border-slate-100/60 last:border-b-0 hover:bg-blue-50/20 transition-colors">
            {cols.map(c=>{const v=row[c];const num=typeof v==='number';return <td key={c} className={`px-2.5 py-[5px] ${num?'text-right tabular-nums font-medium text-slate-800':'text-slate-700'}`}>{num?fmtNum(v):String(v??'—')}</td>;})}
          </tr>
        ))}</tbody>
      </table>
      {rows.length>12&&<div className="border-t border-slate-100 bg-slate-50/20 px-3 py-1 text-[8px] text-slate-400">{rows.length-12} more rows</div>}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   DOCUMENT BLOCK
   ═══════════════════════════════════════════════════════════════════════════ */

function DocumentBlock({block,onUpdate,onReorder,onDelete,onInsertAfter,readOnly,isSelected,onSelect}:{
  block:DocBlock;onUpdate?:(u:Partial<DocBlock>)=>void;onReorder?:(d:'up'|'down')=>void;
  onDelete?:()=>void;onInsertAfter?:(k:DocBlock['kind'])=>void;readOnly?:boolean;
  isSelected?:boolean;onSelect?:()=>void;
}) {
  const [editing,setEditing] = useState(false);
  const [showInsert,setShowInsert] = useState(false);
  const [showMenu,setShowMenu] = useState(false);
  const [hovered,setHovered] = useState(false);
  const [copied,setCopied] = useState(false);
  const isText = TEXT_KINDS.has(block.kind);
  const active = isSelected || hovered;

  const doCopy = useCallback(()=>{
    navigator.clipboard.writeText(block.content||block.metricValue||'').then(()=>{setCopied(true);setTimeout(()=>setCopied(false),1200);}).catch(()=>{});
  },[block]);

  // Hooks must run on EVERY render (rules-of-hooks): compute table data before
  // any early return below, even though it's only used in the table branch.
  const rankItems = useMemo(()=>block.kind==='table'?parseRankItems(block):[],[block]);
  const aggRows = useMemo(()=>block.kind==='table'?parseAggRows(block):[],[block]);

  if (block.kind==='divider') return (
    <div className="group relative my-5 flex items-center cursor-pointer" onClick={onSelect} onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>setHovered(false)}>
      <div className={`h-px flex-1 transition-colors ${active?'bg-blue-300':'bg-gradient-to-r from-transparent via-slate-200 to-transparent'}`}/>
      {!readOnly&&active&&<button type="button" onClick={e=>{e.stopPropagation();onDelete?.();}} className="absolute -right-7 rounded p-1 text-slate-300 hover:bg-red-50 hover:text-red-400 print:hidden"><Trash2 className="h-3 w-3"/></button>}
    </div>
  );
  if (block.kind==='spacer') return <div className="h-6"/>;

  return (
    <div className={`group/block relative ${isSelected?'z-10':''}`} data-block-id={block.id}
      onClick={e=>{if(!editing){e.stopPropagation();onSelect?.();}}}
      onMouseEnter={()=>setHovered(true)} onMouseLeave={()=>{setHovered(false);setShowMenu(false);setShowInsert(false);}}>

      {/* side gutter controls — larger hit targets */}
      {!readOnly&&active&&block.status==='done'&&(
        <div className="absolute -left-9 top-0 flex flex-col items-center gap-0 print:hidden">
          <button type="button" onClick={e=>{e.stopPropagation();onReorder?.('up');}} className="rounded p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-600 transition-colors"><ChevronUp className="h-3 w-3"/></button>
          <GripVertical className="h-3 w-3 cursor-grab text-slate-200 hover:text-slate-500"/>
          <button type="button" onClick={e=>{e.stopPropagation();onReorder?.('down');}} className="rounded p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-600 transition-colors"><ChevronDown className="h-3 w-3"/></button>
        </div>
      )}

      {/* action bar — appears on select/hover */}
      {!readOnly&&active&&block.status==='done'&&(
        <div className="absolute -right-9 top-0 flex flex-col items-center gap-0.5 print:hidden">
          {copied?<span className="rounded bg-emerald-50 px-1 py-0.5 text-[7px] font-semibold text-emerald-600">✓</span>:(
            <>
              {isText&&<button type="button" onClick={e=>{e.stopPropagation();setEditing(true);}} className="rounded p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-600 transition-colors" title="Edit"><Pencil className="h-3 w-3"/></button>}
              <button type="button" onClick={e=>{e.stopPropagation();doCopy();}} className="rounded p-1 text-slate-300 hover:bg-slate-100 hover:text-slate-600 transition-colors" title="Copy"><Copy className="h-3 w-3"/></button>
              <button type="button" onClick={e=>{e.stopPropagation();onDelete?.();}} className="rounded p-1 text-slate-300 hover:bg-red-50 hover:text-red-400 transition-colors" title="Delete"><Trash2 className="h-3 w-3"/></button>
            </>
          )}
        </div>
      )}

      {/* block body */}
      <div className={`relative rounded transition-all duration-100 ${
        isSelected&&!readOnly&&block.status==='done'?'bg-blue-50/25 ring-1 ring-blue-200/40':
        hovered&&!readOnly&&block.status==='done'?'bg-slate-50/40':''
      } ${block.status==='pending'?'opacity-[0.18]':''}`}
        onDoubleClick={()=>{if(isText&&!readOnly&&block.status==='done')setEditing(true);}}>

        {block.status==='generating'&&<BlockShimmer title={block.title} kind={block.kind}/>}

        {block.status==='error'&&(
          <div className="flex items-start gap-2 rounded bg-red-50/50 px-3 py-2 text-[11px]">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 text-red-400"/>
            <span className="text-red-700">Failed{block.title?` — ${block.title}`:''}</span>
          </div>
        )}

        {block.status==='pending'&&(
          <div className="flex items-center gap-2 py-2 px-1">
            <div className="h-1.5 w-1.5 rounded-full bg-slate-200/80"/>
            <span className="text-[9px] text-slate-400/60">{block.title||blockLabel(block.kind)}</span>
            <span className="ml-auto rounded bg-slate-100/50 px-1.5 py-0.5 text-[7px] font-medium uppercase tracking-wider text-slate-300">{block.kind.replace(/_/g,' ')}</span>
          </div>
        )}

        {block.status==='done'&&!editing&&(<>
          {block.kind==='heading'&&(()=>{
            const l=block.level||2;
            return <div className={
              l===1?'mt-10 mb-2 text-[19px] font-bold leading-tight tracking-[-0.01em] text-slate-900 first:mt-0'
              :l===2?'mt-7 mb-1 text-[15.5px] font-bold leading-snug text-slate-800 first:mt-0'
              :'mt-5 mb-0.5 text-[13px] font-semibold leading-snug text-slate-700 first:mt-0'
            }>{block.content||'Untitled'}</div>;
          })()}

          {block.kind==='narrative'&&<p className="py-[2px] text-[12.5px] leading-[1.8] text-slate-600">{block.content||(readOnly?'':<span className="italic text-slate-300">Double-click to edit…</span>)}</p>}

          {block.kind==='key_finding'&&(
            <div className="my-2.5 rounded bg-gradient-to-r from-blue-50/70 to-transparent px-4 py-3">
              <div className="mb-1 flex items-center gap-1.5"><TrendingUp className="h-2.5 w-2.5 text-blue-500"/><span className="text-[8px] font-bold uppercase tracking-[0.12em] text-blue-600/70">Key Finding</span></div>
              <p className="text-[12.5px] font-medium leading-[1.7] text-slate-700">{block.content}</p>
            </div>
          )}

          {(block.kind==='source_note'||block.kind==='footnote')&&<p className="py-0.5 text-[9.5px] leading-relaxed text-slate-400">{block.kind==='source_note'&&<span className="font-semibold text-slate-500">Source: </span>}{block.content}</p>}

          {(block.kind==='methodology_note'||block.kind==='data_caveat'||block.kind==='glossary_term')&&(
            <div className={`my-1.5 rounded px-3 py-2 text-[10.5px] leading-relaxed ${block.kind==='data_caveat'?'bg-amber-50/40 text-amber-800':'bg-slate-50/60 text-slate-500'}`}>
              <span className="font-semibold">{blockLabel(block.kind)}: </span>{block.content}
            </div>
          )}

          {block.kind==='chart'&&(
            <div className="my-3 overflow-hidden rounded border border-slate-200/50">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/40 px-4 py-1.5">
                <p className="text-[10px] font-semibold text-slate-600">{block.title||'Chart'}</p>
                <BarChart3 className="h-3 w-3 text-slate-300"/>
              </div>
              <div className="flex h-40 items-end gap-[2.5%] px-5 pb-5 pt-4">
                {[52,78,42,68,45,85,38,62,72,48,80,55].map((h,i)=>(
                  <div key={i} className="group/bar relative flex-1 rounded-t cursor-default" style={{height:`${h}%`,background:`hsl(${215+i*2.5},50%,${65+i*1.2}%)`}}>
                    <span className="pointer-events-none absolute -top-4 left-1/2 -translate-x-1/2 rounded bg-slate-700 px-1 py-px text-[7px] tabular-nums text-white opacity-0 group-hover/bar:opacity-100 transition-opacity">{h}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {block.kind==='table'&&(
            rankItems.length>0?<RankingTable items={rankItems} title={block.title} measure={block.title||'Value'}/>
            :aggRows.length>0?<AggTable rows={aggRows} title={block.title}/>
            :<div className="my-3 overflow-hidden rounded border border-slate-200/50">
              <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50/40 px-4 py-1.5">
                <p className="text-[10px] font-semibold text-slate-600">{block.title||'Table'}</p><Table2 className="h-3 w-3 text-slate-300"/>
              </div>
              <div className="flex h-16 items-center justify-center text-[10px] text-slate-400">Data renders after assembly</div>
            </div>
          )}

          {block.kind==='metric'&&(
            <div className="my-3 rounded border border-slate-200/50 bg-gradient-to-br from-white to-slate-50/30 px-5 py-3.5">
              <p className="text-[8px] font-bold uppercase tracking-[0.12em] text-slate-400">{block.title||'Metric'}</p>
              <div className="mt-1.5 flex items-baseline gap-2">
                <span className="text-[26px] font-bold tabular-nums leading-none text-slate-800">{fmtNum(block.metricValue)}</span>
                {block.metricUnit&&<span className="text-[11px] font-medium text-slate-400">{block.metricUnit}</span>}
              </div>
              {block.content&&<p className="mt-2 text-[10px] leading-relaxed text-slate-500">{block.content}</p>}
            </div>
          )}
        </>)}

        {editing&&<InlineEditor value={block.content} level={block.kind==='heading'?block.level:undefined} onChange={v=>onUpdate?.({content:v})} onBlur={()=>setEditing(false)}/>}
      </div>

      {/* insert line — visible on hover with clear affordance */}
      {!readOnly&&(
        <div className="relative flex h-3 items-center justify-center print:hidden" onClick={e=>e.stopPropagation()}>
          {active&&<div className="absolute inset-x-0 top-1/2 h-px bg-blue-100 transition-opacity"/>}
          {active&&(
            <button type="button" onClick={()=>setShowInsert(!showInsert)}
              className="relative z-10 flex h-4 w-4 items-center justify-center rounded-full border border-blue-200 bg-white text-blue-400 shadow-sm transition-all hover:scale-110 hover:border-blue-400 hover:text-blue-600 hover:shadow">
              <Plus className="h-2.5 w-2.5"/>
            </button>
          )}
          {showInsert&&<InsertMenu onInsert={k=>onInsertAfter?.(k)} onClose={()=>setShowInsert(false)}/>}
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   COVER + TOC
   ═══════════════════════════════════════════════════════════════════════════ */

function CoverSection({title,subtitle,blocks:rawBlocks,collapsed,onToggle}:{title:string;subtitle?:string;blocks:DocBlock[];collapsed:boolean;onToggle:()=>void}) {
  const blocks = rawBlocks || [];
  const wc = wordCount(blocks) || 0;
  const toc = extractToc(blocks);
  const done = blocks.filter(b=>b?.status==='done').length;
  const total = blocks.filter(b=>b?.kind!=='divider'&&b?.kind!=='spacer').length;
  const today = new Date().toLocaleDateString('en-IN',{day:'2-digit',month:'long',year:'numeric'});

  if (collapsed) return (
    <div className="mb-6 flex items-center justify-between rounded-md bg-slate-50/50 px-4 py-2 print:hidden">
      <div className="flex items-center gap-3">
        <div className="flex h-5 w-5 items-center justify-center rounded bg-slate-800 text-[6px] font-bold text-white">BS</div>
        <span className="text-[11px] font-semibold text-slate-700">{title}</span>
        <span className="text-[9px] text-slate-400">{today} · {wc.toLocaleString()} words</span>
      </div>
      <button type="button" onClick={onToggle} className="rounded px-2 py-0.5 text-[9px] font-medium text-blue-600 hover:bg-blue-50">Expand cover</button>
    </div>
  );

  return (
    <div className="mb-12 pb-10 border-b border-slate-200/50">
      {/* collapse toggle */}
      <div className="mb-6 flex justify-end print:hidden">
        <button type="button" onClick={onToggle} className="rounded px-2 py-0.5 text-[9px] font-medium text-slate-400 hover:bg-slate-50 hover:text-slate-600">Collapse</button>
      </div>
      {/* header strip */}
      <div className="mb-10 flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center rounded bg-slate-800 text-[9px] font-bold text-white">BS</div>
        <div><p className="text-[8px] font-bold uppercase tracking-[0.14em] text-slate-400">Ministry of Statistics & Programme Implementation</p><p className="text-[7px] text-slate-400">BharatStat Intelligence Platform</p></div>
      </div>

      {/* title */}
      <div className="h-0.5 w-12 rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 mb-4"/>
      <h1 className="text-[24px] font-bold leading-tight tracking-tight text-slate-900">{title||'Statistical Intelligence Report'}</h1>
      {subtitle&&<p className="mt-2 text-[13px] leading-relaxed text-slate-500">{subtitle}</p>}

      {/* meta chips */}
      <div className="mt-6 flex flex-wrap gap-3 text-[9px]">
        <span className="rounded bg-slate-50 px-2.5 py-1 text-slate-600"><span className="font-semibold text-slate-400">Date </span>{today}</span>
        <span className="rounded bg-slate-50 px-2.5 py-1 text-slate-600"><span className="font-semibold text-slate-400">Words </span>{wc.toLocaleString()} · {readTime(wc)}</span>
        <span className="rounded bg-slate-50 px-2.5 py-1 text-slate-600"><span className="font-semibold text-slate-400">Status </span>{done}/{total} components</span>
      </div>

      {/* TOC */}
      {toc.length>2&&(
        <div className="mt-8">
          <p className="mb-2 text-[8px] font-bold uppercase tracking-[0.12em] text-slate-400">Contents</p>
          <div className="space-y-[3px]">
            {toc.map((item,i)=>(
              <div key={item.id} className="flex items-baseline gap-1.5 text-[10px]" style={{paddingLeft:`${(item.level-1)*14}px`}}>
                <span className="shrink-0 tabular-nums text-slate-400">{i+1}.</span>
                <span className={item.level===1?'font-semibold text-slate-800':item.level===2?'font-medium text-slate-700':'text-slate-600'}>{item.text}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN CANVAS — continuous scroll (Google Docs / MS Word model)
   ═══════════════════════════════════════════════════════════════════════════ */

export function ReportDocumentCanvas({
  blocks: rawBlocks, onUpdateBlock, onReorderBlock, onDeleteBlock, onInsertBlock,
  readOnly=false, className, reportTitle, reportSubtitle,
}: ReportDocumentCanvasProps) {
  const blocks = rawBlocks || [];
  const [selectedId, setSelectedId] = useState<string|null>(null);
  const [coverCollapsed, setCoverCollapsed] = useState(false);
  const done = blocks.filter(b=>b?.status==='done').length;
  const total = blocks.filter(b=>b?.kind!=='divider'&&b?.kind!=='spacer').length;
  const gen = blocks.filter(b=>b?.status==='generating').length;
  const wc = wordCount(blocks) || 0;

  // Deselect when clicking the canvas background
  const handleBgClick = useCallback(() => setSelectedId(null), []);

  // Keyboard navigation
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!selectedId || readOnly) return;
      const blockIds = blocks.map(b => b.id);
      const idx = blockIds.indexOf(selectedId);
      if (idx < 0) return;

      if (e.key === 'ArrowDown' && idx < blockIds.length - 1) {
        e.preventDefault(); setSelectedId(blockIds[idx + 1]);
      } else if (e.key === 'ArrowUp' && idx > 0) {
        e.preventDefault(); setSelectedId(blockIds[idx - 1]);
      } else if (e.key === 'Delete' || e.key === 'Backspace') {
        if (!e.target || (e.target as HTMLElement).contentEditable !== 'true') {
          e.preventDefault(); onDeleteBlock?.(selectedId);
          setSelectedId(blockIds[idx + 1] || blockIds[idx - 1] || null);
        }
      } else if (e.key === 'Enter' && !e.shiftKey) {
        const block = blocks.find(b => b.id === selectedId);
        if (block && TEXT_KINDS.has(block.kind) && block.status === 'done') {
          e.preventDefault();
          // Trigger edit mode by scrolling into view
          const el = document.querySelector(`[data-block-id="${selectedId}"]`);
          el?.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        }
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [selectedId, blocks, readOnly, onDeleteBlock]);

  // Auto-collapse cover once generation starts
  useEffect(() => {
    if (gen > 0 && !coverCollapsed) setCoverCollapsed(true);
  }, [gen, coverCollapsed]);

  return (
    <div className={className||''}>
      {/* status bar */}
      {total>0&&(
        <div className="mb-4 flex items-center justify-between text-[9px] text-slate-400 print:hidden">
          <div className="flex items-center gap-2.5">
            <span className="font-medium text-slate-500">{wc.toLocaleString()} words</span>
            <span className="text-slate-200">·</span>
            <span>{readTime(wc)}</span>
            {gen>0&&<><span className="text-slate-200">·</span><span className="flex items-center gap-1 text-blue-500"><Loader2 className="h-2 w-2 animate-spin"/>{gen} writing</span></>}
          </div>
          <div className="flex items-center gap-1.5">
            <div className="h-[3px] w-16 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-400 transition-all duration-700" style={{width:`${total?(done/total)*100:0}%`}}/></div>
            <span className="tabular-nums">{done}/{total}</span>
          </div>
        </div>
      )}

      {/* ═══ THE DOCUMENT — single continuous surface ═══ */}
      <div
        className="mx-auto bg-white print:shadow-none print:m-0 cursor-default"
        onClick={handleBgClick}
        style={{
          width: '210mm',
          maxWidth: '100%',
          padding: '24mm 30mm',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.03), 0 2px 8px rgba(0,0,0,0.04), 0 12px 40px rgba(0,0,0,0.03)',
          borderRadius: '1px',
          minHeight: '297mm',
        }}
      >
        {/* Cover + TOC (collapsible) */}
        <CoverSection title={reportTitle||'Energy Statistics Report'} subtitle={reportSubtitle} blocks={blocks} collapsed={coverCollapsed} onToggle={()=>setCoverCollapsed(c=>!c)}/>

        {/* Content blocks — continuous flow */}
        <div>
          {blocks.map(block=>(
            <DocumentBlock key={block.id} block={block}
              onUpdate={onUpdateBlock?(u)=>onUpdateBlock(block.id,u):undefined}
              onReorder={onReorderBlock?(d)=>onReorderBlock(block.id,d):undefined}
              onDelete={onDeleteBlock?()=>onDeleteBlock(block.id):undefined}
              onInsertAfter={onInsertBlock?(k)=>onInsertBlock(block.id,k):undefined}
              readOnly={readOnly}
              isSelected={selectedId===block.id}
              onSelect={()=>setSelectedId(block.id)}/>
          ))}

          {blocks.length===0&&(
            <div className="flex h-40 flex-col items-center justify-center text-slate-300">
              <FileText className="mb-2 h-6 w-6 text-slate-200"/>
              <p className="text-[11px]">Content appears as components generate</p>
            </div>
          )}
        </div>

        {/* Document end footer */}
        {done>0&&(
          <div className="mt-16 border-t border-slate-200/50 pt-4 text-center text-[8px] text-slate-300 print:text-slate-400">
            <p>— End of Document —</p>
            <p className="mt-1">BharatStat Intelligence Report · Generated {new Date().toLocaleDateString('en-IN')} · {wc.toLocaleString()} words</p>
          </div>
        )}
      </div>
    </div>
  );
}
