package app.brainamon.mobile;

import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.CancellationSignal;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsProvider;
import android.provider.DocumentsContract.Document;
import java.io.File;
import java.io.FileNotFoundException;

/** Debug-only SAF provider. Every document is confined to the fixture vault in app-private storage. */
public final class SyncProbeDocuments extends DocumentsProvider {
    static File root(android.content.Context c){File f=new File(c.getFilesDir(),"sync-fixture-vault");f.mkdirs();return f;}
    private File file(String id)throws FileNotFoundException {
        try{File root=root(getContext()).getCanonicalFile(),f=id.equals("root")?root:new File(root,id).getCanonicalFile();if(!f.equals(root)&&!f.toPath().startsWith(root.toPath()))throw new Exception();return f;}catch(Exception e){throw new FileNotFoundException("Invalid fixture path");}
    }
    private String id(File f)throws Exception{return root(getContext()).getCanonicalFile().toPath().relativize(f.getCanonicalFile().toPath()).toString().replace('\\','/');}
    public boolean onCreate(){return true;}
    public boolean isChildDocument(String parent,String child){try{return file(child).toPath().startsWith(file(parent).toPath());}catch(Exception e){return false;}}
    public Cursor queryRoots(String[] projection){return new MatrixCursor(new String[]{"root_id","document_id","title","flags"});}
    private MatrixCursor cursor(String[] projection){return new MatrixCursor(projection==null?new String[]{Document.COLUMN_DOCUMENT_ID,Document.COLUMN_DISPLAY_NAME,Document.COLUMN_MIME_TYPE,Document.COLUMN_SIZE,Document.COLUMN_LAST_MODIFIED,Document.COLUMN_FLAGS}:projection);}
    private void row(MatrixCursor c,String id,File f){MatrixCursor.RowBuilder r=c.newRow();for(String col:c.getColumnNames())switch(col){
        case Document.COLUMN_DOCUMENT_ID:r.add(id);break;
        case Document.COLUMN_DISPLAY_NAME:r.add(f.getName());break;
        case Document.COLUMN_MIME_TYPE:r.add(f.isDirectory()?Document.MIME_TYPE_DIR:"application/octet-stream");break;
        case Document.COLUMN_SIZE:r.add(f.length());break;
        case Document.COLUMN_LAST_MODIFIED:r.add(f.lastModified());break;
        case Document.COLUMN_FLAGS:r.add(Document.FLAG_SUPPORTS_WRITE|Document.FLAG_SUPPORTS_DELETE|Document.FLAG_SUPPORTS_RENAME|Document.FLAG_DIR_SUPPORTS_CREATE);break;
        default:r.add(null);
    }}
    public Cursor queryDocument(String id,String[] projection)throws FileNotFoundException {MatrixCursor c=cursor(projection);File f=file(id);if(f.exists())row(c,id,f);return c;}
    public Cursor queryChildDocuments(String id,String[] projection,String sort)throws FileNotFoundException {MatrixCursor c=cursor(projection);File[] children=file(id).listFiles();if(children!=null)for(File f:children)try{row(c,id(f),f);}catch(Exception e){throw new FileNotFoundException();}return c;}
    public ParcelFileDescriptor openDocument(String id,String mode,CancellationSignal signal)throws FileNotFoundException{return ParcelFileDescriptor.open(file(id),ParcelFileDescriptor.parseMode(mode));}
    public String createDocument(String parent,String mime,String name)throws FileNotFoundException {try{if(name.contains("/")||name.contains("\\")||name.equals(".."))throw new Exception();File f=new File(file(parent),name);if(mime.equals(Document.MIME_TYPE_DIR))f.mkdirs();else f.createNewFile();return id(f);}catch(Exception e){throw new FileNotFoundException();}}
    public String renameDocument(String id,String name)throws FileNotFoundException {try{File f=file(id),next=new File(f.getParentFile(),name);file(id(next));if(!f.renameTo(next))throw new Exception();return id(next);}catch(Exception e){throw new FileNotFoundException();}}
    public void deleteDocument(String id)throws FileNotFoundException {if(!file(id).delete())throw new FileNotFoundException("Could not delete fixture document");}
}
