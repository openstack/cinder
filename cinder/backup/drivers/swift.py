# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2014 TrilioData, Inc
# Copyright (c) 2015 EMC Corporation
# Copyright (C) 2015 Kevin Fox <kevin@efox.cc>
# Copyright (C) 2015 Tom Barron <tpb@dyncloud.net>
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

"""Implementation of a backup service that uses Swift as the backend

**Related Flags**

:backup_swift_url: The URL of the Swift endpoint (default: None, use catalog).
:backup_swift_auth_url: The URL of the Keystone endpoint for authentication
                                    (default: None, use catalog).
:swift_catalog_info: Info to match when looking for swift in the service '
                     catalog.
:keystone_catalog_info: Info to match when looking for keystone in the service
                        catalog.
:backup_swift_object_size: The size in bytes of the Swift objects used
                                    for volume backups (default: 52428800).
:backup_swift_retry_attempts: The number of retries to make for Swift
                                    operations (default: 10).
:backup_swift_retry_backoff: The backoff time in seconds between retrying
                                    failed Swift operations (default: 10).
:backup_compression_algorithm: Compression algorithm to use for volume
                               backups. Supported options are:
                               None (to disable), zlib and bz2 (default: zlib)
:backup_swift_ca_cert_file: The location of the CA certificate file to use
                            for swift client requests (default: None)
:backup_swift_auth_insecure: If true, bypass verification of server's
                             certificate for SSL connections (default: False)
"""

import hashlib
import socket

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
import six
from swiftclient import client as swift

from cinder.backup import chunkeddriver
from cinder import exception
from cinder.i18n import _
from cinder.i18n import _LE

LOG = logging.getLogger(__name__)

swiftbackup_service_opts = [
    cfg.StrOpt('backup_swift_url',
               help='The URL of the Swift endpoint'),
    cfg.StrOpt('backup_swift_auth_url',
               help='The URL of the Keystone endpoint'),
    cfg.StrOpt('swift_catalog_info',
               default='object-store:swift:publicURL',
               help='Info to match when looking for swift in the service '
               'catalog. Format is: separated values of the form: '
               '<service_type>:<service_name>:<endpoint_type> - '
               'Only used if backup_swift_url is unset'),
    cfg.StrOpt('keystone_catalog_info',
               default='identity:Identity Service:publicURL',
               help='Info to match when looking for keystone in the service '
               'catalog. Format is: separated values of the form: '
               '<service_type>:<service_name>:<endpoint_type> - '
               'Only used if backup_swift_auth_url is unset'),
    cfg.StrOpt('backup_swift_auth',
               default='per_user',
               help='Swift authentication mechanism'),
    cfg.StrOpt('backup_swift_auth_version',
               default='1',
               help='Swift authentication version. Specify "1" for auth 1.0'
                    ', or "2" for auth 2.0'),
    cfg.StrOpt('backup_swift_tenant',
               help='Swift tenant/account name. Required when connecting'
                    ' to an auth 2.0 system'),
    cfg.StrOpt('backup_swift_user',
               help='Swift user name'),
    cfg.StrOpt('backup_swift_key',
               help='Swift key for authentication'),
    cfg.StrOpt('backup_swift_container',
               default='volumebackups',
               help='The default Swift container to use'),
    cfg.IntOpt('backup_swift_object_size',
               default=52428800,
               help='The size in bytes of Swift backup objects'),
    cfg.IntOpt('backup_swift_block_size',
               default=32768,
               help='The size in bytes that changes are tracked '
                    'for incremental backups. backup_swift_object_size '
                    'has to be multiple of backup_swift_block_size.'),
    cfg.IntOpt('backup_swift_retry_attempts',
               default=3,
               help='The number of retries to make for Swift operations'),
    cfg.IntOpt('backup_swift_retry_backoff',
               default=2,
               help='The backoff time in seconds between Swift retries'),
    cfg.BoolOpt('backup_swift_enable_progress_timer',
                default=True,
                help='Enable or Disable the timer to send the periodic '
                     'progress notifications to Ceilometer when backing '
                     'up the volume to the Swift backend storage. The '
                     'default value is True to enable the timer.'),
    cfg.StrOpt('backup_swift_ca_cert_file',
               help='Location of the CA certificate file to use for swift '
                    'client requests.'),
    cfg.BoolOpt('backup_swift_auth_insecure',
                default=False,
                help='Bypass verification of server certificate when '
                     'making SSL connection to Swift.'),
]

CONF = cfg.CONF
CONF.register_opts(swiftbackup_service_opts)


class SwiftBackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete of backup objects within Swift."""

    def __init__(self, context, db_driver=None):
        chunk_size_bytes = CONF.backup_swift_object_size
        sha_block_size_bytes = CONF.backup_swift_block_size
        backup_default_container = CONF.backup_swift_container
        enable_progress_timer = CONF.backup_swift_enable_progress_timer
        super(SwiftBackupDriver, self).__init__(context, chunk_size_bytes,
                                                sha_block_size_bytes,
                                                backup_default_container,
                                                enable_progress_timer,
                                                db_driver)
        if CONF.backup_swift_url is None:
            self.swift_url = None
            info = CONF.swift_catalog_info
            try:
                service_type, service_name, endpoint_type = info.split(':')
            except ValueError:
                raise exception.BackupDriverException(_(
                    "Failed to parse the configuration option "
                    "'swift_catalog_info', must be in the form "
                    "<service_type>:<service_name>:<endpoint_type>"))
            for entry in context.service_catalog:
                if entry.get('type') == service_type:
                    # It is assumed that service_types are unique within
                    # the service catalog, so once the correct one is found
                    # it is safe to break out of the loop
                    self.swift_url = entry.get(
                        'endpoints')[0].get(endpoint_type)
                    break
        else:
            self.swift_url = '%s%s' % (CONF.backup_swift_url,
                                       context.project_id)
        if self.swift_url is None:
            raise exception.BackupDriverException(_(
                "Could not determine which Swift endpoint to use. This can "
                "either be set in the service catalog or with the "
                "cinder.conf config option 'backup_swift_url'."))
        if CONF.backup_swift_auth_url is None:
            self.auth_url = None
            info = CONF.keystone_catalog_info
            try:
                service_type, service_name, endpoint_type = info.split(':')
            except ValueError:
                raise exception.BackupDriverException(_(
                    "Failed to parse the configuration option "
                    "'keystone_catalog_info', must be in the form "
                    "<service_type>:<service_name>:<endpoint_type>"))
            for entry in context.service_catalog:
                if entry.get('type') == service_type:
                    # It is assumed that service_types are unique within
                    # the service catalog, so once the correct one is found
                    # it is safe to break out of the loop
                    self.auth_url = entry.get(
                        'endpoints')[0].get(endpoint_type)
                    break
        else:
            self.auth_url = '%s%s' % (CONF.backup_swift_auth_url,
                                      context.project_id)
        if self.auth_url is None:
            raise exception.BackupDriverException(_(
                "Could not determine which Keystone endpoint to use. This can "
                "either be set in the service catalog or with the "
                "cinder.conf config option 'backup_swift_auth_url'."))
        LOG.debug("Using swift URL %s", self.swift_url)
        LOG.debug("Using auth URL %s", self.auth_url)
        self.swift_attempts = CONF.backup_swift_retry_attempts
        self.swift_backoff = CONF.backup_swift_retry_backoff
        LOG.debug('Connect to %s in "%s" mode', CONF.backup_swift_url,
                  CONF.backup_swift_auth)
        self.backup_swift_auth_insecure = CONF.backup_swift_auth_insecure
        if CONF.backup_swift_auth == 'single_user':
            if CONF.backup_swift_user is None:
                LOG.error(_LE("single_user auth mode enabled, "
                              "but %(param)s not set"),
                          {'param': 'backup_swift_user'})
                raise exception.ParameterNotFound(param='backup_swift_user')
            self.conn = swift.Connection(
                authurl=self.auth_url,
                auth_version=CONF.backup_swift_auth_version,
                tenant_name=CONF.backup_swift_tenant,
                user=CONF.backup_swift_user,
                key=CONF.backup_swift_key,
                retries=self.swift_attempts,
                starting_backoff=self.swift_backoff,
                insecure=self.backup_swift_auth_insecure,
                cacert=CONF.backup_swift_ca_cert_file)
        else:
            self.conn = swift.Connection(retries=self.swift_attempts,
                                         preauthurl=self.swift_url,
                                         preauthtoken=self.context.auth_token,
                                         starting_backoff=self.swift_backoff,
                                         insecure= (
                                             self.backup_swift_auth_insecure),
                                         cacert=CONF.backup_swift_ca_cert_file)

    class SwiftObjectWriter(object):
        def __init__(self, container, object_name, conn):
            self.container = container
            self.object_name = object_name
            self.conn = conn
            self.data = bytearray()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.close()

        def write(self, data):
            self.data += data

        def close(self):
            reader = six.BytesIO(self.data)
            try:
                etag = self.conn.put_object(self.container, self.object_name,
                                            reader,
                                            content_length=len(self.data))
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=err)
            LOG.debug('swift MD5 for %(object_name)s: %(etag)s',
                      {'object_name': self.object_name, 'etag': etag, })
            md5 = hashlib.md5(self.data).hexdigest()
            LOG.debug('backup MD5 for %(object_name)s: %(md5)s',
                      {'object_name': self.object_name, 'md5': md5})
            if etag != md5:
                err = _('error writing object to swift, MD5 of object in '
                        'swift %(etag)s is not the same as MD5 of object sent '
                        'to swift %(md5)s'), {'etag': etag, 'md5': md5}
                raise exception.InvalidBackup(reason=err)
            return md5

    class SwiftObjectReader(object):
        def __init__(self, container, object_name, conn):
            self.container = container
            self.object_name = object_name
            self.conn = conn

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            pass

        def read(self):
            try:
                (_resp, body) = self.conn.get_object(self.container,
                                                     self.object_name)
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=err)
            return body

    def put_container(self, container):
        """Create the container if needed. No failure if it pre-exists."""
        try:
            self.conn.put_container(container)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)
        return

    def get_container_entries(self, container, prefix):
        """Get container entry names"""
        try:
            swift_objects = self.conn.get_container(container,
                                                    prefix=prefix,
                                                    full_listing=True)[1]
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)
        swift_object_names = [swift_obj['name'] for swift_obj in swift_objects]
        return swift_object_names

    def get_object_writer(self, container, object_name, extra_metadata=None):
        """Return a writer object.

        Returns a writer object that stores a chunk of volume data in a
        Swift object store.
        """
        return self.SwiftObjectWriter(container, object_name, self.conn)

    def get_object_reader(self, container, object_name, extra_metadata=None):
        """Return reader object.

        Returns a reader object that retrieves a chunk of backed-up volume data
        from a Swift object store.
        """
        return self.SwiftObjectReader(container, object_name, self.conn)

    def delete_object(self, container, object_name):
        """Deletes a backup object from a Swift object store."""
        try:
            self.conn.delete_object(container, object_name)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)

    def _generate_object_name_prefix(self, backup):
        """Generates a Swift backup object name prefix."""
        az = 'az_%s' % self.az
        backup_name = '%s_backup_%s' % (az, backup['id'])
        volume = 'volume_%s' % (backup['volume_id'])
        timestamp = timeutils.utcnow().strftime("%Y%m%d%H%M%S")
        prefix = volume + '/' + timestamp + '/' + backup_name
        LOG.debug('generate_object_name_prefix: %s', prefix)
        return prefix

    def update_container_name(self, backup, container):
        """Use the container name as provided - don't update."""
        return container

    def get_extra_metadata(self, backup, volume):
        """Swift driver does not use any extra metadata."""
        return None


def get_backup_driver(context):
    return SwiftBackupDriver(context)
