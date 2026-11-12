package app.brainamon.mobile;

import android.content.Context;
import android.content.ContentValues;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONObject;

/** Immutable encrypted transfer envelopes and native checkpoints; never a second change journal. */
final class SyncStore extends SQLiteOpenHelper {
    private final java.io.File files;
    private static final Object FILES = new Object();
    SyncStore(Context c) { super(c, "brainamon-sync.db", null, 1); files=new java.io.File(c.getNoBackupFilesDir(),"sync-content"); }
    // Android CursorWindow cannot hold a large queue or library part. SQLite commits small file pointers.
    private String content(String value) {
        if(value.length()<65536)return value;
        try {
            byte[] bytes=SyncKey.utf(value);String name=SyncKey.hex(SyncKey.hash(bytes));
            synchronized(FILES){
                if(!files.isDirectory() && !files.mkdirs())throw new java.io.IOException("Cannot save sync content");
                android.util.AtomicFile file=new android.util.AtomicFile(new java.io.File(files,name));
                if(!file.getBaseFile().isFile()){
                    java.io.FileOutputStream out=file.startWrite();
                    try{out.write(bytes);file.finishWrite(out);}catch(Exception e){file.failWrite(out);throw e;}
                }
            }
            return "@"+name;
        }catch(Exception e){throw new IllegalStateException("Sync content could not be saved",e);}
    }
    private String expand(String value) {
        if(value==null || !value.matches("@[a-f0-9]{64}"))return value;
        try(java.io.InputStream in=new java.io.FileInputStream(new java.io.File(files,value.substring(1)))){
            return new String(SyncFiles.bytes(in,80*1024*1024),java.nio.charset.StandardCharsets.UTF_8);
        }catch(Exception e){throw new IllegalStateException("Sync content could not be read",e);}
    }
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE state (scope TEXT NOT NULL, name TEXT NOT NULL, value TEXT NOT NULL, PRIMARY KEY(scope,name))");
        db.execSQL("CREATE TABLE outbox (scope TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL, remote TEXT, PRIMARY KEY(scope,id))");
    }
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) { throw new IllegalStateException("Unsupported sync storage version"); }
    String get(String scope, String name) {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT value FROM state WHERE scope=? AND name=?", new String[]{scope,name})) { return c.moveToFirst() ? expand(c.getString(0)) : null; }
    }
    JSONObject work(String id)throws Exception {
        String value=get("","work/"+id);return value==null?null:new JSONObject(value);
    }
    void work(String id,JSONObject value){put("","work/"+id,value.toString());}
    void put(String scope, String name, String value) {
      synchronized(FILES){
        ContentValues v = new ContentValues(); v.put("scope", scope); v.put("name", name); v.put("value", content(value));
        if (getWritableDatabase().insertWithOnConflict("state", null, v, SQLiteDatabase.CONFLICT_REPLACE) < 0) throw new IllegalStateException("Sync progress could not be saved");
      }
    }
    JSONObject receipt(String scope, String id) throws Exception {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT name,remote FROM outbox WHERE scope=? AND id=?", new String[]{scope,id})) {
            return c.moveToFirst() ? new JSONObject().put("name", c.getString(0)).put("remote", c.isNull(1) ? JSONObject.NULL : c.getString(1)) : null;
        }
    }
    void stage(String scope, String id, String name, String data) {
      synchronized(FILES){
        ContentValues v = new ContentValues(); v.put("scope",scope); v.put("id",id); v.put("name",name); v.put("data",content(data));
        // A lost callback must reuse the first sealed envelope, including its random nonce/name.
        if(getWritableDatabase().insertWithOnConflict("outbox", null, v, SQLiteDatabase.CONFLICT_IGNORE)<0){
            try(Cursor c=getReadableDatabase().rawQuery("SELECT id FROM outbox WHERE scope=? AND id=?",new String[]{scope,id})){
                if(!c.moveToFirst())throw new IllegalStateException("Transfer could not be saved");
            }
        }
      }
    }
    JSONObject next(String scope) throws Exception {
        try (Cursor c = getReadableDatabase().rawQuery("SELECT id,name,data FROM outbox WHERE scope=? AND remote IS NULL ORDER BY rowid LIMIT 1", new String[]{scope})) {
            return c.moveToFirst() ? new JSONObject().put("id",c.getString(0)).put("name",c.getString(1)).put("data",expand(c.getString(2))) : null;
        }
    }
    void delivered(String scope, String id, String remote) {
        ContentValues v = new ContentValues(); v.put("remote",remote);
        // Keep a small receipt until the page commits its journal acknowledgement.
        v.put("data", "");
        if (getWritableDatabase().update("outbox",v,"scope=? AND id=?",new String[]{scope,id}) != 1) throw new IllegalStateException("Transfer receipt missing");
    }
    void remove(String scope,String name){getWritableDatabase().delete("state","scope=? AND name=?",new String[]{scope,name});}
    void removePrefix(String scope,String prefix){getWritableDatabase().delete("state","scope=? AND name LIKE ?",new String[]{scope,prefix+"%"});}
    void compact(String scope)throws Exception {
        try(Cursor c=getReadableDatabase().rawQuery("SELECT name,value FROM state WHERE scope=? AND (name LIKE 'upload-time/%' OR (name LIKE 'download/%' AND length(name)=73))",new String[]{scope})){
            while(c.moveToNext()){
                String name=c.getString(0);long at=name.startsWith("upload-time/")?Long.parseLong(c.getString(1)):new JSONObject(c.getString(1)).optLong("at");
                if(at<System.currentTimeMillis()-7*86400000L){
                    if(name.startsWith("upload-time/")){remove(scope,"upload/"+name.substring(12));remove(scope,name);}else removePrefix(scope,name);
                }
            }
        }
        // Keep the current and previous committed snapshots while the page switches between them.
        java.util.Set<String> keep=new java.util.HashSet<>();
        for(String slot:new String[]{"manifest","previous-manifest"}){
            String raw=get(scope,slot);if(raw==null)continue;
            JSONObject entries=new JSONObject(raw).getJSONObject("files");
            java.util.Iterator<String> names=entries.keys();while(names.hasNext()){
                String name=names.next();keep.add("file/"+name+"/"+entries.getJSONObject(name).getString("v"));
            }
        }
        if(!keep.isEmpty())try(Cursor c=getReadableDatabase().rawQuery("SELECT name FROM state WHERE scope=? AND name LIKE 'file/%'",new String[]{scope})){
            while(c.moveToNext()){String name=c.getString(0);if(!keep.contains(name))getWritableDatabase().delete("state","scope=? AND name=?",new String[]{scope,name});}
        }
        synchronized(FILES){
            java.util.Set<String> used=new java.util.HashSet<>();
            try(Cursor c=getReadableDatabase().rawQuery("SELECT value FROM state WHERE value LIKE '@%' UNION SELECT data FROM outbox WHERE data LIKE '@%'",null)){
                while(c.moveToNext())used.add(c.getString(0).substring(1));
            }
            java.io.File[] all=files.listFiles();if(all!=null)for(java.io.File f:all)
                if(f.getName().matches("[a-f0-9]{64}") && !used.contains(f.getName()) && f.lastModified()<System.currentTimeMillis()-86400000L)f.delete();
        }
    }
}
