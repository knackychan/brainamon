package app.brainamon.mobile;

import java.io.IOException;

/** SAF has no atomic replacement: keep a named backup until the final rename commits. */
public final class RecoverableReplace {
    public static final String BACKUP = ".vsync-backup";
    public interface Entry {
        boolean rename(String name);
        boolean delete();
    }
    public interface Folder { Entry find(String name); }

    public static void recover(Folder folder, String name) throws IOException {
        Entry backup = folder.find(name + BACKUP);
        if (backup != null && folder.find(name) == null && !backup.rename(name))
            throw new IOException("Previous document remains in " + name + BACKUP + "; restore failed");
    }

    public static void finish(Folder folder, String name, String temporary) throws IOException {
        recover(folder, name);
        Entry stale = folder.find(name + BACKUP);
        if (stale != null && !stale.delete())
            throw new IOException("Previous backup retained; cleanup failed");
        Entry next = folder.find(temporary);
        if (next == null) throw new IOException("Staged document missing");
        Entry old = folder.find(name);
        if (old != null && !old.rename(name + BACKUP))
            throw new IOException("Cannot preserve previous document; replacement cancelled");
        if (!next.rename(name)) {
            if (old != null && !old.rename(name))
                throw new IOException("Replacement failed; previous document retained in " + name + BACKUP);
            throw new IOException("Replacement failed; previous document restored");
        }
        // The final document is committed. A failed cleanup leaves a discoverable backup.
        if (old != null) old.delete();
    }
    private RecoverableReplace() {}
}
