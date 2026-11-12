package app.brainamon.mobile;

import android.app.Instrumentation;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.SharedPreferences;
import android.database.DatabaseErrorHandler;
import android.database.sqlite.SQLiteDatabase;
import android.os.Bundle;
import android.provider.DocumentsContract;
import androidx.work.*;
import org.json.JSONObject;
import java.io.File;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/** Explicit adb instrumentation only; never registered in a release or invoked by normal startup. */
public final class SyncProbe extends Instrumentation {
    private Bundle args;
    static final String WORK="brainamon-sync-fixture", PERIOD="brainamon-sync-fixture-periodic";
    static class Isolated extends ContextWrapper {
        Isolated(Context c){super(c);}
        public SharedPreferences getSharedPreferences(String n,int mode){return super.getSharedPreferences("sync-fixture-"+n,mode);}
        public SQLiteDatabase openOrCreateDatabase(String n,int mode,SQLiteDatabase.CursorFactory f){return super.openOrCreateDatabase("sync-fixture-"+n,mode,f);}
        public SQLiteDatabase openOrCreateDatabase(String n,int mode,SQLiteDatabase.CursorFactory f,DatabaseErrorHandler h){return super.openOrCreateDatabase("sync-fixture-"+n,mode,f,h);}
        public File getDatabasePath(String n){return super.getDatabasePath("sync-fixture-"+n);}
        public File getNoBackupFilesDir(){File f=new File(super.getNoBackupFilesDir(),"sync-fixture");f.mkdirs();return f;}
    }
    public void onCreate(Bundle args){this.args=args;start();}
    static JSONObject fixture(String path)throws Exception {
        HttpURLConnection c=(HttpURLConnection)new URL("http://127.0.0.1:18876"+path).openConnection();c.setConnectTimeout(5000);c.setReadTimeout(5000);
        try(java.io.InputStream in=c.getInputStream()){return new JSONObject(new String(SyncFiles.bytes(in,100000),StandardCharsets.UTF_8));}finally{c.disconnect();}
    }
    public void onStart(){Bundle result=execute(getTargetContext(),args);finish(result.containsKey("error")?1:0,result);}
    static Bundle execute(Context target,Bundle args){Bundle result=new Bundle();
        try{
            Context c=new Isolated(target);String cmd=args.getString("command","status");WorkManager wm=WorkManager.getInstance(target);
            try(SyncStore db=new SyncStore(c)){
                if(cmd.equals("provider-safety")){
                    result.putString("provider",SyncProviderProbe.safety(target,args.getString("revoke","false").equals("true")).toString());
                }else if(cmd.equals("provider-scale")){
                    result.putString("provider",SyncProviderProbe.run(target,args.getString("size","1500")).toString());
                }else if(cmd.equals("init")){
                    JSONObject f=fixture("/fixture"),p=f.getJSONObject("pair");PhoneSecrets.set(c,"bp-pair",p.toString());
                    JSONObject policy=new JSONObject().put("enabled",true).put("paused",false).put("blocked",false).put("wifiOnly",true).put("device","p0000000001").put("vault",true)
                        .put("uri",DocumentsContract.buildTreeDocumentUri(target.getPackageName()+".syncfixture","root").toString()).put("generation",1);
                    db.put("","policy",policy.toString());
                    target.grantUriPermission(target.getPackageName(),android.net.Uri.parse(policy.getString("uri")),
                        android.content.Intent.FLAG_GRANT_READ_URI_PERMISSION|android.content.Intent.FLAG_GRANT_WRITE_URI_PERMISSION|android.content.Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION|android.content.Intent.FLAG_GRANT_PREFIX_URI_PERMISSION);
                    target.getContentResolver().takePersistableUriPermission(android.net.Uri.parse(policy.getString("uri")),3);
                    File note=new File(SyncProbeDocuments.root(target),"phone.md");if(!note.exists())try(java.io.FileOutputStream out=new java.io.FileOutputStream(note)){out.write(SyncKey.utf("Fixture phone note"));}
                }else if(cmd.equals("lifecycle")){
                    String saved=db.get("","policy"),status=db.get("","status");
                    JSONObject p=new JSONObject(saved);p.put("paused",false).put("enabled",true).put("blocked",false).put("wifiOnly",false);
                    db.put("","policy",p.toString());
                    java.util.concurrent.atomic.AtomicBoolean stopped=new java.util.concurrent.atomic.AtomicBoolean();
                    try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,stopped::get)){
                        stopped.set(true);expectCheckpoint(r,"paused");stopped.set(false);
                        r.cancel();expectCheckpoint(r,"paused");r.cancelled=false;
                        JSONObject changed=new JSONObject(p.toString()).put("generation",p.optLong("generation")+1);
                        db.put("","policy",changed.toString());expectCheckpoint(r,"paused");
                        db.put("","policy",new JSONObject(p.toString()).put("blocked",true).toString());expectCheckpoint(r,"paused");
                        db.put("","policy",new JSONObject(p.toString()).put("paused",true).toString());
                        stopped.set(true);expectCheckpoint(r,"paused");
                        db.put("","policy",p.toString());db.put("","status",new JSONObject().put("state","paused").toString());
                        JSONObject current=SyncWork.status(c,"");
                        if(current.getBoolean("paused") || current.getString("state").equals("paused"))throw new AssertionError("Stale pause survived resume");
                        stopped.set(false);
                        try(SyncRunner budget=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,stopped::get,0)){
                            try{budget.checkpoint();throw new AssertionError("Budget accepted");}catch(SyncRunner.BudgetExpired expected){}
                            budget.checkpoint(false);
                            stopped.set(true);
                            try{budget.checkpoint();throw new AssertionError("Stopped budget continued");}catch(SyncRunner.Cancelled expected){}
                        }
                        result.putString("lifecycleChecks","budget, system stop, cancellation, generation, blocked, manual pause and stale status passed");
                    }finally{db.put("","policy",saved);if(status==null)db.remove("","status");else db.put("","status",status);}
                }else if(cmd.equals("checkpoint-scale")){
                    String saved=db.get("","policy"),secret=PhoneSecrets.get(c,"bp-pair");
                    JSONObject p=new JSONObject(saved).put("paused",false).put("enabled",true).put("blocked",false).put("wifiOnly",false);
                    db.put("","policy",p.toString());
                    try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,()->false)){
                        long at=android.os.SystemClock.elapsedRealtime();
                        for(int i=0;i<250;i++)try{r.checkpoint();}catch(java.io.IOException e){if(!"offline".equals(e.getMessage()))throw e;}
                        result.putLong("checkpointMs",android.os.SystemClock.elapsedRealtime()-at);
                        PhoneSecrets.set(c,"bp-pair",new JSONObject(secret).put("g","changed@example.invalid").put("e","changed@example.invalid").toString());expectCheckpoint(r,"paused");
                        PhoneSecrets.set(c,"bp-pair",new JSONObject(secret).put("backupTask",new JSONObject()).toString());expectCheckpoint(r,"auth");
                        PhoneSecrets.set(c,"bp-pair",null);expectCheckpoint(r,"auth");
                        c.getSharedPreferences("brainamon-secrets",Context.MODE_PRIVATE).edit().putString("bp-pair","broken").commit();
                        try{r.checkpoint();throw new AssertionError("Corrupt protected pairing accepted");}catch(IllegalStateException expected){}
                        PhoneSecrets.set(c,"bp-pair",new JSONObject(secret).put("fixture",true).toString());
                        try{r.checkpoint();}catch(java.io.IOException e){if(!"offline".equals(e.getMessage()))throw e;}
                        result.putString("identityChecks","account change, management task, removal and corrupt pairing refused; valid metadata accepted");
                    }finally{PhoneSecrets.set(c,"bp-pair",secret);db.put("","policy",saved);}
                }else if(cmd.equals("saf-write-scale")){
                    JSONObject pair=SyncRunner.pair(c);SyncKey key=new SyncKey(android.util.Base64.decode(pair.getString("k"),android.util.Base64.URL_SAFE));
                    SyncFiles fs=new SyncFiles(c,SyncWork.policy(c).getString("uri"),key);
                    String name="write-scale-"+java.util.UUID.randomUUID();File dir=new File(SyncProbeDocuments.root(target),name);
                    if(!dir.mkdir())throw new AssertionError("Cannot create isolated write fixture");
                    byte[] original=SyncKey.utf("Synthetic original"),next=SyncKey.utf("Synthetic replacement");
                    try{
                        for(int i=0;i<1500;i++)try(java.io.FileOutputStream out=new java.io.FileOutputStream(new File(dir,"note-"+i+".md"))){out.write(original);}
                        long at=android.os.SystemClock.elapsedRealtime();fs.has(name+"/note-0.md");result.putLong("coldLookupMs",android.os.SystemClock.elapsedRealtime()-at);
                        at=android.os.SystemClock.elapsedRealtime();
                        for(int i=0;i<2;i++)fs.write(name+"/new-"+i+".md",next,null,true);
                        result.putLong("createTwoMs",android.os.SystemClock.elapsedRealtime()-at);
                        at=android.os.SystemClock.elapsedRealtime();
                        for(int i=0;i<2;i++)fs.write(name+"/note-"+i+".md",next,key.contentId(original),true);
                        result.putLong("replaceTwoMs",android.os.SystemClock.elapsedRealtime()-at);
                        if(!java.util.Arrays.equals(fs.read(name+"/note-0.md"),next))throw new AssertionError("Replacement bytes differ");
                        result.putString("writeScaleChecks","1500 siblings, safe create and replacement verified");
                    }finally{File[] all=dir.listFiles();if(all!=null)for(File f:all)if(!f.delete())throw new AssertionError("Write fixture cleanup failed");if(!dir.delete())throw new AssertionError("Write fixture folder cleanup failed");}
                }else if(cmd.equals("active-status")){
                    String saved=db.get("","policy"),status=db.get("","status");
                    JSONObject p=new JSONObject(saved).put("paused",false).put("enabled",true).put("blocked",false).put("wifiOnly",false);
                    OneTimeWorkRequest waiting=new OneTimeWorkRequest.Builder(SyncWork.class).setInitialDelay(1,TimeUnit.HOURS).build();
                    if(SyncWork.active!=null)throw new AssertionError("Unexpected active Contributor runner");
                    db.put("","policy",p.toString());
                    try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,()->false)){
                        if(!SyncWork.network(c,p).isEmpty())throw new AssertionError("Status fixture requires network");
                        wm.enqueue(waiting).getResult().get(10,TimeUnit.SECONDS);
                        SyncWork.active=r;
                        db.put("","status",new JSONObject().put("id",r.id).put("state","syncing").put("phase","vault").toString());
                        JSONObject observed=SyncWork.status(c,waiting.getId().toString());
                        if(!observed.getString("state").equals("syncing") || !observed.getString("id").equals(r.id))throw new AssertionError("Queued observer hid active worker");
                        if(observed.getBoolean("finished") || !observed.getBoolean("scheduled"))throw new AssertionError("Observed request completion changed");
                        SyncWork.active=null;
                        if(!SyncWork.status(c,waiting.getId().toString()).getString("state").equals("queued"))throw new AssertionError("Inactive request appeared running");
                        result.putString("activeStatusChecks","active worker visible while another request waits; inactive request remains queued");
                    }finally{
                        SyncWork.active=null;wm.cancelWorkById(waiting.getId()).getResult().get(10,TimeUnit.SECONDS);
                        db.put("","policy",saved);if(status==null)db.remove("","status");else db.put("","status",status);
                    }
                }else if(cmd.equals("counts")){
                    String saved=db.get("","policy"),status=db.get("","status"),secret=PhoneSecrets.get(c,"bp-pair");
                    JSONObject p=new JSONObject(saved).put("paused",false).put("enabled",true).put("blocked",false).put("wifiOnly",false);
                    String scope=SyncRunner.scope(SyncRunner.pair(c),p.getString("device")),slot=SyncRunner.stateName("vault-counts",p),prior=db.get(scope,slot);
                    db.put("","policy",p.toString());
                    try {
                        try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,()->false)){
                            r.dispatch("progress",new org.json.JSONArray().put("vault").put(.63).put(new JSONObject().put("key","backup.vault.step.taking")
                                .put("done",2).put("total",8).put("files",new JSONObject().put("done",7).put("total",13))));
                        }
                        SyncWork.report(c,"retry",0);
                        JSONObject counts=SyncWork.status(c,"").getJSONObject("vaultFiles");
                        if(counts.getInt("done")!=7 || counts.getInt("total")!=13)throw new AssertionError("Counts lost after runner close/retry");
                        db.put("","policy",new JSONObject(p.toString()).put("uri","content://different-folder").toString());
                        if(!SyncWork.status(c,"").isNull("vaultFiles"))throw new AssertionError("Counts leaked across folders");
                        db.put("","policy",p.toString());
                        PhoneSecrets.set(c,"bp-pair",new JSONObject(secret).put("g","changed@example.invalid").put("e","changed@example.invalid").toString());
                        if(!SyncWork.status(c,"").isNull("vaultFiles"))throw new AssertionError("Counts leaked across accounts");
                        PhoneSecrets.set(c,"bp-pair",null);
                        if(!SyncWork.status(c,"").isNull("vaultFiles"))throw new AssertionError("Counts remained after unpairing");
                        result.putString("countChecks","durable counts after close/retry; account, folder and unpair isolation passed");
                    }finally{
                        PhoneSecrets.set(c,"bp-pair",secret);db.put("","policy",saved);
                        if(status==null)db.remove("","status");else db.put("","status",status);
                        if(prior==null)db.remove(scope,slot);else db.put(scope,slot,prior);
                    }
                }else if(cmd.equals("http-batch")){
                    String saved=db.get("","policy");
                    JSONObject p=new JSONObject(saved).put("paused",false).put("enabled",true).put("blocked",false).put("wifiOnly",false);
                    db.put("","policy",p.toString());
                    java.util.concurrent.atomic.AtomicInteger renewals=new java.util.concurrent.atomic.AtomicInteger();
                    try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),p,()->false){
                        protected String endpoint(){return "http://127.0.0.1:18877";}
                        protected void clearToken(){}
                        protected void renew(){renewals.incrementAndGet();token="fixture";}
                    }){
                        r.token="fixture";r.dispatch("authorized",new org.json.JSONArray().put(System.currentTimeMillis()/1000.0+3600));
                        org.json.JSONArray calls=new org.json.JSONArray();
                        for(int i=0;i<8;i++)calls.put(new JSONObject().put("method","get").put("args",new org.json.JSONArray().put("probe-"+i)));
                        long at=android.os.SystemClock.elapsedRealtime();
                        for(int i=0;i<8;i++)verifyReply(r.getBytes(calls.getJSONObject(i).getJSONArray("args")));
                        long serial=android.os.SystemClock.elapsedRealtime()-at;result.putLong("serialMs",serial);
                        at=android.os.SystemClock.elapsedRealtime();
                        java.util.Map<Integer,java.util.concurrent.Future<byte[]>> reads=r.readCalls(calls);
                        for(java.util.concurrent.Future<byte[]> f:reads.values())verifyReply(f.get(20,TimeUnit.SECONDS));
                        long parallel=android.os.SystemClock.elapsedRealtime()-at;result.putLong("parallelMs",parallel);
                        if(parallel>=serial*0.65)throw new AssertionError("Native reads remain serialized");
                        calls.put(calls.getJSONObject(0));reads=r.readCalls(calls);
                        if(reads.get(0)!=reads.get(8))throw new AssertionError("Duplicate reads share a resumable slot concurrently");
                        for(java.util.concurrent.Future<byte[]> f:reads.values())verifyReply(f.get(20,TimeUnit.SECONDS));
                        r.token="expired-fixture";reads=r.readCalls(calls);
                        for(java.util.concurrent.Future<byte[]> f:reads.values())verifyReply(f.get(20,TimeUnit.SECONDS));
                        if(renewals.get()!=1)throw new AssertionError("Concurrent token renewals: "+renewals.get());
                        reads=r.readCalls(calls);Thread.sleep(150);r.cancel();
                        for(java.util.concurrent.Future<byte[]> f:reads.values()) {
                            try{f.get(20,TimeUnit.SECONDS);throw new AssertionError("Cancelled download succeeded");}
                            catch(java.util.concurrent.ExecutionException expected){}
                        }
                        result.putString("httpChecks","four read workers, identical bytes, coalesced duplicates/401, cancellation passed");
                    }finally{db.put("","policy",saved);}
                }else if(cmd.equals("http-reuse")){
                    try(SyncRunner r=new SyncRunner(c,java.util.UUID.randomUUID().toString(),SyncWork.policy(c),()->false){
                        protected String endpoint(){return "http://127.0.0.1:18877";}
                        protected void renew(){token="fixture";}
                    }){
                        java.lang.reflect.Method http=SyncRunner.class.getDeclaredMethod("http",String.class,String.class,byte[].class,String.class,int.class,boolean.class);
                        http.setAccessible(true);
                        for(int i=0;i<4;i++){
                            byte[] bytes=(byte[])http.invoke(r,"GET","/probe",null,null,20000,false);
                            if(!new JSONObject(new String(bytes,StandardCharsets.UTF_8)).getBoolean("ok"))throw new AssertionError("HTTP fixture response mismatch");
                        }
                        r.cancel();
                        try{http.invoke(r,"GET","/probe",null,null,20000,false);throw new AssertionError("Cancelled HTTP call ran");}
                        catch(java.lang.reflect.InvocationTargetException expected){if(!"paused".equals(expected.getCause().getMessage()))throw expected;}
                        result.putString("httpChecks","four requests completed; cancellation refused a fifth");
                    }
                }else if(cmd.equals("saf-scale")){
                    JSONObject pair=SyncRunner.pair(c);
                    SyncKey key=new SyncKey(android.util.Base64.decode(pair.getString("k"),android.util.Base64.URL_SAFE));
                    SyncFiles fs=new SyncFiles(c,SyncWork.policy(c).getString("uri"),key);
                    String name="scale-"+java.util.UUID.randomUUID();
                    File dir=new File(SyncProbeDocuments.root(target),name);
                    if(!dir.mkdir())throw new AssertionError("Cannot create isolated scale fixture");
                    try{
                        for(int i=0;i<256;i++)try(java.io.FileOutputStream out=new java.io.FileOutputStream(new File(dir,"note-"+i+".md"))){out.write(SyncKey.utf("Synthetic scale note"));}
                        long started=android.os.SystemClock.elapsedRealtime();
                        for(int i=0;i<16;i++)if(!fs.has(name+"/note-0.md"))throw new AssertionError("Scale note missing");
                        result.putLong("refreshMs",android.os.SystemClock.elapsedRealtime()-started);
                        if(!new File(dir,"note-0.md").renameTo(new File(dir,"renamed.md")) || fs.has(name+"/note-0.md") || !fs.has(name+"/renamed.md"))
                            throw new AssertionError("Fresh lookup retained a renamed document");
                        byte[] next=SyncKey.utf("Updated synthetic scale note");
                        fs.write(name+"/renamed.md",next,key.contentId(SyncKey.utf("Synthetic scale note")),true);
                        if(!java.util.Arrays.equals(fs.read(name+"/renamed.md"),next))throw new AssertionError("Scale replacement failed");
                        result.putString("scaleChecks","256 siblings, 16 fresh lookups, external rename and safe replacement passed");
                    }finally{File[] all=dir.listFiles();if(all!=null)for(File f:all)if(!f.delete())throw new AssertionError("Scale fixture cleanup failed");if(!dir.delete())throw new AssertionError("Scale folder cleanup failed");}
                }else if(cmd.equals("check")){
                    JSONObject pair=SyncRunner.pair(c);
                    SyncKey key=new SyncKey(android.util.Base64.decode(pair.getString("k"),android.util.Base64.URL_SAFE));
                    SyncFiles fs=new SyncFiles(c,SyncWork.policy(c).getString("uri"),key);
                    String name="fixture-concurrent.md";
                    File file=new File(SyncProbeDocuments.root(target),name);
                    byte[] original=SyncKey.utf("before scan"),edited=SyncKey.utf("edited in Obsidian");
                    try(java.io.FileOutputStream out=new java.io.FileOutputStream(file)){out.write(original);}
                    String expected=key.contentId(fs.read(name));
                    try(java.io.FileOutputStream out=new java.io.FileOutputStream(file)){out.write(edited);}
                    for(int action=0;action<3;action++){
                        boolean conflict=false;
                        try{if(action==2)fs.remove(name,expected);else fs.write(name,original,action==0?expected:null,true);}
                        catch(java.io.IOException e){conflict=e.getMessage().equals("conflict");}
                        if(!conflict || !java.util.Arrays.equals(fs.read(name),edited))throw new AssertionError("Concurrent vault edit was not preserved");
                    }
                    if(fs.has(name+".vsync-tmp"))throw new AssertionError("Conflict left a staged file");
                    fs.write(name,original,key.contentId(edited),true);
                    if(!java.util.Arrays.equals(fs.read(name),original))throw new AssertionError("Safe replacement failed");
                    fs.remove(name,key.contentId(original));
                    try{SyncFiles.path("../escape");throw new AssertionError("Traversal accepted");}catch(java.io.IOException expectedError){}
                    PhoneSecrets.set(c,"fixture-secret","kept");
                    if(!"kept".equals(PhoneSecrets.get(c,"fixture-secret")))throw new AssertionError("Secret did not round trip");
                    PhoneSecrets.set(c,"fixture-secret",null);
                    result.putString("checks","replace, concurrent edit, create collision, delete conflict, traversal, secrets: passed");
                }else if(cmd.equals("revoke-test-vault")){
                    android.net.Uri uri=android.net.Uri.parse(args.getString("uri",""));
                    String path=DocumentsContract.getTreeDocumentId(uri);
                    if(!"com.android.externalstorage.documents".equals(uri.getAuthority()) || !path.matches("primary:Documents/(?:[^/]+/)*Brainamon-Sync-Test-[0-9-]+"))
                        throw new IllegalArgumentException("Only an explicitly named sync test folder may be revoked");
                    target.getContentResolver().releasePersistableUriPermission(uri,3);
                    result.putString("revoked",uri.toString());
                }else if(cmd.equals("pause")||cmd.equals("resume")){
                    JSONObject p=SyncWork.policy(c);p.put("paused",cmd.equals("pause")).put("generation",p.optLong("generation")+1);db.put("","policy",p.toString());
                }else if(cmd.equals("queue")){
                    JSONObject pair=SyncRunner.pair(c);SyncKey key=new SyncKey(android.util.Base64.decode(pair.getString("k"),android.util.Base64.URL_SAFE));
                    String scope=SyncRunner.scope(pair,"p0000000001");int count=Integer.parseInt(args.getString("count","64")),size=Integer.parseInt(args.getString("size","65536"));
                    if(count<1||count>1000||size<1||size>5*1024*1024)throw new IllegalArgumentException("Fixture size");
                    char[] text=new char[size];java.util.Arrays.fill(text,'x');long at=System.currentTimeMillis();
                    for(int i=0;i<count;i++){
                        JSONObject doc=new JSONObject().put("format",1).put("device","p0000000001").put("at",at+i)
                            .put("changes",new org.json.JSONArray().put(new JSONObject().put("op","note").put("body",new String(text))));
                        String id=SyncKey.hex(SyncKey.hash(SyncKey.utf("p0000000001\n"+(at+i)+"\n\n\n"))),name="chg-"+java.util.UUID.randomUUID().toString().replace("-","");
                        db.stage(scope,id,name,android.util.Base64.encodeToString(key.seal(name,SyncKey.utf(doc.toString())),android.util.Base64.NO_WRAP));
                    }
                }else if(cmd.equals("start")){
                    OneTimeWorkRequest.Builder builder=new OneTimeWorkRequest.Builder(ProbeWorker.class).setConstraints(SyncWork.constraints(SyncWork.policy(c))).setBackoffCriteria(BackoffPolicy.EXPONENTIAL,30,TimeUnit.SECONDS);
                    if(android.os.Build.VERSION.SDK_INT>=31)builder.setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST);
                    OneTimeWorkRequest work=builder.build();
                    wm.enqueueUniqueWork(WORK,ExistingWorkPolicy.KEEP,work).getResult().get(10,TimeUnit.SECONDS);result.putString("id",work.getId().toString());
                }else if(cmd.equals("periodic")){
                    PeriodicWorkRequest work=new PeriodicWorkRequest.Builder(ProbeWorker.class,15,TimeUnit.MINUTES).setInitialDelay(15,TimeUnit.MINUTES).setConstraints(SyncWork.constraints(SyncWork.policy(c))).build();
                    wm.enqueueUniquePeriodicWork(PERIOD,ExistingPeriodicWorkPolicy.KEEP,work).getResult().get(10,TimeUnit.SECONDS);
                }else if(cmd.equals("stop")){wm.cancelUniqueWork(WORK).getResult().get(10,TimeUnit.SECONDS);wm.cancelUniqueWork(PERIOD).getResult().get(10,TimeUnit.SECONDS);}
                result.putString("status",db.get("","status"));result.putString("supported",String.valueOf(SyncWork.supported()));
                result.putString("runs",db.get("","fixture-runs"));
            }
            return result;
        }catch(Exception e){result.putString("error",e.toString());return result;}
    }
    private static void expectCheckpoint(SyncRunner runner,String why)throws Exception {
        try{runner.checkpoint();throw new AssertionError("Checkpoint accepted "+why);}
        catch(java.io.IOException e){if(!why.equals(e.getMessage()))throw new AssertionError("Expected "+why+", got "+e.getMessage());}
    }
    private static void verifyReply(byte[] reply)throws Exception {
        if(!new JSONObject(new String(reply,StandardCharsets.UTF_8)).getBoolean("ok"))throw new AssertionError("HTTP fixture bytes");
    }
    public static final class ProbeWorker extends Worker {
        public ProbeWorker(Context c,WorkerParameters p){super(c,p);}
        public Result doWork(){Context c=new Isolated(getApplicationContext());
            if(!SyncWork.ROUND.tryLock())return Result.retry();
            try(SyncRunner r=new SyncRunner(c,getId().toString(),SyncWork.policy(c),this::isStopped){
                protected String endpoint(){return "http://127.0.0.1:18876";}
                protected void clearToken(){}
                protected void renew()throws Exception {if(fixture("/fixture/token").optBoolean("expired"))throw new java.io.IOException("auth");token="fixture";}
                Object dispatch(String method,org.json.JSONArray args)throws Exception{try{return super.dispatch(method,args);}catch(Exception e){android.util.Log.e("SyncProbe",method,e);throw e;}}
            }){
                JSONObject done=r.run(false,false);SyncWork.report(c,"idle",System.currentTimeMillis());
                try(SyncStore db=new SyncStore(c)){String count=db.get("","fixture-runs");db.put("","fixture-runs",String.valueOf(count==null?1:Integer.parseInt(count)+1));}
                return Result.success();
            }catch(Exception e){android.util.Log.e("SyncProbe","Fixture round",e);try{SyncWork.report(c,SyncRunner.reason(e),0);}catch(Exception ignored){}return Result.retry();}
            finally{SyncWork.ROUND.unlock();}
        }
    }
}
