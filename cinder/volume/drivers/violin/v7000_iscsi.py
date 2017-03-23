# Copyright 2016 Violin Memory, Inc.
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
Violin 7000 Series All-Flash Array iSCSI Volume Driver

Provides ISCSI specific LUN services for V7000 series flash arrays.

This driver requires Concerto v7.5.4 or newer software on the array.

You will need to install the python VMEM REST client:
sudo pip install vmemclient

Set the following in the cinder.conf file to enable the VMEM V7000
ISCSI Driver along with the required flags:

volume_driver=cinder.volume.drivers.violin.v7000_iscsi.V7000ISCSIDriver
"""

import random
import uuid

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.violin import v7000_common

LOG = logging.getLogger(__name__)


@interface.volumedriver
class V7000ISCSIDriver(driver.ISCSIDriver):
    """Executes commands relating to iscsi based Violin Memory arrays.

    Version history:
        1.0 - Initial driver
    """

    VERSION = '1.0'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "Violin_Memory_CI"

    # TODO(smcginnis) Either remove this if CI requirements are met, or
    # remove this driver in the Queens release per normal deprecation
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(V7000ISCSIDriver, self).__init__(*args, **kwargs)
        self.stats = {}
        self.gateway_iscsi_ip_addresses = []
        self.configuration.append_config_values(v7000_common.violin_opts)
        self.configuration.append_config_values(san.san_opts)
        self.common = v7000_common.V7000Common(self.configuration)

        LOG.info("Initialized driver %(name)s version: %(vers)s",
                 {'name': self.__class__.__name__, 'vers': self.VERSION})

    def do_setup(self, context):
        """Any initialization the driver does while starting."""
        super(V7000ISCSIDriver, self).do_setup(context)

        self.common.do_setup(context)

        # Register the client with the storage array
        iscsi_version = self.VERSION + "-ISCSI"
        self.common.vmem_mg.utility.set_managed_by_openstack_version(
            iscsi_version, protocol="iSCSI")

        # Getting iscsi IPs from the array is incredibly expensive,
        # so only do it once.
        if not self.configuration.violin_iscsi_target_ips:
            LOG.warning("iSCSI target ip addresses not configured.")
            self.gateway_iscsi_ip_addresses = (
                self.common.vmem_mg.utility.get_iscsi_interfaces())
        else:
            self.gateway_iscsi_ip_addresses = (
                self.configuration.violin_iscsi_target_ips)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self.common.check_for_setup_error()
        if len(self.gateway_iscsi_ip_addresses) == 0:
            msg = _('No iSCSI IPs configured on SAN gateway')
            raise exception.ViolinInvalidBackendConfig(reason=msg)

    def create_volume(self, volume):
        """Creates a volume."""
        self.common._create_lun(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.common._create_volume_from_snapshot(snapshot, volume)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self.common._create_lun_from_lun(src_vref, volume)

    def delete_volume(self, volume):
        """Deletes a volume."""
        self.common._delete_lun(volume)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        self.common._extend_lun(volume, new_size)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common._create_lun_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.common._delete_lun_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Synchronously checks and re-exports volumes at cinder start time."""
        pass

    def create_export(self, context, volume, connector):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        resp = {}

        LOG.debug("Initialize_connection: initiator - %(initiator)s  host - "
                  "%(host)s ip - %(ip)s",
                  {'initiator': connector['initiator'],
                   'host': connector['host'],
                   'ip': connector['ip']})

        iqn = self._get_iqn(connector)

        # pick a random single target to give the connector since
        # there is no multipathing support
        tgt = self.gateway_iscsi_ip_addresses[random.randint(
            0, len(self.gateway_iscsi_ip_addresses) - 1)]

        resp = self.common.vmem_mg.client.create_client(
            name=connector['host'], proto='iSCSI',
            iscsi_iqns=connector['initiator'])

        # raise if we failed for any reason other than a 'client
        # already exists' error code
        if not resp['success'] and 'Error: 0x900100cd' not in resp['msg']:
            msg = _("Failed to create iscsi client")
            raise exception.ViolinBackendErr(message=msg)

        resp = self.common.vmem_mg.client.create_iscsi_target(
            name=iqn, client_name=connector['host'],
            ip=self.gateway_iscsi_ip_addresses, access_mode='ReadWrite')

        # same here, raise for any failure other than a 'target
        # already exists' error code
        if not resp['success'] and 'Error: 0x09024309' not in resp['msg']:
            msg = _("Failed to create iscsi target")
            raise exception.ViolinBackendErr(message=msg)

        lun_id = self._export_lun(volume, iqn, connector)

        properties = {}
        properties['target_discovered'] = False
        properties['target_iqn'] = iqn
        properties['target_portal'] = '%s:%s' % (tgt, '3260')
        properties['target_lun'] = lun_id
        properties['volume_id'] = volume['id']

        LOG.debug("Return ISCSI data: %(properties)s.",
                  {'properties': properties})

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminates the connection (target<-->initiator)."""
        iqn = self._get_iqn(connector)
        self._unexport_lun(volume, iqn, connector)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, update the stats first.
        """
        if refresh or not self.stats:
            self._update_volume_stats()
        return self.stats

    def _update_volume_stats(self):
        """Gathers array stats and converts them to GB values."""
        data = self.common._get_volume_stats(self.configuration.san_ip)

        backend_name = self.configuration.volume_backend_name
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = 'iSCSI'
        for i in data:
            LOG.debug("stat update: %(name)s=%(data)s",
                      {'name': i, 'data': data[i]})

        self.stats = data

    def _export_lun(self, volume, target, connector):
        """Generates the export configuration for the given volume.

        :param volume:  volume object provided by the Manager
        :param connector:  connector object provided by the Manager
        :returns: the LUN ID assigned by the backend
        """
        lun_id = ''
        v = self.common.vmem_mg

        LOG.debug("Exporting lun %(vol_id)s - initiator iqns %(i_iqns)s "
                  "- target iqns %(t_iqns)s.",
                  {'vol_id': volume['id'], 'i_iqns': connector['initiator'],
                   't_iqns': self.gateway_iscsi_ip_addresses})

        try:
            lun_id = self.common._send_cmd_and_verify(
                v.lun.assign_lun_to_iscsi_target,
                self._is_lun_id_ready,
                "Assign device successfully",
                [volume['id'], target],
                [volume['id'], connector['host']])

        except exception.ViolinBackendErr:
            LOG.exception("Backend returned error for lun export.")
            raise

        except Exception:
            raise exception.ViolinInvalidBackendConfig(
                reason=_('LUN export failed!'))

        lun_id = self._get_lun_id(volume['id'], connector['host'])
        LOG.info("Exported lun %(vol_id)s on lun_id %(lun_id)s.",
                 {'vol_id': volume['id'], 'lun_id': lun_id})

        return lun_id

    def _unexport_lun(self, volume, target, connector):
        """Removes the export configuration for the given volume.

        The equivalent CLI command is "no lun export container
        <container_name> name <lun_name>"

        Arguments:
            volume -- volume object provided by the Manager
        """
        v = self.common.vmem_mg

        LOG.info("Unexporting lun %(vol)s host is %(host)s.",
                 {'vol': volume['id'], 'host': connector['host']})

        try:
            self.common._send_cmd(v.lun.unassign_lun_from_iscsi_target,
                                  "Unassign device successfully",
                                  volume['id'], target, True)

        except exception.ViolinBackendErrNotFound:
            LOG.info("Lun %s already unexported, continuing...",
                     volume['id'])

        except Exception:
            LOG.exception("LUN unexport failed!")
            msg = _("LUN unexport failed")
            raise exception.ViolinBackendErr(message=msg)

    def _is_lun_id_ready(self, volume_name, client_name):
        """Get the lun ID for an exported volume.

        If the lun is successfully assigned (exported) to a client, the
        client info has the lun_id.

        Note: The structure returned for iscsi is different from the
        one returned for FC. Therefore this function is here instead of
        common.

        Arguments:
            volume_name -- name of volume to query for lun ID
            client_name -- name of client associated with the volume

        Returns:
            lun_id -- Returns True or False
        """

        lun_id = -1
        lun_id = self._get_lun_id(volume_name, client_name)

        if lun_id is None:
            return False
        else:
            return True

    def _get_lun_id(self, volume_name, client_name):
        """Get the lun ID for an exported volume.

        If the lun is successfully assigned (exported) to a client, the
        client info has the lun_id.

        Note: The structure returned for iscsi is different from the
        one returned for FC. Therefore this function is here instead of
        common.

        Arguments:
            volume_name -- name of volume to query for lun ID
            client_name -- name of client associated with the volume

        Returns:
            lun_id -- integer value of lun ID
        """
        v = self.common.vmem_mg
        lun_id = None

        client_info = v.client.get_client_info(client_name)

        for x in client_info['ISCSIDevices']:
            if volume_name == x['name']:
                lun_id = x['lun']
                break

        if lun_id:
            lun_id = int(lun_id)

        return lun_id

    def _get_iqn(self, connector):
        # The vmemclient connection properties list hostname field may
        # change depending on failover cluster config.  Use a UUID
        # from the backend's IP address to avoid a potential naming
        # issue.
        host_uuid = uuid.uuid3(uuid.NAMESPACE_DNS, self.configuration.san_ip)
        return "%s%s.%s" % (self.configuration.iscsi_target_prefix,
                            connector['host'], host_uuid)
