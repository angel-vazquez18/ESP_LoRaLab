"""One tracked saved-evidence worker, joined before its store can close."""

import asyncio


class SavedEvidenceWorker:
    def __init__(self, busy_message):
        self.busy_message, self.workers, self.closing = busy_message, set(), False

    def finished(self, worker):
        self.workers.discard(worker)
        if not worker.cancelled():
            worker.exception()

    async def run(self, operation, *args):
        if self.closing:
            raise RuntimeError("Host is shutting down")
        if self.workers:
            raise RuntimeError(self.busy_message)
        worker = asyncio.create_task(asyncio.to_thread(operation, *args))
        self.workers.add(worker)
        worker.add_done_callback(self.finished)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            await asyncio.gather(asyncio.shield(worker), return_exceptions=True)
            raise

    async def close(self):
        self.closing = True
        await asyncio.gather(
            *(asyncio.shield(task) for task in self.workers), return_exceptions=True
        )
