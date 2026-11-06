"""Tiny client for PPSSPP's remote debugger (WebSocket JSON API at ws://127.0.0.1:<port>/debugger).
Lets us drive the emulator without touching the desktop: press buttons, read game status, grab frames."""
import base64, json, os, socket, struct, time


class PPSSPP:
    def __init__(self, port, host='127.0.0.1', timeout=10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f'GET /debugger HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
               f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: debugger.ppsspp.org\r\n\r\n')
        self.s.sendall(req.encode())
        resp = b''
        while b'\r\n\r\n' not in resp:
            resp += self.s.recv(4096)
        head, self.buf = resp.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise RuntimeError(head.decode(errors='replace'))
        self.ticket = 0

    # --- framing
    def _send(self, text):
        data = text.encode()
        hdr = bytearray([0x81])
        n = len(data)
        if n < 126: hdr.append(0x80 | n)
        elif n < 65536: hdr += bytes([0x80 | 126]) + struct.pack('>H', n)
        else: hdr += bytes([0x80 | 127]) + struct.pack('>Q', n)
        mask = os.urandom(4)
        hdr += mask
        self.s.sendall(bytes(hdr) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(1 << 20)
            if not chunk: raise ConnectionError('closed')
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        msg = b''
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126: n = struct.unpack('>H', self._read(2))[0]
            elif n == 127: n = struct.unpack('>Q', self._read(8))[0]
            if b1 & 0x80: mask = self._read(4)
            payload = self._read(n)
            op = b0 & 0x0F
            if op == 9:      # ping -> pong
                continue
            msg += payload
            if b0 & 0x80:
                return msg.decode(errors='replace')

    def call(self, event, timeout=15, **params):
        self.ticket += 1
        t = str(self.ticket)
        self._send(json.dumps(dict(event=event, ticket=t, **params)))
        end = time.time() + timeout
        while time.time() < end:
            m = json.loads(self._recv())
            if m.get('ticket') == t or (m.get('event') == event and 'ticket' not in m):
                if m.get('event') == 'error':
                    raise RuntimeError(m.get('message'))
                return m
        raise TimeoutError(event)

    # --- helpers
    def press(self, button, frames=4, wait=0.35):
        self.call('input.buttons.press', button=button, duration=frames)
        time.sleep(wait)

    def screenshot(self, path):
        self.call('cpu.stepping')
        try:
            r = self.call('gpu.buffer.screenshot', type='base64')
        finally:
            self.call('cpu.resume')
        open(path, 'wb').write(base64.b64decode(r['base64']))
        return r.get('width'), r.get('height')


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    p = PPSSPP(int(sys.argv[1]))
    for cmd in sys.argv[2:]:
        op, _, arg = cmd.partition(':')
        if op == 'press':
            name, _, n = arg.partition('*')
            for _ in range(int(n or 1)): p.press(name)
        elif op == 'hold':
            name, _, fr = arg.partition('*'); p.call('input.buttons.press', button=name, duration=int(fr)); time.sleep(int(fr) / 60 + 0.2)
        elif op == 'wait': time.sleep(float(arg))
        elif op == 'shot': print('shot', arg, p.screenshot(arg))
        elif op == 'status': print(p.call('game.status'))
        elif op == 'raw': print(p.call(arg))
