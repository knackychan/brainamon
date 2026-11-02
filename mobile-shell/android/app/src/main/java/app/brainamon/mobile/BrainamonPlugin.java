package app.brainamon.mobile;

import android.accounts.Account;
import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ActivityNotFoundException;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.net.Uri;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.Build;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import androidx.activity.result.ActivityResult;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.IntentSenderRequest;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.documentfile.provider.DocumentFile;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.google.android.gms.auth.api.identity.AuthorizationRequest;
import com.google.android.gms.auth.api.identity.AuthorizationResult;
import com.google.android.gms.auth.api.identity.Identity;
import com.google.android.gms.common.api.ApiException;
import com.google.android.gms.common.api.Scope;
import com.google.mlkit.vision.barcode.common.Barcode;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanner;
import com.google.mlkit.vision.codescanner.GmsBarcodeScannerOptions;
import com.google.mlkit.vision.codescanner.GmsBarcodeScanning;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Arrays;
import java.util.Iterator;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.SynchronousQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/**
 * What the Brainamon phone page needs from Android (projects/mobile-app/PLAN.md Phase 6), called from
 * web/src/mobile/native.ts:
 * - secrets: the pairing (mirror key, AI keys) and the Google token, encrypted with an Android
 *   Keystore key that never leaves the phone; a restored backup cannot be read (the key is not in it)
 * - googleToken: an access token for the Drive app data folder through Google's AuthorizationClient
 *   (no client id in the app: Google matches the Android OAuth client by package name and signing key)
 * - scanQr: the pairing QR through Google's code scanner (no camera permission: Play services shows it)
 * - "shared" event: text shared to Brainamon from another app (ACTION_SEND text/plain); kept until the
 *   page listens, so the share that started the app is not lost (BridgeActivity hands the launch
 *   intent to handleOnNewIntent too)
 * - "sharedFile" event: a picture, PDF or .md / .txt file shared to Brainamon (ACTION_SEND with
 *   EXTRA_STREAM), read from its content URI as base64 {name, type, data} or {error}; kept the same way
 * - deviceName: the name the PC's Phones list shows (D13): Settings.Global.DEVICE_NAME from API 25, else maker and model
 */
@CapacitorPlugin(name = "Brainamon")
public class BrainamonPlugin extends Plugin {

    private ConnectivityManager connectivity;
    private ConnectivityManager.NetworkCallback networkCallback;
    private Network currentNetwork;

    private JSObject networkState(NetworkCapabilities caps) {
        JSObject state = new JSObject();
        state.put("connected", caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET));
        // A VPN may carry both transports: never call it Wi-Fi if cellular can carry the traffic.
        String type = caps == null ? "none" : caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) ? "cellular"
            : caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ? "wifi"
            : caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) ? "ethernet" : "unknown";
        state.put("type", type);
        return state;
    }

    @PluginMethod
    public void networkStatus(PluginCall call) {
        try { call.resolve(networkState(connectivity.getNetworkCapabilities(connectivity.getActiveNetwork()))); }
        catch (RuntimeException e) { call.reject("Could not check the network.", "network", e); }
    }

    private final ConcurrentHashMap<String, AiStream> aiStreams = new ConcurrentHashMap<>();
    private final ThreadPoolExecutor aiWorkers = new ThreadPoolExecutor(4, 4, 0L, TimeUnit.MILLISECONDS, new SynchronousQueue<>());
    private final ScheduledExecutorService aiClock = Executors.newSingleThreadScheduledExecutor();

    private final class AiStream {
        final String id;
        final AtomicBoolean terminal = new AtomicBoolean();
        volatile boolean cancelled;
        volatile HttpURLConnection connection;
        volatile InputStream input;
        int awaiting = -1;
        AiStream(String id) { this.id = id; }
        void emit(String kind, JSObject event) {
            if (terminal.get()) return;
            event.put("id", id); event.put("kind", kind);
            notifyListeners("aiStream", event);
        }
        void finish(String kind, String message) {
            if (!terminal.compareAndSet(false, true)) return;
            JSObject event = new JSObject();
            event.put("id", id); event.put("kind", kind);
            if (message != null) event.put("message", message);
            notifyListeners("aiStream", event);
        }
        void cancel() {
            cancelled = true;
            synchronized (this) { notifyAll(); }
            HttpURLConnection c = connection;
            if (c != null) c.disconnect();
            InputStream in = input;
            if (in != null) try { in.close(); } catch (Exception ignored) { }
        }
        void check(long deadline) throws Exception {
            if (cancelled || System.nanoTime() >= deadline) throw new java.io.IOException("Stream cancelled or timed out.");
        }
    }

    @PluginMethod
    public void aiStreamStart(PluginCall call) {
        final String id = call.getString("id", "");
        try {
            if (!id.matches("[A-Za-z0-9_-]{1,100}")) throw new IllegalArgumentException();
            URL url = new URL(call.getString("url", ""));
            String host = url.getHost(), path = url.getPath();
            boolean approved = "https".equals(url.getProtocol()) && (url.getPort() == -1 || url.getPort() == 443)
                && ((host.equals("api.anthropic.com") && path.equals("/v1/messages"))
                    || (host.equals("api.openai.com") && path.equals("/v1/responses")));
            boolean debug = (getContext().getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0;
            boolean fixture = debug && url.getProtocol().equals("http") && (host.equals("127.0.0.1") || host.equals("10.0.2.2"))
                && (path.equals("/ai/anthropic/v1/messages") || path.equals("/ai/openai/v1/responses"));
            if ((!approved && !fixture) || url.getUserInfo() != null || url.getQuery() != null || url.getRef() != null) throw new IllegalArgumentException();
            String body = call.getString("body", "");
            if (!new JSObject(body).optBoolean("stream", false)) throw new IllegalArgumentException();
            JSObject headers = call.getObject("headers", new JSObject());
            Set<String> allowed = new java.util.HashSet<>(Arrays.asList("content-type", "authorization", "x-api-key", "anthropic-version", "anthropic-dangerous-direct-browser-access"));
            for (Iterator<String> keys = headers.keys(); keys.hasNext();) {
                String name = keys.next();
                if (!allowed.contains(name.toLowerCase(Locale.ROOT)) || !(headers.get(name) instanceof String)
                    || headers.getString(name).contains("\r") || headers.getString(name).contains("\n")) throw new IllegalArgumentException();
            }
            int connect = call.getInt("connectTimeoutMs", 10000), request = call.getInt("requestTimeoutMs", 60000);
            if (connect <= 0 || connect > 10000 || request <= 0 || request > 60000) throw new IllegalArgumentException();
            AiStream stream = new AiStream(id);
            synchronized (aiStreams) {
                if (aiStreams.size() >= 4 || aiStreams.containsKey(id)) { call.reject("Native stream capacity or duplicate request ID."); return; }
                aiStreams.put(id, stream);
            }
            try {
                aiWorkers.execute(() -> runAiStream(stream, url, headers, body, connect, request));
                call.resolve();
            } catch (RuntimeException e) {
                aiStreams.remove(id, stream); call.reject("Native stream workers unavailable.");
            }
        } catch (Exception e) { call.reject("Invalid native AI stream request."); }
    }

    private void runAiStream(AiStream s, URL url, JSObject headers, String body, int connect, int request) {
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(request);
        ScheduledFuture<?> timer = aiClock.schedule(s::cancel, request, TimeUnit.MILLISECONDS);
        try {
            s.check(deadline);
            HttpURLConnection c = (HttpURLConnection) url.openConnection();
            s.connection = c;
            c.setInstanceFollowRedirects(false);
            c.setConnectTimeout(connect); c.setReadTimeout(request);
            c.setRequestMethod("POST"); c.setDoOutput(true);
            for (Iterator<String> keys = headers.keys(); keys.hasNext();) {
                String key = keys.next(); c.setRequestProperty(key, headers.getString(key));
            }
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(bytes.length);
            s.check(deadline);
            try (OutputStream out = c.getOutputStream()) { out.write(bytes); }
            s.check(deadline);
            int status = c.getResponseCode();
            if (status >= 300 && status < 400) throw new java.io.IOException("Redirect refused.");
            JSObject h = new JSObject();
            for (Map.Entry<String, List<String>> e : c.getHeaderFields().entrySet())
                if (e.getKey() != null) h.put(e.getKey(), String.join(", ", e.getValue()));
            JSObject event = new JSObject(); event.put("status", status); event.put("headers", h);
            s.emit("headers", event);
            s.input = status >= 400 ? c.getErrorStream() : c.getInputStream();
            byte[] buffer = new byte[8192];
            int seq = 0, errorBytes = 0;
            if (s.input != null) for (;;) {
                s.check(deadline);
                int n = s.input.read(buffer);
                if (n < 0) break;
                if (status >= 400 && (errorBytes += n) > 8192) break;
                synchronized (s) { s.awaiting = seq; }
                JSObject chunk = new JSObject(); chunk.put("seq", seq++);
                chunk.put("data", Base64.encodeToString(buffer, 0, n, Base64.NO_WRAP));
                s.emit("chunk", chunk);
                synchronized (s) {
                    while (s.awaiting >= 0 && !s.cancelled) {
                        s.check(deadline);
                        long waitMs = Math.max(1, TimeUnit.NANOSECONDS.toMillis(deadline - System.nanoTime()));
                        s.wait(waitMs);
                    }
                }
            }
            s.check(deadline); s.finish("done", null);
        } catch (Exception e) { s.finish("error", "Native AI stream interrupted or timed out."); }
        finally { timer.cancel(false); s.cancel(); aiStreams.remove(s.id, s); }
    }

    @PluginMethod
    public void aiStreamAck(PluginCall call) {
        AiStream s = aiStreams.get(call.getString("id", ""));
        if (s != null) {
            boolean valid;
            synchronized (s) {
                valid = s.awaiting >= 0 && s.awaiting == call.getInt("seq", -1);
                if (valid) { s.awaiting = -1; s.notifyAll(); }
            }
            if (!valid) { s.finish("error", "Invalid stream sequence."); s.cancel(); call.reject("Invalid stream sequence."); return; }
        }
        call.resolve();
    }

    @PluginMethod
    public void aiStreamCancel(PluginCall call) {
        AiStream s = aiStreams.get(call.getString("id", ""));
        if (s != null) { s.finish("error", "Native AI stream cancelled."); s.cancel(); }
        call.resolve();
    }

    @Override
    protected void handleOnDestroy() {
        if (connectivity != null && networkCallback != null) connectivity.unregisterNetworkCallback(networkCallback);
        for (AiStream s : aiStreams.values()) { s.finish("error", "Native stream closed."); s.cancel(); }
        aiStreams.clear(); aiWorkers.shutdownNow(); aiClock.shutdownNow();
        super.handleOnDestroy();
    }

    private static final String PREFS = "brainamon-secrets";
    private static final String KEY_ALIAS = "brainamon-secrets-v1";
    private static final String DRIVE_APPDATA = "https://www.googleapis.com/auth/drive.appdata";

    private ActivityResultLauncher<IntentSenderRequest> consent;
    private PluginCall tokenCall = null;

    @Override
    public void load() {
        connectivity = (ConnectivityManager) getContext().getSystemService(Context.CONNECTIVITY_SERVICE);
        networkCallback = new ConnectivityManager.NetworkCallback() {
            @Override public void onCapabilitiesChanged(Network network, NetworkCapabilities caps) {
                currentNetwork = network;
                notifyListeners("networkChange", networkState(caps));
            }
            @Override public void onLost(Network network) {
                if (network.equals(currentNetwork)) { currentNetwork = null; notifyListeners("networkChange", networkState(null)); }
            }
        };
        connectivity.registerDefaultNetworkCallback(networkCallback);
        consent = getActivity().registerForActivityResult(new ActivityResultContracts.StartIntentSenderForResult(), result -> {
            PluginCall call = tokenCall;
            tokenCall = null;
            if (call == null) return;
            try {
                AuthorizationResult r = Identity.getAuthorizationClient(getActivity()).getAuthorizationResultFromIntent(result.getData());
                resolveToken(call, r);
            } catch (ApiException e) {
                call.reject("Google Drive was not connected.", "denied", e);
            } catch (RuntimeException e) { // the sheet closed with no answer: the page must hear back, or Connect looks dead
                call.reject("Google sign-in failed: " + e.getMessage(), "failed", e);
            }
        });
    }

    // ── Obsidian: an obsidian:// link, with an answer when no app takes it (Obsidian not installed) ──

    @PluginMethod
    public void openUri(PluginCall call) {
        String uri = call.getString("uri", "");
        if (!uri.startsWith("obsidian://")) { call.reject("only obsidian:// links"); return; }
        Intent i = new Intent(Intent.ACTION_VIEW, Uri.parse(uri));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        JSObject o = new JSObject();
        try {
            getActivity().startActivity(i);
            o.put("opened", true);
        } catch (ActivityNotFoundException e) {
            o.put("opened", false);
        }
        call.resolve(o);
    }

    // ── clipboard: the Add screen's Paste button (the WebView refuses navigator.clipboard.readText) ──

    @PluginMethod
    public void clipboardText(PluginCall call) {
        // Android 10+ lets only the focused app read the clipboard: read it on the UI thread, after the tap
        getActivity().runOnUiThread(() -> {
            ClipboardManager cm = (ClipboardManager) getContext().getSystemService(Context.CLIPBOARD_SERVICE);
            ClipData clip = cm == null ? null : cm.getPrimaryClip();
            StringBuilder text = new StringBuilder();
            if (clip != null) {
                for (int i = 0; i < clip.getItemCount(); i++) {
                    CharSequence t = clip.getItemAt(i).coerceToText(getContext());
                    if (t != null && t.length() > 0) text.append(text.length() > 0 ? "\n" : "").append(t);
                }
            }
            JSObject o = new JSObject();
            o.put("text", text.toString());
            call.resolve(o);
        });
    }

    // ── the phone's name: the PC's Phones list (D13, web/src/mobile/mirror/phone-record.ts) ──

    @PluginMethod
    public void deviceName(PluginCall call) {
        String name = null;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N_MR1) {          // Settings.Global.DEVICE_NAME is API 25
            try { name = Settings.Global.getString(getContext().getContentResolver(), Settings.Global.DEVICE_NAME); }
            catch (SecurityException e) { name = null; }
        }
        if (name == null || name.trim().isEmpty()) name = (Build.MANUFACTURER + " " + Build.MODEL).trim();
        JSObject o = new JSObject();
        o.put("name", name);
        call.resolve(o);
    }

    // ── secrets ──────────────────────────────────────────────────────────────

    private SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        if (ks.containsAlias(KEY_ALIAS)) return ((KeyStore.SecretKeyEntry) ks.getEntry(KEY_ALIAS, null)).getSecretKey();
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        g.init(
            new KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        );
        return g.generateKey();
    }

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    @PluginMethod
    public void secretGet(PluginCall call) {
        String name = call.getString("key", "");
        String stored = prefs().getString(name, null);
        JSObject out = new JSObject();
        if (stored == null) {
            out.put("value", null);
            call.resolve(out);
            return;
        }
        try {
            byte[] all = Base64.decode(stored, Base64.NO_WRAP);
            ByteBuffer b = ByteBuffer.wrap(all);
            byte[] iv = new byte[12];
            b.get(iv);
            byte[] ct = new byte[b.remaining()];
            b.get(ct);
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
            out.put("value", new String(c.doFinal(ct), StandardCharsets.UTF_8));
        } catch (Exception e) {
            prefs().edit().remove(name).apply(); // another key (a restored backup): unreadable, start again
            out.put("value", null);
        }
        call.resolve(out);
    }

    @PluginMethod
    public void secretSet(PluginCall call) {
        String name = call.getString("key", "");
        String value = call.getString("value");
        if (value == null) {
            prefs().edit().remove(name).apply();
            call.resolve();
            return;
        }
        try {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, key());
            byte[] iv = c.getIV();
            byte[] ct = c.doFinal(value.getBytes(StandardCharsets.UTF_8));
            byte[] all = ByteBuffer.allocate(iv.length + ct.length).put(iv).put(ct).array();
            prefs().edit().putString(name, Base64.encodeToString(all, Base64.NO_WRAP)).apply();
            call.resolve();
        } catch (Exception e) {
            call.reject("The phone could not store the secret: " + e.getMessage(), e);
        }
    }

    // ── Google Drive ─────────────────────────────────────────────────────────

    /**
     * {silent}: true never shows anything (fails with "consent" when the user must agree first).
     * {account}: that Google account only (a silent renewal for the account confirmed on the phone).
     * {choose}: show the account chooser, even when Google remembers an account for the app (after a
     * reset it handed that one back without asking).
     */
    @PluginMethod
    public void googleToken(PluginCall call) {
        boolean silent = Boolean.TRUE.equals(call.getBoolean("silent", false));
        boolean choose = Boolean.TRUE.equals(call.getBoolean("choose", false));
        String account = call.getString("account", "");
        if (tokenCall != null) { // an earlier sheet the page stopped waiting for: it must not answer for this call
            tokenCall.reject("Replaced by a newer sign-in.", "replaced");
            tokenCall = null;
        }
        AuthorizationRequest.Builder b = AuthorizationRequest.builder().setRequestedScopes(Collections.singletonList(new Scope(DRIVE_APPDATA)));
        if (account != null && !account.isEmpty()) b.setAccount(new Account(account, "com.google"));
        if (choose && !silent) b.setPrompt(AuthorizationRequest.Prompt.SELECT_ACCOUNT);
        AuthorizationRequest req = b.build();
        Identity.getAuthorizationClient(getActivity())
            .authorize(req)
            .addOnSuccessListener(r -> {
                if (!r.hasResolution()) {
                    resolveToken(call, r);
                } else if (silent || r.getPendingIntent() == null) {
                    call.reject("Google Drive needs you to agree first.", "consent");
                } else {
                    tokenCall = call;
                    consent.launch(new IntentSenderRequest.Builder(r.getPendingIntent().getIntentSender()).build());
                }
            })
            .addOnFailureListener(e -> call.reject("Google sign-in failed: " + e.getMessage(), "failed", e));
    }

    private void resolveToken(PluginCall call, AuthorizationResult r) {
        if (r.getAccessToken() == null) {
            call.reject("Google gave no access to Drive.", "denied");
            return;
        }
        JSObject out = new JSObject();
        out.put("token", r.getAccessToken());
        out.put("expiresIn", 3600); // Google's access tokens last about an hour
        call.resolve(out);
    }

    // ── the pairing QR ───────────────────────────────────────────────────────

    @PluginMethod
    public void scanQr(PluginCall call) {
        GmsBarcodeScannerOptions options = new GmsBarcodeScannerOptions.Builder().setBarcodeFormats(Barcode.FORMAT_QR_CODE).build();
        GmsBarcodeScanner scanner = GmsBarcodeScanning.getClient(getActivity(), options);
        scanner
            .startScan()
            .addOnSuccessListener(code -> {
                JSObject out = new JSObject();
                out.put("text", code.getRawValue());
                call.resolve(out);
            })
            .addOnCanceledListener(() -> call.reject("No code was scanned.", "cancelled"))
            .addOnFailureListener(e -> call.reject("The scanner could not start: " + e.getMessage(), "failed", e));
    }

    // ── the share sheet ──────────────────────────────────────────────────────

    private static String sharedText(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return null;
        String text = intent.getStringExtra(Intent.EXTRA_TEXT);
        String subject = intent.getStringExtra(Intent.EXTRA_SUBJECT);
        if (text == null || text.isEmpty()) return subject;
        return subject != null && !subject.isEmpty() && !text.contains(subject) ? text + "\n" + subject : text;
    }

    private static final int MAX_SHARED_BYTES = 30 * 1024 * 1024;

    @SuppressWarnings("deprecation")
    private JSObject sharedFile(Intent intent) {
        if (intent == null || !Intent.ACTION_SEND.equals(intent.getAction())) return null;
        Uri uri = intent.getParcelableExtra(Intent.EXTRA_STREAM);
        if (uri == null) return null;
        JSObject out = new JSObject();
        String name = "shared";
        try (Cursor c = getContext().getContentResolver().query(uri, new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
            if (c != null && c.moveToFirst() && !c.isNull(0)) name = c.getString(0);
        } catch (Exception ignored) { }
        String type = intent.getType();
        out.put("name", name);
        out.put("type", type == null ? "" : type);
        try (InputStream in = getContext().getContentResolver().openInputStream(uri)) {
            if (in == null) throw new IllegalStateException("no data");
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[65536];
            int n;
            while ((n = in.read(chunk)) > 0) {
                buf.write(chunk, 0, n);
                if (buf.size() > MAX_SHARED_BYTES) {
                    out.put("error", "That file is over 30 MB.");
                    return out;
                }
            }
            out.put("data", Base64.encodeToString(buf.toByteArray(), Base64.NO_WRAP));
        } catch (Exception e) {
            out.put("error", "Brainamon could not read the shared file: " + e.getMessage());
        }
        return out;
    }

    @Override
    protected void handleOnNewIntent(Intent intent) {
        JSObject file = sharedFile(intent);
        if (file != null) {
            notifyListeners("sharedFile", file, true);
            return;
        }
        String text = sharedText(intent);
        if (text == null) return;
        JSObject out = new JSObject();
        out.put("text", text);
        notifyListeners("shared", out, true);
    }

    // ── vault sync: the folder the user picked (projects/vault-sync/plans/03-phone-side.md) ──
    @PluginMethod
    public void vaultPick(PluginCall call) {
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION | Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
        startActivityForResult(call, i, "vaultPicked");
    }

    @ActivityCallback
    private void vaultPicked(PluginCall call, ActivityResult result) {
        if (call == null) return;
        Intent data = result.getData();
        if (result.getResultCode() != Activity.RESULT_OK || data == null || data.getData() == null) {
            call.reject("cancelled");
            return;
        }
        Uri uri = data.getData();
        getContext().getContentResolver().takePersistableUriPermission(uri,
                Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
        DocumentFile root = DocumentFile.fromTreeUri(getContext(), uri);
        JSObject o = new JSObject();
        o.put("uri", uri.toString());
        o.put("name", root != null && root.getName() != null ? root.getName() : "");
        call.resolve(o);
    }

    // each folder's children by name, read once per round (vaultList starts over): findFile lists the whole
    // folder on every call, which made a first sync into folders of thousands of files quadratic
    private final Map<String, Map<String, DocumentFile>> vaultDirs = new HashMap<>();

    private Map<String, DocumentFile> vaultChildren(DocumentFile dir) {
        String k = dir.getUri().toString();
        Map<String, DocumentFile> kids = vaultDirs.get(k);
        if (kids == null) {
            kids = new HashMap<>();
            for (DocumentFile f : dir.listFiles()) if (f.getName() != null) kids.put(f.getName(), f);
            vaultDirs.put(k, kids);
        }
        return kids;
    }

    private DocumentFile vaultFind(String uri, String path, boolean create) {
        DocumentFile cur = DocumentFile.fromTreeUri(getContext(), Uri.parse(uri));
        String[] parts = path.split("/");
        for (int i = 0; i < parts.length && cur != null; i++) {
            Map<String, DocumentFile> kids = vaultChildren(cur);
            DocumentFile next = kids.get(parts[i]);
            if (next == null && create) {
                next = (i == parts.length - 1) ? cur.createFile("application/octet-stream", parts[i]) : cur.createDirectory(parts[i]);
                if (next != null) kids.put(next.getName() != null ? next.getName() : parts[i], next);
            }
            cur = next;
        }
        return cur;
    }

    // the folder that holds `path` (the picked folder itself for a top-level file)
    private DocumentFile vaultParent(String uri, String path) {
        int slash = path.lastIndexOf('/');
        return slash < 0 ? DocumentFile.fromTreeUri(getContext(), Uri.parse(uri)) : vaultFind(uri, path.substring(0, slash), false);
    }

    private static String vaultLeaf(String path) {
        return path.substring(path.lastIndexOf('/') + 1);
    }

    private RecoverableReplace.Folder vaultReplacementFolder(DocumentFile parent) {
        return name -> {
            DocumentFile file = parent.findFile(name);
            if (file == null) return null;
            return new RecoverableReplace.Entry() {
                public boolean rename(String next) { return file.renameTo(next); }
                public boolean delete() { return file.delete(); }
            };
        };
    }

    private void vaultWalk(DocumentFile dir, String prefix, List<String> skip, JSArray out) throws java.io.IOException {
        for (DocumentFile f : dir.listFiles()) {
            String name = f.getName();
            if (name != null && name.endsWith(RecoverableReplace.BACKUP))
                RecoverableReplace.recover(vaultReplacementFolder(dir), name.substring(0, name.length() - RecoverableReplace.BACKUP.length()));
        }
        Map<String, DocumentFile> kids = new HashMap<>();
        vaultDirs.put(dir.getUri().toString(), kids);
        for (DocumentFile f : dir.listFiles()) {
            String name = f.getName();
            if (name == null || name.endsWith(RecoverableReplace.BACKUP)) continue;
            kids.put(name, f);
            String rel = prefix.isEmpty() ? name : prefix + "/" + name;
            boolean skipped = false;
            for (String s : skip) if (rel.equals(s) || rel.startsWith(s + "/")) skipped = true;
            if (skipped) continue;
            if (f.isDirectory()) {
                vaultWalk(f, rel, skip, out);
            } else if (f.isFile()) {
                JSObject o = new JSObject();
                o.put("path", rel);
                o.put("size", f.length());
                o.put("mtime", f.lastModified());
                out.put(o);
            }
        }
    }

    @PluginMethod
    public void vaultList(PluginCall call) {
        try {
            List<String> skip = new ArrayList<>();
            JSArray s = call.getArray("skip");
            if (s != null) for (int i = 0; i < s.length(); i++) skip.add(s.getString(i));
            JSArray out = new JSArray();
            DocumentFile root = DocumentFile.fromTreeUri(getContext(), Uri.parse(call.getString("uri")));
            if (root == null) { call.reject("folder not available"); return; }
            vaultDirs.clear();          // a new round: the folder may have changed since the last one
            vaultWalk(root, "", skip, out);
            JSObject o = new JSObject();
            o.put("files", out);
            call.resolve(o);
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    @PluginMethod
    public void vaultStat(PluginCall call) {
        try {
            JSObject o = new JSObject();
            o.put("exists", vaultFind(call.getString("uri"), call.getString("path"), false) != null);
            call.resolve(o);
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    @PluginMethod
    public void vaultRead(PluginCall call) {
        try {
            DocumentFile f = vaultFind(call.getString("uri"), call.getString("path"), false);
            if (f == null) { call.reject("missing"); return; }
            long offset = call.getDouble("offset", 0.0).longValue();
            int length = call.getInt("length", 3145728);
            try (InputStream in = getContext().getContentResolver().openInputStream(f.getUri())) {
                long skipped = 0;
                while (skipped < offset) {
                    long n = in.skip(offset - skipped);
                    if (n <= 0) break;
                    skipped += n;
                }
                byte[] buf = new byte[length];
                int got = 0, r;
                while (got < length && (r = in.read(buf, got, length - got)) > 0) got += r;
                JSObject o = new JSObject();
                o.put("data", Base64.encodeToString(buf, 0, got, Base64.NO_WRAP));
                o.put("eof", got < length);
                call.resolve(o);
            }
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    @PluginMethod
    public void vaultWrite(PluginCall call) {
        try {
            DocumentFile f = vaultFind(call.getString("uri"), call.getString("path"), true);
            if (f == null) { call.reject("cannot create the file"); return; }
            byte[] bytes = Base64.decode(call.getString("data", ""), Base64.DEFAULT);
            String mode = Boolean.TRUE.equals(call.getBoolean("append", false)) ? "wa" : "wt";
            try (OutputStream out = getContext().getContentResolver().openOutputStream(f.getUri(), mode)) {
                out.write(bytes);
            }
            call.resolve();
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    @PluginMethod
    public void vaultFinish(PluginCall call) {
        try {
            String uri = call.getString("uri"), path = call.getString("path"), tmpPath = call.getString("tmp");
            DocumentFile parent = vaultParent(uri, path);
            if (parent == null) { call.reject("missing"); return; }
            Map<String, DocumentFile> kids = vaultChildren(parent);
            String name = vaultLeaf(path), tmpName = vaultLeaf(tmpPath);
            RecoverableReplace.finish(vaultReplacementFolder(parent), name, tmpName);
            vaultDirs.remove(parent.getUri().toString());
            call.resolve();
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }

    @PluginMethod
    public void vaultDelete(PluginCall call) {
        try {
            String uri = call.getString("uri"), path = call.getString("path");
            DocumentFile parent = vaultParent(uri, path);
            if (parent != null) {
                Map<String, DocumentFile> kids = vaultChildren(parent);
                DocumentFile f = kids.remove(vaultLeaf(path));
                if (f != null && !f.delete()) { call.reject("delete failed"); return; }
            }
            call.resolve();
        } catch (Exception e) {
            call.reject(String.valueOf(e.getMessage()));
        }
    }
}
