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

"""Implementation of a backup service that uses S3 as the backend

**Related Flags**

:backup_s3_endpoint_url: The url where the S3 server is listening.
                       (default: None)
:backup_s3_store_bucket: The S3 bucket to be used to store
                         the Cinder backup data. (default: volumebackups)
:backup_s3_store_access_key: The S3 query token access key. (default: None)
:backup_s3_store_secret_key: The S3 query token secret key. (default: None)
:backup_s3_sse_customer_key: The SSECustomerKey.
                             backup_s3_sse_customer_algorithm must be set at
                             the same time to enable SSE. (default: None)
:backup_s3_sse_customer_algorithm: The SSECustomerAlgorithm.
                                   backup_s3_sse_customer_key must be set at
                                   the same time to enable SSE. (default: None)
:backup_s3_object_size: The size in bytes of S3 backup objects.
                        (default: 52428800)
:backup_s3_block_size: The size in bytes that changes are tracked
                       for incremental backups. backup_s3_object_size
                       has to be multiple of backup_s3_block_size.
                       (default: 32768).
:backup_s3_md5_validation: Enable or Disable md5 validation in the s3 backend.
                           (default: True)
:backup_s3_http_proxy: Address or host for the http proxy server.
                       (default: '')
:backup_s3_https_proxy: Address or host for the https proxy server.
                        (default: '')
:backup_s3_timeout: The time in seconds till a timeout exception is thrown.
                    (default: 60)
:backup_s3_max_pool_connections: The maximum number of connections
                                 to keep in a connection pool. (default: 10)
:backup_s3_retry_max_attempts: An integer representing the maximum number of
                               retry attempts that will be made on
                               a single request.  (default: 4)
:backup_s3_retry_mode: A string representing the type of retry mode.
                       e.g: legacy, standard, adaptive. (default: legacy)
:backup_s3_verify_ssl: Enable or Disable ssl verify.
                          (default: True)
:backup_s3_ca_cert_file: A filename of the CA cert bundle to use.
                        (default: None)
:backup_s3_enable_progress_timer: Enable or Disable the timer to send the
                                  periodic progress notifications to
                                  Ceilometer when backing up the volume to the
                                  S3 backend storage. (default: True)
:backup_compression_algorithm: Compression algorithm to use for volume
                               backups. Supported options are:
                               None (to disable), zlib, bz2
                               and zstd. (default: zlib)
"""

import base64
import functools
import io
import itertools as it
import socket

import boto3
from botocore.config import Config
from botocore import exceptions as boto_exc
from botocore.vendored.requests.packages.urllib3 import exceptions as \
    urrlib_exc
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils.secretutils import md5
from oslo_utils import timeutils

from cinder.backup import chunkeddriver
from cinder import exception
from cinder.i18n import _
from cinder import interface

LOG = logging.getLogger(__name__)

s3backup_service_opts = [
    cfg.StrOpt('backup_s3_endpoint_url',
               help=_('The url where the S3 server is listening.')),
    cfg.StrOpt('backup_s3_store_access_key', secret=True,
               help=_('The S3 query token access key.')),
    cfg.StrOpt('backup_s3_store_secret_key', secret=True,
               help=_('The S3 query token secret key.')),
    cfg.StrOpt('backup_s3_store_bucket', default='volumebackups',
               help=_('The S3 bucket to be used '
                      'to store the Cinder backup data.')),
    cfg.IntOpt('backup_s3_object_size', default=52428800,
               help='The size in bytes of S3 backup objects'),
    cfg.IntOpt('backup_s3_block_size', default=32768,
               help='The size in bytes that changes are tracked '
                    'for incremental backups. backup_s3_object_size '
                    'has to be multiple of backup_s3_block_size.'),
    cfg.BoolOpt('backup_s3_enable_progress_timer', default=True,
                help='Enable or Disable the timer to send the periodic '
                     'progress notifications to Ceilometer when backing '
                     'up the volume to the S3 backend storage. The '
                     'default value is True to enable the timer.'),
    cfg.StrOpt('backup_s3_http_proxy', default='',
               help='Address or host for the http proxy server.'),
    cfg.StrOpt('backup_s3_https_proxy', default='',
               help='Address or host for the https proxy server.'),
    cfg.FloatOpt('backup_s3_timeout', default=60,
                 help='The time in seconds till '
                      'a timeout exception is thrown.'),
    cfg.IntOpt('backup_s3_max_pool_connections', default=10,
               help='The maximum number of connections '
                    'to keep in a connection pool.'),
    cfg.IntOpt('backup_s3_retry_max_attempts', default=4,
               help='An integer representing the maximum number of '
                    'retry attempts that will be made on a single request.'),
    cfg.StrOpt('backup_s3_retry_mode', default='legacy',
               help='A string representing the type of retry mode. '
                    'e.g: legacy, standard, adaptive'),
    cfg.BoolOpt('backup_s3_verify_ssl', default=True,
                help='Enable or Disable ssl verify.'),
    cfg.StrOpt('backup_s3_ca_cert_file', default=None,
               help='path/to/cert/bundle.pem '
                    '- A filename of the CA cert bundle to use.'),
    cfg.BoolOpt('backup_s3_md5_validation', default=True,
                help='Enable or Disable md5 validation in the s3 backend.'),
    cfg.StrOpt('backup_s3_sse_customer_key', default=None, secret=True,
               help='The SSECustomerKey. backup_s3_sse_customer_algorithm '
                    'must be set at the same time to enable SSE.'),
    cfg.StrOpt('backup_s3_sse_customer_algorithm', default=None,
               help='The SSECustomerAlgorithm. backup_s3_sse_customer_key '
                    'must be set at the same time to enable SSE.')
]

CONF = cfg.CONF
CONF.register_opts(s3backup_service_opts)
CONF.import_opt('backup_compression_algorithm', 'cinder.backup.chunkeddriver')


class S3ConnectionFailure(exception.BackupDriverException):
    message = _("S3 connection failure: %(reason)s")


class S3ClientError(exception.BackupDriverException):
    message = _("S3 client error: %(reason)s")


def _wrap_exception(func):
    @functools.wraps(func)
    def func_wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except boto_exc.ClientError as err:
            raise S3ClientError(reason=err)
        except Exception as err:
            raise S3ConnectionFailure(reason=err)

    return func_wrapper


@interface.backupdriver
class S3BackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete of backup objects within S3."""

    def __init__(self, context):
        chunk_size_bytes = CONF.backup_s3_object_size
        sha_block_size_bytes = CONF.backup_s3_block_size
        backup_bucket = CONF.backup_s3_store_bucket
        enable_progress_timer = CONF.backup_s3_enable_progress_timer
        super().__init__(
            context,
            chunk_size_bytes,
            sha_block_size_bytes,
            backup_bucket,
            enable_progress_timer,
        )
        config_args = dict(
            connect_timeout=CONF.backup_s3_timeout,
            read_timeout=CONF.backup_s3_timeout,
            max_pool_connections=CONF.backup_s3_max_pool_connections,
            retries={
                'max_attempts': CONF.backup_s3_retry_max_attempts,
                'mode': CONF.backup_s3_retry_mode})
        if CONF.backup_s3_http_proxy:
            config_args['proxies'] = {'http': CONF.backup_s3_http_proxy}
        if CONF.backup_s3_https_proxy:
            config_args.setdefault('proxies', {}).update(
                {'https': CONF.backup_s3_https_proxy})
        conn_args = {
            'aws_access_key_id': CONF.backup_s3_store_access_key,
            'aws_secret_access_key': CONF.backup_s3_store_secret_key,
            'endpoint_url': CONF.backup_s3_endpoint_url,
            'config': Config(**config_args)}
        if CONF.backup_s3_verify_ssl:
            conn_args['verify'] = CONF.backup_s3_ca_cert_file
        else:
            conn_args['verify'] = False
        self.conn = boto3.client('s3', **conn_args)

    @staticmethod
    def get_driver_options():
        backup_opts = [CONF._opts['backup_compression_algorithm']['opt']]
        return s3backup_service_opts + backup_opts

    @_wrap_exception
    def put_container(self, bucket):
        """Create the bucket if not exists."""
        try:
            self.conn.head_bucket(Bucket=bucket)
        except boto_exc.ClientError as e:
            # NOTE: If it was a 404 error, then the bucket does not exist.
            error_code = e.response['Error']['Code']
            if error_code != '404':
                raise
            self.conn.create_bucket(Bucket=bucket)

    @_wrap_exception
    def get_container_entries(self, bucket, prefix):
        """Get bucket entry names."""
        paginator = self.conn.get_paginator('list_objects_v2')
        page_iterator = paginator.paginate(Bucket=bucket,
                                           Prefix=prefix)
        result = [obj_dict.get('Key') for obj_dict in it.chain.from_iterable(
            page.get('Contents') for page in page_iterator)]
        return result

    def get_object_writer(self, bucket, object_name, extra_metadata=None):
        """Return a writer object.

        Returns a writer object that stores a chunk of volume data in a
        S3 object store.
        """
        return S3ObjectWriter(bucket, object_name, self.conn)

    def get_object_reader(self, bucket, object_name, extra_metadata=None):
        """Return reader object.

        Returns a reader object that retrieves a chunk of backed-up volume data
        from a S3 object store.
        """
        return S3ObjectReader(bucket, object_name, self.conn)

    @_wrap_exception
    def delete_object(self, bucket, object_name):
        """Deletes a backup object from a S3 object store."""
        self.conn.delete_object(
            Bucket=bucket,
            Key=object_name)

    def _generate_object_name_prefix(self, backup):
        """Generates a S3 backup object name prefix.

        prefix = volume_volid/timestamp/az_saz_backup_bakid
        volid is volume id.
        timestamp is time in UTC with format of YearMonthDateHourMinuteSecond.
        saz is storage_availability_zone.
        bakid is backup id for volid.
        """
        az = 'az_%s' % self.az
        backup_name = '%s_backup_%s' % (az, backup.id)
        volume = 'volume_%s' % (backup.volume_id)
        timestamp = timeutils.utcnow().strftime("%Y%m%d%H%M%S")
        prefix = volume + '/' + timestamp + '/' + backup_name
        LOG.debug('generate_object_name_prefix: %s', prefix)
        return prefix

    def update_container_name(self, backup, container):
        """Use the bucket name as provided - don't update."""
        return

    def get_extra_metadata(self, backup, volume):
        """S3 driver does not use any extra metadata."""
        return

    def check_for_setup_error(self):
        required_options = ('backup_s3_endpoint_url',
                            'backup_s3_store_access_key',
                            'backup_s3_store_secret_key')
        for opt in required_options:
            val = getattr(CONF, opt, None)
            if not val:
                raise exception.InvalidConfigurationValue(option=opt,
                                                          value=val)
        if ((not CONF.backup_s3_sse_customer_algorithm)
                != (not CONF.backup_s3_sse_customer_key)):
            LOG.warning("Both the backup_s3_sse_customer_algorithm and "
                        "backup_s3_sse_customer_key options must be set "
                        "to enable SSE. SSE is disabled.")

        try:
            self.conn.list_buckets()
        except Exception:
            LOG.exception("Cannot list s3 buckets during backup "
                          "driver initialization.")
            raise


class S3ObjectWriter(object):
    def __init__(self, bucket, object_name, conn):
        self.bucket = bucket
        self.object_name = object_name
        self.conn = conn
        self.data = bytearray()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write(self, data):
        self.data += data

    @_wrap_exception
    def close(self):
        reader = io.BytesIO(self.data)
        contentmd5 = base64.b64encode(
            md5(self.data, usedforsecurity=False).digest()).decode('utf-8')
        put_args = {'Bucket': self.bucket,
                    'Body': reader,
                    'Key': self.object_name,
                    'ContentLength': len(self.data)}
        if CONF.backup_s3_md5_validation:
            put_args['ContentMD5'] = contentmd5
        if (CONF.backup_s3_sse_customer_algorithm
                and CONF.backup_s3_sse_customer_key):
            put_args.update(
                SSECustomerAlgorithm=CONF.backup_s3_sse_customer_algorithm,
                SSECustomerKey=CONF.backup_s3_sse_customer_key)
        self.conn.put_object(**put_args)
        return contentmd5


class S3ObjectReader(object):
    def __init__(self, bucket, object_name, conn):
        self.bucket = bucket
        self.object_name = object_name
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    @_wrap_exception
    def read(self):
        get_args = {'Bucket': self.bucket,
                    'Key': self.object_name}
        if (CONF.backup_s3_sse_customer_algorithm
                and CONF.backup_s3_sse_customer_key):
            get_args.update(
                SSECustomerAlgorithm=CONF.backup_s3_sse_customer_algorithm,
                SSECustomerKey=CONF.backup_s3_sse_customer_key)
        # NOTE: these retries account for errors that occur when streaming
        # down the data from s3 (i.e. socket errors and read timeouts that
        # occur after recieving an OK response from s3). Other retryable
        # exceptions such as throttling errors and 5xx errors are already
        # retried by botocore.
        last_exception = None
        for i in range(CONF.backup_s3_retry_max_attempts):
            try:
                resp = self.conn.get_object(**get_args)
                return resp.get('Body').read()
            except (socket.timeout, socket.error,
                    urrlib_exc.ReadTimeoutError,
                    boto_exc.IncompleteReadError) as e:
                last_exception = e
                continue
        raise S3ClientError(reason=last_exception)
