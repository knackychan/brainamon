package app.brainamon.mobile;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.os.SystemClock;
import android.provider.DocumentsContract;
import org.json.JSONArray;
import org.json.JSONObject;

/** Explicit synthetic external-storage fixture; never accepts the user's vault. */
public final class SyncProviderProbe extends Activity {
    private static final String ID="primary:Documents/Brainamon-Sync-Test-2026-11-12";
    private static final String AUTH="com.android.externalstorage.documents";
    private static void validate(Uri uri) {
        if(!AUTH.equals(uri.getAuthority()) || !ID.equals(DocumentsContract.getTreeDocumentId(uri)))
            throw new IllegalArgumentException("Select only the isolated sync test folder");
    }
    public void onCreate(Bundle saved) {
        super.onCreate(saved);
        if(saved==null)startActivityForResult(new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
            .putExtra(DocumentsContract.EXTRA_INITIAL_URI,DocumentsContract.buildDocumentUri(AUTH,ID))
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION|Intent.FLAG_GRANT_WRITE_URI_PERMISSION|Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION),1);
    }
    protected void onActivityResult(int request,int result,Intent data) {
        super.onActivityResult(request,result,data);
        if(result==RESULT_OK && data!=null) {
            Uri uri=data.getData();validate(uri);
            getContentResolver().takePersistableUriPermission(uri,3);
            getSharedPreferences("sync-provider-probe",0).edit().putString("uri",uri.toString()).commit();
        }
        finish();
    }
    static JSONObject run(Context c,String size)throws Exception {
        if(!size.equals("1500") && !size.equals("4645"))throw new IllegalArgumentException("Fixture size");
        Uri tree=Uri.parse(c.getSharedPreferences("sync-provider-probe",0).getString("uri",""));validate(tree);
        Uri dir=DocumentsContract.buildDocumentUriUsingTree(tree,ID+"/"+size);
        JSONObject result=new JSONObject().put("siblings",Integer.parseInt(size));
        // Research only: report failures verbatim, never convert errors into missing documents.
        for(String leaf:new String[]{"note-0.md","absent.md"}) {
            Uri doc=DocumentsContract.buildDocumentUriUsingTree(tree,ID+"/"+size+"/"+leaf);
            long at=SystemClock.elapsedRealtime();
            try(Cursor rows=c.getContentResolver().query(doc,new String[]{DocumentsContract.Document.COLUMN_DOCUMENT_ID},null,null,null)) {
                result.put(leaf,new JSONObject().put("rows",rows==null?-1:rows.getCount()).put("ms",SystemClock.elapsedRealtime()-at));
            }catch(Exception e){result.put(leaf,new JSONObject().put("error",e.toString()).put("ms",SystemClock.elapsedRealtime()-at));}
        }
        try(ParcelFileDescriptor fd=c.getContentResolver().openFileDescriptor(dir,"r")) {
            JSONObject descriptor=new JSONObject().put("opened",fd!=null);
            if(fd!=null)for(String leaf:new String[]{"note-0.md","absent.md"})try{
                descriptor.put(leaf,android.system.Os.stat("/proc/self/fd/"+fd.getFd()+"/"+leaf).st_size);
            }catch(Exception e){descriptor.put(leaf,e.toString());}
            result.put("directoryDescriptor",descriptor);
        }catch(Exception e){result.put("directoryDescriptor",e.toString());}
        SyncKey key=new SyncKey(new byte[32]);
        try(SyncFiles fs=new SyncFiles(c,tree.toString(),key)) {
        long at=SystemClock.elapsedRealtime();
        if(!fs.has(size+"/note-0.md"))throw new AssertionError("Fixture absent");
        result.put("coldLookupMs",SystemClock.elapsedRealtime()-at);fs.timings.clear();
        byte[] original=SyncKey.utf("Synthetic original"),replacement=SyncKey.utf("Synthetic replacement");
        String unique="probe-"+java.util.UUID.randomUUID();
        JSONArray creates=new JSONArray(),replaces=new JSONArray();
        for(int i=0;i<4;i++) {
            String p=size+"/"+unique+"-"+i+".md";
            at=SystemClock.elapsedRealtime();fs.write(p,original,null,true);creates.put(SystemClock.elapsedRealtime()-at);
            at=SystemClock.elapsedRealtime();fs.write(p,replacement,key.contentId(original),true);replaces.put(SystemClock.elapsedRealtime()-at);
            if(!java.util.Arrays.equals(fs.read(p),replacement))throw new AssertionError("Replacement content");
        }
        JSONObject timing=new JSONObject();for(java.util.Map.Entry<String,long[]> e:fs.timings.entrySet())timing.put(e.getKey(),new JSONArray(e.getValue()));
        result.put("createMs",creates).put("replaceMs",replaces).put("timings",timing);
        for(int i=0;i<4;i++)fs.remove(size+"/"+unique+"-"+i+".md",key.contentId(replacement));
        return result;
        }
    }
    static JSONObject safety(Context c,boolean revoke)throws Exception {
        Uri tree=Uri.parse(c.getSharedPreferences("sync-provider-probe",0).getString("uri",""));validate(tree);
        Uri root=DocumentsContract.buildDocumentUriUsingTree(tree,ID);
        String name="safety-"+java.util.UUID.randomUUID();
        Uri folder=DocumentsContract.createDocument(c.getContentResolver(),root,DocumentsContract.Document.MIME_TYPE_DIR,name);
        SyncKey key=new SyncKey(new byte[32]);byte[] before=SyncKey.utf("original"),edited=SyncKey.utf("external"),next=SyncKey.utf("replaced");
        try(SyncFiles fs=new SyncFiles(c,tree.toString(),key)) {
            String p=name+"/note.md";
            if(fs.has(p))throw new AssertionError("Synthetic collision");
            Uri note=DocumentsContract.createDocument(c.getContentResolver(),folder,"text/markdown","note.md");
            try(java.io.OutputStream out=c.getContentResolver().openOutputStream(note,"wt")){out.write(edited);}
            for(int action=0;action<3;action++) {
                try {
                    if(action==2)fs.remove(p,key.contentId(before));else fs.write(p,next,action==0?null:key.contentId(before),true);
                    throw new AssertionError("Concurrent edit accepted");
                }catch(java.io.IOException e){if(!"conflict".equals(e.getMessage()))throw e;}
                if(!java.util.Arrays.equals(fs.read(p),edited))throw new AssertionError("Concurrent edit lost");
            }
            fs.write(p,next,key.contentId(edited),true);
            if(!java.util.Arrays.equals(fs.read(p),next))throw new AssertionError("Safe replacement content");
            note=DocumentsContract.buildDocumentUriUsingTree(tree,ID+"/"+p);
            Uri backup=DocumentsContract.renameDocument(c.getContentResolver(),note,"note.md"+RecoverableReplace.BACKUP);
            fs.write(p,before,key.contentId(next),true);
            if(!java.util.Arrays.equals(fs.read(p),before) || fs.has(p+RecoverableReplace.BACKUP))throw new AssertionError("Interrupted replacement recovery");
            for(String bad:new String[]{"../escape","a/../escape","/escape","a\\b","a//b","a:b"}) {
                try{fs.has(bad);throw new AssertionError("Traversal accepted");}catch(java.io.IOException expected){}
            }
            // A live descriptor must not read a directory that has since moved out of its original path.
            Uri moved=DocumentsContract.renameDocument(c.getContentResolver(),folder,name+"-moved");
            folder=DocumentsContract.createDocument(c.getContentResolver(),root,DocumentsContract.Document.MIME_TYPE_DIR,name);
            if(fs.has(p))throw new AssertionError("Stale directory descriptor used");
            DocumentsContract.deleteDocument(c.getContentResolver(),DocumentsContract.buildDocumentUriUsingTree(tree,ID+"/"+name+"-moved/note.md"));
            DocumentsContract.deleteDocument(c.getContentResolver(),moved);
            if(revoke) {
                c.getContentResolver().releasePersistableUriPermission(tree,3);
                try{fs.has(p);throw new AssertionError("Revoked grant reported a missing file");}
                catch(SecurityException expected){}
            }else DocumentsContract.deleteDocument(c.getContentResolver(),folder);
        }
        return new JSONObject().put("safety","create collision, concurrent edit/delete, safe replacement, recovery, traversal, moved directory").put("revoked",revoke);
    }
}
