package app.brainamon.mobile;

import android.animation.Animator;
import android.animation.AnimatorListenerAdapter;
import android.animation.ValueAnimator;
import android.app.Activity;
import android.content.res.Configuration;
import android.graphics.Bitmap;
import android.graphics.Outline;
import android.graphics.Rect;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.PixelCopy;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.view.animation.AccelerateDecelerateInterpolator;
import android.view.animation.DecelerateInterpolator;
import android.view.animation.LinearInterpolator;
import android.view.animation.OvershootInterpolator;
import android.webkit.WebView;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

/**
 * The tray of the site window (projects/motion-language plan 06; spec section 3): a card at the bottom that
 * shows what the reader does while the WebView above it keeps its size. It starts as a 78 dp strip (the sign-in
 * message), grows to 176 dp when reading starts (the count of new posts, how many are already in the library, a
 * busy bar and a window where the newest post slides up), and ends with the finish (a green tick, the count and
 * one button). A picture the page reports is copied out of one snapshot of the window and flies from where it
 * was read to the row (at most three at a time), the count ticking at each arrival. Without motion (the page's
 * flag, or Android's animations set to off) there is no ghost, no sweep and no slide: numbers snap.
 * Words come from the page (intent extra "labels", the phone's language), with English fallbacks in SiteText.
 * Everything the page reports is untrusted: SiteText checks labels and rectangles.
 */
final class SiteTray {
    private static final int COLLAPSED_DP = 78, EXPANDED_DP = 176, ROW_DP = 42, THUMB_DP = 32;
    private static final int GROW_MS = 450, SLIDE_MS = 320, FLY_MS = 420, POP_MS = 250, LIFT_MS = 220, BUSY_MS = 1180;
    private static final int SIGN = 0, READ = 1, DONE = 2;
    private static final int ACCENT = 0xFFFF5A1F, OK = 0xFF2BD17E;

    private static final class Arrival {
        String title = "", creator = "";
        Bitmap thumb;
        int sx, sy, sw, sh;
        long gap = SiteText.MAX_GAP_MS;
    }

    private final Activity act;
    private final WebView web;
    private final boolean reader, motion;
    private final String siteName, lang;
    private final Map<String, String> labels = new HashMap<>();
    private final Runnable onCancel;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ArrayDeque<Arrival> queue = new ArrayDeque<>();
    private final List<Animator> live = new ArrayList<>();
    private final int paper, ink, dim, line, okInk;

    private final LinearLayout view;
    private final FrameLayout ghosts, body, rowWindow, barTrack;
    private final View barFill;
    private final TextView signText, titleView, countView, newView, knownView, cancelView;
    private final LinearLayout readBox, doneBox;
    private final TextView circle, doneCount, doneLabel, doneSub, button;

    private int mode = SIGN, shown, added, known, flights, snapshots;
    private boolean ended, pumping, busy, destroyed;
    private String endReason = "", lastPhase = "signin";
    private boolean signed, unsaveFailed;
    private Runnable go;
    private View current;
    private ValueAnimator barAnim;

    SiteTray(Activity act, WebView web, FrameLayout host, String siteName, boolean reader, String labelsJson,
             boolean motionRequested, Runnable onCancel) {
        this.act = act;
        this.web = web;
        this.reader = reader;
        this.siteName = siteName;
        this.onCancel = onCancel;
        parse(labelsJson);
        String l = labels.get("lang");
        this.lang = l == null ? "en" : l;
        float scale = 1f;
        try {
            scale = Settings.Global.getFloat(act.getContentResolver(), Settings.Global.ANIMATOR_DURATION_SCALE, 1f);
        } catch (RuntimeException e) {
            // unreadable: motion stays as the page asked
        }
        this.motion = motionRequested && scale > 0f;
        boolean night = (act.getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES;
        paper = night ? 0xFF1D1F24 : 0xFFFBFAF6;
        ink = night ? 0xFFECECE6 : 0xFF17181B;
        dim = night ? 0xFF8B8F95 : 0xFF6B6D70;
        line = night ? 0xFF33363D : 0xFFE4E1D8;
        okInk = night ? 0xFF3CC98A : 0xFF12804A;

        view = new LinearLayout(act);
        view.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(paper);
        bg.setStroke(dp(1), line);
        float r = dp(16);
        bg.setCornerRadii(new float[] {r, r, r, r, 0, 0, 0, 0});
        view.setBackground(bg);
        view.setElevation(dp(12));
        view.setClickable(true);

        LinearLayout header = new LinearLayout(act);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        header.setPadding(dp(14), 0, dp(6), 0);
        ImageView logo = new ImageView(act);
        logo.setImageDrawable(act.getPackageManager().getApplicationIcon(act.getApplicationInfo()));
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        header.addView(logo, new LinearLayout.LayoutParams(dp(22), dp(22)));
        TextView brand = text(15, ink, true);
        brand.setText("Brainamon");
        brand.setPadding(dp(8), 0, 0, 0);
        header.addView(brand, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        cancelView = text(14, accent(), true);
        cancelView.setText(SiteText.label(labels, reader ? "cancel" : "close"));
        cancelView.setPadding(dp(12), dp(8), dp(12), dp(8));
        cancelView.setMinHeight(dp(40));
        cancelView.setGravity(Gravity.CENTER);
        cancelView.setOnClickListener(v -> onCancel.run());
        header.addView(cancelView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, dp(40)));
        view.addView(header, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)));

        body = new FrameLayout(act);
        body.setPadding(dp(16), 0, dp(16), dp(8));
        body.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE);
        view.addView(body, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        signText = text(13, dim, false);
        signText.setMaxLines(3);
        signText.setEllipsize(TextUtils.TruncateAt.END);
        body.addView(signText, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        readBox = new LinearLayout(act);
        readBox.setOrientation(LinearLayout.VERTICAL);
        titleView = text(12, dim, false);
        titleView.setSingleLine(true);
        titleView.setEllipsize(TextUtils.TruncateAt.END);
        readBox.addView(titleView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(18)));
        LinearLayout counts = new LinearLayout(act);
        counts.setOrientation(LinearLayout.HORIZONTAL);
        counts.setGravity(Gravity.BOTTOM);
        countView = text(28, ink, true);
        countView.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        countView.setText("0");
        counts.addView(countView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        newView = text(14, ink, false);
        newView.setText(SiteText.count(labels, lang, "newWord", "n", 0));
        newView.setPadding(dp(6), 0, 0, dp(4));
        counts.addView(newView, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        knownView = text(12, dim, false);
        knownView.setSingleLine(true);
        knownView.setEllipsize(TextUtils.TruncateAt.END);
        knownView.setPadding(dp(6), 0, 0, dp(4));
        counts.addView(knownView, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        readBox.addView(counts, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(38)));
        barTrack = new FrameLayout(act);
        GradientDrawable track = new GradientDrawable();
        track.setColor(line);
        track.setCornerRadius(dp(2));
        barTrack.setBackground(track);
        barTrack.setClipChildren(true);
        barFill = new View(act);
        GradientDrawable fill = new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, new int[] {0x00FF5A1F, ACCENT, 0x00FF5A1F});
        fill.setCornerRadius(dp(2));
        barFill.setBackground(fill);
        barTrack.addView(barFill, new FrameLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT));
        LinearLayout.LayoutParams tp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(4));
        tp.topMargin = dp(6);
        tp.bottomMargin = dp(8);
        readBox.addView(barTrack, tp);
        rowWindow = new FrameLayout(act);
        rowWindow.setClipChildren(true);
        readBox.addView(rowWindow, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(ROW_DP)));
        readBox.setVisibility(View.GONE);
        body.addView(readBox, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        doneBox = new LinearLayout(act);
        doneBox.setOrientation(LinearLayout.VERTICAL);
        LinearLayout top = new LinearLayout(act);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        circle = text(20, 0xFFFFFFFF, true);
        circle.setGravity(Gravity.CENTER);
        top.addView(circle, new LinearLayout.LayoutParams(dp(36), dp(36)));
        doneCount = text(30, okInk, true);
        doneCount.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        doneCount.setPadding(dp(10), 0, 0, 0);
        top.addView(doneCount, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        doneLabel = text(14, ink, false);
        doneLabel.setPadding(dp(6), dp(6), 0, 0);
        top.addView(doneLabel, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        doneBox.addView(top, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)));
        doneSub = text(12, dim, false);
        doneSub.setMaxLines(3);
        doneSub.setEllipsize(TextUtils.TruncateAt.END);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        sp.topMargin = dp(2);
        doneBox.addView(doneSub, sp);
        View spacer = new View(act);
        doneBox.addView(spacer, new LinearLayout.LayoutParams(1, 0, 1f));
        button = text(15, 0xFFFFFFFF, true);
        button.setGravity(Gravity.CENTER);
        GradientDrawable pill = new GradientDrawable();
        pill.setColor(ACCENT);
        pill.setCornerRadius(dp(20));
        button.setBackground(pill);
        button.setClickable(true);
        button.setOnClickListener(v -> press());
        doneBox.addView(button, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(40)));
        doneBox.setVisibility(View.GONE);
        body.addView(doneBox, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        host.addView(view, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(COLLAPSED_DP), Gravity.BOTTOM));
        ghosts = new FrameLayout(act);
        ghosts.setClipChildren(false);
        host.addView(ghosts, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        phase("signin", false, false);
    }

    /** The WebView keeps this much room under it: the tray covers the rest of the page while it is grown. */
    static int collapsedDp() {
        return COLLAPSED_DP;
    }

    boolean ended() {
        return ended;
    }

    /** The finish button (also the Back button once the finish shows). */
    void press() {
        Runnable r = go;
        go = null;
        if (r != null) r.run();
    }

    // ---- what the page says ----

    void phase(String phase, boolean signedIn, boolean unsaveFailedNow) {
        lastPhase = phase;
        signed = signedIn;
        unsaveFailed = unsaveFailedNow;
        if (mode == DONE || destroyed) return;
        if (!reader) {
            sign(SiteText.fill(SiteText.label(labels, signedIn ? "signedClose" : "signCloseOnly"), "site", siteName));
            return;
        }
        if (mode == READ || "read".equals(phase)) {
            enterRead();
            String t = "wait".equals(phase) ? SiteText.label(labels, "wait")
                : "check".equals(phase) ? SiteText.label(labels, "check")
                : "open".equals(phase) ? SiteText.label(labels, "signedIn")
                : "signin".equals(phase) ? SiteText.fill(SiteText.label(labels, "signIn"), "site", siteName)
                : unsaveFailed ? SiteText.label(labels, "unsaveFailed") : SiteText.label(labels, "reading");
            titleView.setText(t);
            busy("read".equals(phase));
            return;
        }
        if ("check".equals(phase)) sign(SiteText.label(labels, "check"));
        else if ("wait".equals(phase)) sign(SiteText.label(labels, "wait"));
        else if ("open".equals(phase) || signedIn) sign(SiteText.label(labels, "signedIn"));
        else sign(SiteText.fill(SiteText.label(labels, "signIn"), "site", siteName));
    }

    void counts(int addedNow, int knownNow) {
        added = addedNow;
        known = knownNow;
        knownView.setText(known > 0 ? "\u00b7 " + SiteText.count(labels, lang, "known", "k", known) : "");
    }

    /** One accepted batch: `kept` are the new posts, `from` their places in the page's list (which `rects` follows). */
    void batch(List<JSONObject> kept, List<Integer> from, JSONArray rects, double vw) {
        if (ended || destroyed || kept.isEmpty()) return;
        enterRead();
        List<Arrival> list = new ArrayList<>();
        long gap = SiteText.gapMs(kept.size());
        for (JSONObject o : kept) {
            Arrival a = new Arrival();
            a.title = SiteText.headline(o.optString("caption"), o.optString("url"), 80);
            a.creator = SiteText.headline(o.optString("creator"), "", 40);
            a.gap = gap;
            list.add(a);
        }
        if (motion && Build.VERSION.SDK_INT >= 26 && rects != null && vw > 0 && web != null
                && web.getWidth() > 0 && web.getHeight() > 0 && web.isShown()) snapshot(list, from, rects, vw);
        else enqueue(list);
    }

    /** A natural end (end, known, cap, empty): shows the finish once every arrival has landed. */
    void end(String reason, int addedNow, int knownNow, Runnable action) {
        if (ended || destroyed) return;
        ended = true;
        endReason = reason;
        added = addedNow;
        known = knownNow;
        go = action;
        checkDone();
    }

    void destroy() {
        destroyed = true;
        main.removeCallbacksAndMessages(null);
        for (Animator a : new ArrayList<>(live)) a.cancel();
        live.clear();
        for (Arrival a : queue) if (a.thumb != null) a.thumb.recycle();
        queue.clear();
        ghosts.removeAllViews();
    }

    // ---- the picture snapshot ----

    private void snapshot(List<Arrival> list, List<Integer> from, JSONArray rects, double vw) {
        int w = web.getWidth(), h = web.getHeight();
        Bitmap shot;
        try {
            shot = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        } catch (OutOfMemoryError | RuntimeException e) {
            enqueue(list);
            return;
        }
        int[] loc = new int[2];
        web.getLocationInWindow(loc);
        snapshots++;
        try {
            PixelCopy.request(act.getWindow(), new Rect(loc[0], loc[1], loc[0] + w, loc[1] + h), shot, result -> {
                snapshots--;
                if (result == PixelCopy.SUCCESS && !destroyed) crops(list, from, rects, vw, shot, loc);
                shot.recycle();
                if (destroyed) return;
                enqueue(list);
            }, main);
        } catch (IllegalArgumentException e) {
            snapshots--;
            shot.recycle();
            enqueue(list);
        }
    }

    private void crops(List<Arrival> list, List<Integer> from, JSONArray rects, double vw, Bitmap shot, int[] loc) {
        for (int i = 0; i < list.size() && i < from.size(); i++) {
            JSONArray r = rects.optJSONArray(from.get(i));
            if (r == null || r.length() != 4) continue;
            int[] c = SiteText.crop(r.optDouble(0, Double.NaN), r.optDouble(1, Double.NaN), r.optDouble(2, Double.NaN),
                r.optDouble(3, Double.NaN), vw, shot.getWidth(), shot.getHeight());
            if (c == null) continue;
            try {
                int side = Math.min(c[2], c[3]);
                Bitmap square = Bitmap.createBitmap(shot, c[0] + (c[2] - side) / 2, c[1] + (c[3] - side) / 2, side, side);
                Bitmap small = Bitmap.createScaledBitmap(square, dp(THUMB_DP) * 2, dp(THUMB_DP) * 2, true);
                if (small != square) square.recycle();
                Arrival a = list.get(i);
                a.thumb = small;
                a.sx = loc[0] + c[0];
                a.sy = loc[1] + c[1];
                a.sw = c[2];
                a.sh = c[3];
            } catch (RuntimeException | OutOfMemoryError e) {
                // no ghost for this one: the row still arrives
            }
        }
    }

    // ---- arrivals ----

    private void enqueue(List<Arrival> list) {
        if (destroyed) return;
        if (!motion) {
            for (Arrival a : list) {
                shown++;
                showRow(a);
            }
            show(shown);
            checkDone();
            return;
        }
        queue.addAll(list);
        if (!pumping) {
            pumping = true;
            main.post(pump);
        }
        checkDone();
    }

    private final Runnable pump = new Runnable() {
        @Override
        public void run() {
            if (destroyed) return;
            Arrival a = queue.poll();
            if (a == null) {
                pumping = false;
                checkDone();
                return;
            }
            if (a.thumb != null && flights < SiteText.MAX_FLIGHTS && mode == READ && rowWindow.isShown()) fly(a);
            else land(a);
            main.postDelayed(this, a.gap);
        }
    };

    private void fly(Arrival a) {
        flights++;
        ImageView g = new ImageView(act);
        g.setImageBitmap(a.thumb);
        g.setScaleType(ImageView.ScaleType.CENTER_CROP);
        round(g, 6);
        int size = dp(THUMB_DP);
        ghosts.addView(g, new FrameLayout.LayoutParams(size, size));
        int[] gl = new int[2], rl = new int[2];
        ghosts.getLocationInWindow(gl);
        rowWindow.getLocationInWindow(rl);
        float x0 = a.sx + a.sw / 2f - size / 2f - gl[0], y0 = a.sy + a.sh / 2f - size / 2f - gl[1];
        float x1 = rl[0] - gl[0], y1 = rl[1] - gl[1] + dp((ROW_DP - THUMB_DP) / 2);
        float arc = dp(26);
        ValueAnimator v = ValueAnimator.ofFloat(0f, 1f);
        v.setDuration(FLY_MS);
        v.setInterpolator(new AccelerateDecelerateInterpolator());
        v.addUpdateListener(an -> {
            float t = (float) an.getAnimatedValue();
            g.setTranslationX(x0 + (x1 - x0) * t);
            g.setTranslationY(y0 + (y1 - y0) * t - arc * (float) Math.sin(Math.PI * t));
        });
        v.addListener(new AnimatorListenerAdapter() {
            private boolean done;

            @Override
            public void onAnimationEnd(Animator animation) {
                finish(animation);
            }

            @Override
            public void onAnimationCancel(Animator animation) {
                finish(animation);
            }

            private void finish(Animator animation) {
                if (done) return;
                done = true;
                live.remove(animation);
                ghosts.removeView(g);
                flights--;
                if (!destroyed) {
                    land(a);
                    checkDone();
                }
            }
        });
        live.add(v);
        v.start();
    }

    private void land(Arrival a) {
        shown++;
        show(shown);
        lift();
        showRow(a);
    }

    private void show(int n) {
        shown = n;
        countView.setText(String.valueOf(n));
        newView.setText(SiteText.count(labels, lang, "newWord", "n", n));
    }

    private void lift() {
        if (!motion) return;
        countView.setTranslationY(-dp(3));
        countView.animate().translationY(0f).setDuration(LIFT_MS).setInterpolator(new LinearInterpolator()).start();
    }

    private void showRow(Arrival a) {
        View row = makeRow(a);
        View old = current;
        current = row;
        if (!motion || old == null) {
            rowWindow.removeAllViews();
            rowWindow.addView(row);
            return;
        }
        rowWindow.addView(row);
        row.setTranslationY(dp(ROW_DP));
        row.animate().translationY(0f).setDuration(SLIDE_MS).setInterpolator(new DecelerateInterpolator(1.6f)).start();
        old.animate().translationY(-dp(ROW_DP)).alpha(0f).setDuration(SLIDE_MS).setInterpolator(new DecelerateInterpolator(1.6f))
            .withEndAction(() -> rowWindow.removeView(old)).start();
    }

    private View makeRow(Arrival a) {
        LinearLayout row = new LinearLayout(act);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        ImageView thumb = new ImageView(act);
        thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
        if (a.thumb != null) thumb.setImageBitmap(a.thumb);
        else {
            GradientDrawable ph = new GradientDrawable();
            ph.setColor(line);
            thumb.setImageDrawable(ph);
        }
        round(thumb, 6);
        row.addView(thumb, new LinearLayout.LayoutParams(dp(THUMB_DP), dp(THUMB_DP)));
        LinearLayout col = new LinearLayout(act);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setPadding(dp(10), 0, 0, 0);
        TextView title = text(13, ink, false);
        title.setSingleLine(true);
        title.setEllipsize(TextUtils.TruncateAt.END);
        title.setText(a.title);
        col.addView(title, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        if (!a.creator.isEmpty()) {
            TextView by = text(11, dim, false);
            by.setSingleLine(true);
            by.setEllipsize(TextUtils.TruncateAt.END);
            by.setText(a.creator);
            col.addView(by, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        row.addView(col, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        row.setLayoutParams(new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(ROW_DP)));
        return row;
    }

    // ---- modes ----

    private void sign(String message) {
        signText.setText(message);
    }

    private void enterRead() {
        if (mode != SIGN) return;
        mode = READ;
        signText.setVisibility(View.GONE);
        readBox.setVisibility(View.VISIBLE);
        show(shown);
        grow(EXPANDED_DP);
    }

    private void checkDone() {
        if (!ended || mode == DONE || destroyed) return;
        if (!queue.isEmpty() || pumping || flights > 0 || snapshots > 0) return;
        showDone();
    }

    private void showDone() {
        mode = DONE;
        busy(false);
        boolean empty = "empty".equals(endReason);
        readBox.setVisibility(View.GONE);
        signText.setVisibility(View.GONE);
        doneBox.setVisibility(View.VISIBLE);
        cancelView.setVisibility(View.INVISIBLE);
        int n = empty ? 0 : added;
        GradientDrawable dot = new GradientDrawable();
        dot.setShape(GradientDrawable.OVAL);
        dot.setColor(empty ? dim : OK);
        circle.setBackground(dot);
        circle.setText(empty ? "!" : "\u2713");
        doneCount.setText(String.valueOf(n));
        doneCount.setTextColor(empty ? dim : okInk);
        doneLabel.setText(empty ? "" : SiteText.count(labels, lang, "doneNew", "n", n));
        String why = SiteText.label(labels, "end".equals(endReason) ? "doneEnd" : "known".equals(endReason) ? "doneKnown"
            : "cap".equals(endReason) ? "doneCap" : "doneEmpty");
        doneSub.setText(known > 0 ? why + " \u00b7 " + SiteText.count(labels, lang, "known", "k", known) : why);
        button.setText(SiteText.label(labels, n > 0 ? "review" : "back"));
        grow(EXPANDED_DP);
        if (motion) {
            circle.setScaleX(0.5f);
            circle.setScaleY(0.5f);
            circle.setAlpha(0f);
            circle.animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(POP_MS).setInterpolator(new OvershootInterpolator(2f)).start();
            button.animate().setStartDelay(500).scaleX(1.05f).scaleY(1.05f).setDuration(POP_MS).setInterpolator(new DecelerateInterpolator())
                .withEndAction(() -> button.animate().setStartDelay(0).scaleX(1f).scaleY(1f).setDuration(POP_MS).start()).start();
        }
    }

    private void busy(boolean on) {
        if (on == busy) return;
        busy = on;
        if (barAnim != null) {
            barAnim.cancel();
            live.remove(barAnim);
            barAnim = null;
        }
        if (!on) {
            barFill.setVisibility(View.INVISIBLE);
            return;
        }
        barFill.setVisibility(View.VISIBLE);
        if (!motion) {
            sizeFill(1f);
            barFill.setTranslationX(0f);
            barFill.setAlpha(0.3f);
            return;
        }
        barFill.setAlpha(1f);
        barAnim = ValueAnimator.ofFloat(0f, 1f);
        barAnim.setDuration(BUSY_MS);
        barAnim.setInterpolator(new LinearInterpolator());
        barAnim.setRepeatCount(ValueAnimator.INFINITE);
        barAnim.addUpdateListener(an -> {
            int w = barTrack.getWidth();
            if (w <= 0) return;
            sizeFill(0.4f);
            float t = (float) an.getAnimatedValue();
            barFill.setTranslationX(-0.4f * w + t * 1.4f * w);
        });
        live.add(barAnim);
        barAnim.start();
    }

    private void sizeFill(float part) {
        int w = Math.max(0, Math.round(barTrack.getWidth() * part));
        ViewGroup.LayoutParams lp = barFill.getLayoutParams();
        if (lp.width != w) {
            lp.width = w;
            barFill.setLayoutParams(lp);
        }
    }

    private void grow(int toDp) {
        int to = dp(toDp), from = view.getLayoutParams().height;
        if (from == to) return;
        if (!motion) {
            setHeight(to);
            return;
        }
        ValueAnimator v = ValueAnimator.ofInt(from, to);
        v.setDuration(GROW_MS);
        v.setInterpolator(new DecelerateInterpolator(1.6f));
        v.addUpdateListener(an -> setHeight((Integer) an.getAnimatedValue()));
        v.addListener(new AnimatorListenerAdapter() {
            @Override
            public void onAnimationEnd(Animator animation) {
                live.remove(animation);
            }
        });
        live.add(v);
        v.start();
    }

    private void setHeight(int px) {
        ViewGroup.LayoutParams lp = view.getLayoutParams();
        lp.height = px;
        view.setLayoutParams(lp);
    }

    // ---- small helpers ----

    private void parse(String json) {
        if (json == null || json.isEmpty() || json.length() > SiteText.MAX_LABELS_BYTES) return;
        try {
            JSONObject o = new JSONObject(json);
            java.util.Iterator<String> keys = o.keys();
            int n = 0;
            while (keys.hasNext() && n < SiteText.MAX_ENTRIES) {
                String k = keys.next();
                n++;
                if (!SiteText.validKey(k)) continue;
                Object v = o.opt(k);
                String text = v instanceof String ? SiteText.clean((String) v) : null;
                if (text != null) labels.put(k, text);
            }
        } catch (JSONException e) {
            labels.clear();
        }
    }

    private int accent() {
        return ACCENT;
    }

    private TextView text(int sp, int color, boolean bold) {
        TextView t = new TextView(act);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        t.setIncludeFontPadding(false);
        if (bold) t.setTypeface(t.getTypeface(), Typeface.BOLD);
        return t;
    }

    private void round(View v, int radiusDp) {
        final float radius = dp(radiusDp);
        v.setClipToOutline(true);
        v.setOutlineProvider(new ViewOutlineProvider() {
            @Override
            public void getOutline(View view, Outline outline) {
                outline.setRoundRect(0, 0, view.getWidth(), view.getHeight(), radius);
            }
        });
    }

    private int dp(int v) {
        return Math.round(v * act.getResources().getDisplayMetrics().density);
    }
}
