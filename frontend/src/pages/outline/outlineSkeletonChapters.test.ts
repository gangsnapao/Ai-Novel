import { describe, expect, it } from "vitest";

import {
  deriveOutlineChaptersForSkeleton,
  inferOutlineTargetChapterCount,
} from "./outlineSkeletonChapters";

describe("outlineSkeletonChapters", () => {
  it("fills missing chapters from outline total and range settings", () => {
    const contentMd = `
# 全书总纲

## 节奏规划（205章）
- **第一卷（1-30章）**：重生囤货，极热降临，击溃周天豪。
- **第二卷（31-60章）**：极寒与异变升级，建立小区级交易站。
- **第三卷（61-100章）**：进入地下黑市，确立街区供应商地位。
- **第四卷（101-150章）**：攻占冷库园区，实现物资爆发。
- **第五卷（151-205章）**：进军总仓，建立区域新秩序。
`.trim();

    const chapters = deriveOutlineChaptersForSkeleton({
      contentMd,
      structure: {
        chapters: Array.from({ length: 10 }, (_, index) => ({
          number: index + 1,
          title: `已有章节 ${index + 1}`,
          beats: [`已有剧情 ${index + 1}`],
        })),
      },
    });

    expect(inferOutlineTargetChapterCount(contentMd, chapters)).toBe(205);
    expect(chapters).toHaveLength(205);
    expect(chapters[0]).toMatchObject({ number: 1, title: "已有章节 1" });
    expect(chapters[10]).toMatchObject({
      number: 11,
      title: "第11章 第一卷",
      beats: ["重生囤货，极热降临，击溃周天豪。"],
    });
    expect(chapters[204]).toMatchObject({
      number: 205,
      title: "第205章 第五卷",
      beats: ["进军总仓，建立区域新秩序。"],
    });
  });

  it("creates generic chapters when only a total chapter count can be inferred", () => {
    const contentMd = `
# 主纲

## 节奏规划（40章）
这里只写了总量，没有分卷明细。
`.trim();

    const chapters = deriveOutlineChaptersForSkeleton({
      contentMd,
      structure: null,
    });

    expect(chapters).toHaveLength(40);
    expect(chapters[0]).toMatchObject({ number: 1, title: "第1章", beats: [] });
    expect(chapters[39]).toMatchObject({ number: 40, title: "第40章", beats: [] });
  });
});
