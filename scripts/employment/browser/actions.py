"""经审查的浏览器执行片段（在 Playwright MCP 页面上下文运行）。

这些片段只做普通页面交互与 DOM 读取：滚动、点击“展开”、读取已加载文本。
不调用隐藏接口、不读取 Cookie/Token、不进行互动。
"""

from __future__ import annotations

# 小红书面：在结果页由 Agent 点击卡片后执行。一次完成展开与结构化提取。
XHS_EXPAND_AND_PARSE = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const sc = document.querySelector('.note-scroller');
  for (let round = 0; round < 20; round++) {
    [...document.querySelectorAll('.show-more')]
      .filter(b => /展开/.test(b.innerText || ''))
      .forEach(b => b.click());
    if (sc) sc.scrollTop = sc.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(900);
  }
  const parseItem = (el, level, rootId) => {
    const id = (el.id || '').replace(/^comment-/, '');
    const text = (el.querySelector('.content')?.innerText || '').trim();
    const like = (el.querySelector('.interactions .like .count')?.innerText || '').trim();
    const date = (el.querySelector('.info .date')?.innerText || '').trim();
    return {
      platform_comment_id: id || null,
      content: text,
      like_text: like || null,
      time_displayed: date || null,
      comment_level: level,
      children: []
    };
  };
  const parseReplies = (container, rootId, level) =>
    [...container.querySelectorAll(':scope > .list-container > .comment-item, :scope > .comment-item')]
      .map(r => parseItem(r, level, rootId));
  const items = [...document.querySelectorAll('.parent-comment')].map(pc => {
    const top = pc.querySelector(':scope > .comment-item');
    if (!top) return null;
    const node = parseItem(top, 1, (top.id || '').replace(/^comment-/, ''));
    const rc = pc.querySelector(':scope > .reply-container');
    if (rc) node.children = parseReplies(rc, (top.id || '').replace(/^comment-/, ''), 2);
    return node;
  }).filter(Boolean);
  const m = document.body.innerText.match(/共\s*([\d,]+)\s*条评论/);
  return {
    title: document.title,
    url: location.href.split('?')[0],
    displayed_total: m ? Number(m[1].replace(/,/g, '')) : null,
    items
  };
}
"""

# 知乎专栏/回答页：滚动并展开可见评论后一次性提取。
ZHIHU_EXPAND_AND_PARSE = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  for (let round = 0; round < 12; round++) {
    [...document.querySelectorAll('button,div,span')]
      .filter(e => {
        const text = (e.innerText || '').trim();
        return text.length > 0 && text.length < 24 &&
          /展开.*回复|查看全部评论|加载更多|展开更多/.test(text);
      })
      .forEach(b => b.click());
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(700);
  }
  const seen = new Set();
  const items = [];
  for (const el of [...document.querySelectorAll('.CommentContent')]) {
    const text = (el.innerText || '').trim();
    if (!text || seen.has(text)) continue;
    seen.add(text);
    items.push({
      platform_comment_id: null,
      content: text,
      like_text: null,
      time_displayed: null,
      comment_level: 1,
      children: []
    });
  }
  const m = document.body.innerText.match(/(\d+)\s*条评论/);
  return {
    title: document.title,
    url: location.href.split('?')[0],
    displayed_total: m ? Number(m[1]) : null,
    items
  };
}
"""
