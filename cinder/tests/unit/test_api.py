
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Unit tests for the API endpoint."""

from http import client as http_client
import io

import webob


class FakeHttplibSocket(object):
    """A fake socket implementation for http_client.HTTPResponse, trivial."""
    def __init__(self, response_string):
        self.response_string = response_string
        self._buffer = io.StringIO(response_string)

    def makefile(self, _mode, _other):
        """Returns the socket's internal buffer."""
        return self._buffer


class FakeHttplibConnection(object):
    """A fake http_client.HTTPConnection for boto.

    requests made via this connection actually get translated and routed into
    our WSGI app, we then wait for the response and turn it back into
    the http_client.HTTPResponse that boto expects.
    """
    def __init__(self, app, host, is_secure=False):
        self.app = app
        self.host = host

    def request(self, method, path, data, headers):
        req = webob.Request.blank(path)
        req.method = method
        req.body = data
        req.headers = headers
        req.headers['Accept'] = 'text/html'
        req.host = self.host
        # Call the WSGI app, get the HTTP response
        resp = str(req.get_response(self.app))
        # For some reason, the response doesn't have "HTTP/1.0 " prepended; I
        # guess that's a function the web server usually provides.
        resp = "HTTP/1.0 %s" % resp
        self.sock = FakeHttplibSocket(resp)
        self.http_response = http_client.HTTPResponse(self.sock)
        # NOTE(vish): boto is accessing private variables for some reason
        self._HTTPConnection__response = self.http_response
        self.http_response.begin()

    def getresponse(self):
        return self.http_response

    def getresponsebody(self):
        return self.sock.response_string

    def close(self):
        """Required for compatibility with boto/tornado."""
        pass
