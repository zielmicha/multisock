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

class Test(unittest.TestCase):
    def setUp(self):
        self.thread = multisock.SocketThread()
        self.thread.start()

    def test_handlers(self):
        for i in xrange(10):
            addr = 'tcp:localhost:56%02d' % i
            acceptor = self.thread.listen(addr)

            def accepted(sock):
                ch = sock.get_main_channel()
                ch.recv.bind(ch.send_async)
            
            acceptor.bind(accepted)

            client = self.thread.connect(addr)

            def send(channel):
                channel.send_async('hello')
                channel.recv.bind(lambda data: recv(channel, data))
            
            def recv(channel, data):
                assert data == 'hello', repr(data)
            
            for i in xrange(10):
                send(client.get_main_channel())
            
    def test_threads(self):
        for i in xrange(10):
            addr = 'tcp:localhost:55%02d' % i
            acceptor = self.thread.listen(addr)

            def server():
                for i in xrange(4):
                    client = acceptor().get_main_channel()
                    data = client.recv()
                    client.send_async(data)
                
            multisock.async(server)

            def client(i):
                sock = self.thread.connect(addr).get_main_channel()
                sock.send_async('123')
                self.assertEqual(sock.recv(), '123')
        
            for t in [ multisock.async(lambda: client(i)) for i in xrange(4) ]:
                t.join()

if __name__ == '__main__':
    unittest.main()
