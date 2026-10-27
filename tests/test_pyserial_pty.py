import threading
import time

import pytest

from morpheus_vlt.core.transport import PtyByteServer, PtyConfig

serial = pytest.importorskip("serial")



def test_pyserial_over_pty(tmp_path) -> None:
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

    ser = serial.Serial(str(tty_path), baudrate=9600, timeout=1)
    try:
        ser.write(b"ping")
        resp = ser.read(4)
        assert resp == b"PING"
    finally:
        ser.close()

    server.stop()
    thread.join(timeout=2.0)
