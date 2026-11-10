"""经审查的浏览器执行片段（在 Playwright MCP 页面上下文运行）。

这些片段只做普通页面交互与 DOM 读取：滚动、点击“展开”、读取已加载文本。
不调用隐藏接口、不读取 Cookie/Token、不进行互动。
"""

from __future__ import annotations

# 小红书面：在结果页由 Agent 点击卡片后执行。一次完成展开与结构化提取。
# 回复容器递归解析，支持多层楼中楼；不以文本做全局去重。
XHS_EXPAND_AND_PARSE = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const sc = document.querySelector('.note-scroller');
  let lastCount = -1;
  let stable = 0;
  for (let round = 0; round < 20; round++) {
    [...document.querySelectorAll('.show-more')]
      .filter(b => /展开/.test(b.innerText || ''))
      .forEach(b => b.click());
    if (sc) sc.scrollTop = sc.scrollHeight;
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(800);
    const count = document.querySelectorAll('.parent-comment').length;
    if (count === lastCount) stable += 1; else stable = 0;
    lastCount = count;
    if (stable >= 3) break;
  }
  await sleep(1500);
  [...document.querySelectorAll('.show-more')]
    .filter(b => /展开/.test(b.innerText || ''))
    .forEach(b => b.click());
  if (sc) sc.scrollTop = sc.scrollHeight;
  window.scrollTo(0, document.body.scrollHeight);
  await sleep(1200);

  const parseItem = (el, level) => {
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
  // 递归处理 reply-container 内的一级、二级、三级回复。
  const parseReplies = (container, level) =>
    [...container.querySelectorAll(':scope > .list-container > .comment-item, :scope > .comment-item')]
      .map(r => {
        const node = parseItem(r, level);
        const sub = r.querySelector(':scope > .reply-container');
        if (sub) node.children = parseReplies(sub, level + 1);
        return node;
      });

  const items = [...document.querySelectorAll('.parent-comment')].map(pc => {
    const top = pc.querySelector(':scope > .comment-item');
    if (!top) return null;
    const node = parseItem(top, 1);
    const rc = pc.querySelector(':scope > .reply-container');
    if (rc) node.children = parseReplies(rc, 2);
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
# 一级评论与楼中楼通过缩进（getBoundingClientRect().left）区分；
# 回复挂到当前一级评论下；不做全局文本去重，避免不同楼层的相同文本被合并。
ZHIHU_EXPAND_AND_PARSE = r"""
async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  let lastCount = -1;
  let stable = 0;
  for (let round = 0; round < 15; round++) {
    [...document.querySelectorAll('button,div,span')]
      .filter(e => {
        const text = (e.innerText || '').trim();
        return text.length > 0 && text.length < 24 &&
          /展开.*回复|查看全部评论|加载更多|展开更多/.test(text);
      })
      .forEach(b => b.click());
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(700);
    const count = document.querySelectorAll('.CommentContent').length;
    if (count === lastCount) stable += 1; else stable = 0;
    lastCount = count;
    if (stable >= 3) break;
  }

  const nodes = [...document.querySelectorAll('.CommentContent')];
  const baseLeft = nodes.length ? nodes[0].getBoundingClientRect().left : 0;
  const seen = new Set();
  const roots = [];
  let currentTop = null;
  let currentTopIndex = -1;

  for (const el of nodes) {
    const text = (el.innerText || '').trim();
    if (!text) continue;
    const wrapper = el.parentElement ? el.parentElement.innerText : '';
    const timeMatch = wrapper.match(/\d{1,2}-\d{1,2}\s*·\s*[^\n]+/);
    const timeText = timeMatch ? timeMatch[0] : null;
    const left = Math.round(el.getBoundingClientRect().left);
    const level = left > baseLeft + 15 ? 2 : 1;
    const parentIndex = level === 1 ? 'root' : String(currentTopIndex);
    const key = `${level}|${parentIndex}|${text}|${timeText}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const node = {
      platform_comment_id: null,
      content: text,
      like_text: null,
      time_displayed: timeText,
      comment_level: level,
      children: []
    };
    if (level === 1 || !currentTop) {
      node.comment_level = 1;
      roots.push(node);
      currentTop = node;
      currentTopIndex = roots.length - 1;
    } else {
      currentTop.children.push(node);
    }
  }

  const m = document.body.innerText.match(/(\d+)\s*条评论/);
  return {
    title: document.title,
    url: location.href.split('?')[0],
    displayed_total: m ? Number(m[1]) : null,
    items: roots
  };
}
"""

# 搜索结果发现：只读取当前搜索结果页的链接，不进入详情。
DISCOVER_XHS_RESULTS = r"""
() => {
  const seen = new Set();
  const items = [];
  for (const a of [...document.querySelectorAll('a[href*="/search_result/"],a[href*="/explore/"]')]) {
    const href = a.href.split('?')[0];
    const text = (a.innerText || '').trim().replace(/\s+/g, ' ');
    if (!href || !text || text.length < 4 || seen.has(href)) continue;
    seen.add(href);
    items.push({href, text: text.slice(0, 160)});
  }
  return {url: location.href, items};
}
"""

DISCOVER_ZHIHU_RESULTS = r"""
() => {
  const seen = new Set();
  const items = [];
  for (const a of [...document.querySelectorAll('a[href*="/question/"],a[href*="/p/"]')]) {
    const href = a.href.split('?')[0];
    const text = (a.innerText || '').trim().replace(/\s+/g, ' ');
    if (!href || !text || text.length < 4 || seen.has(href)) continue;
    seen.add(href);
    items.push({href, text: text.slice(0, 160)});
  }
  return {url: location.href, items};
}
"""
