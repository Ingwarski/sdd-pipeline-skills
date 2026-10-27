"""Private SDK observer entrypoint; inherit pipes from the direct owner Node."""
from pathlib import Path
import argparse
import json
import os
import select
import socket
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evidence.io import EvidenceError
from evidence.observed_writers import Observer, MAX_REQUEST, canonical
from evidence.producer_runtime import _environment_ledger


def validate_control_fd(fd):
    info = os.fstat(fd)
    if stat.S_ISFIFO(info.st_mode):
        # Named FIFOs are external rendezvous points; only inherited anonymous
        # pipes have zero links on supported POSIX systems.
        if info.st_nlink != 0:
            raise EvidenceError('observer control FIFO is named, not anonymous')
        return
    if not stat.S_ISSOCK(info.st_mode):
        raise EvidenceError('observer control descriptor must be an anonymous pipe/socketpair')
    # Duplicate before wrapping so context-manager close cannot close the Node
    # descriptor. Let Python infer the actual kernel socket family/type.
    with socket.socket(fileno=os.dup(fd)) as control:
        if (control.family != socket.AF_UNIX
                or control.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
                or control.getsockname() not in ('', b'') or control.getpeername() not in ('', b'')):
            raise EvidenceError('observer control socket must be anonymous connected AF_UNIX SOCK_STREAM')


def run(owner_pid, read_fd, write_fd, working_reservation_id, runtime_file_limit=10000):
    observer, ledger = None, None
    try:
        if read_fd == write_fd or min(read_fd, write_fd) < 3:
            raise EvidenceError('observer requires separate private inherited pipe descriptors')
        for fd in (read_fd, write_fd):
            validate_control_fd(fd)
            os.set_blocking(fd, False)
        ledger, attempt = _environment_ledger()
        observer = Observer(ledger, attempt, owner_pid, working_reservation_id, runtime_file_limit=runtime_file_limit)
        buffer = b''
        deadline = time.monotonic() + 30
        while True:
            ready, _, _ = select.select([read_fd], [], [], .005)
            if ready:
                chunk = os.read(read_fd, MAX_REQUEST + 1)
                if not chunk:
                    raise EvidenceError('observer control EOF without durable closure')
                buffer += chunk
                if len(buffer) > MAX_REQUEST:
                    raise EvidenceError('observer request/queue exceeds byte bound')
                if b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    if buffer:
                        raise EvidenceError('observer requires one outstanding bounded command')
                    request = json.loads(line)
                    result = observer.request(request)
                    reply = (canonical(dict(ok=True, result=result)) + '\n').encode()
                    if len(reply) > MAX_REQUEST:
                        raise EvidenceError('observer response exceeds byte bound')
                    # Bounded nonblocking ACK: lost/partial delivery latches history.
                    end = time.monotonic() + 3
                    while reply:
                        if time.monotonic() >= end:
                            raise EvidenceError('observer durable ACK delivery timeout')
                        _, writable, _ = select.select([], [write_fd], [], min(.02, max(0, end - time.monotonic())))
                        if writable:
                            count = os.write(write_fd, reply)
                            reply = reply[count:]
                    deadline = time.monotonic() + 30
                    if request['command'] == 'close':
                        return 0
            observer.sample()
            if observer.value['state'] == 'arming' and time.monotonic() >= deadline:
                raise EvidenceError('observer root arming deadline expired')
    except BaseException as exc:
        if observer is not None:
            try:
                observer.fail(str(exc) or type(exc).__name__, lost=True)
            except BaseException:
                pass  # Existing nonclosed durable session still blocks every finalizer.
        try:
            payload = (canonical(dict(ok=False, problem=str(exc)[:1024])) + '\n').encode()
            os.write(write_fd, payload)
        except (OSError, ValueError):
            pass
        return 1
    finally:
        if observer is not None:
            try:
                observer.shutdown_sampler()
            except BaseException:
                pass  # Nonclosed/failed journal continues to retain every hold.
        if ledger is not None:
            ledger.close()
        for fd in set((read_fd, write_fd)):
            try:
                os.close(fd)
            except OSError:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner-pid', type=int, required=True)
    parser.add_argument('--control-read-fd', type=int, required=True)
    parser.add_argument('--control-write-fd', type=int, required=True)
    parser.add_argument('--working-reservation-id', required=True)
    parser.add_argument('--runtime-file-limit', type=int, default=10000)
    args = parser.parse_args()
    raise SystemExit(run(args.owner_pid, args.control_read_fd, args.control_write_fd, args.working_reservation_id, args.runtime_file_limit))
