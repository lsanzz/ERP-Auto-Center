"""Wake a bounded local consumer of the durable queue after a user action.

Only migration jobs are consumed here. Multiple web/CLI consumers coordinate using
the existing MySQL queue locks. One daemon thread per app avoids one thread/upload.
"""
from datetime import datetime
from threading import Event, Lock, Thread

from sqlalchemy import select

from ..jobs import run_next_job
from ..models import AsyncJob, db

MIGRATION_JOBS = ('MIGRATION_PREPARE', 'MIGRATION_IMPORT')


class MigrationWorker:
    def __init__(self, app):
        self.app = app
        self.lock = Lock()
        self.wakeup = Event()
        self.thread = None

    def start(self):
        with self.lock:
            self.wakeup.set()
            if self.thread is None or not self.thread.is_alive():
                self.thread = Thread(target=self.run, name='migration-worker', daemon=True)
                self.thread.start()

    def run(self):
        try:
            with self.app.app_context():
                while True:
                    self.wakeup.clear()
                    try:
                        job = run_next_job(job_types=MIGRATION_JOBS)
                        if job is not None:
                            continue
                        due = db.session.scalar(select(AsyncJob.available_at).where(
                            AsyncJob.job_type.in_(MIGRATION_JOBS), AsyncJob.status == 'PENDENTE'
                        ).order_by(AsyncJob.available_at).limit(1))
                    finally:
                        db.session.remove()
                    if due is None:
                        with self.lock:
                            if self.wakeup.is_set():
                                continue
                            self.thread = None
                            return
                    # Wait outside any database transaction; enqueue can wake this early.
                    self.wakeup.wait(max(0.2, min(30, (due - datetime.now()).total_seconds())))
        except Exception as exc:
            # No SQL parameters/customer data in logs. The pending queue remains durable.
            self.app.logger.error('migration_worker_stopped error_type=%s', type(exc).__name__)
            with self.lock:
                self.thread = None


def configure_worker(app):
    app.extensions['migration_worker'] = MigrationWorker(app)


def start_worker(app):
    if app.config.get('MIGRATION_AUTO_WORKER', not app.testing):
        app.extensions['migration_worker'].start()
