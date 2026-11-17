package app.brainamon.mobile;

import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * The pure part of the site tray (projects/motion-language plan 06, SiteTray.java): labels with their English
 * fallbacks, the plural rule, the crop of a picture out of a window snapshot and the spacing of arrivals. No
 * Android imports on purpose: tests/test_phone_site_tray.py compiles this file with a plain javac and runs it.
 */
final class SiteText {
    static final int MAX_LABELS_BYTES = 16 * 1024, MAX_LABEL = 200, MAX_ENTRIES = 64, MAX_KEY = 40;
    static final int MAX_FLIGHTS = 3, MIN_SIDE = 8, MAX_BATCH = 25;
    static final long MAX_GAP_MS = 290, GAP_BUDGET_MS = 1100;

    private static final Map<String, String> DEFAULTS = new HashMap<>();

    static {
        DEFAULTS.put("cancel", "Cancel");
        DEFAULTS.put("close", "Close");
        DEFAULTS.put("signIn", "Sign in to {site}. Reading starts by itself.");
        DEFAULTS.put("signedIn", "Signed in. Opening your saved list\u2026");
        DEFAULTS.put("check", "Finish the check on the page. Reading goes on by itself.");
        DEFAULTS.put("wait", "Paused (offline or in the background)");
        DEFAULTS.put("reading", "Reading your saved posts");
        DEFAULTS.put("newWord_one", "new");
        DEFAULTS.put("newWord_other", "new");
        DEFAULTS.put("known_one", "{k} already in library");
        DEFAULTS.put("known_other", "{k} already in library");
        DEFAULTS.put("doneNew_one", "new post");
        DEFAULTS.put("doneNew_other", "new posts");
        DEFAULTS.put("doneEnd", "Read to the end of your list");
        DEFAULTS.put("doneKnown", "Stopped at posts already in your library");
        DEFAULTS.put("doneCap", "Stopped at 20,000 saved items");
        DEFAULTS.put("doneEmpty", "Brainamon could not read this page; the site may have changed");
        DEFAULTS.put("review", "Review & import");
        DEFAULTS.put("back", "Back to Brainamon");
        DEFAULTS.put("signedClose", "Signed in to {site}. Close when done.");
        DEFAULTS.put("signCloseOnly", "Sign in to {site}, then close.");
        DEFAULTS.put("unsaveFailed", "Unsave unavailable; keeping remaining posts saved.");
    }

    private SiteText() {}

    /** A label key the page may send: a short plain identifier, so it can never name anything else. */
    static boolean validKey(String key) {
        if (key == null || key.isEmpty() || key.length() > MAX_KEY || !Character.isLetter(key.charAt(0))) return false;
        for (int i = 0; i < key.length(); i++) {
            char c = key.charAt(i);
            if (!(c >= 'a' && c <= 'z') && !(c >= 'A' && c <= 'Z') && !(c >= '0' && c <= '9') && c != '_') return false;
        }
        return true;
    }

    /** A label's text when it may be kept (not empty, within the cap, no control characters), else null. */
    static String clean(String value) {
        if (value == null || value.isEmpty() || value.length() > MAX_LABEL) return null;
        for (int i = 0; i < value.length(); i++) if (Character.isISOControl(value.charAt(i))) return null;
        return value;
    }

    static boolean known(String key) {
        return DEFAULTS.containsKey(key);
    }

    static String label(Map<String, String> labels, String key) {
        String v = labels == null ? null : labels.get(key);
        if (v != null) return v;
        v = DEFAULTS.get(key);
        return v == null ? "" : v;
    }

    /** English and the other languages: one for exactly 1; French: one for 0 and 1; Chinese: never. */
    static boolean one(String lang, long n) {
        String l = lang == null ? "en" : lang.toLowerCase(Locale.ROOT);
        if (l.startsWith("zh")) return false;
        if (l.startsWith("fr")) return n == 0 || n == 1;
        return n == 1;
    }

    /** The label `key` (as key_one / key_other) for the count n, with {name} replaced by n. */
    static String count(Map<String, String> labels, String lang, String key, String name, long n) {
        String text = label(labels, key + (one(lang, n) ? "_one" : "_other"));
        return text.replace("{" + name + "}", String.valueOf(n));
    }

    static String fill(String template, String name, String value) {
        return template.replace("{" + name + "}", value);
    }

    /** Milliseconds between the arrivals of one batch of k: 290 at most, a batch fits in 1.1 s. */
    static long gapMs(int k) {
        return k <= 0 ? MAX_GAP_MS : Math.min(MAX_GAP_MS, GAP_BUDGET_MS / k);
    }

    /**
     * Where a picture the page reported sits in a snapshot of the window: {left, top, width, height} in
     * snapshot pixels, or null. The rectangle is untrusted: finite numbers, a sane viewport width, at least
     * MIN_SIDE pixels on each side after it is cut to the snapshot.
     */
    static int[] crop(double x, double y, double w, double h, double vw, int bw, int bh) {
        if (bw <= 0 || bh <= 0 || !(vw > 0) || vw > 20000 || Double.isInfinite(vw)) return null;
        double[] r = {x, y, w, h};
        for (double v : r) if (Double.isNaN(v) || Double.isInfinite(v) || Math.abs(v) > 1e6) return null;
        double scale = bw / vw;
        double left = Math.max(0, x * scale), top = Math.max(0, y * scale);
        double right = Math.min(bw, (x + w) * scale), bottom = Math.min(bh, (y + h) * scale);
        if (right - left < MIN_SIDE || bottom - top < MIN_SIDE) return null;
        return new int[] {(int) Math.floor(left), (int) Math.floor(top), (int) Math.floor(right - left), (int) Math.floor(bottom - top)};
    }

    /** The first non-empty line of a caption, cut to max characters; the host of the link when there is none. */
    static String headline(String caption, String url, int max) {
        String first = "";
        if (caption != null) {
            for (String line : caption.split("\\r?\\n")) {
                String t = line.trim();
                if (!t.isEmpty()) { first = t; break; }
            }
        }
        if (first.isEmpty() && url != null) {
            int s = url.indexOf("//");
            String rest = s >= 0 ? url.substring(s + 2) : url;
            int e = rest.indexOf('/');
            first = e >= 0 ? rest.substring(0, e) : rest;
        }
        if (first.length() <= max) return first;
        int cut = max - 1;
        if (cut > 0 && Character.isHighSurrogate(first.charAt(cut - 1))) cut--;
        return first.substring(0, Math.max(0, cut)) + "\u2026";
    }
}
