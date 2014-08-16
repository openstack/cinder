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

from oslo.config import cfg
import six

from cinder.db import base
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import jsonutils
from cinder.openstack.common import log as logging

service_opts = [
    cfg.IntOpt('backup_metadata_version', default=1,
               help='Backup metadata version to be used when backing up '
                    'volume metadata. If this number is bumped, make sure the '
                    'service doing the restore supports the new version.')
]

CONF = cfg.CONF
CONF.register_opts(service_opts)

LOG = logging.getLogger(__name__)


class BackupMetadataAPI(base.Base):

    TYPE_TAG_VOL_BASE_META = 'volume-base-metadata'
    TYPE_TAG_VOL_META = 'volume-metadata'
    TYPE_TAG_VOL_GLANCE_META = 'volume-glance-metadata'

    def __init__(self, context, db_driver=None):
        super(BackupMetadataAPI, self).__init__(db_driver)
        self.context = context

    @staticmethod
    def _is_serializable(value):
        """Returns True if value is serializable."""
        try:
            jsonutils.dumps(value)
        except TypeError:
            LOG.info(_("Value with type=%s is not serializable") %
                     type(value))
            return False

        return True

    def _save_vol_base_meta(self, container, volume_id):
        """Save base volume metadata to container.

        This will fetch all fields from the db Volume object for volume_id and
        save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_BASE_META
        LOG.debug("Getting metadata type '%s'" % type_tag)
        meta = self.db.volume_get(self.context, volume_id)
        if meta:
            container[type_tag] = {}
            for key, value in meta:
                # Exclude fields that are "not JSON serializable"
                if not self._is_serializable(value):
                    LOG.info(_("Unable to serialize field '%s' - excluding "
                               "from backup") % (key))
                    continue
                container[type_tag][key] = value

            LOG.debug("Completed fetching metadata type '%s'" % type_tag)
        else:
            LOG.debug("No metadata type '%s' available" % type_tag)

    def _save_vol_meta(self, container, volume_id):
        """Save volume metadata to container.

        This will fetch all fields from the db VolumeMetadata object for
        volume_id and save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_META
        LOG.debug("Getting metadata type '%s'" % type_tag)
        meta = self.db.volume_metadata_get(self.context, volume_id)
        if meta:
            container[type_tag] = {}
            for entry in meta:
                # Exclude fields that are "not JSON serializable"
                if not self._is_serializable(meta[entry]):
                    LOG.info(_("Unable to serialize field '%s' - excluding "
                               "from backup") % (entry))
                    continue
                container[type_tag][entry] = meta[entry]

            LOG.debug("Completed fetching metadata type '%s'" % type_tag)
        else:
            LOG.debug("No metadata type '%s' available" % type_tag)

    def _save_vol_glance_meta(self, container, volume_id):
        """Save volume Glance metadata to container.

        This will fetch all fields from the db VolumeGlanceMetadata object for
        volume_id and save them in the provided container dictionary.
        """
        type_tag = self.TYPE_TAG_VOL_GLANCE_META
        LOG.debug("Getting metadata type '%s'" % type_tag)
        try:
            meta = self.db.volume_glance_metadata_get(self.context, volume_id)
            if meta:
                container[type_tag] = {}
                for entry in meta:
                    # Exclude fields that are "not JSON serializable"
                    if not self._is_serializable(entry.value):
                        LOG.info(_("Unable to serialize field '%s' - "
                                   "excluding from backup") % (entry))
                        continue
                    container[type_tag][entry.key] = entry.value

            LOG.debug("Completed fetching metadata type '%s'" % type_tag)
        except exception.GlanceMetadataNotFound:
            LOG.debug("No metadata type '%s' available" % type_tag)

    @staticmethod
    def _filter(metadata, fields):
        """Returns set of metadata restricted to required fields.

        If fields is empty list, the full set is returned.
        """
        if fields == []:
            return metadata

        subset = {}
        for field in fields:
            if field in metadata:
                subset[field] = metadata[field]
            else:
                LOG.debug("Excluding field '%s'" % (field))

        return subset

    def _restore_vol_base_meta(self, metadata, volume_id, fields):
        """Restore values to Volume object for provided fields."""
        LOG.debug("Restoring volume base metadata")
        # Only set the display_name if it was not None since the
        # restore action will have set a name which is more useful than
        # None.
        key = 'display_name'
        if key in fields and key in metadata and metadata[key] is None:
            fields = [f for f in fields if f != key]

        metadata = self._filter(metadata, fields)
        self.db.volume_update(self.context, volume_id, metadata)

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

            {<type tag>: (<fields list>, <restore function>)}

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
        else:
            msg = (_("Unsupported backup metadata version (%s)") % (version))
            raise exception.BackupMetadataUnsupportedVersion(msg)

        for type in factory:
            func = factory[type][0]
            fields = factory[type][1]
            if type in meta_container:
                func(meta_container[type], volume_id, fields)
            else:
                msg = "No metadata of type '%s' to restore" % (type)
                LOG.debug(msg)


@six.add_metaclass(abc.ABCMeta)
class BackupDriver(base.Base):

    def __init__(self, context, db_driver=None):
        super(BackupDriver, self).__init__(db_driver)
        self.context = context
        self.backup_meta_api = BackupMetadataAPI(context, db_driver)

    def get_metadata(self, volume_id):
        return self.backup_meta_api.get(volume_id)

    def put_metadata(self, volume_id, json_metadata):
        self.backup_meta_api.put(volume_id, json_metadata)

    @abc.abstractmethod
    def backup(self, backup, volume_file, backup_metadata=False):
        """Start a backup of a specified volume."""
        return

    @abc.abstractmethod
    def restore(self, backup, volume_id, volume_file):
        """Restore a saved backup."""
        return

    @abc.abstractmethod
    def delete(self, backup):
        """Delete a saved backup."""
        return

    def export_record(self, backup):
        """Export backup record.

        Default backup driver implementation.
        Serialize the backup record describing the backup into a string.

        :param backup: backup entry to export
        :returns backup_url - a string describing the backup record
        """
        retval = jsonutils.dumps(backup)
        return retval.encode("base64")

    def import_record(self, backup_url):
        """Import and verify backup record.

        Default backup driver implementation.
        De-serialize the backup record into a dictionary, so we can
        update the database.

        :param backup_url: driver specific backup record string
        :returns dictionary object with database updates
        """
        return jsonutils.loads(backup_url.decode("base64"))


@six.add_metaclass(abc.ABCMeta)
class BackupDriverWithVerify(BackupDriver):
    @abc.abstractmethod
    def verify(self, backup):
        """Verify that the backup exists on the backend.

        Verify that the backup is OK, possibly following an import record
        operation.

        :param backup: backup id of the backup to verify
        :raises: InvalidBackup, NotImplementedError
        """
        return
