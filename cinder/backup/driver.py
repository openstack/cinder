# Copyright (C) 2013 Deutsche Telekom AG
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

"""Base class for all backup drivers."""

import abc

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from cinder.db import base
from cinder import exception
from cinder.i18n import _

backup_opts = [
    cfg.IntOpt('backup_metadata_version', default=2,
               help='Backup metadata version to be used when backing up '
                    'volume metadata. If this number is bumped, make sure the '
                    'service doing the restore supports the new version.'),
    cfg.IntOpt('backup_object_number_per_notification',
               default=10,
               help='The number of chunks or objects, for which one '
                    'Ceilometer notification will be sent'),
    cfg.IntOpt('backup_timer_interval',
               default=120,
               help='Interval, in seconds, between two progress notifications '
                    'reporting the backup status'),
]

CONF = cfg.CONF
CONF.register_opts(backup_opts)

LOG = logging.getLogger(__name__)


class BackupMetadataAPI(base.Base):

    TYPE_TAG_VOL_BASE_META = 'volume-base-metadata'
    TYPE_TAG_VOL_META = 'volume-metadata'
    TYPE_TAG_VOL_GLANCE_META = 'volume-glance-metadata'

    def __init__(self, context, db=None):
        super(BackupMetadataAPI, self).__init__(db)
        self.context = context
        self._key_mgr = None

    @staticmethod
    def _is_serializable(value):
        """Returns True if value is serializable."""
        try:
            jsonutils.dumps(value)
        except TypeError:
            LOG.info("Value with type=%s is not serializable",
                     type(value))
            return False

        return True

    def _save_vol_base_meta(self, container, volume_id):
        """Save base volume metadata to container.

        This will fetch all fields from the db Volume object for volume_id and
        save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_BASE_META
        LOG.debug("Getting metadata type '%s'", type_tag)
        meta = self.db.volume_get(self.context, volume_id)
        if meta:
            container[type_tag] = {}
            for key, value in meta:
                # Exclude fields that are "not JSON serializable"
                if not self._is_serializable(value):
                    LOG.info("Unable to serialize field '%s' - excluding "
                             "from backup", key)
                    continue
                # NOTE(abishop): The backup manager is now responsible for
                # ensuring a copy of the volume's encryption key ID is
                # retained in case the volume is deleted. Yes, this means
                # the backup's volume base metadata now stores the volume's
                # original encryption key ID, which affects how things are
                # handled when backups are restored. The backup manager
                # handles this, too.
                container[type_tag][key] = value

            LOG.debug("Completed fetching metadata type '%s'", type_tag)
        else:
            LOG.debug("No metadata type '%s' available", type_tag)

    def _save_vol_meta(self, container, volume_id):
        """Save volume metadata to container.

        This will fetch all fields from the db VolumeMetadata object for
        volume_id and save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_META
        LOG.debug("Getting metadata type '%s'", type_tag)
        meta = self.db.volume_metadata_get(self.context, volume_id)
        if meta:
            container[type_tag] = {}
            for entry in meta:
                # Exclude fields that are "not JSON serializable"
                if not self._is_serializable(meta[entry]):
                    LOG.info("Unable to serialize field '%s' - excluding "
                             "from backup", entry)
                    continue
                container[type_tag][entry] = meta[entry]

            LOG.debug("Completed fetching metadata type '%s'", type_tag)
        else:
            LOG.debug("No metadata type '%s' available", type_tag)

    def _save_vol_glance_meta(self, container, volume_id):
        """Save volume Glance metadata to container.

        This will fetch all fields from the db VolumeGlanceMetadata object for
        volume_id and save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_GLANCE_META
        LOG.debug("Getting metadata type '%s'", type_tag)
        try:
            meta = self.db.volume_glance_metadata_get(self.context, volume_id)
            if meta:
                container[type_tag] = {}
                for entry in meta:
                    # Exclude fields that are "not JSON serializable"
                    if not self._is_serializable(entry.value):
                        LOG.info("Unable to serialize field '%s' - "
                                 "excluding from backup", entry)
                        continue
                    container[type_tag][entry.key] = entry.value

            LOG.debug("Completed fetching metadata type '%s'", type_tag)
        except exception.GlanceMetadataNotFound:
            LOG.debug("No metadata type '%s' available", type_tag)

    @staticmethod
    def _filter(metadata, fields, excludes=None):
        """Returns set of metadata restricted to required fields.

        If fields is empty list, the full set is returned.

        :param metadata: master set of metadata
        :param fields: list of fields we want to extract
        :param excludes: fields to be excluded
        :returns: filtered metadata
        """
        if not fields:
            return metadata

        if not excludes:
            excludes = []

        subset = {}
        for field in fields:
            if field in metadata and field not in excludes:
                subset[field] = metadata[field]
            else:
                LOG.debug("Excluding field '%s'", field)

        return subset

    def _restore_vol_base_meta(self, metadata, volume_id, fields):
        """Restore values to Volume object for provided fields."""
        LOG.debug("Restoring volume base metadata")
        excludes = []

        # Ignore unencrypted backups.
        key = 'encryption_key_id'
        if key in fields and key in metadata and metadata[key] is not None:
            self._restore_vol_encryption_meta(volume_id,
                                              metadata['volume_type_id'])

        # NOTE(dosaboy): if the target volume looks like it was auto-created
        # as part of this restore operation and we have a name to restore
        # then apply the name to the target volume. However, if that target
        # volume already existed and it has a name or we do not have a name to
        # restore, then ignore this key. This is intended to be a less drastic
        # solution than commit 7ee80f7.
        key = 'display_name'
        if key in fields and key in metadata:
            target_vol = self.db.volume_get(self.context, volume_id)
            name = target_vol.get(key, '')
            if (not metadata.get(key) or name and
                    not name.startswith('restore_backup_')):
                excludes.append(key)
                excludes.append('display_description')

        metadata = self._filter(metadata, fields, excludes=excludes)
        self.db.volume_update(self.context, volume_id, metadata)

    def _restore_vol_encryption_meta(self, volume_id, src_volume_type_id):
        """Restores the volume_type_id for encryption if needed.

        Only allow restoration of an encrypted backup if the destination
        volume has the same volume type as the source volume. Otherwise
        encryption will not work. If volume types are already the same,
        no action is needed.
        """
        dest_vol = self.db.volume_get(self.context, volume_id)
        if dest_vol['volume_type_id'] != src_volume_type_id:
            LOG.debug("Volume type id's do not match.")
            # If the volume types do not match, and the destination volume
            # does not have a volume type, force the destination volume
            # to have the encrypted volume type, provided it still exists.
            if dest_vol['volume_type_id'] is None:
                try:
                    self.db.volume_type_get(
                        self.context, src_volume_type_id)
                except exception.VolumeTypeNotFound:
                    LOG.debug("Volume type of source volume has been "
                              "deleted. Encrypted backup restore has "
                              "failed.")
                    msg = _("The source volume type '%s' is not "
                            "available.") % (src_volume_type_id)
                    raise exception.EncryptedBackupOperationFailed(msg)
                # Update dest volume with src volume's volume_type_id.
                LOG.debug("The volume type of the destination volume "
                          "will become the volume type of the source "
                          "volume.")
                self.db.volume_update(self.context, volume_id,
                                      {'volume_type_id': src_volume_type_id})
            else:
                # Volume type id's do not match, and destination volume
                # has a volume type. Throw exception.
                LOG.warning("Destination volume type is different from "
                            "source volume type for an encrypted volume. "
                            "Encrypted backup restore has failed.")
                msg = (_("The source volume type '%(src)s' is different "
                         "than the destination volume type '%(dest)s'.") %
                       {'src': src_volume_type_id,
                        'dest': dest_vol['volume_type_id']})
                raise exception.EncryptedBackupOperationFailed(msg)

    def _restore_vol_meta(self, metadata, volume_id, fields):
        """Restore values to VolumeMetadata object for provided fields."""
        LOG.debug("Restoring volume metadata")
        metadata = self._filter(metadata, fields)
        self.db.volume_metadata_update(self.context, volume_id, metadata, True)

    def _restore_vol_glance_meta(self, metadata, volume_id, fields):
        """Restore values to VolumeGlanceMetadata object for provided fields.

        First delete any existing metadata then save new values.
        """
        LOG.debug("Restoring volume glance metadata")
        metadata = self._filter(metadata, fields)
        self.db.volume_glance_metadata_delete_by_volume(self.context,
                                                        volume_id)
        for key, value in metadata.items():
            self.db.volume_glance_metadata_create(self.context,
                                                  volume_id,
                                                  key, value)

        # Now mark the volume as bootable
        self.db.volume_update(self.context, volume_id,
                              {'bootable': True})

    def _v1_restore_factory(self):
        """All metadata is backed up but we selectively restore.

        Returns a dictionary of the form:

            {<type tag>: (<restore function>, <fields list>)}

        Empty field list indicates that all backed up fields should be
        restored.
        """
        return {self.TYPE_TAG_VOL_BASE_META:
                (self._restore_vol_base_meta,
                 ['display_name', 'display_description']),
                self.TYPE_TAG_VOL_META:
                (self._restore_vol_meta, []),
                self.TYPE_TAG_VOL_GLANCE_META:
                (self._restore_vol_glance_meta, [])}

    def _v2_restore_factory(self):
        """All metadata is backed up but we selectively restore.

        Returns a dictionary of the form:

            {<type tag>: (<restore function>, <fields list>)}

        Empty field list indicates that all backed up fields should be
        restored.
        """
        return {self.TYPE_TAG_VOL_BASE_META:
                (self._restore_vol_base_meta,
                 ['display_name', 'display_description', 'encryption_key_id']),
                self.TYPE_TAG_VOL_META:
                (self._restore_vol_meta, []),
                self.TYPE_TAG_VOL_GLANCE_META:
                (self._restore_vol_glance_meta, [])}

    def get(self, volume_id):
        """Get volume metadata.

        Returns a json-encoded dict containing all metadata and the restore
        version i.e. the version used to decide what actually gets restored
        from this container when doing a backup restore.
        """
        container = {'version': CONF.backup_metadata_version}
        self._save_vol_base_meta(container, volume_id)
        self._save_vol_meta(container, volume_id)
        self._save_vol_glance_meta(container, volume_id)

        if container:
            return jsonutils.dumps(container)
        else:
            return None

    def put(self, volume_id, json_metadata):
        """Restore volume metadata to a volume.

        The json container should contain a version that is supported here.
        """
        meta_container = jsonutils.loads(json_metadata)
        version = meta_container['version']
        if version == 1:
            factory = self._v1_restore_factory()
        elif version == 2:
            factory = self._v2_restore_factory()
        else:
            msg = (_("Unsupported backup metadata version (%s)") % (version))
            raise exception.BackupMetadataUnsupportedVersion(msg)

        for type in factory:
            func = factory[type][0]
            fields = factory[type][1]
            if type in meta_container:
                func(meta_container[type], volume_id, fields)
            else:
                LOG.debug("No metadata of type '%s' to restore", type)


@six.add_metaclass(abc.ABCMeta)
class BackupDriver(base.Base):

    def __init__(self, context, db=None):
        super(BackupDriver, self).__init__(db)
        self.context = context
        self.backup_meta_api = BackupMetadataAPI(context, db)
        # This flag indicates if backup driver supports force
        # deletion. So it should be set to True if the driver that inherits
        # from BackupDriver supports the force deletion function.
        self.support_force_delete = False

    def get_metadata(self, volume_id):
        return self.backup_meta_api.get(volume_id)

    def put_metadata(self, volume_id, json_metadata):
        self.backup_meta_api.put(volume_id, json_metadata)

    @abc.abstractmethod
    def backup(self, backup, volume_file, backup_metadata=False):
        """Start a backup of a specified volume.

        Some I/O operations may block greenthreads, so in order to prevent
        starvation parameter volume_file will be a proxy that will execute all
        methods in native threads, so the method implementation doesn't need to
        worry about that..
        """
        return

    @abc.abstractmethod
    def restore(self, backup, volume_id, volume_file):
        """Restore a saved backup.

        Some I/O operations may block greenthreads, so in order to prevent
        starvation parameter volume_file will be a proxy that will execute all
        methods in native threads, so the method implementation doesn't need to
        worry about that..

        May raise BackupRestoreCancel to indicate that the restoration of a
        volume has been aborted by changing the backup status.
        """
        return

    @abc.abstractmethod
    def delete_backup(self, backup):
        """Delete a saved backup."""
        return

    def export_record(self, backup):
        """Export driver specific backup record information.

        If backup backend needs additional driver specific information to
        import backup record back into the system it must overwrite this method
        and return it here as a dictionary so it can be serialized into a
        string.

        Default backup driver implementation has no extra information.

        :param backup: backup object to export
        :returns: driver_info - dictionary with extra information
        """
        return {}

    def import_record(self, backup, driver_info):
        """Import driver specific backup record information.

        If backup backend needs additional driver specific information to
        import backup record back into the system it must overwrite this method
        since it will be called with the extra information that was provided by
        export_record when exporting the backup.

        Default backup driver implementation does nothing since it didn't
        export any specific data in export_record.

        :param backup: backup object to export
        :param driver_info: dictionary with driver specific backup record
                            information
        :returns: nothing
        """
        return

    def check_for_setup_error(self):
        """Method for checking if backup backend is successfully installed."""
        return


@six.add_metaclass(abc.ABCMeta)
class BackupDriverWithVerify(BackupDriver):
    @abc.abstractmethod
    def verify(self, backup):
        """Verify that the backup exists on the backend.

        Verify that the backup is OK, possibly following an import record
        operation.

        :param backup: backup id of the backup to verify
        :raises InvalidBackup, NotImplementedError:
        """
        return
