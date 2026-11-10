package app.brainamon.mobile;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.webkit.WebView;
import androidx.webkit.Profile;
import androidx.webkit.ProfileStore;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The Contributor build's SiteBridge (projects/phone-site-reader/plans/01-engine.md); BrainamonPlugin
 * finds it by name. Logins stay in each site's WebView profile ("site-<id>"); this class only keeps
 * whether the login cookie was there ("signed-<id>") and the profiles to delete at the next start.
 * WebView refuses to delete a profile already loaded in the running app, so Forget wipes such a profile's
 * cookies, storage and cache at once and deletes its folder at the next start, before any profile loads.
 */
public final class SiteReader implements SiteBridge {
    static final String PREFS = "brainamon-sites", FORGET = "forget";
    private static volatile Boolean supported;

    public SiteReader() {}

    /** The three WebView features the window needs; without them: "Update Android System WebView". */
    static boolean supported() {
        Boolean s = supported;
        if (s == null) {
            s = WebViewFeature.isFeatureSupported(WebViewFeature.MULTI_PROFILE)
                && WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER)
                && WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT);
            supported = s;
        }
        return s;
    }

    static SharedPreferences prefs(Context ctx) {
        return ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** The page script: the site's file, then the shared runner, in one function. Null when either is missing. */
    static String script(Context ctx, String site) {
        try {
            return "(function () {\n'use strict';\n" + asset(ctx, "sites/" + site + ".js") + "\n"
                + asset(ctx, "sites/_runner.js") + "\n})();\n";
        } catch (IOException e) {
            return null;
        }
    }

    private static String asset(Context ctx, String name) throws IOException {
        try (InputStream in = ctx.getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
            return new String(out.toByteArray(), StandardCharsets.UTF_8);
        }
    }

    private static Set<String> assetNames(Context ctx) {
        try {
            String[] names = ctx.getAssets().list("sites");
            return names == null ? Collections.<String>emptySet() : new HashSet<>(Arrays.asList(names));
        } catch (IOException e) {
            return Collections.emptySet();
        }
    }

    private static Set<String> forgotten(SharedPreferences p) {
        return new HashSet<>(p.getStringSet(FORGET, Collections.<String>emptySet()));
    }

    @Override
    public JSONObject state(Context ctx) throws Exception {
        SharedPreferences p = prefs(ctx);
        Set<String> forget = forgotten(p), assets = assetNames(ctx);
        JSONObject sites = new JSONObject();
        for (SiteConfig s : SiteConfig.ALL) {
            sites.put(s.id, new JSONObject()
                .put("signedIn", p.getBoolean("signed-" + s.id, false))
                .put("pending", new SiteRunFile(ctx, s.id).size())
                .put("forgetting", forget.contains(s.profile()))
                .put("reader", assets.contains(s.id + ".js") && assets.contains("_runner.js")));
        }
        return new JSONObject().put("supported", supported()).put("sites", sites);
    }

    @Override
    public Intent openIntent(Context ctx, String site, JSONArray known, boolean full, boolean complete) throws Exception {
        SiteConfig s = SiteConfig.of(site);
        if (s == null) throw new IllegalArgumentException("site");
        if (!supported()) throw new IllegalStateException("webview");
        if (SiteActivity.open) throw new IllegalStateException("busy");
        new SiteRunFile(ctx, site).writeKnown(known);
        SharedPreferences p = prefs(ctx);
        Set<String> forget = forgotten(p);
        if (forget.remove(s.profile())) p.edit().putStringSet(FORGET, forget).commit();   // in use again: keep its folder
        return new Intent(ctx, SiteActivity.class)
            .putExtra(SiteActivity.EXTRA_SITE, site)
            .putExtra(SiteActivity.EXTRA_FULL, full)
            .putExtra(SiteActivity.EXTRA_COMPLETE, complete);
    }

    @Override
    public JSONObject pending(Context ctx, String site, int offset, int max) throws Exception {
        if (SiteConfig.of(site) == null) throw new IllegalArgumentException("site");
        return new SiteRunFile(ctx, site).page(Math.max(0, offset), Math.max(1, Math.min(max, 2000)));
    }

    @Override
    public void clear(Context ctx, String site) throws Exception {
        if (SiteConfig.of(site) == null) throw new IllegalArgumentException("site");
        new SiteRunFile(ctx, site).clear();
    }

    @Override
    public String forget(Activity activity, String site) throws Exception {
        SiteConfig s = SiteConfig.of(site);
        if (s == null) throw new IllegalArgumentException("site");
        if (SiteActivity.open) throw new IllegalStateException("busy");
        SharedPreferences p = prefs(activity);
        p.edit().putBoolean("signed-" + s.id, false).commit();
        if (!supported()) return "deleted";          // no profiles on this WebView: nothing was ever kept
        ProfileStore store = ProfileStore.getInstance();
        try {
            store.deleteProfile(s.profile());          // false when there was none
            return "deleted";
        } catch (IllegalStateException loaded) {
            // loaded by the window earlier in this run of the app: wipe it now, delete its folder at the next start
            Profile profile = store.getOrCreateProfile(s.profile());
            profile.getCookieManager().removeAllCookies(done -> profile.getCookieManager().flush());
            profile.getWebStorage().deleteAllData();
            WebView w = new WebView(activity);
            WebViewCompat.setProfile(w, s.profile());
            w.clearCache(true);
            w.destroy();
            Set<String> forget = forgotten(p);
            forget.add(s.profile());
            p.edit().putStringSet(FORGET, forget).commit();
            return "cleared";
        }
    }

    @Override
    public void startup(Context ctx) {
        try {
            SharedPreferences p = prefs(ctx);
            Set<String> forget = forgotten(p);
            if (forget.isEmpty() || !supported()) return;
            ProfileStore store = ProfileStore.getInstance();
            for (Iterator<String> it = forget.iterator(); it.hasNext(); ) {
                String name = it.next();
                try {
                    store.deleteProfile(name);
                    it.remove();
                } catch (IllegalArgumentException e) {
                    it.remove();                           // the default profile: never one of ours
                } catch (IllegalStateException e) {
                    // already loaded in this run: the next start deletes it
                }
            }
            p.edit().putStringSet(FORGET, forget).commit();
        } catch (RuntimeException e) {
            // a WebView problem must never stop the app from starting; Forget tries again next time
        }
    }
}
