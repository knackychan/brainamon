// ============================================================
// YOUTUBE PLAYLIST SCRAPER
// ============================================================
// Works for:
//   - Any playlist: https://www.youtube.com/playlist?list=PLxxxxxxx
//   - Watch Later:  https://www.youtube.com/playlist?list=WL
//   - Liked videos: https://www.youtube.com/playlist?list=LL
//
// 1. Open the playlist URL in your browser
// 2. Open DevTools (F12) → Console tab
// 3. Paste this entire script and press Enter
// 4. Wait for "DONE" alert — CSV downloads automatically
// ============================================================

(() => {
const STOP_AT = ''; // e.g. 'Some video title' — leave empty to scrape ALL
if (window.brainamonYouTubeRunning) {
  alert('A YouTube import is already running on this page. Wait for it to finish.');
  return;
}
const page = new URL(location.href);
if (!page.searchParams.get('list') || !['/playlist', '/watch'].includes(page.pathname)) {
  alert('Open one playlist using “View full playlist” / “Afficher la playlist complète”, then paste the script again. The playlists overview cannot be scraped as a video list.');
  return;
}
window.brainamonYouTubeRunning = true;

// ── State ──────────────────────────────────────────────────────────────────
let scraped = [];
let seen = new Set();
let hitStop = false;
let root;

// ── Helpers ────────────────────────────────────────────────────────────────
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function scrapeVisible() {
  let added = 0;

  // Each video in a playlist is a ytd-playlist-video-renderer element
  const items = root.querySelectorAll('ytd-playlist-video-renderer, ytd-playlist-panel-video-renderer');

  items.forEach(item => {
    if (hitStop) return;

    // Get video link
    const a = item.querySelector('a#wc-endpoint, a#thumbnail, a[href*="watch"]');
    if (!a) return;

    let url = '';
    try {
      const u = new URL(a.href);
      const videoId = u.searchParams.get('v');
      if (!videoId) return;
      url = `https://www.youtube.com/watch?v=${videoId}`;
    } catch(e) { return; }

    if (seen.has(url)) return;

    // Title
    const titleEl = item.querySelector('#video-title, h3 a, span#video-title');
    const description = titleEl ? titleEl.textContent.trim() : '';

    // Check stop condition
    if (STOP_AT && description.toLowerCase().includes(STOP_AT.toLowerCase())) {
      hitStop = true;
      console.log(`⛔ Stop condition hit: "${STOP_AT}"`);
      return;
    }

    // Channel name
    const channelEl = item.querySelector('ytd-channel-name a, .ytd-channel-name a, #channel-name a');
    const creator = channelEl ? channelEl.textContent.trim() : '';

    // Thumbnail: use YouTube's direct thumbnail URL (no need to scrape from DOM)
    const videoId = new URL(url).searchParams.get('v');
    const thumb = `https://i.ytimg.com/vi/${videoId}/hqdefault.jpg`;

    scraped.push({ url, description, creator, type: 'Video', thumb });
    seen.add(url);
    added++;
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
  a.download = `youtube_playlist_${new Date().toISOString().slice(0,10)}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  console.log(`✅ CSV downloaded: ${scraped.length} items`);
}

// ── Main scroll loop ────────────────────────────────────────────────────────
async function run() {
  for (let i = 0; i < 10 && !root; i++) {
    root = [...document.querySelectorAll('ytd-playlist-video-list-renderer, ytd-playlist-panel-renderer')]
      .find(el => el.getClientRects().length);
    if (!root) await sleep(500);
  }
  if (!root) throw new Error('No playlist video list was found. Open “View full playlist”, wait for the videos to load, then try again.');
  // The player sidebar scrolls independently of the document.
  function scrollArea() {
    const row = root.querySelector('ytd-playlist-video-renderer, ytd-playlist-panel-video-renderer');
    for (let el = row?.parentElement || root; el; el = el.parentElement) {
      if (el.scrollHeight > el.clientHeight + 1 && /auto|scroll/.test(getComputedStyle(el).overflowY)) return el;
    }
    return document.scrollingElement;
  }
  // Detect playlist name for logging
  const playlistTitle = document.querySelector('yt-formatted-string.title, h1.title')?.textContent?.trim() || 'Unknown playlist';
  console.log(`🚀 YouTube scraper started on: "${playlistTitle}"`);
  scrollArea().scrollTo(0, 0);
  await sleep(1000);

  scrapeVisible();
  let noNew = 0;
  let lastCount = scraped.length;
  let settled = false;

  for (let i = 0; i < 500; i++) {
    if (hitStop) break;

    if (new URL(location.href).searchParams.get('list') !== page.searchParams.get('list')) {
      throw new Error('The playlist changed during import. Stay on one playlist and try again.');
    }
    const area = scrollArea();
    const before = area.scrollTop;
    area.scrollBy(0, Math.max(300, area.clientHeight * 0.8));
    await sleep(1200);

    scrapeVisible();

    const bottom = area.scrollTop + area.clientHeight >= area.scrollHeight - 4;
    if (scraped.length === lastCount && bottom) {
      noNew++;
      if (noNew >= 6) {
        settled = true;
        console.log('No more loaded playlist videos found.');
        break;
      }
    } else {
      if (scraped.length === lastCount && area.scrollTop === before && !bottom) {
        throw new Error('The playlist did not scroll. Open “View full playlist” and try again.');
      }
      noNew = 0;
      lastCount = scraped.length;
    }

    if (i % 10 === 0) console.log(`⏳ Scroll ${i} — ${scraped.length} items so far`);
  }

  if (!scraped.length) {
    alert(hitStop ? 'The stop title was reached before any new videos. No CSV was created.'
      : 'No videos could be read. The playlist may be empty, unavailable, or its layout may have changed. No CSV was created.');
    return;
  }
  downloadCSV();
  const reason = hitStop ? 'Stopped at your chosen title.' : settled ? 'No more loaded videos found.' : 'Scroll limit reached; this is a partial result.';
  alert(`${scraped.length} YouTube videos collected from "${playlistTitle}". ${reason}\nThe CSV will auto-import while Brainamon is watching Downloads. Unavailable videos may be missing.`);
}

run().catch(error => alert(`YouTube import failed: ${error.message}\nNo CSV was created. Try the playlist-link import in Brainamon.`))
  .finally(() => { window.brainamonYouTubeRunning = false; });
})();
