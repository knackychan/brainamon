package app.brainamon.mobile;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** The existing secret format, shared by the page and workers; success means committed to disk. */
final class PhoneSecrets {
    private static synchronized SecretKey key() throws Exception {
        KeyStore ks = KeyStore.getInstance("AndroidKeyStore");
        ks.load(null);
        String alias = "brainamon-secrets-v1";
        if (ks.containsAlias(alias)) return ((KeyStore.SecretKeyEntry) ks.getEntry(alias, null)).getSecretKey();
        KeyGenerator g = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
        g.init(new KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
        return g.generateKey();
    }
    static synchronized String stored(Context context, String name) {
        return context.getSharedPreferences("brainamon-secrets", Context.MODE_PRIVATE).getString(name, null);
    }
    static synchronized String get(Context context, String name) throws Exception {
        String stored = stored(context, name);
        if (stored == null) return null;
        byte[] all = Base64.decode(stored, Base64.NO_WRAP);
        if (all.length < 28) throw new IllegalStateException("Saved sign-in could not be read");
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, all, 0, 12));
        return new String(c.doFinal(all, 12, all.length - 12), StandardCharsets.UTF_8);
    }
    static synchronized void set(Context context, String name, String value) throws Exception {
        android.content.SharedPreferences.Editor edit = context.getSharedPreferences("brainamon-secrets", Context.MODE_PRIVATE).edit();
        if (value == null) edit.remove(name);
        else {
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, key());
            byte[] ct = c.doFinal(value.getBytes(StandardCharsets.UTF_8));
            edit.putString(name, Base64.encodeToString(ByteBuffer.allocate(12 + ct.length).put(c.getIV()).put(ct).array(), Base64.NO_WRAP));
        }
        if (!edit.commit()) throw new java.io.IOException("Saved sign-in could not be stored");
    }
}
