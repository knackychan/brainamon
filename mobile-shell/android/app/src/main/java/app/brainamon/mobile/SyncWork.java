package app.brainamon.mobile;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.NetworkCapabilities;
import android.net.NetworkRequest;
import android.os.Build;
import androidx.annotation.NonNull;
import androidx.javascriptengine.JavaScriptSandbox;
import androidx.work.*;
import org.json.JSONObject;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

/** Android owns scheduling; the page merely requests or observes a round. */
public final class SyncWork extends Worker {
    static final ReentrantLock ROUND = new ReentrantLock();
    static final Object POLICY = new Object();
    static volatile SyncRunner active;
    private static final String NOW = "brainamon-sync-now", PERIODIC = "brainamon-sync-periodic";
    public SyncWork(@NonNull Context c,@NonNull WorkerParameters p){super(c,p);}
    static boolean supported(){return Build.VERSION.SDK_INT>=26 && JavaScriptSandbox.isSupported();}
    static JSONObject policy(Context c)throws Exception {
        try(SyncStore db=new SyncStore(c)){String s=db.get("","policy");return s==null?new JSONObject():new JSONObject(s);}
    }
    static boolean enabled(JSONObject p){return p.optBoolean("enabled") && !p.optBoolean("paused",true) && !p.optBoolean("blocked",true);}
    static String network(Context c,JSONObject p) {
        ConnectivityManager cm=(ConnectivityManager)c.getSystemService(Context.CONNECTIVITY_SERVICE);
        NetworkCapabilities caps=cm.getNetworkCapabilities(cm.getActiveNetwork());
        if(caps==null || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) || !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED))return "offline";
        if(p.optBoolean("wifiOnly",true) && !caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) && !caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))return "wifi";
        return "";
    }
    static Constraints constraints(JSONObject p) {
        Constraints.Builder b=new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED);
        if(p.optBoolean("wifiOnly",true))b.setRequiredNetworkRequest(new NetworkRequest.Builder()
            .addCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .addTransportType(NetworkCapabilities.TRANSPORT_WIFI).addTransportType(NetworkCapabilities.TRANSPORT_ETHERNET).build(),NetworkType.CONNECTED);
        return b.build();
    }
    static void configure(Context c,JSONObject patch)throws Exception {
        JSONObject p;
        synchronized(POLICY){
            p=policy(c);String before=p.toString();
            for(String k:new String[]{"enabled","paused","blocked","wifiOnly","device","uri","vault"})if(patch.has(k))p.put(k,patch.get(k));
            if(!before.equals(p.toString())) {
                p.put("generation",p.optLong("generation")+1);
                try(SyncStore db=new SyncStore(c)){db.put("","policy",p.toString());}
                SyncRunner r=active;if(r!=null)r.cancel();
            }
            WorkManager wm=WorkManager.getInstance(c);
            if(!supported() || !enabled(p)){wm.cancelUniqueWork(NOW);wm.cancelUniqueWork(PERIODIC);return;}
            PeriodicWorkRequest periodic=new PeriodicWorkRequest.Builder(SyncWork.class,15,TimeUnit.MINUTES)
                .setInitialDelay(15,TimeUnit.MINUTES).setConstraints(constraints(p))
                .setInputData(new Data.Builder().putBoolean("periodic",true).build())
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS).build();
            wm.enqueueUniquePeriodicWork(PERIODIC,ExistingPeriodicWorkPolicy.UPDATE,periodic).getResult().get(10,TimeUnit.SECONDS);
        }
    }
    static String request(Context c,boolean force,boolean legacy)throws Exception {
        synchronized(POLICY){
            JSONObject p=policy(c);if(!supported() || !enabled(p))throw new IllegalStateException("paused");
            SyncRunner r=active;
            if(r!=null && !force && !legacy && !r.cancelled && r.accepting)return r.id;
            WorkManager wm=WorkManager.getInstance(c);
            for(WorkInfo info:wm.getWorkInfosForUniqueWork(NOW).get(10,TimeUnit.SECONDS)){
                if(info.getState()==WorkInfo.State.ENQUEUED || info.getState()==WorkInfo.State.BLOCKED){
                    if(!force && !legacy)try(SyncStore db=new SyncStore(c)){
                        JSONObject saved=db.work(info.getId().toString());
                        if(saved==null || !saved.has("done") && current(c,p,saved))return info.getId().toString();
                    }
                }
            }
            JSONObject record=new JSONObject().put("owner",SyncRunner.scope(SyncRunner.pair(c),p.optString("device")))
                .put("generation",p.optLong("generation")).put("force",force).put("legacy",legacy);
            OneTimeWorkRequest work=chunk(UUID.randomUUID(),p,record);
            try(SyncStore db=new SyncStore(c)){db.work(work.getId().toString(),record);}
            wm.enqueueUniqueWork(NOW,ExistingWorkPolicy.APPEND_OR_REPLACE,work).getResult().get(10,TimeUnit.SECONDS);
            return work.getId().toString();
        }
    }
    private static OneTimeWorkRequest chunk(UUID id,JSONObject p,JSONObject record)throws Exception {
        OneTimeWorkRequest.Builder builder=new OneTimeWorkRequest.Builder(SyncWork.class).setId(id).setConstraints(constraints(p))
            .setInputData(new Data.Builder().putBoolean("force",record.optBoolean("force")).putBoolean("legacy",record.optBoolean("legacy"))
                .putString("owner",record.getString("owner")).putLong("generation",record.getLong("generation")).build())
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS);
        if(record.optString("yield").equals("contention"))builder.setInitialDelay(5,TimeUnit.SECONDS);
        else if(Build.VERSION.SDK_INT>=31)builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST);
        return builder.build();
    }
    private static boolean current(Context c,JSONObject p,JSONObject record)throws Exception {
        try{return enabled(p) && p.optLong("generation")==record.optLong("generation")
            && record.getString("owner").equals(SyncRunner.scope(SyncRunner.pair(c),p.optString("device")));}
        catch(java.io.IOException e){if("auth".equals(e.getMessage()))return false;throw e;}
    }
    static void handoff(Context c,SyncStore db,String id,JSONObject record)throws Exception {
        synchronized(POLICY){
            JSONObject p=policy(c);if(!current(c,p,record))throw new SyncRunner.Cancelled();
            String next=record.optString("next",UUID.nameUUIDFromBytes(SyncKey.utf("sync-next:"+id)).toString());
            String raw=db.get("","status");JSONObject status=raw==null?new JSONObject():new JSONObject(raw);
            if(id.equals(status.optString("id")) && status.optBoolean("libraryReady"))record.put("libraryReady",true);
            // Save first; replay uses the same ID if the process dies on either side of WorkManager's commit.
            record.put("next",next);db.work(id,record);
            if(db.work(next)==null){
                JSONObject child=new JSONObject(record.toString());child.remove("next");child.remove("done");db.work(next,child);
            }
            WorkManager wm=WorkManager.getInstance(c);
            if(wm.getWorkInfoById(UUID.fromString(next)).get(10,TimeUnit.SECONDS)==null)
                wm.enqueueUniqueWork(NOW,ExistingWorkPolicy.APPEND_OR_REPLACE,chunk(UUID.fromString(next),p,record)).getResult().get(10,TimeUnit.SECONDS);
            if(id.equals(status.optString("id")))report(c,"queued",0);
        }
    }
    static JSONObject status(Context c,String id)throws Exception {
      synchronized(POLICY){
        JSONObject p=policy(c),out;
        try(SyncStore db=new SyncStore(c)){String s=db.get("","status");out=s==null?new JSONObject():new JSONObject(s);}
        out.put("vaultFiles",JSONObject.NULL);
        // Progress belongs to the authenticated pairing and chosen folder, including after reopening.
        try(SyncStore db=new SyncStore(c)){
            if(PhoneSecrets.get(c,"bp-pair")!=null){
                String scope=SyncRunner.scope(SyncRunner.pair(c),p.optString("device"));
                String counts=db.get(scope,SyncRunner.stateName("vault-counts",p));
                if(counts!=null)out.put("vaultFiles",new JSONObject(counts));
            }
        }catch(java.io.IOException e){if(!"auth".equals(e.getMessage()))throw e;}
        out.put("supported",supported() && !out.optString("state").equals("unsupported"));out.put("paused",p.optBoolean("paused",true));
        if(!enabled(p))out.put("state",p.optBoolean("paused",true)?"paused":"queued");
        else {String net=network(c,p);if(!net.isEmpty())out.put("state",net);
            else if(out.optString("state").equals("paused"))out.put("state","queued");}
        String observed=id!=null && !id.isEmpty()?id:out.optString("id");
        if(!observed.isEmpty()) {
            boolean ready=false,tracked=false;
            JSONObject record;
            try(SyncStore db=new SyncStore(c)){
                java.util.Set<String> visited=new java.util.HashSet<>();
                while((record=db.work(observed))!=null){
                    tracked=true;
                    if(!visited.add(observed))throw new IllegalStateException("Invalid sync continuation");
                    if(!current(c,p,record)){
                        if(observed.equals(out.optString("id")) && active==null){out.put("state",p.optBoolean("paused",true)?"paused":"queued");out.remove("last");}
                        return out.put("finished",true).put("outcome","paused").put("requestReady",false).put("libraryReady",false);
                    }
                    ready|=record.optBoolean("libraryReady");
                    if(!record.has("next"))break;
                    observed=record.getString("next");
                }
            }
            WorkInfo info=WorkManager.getInstance(c).getWorkInfoById(UUID.fromString(observed)).get(10,TimeUnit.SECONDS);
            if(info!=null && info.getState()==WorkInfo.State.ENQUEUED && out.optString("state").equals("syncing") && active==null)out.put("state","queued");
            boolean done=record!=null && record.has("done"),terminal=info!=null && info.getState().isFinished();
            if(done && observed.equals(out.optString("id")) && active==null){
                if(record.optLong("last")>0)out.put("last",record.getLong("last"));
                if(enabled(p) && network(c,p).isEmpty())out.put("state",record.getString("done"));
            }
            out.put("observedId",observed).put("requestReady",ready || observed.equals(out.optString("id")) && out.optBoolean("libraryReady"));
            out.put("finished",done || terminal || !tracked && info==null);
            out.put("outcome",done?record.getString("done"):terminal?info.getOutputData().getString("outcome"):JSONObject.NULL);
            if(terminal && !done && info.getState()!=WorkInfo.State.SUCCEEDED)out.put("outcome","paused");
            out.put("scheduled",!done && (info==null && tracked || info!=null && (info.getState()==WorkInfo.State.ENQUEUED || info.getState()==WorkInfo.State.BLOCKED)));
            if(!done && !terminal && !observed.equals(out.optString("id")) && active==null && enabled(p) && network(c,p).isEmpty())out.put("state","queued");
        }
        return out;
      }
    }
    static void barrier(Context c)throws Exception {
        configure(c,new JSONObject().put("blocked",true));
        if(!ROUND.tryLock(45,TimeUnit.SECONDS))throw new IllegalStateException("Sync is finishing a file. Retry shortly.");
        ROUND.unlock();
    }
    @NonNull public Result doWork(){
        Context c=getApplicationContext();
        String id=getId().toString();JSONObject record=null;boolean locked=false;SyncRunner runner=null;
        try {
            JSONObject p=policy(c);if(!enabled(p))return Result.success();
            // Also recognize periodic requests persisted by builds without the dispatcher flag.
            boolean periodic=getInputData().getBoolean("periodic",false);
            if(!periodic)for(WorkInfo info:WorkManager.getInstance(c).getWorkInfosForUniqueWork(PERIODIC).get(10,TimeUnit.SECONDS))
                if(info.getId().equals(getId()))periodic=true;
            if(periodic){request(c,false,false);return Result.success();}
            try(SyncStore db=new SyncStore(c)){
                record=db.work(id);
                if(record==null){
                    record=new JSONObject().put("owner",getInputData().getString("owner")==null?SyncRunner.scope(SyncRunner.pair(c),p.optString("device")):getInputData().getString("owner"))
                        .put("generation",getInputData().getLong("generation",p.optLong("generation")))
                        .put("force",getInputData().getBoolean("force",false)).put("legacy",getInputData().getBoolean("legacy",false));
                    db.work(id,record);
                }
                if(!current(c,p,record) || isStopped())throw new SyncRunner.Cancelled();
                if(record.has("next")){handoff(c,db,id,record);return Result.success();}
                if(record.has("done"))return Result.success(new Data.Builder().putString("outcome",record.getString("done")).build());
                locked=ROUND.tryLock(1,TimeUnit.SECONDS);
                if(!locked){record.put("yield","contention");handoff(c,db,id,record);return Result.success();}
            }
            String net=network(c,p);if(!net.isEmpty()){report(c,net,0);return Result.retry();}
            runner=new SyncRunner(c,id,p,()->isStopped());active=runner;
            JSONObject result=runner.run(record.optBoolean("force"),record.optBoolean("legacy"));
            synchronized(POLICY){
                runner.accepting=false;runner.checkpoint(false);
                // Staging and the end-of-round handoff share this lock, so the last edit cannot miss its wakeup.
                if(runner.store.next(runner.scope)!=null){record.put("yield","outbox");handoff(c,runner.store,id,record);return Result.success();}
                JSONObject vault=result.optJSONObject("vault");
                String state=vault!=null && !vault.optString("state").equals("idle")?"attention":"idle";
                return finish(c,id,record,state,System.currentTimeMillis());
            }
        }catch(Exception e){
            if(e instanceof SyncRunner.BudgetExpired && runner!=null)try{
                synchronized(POLICY){runner.accepting=false;runner.checkpoint(false);record.put("yield","budget");handoff(c,runner.store,id,record);}
                return Result.success();
            }catch(Exception handoff){e=handoff;}
            if(runner!=null)runner.accepting=false;
            if(e instanceof InterruptedException || isStopped())return Result.success(); // WorkManager owns stop/reschedule.
            String why=SyncRunner.reason(e);try{if(runner!=null)report(c,why,0);}catch(Exception ignored){}
            if(java.util.Arrays.asList("auth","access","permission","conflict","update","library","paused","unsupported","key").contains(why))try{
                return finish(c,id,record,why,0);
            }catch(Exception ignored){}
            return Result.retry();
        }finally{try{if(runner!=null)runner.close();}finally{if(runner!=null && active==runner)active=null;if(locked)ROUND.unlock();}}
    }
    private static Result finish(Context c,String id,JSONObject record,String outcome,long last)throws Exception {
      synchronized(POLICY){
        try(SyncStore db=new SyncStore(c)){
            if(record!=null){record.put("done",outcome);if(last>0)record.put("last",last);db.work(id,record);}
            String raw=db.get("","status");
            if(raw==null || id.equals(new JSONObject(raw).optString("id")))report(c,outcome,last);
        }
        // Domain errors settle this request, while later explicit requests remain runnable.
        return Result.success(new Data.Builder().putString("outcome",outcome).build());
      }
    }
    static void report(Context c,String state,long last)throws Exception {
        try(SyncStore db=new SyncStore(c)){
            String s=db.get("","status");JSONObject out=s==null?new JSONObject():new JSONObject(s);
            out.put("state",state);if(last>0)out.put("last",last);out.put("progress",state.equals("idle")?1:out.optDouble("progress"));
            db.put("","status",out.toString());
        }
    }
    @Override public void onStopped(){SyncRunner r=active;if(r!=null && r.id.equals(getId().toString()))r.cancel();}
}
