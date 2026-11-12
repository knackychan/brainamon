package app.brainamon.mobile;

import android.content.Context;
import android.database.Cursor;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.os.ParcelFileDescriptor;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import androidx.documentfile.provider.DocumentFile;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.util.HashMap;
import java.util.Map;

/** SAF operations owned by a native round. Same recoverable replacement as the foreground bridge. */
final class SyncFiles implements AutoCloseable {
    static final int LIMIT = 50 * 1024 * 1024;
    private final Context context;
    private final DocumentFile root;
    private final SyncKey key;
    private final boolean localProvider;
    private final Map<String,ParcelFileDescriptor> descriptors=new HashMap<>();
    private final Map<String,String> descriptorPaths=new HashMap<>();
    private final Map<String, Map<String, DocumentFile>> dirs = new HashMap<>();
    final Map<String,long[]> timings = new HashMap<>();
    private void timed(String name,long at) { long[] t=timings.computeIfAbsent(name,k->new long[2]);t[0]++;t[1]+=android.os.SystemClock.elapsedRealtime()-at; }
    SyncFiles(Context c, String uri, SyncKey key) throws IOException {
        context = c; this.key = key;
        root = DocumentFile.fromTreeUri(c,Uri.parse(uri));
        if (root == null || !root.canRead() || !root.canWrite()) throw new IOException("permission");
        localProvider="com.android.externalstorage.documents".equals(root.getUri().getAuthority());
    }
    static void path(String p) throws IOException {
        if (p.isEmpty() || p.contains("\\") || p.contains(":") || p.contains("\0")) throw new IOException("Invalid vault path");
        for (String part : p.split("/",-1)) if (part.isEmpty() || part.equals(".") || part.equals("..")) throw new IOException("Invalid vault path");
    }
    private Map<String,DocumentFile> children(DocumentFile dir, boolean fresh) throws IOException {
        String k = dir.getUri().toString();
        Map<String,DocumentFile> previous = dirs.get(k);
        if (!fresh && previous != null) return previous;
        long at=android.os.SystemClock.elapsedRealtime();
        Map<String,DocumentFile> out = new HashMap<>();
        Uri uri = DocumentsContract.buildChildDocumentsUriUsingTree(dir.getUri(), DocumentsContract.getDocumentId(dir.getUri()));
        try (Cursor c = context.getContentResolver().query(uri,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID,DocumentsContract.Document.COLUMN_DISPLAY_NAME},null,null,null)) {
            if (c == null) throw new IOException("permission");
            timed("childrenQuery",at);at=android.os.SystemClock.elapsedRealtime();
            while (c.moveToNext()) {
                String id=c.getString(0),name=c.getString(1);
                if(id==null || name==null)continue;
                // Reuse only matching live IDs; fromTreeUri otherwise repeats a PackageManager lookup per sibling.
                DocumentFile f=previous!=null?previous.get(name):null;
                if(f==null || !id.equals(DocumentsContract.getDocumentId(f.getUri())))
                    f=DocumentFile.fromTreeUri(context,DocumentsContract.buildDocumentUriUsingTree(dir.getUri(),id));
                if (f != null) out.put(name,f);
            }
        }
        timed("childrenRows",at);
        dirs.put(k,out); return out;
    }
    private DocumentFile child(DocumentFile dir,String name,boolean fresh)throws IOException {
        if(localProvider) {
            long at=android.os.SystemClock.elapsedRealtime();
            try {
                // Recheck the provider grant even when the directory descriptor is already open.
                try(Cursor c=context.getContentResolver().query(dir.getUri(),new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID},null,null,null)) {
                    if(c==null || !c.moveToFirst())throw new IOException("permission");
                }
                String uri=dir.getUri().toString();ParcelFileDescriptor fd=descriptors.get(uri);
                if(fd!=null && !descriptorPaths.get(uri).equals(Os.readlink("/proc/self/fd/"+fd.getFd()))) {
                    descriptors.remove(uri);descriptorPaths.remove(uri);fd.close();fd=null;
                }
                if(fd==null) {
                    fd=context.getContentResolver().openFileDescriptor(dir.getUri(),"r");
                    if(fd==null)throw new IOException("permission");
                    if(!OsConstants.S_ISDIR(Os.fstat(fd.getFileDescriptor()).st_mode)){fd.close();fd=null;}
                    else {
                        descriptors.put(uri,fd);descriptorPaths.put(uri,Os.readlink("/proc/self/fd/"+fd.getFd()));
                    }
                }
                if(fd!=null) {
                    try {
                        int mode=Os.lstat("/proc/self/fd/"+fd.getFd()+"/"+name).st_mode;
                        if(OsConstants.S_ISLNK(mode))throw new IOException("Invalid vault path");
                    }catch(ErrnoException e){if(e.errno==OsConstants.ENOENT)return null;throw e;}
                    String parentId=DocumentsContract.getDocumentId(dir.getUri());
                    String id=parentId+(parentId.endsWith(":")?"":"/")+name;
                    return DocumentFile.fromTreeUri(context,DocumentsContract.buildDocumentUriUsingTree(dir.getUri(),id));
                }
            }catch(java.io.FileNotFoundException unsupported){
                // A provider without directory descriptors must prove absence by enumeration instead.
            }catch(ErrnoException e){throw new IOException(e.errno==OsConstants.EACCES?"permission":"Cannot inspect vault document",e);}
            finally{timed("lookup",at);}
        }
        return children(dir,fresh).get(name);
    }
    public void close() {
        for(ParcelFileDescriptor fd:descriptors.values())try{fd.close();}catch(IOException ignored){}
        descriptors.clear();descriptorPaths.clear();
    }
    private DocumentFile find(String p, boolean create, boolean folder) throws IOException {
        path(p); DocumentFile cur = root; String[] parts = p.split("/");
        for (int i=0;i<parts.length && cur!=null;i++) {
            DocumentFile next = child(cur,parts[i],false);
            if (next==null && create) {
                next = i < parts.length-1 || folder ? cur.createDirectory(parts[i]) : cur.createFile("application/octet-stream",parts[i]);
                if (next == null) throw new IOException("permission");
                if(!parts[i].equals(next.getName()))throw new IOException("conflict");
                dirs.computeIfAbsent(cur.getUri().toString(),k->new HashMap<>()).put(parts[i],next);
            }
            cur = next;
        }
        return cur;
    }
    private DocumentFile parent(String p, boolean create) throws IOException { int i=p.lastIndexOf('/'); return i<0 ? root : find(p.substring(0,i),create,true); }
    private static String leaf(String p) { return p.substring(p.lastIndexOf('/')+1); }
    private RecoverableReplace.Folder folder(DocumentFile dir,boolean fresh) throws IOException {
        Map<String,DocumentFile> kids = localProvider?dirs.computeIfAbsent(dir.getUri().toString(),k->new HashMap<>()):children(dir,fresh);
        return name -> {
            DocumentFile f=localProvider?child(dir,name,true):kids.get(name); if(f==null)return null;
            return new RecoverableReplace.Entry() {
                String current=name;
                public boolean rename(String next) {
                    if(!f.renameTo(next))return false;
                    if(!next.equals(f.getName())) {
                        // Providers may choose a numbered name on collision; never call that a commit.
                        f.renameTo(current);return false;
                    }
                    kids.remove(current);kids.put(next,f);current=next;return true;
                }
                public boolean delete() { if(!f.delete())return false;kids.remove(current);return true; }
            };
        };
    }
    JSONArray list(JSONArray skip, Runnable checkpoint) throws Exception { dirs.clear(); JSONArray out=new JSONArray(); walk(root,"",skip,out,checkpoint);return out; }
    private void walk(DocumentFile dir,String prefix,JSONArray skip,JSONArray out,Runnable checkpoint) throws Exception {
        checkpoint.run();
        for(String n : new java.util.ArrayList<>(children(dir,true).keySet())) if(n.endsWith(RecoverableReplace.BACKUP)) RecoverableReplace.recover(folder(dir,true),n.substring(0,n.length()-RecoverableReplace.BACKUP.length()));
        Uri uri=DocumentsContract.buildChildDocumentsUriUsingTree(dir.getUri(),DocumentsContract.getDocumentId(dir.getUri()));
        try(Cursor c=context.getContentResolver().query(uri,new String[]{DocumentsContract.Document.COLUMN_DISPLAY_NAME,DocumentsContract.Document.COLUMN_MIME_TYPE,DocumentsContract.Document.COLUMN_SIZE,DocumentsContract.Document.COLUMN_LAST_MODIFIED},null,null,null)) {
            if(c==null)throw new IOException("permission");
            while(c.moveToNext()) {
                checkpoint.run(); String name=c.getString(0),p=prefix+name;
                if(name==null || name.endsWith(RecoverableReplace.BACKUP))continue;
                boolean skipped=false; for(int i=0;i<skip.length();i++){String s=skip.getString(i);if(p.equals(s)||p.startsWith(s+"/"))skipped=true;}
                if(skipped)continue;
                if(DocumentsContract.Document.MIME_TYPE_DIR.equals(c.getString(1)))walk(children(dir,false).get(name),p+"/",skip,out,checkpoint);
                else out.put(new JSONObject().put("path",p).put("size",c.getLong(2)).put("mtime",c.getLong(3)));
            }
        }
    }
    boolean has(String p)throws Exception { path(p);DocumentFile d=parent(p,false);return d!=null && child(d,leaf(p),true)!=null; }
    byte[] read(String p)throws Exception {
        DocumentFile f=find(p,false,false);if(f==null)throw new IOException("missing");
        try(InputStream in=context.getContentResolver().openInputStream(f.getUri())) { return bytes(in,LIMIT); }
    }
    static byte[] bytes(InputStream in,int limit)throws IOException {
        if(in==null)throw new IOException("missing");
        ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[32768];int n;
        while((n=in.read(buf))!=-1){if(out.size()+n>limit)throw new IOException("File exceeds sync limit");out.write(buf,0,n);}return out.toByteArray();
    }
    private void unchanged(String p,String expected)throws Exception {
        boolean exists=has(p);
        if(expected==null ? exists : !exists || !key.contentId(read(p)).equals(expected))throw new IOException("conflict");
    }
    void write(String p,byte[] data,String expected,boolean check)throws Exception {
        path(p);if(data.length>LIMIT)throw new IOException("File exceeds sync limit");
        DocumentFile dir=parent(p,true);
        long at=android.os.SystemClock.elapsedRealtime();
        RecoverableReplace.recover(folder(dir,true),leaf(p));
        timed("recover",at);at=android.os.SystemClock.elapsedRealtime();
        String tmp=p+".vsync-tmp";DocumentFile next=find(tmp,true,false);
        try(OutputStream out=context.getContentResolver().openOutputStream(next.getUri(),"wt")){if(out==null)throw new IOException("permission");out.write(data);}
        timed("stage",at);at=android.os.SystemClock.elapsedRealtime();
        if(check)try{unchanged(p,expected);}catch(Exception e){next.delete();children(dir,false).remove(leaf(tmp));throw e;}
        timed("guard",at);at=android.os.SystemClock.elapsedRealtime();
        // Generic providers reuse the directory just refreshed by the content guard.
        RecoverableReplace.finish(folder(dir,!check),leaf(p),leaf(tmp));
        timed("finish",at);
    }
    void remove(String p,String expected)throws Exception {
        path(p);
        if(expected!=null)unchanged(p,expected);
        DocumentFile dir=parent(p,false);if(dir==null)return;
        DocumentFile f=child(dir,leaf(p),true);
        if(f!=null && !f.delete())throw new IOException("permission");
        Map<String,DocumentFile> kids=dirs.get(dir.getUri().toString());if(kids!=null)kids.remove(leaf(p));
    }
}
