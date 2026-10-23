"""Resident memory of the server with "Ask your transactions" loaded, at Render's limits.

Run inside the PRODUCTION image, started with Render's limits (PowerShell; throwaway secrets, no
database needed):

    docker build -t polycoin-api:check backend
    docker run -d --name rag-memory --memory 512m --memory-swap 512m --cpus 0.1 `
      -e DJANGO_PRODUCTION=TRUE -e DJANGO_SECRET_KEY=check -e JWT_SIGNING_KEY=check-jwt `
      -e DJANGO_ALLOWED_HOSTS=localhost -e CSRF_TRUSTED_ORIGINS=http://localhost `
      -e FIELD_ENCRYPTION_KEYS=v1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= `
      -e FIELD_ENCRYPTION_ACTIVE_KEY=v1 polycoin-api:check
    docker exec rag-memory python -m ai.rag_memory gunicorn   # the real master and workers
    docker exec rag-memory python -m ai.rag_memory worker     # boot, then a 20,000-row search
    docker rm -f rag-memory

`worker` boots the way gunicorn's master does: config.wsgi sets Django up and loads the URLconf,
which loads the RAG libraries. With --preload the workers share those pages, so per-process RSS
counts them more than once; /sys/fs/cgroup/memory.current is the container's real total. Linux
only: it reads /proc. A measurement tool, never imported by the app.
"""

import gc
import os
import random
import sys
import time

DOCUMENTS = 20_000
TWO_WORKER_GATE_MB = 400  # leaves room in Render's 512 MB for a search and the master
RENDER_MB = 512


def _status(pid: str, field: str) -> int:
    with open(f"/proc/{pid}/status") as file:
        for line in file:
            if line.startswith(field + ":"):
                return int(line.split()[1])
    return 0


def _status_mb(pid: str, field: str) -> float:
    return _status(pid, field) / 1024  # the kernel reports memory in kB


def _rss() -> float:
    return _status_mb("self", "VmRSS")


def _reset_peak() -> bool:
    """Start VmHWM (peak resident memory) again from the current RSS. Linux 4.0+."""
    try:
        with open("/proc/self/clear_refs", "w") as file:
            file.write("5")
        return True
    except OSError:
        return False


def gunicorn() -> None:
    rows = []
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as file:
                cmdline = file.read().replace(b"\0", b" ").decode()
            ppid = _status(pid, "PPid")
        except OSError:
            continue  # the process ended while we looked
        if "gunicorn" in cmdline and "rag_memory" not in cmdline:
            rows.append((pid, ppid, _status_mb(pid, "VmRSS"), _status_mb(pid, "VmHWM")))
    pids = {pid for pid, *_ in rows}
    total = 0.0
    for pid, ppid, rss, peak in sorted(rows, key=lambda row: int(row[0])):
        role = "worker" if str(ppid) in pids else "master"
        total += rss
        print(f"{role:<7} pid {pid:>5}: RSS {rss:6.1f} MB, peak {peak:6.1f} MB")
    print(f"total   RSS {total:.1f} MB of {RENDER_MB} MB")


def worker() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    started = time.perf_counter()
    import config.wsgi  # noqa: F401  what every worker loads: Django, every view, the RAG libraries

    boot_seconds = time.perf_counter() - started
    import numpy as np
    from django.conf import settings

    from ai import rag_fakes as fakes
    from ai.rag import codec
    from ai.rag import retriever as r
    from ai.rag.profiles import UNTUNED

    gc.collect()
    booted = _rss()

    # Stand-in for the SQL result: encrypted payloads as the query would return them. AES-GCM
    # with a throwaway key, the same primitive and blob size as vault (no database here).
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    aead, aad = AESGCM(AESGCM.generate_key(bit_length=256)), b"memory:rag.doc"
    rng, np_rng = random.Random(1), np.random.default_rng(1)
    blobs = []
    for _ in range(0, DOCUMENTS, 1_000):
        for vector in fakes.unit_vectors(np_rng, 1_000):
            nonce = os.urandom(12)
            blobs.append(nonce + aead.encrypt(nonce, codec.pack(vector, fakes.fake_text(rng)), aad))
    categories = [rng.choice(["Food", "Bills", "Transport", "Shopping"]) for _ in blobs]
    gc.collect()
    loaded = _rss()

    # The retriever's own steps, in its order, minus SQL (EncryptedHybridRetriever._search).
    peak_reset = _reset_peak()
    started = time.perf_counter()
    with r.gc_paused():
        payloads = [aead.decrypt(blob[:12], blob[12:], aad) for blob in blobs]
        matrix, texts = codec.unpack_many(payloads, fakes.DIMS)
        del payloads
        corpus = [r.tokenize(f"{text} {category}") for text, category in zip(texts, categories)]
        query = r.remove_stopwords(r.tokenize(fakes.fake_question(rng)))
        limit = settings.RAG_MAX_MATCHES
        keyword = r.rank(r.bm25_scores(query, corpus), r.keyword_presence(query, corpus), limit)
        cosine = r.cosine_scores(fakes.unit_vectors(np_rng, 1)[0], matrix)
        matches = r.vector_matches(cosine, UNTUNED, settings.RAG_RELATIVE_MARGIN)
        vector = r.rank(cosine, matches, limit)
        best = r.rrf_fuse([keyword, vector], settings.RAG_RRF_K, limit)
    ask_seconds = time.perf_counter() - started
    peak = _status_mb("self", "VmHWM")

    del blobs, categories, matrix, texts, corpus, cosine, best
    gc.collect()
    after = _rss()

    print(
        f"worker after boot (Django, views, RAG libraries)  {booted:6.1f} MB, took {boot_seconds:.2f} s"
    )
    print(f"+ {DOCUMENTS:,} encrypted payloads loaded           {loaded:6.1f} MB")
    print(
        f"peak during the search                           {peak:6.1f} MB"
        f"{'' if peak_reset else ' (peak not reset: includes setup)'}"
        f", search without SQL took {ask_seconds:.2f} s"
    )
    print(
        f"after the search, payloads released               {after:6.1f} MB (a long-lived worker keeps this)"
    )
    two_idle = 2 * booted
    print(
        f"\nTwo idle workers: {two_idle:.0f} MB -> gate <= {TWO_WORKER_GATE_MB} MB: "
        f"{'PASS' if two_idle <= TWO_WORKER_GATE_MB else 'FAIL'}"
    )
    print(
        f"Worst case, one idle worker + one mid-search: {booted + peak:.0f} MB "
        f"of {RENDER_MB} MB (add the master from the `gunicorn` mode)"
    )


if __name__ == "__main__":
    modes = {"gunicorn": gunicorn, "worker": worker}
    if len(sys.argv) != 2 or sys.argv[1] not in modes:
        sys.exit("usage: python -m ai.rag_memory gunicorn|worker")
    modes[sys.argv[1]]()
