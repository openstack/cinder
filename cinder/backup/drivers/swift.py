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

"""Implementation of a backup service that uses Swift as the backend

**Related Flags**

:backup_swift_url: The URL of the Swift endpoint (default:
                                                        localhost:8080).
:backup_swift_object_size: The size in bytes of the Swift objects used
                                    for volume backups (default: 52428800).
:backup_swift_retry_attempts: The number of retries to make for Swift
                                    operations (default: 10).
:backup_swift_retry_backoff: The backoff time in seconds between retrying
                                    failed Swift operations (default: 10).
:backup_compression_algorithm: Compression algorithm to use for volume
                               backups. Supported options are:
                               None (to disable), zlib and bz2 (default: zlib)
"""

import hashlib
import json
import os
import six
import socket

import eventlet
from oslo.config import cfg

from cinder.backup.driver import BackupDriver
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder.openstack.common import units
from swiftclient import client as swift


LOG = logging.getLogger(__name__)

swiftbackup_service_opts = [
    cfg.StrOpt('backup_swift_url',
               default='http://localhost:8080/v1/AUTH_',
               help='The URL of the Swift endpoint'),
    cfg.StrOpt('backup_swift_auth',
               default='per_user',
               help='Swift authentication mechanism'),
    cfg.StrOpt('backup_swift_user',
               default=None,
               help='Swift user name'),
    cfg.StrOpt('backup_swift_key',
               default=None,
               help='Swift key for authentication'),
    cfg.StrOpt('backup_swift_container',
               default='volumebackups',
               help='The default Swift container to use'),
    cfg.IntOpt('backup_swift_object_size',
               default=52428800,
               help='The size in bytes of Swift backup objects'),
    cfg.IntOpt('backup_swift_retry_attempts',
               default=3,
               help='The number of retries to make for Swift operations'),
    cfg.IntOpt('backup_swift_retry_backoff',
               default=2,
               help='The backoff time in seconds between Swift retries'),
    cfg.StrOpt('backup_compression_algorithm',
               default='zlib',
               help='Compression algorithm (None to disable)'),
]

CONF = cfg.CONF
CONF.register_opts(swiftbackup_service_opts)


class SwiftBackupDriver(BackupDriver):
    """Provides backup, restore and delete of backup objects within Swift."""

    DRIVER_VERSION = '1.0.0'
    DRIVER_VERSION_MAPPING = {'1.0.0': '_restore_v1'}

    def _get_compressor(self, algorithm):
        try:
            if algorithm.lower() in ('none', 'off', 'no'):
                return None
            elif algorithm.lower() in ('zlib', 'gzip'):
                import zlib as compressor
                return compressor
            elif algorithm.lower() in ('bz2', 'bzip2'):
                import bz2 as compressor
                return compressor
        except ImportError:
            pass

        err = _('unsupported compression algorithm: %s') % algorithm
        raise ValueError(unicode(err))

    def __init__(self, context, db_driver=None):
        super(SwiftBackupDriver, self).__init__(context, db_driver)
        self.swift_url = '%s%s' % (CONF.backup_swift_url,
                                   self.context.project_id)
        self.az = CONF.storage_availability_zone
        self.data_block_size_bytes = CONF.backup_swift_object_size
        self.swift_attempts = CONF.backup_swift_retry_attempts
        self.swift_backoff = CONF.backup_swift_retry_backoff
        self.compressor = \
            self._get_compressor(CONF.backup_compression_algorithm)
        LOG.debug('Connect to %s in "%s" mode' % (CONF.backup_swift_url,
                                                  CONF.backup_swift_auth))
        if CONF.backup_swift_auth == 'single_user':
            if CONF.backup_swift_user is None:
                LOG.error(_("single_user auth mode enabled, "
                            "but %(param)s not set")
                          % {'param': 'backup_swift_user'})
                raise exception.ParameterNotFound(param='backup_swift_user')
            self.conn = swift.Connection(authurl=CONF.backup_swift_url,
                                         user=CONF.backup_swift_user,
                                         key=CONF.backup_swift_key,
                                         retries=self.swift_attempts,
                                         starting_backoff=self.swift_backoff)
        else:
            self.conn = swift.Connection(retries=self.swift_attempts,
                                         preauthurl=self.swift_url,
                                         preauthtoken=self.context.auth_token,
                                         starting_backoff=self.swift_backoff)

    def _create_container(self, context, backup):
        backup_id = backup['id']
        container = backup['container']
        LOG.debug('_create_container started, container: %(container)s,'
                  'backup: %(backup_id)s' %
                  {'container': container, 'backup_id': backup_id})
        if container is None:
            container = CONF.backup_swift_container
            self.db.backup_update(context, backup_id, {'container': container})
        # NOTE(gfidente): accordingly to the Object Storage API reference, we
        # do not need to check if a container already exists, container PUT
        # requests are idempotent and a code of 202 (Accepted) is returned when
        # the container already existed.
        self.conn.put_container(container)
        return container

    def _generate_swift_object_name_prefix(self, backup):
        az = 'az_%s' % self.az
        backup_name = '%s_backup_%s' % (az, backup['id'])
        volume = 'volume_%s' % (backup['volume_id'])
        timestamp = timeutils.strtime(fmt="%Y%m%d%H%M%S")
        prefix = volume + '/' + timestamp + '/' + backup_name
        LOG.debug('_generate_swift_object_name_prefix: %s' % prefix)
        return prefix

    def _generate_object_names(self, backup):
        prefix = backup['service_metadata']
        swift_objects = self.conn.get_container(backup['container'],
                                                prefix=prefix,
                                                full_listing=True)[1]
        swift_object_names = [swift_obj['name'] for swift_obj in swift_objects]
        LOG.debug('generated object list: %s' % swift_object_names)
        return swift_object_names

    def _metadata_filename(self, backup):
        swift_object_name = backup['service_metadata']
        filename = '%s_metadata' % swift_object_name
        return filename

    def _write_metadata(self, backup, volume_id, container, object_list,
                        volume_meta):
        filename = self._metadata_filename(backup)
        LOG.debug('_write_metadata started, container name: %(container)s,'
                  ' metadata filename: %(filename)s' %
                  {'container': container, 'filename': filename})
        metadata = {}
        metadata['version'] = self.DRIVER_VERSION
        metadata['backup_id'] = backup['id']
        metadata['volume_id'] = volume_id
        metadata['backup_name'] = backup['display_name']
        metadata['backup_description'] = backup['display_description']
        metadata['created_at'] = str(backup['created_at'])
        metadata['objects'] = object_list
        metadata['volume_meta'] = volume_meta
        metadata_json = json.dumps(metadata, sort_keys=True, indent=2)
        reader = six.StringIO(metadata_json)
        etag = self.conn.put_object(container, filename, reader,
                                    content_length=reader.len)
        md5 = hashlib.md5(metadata_json).hexdigest()
        if etag != md5:
            err = _('error writing metadata file to swift, MD5 of metadata'
                    ' file in swift [%(etag)s] is not the same as MD5 of '
                    'metadata file sent to swift [%(md5)s]') % {'etag': etag,
                                                                'md5': md5}
            raise exception.InvalidBackup(reason=err)
        LOG.debug('_write_metadata finished')

    def _read_metadata(self, backup):
        container = backup['container']
        filename = self._metadata_filename(backup)
        LOG.debug('_read_metadata started, container name: %(container)s, '
                  'metadata filename: %(filename)s' %
                  {'container': container, 'filename': filename})
        (resp, body) = self.conn.get_object(container, filename)
        metadata = json.loads(body)
        LOG.debug('_read_metadata finished (%s)' % metadata)
        return metadata

    def _prepare_backup(self, backup):
        """Prepare the backup process and return the backup metadata."""
        backup_id = backup['id']
        volume_id = backup['volume_id']
        volume = self.db.volume_get(self.context, volume_id)

        if volume['size'] <= 0:
            err = _('volume size %d is invalid.') % volume['size']
            raise exception.InvalidVolume(reason=err)

        try:
            container = self._create_container(self.context, backup)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)

        object_prefix = self._generate_swift_object_name_prefix(backup)
        backup['service_metadata'] = object_prefix
        self.db.backup_update(self.context, backup_id, {'service_metadata':
                                                        object_prefix})
        volume_size_bytes = volume['size'] * units.Gi
        availability_zone = self.az
        LOG.debug('starting backup of volume: %(volume_id)s to swift,'
                  ' volume size: %(volume_size_bytes)d, swift object names'
                  ' prefix %(object_prefix)s, availability zone:'
                  ' %(availability_zone)s' %
                  {
                      'volume_id': volume_id,
                      'volume_size_bytes': volume_size_bytes,
                      'object_prefix': object_prefix,
                      'availability_zone': availability_zone,
                  })
        object_meta = {'id': 1, 'list': [], 'prefix': object_prefix,
                       'volume_meta': None}
        return object_meta, container

    def _backup_chunk(self, backup, container, data, data_offset, object_meta):
        """Backup data chunk based on the object metadata and offset."""
        object_prefix = object_meta['prefix']
        object_list = object_meta['list']
        object_id = object_meta['id']
        object_name = '%s-%05d' % (object_prefix, object_id)
        obj = {}
        obj[object_name] = {}
        obj[object_name]['offset'] = data_offset
        obj[object_name]['length'] = len(data)
        LOG.debug('reading chunk of data from volume')
        if self.compressor is not None:
            algorithm = CONF.backup_compression_algorithm.lower()
            obj[object_name]['compression'] = algorithm
            data_size_bytes = len(data)
            data = self.compressor.compress(data)
            comp_size_bytes = len(data)
            LOG.debug('compressed %(data_size_bytes)d bytes of data '
                      'to %(comp_size_bytes)d bytes using '
                      '%(algorithm)s' %
                      {
                          'data_size_bytes': data_size_bytes,
                          'comp_size_bytes': comp_size_bytes,
                          'algorithm': algorithm,
                      })
        else:
            LOG.debug('not compressing data')
            obj[object_name]['compression'] = 'none'

        reader = six.StringIO(data)
        LOG.debug('About to put_object')
        try:
            etag = self.conn.put_object(container, object_name, reader,
                                        content_length=len(data))
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)
        LOG.debug('swift MD5 for %(object_name)s: %(etag)s' %
                  {'object_name': object_name, 'etag': etag, })
        md5 = hashlib.md5(data).hexdigest()
        obj[object_name]['md5'] = md5
        LOG.debug('backup MD5 for %(object_name)s: %(md5)s' %
                  {'object_name': object_name, 'md5': md5})
        if etag != md5:
            err = _('error writing object to swift, MD5 of object in '
                    'swift %(etag)s is not the same as MD5 of object sent '
                    'to swift %(md5)s') % {'etag': etag, 'md5': md5}
            raise exception.InvalidBackup(reason=err)
        object_list.append(obj)
        object_id += 1
        object_meta['list'] = object_list
        object_meta['id'] = object_id
        LOG.debug('Calling eventlet.sleep(0)')
        eventlet.sleep(0)

    def _finalize_backup(self, backup, container, object_meta):
        """Finalize the backup by updating its metadata on Swift."""
        object_list = object_meta['list']
        object_id = object_meta['id']
        volume_meta = object_meta['volume_meta']
        try:
            self._write_metadata(backup,
                                 backup['volume_id'],
                                 container,
                                 object_list,
                                 volume_meta)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)
        self.db.backup_update(self.context, backup['id'],
                              {'object_count': object_id})
        LOG.debug('backup %s finished.' % backup['id'])

    def _backup_metadata(self, backup, object_meta):
        """Backup volume metadata.

        NOTE(dosaboy): the metadata we are backing up is obtained from a
                       versioned api so we should not alter it in any way here.
                       We must also be sure that the service that will perform
                       the restore is compatible with version used.
        """
        json_meta = self.get_metadata(backup['volume_id'])
        if not json_meta:
            LOG.debug("No volume metadata to backup")
            return

        object_meta["volume_meta"] = json_meta

    def backup(self, backup, volume_file, backup_metadata=True):
        """Backup the given volume to Swift."""

        object_meta, container = self._prepare_backup(backup)
        while True:
            data = volume_file.read(self.data_block_size_bytes)
            data_offset = volume_file.tell()
            if data == '':
                break
            self._backup_chunk(backup, container, data,
                               data_offset, object_meta)

        if backup_metadata:
            try:
                self._backup_metadata(backup, object_meta)
            except Exception as err:
                with excutils.save_and_reraise_exception():
                    LOG.exception(
                        _("Backup volume metadata to swift failed: %s") %
                        six.text_type(err))
                    self.delete(backup)

        self._finalize_backup(backup, container, object_meta)

    def _restore_v1(self, backup, volume_id, metadata, volume_file):
        """Restore a v1 swift volume backup from swift."""
        backup_id = backup['id']
        LOG.debug('v1 swift volume backup restore of %s started', backup_id)
        container = backup['container']
        metadata_objects = metadata['objects']
        metadata_object_names = sum((obj.keys() for obj in metadata_objects),
                                    [])
        LOG.debug('metadata_object_names = %s' % metadata_object_names)
        prune_list = [self._metadata_filename(backup)]
        swift_object_names = [swift_object_name for swift_object_name in
                              self._generate_object_names(backup)
                              if swift_object_name not in prune_list]
        if sorted(swift_object_names) != sorted(metadata_object_names):
            err = _('restore_backup aborted, actual swift object list in '
                    'swift does not match object list stored in metadata')
            raise exception.InvalidBackup(reason=err)

        for metadata_object in metadata_objects:
            object_name = metadata_object.keys()[0]
            LOG.debug('restoring object from swift. backup: %(backup_id)s, '
                      'container: %(container)s, swift object name: '
                      '%(object_name)s, volume: %(volume_id)s' %
                      {
                          'backup_id': backup_id,
                          'container': container,
                          'object_name': object_name,
                          'volume_id': volume_id,
                      })
            try:
                (resp, body) = self.conn.get_object(container, object_name)
            except socket.error as err:
                raise exception.SwiftConnectionFailed(reason=err)
            compression_algorithm = metadata_object[object_name]['compression']
            decompressor = self._get_compressor(compression_algorithm)
            if decompressor is not None:
                LOG.debug('decompressing data using %s algorithm' %
                          compression_algorithm)
                decompressed = decompressor.decompress(body)
                volume_file.write(decompressed)
            else:
                volume_file.write(body)

            # force flush every write to avoid long blocking write on close
            volume_file.flush()

            # Be tolerant to IO implementations that do not support fileno()
            try:
                fileno = volume_file.fileno()
            except IOError:
                LOG.info("volume_file does not support fileno() so skipping "
                         "fsync()")
            else:
                os.fsync(fileno)

            # Restoring a backup to a volume can take some time. Yield so other
            # threads can run, allowing for among other things the service
            # status to be updated
            eventlet.sleep(0)
        LOG.debug('v1 swift volume backup restore of %s finished',
                  backup_id)

    def restore(self, backup, volume_id, volume_file):
        """Restore the given volume backup from swift."""
        backup_id = backup['id']
        container = backup['container']
        object_prefix = backup['service_metadata']
        LOG.debug('starting restore of backup %(object_prefix)s from swift'
                  ' container: %(container)s, to volume %(volume_id)s, '
                  'backup: %(backup_id)s' %
                  {
                      'object_prefix': object_prefix,
                      'container': container,
                      'volume_id': volume_id,
                      'backup_id': backup_id,
                  })
        try:
            metadata = self._read_metadata(backup)
        except socket.error as err:
            raise exception.SwiftConnectionFailed(reason=err)
        metadata_version = metadata['version']
        LOG.debug('Restoring swift backup version %s', metadata_version)
        try:
            restore_func = getattr(self, self.DRIVER_VERSION_MAPPING.get(
                metadata_version))
        except TypeError:
            err = (_('No support to restore swift backup version %s')
                   % metadata_version)
            raise exception.InvalidBackup(reason=err)
        restore_func(backup, volume_id, metadata, volume_file)

        volume_meta = metadata.get('volume_meta', None)
        try:
            if volume_meta:
                self.put_metadata(volume_id, volume_meta)
            else:
                LOG.debug("No volume metadata in this backup")
        except exception.BackupMetadataUnsupportedVersion:
            msg = _("Metadata restore failed due to incompatible version")
            LOG.error(msg)
            raise exception.BackupOperationError(msg)

        LOG.debug('restore %(backup_id)s to %(volume_id)s finished.' %
                  {'backup_id': backup_id, 'volume_id': volume_id})

    def delete(self, backup):
        """Delete the given backup from swift."""
        container = backup['container']
        LOG.debug('delete started, backup: %s, container: %s, prefix: %s',
                  backup['id'], container, backup['service_metadata'])

        if container is not None:
            swift_object_names = []
            try:
                swift_object_names = self._generate_object_names(backup)
            except Exception:
                LOG.warn(_('swift error while listing objects, continuing'
                           ' with delete'))

            for swift_object_name in swift_object_names:
                try:
                    self.conn.delete_object(container, swift_object_name)
                except socket.error as err:
                    raise exception.SwiftConnectionFailed(reason=err)
                except Exception:
                    LOG.warn(_('swift error while deleting object %s, '
                               'continuing with delete') % swift_object_name)
                else:
                    LOG.debug('deleted swift object: %(swift_object_name)s'
                              ' in container: %(container)s' %
                              {
                                  'swift_object_name': swift_object_name,
                                  'container': container
                              })
                # Deleting a backup's objects from swift can take some time.
                # Yield so other threads can run
                eventlet.sleep(0)

        LOG.debug('delete %s finished' % backup['id'])


def get_backup_driver(context):
    return SwiftBackupDriver(context)
