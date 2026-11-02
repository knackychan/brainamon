// ============================================================
// FACEBOOK SAVED POSTS SCRAPER
// ============================================================
// 1. Open https://www.facebook.com/saved
// 2. F12 → Console → paste → Enter
//
// STOP_AT            : stop at this title (empty = scrape all)
// UNSAVE_AFTER_SCRAPE: unsave each item after scraping
// CAPTURE_THUMBS     : save thumbnail as base64
// ============================================================

const STOP_AT             = '';
const UNSAVE_AFTER_SCRAPE = false;
const CAPTURE_THUMBS      = true;

let scraped = [];
let seen    = new Set();
let running = true;

window.stopScraper = () => { running = false; };
console.log('💡 Type stopScraper() to stop early');

const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── Extract reel ID from a link ───────────────────────────────────────────
function getReelId(a) {
  try {
    const m = new URL(a.href).pathname.match(/\/(reel|watch|videos)\/(\d+)/);
    return m ? m[2] : null;
  } catch(e) { return null; }
}

// ── Extract the post caption from a saved-reel card ───────────────────────
// Facebook no longer keeps the caption in the card's visible innerText for every
// item (it can live in an aria-label / img alt / clamped node). Gather candidates
// from several sources and return the first that isn't boilerplate/meta.
function extractDescription(a, row, creator) {
  const cl = (creator || '').toLowerCase().trim();
  const isMeta = (raw) => {
    const t = (raw || '').toLowerCase().trim();
    if (t.length <= 5) return true;
    if (t.includes('saved from')) return true;
    if (t.includes('add to collection')) return true;
    if (t.includes('see more') || t.includes('see less')) return true;
    if (/^reels?\s*[•·]/i.test(t)) return true;
    if (cl && t === cl) return true;                                    // bare creator name
    if (/^\d+(\.\d+)?[kmb]?\s*(views?|likes?|comments?|shares?|plays?)/i.test(t)) return true;
    if (/^\d+\s*(s|m|h|d|w|y|hr|hrs|min|mins)\b/i.test(t)) return true; // "3d" / "5 h" timestamps
    if (/'s (video|reel|post)$/i.test(t)) return true;                 // "Jade Moon's video"
    return false;
  };

  const candidates = [];
  const push = (s) => { if (s) s.split('\n').forEach(l => candidates.push(l.trim())); };

  // Priority order: visible text → aria-labels → image alts. innerText stays first
  // so well-behaved cards keep their old result.
  push(row.innerText);
  if (a.getAttribute('aria-label')) candidates.push(a.getAttribute('aria-label').trim());
  row.querySelectorAll('[aria-label]').forEach(el => {
    const v = el.getAttribute('aria-label'); if (v) candidates.push(v.trim());
  });
  row.querySelectorAll('img[alt]').forEach(el => {
    const v = el.getAttribute('alt'); if (v) candidates.push(v.trim());
  });

  const good = candidates.filter(s => !isMeta(s));
  return good.length ? good[0] : '';
}

// ── Find all reel rows currently in DOM ───────────────────────────────────
function getVisibleRows() {
  const rows = [];
  document.querySelectorAll('a[href]').forEach(a => {
    const id = getReelId(a);
    if (!id || seen.has(id)) return;
    // Walk up to find the container with "Add to collection"
    let el = a.parentElement;
    for (let i = 0; i < 20; i++) {
      if (!el) break;
      if ((el.innerText || '').includes('Add to collection')) {
        rows.push({ id, a, row: el });
        return;
      }
      el = el.parentElement;
    }
  });
  return rows;
}

// ── Capture thumbnail ─────────────────────────────────────────────────────
async function getThumb(row) {
  if (!CAPTURE_THUMBS) return '';
  const img = row.querySelector('img[src*="fbcdn"], img[src*="scontent"]');
  if (!img?.src) return '';
  try {
    const blob = await (await fetch(img.src)).blob();
    return await new Promise(res => {
      const r = new FileReader();
      r.onload  = () => res(r.result.split(',')[1] || '');
      r.onerror = () => res('');
      r.readAsDataURL(blob);
    });
  } catch(e) { return ''; }
}

// ── Unsave a row ──────────────────────────────────────────────────────────
async function unsave(row) {
  try {
    row.scrollIntoView({ behavior: 'smooth', block: 'center' });
    await sleep(600);
    const btn = Array.from(row.querySelectorAll('[role="button"]'))
      .find(b => (b.getAttribute('aria-label') || '').includes('More options'));
    if (!btn) return false;
    btn.click();
    await sleep(800);
    const item = Array.from(document.querySelectorAll('[role="menuitem"]'))
      .find(m => m.innerText?.toLowerCase().includes('unsave'));
    if (!item) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      return false;
    }
    item.click();
    await sleep(1000);
    return true;
  } catch(e) { return false; }
}

// ── Download CSV ──────────────────────────────────────────────────────────
function downloadCSV() {
  const cols = ['id', 'url', 'description', 'creator', 'type', 'thumb'];
  const csv  = [cols.join(','),
    ...scraped.map(r => cols.map(c => `"${(r[c]||'').replace(/"/g,'""').replace(/\n/g,' ')}"`).join(','))
  ].join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
  a.download = `fb_saved_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
  console.log(`✅ Downloaded CSV: ${scraped.length} items`);
}

// ── Main ──────────────────────────────────────────────────────────────────
async function run() {
  console.log('🚀 Starting...');
  window.scrollTo(0, 0);
  await sleep(1500);

  let emptyScrolls = 0;

  while (running) {
    const rows = getVisibleRows();

    if (rows.length === 0) {
      // Nothing new visible — scroll down
      emptyScrolls++;
      if (emptyScrolls >= 10) { console.log('📭 Reached end.'); break; }
      window.scrollBy(0, 800);
      await sleep(1800);
      continue;
    }

    emptyScrolls = 0;

    // Process ALL newly visible rows in one pass
    for (const { id, a, row } of rows) {
      if (!running) break;
      seen.add(id);

      const fullText = row.innerText || '';

      // Stop condition
      if (STOP_AT && fullText.toLowerCase().includes(STOP_AT.toLowerCase())) {
        console.log(`⛔ Stop: "${STOP_AT}"`);
        running = false;
        break;
      }

      // Creator (from the "Reel • Creator" label)
      const cm = fullText.match(/Reels?\s*[•·]\s*([^\n]+)/i);
      const creator = cm ? cm[1].trim() : '';

      // Description — multi-source (innerText / aria-label / img alt), see extractDescription
      const description = extractDescription(a, row, creator);

      // Type
      const type = /\/(watch|videos)\//.test(a.href) ? 'Video' : 'Reel';

      // URL
      const url = 'https://www.facebook.com' + new URL(a.href).pathname;

      // Thumb
      const thumb = await getThumb(row);

      scraped.push({ id, url, description, creator, type, thumb });
      console.log(`📥 [${scraped.length}] ${id} — ${description.slice(0, 60)}`);

      // Unsave
      if (UNSAVE_AFTER_SCRAPE) {
        const ok = await unsave(row);
        console.log(ok ? '   🗑 Unsaved' : '   ⚠ Could not unsave');
      }

      await sleep(200);
    }

    // Scroll a bit to reveal more items
    window.scrollBy(0, 600);
    await sleep(1500);
  }

  console.log(`\n✅ Done! ${scraped.length} items scraped.`);
  downloadCSV();
  alert(`✅ Done!\n${scraped.length} items scraped${UNSAVE_AFTER_SCRAPE ? ' and unsaved' : ''}.\n\nThe CSV will auto-import into Brainamon.`);
}

run();
