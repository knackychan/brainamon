// Joined with the phone's Threads card reader by library/scrape_watch.py.
// Paste on Threads Saved while signed in. Reads saves without removing anything.
(async function () {
  'use strict';
  const STOP_AT = '';
  // THREADS_SITE

  const saved = () => /(^|\.)threads\.(com|net)$/i.test(location.hostname) && SITE.onSaved(location);
  if (!saved()) { alert('Open https://www.threads.com/saved and sign in, then run the script again.'); return; }
  if (window.brainamonThreadsRunning) { alert('The Threads scraper is already running.'); return; }
  window.brainamonThreadsRunning = true;
  const rows = [], seen = new Set(), stop = STOP_AT.trim().toLowerCase();
  let empty = 0, stopped = false;
  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  try {
    window.scrollTo(0, 0);
    await sleep(4000);
    while (empty < 10 && rows.length < 20000 && !stopped) {
      if (!saved() || document.querySelector('input[type="password"], input[autocomplete="one-time-code"]')) {
        throw new Error('Threads Saved became unavailable. Sign in and run the script again.');
      }
      let fresh = 0;
      for (const card of SITE.read(document)) {
        const key = SITE.key(card.url);
        if (!key || seen.has(key)) continue;
        seen.add(key);
        fresh++;
        if (stop && card.caption.toLowerCase().includes(stop)) { stopped = true; break; }
        let thumb = '';
        if (card.pic && card.pic.length <= 2000) {
          try {
            const url = new URL(card.pic);
            if (url.protocol !== 'https:' || url.username || url.password || url.port ||
                !/(^|\.)(cdninstagram\.com|fbcdn\.net)$/i.test(url.hostname)) throw new Error('Invalid picture');
            const response = await fetch(url.href, { redirect: 'error' });
            if (response.ok) {
              const blob = await response.blob();
              thumb = await new Promise(resolve => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result || '').split(',')[1] || '');
                reader.onerror = () => resolve('');
                reader.readAsDataURL(blob);
              });
            }
          } catch (e) { /* Keep the post text and link when its picture cannot be read. */ }
        }
        rows.push({ url: card.url, description: card.caption, creator: card.creator, type: card.kind, thumb });
        if (rows.length >= 20000) break;
      }
      console.log(`Threads: ${rows.length} saved posts collected.`);
      empty = fresh ? 0 : empty + 1;
      if (!stopped) {
        const el = document.scrollingElement || document.documentElement, before = el.scrollTop;
        window.scrollBy(0, Math.round(window.innerHeight * 0.85));
        if (el.scrollTop === before) window.scrollTo(0, el.scrollHeight);
        await sleep(1500);
      }
    }
    if (!rows.length) {
      alert(stopped ? 'The stop title was reached. No new Threads posts to export.' : 'No Threads posts could be read. Saved may be empty or the page layout may have changed.');
      return;
    }
    const fields = ['url', 'description', 'creator', 'type', 'thumb'];
    const csv = [fields.join(','), ...rows.map(row => fields.map(field => '"' + String(row[field] || '').replace(/"/g, '""') + '"').join(','))].join('\n');
    const href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    const a = document.createElement('a');
    a.href = href;
    a.download = `threads_saved_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1000);
    alert(`Exported ${rows.length} Threads posts${rows.length >= 20000 ? ' (20,000-post limit reached)' : ''}. Keep the Scrapers window open while Brainamon imports the CSV.`);
  } catch (e) {
    alert(`Threads scraper stopped: ${e.message}`);
    console.error(e);
  } finally {
    window.brainamonThreadsRunning = false;
  }
})();
