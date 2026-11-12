package app.brainamon.mobile;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import org.json.JSONArray;
import org.json.JSONObject;

/**
 * The phone site reader (projects/phone-site-reader), as BrainamonPlugin sees it. The reader itself
 * (SiteReader, SiteActivity, SiteConfig, SiteRunFile) lives in the main source set for both builds.
 */
public interface SiteBridge {
    /** {supported, sites: {id: {signedIn, pending, forgetting, reader}}}. Any thread. */
    JSONObject state(Context ctx) throws Exception;

    /** The site window's intent; writes the known-link hashes the page will get. Any thread. */
    Intent openIntent(Context ctx, String site, JSONArray known, boolean full, boolean complete) throws Exception;

    /** At most max items of the site's run file from offset: {items, total}. Any thread. */
    JSONObject pending(Context ctx, String site, int offset, int max) throws Exception;

    /** Deletes the run file (after the Import screen took its items). Any thread. */
    void clear(Context ctx, String site) throws Exception;

    /** Wipes the site's login on this phone: "deleted", or "cleared" (its folder goes at the next start). UI thread. */
    String forget(Activity activity, String site) throws Exception;

    /** Deletes the profiles forgotten earlier, before any is loaded. UI thread, from the plugin's load(). */
    void startup(Context ctx);
}
