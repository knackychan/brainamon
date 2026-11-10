package app.brainamon.mobile;

import android.content.Context;
import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * A site run's items on disk until the Import screen takes them (projects/phone-site-reader):
 * <noBackupFilesDir>/site-runs/<site>.jsonl, one item per line, written and synced batch by batch, so a
 * killed app loses at most the batch in flight. <site>.known holds the known-link hashes the page gets.
 * App-private and out of backups. The page's items are reduced here to five fields and the sizes the
 * phone keeps; web/src/mobile/sites.ts checks them again before import.
 */
final class SiteRunFile {
    static final int MAX_ITEMS = 20000, MAX_KNOWN = 50000;
    private static final Pattern HASH = Pattern.compile("[0-9a-f]{16}");
    private static final Object LOCK = new Object();      // the window appends while the plugin may read
    private final File items, known;

    SiteRunFile(Context ctx, String site) {
        File dir = new File(ctx.getNoBackupFilesDir(), "site-runs");
        items = new File(dir, site + ".jsonl");
        known = new File(dir, site + ".known");
    }

    /** One item as the page sent it, reduced to url, kind, caption, creator, pic; null when unusable. */
    static JSONObject shape(Object raw) {
        if (!(raw instanceof JSONObject)) return null;
        JSONObject o = (JSONObject) raw;
        String url = str(o, "url"), kind = str(o, "kind"), pic = str(o, "pic");
        if (!url.startsWith("https://") || url.length() > 500) return null;
        if (!kind.equals("Reel") && !kind.equals("Video") && !kind.equals("Post")) return null;
        if (!pic.startsWith("https://") || pic.length() > 2000) pic = "";
        try {
            return new JSONObject()
                .put("url", url)
                .put("kind", kind)
                .put("caption", cut(str(o, "caption"), 5000))
                .put("creator", cut(str(o, "creator"), 120))
                .put("pic", pic);
        } catch (JSONException e) {
            return null;
        }
    }

    private static String str(JSONObject o, String name) {
        Object v = o.opt(name);
        return v instanceof String ? (String) v : "";
    }

    private static String cut(String s, int max) {
        return s.length() > max ? s.substring(0, max) : s;
    }

    /** The links already in the file (an earlier, unimported run of this site included). */
    Set<String> urls() throws IOException {
        synchronized (LOCK) {
            Set<String> out = new HashSet<>();
            if (!items.isFile()) return out;
            try (BufferedReader in = reader()) {
                for (String line; (line = in.readLine()) != null; ) {
                    if (line.isEmpty()) continue;
                    try { out.add(new JSONObject(line).getString("url")); } catch (JSONException e) { /* a line cut by a crash */ }
                }
            }
            return out;
        }
    }

    int size() {
        synchronized (LOCK) {
            if (!items.isFile()) return 0;
            int n = 0;
            try (BufferedReader in = reader()) {
                for (String line; (line = in.readLine()) != null; ) if (!line.isEmpty()) n++;
            } catch (IOException e) {
                return 0;
            }
            return n;
        }
    }

    void append(List<JSONObject> list) throws IOException {
        synchronized (LOCK) {
            File dir = items.getParentFile();
            if (dir != null && !dir.isDirectory() && !dir.mkdirs()) throw new IOException("site-runs");
            StringBuilder b = new StringBuilder();
            if (items.length() > 0) {
                try (RandomAccessFile f = new RandomAccessFile(items, "r")) {
                    f.seek(f.length() - 1);
                    if (f.read() != '\n') b.append('\n');   // the line a crash cut stays apart
                }
            }
            for (JSONObject o : list) b.append(o.toString()).append('\n');
            try (FileOutputStream out = new FileOutputStream(items, true)) {
                out.write(b.toString().getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
        }
    }

    /** {items: at most max items from offset, total: all the items in the file}. */
    JSONObject page(int offset, int max) throws IOException, JSONException {
        synchronized (LOCK) {
            JSONArray out = new JSONArray();
            int total = 0;
            if (items.isFile()) {
                try (BufferedReader in = reader()) {
                    for (String line; (line = in.readLine()) != null; ) {
                        if (line.isEmpty()) continue;
                        if (total >= offset && total - offset < max) {
                            try { out.put(new JSONObject(line)); } catch (JSONException e) { /* a line cut by a crash */ }
                        }
                        total++;
                    }
                }
            }
            return new JSONObject().put("items", out).put("total", total);
        }
    }

    /** After the import: the items and the known-link hashes go. */
    void clear() throws IOException {
        synchronized (LOCK) {
            if (items.exists() && !items.delete()) throw new IOException("Could not clear saved results.");
            if (known.exists() && !known.delete()) throw new IOException("Could not clear known hashes.");
        }
    }

    void writeKnown(JSONArray hashes) throws IOException {
        JSONArray keep = new JSONArray();
        for (int i = 0; hashes != null && i < hashes.length() && keep.length() < MAX_KNOWN; i++) {
            String h = hashes.optString(i, "");
            if (HASH.matcher(h).matches()) keep.put(h);
        }
        synchronized (LOCK) {
            File dir = known.getParentFile();
            if (dir != null && !dir.isDirectory() && !dir.mkdirs()) throw new IOException("site-runs");
            try (FileOutputStream out = new FileOutputStream(known, false)) {
                out.write(keep.toString().getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
        }
    }

    JSONArray readKnown() {
        synchronized (LOCK) {
            if (!known.isFile()) return new JSONArray();
            try (InputStream in = new FileInputStream(known)) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                for (int n; (n = in.read(buf)) > 0; ) b.write(buf, 0, n);
                return new JSONArray(new String(b.toByteArray(), StandardCharsets.UTF_8));
            } catch (IOException | JSONException e) {
                return new JSONArray();
            }
        }
    }

    private BufferedReader reader() throws IOException {
        return new BufferedReader(new InputStreamReader(new FileInputStream(items), StandardCharsets.UTF_8));
    }
}
