# Copyright (c) 2012, Michal Zielinski <michal@zielinscy.org.pl>
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
# 
#     * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
# 
#     * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

'''
class Socket:
    remote_address
    get_main_channel() -> Channel
    get_channel(id -> int) -> Channel
    new_channel() -> Channel
    
class Channel:
    send(data -> str)
    send_async(data -> str)
    recv -> Operation

class RpcChannel
    rpc_send(data -> str) -> Operation
    rpc_recv -> Operation -- operation returns function that should be
        called with response - this functions is async

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
        self.socket_objects = {}
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
        set_thread_name('multisockselect')
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

        #print 'select', polled_read_sockets + polled_accept_sockets, polled_write_sockets
        readable_sockets, writable_sockets, error_sockets = select.select(polled_read_sockets + polled_accept_sockets,
                                                                          polled_write_sockets,
                                                                          polled_read_sockets + polled_accept_sockets + polled_write_sockets)
        #print '----->', readable_sockets, writable_sockets, error_sockets
        
        # even if select was not interrupted by writing to pipe, next select will use
        # new data (see first comment)
        with self.main_lock:
            self._interrupted = True
            
        def _send_nonblock(sock, data):
            try:
                return sock.send(data)
            except socket.error: # TODO: check EAGAIN
                return 0
        
        for sock in error_sockets:
            self.socket_objects[sock].close()

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
                os.read(self._interrupt_pipe_r, 1)
            else:
                data = sock.recv(4096)
                if not data:
                    self.socket_objects[sock].close()
                else:
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
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addr)
        sock.listen(1)

        acceptor = Acceptor(self, sock)
        self.socket_objects[sock] = acceptor
        return acceptor

    def start(self):
        self.thread = threading.Thread(target=self.loop, name='multisock select')
        self.thread.daemon = True
        self.thread.start()

class Acceptor(object):
    def __init__(self, thread, socket):
        self._socket = socket
        self.accept = Operation()
        self._thread = thread
        with self._thread.main_lock:
            self._thread.polled_accept_sockets.append(self._socket)
            self._thread.on_receive[self._socket] = \
                lambda (sock, addr): self.accept.dispatch(Socket(self._thread, sock, is_client=False))
            self._thread._interrupt_select()

    def close(self):
        with self._thread.main_lock:
            del self._thread.socket_objects[self._socket]
            self._thread.polled_accept_sockets.remove(self._socket)
        self._socket.close()
        
class Socket(object):
    def __init__(self, thread, sock, is_client):
        self.closed = False
        self._thread = thread
        self._socket = sock
        with self._thread.main_lock:
            self._thread.on_receive[self._socket] = self._received
            self._thread.polled_read_sockets.append(self._socket)
            self._thread._interrupt_select()
            self._thread.socket_objects[self._socket] = self

        self._buffer_list = collections.deque()
        self._buffer_len = 0

        self._channels = {}
        self._next_channel_id = 1
        self._is_client = is_client

    def _write_async(self, data):
        self.check_not_closed()
        self._thread._write_async(self._socket, data)

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
                self._buffer_list.appendleft(data[-size_to_pushback:])
                buff.append(data[:-size_to_pushback])
                break
            else:
                buff.append(data)

        packet = ''.join(buff)
        self._buffer_len -= len(packet)
        assert size + UINT32_SIZE == len(packet)
        return packet

    def _received_packet(self, packet):
        channel, = struct.unpack(UINT32_STRUCT, packet[UINT32_SIZE * 1: UINT32_SIZE * 2])
        data = packet[UINT32_SIZE * 2:]
        self.get_channel(channel)._received(data)

    def get_channel(self, id):
        if id not in self._channels:
            self._channels[id] = Channel(self, id)

        return self._channels[id]

    def get_main_channel(self):
        return self.get_channel(MSB_SYSTEM | SYSTEM_MAIN)
    
    def new_channel(self):
        id = self._next_channel_id
        self._next_channel_id += 1
        assert id < MAX_ID
        msb = MSB_CLIENT if self._is_client else MSB_SERVER
        return self.get_channel(msb | id)

    def check_not_closed(self):
        if self.closed:
            raise SocketClosedError('socket is closed')

    def close(self):
        self.closed = True
        self._socket.close()
        with self._thread.main_lock:
            self._thread.polled_read_sockets.remove(self._socket)
            del self._thread.socket_objects[self._socket]
            try:
                del self._thread.data_to_write[self._socket]
            except KeyError:
                pass

        for channel in self._channels.values():
            channel._closed()

class SocketClosedError(socket.error):
    pass

class Channel(object):
    def __init__(self, socket, id):
        self.socket = socket
        self.id = id
        self.recv = Operation()

    def _received(self, data):
        self.recv.dispatch(data)

    def _closed(self):
        self.recv.close()

    def send_async(self, data):
        header = struct.pack(UINT32_STRUCT, len(data) + UINT32_SIZE) + struct.pack(UINT32_STRUCT, self.id)
        self.socket._write_async(header + data)

RPC_REQUEST = 0x10000000
RPC_RESPONSE = 0x20000000
RPC_NUM_MASK = 0x0FFFFFFF

class RpcChannel(object):
    def __init__(self, channel):
        self._rpc_num = 0
        self.channel = channel
        self.channel.recv.bind(self._received)
        self.rpc_recv = Operation()
        self._operations = {}

    def _received(self, packet):
        flags_num, = struct.unpack(UINT32_STRUCT, packet[:UINT32_SIZE])
        num = RPC_NUM_MASK & flags_num
        data = packet[UINT32_SIZE:]
        if RPC_REQUEST & flags_num:
            def func(data):
                self._send(num | RPC_RESPONSE, data)
            
            self.rpc_recv.dispatch((data, func))
        elif RPC_RESPONSE & flags_num:
            # TODO: signal error if num not in _operations
            self._operations[num].dispatch(data)
        else:
            # TODO: signal error
            print 'Error: invalid flag'
        
    def rpc_send(self, data):
        self._rpc_num += 1
        num = self._rpc_num
        self._send(num | RPC_REQUEST, data)
        operation = Operation()
        self._operations[num] = operation
        return operation

    def _send(self, num, data):
        header = struct.pack(UINT32_STRUCT, num)
        self.channel.send_async(header + data)
        
class Operation(object):
    def __init__(self):
        self._callback = None
        self._closed = False
        self._queue = queue.Queue(0)
        # value that is passed to queue when Operation is closed
        self._special_close_value = object()

    def dispatch(self, data):
        self._check_closed()
        if self._callback:
            self._callback(data)
        else:
            self._queue.put(data)

    def bind(self, func):
        self._callback = func

    def _check_closed(self):
        if self._closed:
            raise SocketClosedError('socket is closed')

    def _check_close_val(self, val):
        if val is self._special_close_value:
            raise SocketClosedError('socket is closed')
        else:
            return val

    def close(self):
        # FIXME: this doesn't work reliably when more than 10 threads is
        # waiting on queue
        self._closed = True
        for i in xrange(10):
            self._queue.put(self._special_close_value)

    def __call__(self):
        assert not self._callback
        self._check_closed()
        return self._check_close_val(self._queue.get())

    def noblock(self):
        assert not self._callback
        self._check_closed()
        try:
            return self._check_close_val(self._queue.get_nowait())
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

def async(method):
    ' Simple helper method that starts new thread '
    t = threading.Thread(target=method)
    t.daemon = True
    t.start()
    return t

def listen(*args, **kwargs):
    return get_global_thread().listen(*args, **kwargs)

def connect(*args, **kwargs):
    return get_global_thread().connect(*args, **kwargs)

_global_thread = None

def get_global_thread():
    global _global_thread
    if not _global_thread:
        _global_thread = SocketThread()
        _global_thread.start()
    return _global_thread

try:
    import ctypes

    libc = ctypes.CDLL('libc.so.6')
    
    def set_thread_name(name):
        name = name[:15] + '\0'
        libc.prctl(15, name, 0, 0, 0)
    
except (ImportError, OSError):
    
    def set_thread_name(name):
        pass
