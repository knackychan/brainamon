"""Run the actual SAF replacement state machine with a synthetic provider, no device."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'requires an already installed JDK')
class SafReplacement(unittest.TestCase):
    def test_provider_failures_rollback_and_process_interruption(self):
        source = Path(__file__).resolve().parents[1] / 'mobile-shell/android/app/src/main/java/app/brainamon/mobile/RecoverableReplace.java'
        harness = r'''
package app.brainamon.mobile;
import java.util.*;
import java.io.*;
public class ReplacementCheck {
    static class Tree implements RecoverableReplace.Folder {
        Map<String, Doc> files = new HashMap<>();
        Set<Integer> fail = new HashSet<>();
        int step;
        public RecoverableReplace.Entry find(String name) { return files.get(name); }
        void put(String name, String data) { files.put(name, new Doc(this, name, data)); }
        boolean has(String data) { return files.values().stream().anyMatch(d -> d.data.equals(data)); }
    }
    static class Doc implements RecoverableReplace.Entry {
        Tree tree; String name, data;
        Doc(Tree t, String n, String d) { tree=t; name=n; data=d; }
        public boolean rename(String next) {
            if(tree.fail.contains(++tree.step) || tree.files.containsKey(next)) return false;
            tree.files.remove(name); name=next; tree.files.put(name,this); return true;
        }
        public boolean delete() {
            if(tree.fail.contains(++tree.step)) return false;
            tree.files.remove(name); return true;
        }
    }
    static Tree fresh() { Tree t=new Tree();t.put("note.md","old");t.put("note.md.vsync-tmp","new");return t; }
    public static void main(String[] args) throws Exception {
        for(int fail=1;fail<=3;fail++) {
            Tree t=fresh();t.fail.add(fail);
            boolean committed=false;
            try { RecoverableReplace.finish(t,"note.md","note.md.vsync-tmp"); committed=true; } catch(IOException e) {}
            if(committed) { assert t.files.get("note.md").data.equals("new"); }
            else { assert t.has("old"); }
        }
        Tree rollback=fresh();rollback.fail.addAll(Arrays.asList(2,3));
        try { RecoverableReplace.finish(rollback,"note.md","note.md.vsync-tmp");throw new AssertionError(); } catch(IOException expected) {}
        assert rollback.files.containsKey("note.md.vsync-backup");
        rollback.fail.clear();RecoverableReplace.recover(rollback,"note.md");
        assert rollback.files.get("note.md").data.equals("old");
        Tree interrupted=fresh();interrupted.files.get("note.md").rename("note.md.vsync-backup");
        RecoverableReplace.recover(interrupted,"note.md");
        assert interrupted.files.get("note.md").data.equals("old");
        RecoverableReplace.finish(interrupted,"note.md","note.md.vsync-tmp");
        assert interrupted.files.get("note.md").data.equals("new");
        assert !interrupted.files.containsKey("note.md.vsync-backup");
        System.out.print("replacement checks passed");
    }
}
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            check = root / 'ReplacementCheck.java'
            check.write_text(harness)
            subprocess.run(['javac', '-d', str(root), str(source), str(check)], check=True, capture_output=True, timeout=30)
            result = subprocess.run(['java', '-ea', '-cp', str(root), 'app.brainamon.mobile.ReplacementCheck'], check=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.stdout, 'replacement checks passed')

    def test_actual_native_directory_adapter_uses_one_fresh_query_and_preserves_recovery(self):
        native = Path(__file__).resolve().parents[1] / 'mobile-shell/android/app/src/main/java/app/brainamon/mobile'
        plugin = (native / 'BrainamonPlugin.java').read_text(encoding='utf-8')

        def method(signature):
            start = plugin.index(signature)
            end = plugin.index('{', start) + 1
            depth = 1
            while depth:
                depth += (plugin[end] == '{') - (plugin[end] == '}')
                end += 1
            return plugin[start:end]

        adapter = '\n'.join(method(signature) for signature in (
            'private Map<String, DocumentFile> vaultChildren(DocumentFile dir)',
            'private Map<String, DocumentFile> vaultChildren(DocumentFile dir, boolean refresh)',
            'private RecoverableReplace.Folder vaultReplacementFolder('))
        harness = r'''
package app.brainamon.mobile;
import java.util.*;
public class DirectoryCheck {
    static class Node {
        String name, id, data;
        Node(String name, String id, String data) { this.name=name; this.id=id; this.data=data; }
    }
    static class Store {
        Map<String,Node> files=new LinkedHashMap<>();
        Set<Integer> fail=new HashSet<>();
        int serial, step, queries, names, lists, wrappers;
        String parentId="root";
        boolean nullCursor;
        void put(String name,String data) { files.put(name,new Node(name,"id-"+(++serial),data)); }
        Node byId(String id) { return files.values().stream().filter(n->n.id.equals(id)).findFirst().orElse(null); }
    }
    static class Uri {
        Store store; String id;
        Uri(Store store,String id) { this.store=store; this.id=id; }
        public String toString() { return id; }
    }
    static class DocumentsContract {
        static class Document {
            static final String COLUMN_DOCUMENT_ID="document_id", COLUMN_DISPLAY_NAME="_display_name";
        }
        static String getDocumentId(Uri uri) { return uri.id; }
        static Uri buildChildDocumentsUriUsingTree(Uri uri,String id) { return new Uri(uri.store,id); }
        static Uri buildDocumentUriUsingTree(Uri uri,String id) { return new Uri(uri.store,id); }
    }
    static class Cursor implements AutoCloseable {
        List<Node> nodes; int at=-1;
        Cursor(Store store) { nodes=new ArrayList<>(store.files.values()); }
        boolean moveToNext() { return ++at<nodes.size(); }
        String getString(int column) { return column==0?nodes.get(at).id:nodes.get(at).name; }
        public void close() {}
    }
    static class Resolver {
        Store store;
        Resolver(Store store) { this.store=store; }
        Cursor query(Uri uri,String[] columns,Object selection,Object args,Object sort) {
            assert Arrays.equals(columns,new String[]{"document_id","_display_name"});
            assert uri.id.equals(store.parentId) : "queried the wrong parent folder";
            store.queries++;
            return store.nullCursor?null:new Cursor(store);
        }
    }
    static class Context {
        Resolver resolver;
        Context(Store store) { resolver=new Resolver(store); }
        Resolver getContentResolver() { return resolver; }
    }
    static class DocumentFile {
        Uri uri;
        DocumentFile(Uri uri) { this.uri=uri; }
        static DocumentFile fromTreeUri(Context context,Uri uri) {
            uri.store.wrappers++;
            assert uri.store.byId(uri.id)!=null : "child document ID was replaced with the tree root";
            return new DocumentFile(uri);
        }
        Uri getUri() { return uri; }
        String getName() { uri.store.names++; return uri.store.byId(uri.id).name; }
        DocumentFile[] listFiles() { uri.store.lists++; throw new AssertionError("per-file directory scan"); }
        DocumentFile findFile(String name) { throw new AssertionError("per-file findFile"); }
        boolean renameTo(String next) {
            Store store=uri.store; Node node=store.byId(uri.id);
            if (store.fail.contains(++store.step)||store.files.containsKey(next)) return false;
            store.files.remove(node.name); node.name=next; node.id="id-"+(++store.serial);
            uri=new Uri(store,node.id); store.files.put(next,node); return true;
        }
        boolean delete() {
            Store store=uri.store;
            if (store.fail.contains(++store.step)) return false;
            store.files.remove(store.byId(uri.id).name); return true;
        }
    }
    static class Adapter {
        private final Map<String,Map<String,DocumentFile>> vaultDirs=new HashMap<>();
        Context context;
        Adapter(Store store) { context=new Context(store); }
        Context getContext() { return context; }
        /* ACTUAL_ADAPTER */
    }
    static DocumentFile parent(Store store) { return new DocumentFile(new Uri(store,store.parentId)); }
    public static void main(String[] args) throws Exception {
        Store large=new Store();
        for(int i=0;i<4316;i++) large.put("existing-"+i+".md","keep");
        large.put("note.md.vsync-tmp","new");
        Adapter adapter=new Adapter(large); DocumentFile parent=parent(large);
        adapter.vaultChildren(parent); // A round's initial scan already supplies these DocumentFiles.
        large.queries=0; large.wrappers=0;
        RecoverableReplace.finish(adapter.vaultReplacementFolder(parent),"note.md","note.md.vsync-tmp");
        assert large.queries==1 && large.names==0 && large.lists==0 && large.wrappers==0;
        Map<String,DocumentFile> cached=adapter.vaultChildren(parent);
        assert large.queries==1 : "successful commit discarded the directory cache";
        assert cached.containsKey("note.md") && !cached.containsKey("note.md.vsync-tmp");
        assert large.byId(cached.get("note.md").getUri().id).data.equals("new");

        Store nested=new Store(); nested.parentId="tree/Brainamon/Items";
        nested.put("note.md.vsync-tmp","nested content");
        Adapter nestedAdapter=new Adapter(nested); DocumentFile np=parent(nested);
        RecoverableReplace.finish(nestedAdapter.vaultReplacementFolder(np),"note.md","note.md.vsync-tmp");
        DocumentFile child=nestedAdapter.vaultChildren(np).get("note.md");
        assert !child.getUri().id.equals(np.getUri().id);
        assert nested.byId(child.getUri().id).data.equals("nested content");
        assert nested.queries==1;

        // Changes made by Obsidian after a prior scan must be seen before replacement.
        Store changed=new Store(); Adapter external=new Adapter(changed); DocumentFile cp=parent(changed);
        external.vaultChildren(cp);
        changed.put("note.md","external edit"); changed.put("note.md.vsync-tmp","new");
        RecoverableReplace.Folder refreshed=external.vaultReplacementFolder(cp);
        assert refreshed.find("note.md")!=null && changed.queries==2;
        changed.fail.add(2); // final rename fails, so the external edit must be restored.
        try { RecoverableReplace.finish(refreshed,"note.md","note.md.vsync-tmp"); throw new AssertionError(); }
        catch(java.io.IOException expected) {}
        assert changed.files.get("note.md").data.equals("external edit");
        external.vaultChildren(cp);
        assert changed.queries==3 : "provider failure did not invalidate the snapshot";
        changed.files.remove("note.md");
        assert external.vaultReplacementFolder(cp).find("note.md")==null;

        Store replaced=new Store(); replaced.put("note.md","old");
        Adapter replacedAdapter=new Adapter(replaced); DocumentFile pp=parent(replaced);
        String oldId=replacedAdapter.vaultChildren(pp).get("note.md").getUri().id;
        replaced.put("note.md","recreated by Obsidian");
        replacedAdapter.vaultReplacementFolder(pp);
        DocumentFile replacement=replacedAdapter.vaultChildren(pp).get("note.md");
        assert !replacement.getUri().id.equals(oldId);
        assert replaced.byId(replacement.getUri().id).data.equals("recreated by Obsidian");

        Store cleanup=new Store(); cleanup.put("note.md","old"); cleanup.put("note.md.vsync-tmp","new");
        cleanup.fail.add(3); // Backup cleanup fails after commit: retain both and refresh next use.
        Adapter cleanupAdapter=new Adapter(cleanup); DocumentFile dp=parent(cleanup);
        RecoverableReplace.finish(cleanupAdapter.vaultReplacementFolder(dp),"note.md","note.md.vsync-tmp");
        assert cleanup.files.get("note.md").data.equals("new");
        assert cleanup.files.get("note.md.vsync-backup").data.equals("old");
        assert cleanupAdapter.vaultChildren(dp).containsKey("note.md.vsync-backup");
        assert cleanup.queries==2;

        Store interrupted=new Store(); interrupted.put("note.md.vsync-backup","old");
        Adapter recovery=new Adapter(interrupted); DocumentFile rp=parent(interrupted);
        RecoverableReplace.recover(recovery.vaultReplacementFolder(rp),"note.md");
        assert interrupted.files.get("note.md").data.equals("old");
        assert recovery.vaultChildren(rp).containsKey("note.md");
        assert !recovery.vaultChildren(rp).containsKey("note.md.vsync-backup");
        assert interrupted.queries==1;

        Store missing=new Store(); missing.nullCursor=true;
        try { new Adapter(missing).vaultChildren(parent(missing)); throw new AssertionError(); }
        catch(IllegalStateException expected) {}
        System.out.print("4316 siblings: 1 provider query, 0 name queries, 0 new wrappers; refresh and rollback passed");
    }
}
'''.replace('/* ACTUAL_ADAPTER */', adapter)
        with tempfile.TemporaryDirectory(prefix='saf-directory-test-') as folder:
            root = Path(folder)
            check = root / 'DirectoryCheck.java'
            check.write_text(harness, encoding='utf-8')
            subprocess.run(['javac', '-d', str(root), str(native / 'RecoverableReplace.java'), str(check)],
                           check=True, capture_output=True, timeout=30)
            result = subprocess.run(['java', '-ea', '-cp', str(root), 'app.brainamon.mobile.DirectoryCheck'],
                                    check=True, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.stdout, '4316 siblings: 1 provider query, 0 name queries, 0 new wrappers; refresh and rollback passed')
