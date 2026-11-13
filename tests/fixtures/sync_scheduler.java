package app.brainamon.mobile;
import java.util.*;
import java.util.concurrent.*;
import java.io.*;

public class SchedulerCheck {
    static Context c=new Context();
    static WorkManager wm=WorkManager.getInstance(c);
    static SyncStore db=new SyncStore(c);
    static JSONObject policy;
    static void reset()throws Exception {
        SyncStore.rows.clear();SyncStore.crashAfterWork=0;SyncStore.workWrites=0;wm.jobs.clear();wm.names.clear();wm.parents.clear();wm.crash="";
        SyncRunner.calls=0;SyncRunner.budgets=0;SyncRunner.priorityEdits=0;SyncRunner.error="";SyncRunner.lateEdit=false;
        SyncWork.active=null;Clock.now=0;c.owner="account-a";c.network="";
        policy=new JSONObject().put("enabled",true).put("paused",false).put("blocked",false).put("generation",1)
            .put("device","phone").put("uri","content://vault").put("wifiOnly",true);
        db.put("","policy",policy.toString());
    }
    static String request(boolean force,boolean legacy)throws Exception{return SyncWork.request(c,force,legacy);}
    static WorkInfo info(String id){return wm.jobs.get(UUID.fromString(id));}
    static String next(String id)throws Exception{return db.work(id).getString("next");}
    static Worker.Result run(String id)throws Exception {
        WorkInfo i=info(id);i.state=WorkInfo.State.RUNNING;
        Worker.Result result=new SyncWork(c,new WorkerParameters(i.id,i.input)).doWork();
        if(result.kind.equals("retry")){i.attempts++;i.state=WorkInfo.State.ENQUEUED;}
        else {i.state=WorkInfo.State.SUCCEEDED;i.output=result.output;}
        return result;
    }
    static void noDone(String root)throws Exception {
        JSONObject s=SyncWork.status(c,root);
        assert !s.optBoolean("finished") : "chunk became a round receipt";
        assert !s.optString("state").equals("idle");
        assert s.optLong("last")==0 : "budget updated the completed-round time";
    }
    public static void main(String[] args)throws Exception {
        reset();String root=request(true,true);SyncRunner.budgets=3;
        String current=root;
        for(int chunk=0;chunk<3;chunk++){
            assert run(current).kind.equals("success");assert info(current).attempts==0;
            String child=next(current);
            assert wm.parents.get(UUID.fromString(child)).equals(UUID.fromString(current));
            assert info(child).input.getBoolean("force",false) && info(child).input.getBoolean("legacy",false);
            assert info(child).constraints.wifi;
            assert info(child).initialDelay==0;
            assert db.work(current).getString("yield").equals("budget");
            assert info(child).backoff==BackoffPolicy.LINEAR && info(child).backoffSeconds==10;
            noDone(root);current=child;
        }
        assert run(current).kind.equals("success");assert SyncRunner.calls==4;
        assert SyncWork.status(c,root).getString("outcome").equals("idle");
        assert SyncWork.status(c,root).getBoolean("finished");
        int runs=SyncRunner.calls;run(current);assert SyncRunner.calls==runs : "completed result replay reran the vault";

        // Kill at each durable handoff boundary, including after enqueue but before acknowledging it.
        for(String boundary:new String[]{"after-marker","before-enqueue","after-enqueue"}){
            reset();root=request(false,false);SyncRunner.budgets=1;wm.crash=boundary;
            if(boundary.equals("after-marker"))SyncStore.crashAfterWork=2;
            try{run(root);throw new AssertionError("crash not reached");}catch(ProcessDeath expected){}
            String child=next(root);noDone(root);assert SyncRunner.calls==1;
            wm.crash="";SyncStore.crashAfterWork=0;assert run(root).kind.equals("success");
            assert next(root).equals(child);assert wm.jobs.size()==2;
            assert SyncRunner.calls==1 : "handoff replay restarted content work";
            run(child);assert SyncWork.status(c,root).getBoolean("finished");
        }

        reset();root=request(false,false);SyncStore.crashAfterWork=2;
        try{run(root);throw new AssertionError("completion crash not reached");}catch(ProcessDeath expected){}
        assert db.work(root).has("done");assert SyncWork.status(c,root).getString("state").equals("idle");
        assert SyncWork.status(c,root).optLong("last")>0;
        SyncStore.crashAfterWork=0;info(root).state=WorkInfo.State.ENQUEUED;
        db.put(c.owner,"edit","newly staged after process death");
        String fresh=request(false,false);
        assert !fresh.equals(root) : "new edit joined a completed request awaiting Android's acknowledgement";
        run(root);assert SyncRunner.calls==1;assert db.next(c.owner)!=null;
        run(fresh);assert db.next(c.owner)==null;

        reset();root=request(false,false);SyncRunner.error="retry";
        assert run(root).kind.equals("retry");assert !db.work(root).has("next");
        assert run(root).kind.equals("retry");assert info(root).attempts==2;
        SyncRunner.error="";assert run(root).kind.equals("success");

        // Fresh uploads and explicit retry bypass backoff, preserving data/options and existing observers.
        reset();root=request(false,false);SyncRunner.error="retry";run(root);
        info(root).nextAt=System.currentTimeMillis()+80*60_000;
        String queued=request(true,true);
        db.put(c.owner,"edit","saved phone changes");
        JSONObject delayed=SyncWork.status(c,queued);
        assert delayed.getString("state").equals("retry") && delayed.getBoolean("retryable");
        assert delayed.getLong("nextAt")==info(root).nextAt;
        assert request(false,false).equals(root) : "automatic triggers reset backoff";
        fresh=SyncWork.retry(c);
        assert !fresh.equals(root) && info(fresh).attempts==0;
        assert info(root).state==WorkInfo.State.CANCELLED && info(queued).state==WorkInfo.State.CANCELLED;
        assert info(fresh).input.getBoolean("force",false) && info(fresh).input.getBoolean("legacy",false);
        assert db.next(c.owner)!=null : "retry discarded staged changes";
        assert !SyncWork.status(c,root).getBoolean("finished");
        assert !SyncWork.status(c,queued).getBoolean("finished");
        assert SyncWork.status(c,root).isNull("nextAt") && !SyncWork.status(c,root).getBoolean("retryable");
        assert SyncWork.retry(c).equals(fresh) : "repeat tap duplicated fresh work";
        SyncRunner.error="";run(fresh);
        assert SyncWork.status(c,root).getString("outcome").equals("idle");
        assert SyncWork.status(c,queued).getString("outcome").equals("idle");
        assert db.next(c.owner)==null;

        reset();root=request(false,false);info(root).state=WorkInfo.State.RUNNING;
        assert SyncWork.retry(c).equals(root) && wm.jobs.size()==1 : "retry cancelled running work";
        SyncWork.active=new SyncRunner(c,root,policy,()->false);SyncWork.active.cancelled=true;
        fresh=SyncWork.retry(c);assert !fresh.equals(root) : "new edit joined a stopped runner before Android rescheduled it";
        SyncWork.active=null;
        reset();root=request(false,false);run(root);info(root).state=WorkInfo.State.RUNNING;
        SyncWork.active=new SyncRunner(c,root,policy,()->false);SyncWork.active.accepting=false;
        db.put(c.owner,"edit","saved just after completion");fresh=SyncWork.retry(c);
        assert !fresh.equals(root) : "new upload joined the runner after its last outbox check";
        SyncWork.active=null;run(fresh);assert db.next(c.owner)==null;
        reset();root=request(false,false);SyncRunner.error="retry";run(root);c.network="offline";
        assert !SyncWork.status(c,root).getBoolean("retryable");
        db.put("","policy",new JSONObject(policy.toString()).put("paused",true).toString());
        try{SyncWork.retry(c);throw new AssertionError("retry bypassed pause");}catch(IllegalStateException expected){}

        // A crash after replacement is enqueued still leaves the fresh request runnable.
        reset();root=request(false,false);SyncRunner.error="retry";run(root);wm.crash="after-enqueue";
        try{SyncWork.retry(c);throw new AssertionError("retry crash not reached");}catch(ProcessDeath expected){}
        wm.crash="";fresh=request(false,false);assert !fresh.equals(root);
        SyncRunner.error="";run(fresh);assert SyncWork.status(c,fresh).getBoolean("finished");

        // A new phone edit interrupts the low-priority vault at its next safe checkpoint, without backoff.
        reset();root=request(false,false);SyncRunner.priorityEdits=1;
        db.put(c.owner,"vault-state","saved vault checkpoint");
        assert run(root).kind.equals("success");
        String urgent=next(root);
        assert db.work(root).getString("yield").equals("uploads");
        assert info(urgent).initialDelay==0 && info(urgent).attempts==0;
        assert db.next(c.owner)!=null && db.get(c.owner,"vault-state").equals("saved vault checkpoint");
        noDone(root);run(urgent);
        assert db.next(c.owner)==null && SyncWork.status(c,root).getString("outcome").equals("idle");

        reset();root=request(false,false);String explicit=request(true,true);SyncRunner.budgets=1;
        run(root);String child=next(root);
        assert wm.parents.get(UUID.fromString(child)).equals(UUID.fromString(explicit));
        SyncRunner.error="permission";assert run(explicit).kind.equals("success");
        assert SyncWork.status(c,explicit).getString("outcome").equals("permission");
        SyncRunner.error="";run(child);
        assert SyncWork.status(c,root).getString("outcome").equals("idle");
        assert SyncWork.status(c,explicit).getString("outcome").equals("permission");

        // Periodic work (including an old untagged periodic job) joins without running or backing off.
        reset();root=request(false,false);
        OneTimeWorkRequest periodic=new OneTimeWorkRequest.Builder(SyncWork.class).build();
        wm.enqueueUniqueWork("brainamon-sync-periodic",ExistingWorkPolicy.APPEND_OR_REPLACE,periodic);
        assert run(periodic.id.toString()).kind.equals("success");assert SyncRunner.calls==0;assert wm.jobs.size()==2;

        // The lock is held by another writer; no failure backoff and no overlapping runner.
        reset();root=request(false,false);CountDownLatch acquired=new CountDownLatch(1),release=new CountDownLatch(1);
        Thread holder=new Thread(()->{SyncWork.ROUND.lock();try{acquired.countDown();release.await();}catch(Exception e){throw new RuntimeException(e);}finally{SyncWork.ROUND.unlock();}});
        holder.start();acquired.await();
        try{assert run(root).kind.equals("success");assert SyncRunner.calls==0;assert info(root).attempts==0;assert db.work(root).has("next");assert info(next(root)).initialDelay==5;assert db.work(root).getString("yield").equals("contention");}
        finally{release.countDown();holder.join();}
        run(next(root));assert SyncRunner.calls==1;

        for(String change:new String[]{"generation","account","pause","stop"}){
            reset();root=request(true,true);SyncRunner.budgets=1;run(root);child=next(root);
            if(change.equals("generation"))db.put("","policy",new JSONObject(policy.toString()).put("generation",2).toString());
            if(change.equals("account"))c.owner="account-b";
            if(change.equals("pause"))db.put("","policy",new JSONObject(policy.toString()).put("paused",true).toString());
            if(change.equals("stop")){
                SyncWork stopped=new SyncWork(c,new WorkerParameters(info(child).id,info(child).input));stopped.stopped=true;
                stopped.doWork();assert !db.work(child).has("next");
            }else{
                run(child);assert SyncWork.status(c,root).getString("outcome").equals("paused");
            }
            assert SyncRunner.calls==1 : "stale continuation performed I/O";
        }

        reset();root=request(false,false);SyncRunner.lateEdit=true;run(root);child=next(root);noDone(root);
        assert db.next("account-a")!=null : "handoff acknowledged a queued edit";
        SyncRunner.lateEdit=false;run(child);assert db.next("account-a")==null;
        assert SyncWork.status(c,root).getBoolean("finished");

        // A different active request cannot hide a saved completion or make a chunk look complete.
        reset();root=request(false,false);SyncRunner.budgets=1;run(root);child=next(root);
        String countsSlot=SyncRunner.stateName("vault-counts",policy);
        db.put(c.owner,countsSlot,new JSONObject().put("done",7).put("total",13).toString());
        SyncWork.active=new SyncRunner(c,UUID.randomUUID().toString(),policy,()->false);
        db.put("","status",new JSONObject().put("id",SyncWork.active.id).put("state","syncing").toString());
        JSONObject observed=SyncWork.status(c,root);
        assert observed.getString("state").equals("syncing") && !observed.getBoolean("finished");
        assert observed.getJSONObject("vaultFiles").optLong("done")==7;
        SyncWork.active=null;observed=SyncWork.status(c,root);
        assert observed.getString("state").equals("queued") && observed.getBoolean("scheduled");
        assert observed.getJSONObject("vaultFiles").optLong("done")==7;
        c.owner="account-b";assert SyncWork.status(c,root).isNull("vaultFiles");

        // Production checkpoint ordering: lifecycle/account/network changes beat an expired budget.
        reset();SyncRunner r=new SyncRunner(c,"checkpoint",policy,()->false);r.deadline=0;
        try{r.checkpoint();throw new AssertionError();}catch(SyncRunner.BudgetExpired expected){}
        r.checkpoint(false);
        r.cancelled=true;try{r.checkpoint();throw new AssertionError();}catch(SyncRunner.Cancelled expected){}r.cancelled=false;
        c.owner="account-b";try{r.checkpoint();throw new AssertionError();}catch(SyncRunner.Cancelled expected){}c.owner="account-a";
        db.put("","policy",new JSONObject(policy.toString()).put("generation",2).toString());
        try{r.checkpoint();throw new AssertionError();}catch(SyncRunner.Cancelled expected){}
        db.put("","policy",policy.toString());c.network="offline";
        try{r.checkpoint();throw new AssertionError();}catch(IOException expected){assert expected.getMessage().equals("offline");}
        System.out.println("scheduler checks passed");
    }
}

// Test doubles model committed rows and WorkManager dependencies; they never touch Android/user data.
class ProcessDeath extends Error {}
class Clock { static long now; }
class Context { String owner="account-a",network=""; }
class Build { static class VERSION { static int SDK_INT=34; } }
class Constraints { boolean wifi;Constraints(boolean wifi){this.wifi=wifi;} }
enum BackoffPolicy { EXPONENTIAL,LINEAR }
enum OutOfQuotaPolicy { RUN_AS_NON_EXPEDITED_WORK_REQUEST }
enum ExistingWorkPolicy { APPEND_OR_REPLACE, REPLACE }
enum ExistingPeriodicWorkPolicy { UPDATE }
class Data {
    Map<String,Object> values=new HashMap<>();
    boolean getBoolean(String k,boolean d){return (boolean)values.getOrDefault(k,d);}
    long getLong(String k,long d){return ((Number)values.getOrDefault(k,d)).longValue();}
    String getString(String k){return (String)values.get(k);}
    static class Builder { Data d=new Data();Builder putBoolean(String k,boolean v){d.values.put(k,v);return this;}Builder putLong(String k,long v){d.values.put(k,v);return this;}Builder putString(String k,String v){d.values.put(k,v);return this;}Data build(){return d;} }
}
class WorkerParameters {UUID id;Data data;WorkerParameters(UUID id,Data data){this.id=id;this.data=data;} }
class Worker {
    Context c;WorkerParameters p;boolean stopped;
    Worker(Context c,WorkerParameters p){this.c=c;this.p=p;}
    Context getApplicationContext(){return c;}UUID getId(){return p.id;}Data getInputData(){return p.data;}boolean isStopped(){return stopped;}
    public void onStopped(){}
    static class Result {String kind;Data output;Result(String k,Data d){kind=k;output=d;}static Result retry(){return new Result("retry",new Data());}static Result success(){return success(new Data());}static Result success(Data d){return new Result("success",d);} }
}
class OneTimeWorkRequest {
    UUID id=UUID.randomUUID();Data data=new Data();Constraints constraints;BackoffPolicy backoff;long seconds,initialDelay;
    UUID getId(){return id;}
    static class Builder {
        OneTimeWorkRequest r=new OneTimeWorkRequest();Builder(Class<?> c){}Builder setId(UUID id){r.id=id;return this;}Builder setConstraints(Constraints c){r.constraints=c;return this;}
        Builder setInputData(Data d){r.data=d;return this;}Builder setBackoffCriteria(BackoffPolicy b,long n,TimeUnit u){r.backoff=b;r.seconds=u.toSeconds(n);return this;}
        Builder setInitialDelay(long n,TimeUnit u){r.initialDelay=u.toSeconds(n);return this;}
        Builder setExpedited(OutOfQuotaPolicy p){return this;}OneTimeWorkRequest build(){return r;}
    }
}
class PeriodicWorkRequest {
    static class Builder {Builder(Class<?> c,long n,TimeUnit u){}Builder setInitialDelay(long n,TimeUnit u){return this;}Builder setConstraints(Constraints c){return this;}Builder setInputData(Data d){return this;}Builder setBackoffCriteria(BackoffPolicy b,long n,TimeUnit u){return this;}PeriodicWorkRequest build(){return new PeriodicWorkRequest();} }
}
class WorkInfo {
    enum State { ENQUEUED,BLOCKED,RUNNING,SUCCEEDED,FAILED,CANCELLED;boolean isFinished(){return this==SUCCEEDED||this==FAILED||this==CANCELLED;} }
    UUID id;State state=State.ENQUEUED;Data input,output=new Data();int attempts;Constraints constraints;BackoffPolicy backoff;long backoffSeconds,initialDelay,nextAt;
    WorkInfo(OneTimeWorkRequest r){id=r.id;input=r.data;constraints=r.constraints;backoff=r.backoff;backoffSeconds=r.seconds;initialDelay=r.initialDelay;}
    UUID getId(){return id;}State getState(){return state;}Data getOutputData(){return output;}
    int getRunAttemptCount(){return attempts;}long getNextScheduleTimeMillis(){return nextAt;}
}
class Operation {CompletableFuture<Void> getResult(){return CompletableFuture.completedFuture(null);} }
class WorkManager {
    static WorkManager instance=new WorkManager();static WorkManager getInstance(Context c){return instance;}
    Map<UUID,WorkInfo> jobs=new LinkedHashMap<>();Map<String,List<UUID>> names=new HashMap<>();Map<UUID,UUID> parents=new HashMap<>();String crash="";
    CompletableFuture<List<WorkInfo>> getWorkInfosForUniqueWork(String name){List<WorkInfo> out=new ArrayList<>();for(UUID id:names.getOrDefault(name,List.of()))out.add(jobs.get(id));return CompletableFuture.completedFuture(out);}
    CompletableFuture<WorkInfo> getWorkInfoById(UUID id){return CompletableFuture.completedFuture(jobs.get(id));}
    Operation enqueueUniqueWork(String name,ExistingWorkPolicy p,OneTimeWorkRequest r){
        if(crash.equals("before-enqueue"))throw new ProcessDeath();
        if(jobs.containsKey(r.id))throw new AssertionError("duplicate durable work ID");
        List<UUID> chain=names.computeIfAbsent(name,k->new ArrayList<>());WorkInfo info=new WorkInfo(r);
        if(p==ExistingWorkPolicy.REPLACE){for(UUID prior:chain)if(!jobs.get(prior).state.isFinished())jobs.get(prior).state=WorkInfo.State.CANCELLED;chain.clear();}
        if(!chain.isEmpty()){UUID prior=chain.get(chain.size()-1);parents.put(r.id,prior);if(!jobs.get(prior).state.isFinished())info.state=WorkInfo.State.BLOCKED;}
        jobs.put(r.id,info);chain.add(r.id);
        if(crash.equals("after-enqueue"))throw new ProcessDeath();return new Operation();
    }
    Operation enqueueUniquePeriodicWork(String n,ExistingPeriodicWorkPolicy p,PeriodicWorkRequest r){return new Operation();}
    Operation cancelUniqueWork(String name){for(UUID id:names.getOrDefault(name,List.of()))jobs.get(id).state=WorkInfo.State.CANCELLED;return new Operation();}
}
class JSONObject {
    static final Object NULL=new Object();static Map<String,Map<String,Object>> snapshots=new HashMap<>();Map<String,Object> values=new HashMap<>();
    JSONObject(){}JSONObject(String s){values.putAll(Objects.requireNonNull(snapshots.get(s),s));}
    JSONObject put(String k,Object v){if(v==null)values.remove(k);else values.put(k,v);return this;}Object get(String k){return values.get(k);}void remove(String k){values.remove(k);}boolean has(String k){return values.containsKey(k);}
    String getString(String k){return (String)Objects.requireNonNull(values.get(k),k);}String optString(String k){return optString(k,"");}String optString(String k,String d){return (String)values.getOrDefault(k,d);}
    boolean optBoolean(String k){return optBoolean(k,false);}boolean optBoolean(String k,boolean d){return (boolean)values.getOrDefault(k,d);}boolean getBoolean(String k){return (boolean)values.get(k);}
    long optLong(String k){return ((Number)values.getOrDefault(k,0)).longValue();}long getLong(String k){return ((Number)values.get(k)).longValue();}double optDouble(String k){return ((Number)values.getOrDefault(k,0)).doubleValue();}
    JSONObject optJSONObject(String k){return (JSONObject)values.get(k);}JSONObject getJSONObject(String k){return (JSONObject)values.get(k);}boolean isNull(String k){return !has(k)||values.get(k)==NULL;}
    public String toString(){String id=UUID.randomUUID().toString();snapshots.put(id,new HashMap<>(values));return id;}
}
class SyncStore implements AutoCloseable {
    static Map<String,String> rows=new HashMap<>();static int crashAfterWork,workWrites;SyncStore(Context c){}public void close(){}
    String get(String scope,String name){return rows.get(scope+"/"+name);}void put(String scope,String name,String value){rows.put(scope+"/"+name,value);}
    JSONObject work(String id){String value=get("","work/"+id);return value==null?null:new JSONObject(value);}void work(String id,JSONObject value){put("","work/"+id,value.toString());if(++workWrites==crashAfterWork)throw new ProcessDeath();}
    JSONObject next(String scope){return get(scope,"edit")==null?null:new JSONObject().put("name","queued-edit");}
    boolean hasPending(String scope){return next(scope)!=null;}
}
class SyncKey {static byte[] utf(String s){return s.getBytes(java.nio.charset.StandardCharsets.UTF_8);} }
class PhoneSecrets {static String get(Context c,String name){return c.owner;}static String stored(Context c,String name){return c.owner;} }
class SyncRunner implements AutoCloseable {
    /* CHECKPOINTS */
    String id,scope,savedPair;Context context;JSONObject policy;SyncStore store;long deadline=Long.MAX_VALUE;
    boolean accepting=true,cancelled,prioritizeUploads;java.util.function.BooleanSupplier stopped;
    static int calls,budgets,priorityEdits;static String error="";static boolean lateEdit;
    SyncRunner(Context c,String id,JSONObject p,java.util.function.BooleanSupplier stop)throws Exception {context=c;this.id=id;policy=p;scope=c.owner;savedPair=c.owner;store=new SyncStore(c);stopped=stop;}
    static JSONObject pair(Context c)throws IOException{if(c.owner==null)throw new IOException("auth");return new JSONObject().put("owner",c.owner);}
    static String scope(JSONObject p,String device){return p.getString("owner");}
    static String stateName(String name,JSONObject p){return name+"/"+p.optString("uri");}
    void timed(String name,long at){}
    JSONObject run(boolean force,boolean legacy)throws Exception {
        calls++;checkpoint();store.put("","status",new JSONObject().put("id",id).put("state","syncing").put("libraryReady",true).toString());
        if(!error.isEmpty())throw new IOException(error);
        if(priorityEdits-->0){prioritizeUploads=true;store.put(scope,"edit","new phone change during vault sync");checkpoint();}
        if(budgets-->0){deadline=Clock.now;checkpoint();}
        if(lateEdit)store.put(scope,"edit","saved");else SyncStore.rows.remove(scope+"/edit");
        return new JSONObject();
    }
    void cancel(){cancelled=true;}public void close(){cancel();}
}
