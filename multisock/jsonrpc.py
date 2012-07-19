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
Example:
Server:
>>> channel = multisock.listen('tcp:localhost:5000').accept().get_main_channel()
>>> ch = JsonRpcChannel(channel)
>>> class RpcMethods:
    def rpc_greet(self, name):
        return 'Hello, ' + name
>>> ch.server = RpcMethods()
Client:
>>> channel = multisock.connect('tcp:localhost:5000').get_main_channel()
>>> ch = JsonRpcChannel(channel)
>>> ch.call.greet('Michal')
'Hello, Michal'
'''

import json
import multisock
import functools

class JsonRpcChannel(object):
    def __init__(self, channel, async=False):
        self._rpc = multisock.RpcChannel(channel)
        self.server = None
        self.call = _Proxy(self)
        if async:
            multisock.async(self._loop)
        else:
            self._rpc.rpc_recv.bind(self._recv)

    def _loop(self):
        multisock.set_thread_name('jsonrpc server')
        while True:
            result = self._rpc.rpc_recv()
            self._recv(result)
        
    def _recv(self, (data, return_)):
        def return_error(kind, text):
            return_(json.dumps({'error': kind, 'message': text}))
        
        call = json.loads(data)
        if not self.server:
            return_error('TypeError', 'Not expected any calls')
            return
            
        name = call['name']
        try:
            method = getattr(self.server, 'rpc_' + name)
        except AttributeError:
            return_error('AttributeError', 'No such method')
            return

        try:
            result = method(*call['args'], **call['kwargs'])
        except Exception as err:
            return_error(err.__class__.__name__, err.message)
        else:
            return_(json.dumps({'result': result}))

    def call_func(self, name, *args, **kwargs):
        data = json.dumps({'name': name, 'args': args, 'kwargs': kwargs})
        result = json.loads(self._rpc.rpc_send(data)())
        if 'error' in result:
            raise RemoteError(result['error'], result['message'])
        return result['result']

class _Proxy(object):
    def __init__(self, channel):
        self._channel = channel

    def __getattr__(self, name):
        return functools.partial(self._channel.call_func, name)
    
class RemoteError(Exception):
    pass

        
    
    
