/** Enterprise AST v2.0 — mirrors template_engine/ast/enterprise_schema.py */

export interface EnterpriseMetadata {
  documentId: string;
  version: string;
  language: string;
  createdAt: string;
  updatedAt: string;
  checksum: string;
  name?: string;
  source_hash?: string | null;
  page_count?: number;
  extraction_method?: string;
}

export interface SemanticNode {
  id: string;
  type: string;
  title: string;
  kind: string;
  required?: boolean;
  hints?: Record<string, unknown>;
  children?: SemanticNode[];
  contentRef?: string | null;
  tableRef?: string | null;
}

export interface EnterpriseDocumentAST {
  metadata: EnterpriseMetadata;
  layoutAST: { pages: unknown[] };
  styleAST: { styles: unknown[] };
  geometryAST: { nodes: unknown[] };
  assetAST: { assets: unknown[] };
  annotationAST: Record<string, unknown[]>;
  semanticAST: { nodes: SemanticNode[] };
  contentAST: { paragraphs: unknown[]; lists: unknown[]; quotes: unknown[]; codeBlocks: unknown[] };
  tableAST: { tables: unknown[] };
  figureAST: { figures: unknown[] };
  chartAST: { charts: unknown[] };
  entityGraph: { entities: unknown[] };
  relationshipGraph: { relationships: unknown[] };
  knowledgeGraph: { concepts: unknown[] };
  factGraph: { facts: unknown[] };
  analyticsAST: Record<string, unknown[]>;
  citationAST: { citations: unknown[] };
  retrievalAST: { chunks: unknown[] };
  agentAST: { agents: unknown[] };
  blocks?: unknown[];
  quality_report?: {
    passed: boolean;
    score: number;
    errors: string[];
    warnings: string[];
  };
}

export function isEnterpriseAst(ast: Record<string, unknown>): boolean {
  const meta = ast.metadata as EnterpriseMetadata | undefined;
  return meta?.version === '2.0' || 'layoutAST' in ast;
}
