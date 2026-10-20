"""Exit straight away once a script's work is done.

On Ryan's Mac the Python process can hang at interpreter shutdown after
printing its final "Done" line (torch / the embedding model on the Apple GPU
tearing down; seen after the 222-minute podcast run and after every single
episode run). A hung process blocks anything chained after it -- a shell
`for` loop, or the nightly job's upload step. Everything these scripts write
is committed before they finish, so skipping the slow teardown loses nothing.
"""
import os
import sys
import traceback


def finish(code=0):
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(code)


def install():
    """Also covers an uncaught exception: print the traceback, then exit."""
    def hook(exc_type, exc, tb):
        traceback.print_exception(exc_type, exc, tb)
        finish(1)
    sys.excepthook = hook
