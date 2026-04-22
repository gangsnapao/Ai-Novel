import {
  deriveOutlineFromStoredContent,
  type OutlineGenChapter,
} from "../outlineParsing";

type OutlineChapterRangeSection = {
  start: number;
  end: number;
  label: string;
  summary: string;
};

const OUTLINE_RANGE_RE =
  /^(.+?)\s*[（(]\s*第?\s*(\d{1,4})\s*[-—–~至]+\s*(\d{1,4})\s*章\s*[）)]\s*(?:[：:]\s*(.+))?$/u;
const OUTLINE_TOTAL_RE_LIST = [
  /[（(]\s*(\d{1,4})\s*章\s*[）)]/gu,
  /目标(?:总)?章节数[：:]\s*(\d{1,4})/gu,
  /总章数[：:]\s*(\d{1,4})/gu,
];

function sanitizeMarkdownInline(text: string): string {
  return text
    .replace(/`+/g, "")
    .replace(/\*\*/g, "")
    .replace(/\*/g, "")
    .replace(/^#+\s*/, "")
    .replace(/^[>-]\s*/, "")
    .trim();
}

function pickOutlineSectionForChapter(
  sections: OutlineChapterRangeSection[],
  chapterNumber: number,
): OutlineChapterRangeSection | null {
  const candidates = sections.filter(
    (section) => chapterNumber >= section.start && chapterNumber <= section.end,
  );
  if (candidates.length === 0) return null;
  candidates.sort((left, right) => {
    const spanDiff = left.end - left.start - (right.end - right.start);
    if (spanDiff !== 0) return spanDiff;
    const summaryDiff = Number(Boolean(right.summary)) - Number(Boolean(left.summary));
    if (summaryDiff !== 0) return summaryDiff;
    return left.start - right.start;
  });
  return candidates[0] ?? null;
}

function inferOutlineRangeSections(contentMd: string): OutlineChapterRangeSection[] {
  const rawSections: OutlineChapterRangeSection[] = [];
  for (const rawLine of contentMd.split(/\r?\n/u)) {
    const line = sanitizeMarkdownInline(rawLine.trim());
    if (!line) continue;
    const match = line.match(OUTLINE_RANGE_RE);
    if (!match) continue;
    const start = Number(match[2]);
    const end = Number(match[3]);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0 || end < start) continue;
    const label = sanitizeMarkdownInline(match[1] ?? "");
    const summary = sanitizeMarkdownInline(match[4] ?? "");
    if (!label) continue;
    rawSections.push({ start, end, label, summary });
  }

  // Keep the monotonic global ranges and ignore later per-volume local ranges like 1-8 / 9-15 / ...
  const sections: OutlineChapterRangeSection[] = [];
  let maxEnd = 0;
  for (const section of rawSections) {
    if (section.end <= maxEnd) continue;
    sections.push(section);
    maxEnd = section.end;
  }
  return sections;
}

export function inferOutlineTargetChapterCount(
  contentMd: string,
  chapters: OutlineGenChapter[] = [],
): number | null {
  let maxValue = 0;
  for (const chapter of chapters) {
    const number = Number(chapter.number);
    if (Number.isFinite(number) && number > maxValue) maxValue = number;
  }

  for (const pattern of OUTLINE_TOTAL_RE_LIST) {
    for (const match of contentMd.matchAll(pattern)) {
      const value = Number(match[1]);
      if (Number.isFinite(value) && value > maxValue) maxValue = value;
    }
  }

  for (const section of inferOutlineRangeSections(contentMd)) {
    if (section.end > maxValue) maxValue = section.end;
  }

  return maxValue > 0 ? maxValue : null;
}

export function expandOutlineChaptersForSkeleton(args: {
  contentMd: string;
  chapters: OutlineGenChapter[];
}): OutlineGenChapter[] {
  const { contentMd, chapters } = args;
  const byNumber = new Map<number, OutlineGenChapter>();
  for (const chapter of chapters) {
    const number = Number(chapter.number);
    if (!Number.isFinite(number) || number <= 0) continue;
    byNumber.set(number, {
      number,
      title: typeof chapter.title === "string" ? chapter.title : "",
      beats: Array.isArray(chapter.beats) ? chapter.beats.map(String).filter(Boolean) : [],
    });
  }

  const targetChapterCount = inferOutlineTargetChapterCount(contentMd, chapters);
  if (!targetChapterCount || targetChapterCount <= byNumber.size) {
    return Array.from(byNumber.values()).sort((left, right) => left.number - right.number);
  }

  const sections = inferOutlineRangeSections(contentMd);
  for (let chapterNumber = 1; chapterNumber <= targetChapterCount; chapterNumber += 1) {
    if (byNumber.has(chapterNumber)) continue;
    const section = pickOutlineSectionForChapter(sections, chapterNumber);
    const sectionLabel = section?.label ?? "";
    const title = sectionLabel ? `第${chapterNumber}章 ${sectionLabel}` : `第${chapterNumber}章`;
    const beats = section?.summary ? [section.summary] : [];
    byNumber.set(chapterNumber, {
      number: chapterNumber,
      title,
      beats,
    });
  }

  return Array.from(byNumber.values()).sort((left, right) => left.number - right.number);
}

export function deriveOutlineChaptersForSkeleton(args: {
  contentMd: string;
  structure: unknown;
  previewChapters?: OutlineGenChapter[] | null;
}): OutlineGenChapter[] {
  const baseChapters =
    args.previewChapters && args.previewChapters.length > 0
      ? args.previewChapters
      : deriveOutlineFromStoredContent(args.contentMd, args.structure).chapters;

  return expandOutlineChaptersForSkeleton({
    contentMd: args.contentMd,
    chapters: baseChapters,
  });
}
