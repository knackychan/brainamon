package app.brainamon.mobile;

/** Shell-only debug controls; a broadcast does not kill its target process when it returns. */
public final class SyncProbeReceiver extends android.content.BroadcastReceiver {
    public void onReceive(android.content.Context context,android.content.Intent intent){
        PendingResult pending=goAsync();
        new Thread(()->{
            try{android.os.Bundle result=SyncProbe.execute(context,intent.getExtras());android.util.Log.i("SyncProbe",result.toString());}
            finally{pending.finish();}
        },"sync-fixture").start();
    }
}
