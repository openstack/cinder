# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (C) 2014 TrilioData, Inc
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

import hashlib
import os
import socket
import tempfile

from six.moves import http_client

from swiftclient import client as swift


class FakeSwiftClient2(object):
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def Connection(self, *args, **kargs):
        return FakeSwiftConnection2()


class FakeSwiftConnection2(object):
    def __init__(self, *args, **kwargs):
        self.tempdir = tempfile.mkdtemp()

    def head_container(self, container):
        if container == 'missing_container':
            raise swift.ClientException('fake exception',
                                        http_status=http_client.NOT_FOUND)
        elif container == 'unauthorized_container':
            raise swift.ClientException('fake exception',
                                        http_status=http_client.UNAUTHORIZED)
        elif container == 'socket_error_on_head':
            raise socket.error(111, 'ECONNREFUSED')

    def put_container(self, container):
        pass

    def get_container(self, container, **kwargs):
        fake_header = None
        container_dir = tempfile.gettempdir() + '/' + container
        fake_body = []
        for f in os.listdir(container_dir):
            try:
                f.index(kwargs['prefix'])
                fake_body.append({'name': f})
            except Exception:
                pass

        return fake_header, fake_body

    def head_object(self, container, name):
        return {'etag': 'fake-md5-sum'}

    def get_object(self, container, name):
        if container == 'socket_error_on_get':
            raise socket.error(111, 'ECONNREFUSED')
        object_path = tempfile.gettempdir() + '/' + container + '/' + name
        with open(object_path, 'rb') as object_file:
            return (None, object_file.read())

    def put_object(self, container, name, reader, content_length=None,
                   etag=None, chunk_size=None, content_type=None,
                   headers=None, query_string=None):
        object_path = tempfile.gettempdir() + '/' + container + '/' + name
        with open(object_path, 'wb') as object_file:
            object_file.write(reader.read())
        return hashlib.md5(reader.read()).hexdigest()

    def delete_object(self, container, name):
        pass
