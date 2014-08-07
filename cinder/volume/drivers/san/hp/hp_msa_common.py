#    Copyright 2014 Objectif Libre
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
#
"""
Volume driver common utilities for HP MSA Storage array
"""

import base64
import uuid

from oslo.config import cfg

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san.hp import hp_msa_client as msa

LOG = logging.getLogger(__name__)

hpmsa_opt = [
    cfg.StrOpt('msa_vdisk',
               default='OpenStack',
               help="The VDisk to use for volume creation."),
]

CONF = cfg.CONF
CONF.register_opts(hpmsa_opt)


class HPMSACommon(object):
    VERSION = "0.1"

    stats = {}

    def __init__(self, config):
        self.config = config
        self.client = msa.HPMSAClient(self.config.san_ip,
                                      self.config.san_login,
                                      self.config.san_password)

        self.vdisk = self.config.msa_vdisk

    def get_version(self):
        return self.VERSION

    def do_setup(self, context):
        self.client_login()
        self._validate_vdisks()
        self.client_logout()

    def client_login(self):
        LOG.debug("Connecting to MSA")
        try:
            self.client.login()
        except msa.HPMSAConnectionError as ex:
            msg = (_("Failed to connect to MSA Array (%(host)s): %(err)s") %
                   {'host': self.config.san_ip, 'err': ex})
            LOG.error(msg)
            raise exception.HPMSAConnectionError(reason=msg)
        except msa.HPMSAAuthenticationError:
            msg = _("Failed to log on MSA Array (invalid login?)")
            LOG.error(msg)
            raise exception.HPMSAConnectionError(reason=msg)

    def _validate_vdisks(self):
        if not self.client.vdisk_exists(self.vdisk):
            self.client_logout()
            raise exception.HPMSAInvalidVDisk(vdisk=self.vdisk)

    def client_logout(self):
        self.client.logout()
        LOG.debug("Disconnected from MSA Array")

    def _get_vol_name(self, volume_id):
        volume_name = self._encode_name(volume_id)
        return "v%s" % volume_name

    def _get_snap_name(self, snapshot_id):
        snapshot_name = self._encode_name(snapshot_id)
        return "s%s" % snapshot_name

    def _encode_name(self, name):
        """Get converted MSA volume name.

        Converts the openstack volume id from
        ecffc30f-98cb-4cf5-85ee-d7309cc17cd2
        to
        7P_DD5jLTPWF7tcwnMF80g

        We convert the 128 bits of the uuid into a 24character long
        base64 encoded string. This still exceeds the limit of 20 characters
        so we truncate the name later.
        """
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        vol_encoded = base64.b64encode(vol_uuid.bytes)
        vol_encoded = vol_encoded.replace('=', '')

        # + is not a valid character for MSA
        vol_encoded = vol_encoded.replace('+', '.')
        # since we use http URLs to send paramters, '/' is not an acceptable
        # parameter
        vol_encoded = vol_encoded.replace('/', '_')

        # NOTE(gpocentek): we limit the size to 20 characters since the array
        # doesn't support more than that for now. Duplicates should happen very
        # rarely.
        # We return 19 chars here because the _get_{vol,snap}_name functions
        # prepend a character
        return vol_encoded[:19]

    def check_flags(self, options, required_flags):
        for flag in required_flags:
            if not getattr(options, flag, None):
                msg = _('%s configuration option is not set') % flag
                LOG.error(msg)
                raise exception.InvalidInput(reason=msg)

    def create_volume(self, volume):
        volume_id = self._get_vol_name(volume['id'])
        LOG.debug("Create Volume (%(display_name)s: %(name)s %(id)s)" %
                  {'display_name': volume['display_name'],
                   'name': volume['name'], 'id': volume_id})

        # use base64 to encode the volume name (UUID is too long for MSA)
        volume_name = self._get_vol_name(volume['id'])
        volume_size = "%dGB" % volume['size']
        try:
            metadata = self.client.create_volume(self.config.msa_vdisk,
                                                 volume_name,
                                                 volume_size)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

        return metadata

    def _assert_enough_space_for_copy(self, volume_size):
        """The MSA creates a snap pool before trying to copy the volume.
        The pool is 5.27GB or 20% of the volume size, whichever is larger.

        Verify that we have enough space for the pool and then copy
        """
        pool_size = max(volume_size * 0.2, 5.27)
        required_size = pool_size + volume_size
        if required_size > self.stats['free_capacity_gb']:
            raise exception.HPMSANotEnoughSpace(vdisk=self.vdisk)

    def _assert_source_detached(self, volume):
        """The MSA requires a volume to be dettached to clone it.

        Make sure that the volume is not in use when trying to copy it.
        """
        if volume['status'] != "available" or \
           volume['attach_status'] == "attached":
            msg = _("Volume must be detached to perform a clone operation.")
            LOG.error(msg)
            raise exception.VolumeAttached(volume_id=volume['id'])

    def create_cloned_volume(self, volume, src_vref):
        self.get_volume_stats(True)
        self._assert_enough_space_for_copy(volume['size'])
        self._assert_source_detached(src_vref)

        LOG.debug("Cloning Volume %(source_id)s (%(dest_id)s)" %
                  {'source_id': volume['source_volid'],
                   'dest_id': volume['id']})

        orig_name = self._get_vol_name(volume['source_volid'])
        dest_name = self._get_vol_name(volume['id'])
        try:
            self.client.copy_volume(orig_name, dest_name,
                                    self.config.msa_vdisk)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

        return None

    def create_volume_from_snapshot(self, volume, snapshot):
        self.get_volume_stats(True)
        self._assert_enough_space_for_copy(volume['size'])

        LOG.debug("Creating Volume from snapshot %(source_id)s "
                  "(%(dest_id)s)" %
                  {'source_id': snapshot['id'], 'dest_id': volume['id']})

        orig_name = self._get_snap_name(snapshot['id'])
        dest_name = self._get_vol_name(volume['id'])
        try:
            self.client.copy_volume(orig_name, dest_name,
                                    self.config.msa_vdisk)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

        return None

    def delete_volume(self, volume):
        LOG.debug("Deleting Volume (%s)" % volume['id'])
        volume_name = self._get_vol_name(volume['id'])
        try:
            self.client.delete_volume(volume_name)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            # if the volume wasn't found, ignore the error
            if 'The volume was not found on this system.' in ex:
                return
            raise exception.Invalid(ex)

    def get_volume_stats(self, refresh):
        if refresh:
            self._update_volume_stats()

        return self.stats

    def _update_volume_stats(self):
        # storage_protocol and volume_backend_name are
        # set in the child classes
        stats = {'driver_version': self.VERSION,
                 'free_capacity_gb': 'unknown',
                 'reserved_percentage': 0,
                 'storage_protocol': None,
                 'total_capacity_gb': 'unknown',
                 'QoS_support': False,
                 'vendor_name': 'Hewlett-Packard',
                 'volume_backend_name': None}

        try:
            vdisk_stats = self.client.vdisk_stats(self.config.msa_vdisk)
            stats.update(vdisk_stats)
        except msa.HPMSARequestError:
            err = (_("Unable to get stats for VDisk (%s)")
                   % self.config.msa_vdisk)
            LOG.error(err)
            raise exception.Invalid(reason=err)

        self.stats = stats

    def _assert_connector_ok(self, connector):
        if not connector['wwpns']:
            msg = _("Connector doesn't provide wwpns")
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    def map_volume(self, volume, connector):
        self._assert_connector_ok(connector)
        volume_name = self._get_vol_name(volume['id'])
        try:
            data = self.client.map_volume(volume_name, connector['wwpns'])
            return data
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

    def unmap_volume(self, volume, connector):
        self._assert_connector_ok(connector)
        volume_name = self._get_vol_name(volume['id'])
        try:
            self.client.unmap_volume(volume_name, connector['wwpns'])
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

    def get_active_fc_target_ports(self):
        return self.client.get_active_fc_target_ports()

    def create_snapshot(self, snapshot):
        LOG.debug("Creating Snapshot from %(volume_id)s (%(snap_id)s)" %
                  {'volume_id': snapshot['volume_id'],
                   'snap_id': snapshot['id']})
        snap_name = self._get_snap_name(snapshot['id'])
        vol_name = self._get_vol_name(snapshot['volume_id'])
        try:
            self.client.create_snapshot(vol_name, snap_name)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)

    def delete_snapshot(self, snapshot):
        snap_name = self._get_snap_name(snapshot['id'])
        LOG.debug("Deleting Snapshot (%s)" % snapshot['id'])

        try:
            self.client.delete_snapshot(snap_name)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            # if the volume wasn't found, ignore the error
            if 'The volume was not found on this system.' in ex:
                return
            raise exception.Invalid(ex)

    def extend_volume(self, volume, new_size):
        volume_name = self._get_vol_name(volume['id'])
        old_size = volume['size']
        growth_size = int(new_size) - old_size
        LOG.debug("Extending Volume %(volume_name)s from %(old_size)s to "
                  "%(new_size)s, by %(growth_size)s GB." %
                  {'volume_name': volume_name, 'old_size': old_size,
                   'new_size': new_size, 'growth_size': growth_size})
        try:
            self.client.extend_volume(volume_name, "%dGB" % growth_size)
        except msa.HPMSARequestError as ex:
            LOG.error(ex)
            raise exception.Invalid(ex)
