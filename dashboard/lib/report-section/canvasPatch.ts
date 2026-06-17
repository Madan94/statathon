import type { CanvasPatch, GeneratedSectionBlock, ReportSectionRequest } from './types';

export function buildCanvasPatch(request: ReportSectionRequest, blocks: GeneratedSectionBlock[]): CanvasPatch {
  const operations: CanvasPatch['operations'] = [];
  if (request.target.chapter?.create) {
    operations.push({ op: 'create_chapter', chapterTitle: request.target.chapter.title });
  }
  if (request.target.section?.create) {
    operations.push({ op: 'create_section', chapterTitle: request.target.chapter?.title, sectionTitle: request.target.section.title });
  }
  for (const block of blocks) {
    operations.push({
      op: request.target.insertAfterBlockId ? 'insert_after_block' : 'append_block',
      block,
      chapterTitle: request.target.chapter?.title,
      sectionTitle: request.target.section?.title,
      afterBlockId: request.target.insertAfterBlockId ?? null,
    });
  }
  return {
    requestId: request.requestId,
    templateId: request.target.templateId,
    signature: request.target.signature,
    operations,
  };
}
