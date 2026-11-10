"""浏览器侧脚本（在 ZCode 内置浏览器中执行）。

这些脚本是**确定性**的：搜索解析、滚动、展开、DOM 提取。
ZCode Agent 只负责把它们放进内置浏览器执行，不需要逐条推理页面结构。

约束：
- 只读取页面正常可见的 DOM，不调用隐藏接口；
- 不返回作者昵称、头像、用户 ID、主页、位置；
- 结果字段固定，Python 侧再做校验与分类。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 小红书
# ---------------------------------------------------------------------------

XHS_SEARCH_JS = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('section.note-item'));
  const bodyText = document.body ? document.body.innerText : '';
  return {
    pageTitle: document.title,
    raw: cards.length,
    loginWall: /登录后查看|扫码登录|请先登录/.test(bodyText),
    cards: cards.slice(0, 60).map((c, i) => {
      const a = c.querySelector('a.title');
      const id = c.getAttribute('data-note-id') || '';
      const anyLink = c.querySelector('a[href*="/search_result/"], a[href*="/explore/"]');
      const href = (a && a.getAttribute('href')) || (anyLink && anyLink.getAttribute('href')) || '';
      return {
        index: i,
        note_id: id,
        title: (a ? a.innerText : '').trim().slice(0, 120),
        href,
        canonical_url: id ? ('https://www.xiaohongshu.com/explore/' + id) : '',
      };
    }).filter(c => c.note_id),
  };
})()
"""

XHS_COUNT_JS = r"""
(() => document.querySelectorAll('.comment-item').length)
"""

XHS_SCROLL_JS = r"""
(() => {
  const el = document.querySelector('.note-scroller') || document.scrollingElement;
  if (el) el.scrollTop = el.scrollHeight;
  const comments = document.querySelector('.comments-container');
  if (comments) comments.scrollTop = comments.scrollHeight;
  return true;
})()
"""

XHS_EXTRACT_JS = r"""
(() => {
  const textOf = (el) => (el && el.innerText ? el.innerText.trim() : '');
  const title = textOf(document.querySelector('#detail-title'));
  const bodyEl = document.querySelector('.note-content .desc')
    || document.querySelector('#detail-desc')
    || document.querySelector('.note-content');
  let body = textOf(bodyEl).split('猜你想搜')[0].trim();
  const dateEl = document.querySelector('.bottom-container .date')
    || document.querySelector('.note-content .date')
    || document.querySelector('.publish-date');
  const totalText = textOf(document.querySelector('.comments-container .total')
    || document.querySelector('.comments-el .total'));
  const totalMatch = totalText.match(/(\d+)\s*条评论/);
  const parseItem = (el) => {
    const id = (el.id || '').replace(/^comment-/, '') || null;
    const content = textOf(el.querySelector('.content'));
    const like = textOf(el.querySelector('.interactions .like .count') || el.querySelector('.like .count'));
    const date = textOf(el.querySelector('.info .date') || el.querySelector('.date'));
    return {
      id,
      content: content.slice(0, 4000),
      like_text: like.slice(0, 20),
      date_text: date.slice(0, 40),
      children: [],
    };
  };
  const roots = [];
  Array.from(document.querySelectorAll('.parent-comment')).forEach((parent) => {
    const items = Array.from(parent.querySelectorAll('.comment-item'));
    if (!items.length) return;
    const rootEl = items.find((el) => !el.closest('.reply-container')) || items[0];
    const rootNode = parseItem(rootEl);
    if (!rootNode.content && !rootNode.id) return;
    const byEl = new Map([[rootEl, rootNode]]);
    items.forEach((el) => {
      if (el === rootEl) return;
      const node = parseItem(el);
      if (!node.content && !node.id) return;
      let ancestor = el.parentElement;
      let host = rootNode;
      while (ancestor && ancestor !== parent) {
        if (byEl.has(ancestor)) { host = byEl.get(ancestor); break; }
        ancestor = ancestor.parentElement;
      }
      host.children.push(node);
      byEl.set(el, node);
    });
    roots.push(rootNode);
  });
  return {
    url: location.href.split('?')[0].split('#')[0],
    title,
    body: body.slice(0, 20000),
    published_text: dateEl ? textOf(dateEl).slice(0, 60) : null,
    displayed_total: totalMatch ? parseInt(totalMatch[1], 10) : null,
    comments: roots,
  };
})()
"""

# ---------------------------------------------------------------------------
# 知乎
# ---------------------------------------------------------------------------

ZHIHU_SEARCH_JS = r"""
(() => {
  const cards = Array.from(document.querySelectorAll('.SearchResult-Card'));
  const origin = location.origin;
  const toAbsolute = (href) => (href && href.startsWith('http')) ? href : origin + href;
  return {
    pageTitle: document.title,
    raw: cards.length,
    loginWall: false,
    cards: cards.slice(0, 60).map((c, i) => {
      const link = Array.from(c.querySelectorAll('a[href]'))
        .map((a) => a.getAttribute('href') || '')
        .find((href) => href.includes('/answer/') || href.startsWith('/p/') || href.startsWith('/question/'));
      const titleEl = c.querySelector('h2, .ContentItem-title, a');
      return {
        index: i,
        note_id: '',
        title: (titleEl ? titleEl.innerText : '').trim().slice(0, 120),
        href: link ? toAbsolute(link) : '',
        canonical_url: link ? toAbsolute(link).split('?')[0] : '',
      };
    }).filter(c => c.href),
  };
})()
"""

ZHIHU_COUNT_JS = r"""
(() => document.querySelectorAll('.CommentContent').length)
"""

ZHIHU_SCROLL_JS = r"""
(() => {
  window.scrollBy(0, Math.max(window.innerHeight, 800));
  return true;
})()
"""

ZHIHU_EXTRACT_JS = r"""
(() => {
  const textOf = (el) => (el && el.innerText ? el.innerText.trim() : '');
  const title = textOf(document.querySelector('.QuestionHeader-title') || document.querySelector('.Post-Title'));
  let body = textOf(document.querySelector('.Post-RichText'));
  if (!body) {
    const parts = [];
    const q = document.querySelector('.QuestionRichText');
    if (q) parts.push(textOf(q));
    Array.from(document.querySelectorAll('.RichText')).slice(0, 2).forEach((el) => parts.push(textOf(el)));
    body = Array.from(new Set(parts.filter(Boolean))).join('\n');
  }
  const timeText = textOf(document.querySelector('.ContentItem-time')
    || document.querySelector('.Post-Time')
    || document.querySelector('.QuestionHeader-detail'));

  const items = Array.from(document.querySelectorAll('.ContentItem'));
  const scope = items.find((it) => it.querySelector('.CommentContent')) || document;
  let totalText = '';
  const candidates = Array.from(scope.querySelectorAll('.ContentItem-actions, .Post-Actions, .Comments-container, button'));
  for (const el of candidates) {
    const t = textOf(el).replace(/\s+/g, ' ');
    if (t.includes('条评论')) { totalText = t; break; }
  }
  if (!totalText) {
    for (const el of Array.from(document.querySelectorAll('button'))) {
      const t = textOf(el).replace(/\s+/g, ' ');
      if (t.includes('条评论')) { totalText = t; break; }
    }
  }
  const totalMatch = totalText.match(/(\d+)\s*条评论/);
  const comments = Array.from(scope.querySelectorAll('.CommentContent')).map((el) => {
    const rect = el.getBoundingClientRect();
    const container = el.closest('.CommentItem, .CommentItemV2, .CommentContentParent, div');
    const meta = container ? container.innerText : '';
    const timeMatch = meta.match(/(\d{2}-\d{2}\s*[·・]?\s*[^\n]{0,12})|(\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2})|(\d+\s*(?:小时|分钟|天)前)/);
    return {
      left: Math.round(rect.left),
      text: textOf(el).slice(0, 4000),
      time_text: timeMatch ? timeMatch[0].trim().slice(0, 30) : '',
    };
  });
  return {
    url: location.href.split('?')[0].split('#')[0],
    title,
    body: body.slice(0, 20000),
    published_text: timeText ? timeText.slice(0, 80) : null,
    displayed_total: totalMatch ? parseInt(totalMatch[1], 10) : null,
    comments_flat: comments,
  };
})()
"""

# ---------------------------------------------------------------------------
# 批处理工作流：一次调用完成"搜索 → 打开 → 展开 → 提取"
# ---------------------------------------------------------------------------

WORKFLOW_JS = r"""
async ({ tab, task, browser }) => {
  const wait = (ms) => tab.playwright.waitForTimeout(ms);
  const out = { platform: task.platform, query: task.query, search: null, articles: [], notes: [] };
  const isDetailUrl = (value) => (task.platform === 'zhihu'
    ? /\/(answer|question|p)\//.test(value)
    : /\/explore\//.test(value));
  const SEARCH_URL = task.search_url || "";

  if (SEARCH_URL) {
    await tab.goto(SEARCH_URL);
    await tab.playwright.waitForLoadState({ state: 'domcontentloaded' });
    await wait(2500);
    out.search = await tab.playwright.evaluate(task.scripts.search);
  }
  if (out.search && out.search.loginWall) {
    out.blocked = { kind: 'login_required', stage: 'search' };
    return out;
  }

  const cards = (out.search && out.search.cards) || [];
  const excluded = new Set((task.exclude_urls || []).map((u) => String(u)));
  const isExcluded = (c) => excluded.has(String(c && c.canonical_url ? c.canonical_url : ""));
  // 按搜索结果顺序组成候选池；跳过已采集 URL 与重复卡片，最多准备 size*3 个。
  const seen = new Set();
  const pool = [];
  for (const c of cards) {
    const key = String(c.canonical_url || c.note_id || "");
    if (!key || seen.has(key) || isExcluded(c)) continue;
    seen.add(key);
    pool.push(c);
    if (pool.length >= Math.max(task.size * 3, task.size)) break;
  }

  const backToSearch = async () => {
    if (!SEARCH_URL) return;
    try {
      const url = String(await tab.playwright.evaluate("(() => location.href)()"));
      if (url.indexOf('search_result') === -1 && url.indexOf('/search') === -1) {
        await tab.goto(SEARCH_URL);
        await tab.playwright.waitForLoadState({ state: 'domcontentloaded' });
        await wait(1800);
      }
    } catch (e) {}
  };

  const openXiaohongshu = async (t) => {
    const href = t.href ? String(t.href) : '';
    if (t.note_id) {
      for (const sel of ['a.title', 'a.cover', 'a']) {
        const loc = tab.playwright.locator('section.note-item[data-note-id="' + t.note_id + '"] ' + sel);
        if ((await loc.count()) === 0) continue;
        const beforeIds = browser ? (await browser.tabs.list()).map((x) => x.id) : [];
        try {
          await loc.nth(0).click({ timeout: 6000 });
        } catch (e) {
          continue;
        }
        await wait(1500);
        const nowUrl = String(await tab.playwright.evaluate("(() => location.href)()"));
        if (/\/explore\//.test(nowUrl)) return tab;
        if (browser) {
          const after = await browser.tabs.list();
          const fresh = after.find((x) => !beforeIds.includes(x.id) && /\/explore\//.test(x.url));
          if (fresh) return await browser.tabs.get(fresh.id);
        }
        return tab;
      }
    }
    if (href) {
      await tab.goto(href.startsWith('http') ? href : 'https://www.xiaohongshu.com' + href);
      return tab;
    }
    throw new Error('card_missing');
  };

  let okCount = 0;
  while (pool.length && okCount < task.size) {
    const card = pool.shift();
    const t = {
      note_id: card.note_id || null,
      canonical_url: card.canonical_url || null,
      href: card.href || '',
    };
    const entry = { candidate_id: null, note_id: t.note_id, canonical_url: t.canonical_url, ok: false };
    let workTab = tab;
    try {
      if (task.platform === 'zhihu') {
        const target = t.canonical_url || t.href;
        if (!target) throw new Error('missing_target_url');
        await tab.goto(target.startsWith('http') ? target : 'https://www.zhihu.com' + target);
      } else {
        workTab = await openXiaohongshu(t);
      }

      await workTab.playwright.waitForLoadState({ state: 'domcontentloaded' }).catch(() => {});
      await wait(1200);

      let url = '';
      for (let i = 0; i < 8; i += 1) {
        url = String(await workTab.playwright.evaluate("(() => location.href.split('?')[0])()"));
        if (/website-login|\/login/.test(url)) break;
        if (/\/404/.test(url)) break;
        if (isDetailUrl(url)) break;
        await wait(700);
      }
      entry.url = url;
      if (/website-login|\/login/.test(url)) {
        entry.error_type = 'login_required';
        entry.message = 'redirected_to_login';
        out.articles.push(entry);
        out.blocked = { kind: 'login_required', stage: 'detail' };
        break;
      }
      if (!isDetailUrl(url)) {
        throw new Error(/\/404/.test(url) ? 'note_unavailable' : 'detail_not_opened');
      }

      if (task.scripts.scroll) {
        let previous = -1;
        let stable = 0;
        for (let r = 0; r < 8; r += 1) {
          const before = task.scripts.count
            ? Number(await workTab.playwright.evaluate(task.scripts.count))
            : 0;
          await workTab.playwright.evaluate(task.scripts.scroll);
          await wait(600);
          const after = task.scripts.count
            ? Number(await workTab.playwright.evaluate(task.scripts.count))
            : 0;
          if (after === before && after === previous) {
            stable += 1;
            if (stable >= 2) break;
          } else {
            stable = 0;
          }
          previous = after;
        }
      }
      if (task.selectors && task.selectors.expand) {
        const buttons = workTab.playwright.locator(task.selectors.expand);
        const count = Math.min(await buttons.count(), 3);
        for (let i = 0; i < count; i += 1) {
          try { await buttons.nth(i).click({ timeout: 2500 }); await wait(800); } catch (e) {}
        }
      }

      const data = await workTab.playwright.evaluate(task.scripts.extract);
      out.articles.push({ ...entry, ...data, ok: true });
      okCount += 1;
    } catch (err) {
      if (!entry.error_type) {
        entry.error_type = 'selector_error';
        entry.message = String((err && err.message) || err).slice(0, 200);
      }
      out.articles.push(entry);
      if (workTab === tab) await backToSearch();
    } finally {
      if (workTab !== tab) {
        try { await workTab.close(); } catch (e) {}
      }
    }
  }
  return out;
}
"""


PLATFORM_SCRIPTS: dict[str, dict[str, str]] = {
    "xiaohongshu": {
        "search": XHS_SEARCH_JS,
        "scroll": XHS_SCROLL_JS,
        "count": XHS_COUNT_JS,
        "extract": XHS_EXTRACT_JS,
        "expand": ".show-more",
        "search_url_template": (
            "https://www.xiaohongshu.com/search_result?keyword={query}&source=web_explore_feed"
        ),
    },
    "zhihu": {
        "search": ZHIHU_SEARCH_JS,
        "scroll": ZHIHU_SCROLL_JS,
        "count": ZHIHU_COUNT_JS,
        "extract": ZHIHU_EXTRACT_JS,
        "expand": "button:has-text('展开')",
        "search_url_template": "https://www.zhihu.com/search?type=content&q={query}",
    },
}


def search_url(platform: str, query: str) -> str:
    from urllib.parse import quote

    return PLATFORM_SCRIPTS[platform]["search_url_template"].format(query=quote(query))


def task_scripts(platform: str) -> dict[str, str]:
    entry = PLATFORM_SCRIPTS[platform]
    return {
        "search": entry["search"],
        "scroll": entry["scroll"],
        "count": entry["count"],
        "extract": entry["extract"],
    }


def task_selectors(platform: str) -> dict[str, str]:
    return {"expand": PLATFORM_SCRIPTS[platform]["expand"]}
