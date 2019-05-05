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
import os
import tempfile


class FakeGoogleObjectInsertExecute(object):

    def execute(self, *args, **kwargs):
        return {u'md5Hash': u'Z2NzY2luZGVybWQ1'}


class FakeGoogleObjectListExecute(object):

    def __init__(self, *args, **kwargs):
        self.bucket_name = kwargs['bucket']
        self.prefix = kwargs['prefix']

    def execute(self, *args, **kwargs):
        bucket_dir = tempfile.gettempdir() + '/' + self.bucket_name
        fake_body = []
        for f in os.listdir(bucket_dir):
            try:
                f.index(self.prefix)
                fake_body.append({'name': f})
            except Exception:
                pass

        return {'items': fake_body}


class FakeGoogleBucketListExecute(object):

    def execute(self, *args, **kwargs):
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
        object_path = (tempfile.gettempdir() + '/' + kwargs['bucket'] + '/' +
                       kwargs['name'])
        kwargs['media_body']._fd.getvalue()
        with open(object_path, 'wb') as object_file:
            kwargs['media_body']._fd.seek(0)
            object_file.write(kwargs['media_body']._fd.read())

        return FakeGoogleObjectInsertExecute()

    def get_media(self, *args, **kwargs):
        return FakeMediaObject(*args, **kwargs)

    def list(self, *args, **kwargs):
        return FakeGoogleObjectListExecute(*args, **kwargs)


class FakeGoogleBucket(object):

    def list(self, *args, **kwargs):
        return FakeGoogleBucketListExecute()

    def insert(self, *args, **kwargs):
        return FakeGoogleBucketInsertExecute()


class FakeGoogleDiscovery(object):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def Build(cls, *args, **kargs):
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
    def from_stream(cls, *args, **kwargs):
        pass


class FakeGoogleMediaIoBaseDownload(object):
    def __init__(self, fh, req, chunksize=None):
        object_path = (tempfile.gettempdir() + '/' + req.bucket_name + '/' +
                       req.object_name)
        with open(object_path, 'rb') as object_file:
            fh.write(object_file.read())

    def next_chunk(self, **kwargs):
        return (100, True)
