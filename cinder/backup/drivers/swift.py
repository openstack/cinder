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

import io
import socket

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import secretutils
from oslo_utils import timeutils
from swiftclient import client as swift
from swiftclient import exceptions as swift_exc

from cinder.backup import chunkeddriver
from cinder import exception
from cinder.i18n import _
from cinder import interface

LOG = logging.getLogger(__name__)

swiftbackup_service_opts = [
    cfg.URIOpt('backup_swift_url',
               help='The URL of the Swift endpoint'),
    cfg.URIOpt('backup_swift_auth_url',
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
               choices=['per_user', 'single_user'],
               help='Swift authentication mechanism (per_user or '
               'single_user).'),
    cfg.StrOpt('backup_swift_auth_version',
               default='1',
               help='Swift authentication version. Specify "1" for auth 1.0'
                    ', or "2" for auth 2.0 or "3" for auth 3.0'),
    cfg.StrOpt('backup_swift_tenant',
               help='Swift tenant/account name. Required when connecting'
                    ' to an auth 2.0 system'),
    cfg.StrOpt('backup_swift_user_domain',
               default=None,
               help='Swift user domain name. Required when connecting'
                    ' to an auth 3.0 system'),
    cfg.StrOpt('backup_swift_project_domain',
               default=None,
               help='Swift project domain name. Required when connecting'
                    ' to an auth 3.0 system'),
    cfg.StrOpt('backup_swift_project',
               default=None,
               help='Swift project/account name. Required when connecting'
                    ' to an auth 3.0 system'),
    cfg.StrOpt('backup_swift_user',
               help='Swift user name'),
    cfg.StrOpt('backup_swift_key',
               secret=True,
               help='Swift key for authentication'),
    cfg.StrOpt('backup_swift_container',
               default='volumebackups',
               help='The default Swift container to use'),
    cfg.StrOpt('backup_swift_create_storage_policy',
               default=None,
               help='The storage policy to use when creating the Swift '
                    'container. If the container already exists the '
                    'storage policy cannot be enforced'),
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


@interface.backupdriver
class SwiftBackupDriver(chunkeddriver.ChunkedBackupDriver):
    """Provides backup, restore and delete of backup objects within Swift."""

    def __init__(self, context):
        chunk_size_bytes = CONF.backup_swift_object_size
        sha_block_size_bytes = CONF.backup_swift_block_size
        backup_default_container = CONF.backup_swift_container
        enable_progress_timer = CONF.backup_swift_enable_progress_timer
        super().__init__(
            context,
            chunk_size_bytes,
            sha_block_size_bytes,
            backup_default_container,
            enable_progress_timer,
        )

        # Do not intialize the instance created when the backup service
        # starts up. The context will be missing information to do things
        # like fetching endpoints from the service catalog.
        if context and context.user_id:
            self.initialize()

    @staticmethod
    def get_driver_options():
        return swiftbackup_service_opts

    def initialize(self):
        self.swift_attempts = CONF.backup_swift_retry_attempts
        self.swift_backoff = CONF.backup_swift_retry_backoff
        self.backup_swift_auth_insecure = CONF.backup_swift_auth_insecure

        if CONF.backup_swift_auth == 'single_user':
            if CONF.backup_swift_user is None:
                LOG.error("single_user auth mode enabled, "
                          "but %(param)s not set",
                          {'param': 'backup_swift_user'})
                raise exception.ParameterNotFound(param='backup_swift_user')
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
                for entry in self.context.service_catalog:
                    if entry.get('type') == service_type:
                        # It is assumed that service_types are unique within
                        # the service catalog, so once the correct one is found
                        # it is safe to break out of the loop
                        self.auth_url = entry.get(
                            'endpoints')[0].get(endpoint_type)
                        break
            else:
                self.auth_url = CONF.backup_swift_auth_url
            if self.auth_url is None:
                raise exception.BackupDriverException(_(
                    "Could not determine which Keystone endpoint to use. This "
                    "can either be set in the service catalog or with the "
                    "cinder.conf config option 'backup_swift_auth_url'."))
            LOG.debug("Using auth URL %s", self.auth_url)
            LOG.debug('Connect to %s in "%s" mode', CONF.backup_swift_auth_url,
                      CONF.backup_swift_auth)

            os_options = {}
            if CONF.backup_swift_user_domain is not None:
                os_options['user_domain_name'] = CONF.backup_swift_user_domain
            if CONF.backup_swift_project_domain is not None:
                os_options['project_domain_name'] = (
                    CONF.backup_swift_project_domain
                )
            if CONF.backup_swift_project is not None:
                os_options['project_name'] = CONF.backup_swift_project
            self.conn = swift.Connection(
                authurl=self.auth_url,
                auth_version=CONF.backup_swift_auth_version,
                tenant_name=CONF.backup_swift_tenant,
                user=CONF.backup_swift_user,
                key=CONF.backup_swift_key,
                os_options=os_options,
                retries=self.swift_attempts,
                starting_backoff=self.swift_backoff,
                insecure=self.backup_swift_auth_insecure,
                cacert=CONF.backup_swift_ca_cert_file)
        else:
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
                for entry in self.context.service_catalog:
                    if entry.get('type') == service_type:
                        # It is assumed that service_types are unique within
                        # the service catalog, so once the correct one is found
                        # it is safe to break out of the loop
                        self.swift_url = entry.get(
                            'endpoints')[0].get(endpoint_type)
                        break
            else:
                self.swift_url = '%s%s' % (CONF.backup_swift_url,
                                           self.context.project_id)
            if self.swift_url is None:
                raise exception.BackupDriverException(_(
                    "Could not determine which Swift endpoint to use. This "
                    "can either be set in the service catalog or with the "
                    "cinder.conf config option 'backup_swift_url'."))
            LOG.debug("Using swift URL %s", self.swift_url)
            LOG.debug('Connect to %s in "%s" mode', CONF.backup_swift_url,
                      CONF.backup_swift_auth)

            self.conn = swift.Connection(retries=self.swift_attempts,
                                         preauthurl=self.swift_url,
                                         preauthtoken=self.context.auth_token,
                                         starting_backoff=self.swift_backoff,
                                         insecure=(
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
            reader = io.BytesIO(self.data)
            try:
                etag = self.conn.put_object(self.container, self.object_name,
                                            reader,
                                            content_length=len(self.data))
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=err)
            md5 = secretutils.md5(self.data, usedforsecurity=False).hexdigest()
            if etag != md5:
                err = _('error writing object to swift, MD5 of object in '
                        'swift %(etag)s is not the same as MD5 of object sent '
                        'to swift %(md5)s') % {'etag': etag, 'md5': md5}
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
        """Create the container if needed.

        Check if the container exist by issuing a HEAD request, if
        the container does not exist we create it.

        We cannot enforce a new storage policy on an
        existing container.
        """
        try:
            self.conn.head_container(container)
        except swift_exc.ClientException as e:
            if e.http_status == 404:
                try:
                    storage_policy = CONF.backup_swift_create_storage_policy
                    headers = ({'X-Storage-Policy': storage_policy}
                               if storage_policy else None)
                    self.conn.put_container(container, headers=headers)
                except socket.error as err:
                    raise exception.SwiftConnectionFailed(reason=err)
                return
            LOG.warning("Failed to HEAD container to determine if it "
                        "exists and should be created.")
            raise exception.SwiftConnectionFailed(reason=e)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)

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

    def check_for_setup_error(self):
        # Here we are trying to connect to swift backend service
        # without any additional parameters.
        # At the moment of execution we don't have any user data
        # After just trying to do easiest operations, that will show
        # that we've configured swift backup driver in right way
        if not CONF.backup_swift_url:
            LOG.warning("We will use endpoints from keystone. It is "
                        "possible we could have problems because of it.")
            return
        conn = swift.Connection(retries=CONF.backup_swift_retry_attempts,
                                preauthurl=CONF.backup_swift_url)
        try:
            conn.get_capabilities()
            # TODO(e0ne) catch less general exception
        except Exception:
            LOG.exception("Can not get Swift capabilities during backup "
                          "driver initialization.")
            raise
