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
