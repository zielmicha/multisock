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

import unittest

import multisock
import socket
import functools

class Test(unittest.TestCase):
    def setUp(self):
        self.thread = multisock.SocketThread()
        self.thread.start()

    def test_handlers(self):
        self._test_data(6, 'hello')
        self._test_data(8, 'hello' * 7000)

    def _test_data(self, portprefix, s):
        for i in xrange(10):
            addr = 'tcp:localhost:5%d%02d' % (portprefix, i)
            acceptor = self.thread.listen(addr)

            def accepted(sock):
                ch = sock.get_main_channel()
                ch.recv.bind(ch.send_async)
            
            acceptor.accept.bind(accepted)

            client = self.thread.connect(addr)

            def send(channel, expdata):
                channel.send_async(expdata)
                channel.recv.bind(lambda data: recv(channel, data, expdata))
            
            def recv(channel, data, expdata):
                assert data == expdata, repr(data)

            main = client.get_main_channel()
            for i in xrange(10):
                send(main, 'hello')

            
    def test_threads(self):
        for i in xrange(10):
            addr = 'tcp:localhost:55%02d' % i
            acceptor = self.thread.listen(addr)

            def server():
                for i in xrange(4):
                    client = acceptor.accept().get_main_channel()
                    data = client.recv()
                    client.send_async(data)
                
            multisock.async(server)

            def client(i):
                sock = self.thread.connect(addr).get_main_channel()
                sock.send_async('123')
                self.assertEqual(sock.recv(), '123')
        
            for t in [ multisock.async(lambda: client(i)) for i in xrange(4) ]:
                t.join()

    def test_channels(self):
        for i in xrange(10):
            addr = 'tcp:localhost:57%02d' % i
            acceptor = self.thread.listen(addr)

            def accepted(sock):
                ch = sock.get_main_channel()
                new_channel = sock.new_channel()
                for i in xrange(3):
                    ch.send_async(str(new_channel.id))
                    new_channel.recv.bind(functools.partial(lambda c, a: c.send_async(a), new_channel))
            
            acceptor.accept.bind(accepted)

            client = self.thread.connect(addr)

            main = client.get_main_channel()

            def test_echo(channel, i):
                msg = str(i)
                for i in xrange(5):
                    channel.send_async(msg)
                    assert channel.recv() == msg
            
            for i in xrange(3):
                channel_id = int(main.recv())
                channel = client.get_channel(channel_id)
                test_echo(channel, i)

    def test_rpc(self):
        addr = 'tcp:localhost:5902'
        acceptor = self.thread.listen(addr)
        client = self.thread.connect(addr)
        server = acceptor.accept()

        client_ch = multisock.RpcChannel(client.get_main_channel())
        server_ch = multisock.RpcChannel(server.get_main_channel())

        def echo_rpc((data, return_)):
            return_(data)
        
        server_ch.rpc_recv.bind(echo_rpc)
        for i in xrange(10):
            msg = str(i)
            def check(a, b):
                assert a == b
            client_ch.rpc_send(msg).bind(functools.partial(check, msg))

        assert client_ch.rpc_send('hello')() == 'hello'

    def test_misc(self):
        addr = 'tcp:localhost:5901'
        acceptor = self.thread.listen(addr)
        client = self.thread.connect(addr)
        server = acceptor.accept()
        assert client.get_main_channel() is client.get_main_channel()

        assert client.new_channel().id != server.new_channel().id
        
        last = client.new_channel().id
        for i in xrange(200):
            new = client.new_channel().id
            assert new - last == 1
            last = new
        
    def test_close(self):
        addr = 'tcp:localhost:5904'
        acceptor = self.thread.listen(addr)
        acceptor.close()

        acceptor = self.thread.listen(addr)
        self.assertRaises(socket.error, self.thread.listen, addr)
        client = self.thread.connect(addr)
        client_ch = client.get_main_channel()
        server = acceptor.accept()

        server.close()
        for i in xrange(20):
            self.assertRaises(multisock.SocketClosedError, client_ch.recv)

if __name__ == '__main__':
    unittest.main()
