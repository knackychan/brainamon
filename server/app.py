"""The FastAPI application factory. Run it with `py -m server` (see server/__main__.py)."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import anyio.to_thread
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from core import app_console, app_paths, local_auth
from desktop import updater
from server import events, settings
from server.map_service import MapService
from server import job_kinds  # noqa: F401  (registers the job kinds)
from server.guard import LocalGuard, allowed_hosts, InstallGate, InstallGuard
from server.updates import Updates
from server.jobs import Busy, JobError, JobManager
from server.notify import Notifier
from server.routes import app as app_routes, ask, canvas, categories, claude_code, cloud, files, filing, inbox, io, items, jobs, knowledge, library, license, links, my_notes, obsidian, onboarding, settings as settings_routes, smart
from server.store import Writer
from server.recovery import RecoveryService
from server.sync import SyncService, recorded_vault_id
from server.tints import Tints, router as tints_router


class _WebFiles(StaticFiles):
    """web/dist: the HTML pages are revalidated on every load (no-cache + their etag), so a rebuilt front
    end shows up after a restart instead of WebView2's heuristically cached old page. The hashed
    /assets files keep normal caching."""

    def file_response(self, full_path, *args, **kwargs):
        response = super().file_response(full_path, *args, **kwargs)
        if str(full_path).endswith('.html'):
            response.headers['Cache-Control'] = 'no-cache'
        return response


THREADS = 8


def create_app(data_dir: Path | None = None, port: int | None = None,
               web_dist: Path | None = None, cards_dir: Path | None = None,
               cloud_dir: Path | None = None) -> FastAPI:
    from types import SimpleNamespace
    from server.routes import recovery as recovery_routes
    cloud_dir = Path(cloud_dir or settings.CLOUD_DIR)
    if data_dir is None:
        recovery_startup = RecoveryService(SimpleNamespace(cloud_dir=cloud_dir, key_path=cloud_dir / 'mirror.key'))
        pending = recovery_startup.finish_activation()
        if pending and Path(pending).resolve() != Path(settings.DATA_DIR).resolve():
            # Modules already imported paths from the old pointer; never mix them with the restored DB.
            raise RuntimeError('Recovery activation finished safely. Reopen Brainamon once more to load the restored library.')
        data_dir = Path(pending or settings.DATA_DIR)
    else:
        data_dir = Path(data_dir)
    port = port or settings.PORT
    web_dist = Path(web_dist or settings.WEB_DIST)
    cards_dir = Path(cards_dir or settings.CARDS_DIR)
    db_path = data_dir / settings.DB_NAME

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # sync endpoints and file reads run on anyio's pool: 8 threads instead of the default 40,
        # each of which kept its own reader connection and caches (plan 10-footprint A4)
        anyio.to_thread.current_default_thread_limiter().total_tokens = THREADS
        data_dir.mkdir(parents=True, exist_ok=True)
        updater.backup_on_upgrade(data_dir, settings.DB_NAME)   # new version: DB copy before _migrate()
        writer = Writer(db_path)
        writer.start()               # opens db.Database: schema + _migrate() run here, once
        hub = events.EventHub()
        hub.bind(asyncio.get_running_loop())
        from core import site_sessions
        try:
            site_sessions.cleanup_stale()
        except (OSError, RuntimeError):
            app_console.emit('error', 'Session temporary-file cleanup failed; retry Forget in Settings > Downloads.', level='error')
        app.state.writer = writer
        app.state.hub = hub
        app.state.items_cache = {}          # GET /api/items bodies, keyed on writer.generation
        writer.call(settings_routes.migrate_registry)   # Qt QSettings download paths, copied once
        writer.call(lambda db: db.library_id())        # the permanent library id, created once (map engine decision 4)
        app.state.revealable = set()
        app.state.scrape_watcher = None
        app.state.jobs = JobManager(writer, hub, data_dir)
        app.state.notify = Notifier()                # Windows notifications; off until Settings > App turns them on
        writer.call(app.state.notify.load)
        app.state.jobs.notify = app.state.notify
        app.state.embed_index = None
        app.state.embed_used = 0.0
        idle_drop = asyncio.create_task(smart.drop_when_idle(app))
        app.state.jobs.on_finish.append(lambda key, job: smart.drop_index(app) if key == 'index' else None)
        app.state.tints = Tints(data_dir / 'items')

        def new_thumbs(key, job):
            if key in ('thumb', 'download'):
                for i in job.ok_ids:
                    app.state.tints.refresh(i)
        app.state.jobs.on_finish.append(new_thumbs)
        app.state.jobs.on_finish.append(
            lambda key, job: app.state.revealable.add(job.ctx['reveal']) if job and job.ctx.get('reveal') else None)
        app.state.tints.start()
        # Upload to Google Drive: no thread and no cloud call unless the user turned it on
        def phone_links(ids):
            # links saved on the phone get Fetch thumbnails, as POST /api/inbox/link does; False
            # while another job runs, and the sync thread asks again
            try:
                app.state.jobs.start('thumb', ids, True, {}, auto=True)
            except Busy:
                return False
            except JobError:
                pass
            return True
        def phone_synth(topic, ids):
            # a Synthesize the phone left for the PC (more sources than it folds itself); False
            # while another job runs. A job that cannot start (no key) is reported and dropped.
            try:
                app.state.jobs.start('note', ids, True, {'topic': topic}, auto=True)
            except Busy:
                return False
            except JobError as e:
                app_console.emit('log', f'Synthesize asked from the phone did not start: {e}', level='warning')
            return True
        app.state.sync = SyncService(writer, hub, data_dir, cloud_dir, tints=lambda: dict(app.state.tints.tints),
                                     on_new_links=phone_links, on_synth=phone_synth)
        app.state.jobs.on_prepare.append(lambda key: app.state.sync.refresh_vault_folder() if key == 'export_obsidian' else None)
        app.state.jobs.on_finish.append(lambda key, job: app.state.sync.poke())
        app.state.sync.boot()
        app.state.maps = MapService(writer, hub, data_dir,
                                    vault_devices=lambda: app.state.sync.status().get('vault_devices'),
                                    vault_id_for=lambda folder: recorded_vault_id(cloud_dir, folder))
        app.state.jobs.on_finish.append(lambda key, job: app.state.maps.poke(now=key == 'refresh_map'))
        app.state.maps.boot()
        app.state.updates = Updates(writer, hub)
        app.state.updates.boot()

        def to_console(entry):
            hub.publish('log', entry)
        app_console.add_listener(to_console)
        app_console.emit('log', 'CM-OS server started', payload={'database': str(db_path)})
        yield
        idle_drop.cancel()
        app.state.updates.shutdown()
        app_console.remove_listener(to_console)
        if app.state.scrape_watcher:
            app.state.scrape_watcher.stop()
        app.state.maps.shutdown()
        app.state.jobs.shutdown()
        app.state.sync.recovery.shutdown()
        app.state.sync.shutdown()
        writer.stop()

    app = FastAPI(title='CM-OS', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.api_token = local_auth.create(port)
    app.state.data_dir = data_dir
    app.state.db_path = db_path
    app.state.port = port
    app.state.install_gate = InstallGate()

    app.include_router(library.router)
    app.include_router(links.router)
    app.include_router(app_routes.router)
    app.include_router(onboarding.router)
    app.include_router(inbox.router)
    app.include_router(jobs.router)
    app.include_router(smart.router)
    app.include_router(items.router)
    app.include_router(categories.router)
    app.include_router(files.router)
    app.include_router(settings_routes.router)
    app.include_router(ask.router)
    app.include_router(claude_code.router)
    app.include_router(knowledge.router)
    app.include_router(my_notes.router)
    app.include_router(filing.router)
    app.include_router(canvas.router)
    app.include_router(cloud.router)
    app.include_router(recovery_routes.router)
    app.include_router(license.router)
    app.include_router(io.router)
    app.include_router(obsidian.router)
    app.include_router(tints_router)
    app.include_router(events.router)

    if cards_dir.is_dir():
        # the locked card files, served read-only exactly as they are on disk
        app.mount('/cards', StaticFiles(directory=cards_dir), name='cards')
    if web_dist.is_dir():
        app.mount('/', _WebFiles(directory=web_dist, html=True), name='web')
    else:
        @app.get('/')
        def not_built():
            return PlainTextResponse('Front end not built. Run: cd web && npm install && npm run build')

    app.add_middleware(InstallGuard, gate=app.state.install_gate)
    app.add_middleware(LocalGuard, hosts=allowed_hosts(port), token=app.state.api_token,
                       dev_origins=('http://127.0.0.1:5173',) if not app_paths.FROZEN else ())
    return app
