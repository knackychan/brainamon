package app.brainamon.mobile;

import android.accounts.Account;
import android.content.Context;
import android.net.ConnectivityManager;
import android.net.Network;
import android.util.Base64;
import androidx.javascriptengine.JavaScriptSandbox;
import androidx.javascriptengine.JavaScriptIsolate;
import androidx.javascriptengine.IsolateStartupParameters;
import com.google.android.gms.auth.api.identity.AuthorizationRequest;
import com.google.android.gms.auth.api.identity.AuthorizationResult;
import com.google.android.gms.auth.api.identity.ClearTokenRequest;
import com.google.android.gms.auth.api.identity.Identity;
import com.google.android.gms.common.api.Scope;
import com.google.android.gms.tasks.Tasks;
import org.json.JSONArray;
import org.json.JSONObject;
import org.json.JSONTokener;
import java.io.*;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Collections;
import java.util.concurrent.TimeUnit;
import java.util.function.BooleanSupplier;
import java.util.zip.GZIPInputStream;

/** Native lifetime and I/O for the shipped shared sync algorithm. No Activity reference. */
class SyncRunner implements AutoCloseable {
    final String id;
    final Context context;
    final JSONObject policy, pair;
    final String scope;
    final SyncKey key;
    final SyncStore store;
    private final BooleanSupplier stopped;
    private final long deadline;
    static final class BudgetExpired extends IOException { BudgetExpired(){super("budget");} }
    static final class UploadsPending extends IOException { UploadsPending(){super("uploads");} }
    static final class Cancelled extends IOException { Cancelled(){super("paused");} }
    volatile boolean cancelled;
    volatile boolean accepting=true;
    private final java.util.Set<HttpURLConnection> connections=java.util.concurrent.ConcurrentHashMap.newKeySet();
    private final java.util.concurrent.ExecutorService readers=java.util.concurrent.Executors.newFixedThreadPool(4);
    private Network httpNetwork;
    private JavaScriptSandbox sandbox;
    private com.google.common.util.concurrent.ListenableFuture<JavaScriptSandbox> creating;
    private JavaScriptIsolate js;
    private SyncFiles files;
    protected String token;
    private volatile double authorized;
    private long progressAt;
    private String progressPhase="", progressStep="";
    private double progress;
    private boolean libraryReady;
    private volatile boolean prioritizeUploads;
    private String lastCounts;
    private int binaryId;
    private String savedPair;
    private final java.util.Map<String,long[]> timings=new java.util.TreeMap<>();
    private final long started=android.os.SystemClock.elapsedRealtime();
    private long logged=started;
    SyncRunner(Context c,String id,JSONObject p,BooleanSupplier stopped)throws Exception {
        this(c,id,p,stopped,8*60_000);
    }
    SyncRunner(Context c,String id,JSONObject p,BooleanSupplier stopped,long budgetMs)throws Exception {
        deadline=android.os.SystemClock.elapsedRealtime()+budgetMs;
        context=c;this.id=id;policy=p;this.stopped=stopped;
        synchronized(PhoneSecrets.class){pair=pair(c);savedPair=PhoneSecrets.stored(c,"bp-pair");}
        scope=scope(pair,p.optString("device"));
        key=new SyncKey(Base64.decode(pair.getString("k"),Base64.URL_SAFE|Base64.NO_WRAP));
        if(!key.fingerprint.equals(pair.optString("f")))throw new IOException("access");
        store=new SyncStore(c);
    }
    static JSONObject pair(Context c)throws Exception {
        String s=PhoneSecrets.get(c,"bp-pair");if(s==null)throw new IOException("auth");
        JSONObject p=new JSONObject(s);
        if(p.optInt("v")!=2 || !p.optString("k").matches("[A-Za-z0-9_-]{43}") || p.optString("g").isEmpty()
            || p.has("d") || p.has("backupTask") || (!p.optBoolean("solo") && !p.optString("e").isEmpty() && !p.optString("g").trim().equalsIgnoreCase(p.optString("e").trim())))throw new IOException("auth");
        return p;
    }
    static String scope(JSONObject p,String device)throws Exception {
        return SyncKey.hex(SyncKey.hash(SyncKey.utf(p.optString("k")+":"+p.optString("l")+":"+p.optString("g").toLowerCase(java.util.Locale.ROOT)+":"+p.optBoolean("solo")+":"+device)));
    }
    void checkpoint()throws Exception { checkpoint(true); }
    void checkpoint(boolean budget)throws Exception {
        long at=android.os.SystemClock.elapsedRealtime();
        try{
            JSONObject current=SyncWork.policy(context);
            if(current.optBoolean("paused",true))throw new IOException("paused");
            if(cancelled || stopped.getAsBoolean() || Thread.currentThread().isInterrupted()
                || !SyncWork.enabled(current) || current.optLong("generation")!=policy.optLong("generation"))throw new Cancelled();
            synchronized(PhoneSecrets.class){
                String saved=PhoneSecrets.stored(context,"bp-pair");
                // Identical sealed bytes already passed validation; every changed record is decrypted again.
                if(!java.util.Objects.equals(savedPair,saved)){
                    if(!scope.equals(scope(pair(context),current.optString("device"))))throw new Cancelled();
                    savedPair=saved;
                }
            }
            String net=SyncWork.network(context,current);if(!net.isEmpty())throw new IOException(net);
            if(budget && prioritizeUploads && store.hasPending(scope))throw new UploadsPending();
            if(budget && android.os.SystemClock.elapsedRealtime()>=deadline)throw new BudgetExpired();
        }finally{timed("checkpoint",at);}
    }
    private void timed(String name,long at){synchronized(timings){long[] t=timings.computeIfAbsent(name,k->new long[2]);t[0]++;t[1]+=android.os.SystemClock.elapsedRealtime()-at;}}
    private void logTimings() {
        JSONObject out=new JSONObject();
        try{synchronized(timings){for(java.util.Map.Entry<String,long[]> e:timings.entrySet())out.put(e.getKey(),new JSONArray().put(e.getValue()[0]).put(e.getValue()[1]));}
            if(files!=null)for(java.util.Map.Entry<String,long[]> e:files.timings.entrySet())out.put("saf/"+e.getKey(),new JSONArray().put(e.getValue()[0]).put(e.getValue()[1]));
            out.put("elapsedMs",android.os.SystemClock.elapsedRealtime()-started);android.util.Log.i("BrainamonSyncTiming",out.toString());
        }catch(org.json.JSONException ignored){}
        logged=android.os.SystemClock.elapsedRealtime();
    }
    void access()throws Exception {checkpoint();if(!pair.optBoolean("solo") && authorized<=System.currentTimeMillis()/1000.0)throw new IOException("access");}
    void cancel(){cancelled=true;for(HttpURLConnection c:connections)c.disconnect();}
    public void close(){
        cancel();
        readers.shutdownNow();
        boolean interrupted=Thread.interrupted();
        try{while(!readers.isTerminated())try{readers.awaitTermination(1,TimeUnit.SECONDS);}catch(InterruptedException e){interrupted=true;}}
        finally{if(interrupted)Thread.currentThread().interrupt();}
        logTimings();
        try{if(js!=null)js.close();}finally{
            try{
                if(sandbox!=null)sandbox.close();
                else if(creating!=null)creating.addListener(()->{try{creating.get().close();}catch(Exception ignored){}},Runnable::run);
            }finally{if(files!=null)files.close();store.close();}
        }
    }
    JSONObject run(boolean force,boolean legacy)throws Exception {
        checkpoint();
        if(!SyncWork.supported())throw new IOException("unsupported");
        creating=JavaScriptSandbox.createConnectedInstanceAsync(context);
        sandbox=creating.get(20,TimeUnit.SECONDS);
        for(String feature:new String[]{JavaScriptSandbox.JS_FEATURE_PROMISE_RETURN,JavaScriptSandbox.JS_FEATURE_PROVIDE_CONSUME_ARRAY_BUFFER,JavaScriptSandbox.JS_FEATURE_EVALUATE_WITHOUT_TRANSACTION_LIMIT})
            if(!sandbox.isFeatureSupported(feature))throw new IOException("unsupported");
        IsolateStartupParameters params=new IsolateStartupParameters();params.setMaxEvaluationReturnSizeBytes(80*1024*1024);
        if(sandbox.isFeatureSupported(JavaScriptSandbox.JS_FEATURE_ISOLATE_MAX_HEAP_SIZE))params.setMaxHeapSizeBytes(256L*1024*1024);
        js=sandbox.createIsolate(params);
        String code;try(InputStream in=context.getAssets().open("sync/worker.js")){code=new String(SyncFiles.bytes(in,2*1024*1024),StandardCharsets.UTF_8);}
        evaluate(code+";BrainamonSync.install();''");
        JSONObject config=new JSONObject().put("fp",key.fingerprint).put("verifier",pair.optString("l")).put("solo",pair.optBoolean("solo"))
            .put("device",policy.getString("device")).put("vault",policy.optBoolean("vault") && !policy.optString("uri").isEmpty())
            .put("force",force).put("legacy",legacy).put("watermark",pair.optInt("accessVersion")==2 || store.get(scope,"access-v2")!=null);
        store.put("","status",new JSONObject().put("id",id).put("state","syncing").put("phase","drive").put("progress",0).put("driveStep",new JSONObject().put("key",pair.optBoolean("solo")?"shell.sync.readingIndex":"shell.sync.checkingAccess")).put("libraryReady",false).toString());
        evaluate("BrainamonSync.start("+config+");''");
        for(;;){
            checkpoint();JSONObject message=new JSONObject(evaluate("BrainamonSync.next()"));
            if(message.has("finished")){
                JSONObject done=message.getJSONObject("finished");if(!done.optBoolean("ok"))throw new IOException(done.optString("error","retry"));
                store.compact(scope);
                return done.getJSONObject("value");
            }
            JSONArray calls=message.getJSONArray("calls");
            java.util.Map<Integer,java.util.concurrent.Future<byte[]>> downloads=readCalls(calls);
            for(int i=0;i<calls.length();i++){
                JSONObject call=calls.getJSONObject(i);Object value=JSONObject.NULL;String error=null;
                long at=android.os.SystemClock.elapsedRealtime();String method=call.getString("method");
                try{
                    java.util.concurrent.Future<byte[]> read=downloads.get(i);
                    value=read==null?dispatch(method,call.getJSONArray("args")):binary(read.get());
                }catch(Exception e){
                    // Lifecycle signals must not become shared-algorithm errors (which may be caught there).
                    for(Throwable cause=e;cause!=null;cause=cause.getCause()){
                        if(cause instanceof BudgetExpired)throw (BudgetExpired)cause;
                        if(cause instanceof UploadsPending)throw (UploadsPending)cause;
                        if(cause instanceof Cancelled)throw (Cancelled)cause;
                        if(cause instanceof InterruptedException)throw (InterruptedException)cause;
                    }
                    error=reason(e instanceof java.util.concurrent.ExecutionException?e.getCause():e);
                    if(java.util.Arrays.asList("retry","wifi","offline").contains(error))throw new IOException(error,e);
                }
                finally{timed("rpc/"+method,at);}
                if(android.os.SystemClock.elapsedRealtime()-logged>=30_000)logTimings();
                String encoded=json(value);
                evaluate("BrainamonSync.answer("+call.getInt("id")+","+encoded+","+(error==null?"undefined":JSONObject.quote(error))+");''");
            }
        }
    }
    java.util.Map<Integer,java.util.concurrent.Future<byte[]>> readCalls(JSONArray calls)throws Exception {
        java.util.Map<Integer,java.util.concurrent.Future<byte[]>> reads=new java.util.HashMap<>();
        java.util.Map<String,java.util.concurrent.Future<byte[]>> unique=new java.util.HashMap<>();
        for(int i=0;i<calls.length();i++) {
            JSONObject call=calls.getJSONObject(i);JSONArray args=call.getJSONArray("args");
            // Only independent content reads run concurrently; control, SAF and publication stay ordered.
            if(!call.getString("method").equals("get") || args.optInt(1,SyncFiles.LIMIT+32)==20000)continue;
            String identity=args.toString();java.util.concurrent.Future<byte[]> read=unique.get(identity);
            if(read==null){read=readers.submit(()->getBytes(args));unique.put(identity,read);}
            reads.put(i,read);
        }
        return reads;
    }
    byte[] getBytes(JSONArray args)throws Exception {
        long at=android.os.SystemClock.elapsedRealtime();
        try{
            int limit=args.optInt(1,SyncFiles.LIMIT+32);if(limit!=20000)access();else checkpoint();
            String path="/drive/v3/files/"+q(args.getString(0))+"?alt=media";
            return limit==20000?http("GET",path,null,null,limit,false):download(path,limit);
        }finally{timed("download",at);}
    }
    private String evaluate(String code)throws Exception {
        long at=android.os.SystemClock.elapsedRealtime();
        try{return js.evaluateJavaScriptAsync(code).get(45,TimeUnit.SECONDS);}finally{timed("engine",at);}
    }
    private static String json(Object value){return value==null?"null":value instanceof String?JSONObject.quote((String)value):value.toString();}
    static String stateName(String name,JSONObject policy)throws Exception {
        return name.startsWith("vault-")?name+"/"+SyncKey.hex(SyncKey.hash(SyncKey.utf(policy.optString("uri")))):name;
    }
    private JSONObject binary(byte[] bytes)throws Exception {
        String name="b"+(++binaryId);js.provideNamedData(name,bytes);return new JSONObject().put("binary",name);
    }
    private static byte[] decode(String s){return Base64.decode(s,Base64.NO_WRAP);}
    private SyncFiles fs()throws Exception {if(files==null)files=new SyncFiles(context,policy.getString("uri"),key);return files;}
    Object dispatch(String method,JSONArray a)throws Exception {
        checkpoint();
        switch(method){
            case "name":return key.name(a.getString(0));
            case "contentId":return key.contentId(decode(a.getString(0)));
            case "seal":return binary(key.seal(a.getString(0),decode(a.getString(1))));
            case "open":try{return binary(key.open(a.getString(0),decode(a.getString(1))));}catch(javax.crypto.AEADBadTagException e){throw new IOException("key");}
            case "digest":return binary(SyncKey.hash(decode(a.getString(0))));
            case "verify":return verify(a);
            case "watermark":store.put(scope,"access-v2","true");return null;
            case "authorized":authorized=a.getDouble(0);return null;
            case "load":{String s=store.get(scope,stateName(a.getString(0),policy));return s==null?null:new JSONTokener(s).nextValue();}
            case "save":{
                String name=stateName(a.getString(0),policy),value=json(a.get(1));
                if(name.equals("manifest")){
                    String prior=store.get(scope,"manifest");
                    if(prior!=null && !prior.equals(value))store.put(scope,"previous-manifest",prior);
                }
                store.put(scope,name,value);
                if(name.equals("manifest") || name.equals("solo-list")){
                    libraryReady=true;
                    JSONObject status=new JSONObject(store.get("","status"));status.put("libraryReady",true);store.put("","status",status.toString());
                }
                return null;
            }
            case "outbox":access();return store.next(scope);
            case "delivered":access();store.delivered(scope,a.getString(0),a.getString(1));return null;
            case "find":return find(a.getString(0));
            case "list":access();return list(null);
            case "get":return binary(getBytes(a));
            case "create":access();return create(a.getString(0),decode(a.getString(1)));
            case "remove":access();http("DELETE","/drive/v3/files/"+q(a.getString(0)),null,null,20000);return null;
            case "update":access();http("PATCH","/upload/drive/v3/files/"+q(a.getString(0))+"?uploadType=media",decode(a.getString(1)),"application/octet-stream",20000);return null;
            case "gunzip":try(InputStream in=new GZIPInputStream(new ByteArrayInputStream(decode(a.getString(0))))){return new String(SyncFiles.bytes(in,SyncFiles.LIMIT),StandardCharsets.UTF_8);}
            case "fsList":access();return fs().list(a.getJSONArray(0),()->{try{checkpoint();}catch(Exception e){throw new IllegalStateException(e);}});
            case "fsRead":access();return binary(fs().read(a.getString(0)));
            case "fsHas":access();return fs().has(a.getString(0));
            case "fsWrite":access();fs().write(a.getString(0),decode(a.getString(1)),a.isNull(2)?null:a.getString(2),a.optBoolean(3));return null;
            case "fsRemove":access();fs().remove(a.getString(0),a.isNull(1)?null:a.getString(1));return null;
            case "progress":{
                long now=System.currentTimeMillis();String lane=a.getString(0);double fraction=a.getDouble(1);
                prioritizeUploads=!lane.equals("send");
                progress=Math.max(progress,lane.equals("vault")?0.4+0.59*fraction:0.4*fraction);
                JSONObject step=a.optJSONObject(2),counts=step==null?null:step.optJSONObject("files");
                String stepKey=step==null?"":step.optString("key");
                boolean transition=!lane.equals(progressPhase) || !stepKey.equals(progressStep);
                boolean changed=counts!=null && !counts.toString().equals(lastCounts);
                if(changed){
                    lastCounts=counts.toString();
                    store.put(scope,stateName("vault-counts",policy),new JSONObject(lastCounts).put("at",now).toString());
                }
                if(transition || changed || fraction>=1 || now-progressAt>=1000){
                    store.put("","status",new JSONObject().put("id",id).put("state","syncing").put("phase",lane).put("progress",progress).put(lane.equals("drive")?"driveStep":"vaultStep",step).put("libraryReady",libraryReady).toString());
                    progressAt=now;progressPhase=lane;progressStep=stepKey;
                }return null;
            }
            default:throw new IOException("Unknown sync operation");
        }
    }
    private boolean verify(JSONArray a)throws Exception {
        JSONObject spec=a.getJSONObject(1);byte[] encoded=decode(spec.getString("data"));
        String algorithm=a.get(0) instanceof JSONObject?a.getJSONObject(0).getString("name"):a.getString(0);
        byte[] signature=decode(a.getString(2));String kind;
        if(algorithm.equals("ECDSA")){
            if(signature.length!=64)return false;
            // WebCrypto uses IEEE P1363 r||s; Java's SHA256withECDSA expects DER.
            byte[] r=new java.math.BigInteger(1,java.util.Arrays.copyOfRange(signature,0,32)).toByteArray();
            byte[] s=new java.math.BigInteger(1,java.util.Arrays.copyOfRange(signature,32,64)).toByteArray();
            ByteArrayOutputStream out=new ByteArrayOutputStream();out.write(48);out.write(4+r.length+s.length);out.write(2);out.write(r.length);out.write(r);out.write(2);out.write(s.length);out.write(s);signature=out.toByteArray();kind="EC";
        }else if(algorithm.equals("Ed25519")){
            if(encoded.length!=32)return false;
            encoded=SyncKey.join(new byte[]{48,42,48,5,6,3,43,101,112,3,33,0},encoded);kind="Ed25519";
        }else return false;
        Signature verifier=Signature.getInstance(kind.equals("EC")?"SHA256withECDSA":"Ed25519");
        verifier.initVerify(KeyFactory.getInstance(kind).generatePublic(new X509EncodedKeySpec(encoded)));verifier.update(decode(a.getString(3)));return verifier.verify(signature);
    }
    protected String endpoint(){return "https://www.googleapis.com";}
    protected void clearToken()throws Exception {Tasks.await(Identity.getAuthorizationClient(context).clearToken(ClearTokenRequest.builder().setToken(token).build()),10,TimeUnit.SECONDS);}
    protected void renew()throws Exception {
        checkpoint();
        AuthorizationRequest req=AuthorizationRequest.builder().setAccount(new Account(pair.getString("g"),"com.google"))
            .setRequestedScopes(Collections.singletonList(new Scope("https://www.googleapis.com/auth/drive.appdata"))).build();
        AuthorizationResult r;
        try{r=Tasks.await(Identity.getAuthorizationClient(context).authorize(req),30,TimeUnit.SECONDS);}catch(Exception e){throw new IOException("auth");}
        if(r.hasResolution() || r.getAccessToken()==null)throw new IOException("auth");token=r.getAccessToken();
        JSONObject about=new JSONObject(new String(http("GET","/drive/v3/about?fields=user(emailAddress)",null,null,20000,false),StandardCharsets.UTF_8));
        if(!pair.getString("g").equalsIgnoreCase(about.getJSONObject("user").getString("emailAddress")))throw new IOException("auth");
    }
    private static String q(String s)throws Exception{return URLEncoder.encode(s,"UTF-8");}
    private JSONArray find(String name)throws Exception {
        if(!name.matches("[A-Za-z0-9._-]{1,180}"))throw new IOException("Invalid Drive name");
        if(!name.equals(key.name("control/access-v2.json")) && !name.equals(key.name("control/license-v1.json")))access();
        return list(name);
    }
    private JSONArray list(String name)throws Exception {
        JSONArray out=new JSONArray();String page="";java.util.Set<String> pages=new java.util.HashSet<>();
        do{
            String path="/drive/v3/files?spaces=appDataFolder&fields="+q("files(id,name,size),nextPageToken,incompleteSearch")+"&pageSize=1000&q="+q("trashed = false"+(name==null?"":" and name = '"+name+"'"))+(page.isEmpty()?"":"&pageToken="+q(page));
            boolean control=name!=null && (name.equals(key.name("control/access-v2.json")) || name.equals(key.name("control/license-v1.json")));
            JSONObject d=new JSONObject(new String(http("GET",path,null,null,4*1024*1024,!control),StandardCharsets.UTF_8));
            if(d.optBoolean("incompleteSearch") || !d.has("files"))throw new IOException("retry");
            JSONArray rows=d.getJSONArray("files");for(int i=0;i<rows.length();i++)out.put(rows.get(i));
            page=d.optString("nextPageToken");if(!page.isEmpty() && !pages.add(page))throw new IOException("retry");
        }while(!page.isEmpty());return out;
    }
    private String create(String name,byte[] data)throws Exception {
        if(!name.matches("(?:chg-[a-f0-9]{32}|solo-[a-f0-9]{32}-[a-f0-9]{32}|v[bi]-[a-f0-9]{32})"))throw new IOException("Invalid upload");
        if(pair.optBoolean("solo") && !name.startsWith("solo-"+key.name("phone-backup")+"-"))throw new IOException("access");
        if(data.length>1024*1024)return upload(name,data);
        String boundary="brainamon"+java.util.UUID.randomUUID().toString().replace("-","");
        JSONObject meta=new JSONObject().put("name",name).put("parents",new JSONArray().put("appDataFolder"));
        byte[] head=SyncKey.utf("--"+boundary+"\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"+meta+"\r\n--"+boundary+"\r\nContent-Type: application/octet-stream\r\n\r\n");
        byte[] body=SyncKey.join(SyncKey.join(head,data),SyncKey.utf("\r\n--"+boundary+"--"));
        return new JSONObject(new String(http("POST","/upload/drive/v3/files?uploadType=multipart&fields=id",body,"multipart/related; boundary="+boundary,20000),StandardCharsets.UTF_8)).getString("id");
    }
    private byte[] http(String method,String path,byte[] body,String contentType,int limit)throws Exception {
        return http(method,path,body,contentType,limit,true);
    }
    private byte[] http(String method,String path,byte[] body,String contentType,int limit,boolean protectedCall)throws Exception {
        return exchange(method,path,body,contentType,limit,protectedCall,Collections.emptyMap(),false).data;
    }
    private static final class Reply {
        final int code;final byte[] data;final String location,range,etag,contentRange;
        Reply(HttpURLConnection c,byte[] data)throws IOException{code=c.getResponseCode();this.data=data;location=c.getHeaderField("Location");range=c.getHeaderField("Range");etag=c.getHeaderField("ETag");contentRange=c.getHeaderField("Content-Range");}
    }
    private Reply exchange(String method,String path,byte[] body,String contentType,int limit,boolean protectedCall,java.util.Map<String,String> headers,boolean session)throws Exception {
        boolean authRetried=false;
        for(int attempt=0;;attempt++){
            String requestToken;
            synchronized(this){
                if(token==null)try{renew();}catch(Exception e){token=null;throw e;}
                requestToken=token;
            }
            checkpoint();if(protectedCall)access();
            ConnectivityManager cm=(ConnectivityManager)context.getSystemService(Context.CONNECTIVITY_SERVICE);
            Network current=cm.getActiveNetwork();if(current==null)throw new IOException("offline");
            // Network owns its HTTP connection pool; keep it until the active network changes.
            Network net;synchronized(this){if(!current.equals(httpNetwork))httpNetwork=current;net=httpNetwork;}
            HttpURLConnection c=(HttpURLConnection)net.openConnection(new URL(endpoint()+path));connections.add(c);
            try{
                checkpoint();
                c.setInstanceFollowRedirects(false);c.setConnectTimeout(20000);c.setReadTimeout(20000);c.setRequestMethod(method);c.setRequestProperty("Authorization","Bearer "+requestToken);
                for(java.util.Map.Entry<String,String> h:headers.entrySet())c.setRequestProperty(h.getKey(),h.getValue());
                if(body!=null){c.setDoOutput(true);c.setFixedLengthStreamingMode(body.length);c.setRequestProperty("Content-Type",contentType);
                    try(OutputStream out=c.getOutputStream()){for(int at=0;at<body.length;at+=32768){checkpoint();if(!net.equals(cm.getActiveNetwork()))throw new IOException("offline");out.write(body,at,Math.min(32768,body.length-at));}}
                }
                int status=c.getResponseCode();
                if(status==401 && !authRetried && !path.startsWith("/drive/v3/about?")){
                    authRetried=true;
                    synchronized(this){if(java.util.Objects.equals(token,requestToken)){clearToken();token=null;}}
                    continue;
                }
                if(status==401)throw new IOException("auth");
                if(status==404 && method.equals("DELETE") || session && (status==308 || status==404 || status==410))return new Reply(c,new byte[0]);
                if(status==416 && headers.containsKey("Range"))return new Reply(c,new byte[0]);
                if(status<200 || status>=300){
                    String error="";try(InputStream in=c.getErrorStream()){if(in!=null)error=new String(SyncFiles.bytes(in,20000),StandardCharsets.UTF_8);}
                    boolean retry=status==429 || status>=500 || status==403 && error.contains("rateLimit");
                    // Unknown POST results are reconciled by their immutable name on the next worker attempt.
                    if(retry && attempt<3 && !method.equals("POST") && !(session && method.equals("PUT"))){pause(attempt);continue;}
                    throw new IOException(retry?"retry":status==403?"auth":"library");
                }
                try(InputStream in=c.getInputStream()){
                    ByteArrayOutputStream out=new ByteArrayOutputStream();byte[] buf=new byte[32768];int n;
                    while((n=in.read(buf))!=-1){checkpoint();if(!net.equals(cm.getActiveNetwork()))throw new IOException("offline");if(out.size()+n>limit)throw new IOException("File exceeds sync limit");out.write(buf,0,n);}checkpoint();return new Reply(c,out.toByteArray());
                }
            }catch(java.net.SocketTimeoutException e){if(attempt>=2 || method.equals("POST") || session && method.equals("PUT"))throw new IOException("retry");pause(attempt);}
            finally{connections.remove(c);c.disconnect();}
        }
    }
    private byte[] download(String path,int limit)throws Exception {
        String slot="download/"+SyncKey.hex(SyncKey.hash(SyncKey.utf(path))),raw=store.get(scope,slot);
        JSONObject saved=raw==null?null:new JSONObject(raw);
        int offset=saved==null?0:saved.getInt("next");
        for(;;){
            java.util.Map<String,String> headers=new java.util.HashMap<>();headers.put("Range","bytes="+offset+"-"+(offset+1024*1024-1));
            if(saved!=null)headers.put("If-Range",saved.getString("etag"));
            Reply r=exchange("GET",path,null,null,limit,true,headers,false);
            if(r.code==416){store.removePrefix(scope,slot);throw new IOException("retry");}
            if(r.code==200){store.removePrefix(scope,slot);return r.data;}
            java.util.regex.Matcher range=java.util.regex.Pattern.compile("bytes ([0-9]+)-([0-9]+)/([0-9]+)").matcher(r.contentRange==null?"":r.contentRange);
            if(r.code!=206 || !range.matches())throw new IOException("retry");
            long total=Long.parseLong(range.group(3)),end=Long.parseLong(range.group(2))+1;
            if(Long.parseLong(range.group(1))!=offset || end-offset!=r.data.length || total>limit || end>total || end<=offset)throw new IOException("retry");
            if(r.etag==null || r.etag.startsWith("W/")){
                store.removePrefix(scope,slot);return http("GET",path,null,null,limit);
            }
            if(saved!=null && (!r.etag.equals(saved.getString("etag")) || total!=saved.getLong("total"))){store.removePrefix(scope,slot);throw new IOException("retry");}
            store.put(scope,slot+"/"+offset,Base64.encodeToString(r.data,Base64.NO_WRAP));
            if(end==total){
                ByteArrayOutputStream out=new ByteArrayOutputStream((int)total);
                for(int at=0;at<total;){String chunk=store.get(scope,slot+"/"+at);if(chunk==null)throw new IOException("retry");byte[] bytes=decode(chunk);if(bytes.length==0)throw new IOException("retry");out.write(bytes);at+=bytes.length;}
                store.removePrefix(scope,slot);return out.toByteArray();
            }
            offset=(int)end;saved=new JSONObject().put("next",offset).put("total",total).put("etag",r.etag).put("at",System.currentTimeMillis());
            store.put(scope,slot,saved.toString());
        }
    }
    private String upload(String name,byte[] data)throws Exception {
        String slot="upload/"+name,raw=store.get(scope,slot);
        JSONObject saved=raw==null?null:new JSONObject(raw);
        String logical=name.startsWith("vb-")?"vault/blob/"+name.substring(3):name.startsWith("vi-")?"vault/index":name;
        String digest=SyncKey.hex(SyncKey.hash(key.open(logical,data)));
        if(saved!=null && (!digest.equals(saved.optString("digest")) || saved.optLong("at")<System.currentTimeMillis()-6*86400000L)){store.remove(scope,slot);saved=null;}
        if(saved==null){
            saved=new JSONObject().put("digest",digest).put("data",Base64.encodeToString(data,Base64.NO_WRAP)).put("at",System.currentTimeMillis());
            store.put(scope,slot,saved.toString());
            store.put(scope,"upload-time/"+name,String.valueOf(System.currentTimeMillis()));
        }else data=decode(saved.getString("data")); // A resumed session must use the original encryption nonce.
        String path=saved.optString("path");
        if(path.isEmpty()){
            JSONObject meta=new JSONObject().put("name",name).put("parents",new JSONArray().put("appDataFolder"));
            java.util.Map<String,String> headers=new java.util.HashMap<>();headers.put("X-Upload-Content-Type","application/octet-stream");headers.put("X-Upload-Content-Length",String.valueOf(data.length));
            Reply begin=exchange("POST","/upload/drive/v3/files?uploadType=resumable&fields=id",SyncKey.utf(meta.toString()),"application/json",20000,true,headers,true);
            if(begin.location==null)throw new IOException("retry");
            URL origin=new URL(endpoint()),location=new URL(begin.location);
            if(!origin.getProtocol().equals(location.getProtocol()) || !origin.getHost().equals(location.getHost()) || origin.getPort()!=location.getPort() || !location.getPath().startsWith("/upload/drive/v3/files"))throw new IOException("access");
            path=location.getFile();saved.put("path",path);store.put(scope,slot,saved.toString());
        }
        // Query the server after every interruption; never guess how much of the last chunk arrived.
        Reply reply=exchange("PUT",path,new byte[0],"application/octet-stream",20000,true,Collections.singletonMap("Content-Range","bytes */"+data.length),true);
        int stalls=0;
        for(;;){
            if(reply.code==200 || reply.code==201){String id=new JSONObject(new String(reply.data,StandardCharsets.UTF_8)).getString("id");store.remove(scope,slot);store.remove(scope,"upload-time/"+name);return id;}
            if(reply.code==404 || reply.code==410){store.remove(scope,slot);throw new IOException("retry");}
            if(reply.code!=308)throw new IOException("retry");
            int offset=0;
            if(reply.range!=null){
                java.util.regex.Matcher m=java.util.regex.Pattern.compile("bytes=0-([0-9]+)").matcher(reply.range);
                if(!m.matches())throw new IOException("retry");offset=Math.toIntExact(Long.parseLong(m.group(1))+1);
            }
            if(offset<0 || offset>=data.length)throw new IOException("retry");
            int end=Math.min(data.length,offset+1024*1024);
            reply=exchange("PUT",path,java.util.Arrays.copyOfRange(data,offset,end),"application/octet-stream",20000,true,
                Collections.singletonMap("Content-Range","bytes "+offset+"-"+(end-1)+"/"+data.length),true);
            if(reply.code==308 && (reply.range==null || reply.range.equals("bytes=0-"+(offset-1)))){if(++stalls>=2)throw new IOException("retry");}else stalls=0;
        }
    }
    private void pause(int attempt)throws Exception {long until=android.os.SystemClock.elapsedRealtime()+1000*(1L<<attempt)+(long)(Math.random()*500);while(android.os.SystemClock.elapsedRealtime()<until){checkpoint();Thread.sleep(100);}}
    static String reason(Throwable e){
        String s=e.getMessage();
        if(e instanceof SecurityException)return "permission";
        return java.util.Arrays.asList("auth","access","permission","conflict","update","library","paused","unsupported","wifi","offline","key").contains(s)?s:"retry";
    }
}
