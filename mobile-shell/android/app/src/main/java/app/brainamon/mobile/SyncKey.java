package app.brainamon.mobile;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Arrays;
import javax.crypto.Cipher;
import javax.crypto.Mac;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;

/** BAM1 wire format, pinned against the existing Python and WebCrypto implementations. */
final class SyncKey {
    final String fingerprint;
    private final byte[] data, names;
    static byte[] utf(String s) { return s.getBytes(StandardCharsets.UTF_8); }
    static String hex(byte[] bytes) { StringBuilder b = new StringBuilder(); for (byte v : bytes) b.append(String.format("%02x",v & 255)); return b.toString(); }
    static byte[] hash(byte[] data) throws Exception { return MessageDigest.getInstance("SHA-256").digest(data); }
    static byte[] join(byte[] a, byte[] b) { byte[] out = Arrays.copyOf(a,a.length+b.length); System.arraycopy(b,0,out,a.length,b.length); return out; }
    static byte[] hmac(byte[] key, byte[] value) throws Exception { Mac m = Mac.getInstance("HmacSHA256"); m.init(new SecretKeySpec(key,"HmacSHA256")); return m.doFinal(value); }
    SyncKey(byte[] master) throws Exception {
        if (master.length != 32) throw new IllegalArgumentException("Invalid mirror key");
        byte[] prk = hmac(new byte[32], master);
        data = hmac(prk, join(utf("brainamon-mirror-1 data"),new byte[]{1}));
        names = hmac(prk, join(utf("brainamon-mirror-1 name"),new byte[]{1}));
        fingerprint = hex(hash(join(utf("brainamon-mirror-1 id"),master))).substring(0,12);
    }
    String name(String logical) throws Exception { return hex(hmac(names,utf(logical))).substring(0,32); }
    String contentId(byte[] value) throws Exception { return hex(hmac(names,join(utf("vault-content "),value))).substring(0,32); }
    byte[] seal(String logical, byte[] plain) throws Exception {
        byte[] iv = new byte[12]; new SecureRandom().nextBytes(iv);
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.ENCRYPT_MODE,new SecretKeySpec(data,"AES"),new GCMParameterSpec(128,iv)); c.updateAAD(utf(logical));
        return join(join(utf("BAM1"),iv),c.doFinal(plain));
    }
    byte[] open(String logical, byte[] blob) throws Exception {
        if (blob.length < 32 || !Arrays.equals(Arrays.copyOf(blob,4),utf("BAM1"))) throw new IllegalArgumentException("Invalid sealed file");
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding"); c.init(Cipher.DECRYPT_MODE,new SecretKeySpec(data,"AES"),new GCMParameterSpec(128,blob,4,12)); c.updateAAD(utf(logical));
        return c.doFinal(blob,16,blob.length-16);
    }
}
