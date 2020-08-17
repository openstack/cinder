# Copyright (C) 2020 leafcloud b.v.
# Copyright (C) 2020 FUJITSU LIMITED
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

from botocore.exceptions import ClientError
from botocore.exceptions import ConnectionError


class FakeS3Boto3(object):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    @classmethod
    def Client(cls, *args, **kargs):
        return FakeBoto3Client()


class FakeBoto3Client(object):
    """Logging calls instead of executing."""
    def __init__(self, *args, **kwargs):
        pass

    def list_objects(self, *args, **kwargs):
        return {u'Contents': [{u'Key': u'backup_001'},
                              {u'Key': u'backup_002'},
                              {u'Key': u'backup_003'}]}

    def list_buckets(self, *args, **kwargs):
        return {u'Buckets': [{u'Name': u's3cinderbucket'},
                             {u'Name': u's3bucket'}]}

    def head_bucket(self, *args, **kwargs):
        pass

    def get_object(self, Bucket, *args, **kwargs):
        if Bucket == 's3_api_failure':
            raise ClientError(
                error_response={
                    'Error': {'Code': 'MyCode', 'Message': 'MyMessage'}},
                operation_name='myoperation')
        if Bucket == 's3_connection_error':
            raise ConnectionError(error='MyMessage')

    def create_bucket(self, *args, **kwargs):
        pass

    def put_object(self, Bucket, *args, **kwargs):
        if Bucket == 's3_api_failure':
            raise ClientError(
                error_response={
                    'Error': {'Code': 'MyCode', 'Message': 'MyMessage'}},
                operation_name='myoperation')
        if Bucket == 's3_connection_error':
            raise ConnectionError(error='MyMessage')
