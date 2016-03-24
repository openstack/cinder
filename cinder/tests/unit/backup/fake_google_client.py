# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (C) 2016 Vedams Inc.
# Copyright (C) 2016 Google Inc.
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
import json
import os
import zlib

from googleapiclient import errors
from oauth2client import client
from oslo_utils import units
import six


class FakeGoogleObjectInsertExecute(object):

    def __init__(self, *args, **kwargs):
        self.container_name = kwargs['bucket']

    def execute(self, *args, **kwargs):
        if self.container_name == 'gcs_api_failure':
            raise errors.Error
        return {u'md5Hash': u'Z2NzY2luZGVybWQ1'}


class FakeGoogleObjectListExecute(object):

    def __init__(self, *args, **kwargs):
        self.container_name = kwargs['bucket']

    def execute(self, *args, **kwargs):
        if self.container_name == 'gcs_connection_failure':
            raise Exception

        return {'items': [{'name': 'backup_001'},
                          {'name': 'backup_002'},
                          {'name': 'backup_003'}]}


class FakeGoogleBucketListExecute(object):

    def __init__(self, *args, **kwargs):
        self.container_name = kwargs['prefix']

    def execute(self, *args, **kwargs):
        if self.container_name == 'gcs_oauth2_failure':
            raise client.Error
        return {u'items': [{u'name': u'gcscinderbucket'},
                           {u'name': u'gcsbucket'}]}


class FakeGoogleBucketInsertExecute(object):
    def execute(self, *args, **kwargs):
        pass


class FakeMediaObject(object):
    def __init__(self, *args, **kwargs):
        self.bucket_name = kwargs['bucket']
        self.object_name = kwargs['object']


class FakeGoogleObject(object):

    def insert(self, *args, **kwargs):
        return FakeGoogleObjectInsertExecute(*args, **kwargs)

    def get_media(self, *args, **kwargs):
        return FakeMediaObject(*args, **kwargs)

    def list(self, *args, **kwargs):
        return FakeGoogleObjectListExecute(*args, **kwargs)


class FakeGoogleBucket(object):

    def list(self, *args, **kwargs):
        return FakeGoogleBucketListExecute(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return FakeGoogleBucketInsertExecute()


class FakeGoogleDiscovery(object):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def Build(self, *args, **kargs):
        return FakeDiscoveryBuild()


class FakeDiscoveryBuild(object):
    """Logging calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    def objects(self):
        return FakeGoogleObject()

    def buckets(self):
        return FakeGoogleBucket()


class FakeGoogleCredentials(object):
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def from_stream(self, *args, **kwargs):
        pass


class FakeGoogleMediaIoBaseDownload(object):
    def __init__(self, fh, req, chunksize=None):

        if 'metadata' in req.object_name:
            metadata = {}
            metadata['version'] = '1.0.0'
            metadata['backup_id'] = 123
            metadata['volume_id'] = 123
            metadata['backup_name'] = 'fake backup'
            metadata['backup_description'] = 'fake backup description'
            metadata['created_at'] = '2016-01-09 11:20:54,805'
            metadata['objects'] = [{
                'backup_001': {'compression': 'zlib', 'length': 10,
                               'offset': 0},
                'backup_002': {'compression': 'zlib', 'length': 10,
                               'offset': 10},
                'backup_003': {'compression': 'zlib', 'length': 10,
                               'offset': 20}
            }]
            metadata_json = json.dumps(metadata, sort_keys=True, indent=2)
            if six.PY3:
                metadata_json = metadata_json.encode('utf-8')
            fh.write(metadata_json)
        else:
            fh.write(zlib.compress(os.urandom(units.Mi)))

    def next_chunk(self, **kwargs):
        return (100, True)
