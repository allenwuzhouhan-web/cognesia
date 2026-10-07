"""Read-only RFC 6455 publication on the existing loopback HTTP listener.

Commands use the origin-checked HTTP endpoint. A slow viewer sees the most
recent immutable frame; it never queues or controls numerical integration.
"""
from __future__ import annotations
import base64
import hashlib
import json
import select
import struct
import time

from .workbench_api import json_safe


def websocket_frame(payload, opcode=1):
    if isinstance(payload, str):
        payload = payload.encode('utf8')
    n = len(payload)
    header = bytes((0x80 | opcode, n)) if n < 126 else (
        bytes((0x80 | opcode, 126)) + struct.pack('!H', n) if n < 65536
        else bytes((0x80 | opcode, 127)) + struct.pack('!Q', n))
    return header + payload


def serve_stream(handler, state, session_id):
    origin = handler.headers.get('Origin')
    expected = {f'http://127.0.0.1:{handler.server.server_port}', f'http://localhost:{handler.server.server_port}'}
    if origin and origin not in expected:
        return handler.send_json({'error': 'Cross-origin streams are not allowed'}, 403)
    with state.lock:
        known=session_id in state.jobs
    if not known:
        return handler.send_json({'error': 'Unknown session'}, 404)
    try:
        key = handler.headers.get('Sec-WebSocket-Key', '')
        if len(base64.b64decode(key, validate=True)) != 16:
            raise ValueError()
        if handler.headers.get('Sec-WebSocket-Version') != '13' or handler.headers.get('Upgrade', '').lower() != 'websocket':
            raise ValueError()
    except (ValueError, TypeError):
        return handler.send_json({'error': 'A version 13 WebSocket handshake is required'}, 400)
    accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
    handler.protocol_version = 'HTTP/1.1'
    handler.send_response(101)
    handler.send_header('Upgrade', 'websocket')
    handler.send_header('Connection', 'Upgrade')
    handler.send_header('Sec-WebSocket-Accept', accept)
    handler.end_headers()
    handler.wfile.flush()
    handler.close_connection = True
    sock = handler.connection
    sock.settimeout(2.)
    last_sequence = -1; last_status = None; pending = bytearray()
    try:
        while True:
            with state.lock:
                job = dict(state.jobs[session_id])
                frame = state.frames.get(session_id)
            if frame and frame['sequence'] != last_sequence:
                payload = json.dumps({'type': 'frame', 'frame': json_safe(frame)}, allow_nan=False, separators=(',', ':'))
                sock.sendall(websocket_frame(payload))
                last_sequence = frame['sequence']
            status = json.dumps(json_safe(job), allow_nan=False, separators=(',', ':'))
            if status != last_status:
                sock.sendall(websocket_frame('{"type":"session","session":' + status + '}'))
                last_status = status
            if job['status'] in ('complete', 'cancelled', 'failed'):
                sock.sendall(websocket_frame(struct.pack('!H', 1000), 8))
                return
            if select.select([sock], [], [], .25)[0]:
                data = sock.recv(4096)
                if not data:return
                pending.extend(data)
                while len(pending) >= 2:
                    first, second = pending[:2]
                    length = second & 127
                    # Incoming controls are only close/ping/pong: FIN, no RSV,
                    # <=125 bytes and required client mask per RFC 6455.
                    if not first & 128 or first & 112 or not second & 128 or length > 125 or first & 15 not in (8, 9, 10):
                        sock.sendall(websocket_frame(struct.pack('!H', 1002), 8));return
                    if len(pending) < 6 + length:break
                    mask = pending[2:6]
                    content = bytes(value ^ mask[i % 4] for i, value in enumerate(pending[6:6 + length]))
                    del pending[:6 + length]
                    opcode = first & 15
                    if opcode == 8:
                        sock.sendall(websocket_frame(content, 8));return
                    if opcode == 9:sock.sendall(websocket_frame(content, 10))
    except (OSError, ValueError):
        # Disconnecting never cancels a running simulation.
        return
