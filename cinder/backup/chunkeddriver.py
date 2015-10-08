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

"""Generic base class to implement metadata, compression and chunked data
   operations
"""

import abc
import hashlib
import json
import os

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import units
import six

from cinder.backup import driver
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import objects
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

chunkedbackup_service_opts = [
    cfg.StrOpt('backup_compression_algorithm',
               default='zlib',
               help='Compression algorithm (None to disable)'),
]

CONF = cfg.CONF
CONF.register_opts(chunkedbackup_service_opts)


@six.add_metaclass(abc.ABCMeta)
class ChunkedBackupDriver(driver.BackupDriver):
    """Abstract chunked backup driver.

       Implements common functionality for backup drivers that store volume
       data in multiple "chunks" in a backup repository when the size of
       the backed up cinder volume exceeds the size of a backup repository
       "chunk."

       Provides abstract methods to be implmented in concrete chunking drivers.
    """

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
        raise ValueError(err)

    def __init__(self, context, chunk_size_bytes, sha_block_size_bytes,
                 backup_default_container, enable_progress_timer,
                 db_driver=None):
        super(ChunkedBackupDriver, self).__init__(context, db_driver)
        self.chunk_size_bytes = chunk_size_bytes
        self.sha_block_size_bytes = sha_block_size_bytes
        self.backup_default_container = backup_default_container
        self.enable_progress_timer = enable_progress_timer

        self.backup_timer_interval = CONF.backup_timer_interval
        self.data_block_num = CONF.backup_object_number_per_notification
        self.az = CONF.storage_availability_zone
        self.backup_compression_algorithm = CONF.backup_compression_algorithm
        self.compressor = \
            self._get_compressor(CONF.backup_compression_algorithm)
        self.support_force_delete = True

    # To create your own "chunked" backup driver, implement the following
    # abstract methods.

    @abc.abstractmethod
    def put_container(self, container):
        """Create the container if needed. No failure if it pre-exists."""
        return

    @abc.abstractmethod
    def get_container_entries(self, container, prefix):
        """Get container entry names."""
        return

    @abc.abstractmethod
    def get_object_writer(self, container, object_name, extra_metadata=None):
        """Returns a writer object which stores the chunk data in backup repository.

           The object returned should be a context handler that can be used
           in a "with" context.
        """
        return

    @abc.abstractmethod
    def get_object_reader(self, container, object_name, extra_metadata=None):
        """Returns a reader object for the backed up chunk."""
        return

    @abc.abstractmethod
    def delete_object(self, container, object_name):
        """Delete object from container."""
        return

    @abc.abstractmethod
    def _generate_object_name_prefix(self, backup):
        return

    @abc.abstractmethod
    def update_container_name(self, backup, container):
        """Allow sub-classes to override container name.

        This method exists so that sub-classes can override the container name
        as it comes in to the driver in the backup object. Implementations
        should return None if no change to the container name is desired.
        """
        return

    @abc.abstractmethod
    def get_extra_metadata(self, backup, volume):
        """Return extra metadata to use in prepare_backup.

        This method allows for collection of extra metadata in prepare_backup()
        which will be passed to get_object_reader() and get_object_writer().
        Subclass extensions can use this extra information to optimize
        data transfers. Return a json serializable object.
        """
        return

    def _create_container(self, context, backup):
        backup.container = self.update_container_name(backup, backup.container)
        LOG.debug('_create_container started, container: %(container)s,'
                  'backup: %(backup_id)s.',
                  {'container': backup.container, 'backup_id': backup.id})
        if backup.container is None:
            backup.container = self.backup_default_container
        backup.save()
        self.put_container(backup.container)
        return backup.container

    def _generate_object_names(self, backup):
        prefix = backup['service_metadata']
        object_names = self.get_container_entries(backup['container'], prefix)
        LOG.debug('generated object list: %s.', object_names)
        return object_names

    def _metadata_filename(self, backup):
        object_name = backup['service_metadata']
        filename = '%s_metadata' % object_name
        return filename

    def _sha256_filename(self, backup):
        object_name = backup['service_metadata']
        filename = '%s_sha256file' % object_name
        return filename

    def _write_metadata(self, backup, volume_id, container, object_list,
                        volume_meta, extra_metadata=None):
        filename = self._metadata_filename(backup)
        LOG.debug('_write_metadata started, container name: %(container)s,'
                  ' metadata filename: %(filename)s.',
                  {'container': container, 'filename': filename})
        metadata = {}
        metadata['version'] = self.DRIVER_VERSION
        metadata['backup_id'] = backup['id']
        metadata['volume_id'] = volume_id
        metadata['backup_name'] = backup['display_name']
        metadata['backup_description'] = backup['display_description']
        metadata['created_at'] = str(backup['created_at'])
        metadata['objects'] = object_list
        metadata['parent_id'] = backup['parent_id']
        metadata['volume_meta'] = volume_meta
        if extra_metadata:
            metadata['extra_metadata'] = extra_metadata
        metadata_json = json.dumps(metadata, sort_keys=True, indent=2)
        if six.PY3:
            metadata_json = metadata_json.encode('utf-8')
        with self.get_object_writer(container, filename) as writer:
            writer.write(metadata_json)
        LOG.debug('_write_metadata finished. Metadata: %s.', metadata_json)

    def _write_sha256file(self, backup, volume_id, container, sha256_list):
        filename = self._sha256_filename(backup)
        LOG.debug('_write_sha256file started, container name: %(container)s,'
                  ' sha256file filename: %(filename)s.',
                  {'container': container, 'filename': filename})
        sha256file = {}
        sha256file['version'] = self.DRIVER_VERSION
        sha256file['backup_id'] = backup['id']
        sha256file['volume_id'] = volume_id
        sha256file['backup_name'] = backup['display_name']
        sha256file['backup_description'] = backup['display_description']
        sha256file['created_at'] = six.text_type(backup['created_at'])
        sha256file['chunk_size'] = self.sha_block_size_bytes
        sha256file['sha256s'] = sha256_list
        sha256file_json = json.dumps(sha256file, sort_keys=True, indent=2)
        if six.PY3:
            sha256file_json = sha256file_json.encode('utf-8')
        with self.get_object_writer(container, filename) as writer:
            writer.write(sha256file_json)
        LOG.debug('_write_sha256file finished.')

    def _read_metadata(self, backup):
        container = backup['container']
        filename = self._metadata_filename(backup)
        LOG.debug('_read_metadata started, container name: %(container)s, '
                  'metadata filename: %(filename)s.',
                  {'container': container, 'filename': filename})
        with self.get_object_reader(container, filename) as reader:
            metadata_json = reader.read()
        if six.PY3:
            metadata_json = metadata_json.decode('utf-8')
        metadata = json.loads(metadata_json)
        LOG.debug('_read_metadata finished. Metadata: %s.', metadata_json)
        return metadata

    def _read_sha256file(self, backup):
        container = backup['container']
        filename = self._sha256_filename(backup)
        LOG.debug('_read_sha256file started, container name: %(container)s, '
                  'sha256 filename: %(filename)s.',
                  {'container': container, 'filename': filename})
        with self.get_object_reader(container, filename) as reader:
            sha256file_json = reader.read()
        if six.PY3:
            sha256file_json = sha256file_json.decode('utf-8')
        sha256file = json.loads(sha256file_json)
        LOG.debug('_read_sha256file finished (%s).', sha256file)
        return sha256file

    def _prepare_backup(self, backup):
        """Prepare the backup process and return the backup metadata."""
        volume = self.db.volume_get(self.context, backup.volume_id)

        if volume['size'] <= 0:
            err = _('volume size %d is invalid.') % volume['size']
            raise exception.InvalidVolume(reason=err)

        container = self._create_container(self.context, backup)

        object_prefix = self._generate_object_name_prefix(backup)
        backup.service_metadata = object_prefix
        backup.save()

        volume_size_bytes = volume['size'] * units.Gi
        availability_zone = self.az
        LOG.debug('starting backup of volume: %(volume_id)s,'
                  ' volume size: %(volume_size_bytes)d, object names'
                  ' prefix %(object_prefix)s, availability zone:'
                  ' %(availability_zone)s',
                  {
                      'volume_id': backup.volume_id,
                      'volume_size_bytes': volume_size_bytes,
                      'object_prefix': object_prefix,
                      'availability_zone': availability_zone,
                  })
        object_meta = {'id': 1, 'list': [], 'prefix': object_prefix,
                       'volume_meta': None}
        object_sha256 = {'id': 1, 'sha256s': [], 'prefix': object_prefix}
        extra_metadata = self.get_extra_metadata(backup, volume)
        if extra_metadata is not None:
            object_meta['extra_metadata'] = extra_metadata

        return (object_meta, object_sha256, extra_metadata, container,
                volume_size_bytes)

    def _backup_chunk(self, backup, container, data, data_offset,
                      object_meta, extra_metadata):
        """Backup data chunk based on the object metadata and offset."""
        object_prefix = object_meta['prefix']
        object_list = object_meta['list']

        object_id = object_meta['id']
        object_name = '%s-%05d' % (object_prefix, object_id)
        obj = {}
        obj[object_name] = {}
        obj[object_name]['offset'] = data_offset
        obj[object_name]['length'] = len(data)
        LOG.debug('Backing up chunk of data from volume.')
        algorithm, output_data = self._prepare_output_data(data)
        obj[object_name]['compression'] = algorithm
        LOG.debug('About to put_object')
        with self.get_object_writer(
                container, object_name, extra_metadata=extra_metadata
        ) as writer:
            writer.write(output_data)
        md5 = hashlib.md5(data).hexdigest()
        obj[object_name]['md5'] = md5
        LOG.debug('backup MD5 for %(object_name)s: %(md5)s',
                  {'object_name': object_name, 'md5': md5})
        object_list.append(obj)
        object_id += 1
        object_meta['list'] = object_list
        object_meta['id'] = object_id

        LOG.debug('Calling eventlet.sleep(0)')
        eventlet.sleep(0)

    def _prepare_output_data(self, data):
        if self.compressor is None:
            return 'none', data
        data_size_bytes = len(data)
        compressed_data = self.compressor.compress(data)
        comp_size_bytes = len(compressed_data)
        algorithm = CONF.backup_compression_algorithm.lower()
        if comp_size_bytes >= data_size_bytes:
            LOG.debug('Compression of this chunk was ineffective: '
                      'original length: %(data_size_bytes)d, '
                      'compressed length: %(compressed_size_bytes)d. '
                      'Using original data for this chunk.',
                      {'data_size_bytes': data_size_bytes,
                       'comp_size_bytes': comp_size_bytes,
                       })
            return 'none', data
        LOG.debug('Compressed %(data_size_bytes)d bytes of data '
                  'to %(comp_size_bytes)d bytes using %(algorithm)s.',
                  {'data_size_bytes': data_size_bytes,
                   'comp_size_bytes': comp_size_bytes,
                   'algorithm': algorithm,
                   })
        return algorithm, compressed_data

    def _finalize_backup(self, backup, container, object_meta, object_sha256):
        """Write the backup's metadata to the backup repository."""
        object_list = object_meta['list']
        object_id = object_meta['id']
        volume_meta = object_meta['volume_meta']
        sha256_list = object_sha256['sha256s']
        extra_metadata = object_meta.get('extra_metadata')
        self._write_sha256file(backup,
                               backup.volume_id,
                               container,
                               sha256_list)
        self._write_metadata(backup,
                             backup.volume_id,
                             container,
                             object_list,
                             volume_meta,
                             extra_metadata)
        backup.object_count = object_id
        backup.save()
        LOG.debug('backup %s finished.', backup['id'])

    def _backup_metadata(self, backup, object_meta):
        """Backup volume metadata.

        NOTE(dosaboy): the metadata we are backing up is obtained from a
                       versioned api so we should not alter it in any way here.
                       We must also be sure that the service that will perform
                       the restore is compatible with version used.
        """
        json_meta = self.get_metadata(backup['volume_id'])
        if not json_meta:
            LOG.debug("No volume metadata to backup.")
            return

        object_meta["volume_meta"] = json_meta

    def _send_progress_end(self, context, backup, object_meta):
        object_meta['backup_percent'] = 100
        volume_utils.notify_about_backup_usage(context,
                                               backup,
                                               "createprogress",
                                               extra_usage_info=
                                               object_meta)

    def _send_progress_notification(self, context, backup, object_meta,
                                    total_block_sent_num, total_volume_size):
        backup_percent = total_block_sent_num * 100 / total_volume_size
        object_meta['backup_percent'] = backup_percent
        volume_utils.notify_about_backup_usage(context,
                                               backup,
                                               "createprogress",
                                               extra_usage_info=
                                               object_meta)

    def backup(self, backup, volume_file, backup_metadata=True):
        """Backup the given volume.

           If backup['parent_id'] is given, then an incremental backup
           is performed.
        """
        if self.chunk_size_bytes % self.sha_block_size_bytes:
            err = _('Chunk size is not multiple of '
                    'block size for creating hash.')
            raise exception.InvalidBackup(reason=err)

        # Read the shafile of the parent backup if backup['parent_id']
        # is given.
        parent_backup_shafile = None
        parent_backup = None
        if backup.parent_id:
            parent_backup = objects.Backup.get_by_id(self.context,
                                                     backup.parent_id)
            parent_backup_shafile = self._read_sha256file(parent_backup)
            parent_backup_shalist = parent_backup_shafile['sha256s']
            if (parent_backup_shafile['chunk_size'] !=
                    self.sha_block_size_bytes):
                err = (_('Hash block size has changed since the last '
                         'backup. New hash block size: %(new)s. Old hash '
                         'block size: %(old)s. Do a full backup.')
                       % {'old': parent_backup_shafile['chunk_size'],
                          'new': self.sha_block_size_bytes})
                raise exception.InvalidBackup(reason=err)
            # If the volume size increased since the last backup, fail
            # the incremental backup and ask user to do a full backup.
            if backup.size > parent_backup.size:
                err = _('Volume size increased since the last '
                        'backup. Do a full backup.')
                raise exception.InvalidBackup(reason=err)

        (object_meta, object_sha256, extra_metadata, container,
         volume_size_bytes) = self._prepare_backup(backup)

        counter = 0
        total_block_sent_num = 0

        # There are two mechanisms to send the progress notification.
        # 1. The notifications are periodically sent in a certain interval.
        # 2. The notifications are sent after a certain number of chunks.
        # Both of them are working simultaneously during the volume backup,
        # when "chunked" backup drivers are deployed.
        def _notify_progress():
            self._send_progress_notification(self.context, backup,
                                             object_meta,
                                             total_block_sent_num,
                                             volume_size_bytes)
        timer = loopingcall.FixedIntervalLoopingCall(
            _notify_progress)
        if self.enable_progress_timer:
            timer.start(interval=self.backup_timer_interval)

        sha256_list = object_sha256['sha256s']
        shaindex = 0
        is_backup_canceled = False
        while True:
            # First of all, we check the status of this backup. If it
            # has been changed to delete or has been deleted, we cancel the
            # backup process to do forcing delete.
            backup = objects.Backup.get_by_id(self.context, backup.id)
            if 'deleting' == backup.status or 'deleted' == backup.status:
                is_backup_canceled = True
                # To avoid the chunk left when deletion complete, need to
                # clean up the object of chunk again.
                self.delete(backup)
                LOG.debug('Cancel the backup process of %s.', backup.id)
                break
            data_offset = volume_file.tell()
            data = volume_file.read(self.chunk_size_bytes)
            if data == b'':
                break

            # Calculate new shas with the datablock.
            shalist = []
            off = 0
            datalen = len(data)
            while off < datalen:
                chunk_start = off
                chunk_end = chunk_start + self.sha_block_size_bytes
                if chunk_end > datalen:
                    chunk_end = datalen
                chunk = data[chunk_start:chunk_end]
                sha = hashlib.sha256(chunk).hexdigest()
                shalist.append(sha)
                off += self.sha_block_size_bytes
            sha256_list.extend(shalist)

            # If parent_backup is not None, that means an incremental
            # backup will be performed.
            if parent_backup:
                # Find the extent that needs to be backed up.
                extent_off = -1
                for idx, sha in enumerate(shalist):
                    if sha != parent_backup_shalist[shaindex]:
                        if extent_off == -1:
                            # Start of new extent.
                            extent_off = idx * self.sha_block_size_bytes
                    else:
                        if extent_off != -1:
                            # We've reached the end of extent.
                            extent_end = idx * self.sha_block_size_bytes
                            segment = data[extent_off:extent_end]
                            self._backup_chunk(backup, container, segment,
                                               data_offset + extent_off,
                                               object_meta,
                                               extra_metadata)
                            extent_off = -1
                    shaindex += 1

                # The last extent extends to the end of data buffer.
                if extent_off != -1:
                    extent_end = datalen
                    segment = data[extent_off:extent_end]
                    self._backup_chunk(backup, container, segment,
                                       data_offset + extent_off,
                                       object_meta, extra_metadata)
                    extent_off = -1
            else:  # Do a full backup.
                self._backup_chunk(backup, container, data, data_offset,
                                   object_meta, extra_metadata)

            # Notifications
            total_block_sent_num += self.data_block_num
            counter += 1
            if counter == self.data_block_num:
                # Send the notification to Ceilometer when the chunk
                # number reaches the data_block_num.  The backup percentage
                # is put in the metadata as the extra information.
                self._send_progress_notification(self.context, backup,
                                                 object_meta,
                                                 total_block_sent_num,
                                                 volume_size_bytes)
                # Reset the counter
                counter = 0

        # Stop the timer.
        timer.stop()
        # If backup has been cancelled we have nothing more to do
        # but timer.stop().
        if is_backup_canceled:
            return
        # All the data have been sent, the backup_percent reaches 100.
        self._send_progress_end(self.context, backup, object_meta)

        object_sha256['sha256s'] = sha256_list
        if backup_metadata:
            try:
                self._backup_metadata(backup, object_meta)
            # Whatever goes wrong, we want to log, cleanup, and re-raise.
            except Exception as err:
                with excutils.save_and_reraise_exception():
                    LOG.exception(_LE("Backup volume metadata failed: %s."),
                                  err)
                    self.delete(backup)

        self._finalize_backup(backup, container, object_meta, object_sha256)

    def _restore_v1(self, backup, volume_id, metadata, volume_file):
        """Restore a v1 volume backup."""
        backup_id = backup['id']
        LOG.debug('v1 volume backup restore of %s started.', backup_id)
        extra_metadata = metadata.get('extra_metadata')
        container = backup['container']
        metadata_objects = metadata['objects']
        metadata_object_names = []
        for obj in metadata_objects:
            metadata_object_names.extend(obj.keys())
        LOG.debug('metadata_object_names = %s.', metadata_object_names)
        prune_list = [self._metadata_filename(backup),
                      self._sha256_filename(backup)]
        object_names = [object_name for object_name in
                        self._generate_object_names(backup)
                        if object_name not in prune_list]
        if sorted(object_names) != sorted(metadata_object_names):
            err = _('restore_backup aborted, actual object list '
                    'does not match object list stored in metadata.')
            raise exception.InvalidBackup(reason=err)

        for metadata_object in metadata_objects:
            object_name, obj = list(metadata_object.items())[0]
            LOG.debug('restoring object. backup: %(backup_id)s, '
                      'container: %(container)s, object name: '
                      '%(object_name)s, volume: %(volume_id)s.',
                      {
                          'backup_id': backup_id,
                          'container': container,
                          'object_name': object_name,
                          'volume_id': volume_id,
                      })

            with self.get_object_reader(
                    container, object_name,
                    extra_metadata=extra_metadata) as reader:
                body = reader.read()
            compression_algorithm = metadata_object[object_name]['compression']
            decompressor = self._get_compressor(compression_algorithm)
            volume_file.seek(obj['offset'])
            if decompressor is not None:
                LOG.debug('decompressing data using %s algorithm',
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
                LOG.info(_LI("volume_file does not support "
                             "fileno() so skipping "
                             "fsync()"))
            else:
                os.fsync(fileno)

            # Restoring a backup to a volume can take some time. Yield so other
            # threads can run, allowing for among other things the service
            # status to be updated
            eventlet.sleep(0)
        LOG.debug('v1 volume backup restore of %s finished.',
                  backup_id)

    def restore(self, backup, volume_id, volume_file):
        """Restore the given volume backup from backup repository."""
        backup_id = backup['id']
        container = backup['container']
        object_prefix = backup['service_metadata']
        LOG.debug('starting restore of backup %(object_prefix)s '
                  'container: %(container)s, to volume %(volume_id)s, '
                  'backup: %(backup_id)s.',
                  {
                      'object_prefix': object_prefix,
                      'container': container,
                      'volume_id': volume_id,
                      'backup_id': backup_id,
                  })
        metadata = self._read_metadata(backup)
        metadata_version = metadata['version']
        LOG.debug('Restoring backup version %s', metadata_version)
        try:
            restore_func = getattr(self, self.DRIVER_VERSION_MAPPING.get(
                metadata_version))
        except TypeError:
            err = (_('No support to restore backup version %s')
                   % metadata_version)
            raise exception.InvalidBackup(reason=err)

        # Build a list of backups based on parent_id. A full backup
        # will be the last one in the list.
        backup_list = []
        backup_list.append(backup)
        current_backup = backup
        while current_backup.parent_id:
            prev_backup = objects.Backup.get_by_id(self.context,
                                                   current_backup.parent_id)
            backup_list.append(prev_backup)
            current_backup = prev_backup

        # Do a full restore first, then layer the incremental backups
        # on top of it in order.
        index = len(backup_list) - 1
        while index >= 0:
            backup1 = backup_list[index]
            index = index - 1
            metadata = self._read_metadata(backup1)
            restore_func(backup1, volume_id, metadata, volume_file)

            volume_meta = metadata.get('volume_meta', None)
            try:
                if volume_meta:
                    self.put_metadata(volume_id, volume_meta)
                else:
                    LOG.debug("No volume metadata in this backup.")
            except exception.BackupMetadataUnsupportedVersion:
                msg = _("Metadata restore failed due to incompatible version.")
                LOG.error(msg)
                raise exception.BackupOperationError(msg)

        LOG.debug('restore %(backup_id)s to %(volume_id)s finished.',
                  {'backup_id': backup_id, 'volume_id': volume_id})

    def delete(self, backup):
        """Delete the given backup."""
        container = backup['container']
        object_prefix = backup['service_metadata']
        LOG.debug('delete started, backup: %(id)s, container: %(cont)s, '
                  'prefix: %(pre)s.',
                  {'id': backup['id'],
                   'cont': container,
                   'pre': object_prefix})

        if container is not None and object_prefix is not None:
            object_names = []
            try:
                object_names = self._generate_object_names(backup)
            except Exception:
                LOG.warning(_LW('Error while listing objects, continuing'
                                ' with delete.'))

            for object_name in object_names:
                self.delete_object(container, object_name)
                LOG.debug('deleted object: %(object_name)s'
                          ' in container: %(container)s.',
                          {
                              'object_name': object_name,
                              'container': container
                          })
                # Deleting a backup's objects can take some time.
                # Yield so other threads can run
                eventlet.sleep(0)

        LOG.debug('delete %s finished.', backup['id'])
