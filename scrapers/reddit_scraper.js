// ============================================================
// REDDIT SAVED SCRAPER
// ============================================================
// Reads your saved posts and comments from Reddit's own JSON listing
// (/user/<you>/saved.json) with your logged-in session: no API key.
//
// 1. Open any reddit.com page while logged in (the Scrapers window opens your saved page)
// 2. Open DevTools (F12) → Console tab
// 3. Paste this entire script and press Enter
// 4. Wait for "DONE" alert — CSV downloads automatically
//
// The post itself (title, full text, gallery captions, link; a crosspost's original) comes with the
// saved list: no extra request. Describe reads it from the description.
// FETCH_COMMENTS (off by default) also asks for each post's top comments: one request per post,
// ~2-3 s each, and Reddit often refuses them (429); 3 refusals in a row switch comments off.
//
// Reddit only lists your newest ~1000 saved items. For older ones, request your data at
// reddit.com/settings/data-request (saved_posts.csv).
// ============================================================

const STOP_AT = ''; // e.g. 'Some post title' — leave empty to scrape ALL

const PAGE_DELAY = 1000;   // ms between listing pages
const THUMB_WIDTH = 320;   // smallest preview at least this wide
const SELFTEXT_MAX = 4000; // characters of a text post kept in the description (what Describe reads)
const FETCH_COMMENTS = false; // true: also the top comments (slow, often rate limited)
const COMMENTS = 8;          // top comments kept per post
const COMMENT_MAX = 500;     // characters kept per comment
const THREAD_DELAY = 2000;   // ms between comment requests (Reddit throttles fast readers)
const MAX_THREAD_FAILS = 3;  // comment requests failing in a row before comments are switched off

// ── State ──────────────────────────────────────────────────────────────────
let scraped = [];
let seen = new Set();
let hitStop = false;
let commentsOn = FETCH_COMMENTS;
let threadFails = 0;

// ── Helpers ────────────────────────────────────────────────────────────────
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function waitSeconds(r, attempt) {
  // Reddit's own hint (Retry-After or x-ratelimit-reset), else 15 s, 30 s, 60 s
  const hint = Number(r.headers.get('retry-after') || r.headers.get('x-ratelimit-reset'));
  return hint > 0 && hint <= 600 ? hint : 15 * 2 ** attempt;
}

async function getJSON(path, attempts = 3) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    const r = await fetch(path, { credentials: 'include' });
    if (r.status === 429) {
      const s = waitSeconds(r, attempt);
      console.log(`⏸ Rate limited, waiting ${s} s...`);
      await sleep(s * 1000);
      continue;
    }
    if (!r.ok) throw new Error(`${path} answered ${r.status}`);
    // nearly out of requests for this window: pause until it resets
    const left = Number(r.headers.get('x-ratelimit-remaining'));
    const reset = Number(r.headers.get('x-ratelimit-reset'));
    if (r.headers.has('x-ratelimit-remaining') && left < 2 && reset > 0 && reset <= 600) {
      console.log(`⏸ Request budget used up, waiting ${reset} s...`);
      await sleep(reset * 1000);
    }
    return r.json();
  }
  throw new Error(`${path}: still rate limited`);
}

function canonical(permalink) {
  // Same form as the share-link rule: https://www.reddit.com/r/.../comments/.../ with no query
  const u = new URL(permalink, 'https://www.reddit.com');
  return `https://www.reddit.com${u.pathname}`;
}

function pickImages(d) {
  // Picture candidates, best first: the preview (smallest resolution at least THUMB_WIDTH wide, then the
  // source), the first gallery picture, Reddit's small thumbnail. A preview link can be expired (404).
  const out = [];
  const img = d.preview && d.preview.images && d.preview.images[0];
  if (img) {
    const fit = (img.resolutions || []).find(r => r.width >= THUMB_WIDTH);
    if (fit) out.push(fit.url);
    if (img.source) out.push(img.source.url);
  }
  if (d.media_metadata) {
    const first = d.gallery_data && d.gallery_data.items && d.gallery_data.items[0];
    const meta = first ? d.media_metadata[first.media_id] : Object.values(d.media_metadata)[0];
    if (meta && meta.p) {
      const fit = meta.p.find(r => r.x >= THUMB_WIDTH);
      if (fit) out.push(fit.u);
      if (meta.s && meta.s.u) out.push(meta.s.u);
    }
  }
  // 'self', 'default', 'nsfw' ... are not pictures
  if (/^https?:/.test(d.thumbnail || '')) out.push(d.thumbnail);
  return out.filter(Boolean);
}

async function toBase64(urls) {
  // Raw base64 (no data: prefix), as the importer expects, from the first candidate that loads.
  for (const url of urls || []) {
    try {
      const r = await fetch(url);
      if (!r.ok) continue;
      const blob = await r.blob();
      const dataUrl = await new Promise((res, rej) => {
        const fr = new FileReader();
        fr.onload = () => res(fr.result);
        fr.onerror = rej;
        fr.readAsDataURL(blob);
      });
      const b64 = String(dataUrl).split(',')[1] || '';
      if (b64) return b64;
    } catch (e) {
      // the next candidate
    }
  }
  return '';
}

async function getThread(permalink) {
  // The post (with its full text) and its top-level comments, best first. One try only: a 429 here
  // counts toward MAX_THREAD_FAILS instead of stalling every item.
  const path = new URL(permalink, 'https://www.reddit.com').pathname.replace(/\/?$/, '/');
  const j = await getJSON(`${path}.json?raw_json=1&sort=top&depth=1&limit=${COMMENTS + 4}`, 2);
  const post = (j[0] && j[0].data.children[0] && j[0].data.children[0].data) || {};
  const comments = ((j[1] && j[1].data.children) || [])
    .filter(c => c.kind === 't1')
    .map(c => c.data)
    .filter(c => !c.stickied && c.author !== 'AutoModerator' && c.author !== '[deleted]'
                 && c.body && c.body !== '[removed]' && c.body !== '[deleted]')
    .slice(0, COMMENTS);
  return { post, comments };
}

function commentLines(comments) {
  if (!comments.length) return '';
  return '\n\nTop comments:\n' + comments.map(c =>
    `- u/${c.author} (${c.score}): ${c.body.replace(/\s+/g, ' ').slice(0, COMMENT_MAX)}`
  ).join('\n');
}

async function addThread(row, child) {
  // Post text for a saved comment, top comments for a saved post. A failed request keeps the row as it is;
  // MAX_THREAD_FAILS failures in a row switch comments off so the scrape still finishes.
  try {
    const d = child.data;
    if (child.kind === 't1') {
      const link = d.link_permalink || `/comments/${String(d.link_id || '').replace(/^t3_/, '')}/`;
      const { post } = await getThread(link);
      if (post.selftext) row.description += `\n\nThe post: ${post.selftext.slice(0, SELFTEXT_MAX)}`;
    } else {
      const { comments } = await getThread(d.permalink);
      row.description += commentLines(comments);
    }
    threadFails = 0;
  } catch (e) {
    threadFails++;
    console.log(`⚠ No comments for ${row.url}: ${e.message}`);
    if (threadFails >= MAX_THREAD_FAILS) {
      commentsOn = false;
      console.log('⛔ Reddit keeps refusing comment requests: going on without comments.');
    }
  }
  await sleep(THREAD_DELAY);
}

function toRow(child) {
  const d = child.data;
  if (child.kind === 't1') {
    // A saved comment
    const title = d.link_title || '';
    return {
      url: canonical(d.permalink),
      description: (title ? `Comment on "${title}": ` : '') + (d.body || ''),
      creator: `r/${d.subreddit}`,
      type: 'Post',
      match: `${title} ${d.body || ''}`,
      name: d.name,
      images: [],
    };
  }
  // A saved post (t3). A crosspost's content (text, link, pictures, video) lives in the original post.
  const src = (d.crosspost_parent_list && d.crosspost_parent_list[0]) || d;
  let description = d.title || '';
  if (src.selftext) description += '\n\n' + src.selftext.slice(0, SELFTEXT_MAX);
  const captions = ((src.gallery_data && src.gallery_data.items) || []).map(i => i.caption).filter(Boolean);
  if (captions.length) description += '\n\n' + captions.join('\n');
  if (!src.is_self && src.url && !/reddit\.com|redd\.it/.test(src.domain || '')) description += `\n\n${src.url}`;
  return {
    url: canonical(d.permalink),
    description,
    creator: `r/${d.subreddit}`,
    type: src.is_video ? 'Video' : 'Post',
    match: d.title || '',
    name: d.name,
    images: pickImages(src),
  };
}

function downloadCSV() {
  const headers = ['url', 'description', 'creator', 'type', 'thumb'];
  const rows = scraped.map(item =>
    headers.map(h => `"${String(item[h] || '').replace(/"/g, '""')}"`).join(',')
  );
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `reddit_saved_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  console.log(`✅ CSV downloaded: ${scraped.length} items`);
}

// ── Main listing loop ──────────────────────────────────────────────────────
// collect() is shared with scrapers/reddit_saved_playwright.py (window.__cm); run() is the console path.
async function collect(stopAt = STOP_AT) {
  const me = await getJSON('/api/me.json');
  const name = me && me.data && me.data.name;
  if (!name) throw new Error('Not logged in to Reddit: log in, then run the script again.');
  console.log(`🚀 Reddit scraper started for u/${name}`);

  let after = '';
  let thumbs = 0;
  for (let page = 0; page < 50 && !hitStop; page++) {
    const q = `limit=100&raw_json=1${after ? `&after=${after}` : ''}`;
    const listing = await getJSON(`/user/${encodeURIComponent(name)}/saved.json?${q}`);
    const children = (listing.data && listing.data.children) || [];

    for (const child of children) {
      if (child.kind !== 't1' && child.kind !== 't3') continue;
      const row = toRow(child);
      if (stopAt && row.match.toLowerCase().includes(stopAt.toLowerCase())) {
        hitStop = true;
        console.log(`⛔ Stop condition hit: "${stopAt}"`);
        break;
      }
      if (seen.has(row.url)) continue;
      seen.add(row.url);
      if (commentsOn) await addThread(row, child);
      row.thumb = await toBase64(row.images);
      if (row.thumb) thumbs++;
      scraped.push(row);
    }

    console.log(`⏳ Page ${page + 1} — ${scraped.length} items so far`);
    after = listing.data && listing.data.after;
    if (!after) break;
    await sleep(PAGE_DELAY);
  }
  console.log(`✅ Done! ${scraped.length} items scraped (${thumbs} with a thumbnail).`);
  return { user: name, modhash: (me.data && me.data.modhash) || '', thumbs, rows: scraped };
}

async function unsave(fullname, modhash) {
  // What the "unsave" button sends (old.reddit.com: the modhash comes with /api/me.json). True when Reddit accepts it.
  const r = await fetch('/api/unsave', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-Modhash': modhash },
    body: `id=${encodeURIComponent(fullname)}&uh=${encodeURIComponent(modhash)}`,
  });
  return r.ok;
}

async function run() {
  if (!/(^|\.)reddit\.com$/.test(location.hostname)) {
    alert('Run this on a reddit.com page (logged in).');
    return;
  }
  const { thumbs } = await collect();
  downloadCSV();
  alert(`Done! ${scraped.length} Reddit saved items scraped (${thumbs} with a thumbnail).\n` +
        (FETCH_COMMENTS && !commentsOn ? 'Reddit refused comment requests partway: some items have no comments.\n' : '') +
        'The CSV will auto-import into Brainamon. Run Fetch link info for the missing thumbnails.');
}

window.__cm = { collect, unsave };
if (!window.__CM_NO_RUN) {
  run().catch(e => {
    console.error('❌ Reddit scraper failed:', e);
    if (scraped.length) downloadCSV();
    alert(`Reddit scraper stopped: ${e.message}` + (scraped.length ? `\n${scraped.length} items saved to the CSV.` : ''));
  });
}
