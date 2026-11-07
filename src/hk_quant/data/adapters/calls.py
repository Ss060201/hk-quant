"""Run third-party clients in a killable process with a finite time budget."""
from __future__ import annotations
import multiprocessing as mp


def _worker(connection, name, kwargs):
    try:
        import akshare
        connection.send((True,getattr(akshare,name)(**kwargs)))
    except Exception as exc:
        connection.send((False,f"{type(exc).__name__}: {exc}"[:400]))
    finally:
        connection.close()


def call_akshare(name, *, timeout=45, **kwargs):
    ctx=mp.get_context("spawn")
    receiver,sender=ctx.Pipe(duplex=False)
    process=ctx.Process(target=_worker,args=(sender,name,kwargs),daemon=True)
    process.start();sender.close()
    try:
        if not receiver.poll(timeout):
            raise TimeoutError(f"{name} exceeded {timeout}s")
        ok,result=receiver.recv()
        if not ok:raise RuntimeError(result)
        return result
    finally:
        receiver.close()
        process.join(timeout=.1)
        if process.is_alive():process.terminate();process.join(timeout=2)
