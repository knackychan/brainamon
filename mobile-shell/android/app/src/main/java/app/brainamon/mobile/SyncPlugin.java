package app.brainamon.mobile;

import android.util.Base64;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.JSObject;
import com.getcapacitor.annotation.CapacitorPlugin;
import org.json.JSONObject;
import org.json.JSONTokener;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

@CapacitorPlugin(name="BrainamonSync")
public final class SyncPlugin extends Plugin {
    private final ExecutorService bridge=Executors.newSingleThreadExecutor();
    interface Action { JSONObject run() throws Exception; }
    private void call(PluginCall call,Action action){bridge.execute(()->{try{call.resolve(JSObject.fromJSONObject(action.run()));}catch(Exception e){call.reject(SyncRunner.reason(e),e);}});}
    @PluginMethod public void status(PluginCall c){call(c,()->SyncWork.status(getContext(),c.getString("id","")));}
    @PluginMethod public void configure(PluginCall c){call(c,()->{
        JSONObject patch=c.getData();
        if(patch.has("device") && !patch.getString("device").matches("p[a-f0-9]{10}"))throw new IllegalArgumentException("Invalid device");
        if(patch.has("uri") && !patch.getString("uri").isEmpty() && !patch.getString("uri").startsWith("content://"))throw new IllegalArgumentException("Invalid vault");
        SyncWork.configure(getContext(),patch);return SyncWork.status(getContext(),"");
    });}
    @PluginMethod public void request(PluginCall c){call(c,()->new JSONObject().put("id",SyncWork.request(getContext(),c.getBoolean("force",false),c.getBoolean("legacy",false))));}
    @PluginMethod public void barrier(PluginCall c){call(c,()->{SyncWork.barrier(getContext());return new JSONObject();});}
    private String scope(String expected)throws Exception {
        JSONObject p=SyncRunner.pair(getContext());
        String scope=SyncRunner.scope(p,SyncWork.policy(getContext()).getString("device"));
        if(!scope.equals(expected))throw new IllegalStateException("paused");
        return scope;
    }
    @PluginMethod public void stage(PluginCall c){call(c,()->{
        String scope=scope(c.getString("owner","")),id=c.getString("id",""),name=c.getString("name",""),data=c.getString("data","");
        if(!id.matches("[a-f0-9]{64}") || data.length()>72*1024*1024)throw new IllegalArgumentException("Invalid transfer");
        try(SyncStore db=new SyncStore(getContext())){
            JSONObject prior=db.receipt(scope,id);if(prior!=null)return prior;
            JSONObject p=SyncRunner.pair(getContext());SyncKey key=new SyncKey(Base64.decode(p.getString("k"),Base64.URL_SAFE|Base64.NO_WRAP));
            String prefix=p.optBoolean("solo")?"solo-"+key.name("phone-backup")+"-":"chg-";
            if(!name.startsWith(prefix) || !name.substring(prefix.length()).matches("[a-f0-9]{32}"))throw new IllegalArgumentException("Invalid transfer name");
            byte[] raw=key.open(name,Base64.decode(data,Base64.NO_WRAP));
            JSONObject doc=new JSONObject(new String(raw,java.nio.charset.StandardCharsets.UTF_8));
            String identity=doc.getString("device")+"\n"+doc.getLong("at")+"\n"+doc.optString("stream")+"\n"+doc.optString("seq")+"\n"+doc.optString("previous");
            if(!SyncKey.hex(SyncKey.hash(SyncKey.utf(identity))).equals(id))throw new IllegalArgumentException("Invalid transfer identity");
            if(doc.optInt("format")!=1 || !doc.optString("device").equals(SyncWork.policy(getContext()).getString("device")))throw new IllegalArgumentException("Invalid transfer owner");
            synchronized(SyncWork.POLICY){
                scope(c.getString("owner",""));
                db.stage(scope,id,name,data);
                if(SyncWork.enabled(SyncWork.policy(getContext())))SyncWork.request(getContext(),false,false);
            }
            return db.receipt(scope,id);
        }
    });}
    @PluginMethod public void receipt(PluginCall c){call(c,()->{
        try(SyncStore db=new SyncStore(getContext())){JSONObject r=db.receipt(scope(c.getString("owner","")),c.getString("id",""));return r==null?new JSONObject():r;}
    });}
    @PluginMethod public void cache(PluginCall c){call(c,()->{
        String name=c.getString("name","");if(name.length()>2048)throw new IllegalArgumentException("Invalid cache name");
        try(SyncStore db=new SyncStore(getContext())){String s=db.get(scope(c.getString("owner","")),SyncRunner.stateName(name,SyncWork.policy(getContext())));return new JSONObject().put("value",s==null?JSONObject.NULL:new JSONTokener(s).nextValue());}
    });}
    @PluginMethod public void seedVault(PluginCall c){call(c,()->{
        String scope=scope(c.getString("owner","")),stateName=SyncRunner.stateName("vault-state",SyncWork.policy(getContext()));
        try(SyncStore db=new SyncStore(getContext())){if(db.get(scope,stateName)!=null)return new JSONObject();}
        if(!SyncWork.ROUND.tryLock(1,java.util.concurrent.TimeUnit.SECONDS))return new JSONObject();
        try(SyncStore db=new SyncStore(getContext())){
            if(db.get(scope,stateName)==null && c.getObject("state")!=null)db.put(scope,stateName,c.getObject("state").toString());
        }finally{SyncWork.ROUND.unlock();}return new JSONObject();
    });}
    @Override protected void handleOnDestroy(){bridge.shutdown();super.handleOnDestroy();}
}
