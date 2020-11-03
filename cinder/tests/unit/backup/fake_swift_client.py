# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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

from http import client as http_client
import json
import os
import socket
import zlib

from swiftclient import client as swift


class FakeSwiftClient(object):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def Connection(cls, *args, **kargs):
        return FakeSwiftConnection()


class FakeSwiftConnection(object):
    """Logging calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    def head_container(self, container):
        if container in ['missing_container',
                         'missing_container_socket_error_on_put']:
            raise swift.ClientException('fake exception',
                                        http_status=http_client.NOT_FOUND)
        elif container == 'unauthorized_container':
            raise swift.ClientException('fake exception',
                                        http_status=http_client.UNAUTHORIZED)
        elif container == 'socket_error_on_head':
            raise socket.error(111, 'ECONNREFUSED')
        pass

    def put_container(self, container, headers=None):
        if container == 'missing_container_socket_error_on_put':
            raise socket.error(111, 'ECONNREFUSED')

    def get_container(self, container, **kwargs):
        fake_header = None
        fake_body = [{'name': 'backup_001'},
                     {'name': 'backup_002'},
                     {'name': 'backup_003'}]
        return fake_header, fake_body

    def head_object(self, container, name):
        return {'etag': 'fake-md5-sum'}

    def get_object(self, container, name):
        if container == 'socket_error_on_get':
            raise socket.error(111, 'ECONNREFUSED')
        if 'metadata' in name:
            fake_object_header = None
            metadata = {}
            if container == 'unsupported_version':
                metadata['version'] = '9.9.9'
            else:
                metadata['version'] = '1.0.0'
            metadata['backup_id'] = 123
            metadata['volume_id'] = 123
            metadata['backup_name'] = 'fake backup'
            metadata['backup_description'] = 'fake backup description'
            metadata['created_at'] = '2013-02-19 11:20:54,805'
            metadata['objects'] = [{
                'backup_001': {'compression': 'zlib', 'length': 10,
                               'offset': 0},
                'backup_002': {'compression': 'zlib', 'length': 10,
                               'offset': 10},
                'backup_003': {'compression': 'zlib', 'length': 10,
                               'offset': 20}
            }]
            metadata_json = json.dumps(metadata, sort_keys=True, indent=2)
            metadata_json = metadata_json.encode('utf-8')
            fake_object_body = metadata_json
            return (fake_object_header, fake_object_body)

        fake_header = None
        fake_object_body = os.urandom(1024 * 1024)
        return (fake_header, zlib.compress(fake_object_body))

    def put_object(self, container, name, reader, content_length=None,
                   etag=None, chunk_size=None, content_type=None,
                   headers=None, query_string=None):
        if container == 'socket_error_on_put':
            raise socket.error(111, 'ECONNREFUSED')
        return 'fake-md5-sum'

    def delete_object(self, container, name):
        if container == 'socket_error_on_delete':
            raise socket.error(111, 'ECONNREFUSED')
        pass
