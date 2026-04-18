import { defineCollection } from 'astro:content';
import { file } from 'astro/loaders';
import { z } from 'astro/zod';

const stepSchema = z.object({
  title: z.string(),
  action: z.string(),
  tip: z.string().optional()
});

const featureCategories = [
  '群组核心',
  '入群风控',
  '内容审核',
  '积分运营',
  '消息自动化',
  '邀请增长',
  '群组扩展',
  '活动互动',
  '频道管理',
  '全局设置'
] as const;

const featureSchema = z.object({
  slug: z.string(),
  title: z.string(),
  category: z.enum(featureCategories),
  status: z.string(),
  summary: z.string(),
  kind: z.enum(['simple', 'workspace', 'runtime', 'reference', 'paused']),
  entry: z.object({
    label: z.string(),
    command: z.string().optional(),
    menuKeys: z.array(z.string()).default([])
  }),
  prerequisites: z.array(z.string()),
  steps: z.array(stepSchema),
  flowchart: z.union([
    z.literal('auto'),
    z.object({
      title: z.string(),
      mermaid: z.string()
    })
  ]),
  runtimeFlow: z.boolean().default(false),
  qa: z.array(
    z.object({
      question: z.string(),
      answer: z.string()
    })
  ),
  logicAudit: z.object({
    status: z.enum(['ok', 'needsReview']),
    items: z.array(z.string())
  }),
  truthTableNames: z.array(z.string()).default([])
});

export const collections = {
  features: defineCollection({
    loader: file('src/content/features/catalog.json', {
      parser: (text) => JSON.parse(text).features.map((feature: { slug: string }) => ({ id: feature.slug, ...feature }))
    }),
    schema: featureSchema
  })
};
