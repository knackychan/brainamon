package app.brainamon.mobile;

import java.util.Locale;

/**
 * One site the phone site reader knows (projects/phone-site-reader): its start page, the login cookie
 * that says "signed in" (only its presence is ever checked), the hosts the window may show (the site's
 * own pages, its login and checkpoint pages), and the origins that get the page script and the
 * brainamonSite channel. Cookie names and hosts are the spike's S1 and S2 checks (PLAN.md).
 */
final class SiteConfig {
    final String id, name, start, cookieUrl, cookieName;
    final String[] hosts, origins;

    private SiteConfig(String id, String name, String start, String cookieName, String[] hosts, String[] origins) {
        this.id = id;
        this.name = name;
        this.start = start;
        this.cookieUrl = start;
        this.cookieName = cookieName;
        this.hosts = hosts;
        this.origins = origins;
    }

    static final SiteConfig[] ALL = {
        new SiteConfig("facebook", "Facebook", "https://www.facebook.com/", "c_user",
            new String[] {"facebook.com", "meta.com"},
            new String[] {"https://www.facebook.com", "https://web.facebook.com"}),
        new SiteConfig("instagram", "Instagram", "https://www.instagram.com/", "sessionid",
            new String[] {"instagram.com", "facebook.com", "meta.com"},
            new String[] {"https://www.instagram.com"}),
        new SiteConfig("tiktok", "TikTok", "https://www.tiktok.com/", "sessionid",
            new String[] {"tiktok.com"},
            new String[] {"https://www.tiktok.com"}),
        new SiteConfig("threads", "Threads", "https://www.threads.com/", "sessionid",
            new String[] {"threads.com", "threads.net", "instagram.com", "facebook.com", "meta.com"},
            new String[] {"https://www.threads.com", "https://www.threads.net"}),
    };

    static SiteConfig of(String id) {
        for (SiteConfig s : ALL) if (s.id.equals(id)) return s;
        return null;
    }

    /** The site's own WebView profile: its cookies, storage and cache, apart from everything else. */
    String profile() {
        return "site-" + id;
    }

    /** Whether the window may show a page on this host: one of the site's hosts or a subdomain of one. */
    boolean allows(String host) {
        if (host == null) return false;
        String h = host.toLowerCase(Locale.ROOT);
        for (String a : hosts) if (h.equals(a) || h.endsWith("." + a)) return true;
        return false;
    }
}
