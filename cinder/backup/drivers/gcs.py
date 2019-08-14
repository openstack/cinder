# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2014 TrilioData, Inc
# Copyright (c) 2015 EMC Corporation
# Copyright (C) 2015 Kevin Fox <kevin@efox.cc>
# Copyright (C) 2015 Tom Barron <tpb@dyncloud.net>
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

"""Implementation of a backup service using Google Cloud Storage(GCS)

Google Cloud Storage json apis are used for backup operations.
Authentication and authorization are based on OAuth2.0.
Server-centric flow is used for authentication.
"""

import base64
from distutils import version
import hashlib
import os

try:
    from google.auth import exceptions as gexceptions
    from google.oauth2 import service_account
    import google_auth_httplib2
except ImportError:
    service_account = google_auth_httplib2 = gexceptions = None

try:
    from oauth2client import client
except ImportError:
    client = None

import googleapiclient
from googleapiclient import discovery
from googleapiclient import errors
from googleapiclient import http
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
import six

from cinder.backup import chunkeddriver
from cinder import exception
from cinder.i18n import _
from cinder import interface


LOG = logging.getLogger(__name__)

gcsbackup_service_opts = [
    cfg.StrOpt('backup_gcs_bucket',
               help='The GCS bucket to use.'),
    cfg.IntOpt('backup_gcs_object_size',
               default=52428800,
               help='The size in bytes of GCS backup objects.'),
    cfg.IntOpt('backup_gcs_block_size',
               default=32768,
               help='The size in bytes that changes are tracked '
                    'for incremental backups. backup_gcs_object_size '
                    'has to be multiple of backup_gcs_block_size.'),
    cfg.IntOpt('backup_gcs_reader_chunk_size',
               default=2097152,
               help='GCS object will be downloaded in chunks of bytes.'),
    cfg.IntOpt('backup_gcs_writer_chunk_size',
               default=2097152,
               help='GCS object will be uploaded in chunks of bytes. '
                    'Pass in a value of -1 if the file '
                    'is to be uploaded as a single chunk.'),
    cfg.IntOpt('backup_gcs_num_retries',
               default=3,
               help='Number of times to retry.'),
    cfg.ListOpt('backup_gcs_retry_error_codes',
                default=['429'],
                help='List of GCS error codes.'),
    cfg.StrOpt('backup_gcs_bucket_location',
               default='US',
               help='Location of GCS bucket.'),
    cfg.StrOpt('backup_gcs_storage_class',
               default='NEARLINE',
               help='Storage class of GCS bucket.'),
    cfg.StrOpt('backup_gcs_credential_file',
               help='Absolute path of GCS service account credential file.'),
    cfg.StrOpt('backup_gcs_project_id',
               help='Owner project id for GCS bucket.'),
    cfg.StrOpt('backup_gcs_user_agent',
               default='gcscinder',
               help='Http user-agent string for gcs api.'),
    cfg.BoolOpt('backup_gcs_enable_progress_timer',
                default=True,
                help='Enable or Disable the timer to send the periodic '
                     'progress notifications to Ceilometer when backing '
                     'up the volume to the GCS backend storage. The '
                     'default value is True to enable the timer.'),
    cfg.URIOpt('backup_gcs_proxy_url',
               help='URL for http proxy access.',
               secret=True),

]

CONF = cfg.CONF
CONF.register_opts(gcsbackup_service_opts)
OAUTH_EXCEPTIONS = None


def gcs_logger(func):
    def func_wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except errors.Error as err:
            raise exception.GCSApiFailure(reason=err)
        except OAUTH_EXCEPTIONS as err:
            raise exception.GCSOAuth2Failure(reason=err)
        except Exception as err:
            raise exception.GCSConnectionFailure(reason=err)

    return func_wrapper


@interface.backupdriver
class GoogleBackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete of backup objects within GCS."""

    def __init__(self, context, db=None):
        global OAUTH_EXCEPTIONS
        backup_bucket = CONF.backup_gcs_bucket
        self.gcs_project_id = CONF.backup_gcs_project_id
        chunk_size_bytes = CONF.backup_gcs_object_size
        sha_block_size_bytes = CONF.backup_gcs_block_size
        enable_progress_timer = CONF.backup_gcs_enable_progress_timer
        super(GoogleBackupDriver, self).__init__(context, chunk_size_bytes,
                                                 sha_block_size_bytes,
                                                 backup_bucket,
                                                 enable_progress_timer,
                                                 db)
        self.reader_chunk_size = CONF.backup_gcs_reader_chunk_size
        self.writer_chunk_size = CONF.backup_gcs_writer_chunk_size
        self.bucket_location = CONF.backup_gcs_bucket_location
        self.storage_class = CONF.backup_gcs_storage_class
        self.num_retries = CONF.backup_gcs_num_retries

        # Set or overwrite environmental proxy variables for httplib2 since
        # it's the only mechanism supported when using googleapiclient with
        # google-auth
        if CONF.backup_gcs_proxy_url:
            os.environ['http_proxy'] = CONF.backup_gcs_proxy_url

        backup_credential = CONF.backup_gcs_credential_file
        # If we have google client that support google-auth library
        # (v1.6.0 or higher) and all required libraries are installed use
        # google-auth for the credentials
        if (version.LooseVersion(googleapiclient.__version__) >=
                version.LooseVersion('1.6.0') and service_account):
            creds = service_account.Credentials.from_service_account_file(
                backup_credential)
            OAUTH_EXCEPTIONS = (gexceptions.RefreshError,
                                gexceptions.DefaultCredentialsError,
                                client.Error)

        # Can't use google-auth, use deprecated oauth2client
        else:
            creds = client.GoogleCredentials.from_stream(backup_credential)
            OAUTH_EXCEPTIONS = client.Error

        self.conn = discovery.build('storage',
                                    'v1',
                                    # Avoid log error on oauth2client >= 4.0.0
                                    cache_discovery=False,
                                    credentials=creds)
        self.resumable = self.writer_chunk_size != -1

    @staticmethod
    def get_driver_options():
        return gcsbackup_service_opts

    def check_for_setup_error(self):
        required_options = ('backup_gcs_bucket', 'backup_gcs_credential_file',
                            'backup_gcs_project_id')
        for opt in required_options:
            val = getattr(CONF, opt, None)
            if not val:
                raise exception.InvalidConfigurationValue(option=opt,
                                                          value=val)

    @gcs_logger
    def put_container(self, bucket):
        """Create the bucket if not exists."""
        buckets = self.conn.buckets().list(
            project=self.gcs_project_id,
            prefix=bucket,
            fields="items(name)").execute(
                num_retries=self.num_retries).get('items', [])
        if not any(b.get('name') == bucket for b in buckets):
            self.conn.buckets().insert(
                project=self.gcs_project_id,
                body={'name': bucket,
                      'location': self.bucket_location,
                      'storageClass': self.storage_class}).execute(
                num_retries=self.num_retries)

    @gcs_logger
    def get_container_entries(self, bucket, prefix):
        """Get bucket entry names."""
        obj_list_dict = self.conn.objects().list(
            bucket=bucket,
            fields="items(name)",
            prefix=prefix).execute(num_retries=self.num_retries).get(
            'items', [])
        return [obj_dict.get('name') for obj_dict in obj_list_dict]

    def get_object_writer(self, bucket, object_name, extra_metadata=None):
        """Return a writer object.

        Returns a writer object that stores a chunk of volume data in a
        GCS object store.
        """
        return GoogleObjectWriter(bucket, object_name, self.conn,
                                  self.writer_chunk_size,
                                  self.num_retries,
                                  self.resumable)

    def get_object_reader(self, bucket, object_name, extra_metadata=None):
        """Return reader object.

        Returns a reader object that retrieves a chunk of backed-up volume data
        from a GCS object store.
        """
        return GoogleObjectReader(bucket, object_name, self.conn,
                                  self.reader_chunk_size,
                                  self.num_retries)

    @gcs_logger
    def delete_object(self, bucket, object_name):
        """Deletes a backup object from a GCS object store."""
        self.conn.objects().delete(
            bucket=bucket,
            object=object_name).execute(num_retries=self.num_retries)

    def _generate_object_name_prefix(self, backup):
        """Generates a GCS backup object name prefix.

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

    def update_container_name(self, backup, bucket):
        """Use the bucket name as provided - don't update."""
        return

    def get_extra_metadata(self, backup, volume):
        """GCS driver does not use any extra metadata."""
        return


class GoogleObjectWriter(object):
    def __init__(self, bucket, object_name, conn, writer_chunk_size,
                 num_retries, resumable):
        self.bucket = bucket
        self.object_name = object_name
        self.conn = conn
        self.data = bytearray()
        self.chunk_size = writer_chunk_size
        self.num_retries = num_retries
        self.resumable = resumable

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def write(self, data):
        self.data += data

    @gcs_logger
    def close(self):
        media = http.MediaIoBaseUpload(six.BytesIO(self.data),
                                       'application/octet-stream',
                                       chunksize=self.chunk_size,
                                       resumable=self.resumable)
        resp = self.conn.objects().insert(
            bucket=self.bucket,
            name=self.object_name,
            body={},
            media_body=media).execute(num_retries=self.num_retries)
        etag = resp['md5Hash']
        md5 = hashlib.md5(self.data).digest()
        if six.PY3:
            md5 = md5.encode('utf-8')
            etag = bytes(etag, 'utf-8')
        md5 = base64.b64encode(md5)
        if etag != md5:
            err = _('MD5 of object: %(object_name)s before: '
                    '%(md5)s and after: %(etag)s is not same.') % {
                'object_name': self.object_name,
                'md5': md5, 'etag': etag, }
            raise exception.InvalidBackup(reason=err)
        else:
            LOG.debug('MD5 before: %(md5)s and after: %(etag)s '
                      'writing object: %(object_name)s in GCS.',
                      {'etag': etag, 'md5': md5,
                       'object_name': self.object_name, })
            return md5


class GoogleObjectReader(object):
    def __init__(self, bucket, object_name, conn, reader_chunk_size,
                 num_retries):
        self.bucket = bucket
        self.object_name = object_name
        self.conn = conn
        self.chunk_size = reader_chunk_size
        self.num_retries = num_retries

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        pass

    @gcs_logger
    def read(self):
        req = self.conn.objects().get_media(
            bucket=self.bucket,
            object=self.object_name)
        fh = six.BytesIO()
        downloader = GoogleMediaIoBaseDownload(
            fh, req, chunksize=self.chunk_size)
        done = False
        while not done:
            status, done = downloader.next_chunk(num_retries=self.num_retries)
        LOG.debug('GCS Object download Complete.')
        return fh.getvalue()


class GoogleMediaIoBaseDownload(http.MediaIoBaseDownload):

    @http.util.positional(1)
    def next_chunk(self, num_retries=None):
        error_codes = CONF.backup_gcs_retry_error_codes
        headers = {'range': 'bytes=%d-%d' %
                   (self._progress, self._progress + self._chunksize)}

        gcs_http = self._request.http
        for retry_num in range(num_retries + 1):
            if retry_num > 0:
                self._sleep(self._rand() * 2 ** retry_num)

            resp, content = gcs_http.request(self._uri, headers=headers)
            if resp.status < 500 and (six.text_type(resp.status)
                                      not in error_codes):
                break
        if resp.status in [200, 206]:
            if 'content-location' in resp and (
                    resp['content-location'] != self._uri):
                self._uri = resp['content-location']
            self._progress += len(content)
            self._fd.write(content)

            if 'content-range' in resp:
                content_range = resp['content-range']
                length = content_range.rsplit('/', 1)[1]
                self._total_size = int(length)
            elif 'content-length' in resp:
                self._total_size = int(resp['content-length'])

            if self._progress == self._total_size:
                self._done = True
            return (http.MediaDownloadProgress(self._progress,
                    self._total_size), self._done)

        else:
            raise http.HttpError(resp, content, uri=self._uri)


def get_backup_driver(context):
    return GoogleBackupDriver(context)
