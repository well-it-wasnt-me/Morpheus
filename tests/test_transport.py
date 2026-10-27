import os
import select
import socket
import threading
import time

from morpheus_vlt.core.transport import PtyByteServer, PtyConfig, ServerConfig, TCPByteServer


def _find_free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_tcp_byte_server_echo() -> None:
    port = _find_free_port()

    def handler(data: bytes) -> bytes:
        return data.upper()

    server = TCPByteServer(ServerConfig(host="127.0.0.1", port=port), handler)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    conn = None
    while time.time() < deadline:
        try:
            conn = socket.create_connection(("127.0.0.1", port), timeout=1.0)
            break
        except OSError:
            time.sleep(0.01)
    assert conn is not None

    with conn:
        conn.sendall(b"ping")
        resp = conn.recv(4)
        assert resp == b"PING"

    server.stop()
    thread.join(timeout=2.0)


def test_pty_byte_server_echo(tmp_path) -> None:
    def handler(data: bytes) -> bytes:
        return data.upper()

    tty_path = tmp_path / "ttyMODEM"
    server = PtyByteServer(PtyConfig(link_path=str(tty_path)), handler)
    thread = threading.Thread(target=server.start, daemon=True)
    thread.start()

    deadline = time.time() + 2.0
    while time.time() < deadline and not tty_path.exists():
        time.sleep(0.01)
    assert tty_path.exists()

    fd = os.open(str(tty_path), os.O_RDWR | os.O_NOCTTY)
    try:
        os.write(fd, b"ping")
        readable, _, _ = select.select([fd], [], [], 2.0)
        assert readable
        resp = os.read(fd, 4)
        assert resp == b"PING"
    finally:
        os.close(fd)

    server.stop()
    thread.join(timeout=2.0)
