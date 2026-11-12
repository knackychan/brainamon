package app.brainamon.mobile;

import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.res.TypedArray;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import androidx.activity.EdgeToEdge;
import androidx.activity.OnBackPressedCallback;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.webkit.JavaScriptReplyProxy;
import androidx.webkit.Profile;
import androidx.webkit.ProfileStore;
import androidx.webkit.UserAgentMetadata;
import androidx.webkit.WebMessageCompat;
import androidx.webkit.WebSettingsCompat;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The site window of the phone site reader (projects/phone-site-reader). One site per window,
 * in that site's own WebView profile ("site-<id>":
 * its cookies, storage and cache, apart from the Brainamon page and the other sites), with a desktop
 * Chrome identity (Facebook refuses logins in a WebView's own). The window shows only the site's hosts;
 * other links open in the system browser on a tap. No file access, permissions, downloads, popups or
 * mixed content.
 *
 * When the build has the site's page script (assets/sites/<id>.js and _runner.js), it runs at document
 * start on the site's origins with the "brainamonSite" channel (WebViewCompat.addWebMessageListener, never a
 * Java object exposed to the page). The page's messages are untrusted, since the site's own scripts can post on the
 * same channel: size, type and shape are checked here and again by web/src/mobile/sites.ts. Accepted items
 * go to the run file at once (SiteRunFile). The login cookie is only checked for presence: its value is
 * never kept, logged or sent.
 */
public class SiteActivity extends AppCompatActivity {
    static final String EXTRA_SITE = "site", EXTRA_FULL = "full", EXTRA_COMPLETE = "complete";
    static volatile boolean open = false;

    private static final int MAX_MESSAGE = 256 * 1024, MAX_BATCH = 25, MAX_COUNT = 1000000;
    private static final List<String> PHASES = Arrays.asList("signin", "check", "open", "read", "wait");
    private static final List<String> ENDS = Arrays.asList("end", "known", "empty", "cap", "failure", "unsave-failed", "stop");
    private static final Pattern CHROME = Pattern.compile("Chrome/(\\d+)\\.");
    private static final Pattern MAJOR = Pattern.compile("^(\\d+)\\.");

    private SiteConfig site;
    private Profile profile;
    private WebView web;
    private TextView bar;
    private SiteRunFile run;
    private JSONArray knownHashes = new JSONArray();
    private final Set<String> stored = new HashSet<>();
    private final String runId = Long.toHexString(System.currentTimeMillis()) + Long.toHexString(System.nanoTime());
    private boolean reader, signed, finished, active, unsave, unsaveFailed;
    private String phase = "signin";
    private int added, known, other, dropped;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        open = true;
        site = SiteConfig.of(getIntent().getStringExtra(EXTRA_SITE));
        if (site == null || !SiteReader.supported()) {
            finishWith("unsupported");
            return;
        }
        EdgeToEdge.enable(this);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        String script = SiteReader.script(this, site.id);
        reader = script != null;
        run = new SiteRunFile(this, site.id);
        if (reader) {
            knownHashes = run.readKnown();
            try {
                stored.addAll(run.urls());
            } catch (IOException e) {
                // unreadable: the Import screen reports it when it reads the file
            }
        }
        signed = SiteReader.prefs(this).getBoolean("signed-" + site.id, false);

        // the profile first: WebViewCompat.setProfile must come before anything else is done with the WebView
        profile = ProfileStore.getInstance().getOrCreateProfile(site.profile());
        web = new WebView(this);
        WebViewCompat.setProfile(web, site.profile());

        setContentView(layout());
        settings(web.getSettings());
        if (WebViewFeature.isFeatureSupported(WebViewFeature.MUTE_AUDIO)) WebViewCompat.setAudioMuted(web, true);
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        if (reader) {
            Set<String> origins = new HashSet<>(Arrays.asList(site.origins));
            WebViewCompat.addWebMessageListener(web, "brainamonSite", origins, this::onMessage);
            WebViewCompat.addDocumentStartJavaScript(web, script, origins);
        }
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (web != null && !"read".equals(phase) && web.canGoBack()) web.goBack();
                else finishWith("stop");
            }
        });
        checkSigned();
        showBar();
        if (getIntent().getBooleanExtra("unsave", false) && reader
                && ("facebook".equals(site.id) || "instagram".equals(site.id))) {
            new android.app.AlertDialog.Builder(this)
                .setTitle("Unsave collected posts?")
                .setMessage("Remove collected posts from " + site.name + " Saved after saving their results on this phone? This changes your original account. Review and import the saved results afterward. Posts already in your library are left saved.")
                .setNegativeButton("Cancel", (dialog, which) -> finishWith("stop"))
                .setPositiveButton("Continue", (dialog, which) -> { unsave = true; web.loadUrl(site.start); })
                .setOnCancelListener(dialog -> finishWith("stop"))
                .show();
        } else web.loadUrl(site.start);
    }

    private LinearLayout layout() {
        bar = new TextView(this);
        bar.setTextColor(themeColor(android.R.attr.textColorPrimary, Color.BLACK));
        bar.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        bar.setMaxLines(2);
        bar.setPadding(dp(12), dp(8), dp(8), dp(8));
        Button stop = new Button(this);
        stop.setText(reader ? "Cancel scan" : "Close");
        stop.setOnClickListener(v -> finishWith("stop"));
        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.addView(bar, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        top.addView(stop, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(themeColor(android.R.attr.colorBackground, Color.WHITE));
        root.addView(top, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        root.addView(web, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        // edge to edge (forced from Android 15): the bar and the page stay clear of the system bars,
        // the camera cutout and the keyboard
        ViewCompat.setOnApplyWindowInsetsListener(root, (v, insets) -> {
            Insets i = insets.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout()
                | WindowInsetsCompat.Type.ime());
            v.setPadding(i.left, i.top, i.right, i.bottom);
            return WindowInsetsCompat.CONSUMED;
        });
        return root;
    }

    @SuppressLint("SetJavaScriptEnabled")
    private void settings(WebSettings ws) {
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setSupportMultipleWindows(false);
        ws.setJavaScriptCanOpenWindowsAutomatically(false);
        ws.setGeolocationEnabled(false);
        ws.setMediaPlaybackRequiresUserGesture(true);
        ws.setUseWideViewPort(true);
        ws.setLoadWithOverviewMode(true);
        ws.setSupportZoom(true);
        ws.setBuiltInZoomControls(true);
        ws.setDisplayZoomControls(false);
        // a desktop Chrome of the WebView's own version: no "wv", "Version/4.0" or "Mobile"
        String major = chromeMajor(ws.getUserAgentString());
        ws.setUserAgentString("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/"
            + major + ".0.0.0 Safari/537.36");
        // the client hints must say the same, or they would still say Android WebView
        if (WebViewFeature.isFeatureSupported(WebViewFeature.USER_AGENT_METADATA)) {
            try {
                WebSettingsCompat.setUserAgentMetadata(ws, desktopHints(major));
            } catch (RuntimeException e) {
                // the User-Agent alone; the spike records whether a site minds (S1)
            }
        }
    }

    private String chromeMajor(String defaultAgent) {
        Matcher m = CHROME.matcher(defaultAgent == null ? "" : defaultAgent);
        if (m.find()) return m.group(1);
        PackageInfo p = WebViewCompat.getCurrentWebViewPackage(this);
        Matcher v = MAJOR.matcher(p != null && p.versionName != null ? p.versionName : "");
        return v.find() ? v.group(1) : "140";
    }

    private static UserAgentMetadata desktopHints(String major) {
        String full = major + ".0.0.0";
        List<UserAgentMetadata.BrandVersion> brands = Arrays.asList(
            brand("Google Chrome", major, full), brand("Chromium", major, full), brand("Not_A Brand", "24", "24.0.0.0"));
        return new UserAgentMetadata.Builder()
            .setBrandVersionList(brands)
            .setFullVersion(full)
            .setPlatform("Windows")
            .setPlatformVersion("15.0.0")
            .setArchitecture("x86")
            .setModel("")
            .setMobile(false)
            .setBitness(64)
            .setWow64(false)
            .build();
    }

    private static UserAgentMetadata.BrandVersion brand(String name, String major, String full) {
        return new UserAgentMetadata.BrandVersion.Builder().setBrand(name).setMajorVersion(major).setFullVersion(full).build();
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (!request.isForMainFrame()) return false;
            Uri u = request.getUrl();
            String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(Locale.ROOT);
            boolean ours = site.allows(u.getHost());
            if (ours && scheme.equals("https")) return false;
            if (ours && scheme.equals("http")) {
                view.loadUrl(u.buildUpon().scheme("https").build().toString());
                return true;
            }
            if ((scheme.equals("https") || scheme.equals("http")) && request.hasGesture()) {
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u).addCategory(Intent.CATEGORY_BROWSABLE));
                } catch (ActivityNotFoundException e) {
                    // no browser: the page stays
                }
            }
            return true;
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            checkSigned();
        }

        @Override
        public void doUpdateVisitedHistory(WebView view, String url, boolean isReload) {
            checkSigned();
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            // the page's renderer died: this WebView cannot be used again (what was read is in the run file)
            ViewGroup parent = (ViewGroup) view.getParent();
            if (parent != null) parent.removeView(view);
            view.destroy();
            web = null;
            finishWith("failure");
            return true;
        }
    }

    private static class Chrome extends WebChromeClient {
        @Override
        public void onPermissionRequest(PermissionRequest request) {
            request.deny();
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            callback.invoke(origin, false, false);
        }
    }

    // whether the site's login cookie is there (its value is never kept); remembered for the Import screen
    private boolean checkSigned() {
        boolean on = false;
        String cookies = profile == null ? null : profile.getCookieManager().getCookie(site.cookieUrl);
        if (cookies != null) {
            for (String part : cookies.split(";")) {
                int eq = part.indexOf('=');
                if (eq > 0 && part.substring(0, eq).trim().equals(site.cookieName) && !part.substring(eq + 1).trim().isEmpty()) on = true;
            }
        }
        if (on != SiteReader.prefs(this).getBoolean("signed-" + site.id, false)) {
            SiteReader.prefs(this).edit().putBoolean("signed-" + site.id, on).apply();
        }
        if (on != signed) {
            signed = on;
            showBar();
        }
        return on;
    }

    private void showBar() {
        if (bar == null) return;
        String n = site.name, text;
        if (!reader) text = signed ? "Signed in to " + n + ". Close when done." : "Sign in to " + n + ", then close.";
        else if ("check".equals(phase)) text = "Finish the check on the page. Reading goes on by itself.";
        else if ("open".equals(phase)) text = n + ": opening your saved list";
        else if ("read".equals(phase)) text = n + ": " + added + " new, " + known + " already there";
        else if ("wait".equals(phase)) text = n + ": paused (offline or in the background)";
        else text = "Sign in to " + n + ". Reading starts by itself.";
        if (unsaveFailed) text += ". Unsave unavailable; keeping remaining posts saved.";
        bar.setText(text);
    }

    // the page's messages (scrapers/sites/_runner.js): hello -> init, ping -> signed, status, batch, end
    private void onMessage(WebView view, WebMessageCompat message, Uri origin, boolean isMainFrame, JavaScriptReplyProxy reply) {
        if (finished) return;
        String data = isMainFrame && message.getType() == WebMessageCompat.TYPE_STRING ? message.getData() : null;
        if (data == null || data.length() > MAX_MESSAGE) {
            dropped++;
            return;
        }
        try {
            JSONObject m = new JSONObject(data);
            switch (m.optString("t")) {
                case "hello":
                    reply.postMessage(new JSONObject().put("t", "init").put("run", runId).put("known", knownHashes)
                        .put("unsave", unsave && !unsaveFailed).put("unsaveFailed", unsaveFailed)
                        .put("full", getIntent().getBooleanExtra(EXTRA_FULL, false))
                        .put("complete", getIntent().getBooleanExtra(EXTRA_COMPLETE, false))
                        .put("signed", checkSigned()).put("active", active).toString());
                    break;
                case "ping":
                    reply.postMessage(new JSONObject().put("t", "signed").put("on", checkSigned()).put("active", active).toString());
                    break;
                case "status":
                    status(m);
                    break;
                case "batch":
                    JSONArray items = m.optJSONArray("items");
                    batch(items);
                    JSONArray saved = new JSONArray();
                    if (!finished && items != null && items.length() <= MAX_BATCH) {
                        for (int i = 0; i < items.length(); i++) {
                            JSONObject item = SiteRunFile.shape(items.opt(i));
                            if (item != null && stored.contains(item.optString("url"))) saved.put(item.optString("url"));
                        }
                    }
                    reply.postMessage(new JSONObject().put("t", "stored").put("batch", m.optInt("batch", -1))
                        .put("urls", saved).toString());
                    break;
                case "end":
                    if (ENDS.contains(m.optString("reason"))) finishWith(m.optString("reason"));
                    else dropped++;
                    break;
                default:
                    dropped++;
            }
        } catch (JSONException e) {
            dropped++;
        }
    }

    private void status(JSONObject m) {
        String p = m.optString("phase");
        if (!PHASES.contains(p)) {
            dropped++;
            return;
        }
        phase = p;
        unsaveFailed = unsaveFailed || m.optBoolean("unsaveFailed", false);
        known = Math.max(0, Math.min(m.optInt("known", known), MAX_COUNT));
        other = Math.max(0, Math.min(m.optInt("other", other), MAX_COUNT));
        showBar();
    }

    private void batch(JSONArray items) {
        if (items == null || items.length() > MAX_BATCH) {
            dropped++;
            return;
        }
        List<JSONObject> keep = new ArrayList<>();
        for (int i = 0; i < items.length(); i++) {
            JSONObject o = SiteRunFile.shape(items.opt(i));
            if (o == null || stored.size() >= SiteRunFile.MAX_ITEMS) {
                dropped++;
                continue;
            }
            if (stored.add(o.optString("url"))) keep.add(o);
        }
        if (keep.isEmpty()) return;
        try {
            run.append(keep);
            added += keep.size();
        } catch (IOException e) {
            for (JSONObject o : keep) stored.remove(o.optString("url"));
            dropped += keep.size();
            finishWith("failure");
        }
        showBar();
    }

    private void finishWith(String reason) {
        if (finished) return;
        finished = true;
        setResult(RESULT_OK, new Intent().putExtra("reason", reason).putExtra("added", added).putExtra("known", known)
            .putExtra("other", other).putExtra("dropped", dropped).putExtra("unsaveFailed", unsaveFailed));
        finish();
    }

    private int themeColor(int attr, int fallback) {
        TypedArray a = obtainStyledAttributes(new int[] {attr});
        try {
            return a.getColor(0, fallback);
        } finally {
            a.recycle();
        }
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    @Override
    protected void onPause() {
        active = false;
        super.onPause();
        if (web != null) web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        active = true;
        if (web != null) web.onResume();
    }

    @Override
    protected void onDestroy() {
        open = false;
        if (web != null) {
            ViewGroup parent = (ViewGroup) web.getParent();
            if (parent != null) parent.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
