// ============================================================
// INSTAGRAM SAVED POSTS SCRAPER
// ============================================================
// 1. Open https://www.instagram.com/<your username>/saved/all-posts/ (your profile, Saved, All posts)
// 2. Open DevTools (F12) → Console tab
// 3. Paste this entire script and press Enter
// 4. Wait for "DONE" alert — CSV downloads automatically
//
// OPTIONAL: Set a stop title below to stop at a specific post
// ============================================================

const STOP_AT = ''; // e.g. 'Some post title' — leave empty to scrape ALL

// ── State ──────────────────────────────────────────────────────────────────
let scraped = [];
let seen = new Set();
let hitStop = false;

// ── Helpers ────────────────────────────────────────────────────────────────
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function scrapeVisible() {
  let added = 0;

  // Instagram saved posts are in <article> or <div role="presentation"> blocks
  // Each post links to /p/SHORTCODE/ or /reel/SHORTCODE/
  const links = Array.from(document.querySelectorAll('a[href*="/p/"], a[href*="/reel/"]'));

  links.forEach(a => {
    if (hitStop) return;
    try {
      const p = new URL(a.href).pathname;
      // Normalize URL
      const url = 'https://www.instagram.com' + p.replace(/\/$/, '') + '/';
      if (seen.has(url)) return;

      // Type: reel or post
      const type = p.includes('/reel/') ? 'Reel' : 'Post';

      // Get image thumbnail
      const img = a.querySelector('img');
      const thumb = img ? img.src : '';

      // Alt text often contains the description
      const description = img ? (img.alt || '') : '';

      // Check stop condition
      if (STOP_AT && description.toLowerCase().includes(STOP_AT.toLowerCase())) {
        hitStop = true;
        console.log(`⛔ Stop condition hit: "${STOP_AT}"`);
        return;
      }

      scraped.push({ url, description, creator: '', type, thumb });
      seen.add(url);
      added++;
    } catch(e) {}
  });

  return added;
}

function downloadCSV() {
  const headers = ['url', 'description', 'creator', 'type', 'thumb'];
  const rows = scraped.map(item =>
    headers.map(h => `"${(item[h] || '').replace(/"/g, '""').replace(/\n/g, ' ')}"`).join(',')
  );
  const csv = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `instagram_saved_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  console.log(`✅ CSV downloaded: ${scraped.length} items`);
}

// ── Main scroll loop ────────────────────────────────────────────────────────
async function run() {
  console.log('🚀 Instagram scraper started...');
  window.scrollTo(0, 0);
  await sleep(1000);

  scrapeVisible();
  let noNew = 0;
  let lastCount = scraped.length;

  for (let i = 0; i < 500; i++) {
    if (hitStop) break;

    window.scrollBy(0, 1200);
    await sleep(1500);

    scrapeVisible();

    if (scraped.length === lastCount) {
      noNew++;
      if (noNew >= 8) {
        console.log('📭 No new items found — reached end of saved posts.');
        break;
      }
    } else {
      noNew = 0;
      lastCount = scraped.length;
    }

    if (i % 10 === 0) console.log(`⏳ Scroll ${i} — ${scraped.length} items so far`);
  }

  console.log(`✅ Done! ${scraped.length} items scraped.`);
  downloadCSV();
  alert(`Done! ${scraped.length} Instagram saved posts scraped.\nThe CSV will auto-import into Brainamon.`);
}

run();
