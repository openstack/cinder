# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Nexenta Systems, Inc.
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
"""
:mod:`nexenta.nfsvolume` -- Driver to store NFS volumes on Nexenta Appliance
=====================================================================

.. automodule:: nexenta.nfsvolume
.. moduleauthor:: Blake Lai <blackxwhite@gmail.com>
"""

from oslo.config import cfg

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers import nexenta
from cinder.volume.drivers.nexenta import jsonrpc

VERSION = '1.0'
LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

nexenta_opts = [
    cfg.StrOpt('nexenta_host',
               default='',
               help='IP address of Nexenta SA'),
    cfg.IntOpt('nexenta_rest_port',
               default=2000,
               help='HTTP port to connect to Nexenta REST API server'),
    cfg.StrOpt('nexenta_rest_protocol',
               default='auto',
               help='Use http or https for REST connection (default auto)'),
    cfg.StrOpt('nexenta_user',
               default='admin',
               help='User name to connect to Nexenta SA'),
    cfg.StrOpt('nexenta_password',
               default='nexenta',
               help='Password to connect to Nexenta SA',
               secret=True),
    cfg.StrOpt('nexenta_volume',
               default='cinder',
               help='pool on SA that will hold all volumes'),
    cfg.StrOpt('nexenta_reserve',
               default=False,
               help='flag to create volumes with size reserved'),
    cfg.StrOpt('nexenta_compress',
               default=True,
               help='flag to create volumes with compression feature'),
    cfg.BoolOpt('nexenta_dedup',
                default=False,
                help='flag to create volumes with deduplication feature'),
]
FLAGS.register_opts(nexenta_opts)


class NexentaNFSDriver(driver.VolumeDriver):  # pylint: disable=R0921
    """Executes volume driver commands on Nexenta Appliance."""

    def __init__(self, *args, **kwargs):
        super(NexentaNFSDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(nexenta_opts)

    def do_setup(self, context):
        protocol = self.configuration.nexenta_rest_protocol
        auto = protocol == 'auto'
        if auto:
            protocol = 'http'
        self.nms = jsonrpc.NexentaJSONProxy(
            '%s://%s:%s/rest/nms/' % (protocol, self.configuration.nexenta_host,
                                      self.configuration.nexenta_rest_port),
            self.configuration.nexenta_user, self.configuration.nexenta_password, auto=auto)

    def check_for_setup_error(self):
        """Verify that the volume for our zvols exists.

        :raise: :py:exc:`LookupError`
        """
        if not self.nms.volume.object_exists(self.configuration.nexenta_volume):
            raise LookupError(_("Volume %s does not exist in Nexenta SA"),
                              self.configuration.nexenta_volume)

    def _get_folder_name(self, volume_name):
        """Return folder name that corresponds given volume name."""
        return '%s/%s' % (self.configuration.nexenta_volume, volume_name)

    def create_volume(self, volume):
        """Create a folder on appliance.

        :param volume: volume reference
        """
        quota = '%sG' % (volume['size'])
        reservation = ('%sG' % (volume['size']) if self.configuration.nexenta_reserve else 'none')
        compression = ('on' if self.configuration.nexenta_compress else 'off')
        dedup = ('on' if self.configuration.nexenta_dedup else 'off')
        
        try:
            self.nms.folder.create_with_props(
                self.configuration.nexenta_volume,
                volume['name'],
                { "quota": quota, "reservation": reservation, "compression": compression, "dedup": dedup })
        except nexenta.NexentaException as exc:
            if "out of space" in exc.args[1]:
                raise exception.VolumeSizeExceedsAvailableQuota()
            else:
                raise

    def delete_volume(self, volume):
        """Destroy a folder on appliance.

        :param volume: volume reference
        """
        try:
            self.nms.folder.destroy(self._get_folder_name(volume['name']), '')
        except nexenta.NexentaException as exc:
            if "folder has children" in exc.args[1]:
                raise exception.VolumeIsBusy(volume_name=volume['name'])
            elif "does not exist" in exc.args[1]:
                LOG.warn(_('Got error trying to delete volume'
                       ' %(folder_name)s, assuming it is '
                       'already deleted: %(exc)s'),
                      {'folder_name': self._get_folder_name(volume['name']), 'exc': exc})
            else:
                raise

    def create_snapshot(self, snapshot):
        """Create snapshot of existing folder on appliance.

        :param snapshot: shapshot reference
        """
        self.nms.folder.create_snapshot(
            self._get_folder_name(snapshot['volume_name']),
            snapshot['name'], '-r')

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create new volume from other's snapshot on appliance.

        :param volume: reference of volume to be created
        :param snapshot: reference of source snapshot
        """
        quota = '%sG' % (volume['size'])
        reservation = ('%sG' % (volume['size']) if self.configuration.nexenta_reserve else 'none')
        compression = ('on' if self.configuration.nexenta_compress else 'off')
        dedup = ('on' if self.configuration.nexenta_dedup else 'off')

        self.nms.folder.clone(
            '%s@%s' % (self._get_folder_name(snapshot['volume_name']),
                       snapshot['name']),
            self._get_folder_name(volume['name']))

        try:
            self.nms.folder.set_child_prop(self._get_folder_name(volume['name']), 'quota', quota)
            self.nms.folder.set_child_prop(self._get_folder_name(volume['name']), 'reservation', reservation)
            self.nms.folder.set_child_prop(self._get_folder_name(volume['name']), 'compression', compression)
            self.nms.folder.set_child_prop(self._get_folder_name(volume['name']), 'dedup', dedup)
        except nexenta.NexentaException as exc:
            if "size is greater than available space" in exc.args[1]:
                self.delete_volume(volume)
                raise exception.VolumeSizeExceedsAvailableQuota()
            else:
                raise

    def delete_snapshot(self, snapshot):
        """Delete volume's snapshot on appliance.

        :param snapshot: shapshot reference
        """
        try:
            self.nms.snapshot.destroy(
                '%s@%s' % (self._get_folder_name(snapshot['volume_name']),
                           snapshot['name']),
                '')
        except nexenta.NexentaException as exc:
            if "snapshot has dependent clones" in exc.args[1]:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
            else:
                raise

    def local_path(self, volume):
        """Return local path to existing local volume.

        We never have local volumes, so it raises NotImplementedError.

        :raise: :py:exc:`NotImplementedError`
        """
        raise NotImplementedError

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get folder exported as NFS volume.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        :return: nfs-formatted provider location string
        """
        folder_name = self._get_folder_name(volume['name'])

        try:
            self.nms.netstorsvc.share_folder(
                'svc:/network/nfs/server:default',
                folder_name,
                { "read_write": "*", "extra_options": "anon=0" })
        except nexenta.NexentaException as exc:
            if not ensure:
                raise
            else:
                LOG.info(_('Ignored NFS share folder creation error "%s"'
                           ' while ensuring export'), exc)

        return '%s:/volumes/%s' % (self.configuration.nexenta_host,
                            folder_name)

    def create_export(self, _ctx, volume):
        """Create new export for folder.

        :param volume: reference of volume to be exported
        :return: nfs-formatted provider location string
        """
        loc = self._do_export(_ctx, volume, ensure=False)
        return {'provider_location': loc}

    def ensure_export(self, _ctx, volume):
        """Recreate parts of export if necessary.

        :param volume: reference of volume to be exported
        """
        self._do_export(_ctx, volume, ensure=True)

    def remove_export(self, _ctx, volume):
        """Destroy all resources created to export folder.

        :param volume: reference of volume to be unexported
        """
        folder_name = self._get_folder_name(volume['name'])

        try:
            self.nms.netstorsvc.unshare_folder(
                'svc:/network/nfs/server:default',
                folder_name,
                '0')
        except nexenta.NexentaException as exc:
            LOG.warn(_('Got error trying to unshare folder'
                       ' %(folder_name)s, assuming it is '
                       'already gone: %(exc)s'),
                     {'folder_name': folder_name, 'exc': exc})

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        data = {'export': volume['provider_location'],
                'name': volume['name']}
        return {
            'driver_volume_type': 'nfs',
            'data': data
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        raise NotImplementedError()

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        raise NotImplementedError()

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first."""
        if refresh:
            self._update_volume_status()

        return self._stats

    def _update_volume_status(self):
        """Retrieve status info for Nexenta device."""

        # NOTE(jdg): Aimon Bustardo was kind enough to point out the
        # info he had regarding Nexenta Capabilities, ideally it would
        # be great if somebody from Nexenta looked this over at some point

        KB = 1024
        MB = KB ** 2

        LOG.debug(_("Updating volume status"))
        data = {}
        backend_name = self.__class__.__name__
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Nexenta'
        data["driver_version"] = VERSION
        data["storage_protocol"] = 'NFS'

        stats = self.nms.volume.get_child_props(self.configuration.nexenta_volume,
                                                'health|size|used|available')
        total_unit = stats['size'][-1]
        total_amount = float(stats['size'][:-1])
        free_unit = stats['available'][-1]
        free_amount = float(stats['available'][:-1])

        if total_unit == "T":
                total_amount = total_amount * KB
        elif total_unit == "M":
                total_amount = total_amount / KB
        elif total_unit == "B":
                total_amount = total_amount / MB

        if free_unit == "T":
                free_amount = free_amount * KB
        elif free_unit == "M":
                free_amount = free_amount / KB
        elif free_unit == "B":
                free_amount = free_amount / MB

        data['total_capacity_gb'] = total_amount
        data['free_capacity_gb'] = free_amount

        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data
