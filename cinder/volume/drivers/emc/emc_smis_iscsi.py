# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 EMC Corporation.
# Copyright (c) 2012 OpenStack LLC.
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
ISCSI Drivers for EMC VNX and VMAX/VMAXe arrays based on SMI-S.

"""

import os
import time

from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_smis_common

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


def get_iscsi_initiator():
    """Get iscsi initiator name for this machine."""
    # NOTE openiscsi stores initiator name in a file that
    #      needs root permission to read.
    contents = utils.read_file_as_root('/etc/iscsi/initiatorname.iscsi')
    for l in contents.split('\n'):
        if l.startswith('InitiatorName='):
            return l[l.index('=') + 1:].strip()


class EMCSMISISCSIDriver(driver.ISCSIDriver):
    """EMC ISCSI Drivers for VMAX/VMAXe and VNX using SMI-S."""

    def __init__(self, *args, **kwargs):

        super(EMCSMISISCSIDriver, self).__init__(*args, **kwargs)
        self.common = emc_smis_common.EMCSMISCommon()

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VMAXe/VNX) volume."""
        self.common.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        self.common.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self.common.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common.delete_snapshot(snapshot)

    def _iscsi_location(ip, target, iqn, lun=None):
        return "%s:%s,%s %s %s" % (ip, FLAGS.iscsi_port, target, iqn, lun)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        return self.common.ensure_export(context, volume)

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        return self.common.create_export(context, volume)

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        the iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                }
            }

        """
        self.common.initialize_connection(volume, connector)

        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def _do_iscsi_discovery(self, volume):

        LOG.warn(_("ISCSI provider_location not stored, using discovery"))

        (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p',
                                    FLAGS.iscsi_ip_address,
                                    run_as_root=True)
        for target in out.splitlines():
            return target
        return None

    def _get_iscsi_properties(self, volume):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the id of the volume (currently used by xen)

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        """
        properties = {}

        location = self._do_iscsi_discovery(volume)
        if not location:
            raise exception.InvalidVolume(_("Could not find iSCSI export "
                                          " for volume %s") %
                                          (volume['name']))

        LOG.debug(_("ISCSI Discovery: Found %s") % (location))
        properties['target_discovered'] = True

        results = location.split(" ")
        properties['target_portal'] = results[0].split(",")[0]
        properties['target_iqn'] = results[1]

        device_number = self.common.find_device_number(volume)
        if device_number is None:
            exception_message = (_("Cannot find device number for volume %s")
                                 % volume['name'])
            raise exception.VolumeBackendAPIException(data=exception_message)

        properties['target_lun'] = device_number

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        LOG.debug(_("ISCSI properties: %s") % (properties))

        return properties

    def _run_iscsiadm(self, iscsi_properties, iscsi_command, **kwargs):
        check_exit_code = kwargs.pop('check_exit_code', 0)
        (out, err) = self._execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True,
                                   check_exit_code=check_exit_code)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        self.common.terminate_connection(volume, connector)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        LOG.debug(_('copy_image_to_volume %s.') % volume['name'])
        initiator = get_iscsi_initiator()
        connector = {}
        connector['initiator'] = initiator

        iscsi_properties, volume_path = self._attach_volume(
            context, volume, connector)

        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path, "wb") as image_file:
                image_service.download(context, image_id, image_file)

        self.terminate_connection(volume, connector)

    def _attach_volume(self, context, volume, connector):
        """Attach the volume."""
        iscsi_properties = None
        host_device = None
        init_conn = self.initialize_connection(volume, connector)
        iscsi_properties = init_conn['data']

        self._run_iscsiadm(iscsi_properties, ("--login",),
                           check_exit_code=[0, 255])

        self._iscsiadm_update(iscsi_properties, "node.startup", "automatic")

        host_device = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-%s" %
                       (iscsi_properties['target_portal'],
                        iscsi_properties['target_iqn'],
                        iscsi_properties.get('target_lun', 0)))

        tries = 0
        while not os.path.exists(host_device):
            if tries >= FLAGS.num_iscsi_scan_tries:
                raise exception.CinderException(
                    _("iSCSI device not found at %s") % (host_device))

            LOG.warn(_("ISCSI volume not yet found at: %(host_device)s. "
                     "Will rescan & retry.  Try number: %(tries)s") %
                     locals())

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, ("--rescan",))

            tries = tries + 1
            if not os.path.exists(host_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(host_device)s "
                      "(after %(tries)s rescans)") %
                      locals())

        return iscsi_properties, host_device

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        LOG.debug(_('copy_volume_to_image %s.') % volume['name'])
        initiator = get_iscsi_initiator()
        connector = {}
        connector['initiator'] = initiator

        iscsi_properties, volume_path = self._attach_volume(
            context, volume, connector)

        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path) as volume_file:
                image_service.update(context, image_id, {}, volume_file)

        self.terminate_connection(volume, connector)

    def get_volume_stats(self, refresh=False):
        """Get volume status.
        If 'refresh' is True, run update the stats first."""
        if refresh:
            self.update_volume_status()

        return self._stats

    def update_volume_status(self):
        """Retrieve status info from volume group."""
        LOG.debug(_("Updating volume status"))
        data = self.common.update_volume_status()
        data['volume_backend_name'] = 'EMCSMISISCSIDriver'
        data['storage_protocol'] = 'iSCSI'
        self._stats = data
