'''
class Socket:
    remote_address
    get_main_channel() -> Channel
    get_channel(id -> int) -> Channel
    
class Channel:
    send(data -> str)
    send_async(data -> str)
    recv -> Operation

class Operation:
    __call__() -> T
    noblock() -> T
    bind(func)

class SocketThread
    connect(uri) -> Socket
    listen(uri) -> Operation
'''
import socket
import select
import threading
import time
import os
import collections
import struct
import Queue as queue

UINT32_SIZE = 4
UINT32_STRUCT = '!I'

MSB_SYSTEM = 0x00000000
MSB_CLIENT = 0x10000000
MSB_SERVER = 0x20000000

SYSTEM_MAIN = 1

MAX_ID = 0xFFFFFFF

class SocketThread(object):
    def __init__(self):
        # TODO: delete closed sockets
        # TODO: handle socket close
        self.local = threading.local()
        self.local.in_socket_thread = False
        
        self.main_lock = threading.Lock() # todo: split locks

        self.polled_read_sockets = []
        self.polled_accept_sockets = []
        self.data_to_write = collections.defaultdict(collections.deque)
        self.on_receive = {}
        
        self._interrupt_pipe_r, self._interrupt_pipe_w = os.pipe()
        self._interrupted = False

    def loop(self):
        self._setup()
        try:
            while True:
                self._tick()
        finally:
            self.local.in_socket_thread = False

    def _setup(self):
        set_thread_name('multisock select')
        self.local.in_socket_thread = True
        
    def _tick(self):
        # if data to write is added before entering this lock (or after end of select call)
        # data is not written to pipe, because sockets for selects are not yet choosen
        with self.main_lock:
            polled_read_sockets = list(self.polled_read_sockets)
            polled_accept_sockets = list(self.polled_accept_sockets)
            polled_write_sockets = [ key for key, val in self.data_to_write.items() if val ]
            self._interrupted = False
        # if data to write is added after leaving this lock
        # interrupting code sees that select was not yet interrupted, so it writes to pipe
        # and select is exited immediately
        
        polled_read_sockets.append(self._interrupt_pipe_r)

        readable_sockets, writable_sockets, _ = select.select(polled_read_sockets + polled_accept_sockets, polled_write_sockets, [])

        # even if select was not interrupted by writing to pipe, next select will use
        # new data (see first comment)
        with self.main_lock:
            self._interrupted = True
        
        def _send_nonblock(sock, data):
            try:
                return sock.send(data)
            except socket.error: # TODO: check EAGAIN
                return 0
        
        for sock in writable_sockets:
            deque = self.data_to_write[sock]
            while deque: # other threads never pop, so we don't need to lock
                data = deque.popleft()
                bytes = _send_nonblock(sock, data)
                if bytes != len(data):
                    deque.appendleft(data[bytes:])
                    break

        for sock in readable_sockets:
            if sock in self.polled_accept_sockets:
                self.on_receive[sock](sock.accept())
            elif sock == self._interrupt_pipe_r:
                pass
            else:
                data = sock.recv(4096)
                self.on_receive[sock](data)

    def _write_async(self, socket, data):
        with self.main_lock:
            assert len(data) != 0
            self.data_to_write[socket].append(data)
            self._interrupt_select()

    def _interrupt_select(self):
        # call only in self.main_lock
        if not self._interrupted:
            os.write(self._interrupt_pipe_w, '1')
            self._interrupted = True

    def _setup_socket(self, sock):
        sock.setblocking(False)
        
    def connect(self, uri):
        addr = _parse_tcp_uri(uri)
        sock = socket.socket()
        sock.connect(addr)
        self._setup_socket(sock)
        return Socket(self, sock, is_client=True)
        
    def listen(self, uri):
        addr = _parse_tcp_uri(uri)
        sock = socket.socket()
        sock.bind(addr)
        sock.listen(1)

        acceptor = Operation()
        with self.main_lock:
            self.polled_accept_sockets.append(sock)
            self.on_receive[sock] = lambda (sock, addr): acceptor.dispatch(Socket(self, sock, is_client=False))

        return acceptor

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='multisock select')
        self.thread.daemon = True
        self.thread.start()

class Socket(object):
    def __init__(self, thread, sock, is_client):
        self._thread = thread
        self._sock = sock
        with self._thread.main_lock:
            self._thread.on_receive[self._sock] = self._received
            self._thread.polled_read_sockets.append(self._sock)

        self._buffer_list = collections.deque()
        self._buffer_len = 0

        self._channels = {}
        self._next_channel_id = 1
        self._is_client = is_client

    def _write_async(self, data):
        self._thread._write_async(self._sock, data)

    def _received(self, data):
        self._buffer_len += len(data)
        if self._buffer_list and len(self._buffer_list[0]) < UINT32_SIZE:
            self._buffer_list[0] += data
        else:
            self._buffer_list.append(data)
            
        while self._buffer_len > UINT32_SIZE:
            size, = struct.unpack(UINT32_STRUCT, self._buffer_list[0][:UINT32_SIZE])
            if self._buffer_len >= UINT32_SIZE + size:
                packet = self._read_new_packet_from_buffer(size)
                self._received_packet(packet)
            else:
                break

    def _read_new_packet_from_buffer(self, size):
        size_left = size + UINT32_SIZE
        buff = []
        while True:
            data = self._buffer_list.popleft()
            size_left -= len(data)
            if size_left == 0:
                buff.append(data)
                break
            elif size_left < 0:
                size_to_pushback = -size_left
                self._buffer_list.appendleft(data[:-size_to_pushback])
                buff.append(data[-size_to_pushback:])
                break
            else:
                buff.append(data)

        packet = ''.join(buff)
        self._buffer_len -= len(packet)
        return packet

    def _received_packet(self, packet):
        channel, = struct.unpack(UINT32_STRUCT, packet[UINT32_SIZE * 1: UINT32_SIZE * 2])
        data = packet[UINT32_SIZE * 2:]
        self.get_channel_by_raw_id(channel)._received(data)

    def get_channel_by_raw_id(self, id):
        if id not in self._channels:
            self._channels[id] = Channel(self, id)

        return self._channels[id]

    def get_main_channel(self):
        return self.get_channel_by_raw_id(MSB_SYSTEM | SYSTEM_MAIN)
    
    def get_channel_by_id(self, id):
        assert id < MAX_ID
        msb = MSB_CLIENT if self._is_client else MSB_SERVER
        return get_channel_by_raw_id(msb | id)

class Channel(object):
    def __init__(self, socket, id):
        self.socket = socket
        self.id = id

        self.recv = Operation()

    def _received(self, data):
        self.recv.dispatch(data)

    def send_async(self, data):
        header = struct.pack(UINT32_STRUCT, len(data) + UINT32_SIZE) + struct.pack(UINT32_STRUCT, self.id)
        self.socket._write_async(header + data)

class Operation(object):
    def __init__(self):
        self._callback = None
        self._queue = queue.Queue(0)

    def dispatch(self, data):
        if self._callback:
            self._callback(data)
        else:
            self._queue.put(data)

    def bind(self, func):
        self._callback = func

    def __call__(self):
        assert not self._callback
        return self._queue.get()

    def noblock(self):
        assert not self._callback
        try:
            return self._queue.get_noblock()
        except queue.Empty:
            raise Operation.WouldBlock()

    class WouldBlock(Exception):
        pass
    
def _parse_tcp_uri(uri):
    if uri.startswith('tcp:'):
        host, port = uri[4:].rsplit(':')
        return host, int(port)
    else:
        raise ValueError('Not supported schema of %r' % uri)

try:
    import ctypes

    libc = ctypes.CDLL('libc.so.6')
    
    def set_thread_name(name):
        name = name[:15] + '\0'
        libc.prctl(15, name, 0, 0, 0)
    
except (ImportError, OSError):
    
    def set_thread_name(name):
        pass
