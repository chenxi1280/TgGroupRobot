import { readFileSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import starlight from '@astrojs/starlight';

const catalog = JSON.parse(
  readFileSync(new URL('./src/content/features/catalog.json', import.meta.url), 'utf-8')
);

const categoryOrder = [
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
];

const categoryGroups = categoryOrder
  .map((category) => ({
    label: category,
    items: catalog.features
      .filter((feature) => feature.category === category)
      .map((feature) => ({
        label: feature.title,
        link: `/features/${feature.slug}/`
      }))
  }))
  .filter((group) => group.items.length > 0);

export default defineConfig({
  integrations: [
    starlight({
      title: 'TgGroupRobot 功能手册',
      description: 'Telegram 群组管理机器人功能介绍、配置步骤和常见问题。',
      locales: {
        root: {
          label: '简体中文',
          lang: 'zh-CN'
        }
      },
      customCss: ['./src/styles/custom.css'],
      tableOfContents: {
        minHeadingLevel: 2,
        maxHeadingLevel: 3
      },
      sidebar: [
        {
          label: '开始',
          items: [
            { label: '功能手册首页', link: '/' },
            { label: '快速开始', link: '/quick-start/' },
            { label: '功能总览', link: '/features/' }
          ]
        },
        ...categoryGroups
      ],
      pagefind: true,
      lastUpdated: true,
      credits: false
    }),
    mdx()
  ]
});
