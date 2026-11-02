"""One backend-owned Windows update schedule, independent of visible windows."""
import threading
import time

from core import app_paths
from desktop import updater

AUTO = 'automatic_updates'
ATTEMPT = 'update_last_attempt'
NOTIFIED = 'update_notified'
INTERVAL = 24 * 3600


class Updates:
    def __init__(self, writer, hub):
        self.writer, self.hub = writer, hub
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.thread = None
        self.info = {}
        self.checking = False

    def enabled(self):
        return not app_paths.CONTRIBUTOR and self.writer.read(lambda db: db.get_setting(AUTO, '1') != '0')

    def status(self):
        st = updater.status()
        if st['state'] == 'ready' and self.info.get('latest') and st['version'] != self.info['latest']:
            st['state'] = 'idle'
        return {**self.info, **st, 'automatic': self.enabled(), 'error': st['error'] or self.info.get('error', ''),
                **({'state': 'checking'} if self.checking else {})}

    def emit(self):
        self.hub.publish('update', self.status())

    def check(self, download=False, automatic=False):
        if app_paths.CONTRIBUTOR:
            return {'error': 'This build is updated from its own source or installer; official updates are disabled.'}
        if not self.lock.acquire(blocking=False):
            return self.status()
        try:
            if updater.status()['state'] == 'downloading':
                return self.status()
            if automatic and not self.enabled():
                return self.status()
            self.checking = True
            self.emit()
            self.writer.call(lambda db: db.set_setting(ATTEMPT, str(int(time.time()))))
            self.info = updater.check()
            if (download and not self.stop.is_set() and self.info.get('newer') and not self.info.get('error')
                    and (not automatic or self.enabled())):
                st = updater.status()
                if st['state'] != 'ready' or st['version'] != self.info['latest']:
                    updater.start_download(self.info)
            return self.info
        finally:
            self.checking = False
            self.lock.release()
            self.emit()

    def boot(self):
        if not app_paths.FROZEN or app_paths.CONTRIBUTOR:
            return
        self.thread = threading.Thread(target=self._loop, name='cm-updates', daemon=True)
        self.thread.start()

    def _loop(self):
        self.info = updater.recover()
        if self.stop.is_set():
            return
        self.emit()
        if self.stop.wait(30):
            return
        previous = None
        while not self.stop.is_set():
            if self.enabled():
                try:
                    last = self.writer.read(lambda db: float(db.get_setting(ATTEMPT, '0') or 0))
                except ValueError:
                    last = 0
                if time.time() - last >= INTERVAL:
                    self.check(download=True, automatic=True)
            st = self.status()
            if st != previous:
                self.emit()
                previous = st
            if st['state'] == 'ready' and self.writer.read(lambda db: db.get_setting(NOTIFIED, '')) != st['version']:
                self.writer.call(lambda db: db.set_setting(NOTIFIED, st['version']))
                self.hub.publish('toast', {'text': f'Brainamon {st["version"]} is ready. Open Settings > App to install and restart.', 'level': ''})
            self.stop.wait(1)

    def shutdown(self):
        self.stop.set()
        updater.stop_download()
        if self.thread:
            self.thread.join(10)
