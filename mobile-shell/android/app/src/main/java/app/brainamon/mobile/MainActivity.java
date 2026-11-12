package app.brainamon.mobile;

import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebSettings;
import android.webkit.WebView;
import androidx.activity.EdgeToEdge;
import com.getcapacitor.BridgeActivity;

// The phone page (web/mobile.html) in a WebView, plus the Brainamon plugin (secrets, Google Drive
// sign-in, the pairing QR, the share sheet). Capacitor already sends the service worker's requests
// to the app's own files (android.resolveServiceWorkerRequests, on by default).
public class MainActivity extends BridgeActivity {

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(BrainamonPlugin.class);
        registerPlugin(SyncPlugin.class);
        super.onCreate(savedInstanceState);
        // Draw under the status and navigation bars on every Android version, as Android 15+ forces.
        // Capacitor's SystemBars lifts the WebView by the keyboard's inset, which counts from the bottom of
        // the screen; on Android 14 and older the window otherwise stops above the navigation bar, and the
        // WebView ended a navigation bar's height above the keyboard (a gray band). The page pads for the
        // bars itself (viewport-fit=cover, env(safe-area-inset-*)).
        EdgeToEdge.enable(this);
        // The locked cards size every font as calc(N * var(--u)): about 4 to 8 px on a phone. The WebView's
        // default minimum font size (8 px) and the system font scale (textZoom) lift all of them to the same
        // ~9 px, which overflows the holo text. Brave sets neither, so the cards match there.
        WebSettings settings = getBridge().getWebView().getSettings();
        settings.setMinimumFontSize(1);
        settings.setMinimumLogicalFontSize(1);
        settings.setTextZoom(100);
        // the locked card faces size their text from the card width (fractions of a pixel on a
        // thumbnail card): the WebView's minimum font size and the system font scale would inflate it
        WebSettings s = getBridge().getWebView().getSettings();
        s.setMinimumFontSize(1);
        s.setMinimumLogicalFontSize(1);
        s.setTextZoom(100);
        // debug builds only: the page can be inspected from chrome://inspect on the PC
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
    }
}
