# Copyright 2013 Canonical Ltd.
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

"""Ceph Backup Service Implementation.

This driver supports backuping up ceph volumes to a s3 like object store.

It is capable of performing incremental backups.

If incremental backups are used, multiple backups of the same volume are stored
as snapshots so that minimal space is consumed in the object store and
restoring the volume takes a far reduced amount of time compared to a full
copy.

Note that Cinder supports restoring to a new volume or the original volume the
backup was taken from. For the latter case, a full copy is enforced since this
was deemed the safest action to take. It is therefore recommended to always
restore to a new volume (default).
"""

import fcntl
import os
import re
import subprocess
import time
#import boto
#import boto.s3.connection

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import units

from cinder.backup import driver
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder import utils
import cinder.volume.drivers.rbd as rbd_driver

try:
    import rbd
except ImportError:
    rbd = None

LOG = logging.getLogger(__name__)

service_opts = [
    cfg.StrOpt('sbs_access_key', default='',
               help='Access key for S3 store.'),
    cfg.StrOpt('sbs_secret_key', default='',
               help='Secrete key for S3 store.'),
    cfg.StrOpt('sbs_container', default='backups',
               help='Container in S3 store to save backups.'),

]

CONF = cfg.CONF
CONF.register_opts(service_opts)

class SBSBackupDriver(driver.BackupDriver):
    """Backup Cinder volumes to S3 like Object Store.

    The backup will be performed using incremental differential backups which
	 *should* give a performance gain.
    """
    def __init__(self, context, db_driver=None, execute=None):
        super(SBSBackupDriver, self).__init__(context, db_driver)
        self.rbd = rbd
        self._execute = execute or utils.execute
	self._access_key = encodeutils.safe_encode(CONF.sbs_access_key)
	self._secret_key = encodeutils.safe_encode(CONF.sbs_secret_key)
	self._container = encodeutils.safe_encode(CONF.sbs_container)

    def _get_backup_base_name(self, volume_id, backup_id=None,
                              diff_format=False):
        # Ensure no unicode
        return encodeutils.safe_encode("volume-%s.backup.base" % volume_id)

    @staticmethod
    def backup_snapshot_name_pattern():
        """Returns the pattern used to match backup snapshots.

        It is essential that snapshots created for purposes other than backups
        do not have this name format.
        """
        return r"^backup\.([a-z0-9\-]+?)\.snap\.(.+)$"


    def _get_new_snap_name(self, backup_id):
        return encodeutils.safe_encode("backup.%s.snap.%s" %
                                       (backup_id, time.time()))

    def _get_volume_size_gb(self, volume):
        """Return the size in gigabytes of the given volume.

        Raises exception.InvalidParameterValue if volume size is 0.
        """
        if int(volume['size']) == 0:
            errmsg = _("Need non-zero volume size")
            raise exception.InvalidParameterValue(errmsg)

        return int(volume['size']) * units.Gi

    @classmethod
    def get_backup_snaps(cls, rbd_image, sort=False):
        """Get all backup snapshots for the given rbd image.

        NOTE: this call is made public since these snapshots must be deleted
              before the base volume can be deleted.
        """
        backup_snaps=None
        return backup_snaps

    def _get_most_recent_snap(self, rbd_image):
        """Get the most recent backup snapshot of the provided image.

        Returns name of most recent backup snapshot or None if there are no
        backup snapshots.
        """
        backup_snaps = self.get_backup_snaps(rbd_image, sort=True)
        if not backup_snaps:
            return None

        return backup_snaps[0]['name']

	# shishir change this to work out of s3 or db 
    def _lookup_base_in_dest(self, base_name):
        #Return True if snapshot exists in base image.
		return False

	# shishir change this to work out of s3 or db 
    def _snap_exists(self, base_name, snap_name):
        #Return True if snapshot exists in base image
        return False

    def _upload_to_DSS(self, snap_name, from_snap=None):
        #if from_snap is None, do full upload
        return
    """
    1. If 1st snapshot or missing base or missing incr snap
        create new snapshot (without incr) and treat it as base
        take snapshot from base (incr) with given name (size might be 0)
        upload/store both base and incr snap
    2. If incr snapshot
        create incr snapshot w.r.t latest snap
        upload/store snapshot
    """

    def _check_create_base(self, volume_file, base_name, from_snap):

        #Create an incremental backup from an RBD image.
        rbd_user = volume_file.rbd_user
        rbd_pool = volume_file.rbd_pool
        rbd_conf = volume_file.rbd_conf
        source_rbd_image = volume_file.rbd_image

        # Check if base image exists in dest
        found_base_image = self._lookup_base_in_dest(base_name)

        #If base image not found, create base image, might be 1st snap
        if not found_base_image:
            # since base image is missing, default to full snap.Cleanup too
            if from_snap:
                LOG.debug("Source snapshot '%(snapshot)s' of volume "
                          "%(volume)s is stale so deleting.",
                          {'snapshot': from_snap, 'volume': volume_id})
                source_rbd_image.remove_snap(from_snap)
                source_rbd_image.remove_snap(base_name)
                from_snap = None

            #Create new base image and upload it, so from-snap also becomes base
            from_snap = base_name
            source_rbd_image.create_snap(base_name)
            self._upload_to_DSS(base_name)
        else:
            # If a from_snap is defined but does not exist in the back base
            # then we cannot proceed (see above)
            if not self._snap_exists(base_name, from_snap):
                errmsg = (_("Snapshot='%(snap)s' does not exist in base "
                            "image='%(base)s' - aborting incremental "
                            "backup") %
                          {'snap': from_snap, 'base': base_name})
                LOG.info(errmsg)
                # Raise this exception so that caller can try another
                # approach
                raise exception.BackupRBDOperationFailed(errmsg)


        return (base_name, from_snap)

    def _backup_rbd(self, backup_id, volume_id, volume_file, volume_name,
				    length):
        #Create an incremental backup from an RBD image.
        rbd_user = volume_file.rbd_user
        rbd_pool = volume_file.rbd_pool
        rbd_conf = volume_file.rbd_conf
        source_rbd_image = volume_file.rbd_image

        # Identify our --from-snap point (if one exists)
        from_snap = self._get_most_recent_snap(source_rbd_image)
        base_name = self._get_backup_base_name(volume_id, diff_format=True)
        LOG.debug("Using --from-snap '%(snap)s' for incremental backup of "
                  "volume %(volume)s, with base image '%s(base)s'.",
                    {'snap': from_snap, 'volume': volume_id,
                     'base': base_name})

        #check base snap and from_snap and create base if missing
        base_name, from_snap = self._check_create_base(volume_file, base_name, from_snap)

        # Snapshot source volume so that we have a new point-in-time
        new_snap = self._get_new_snap_name(backup_id)
        LOG.debug("Creating backup snapshot='%s'", new_snap)
        source_rbd_image.create_snap(new_snap)
        # export diff now
        self._upload_to_DSS(new_snap, from_snap)

        self.db.backup_update(self.context, backup_id,
                              {'container': self._container})
        return

    def backup(self, backup, volume_file, backup_metadata=False):
        backup_id = backup['id']
        volume = self.db.volume_get(self.context,backup['volume_id'])
        volume_id = volume['id']
        volume_name = volume['name']

        LOG.debug("Starting backup of volume='%s'.", volume_id)

        # Ensure we are at the beginning of the volume
        volume_file.seek(0)
        length = self._get_volume_size_gb(volume)

        self._backup_rbd(backup_id, volume_id, volume_file, volume_name, length)

        self.db.backup_update(self.context, backup_id,
                              {'container': self._container})
        return

    def restore(self, backup, volume_id, volume_file):
		return

    def delete(self, backup):
        return

def get_backup_driver(context):
    return SBSBackupDriver(context)
