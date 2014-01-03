#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
#
#    Copyright 2012 OpenStack Foundation
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
Volume driver for HP 3PAR Storage array.
This driver requires 3.1.2 MU2 firmware on the 3PAR array, using
the 2.x version of the hp3parclient.

You will need to install the python hp3parclient.
sudo pip install --upgrade "hp3parclient>=2.0"

Set the following in the cinder.conf file to enable the
3PAR Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_3par_fc.HP3PARFCDriver
"""

from hp3parclient import exceptions as hpexceptions

from cinder.openstack.common import log as logging
from cinder import utils
import cinder.volume.driver
from cinder.volume.drivers.san.hp import hp_3par_common as hpcommon
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)


class HP3PARFCDriver(cinder.volume.driver.FibreChannelDriver):
    """OpenStack Fibre Channel driver to enable 3PAR storage array.

    Version history:
        1.0   - Initial driver
        1.1   - QoS, extend volume, multiple iscsi ports, remove domain,
                session changes, faster clone, requires 3.1.2 MU2 firmware,
                copy volume <--> Image.
        1.2.0 - Updated the use of the hp3parclient to 2.0.0 and refactored
                the drivers to use the new APIs.
        1.2.1 - Synchronized extend_volume method.
        1.2.2 - Added try/finally around client login/logout.
        1.2.3 - Added ability to add WWNs to host.
        1.2.4 - Added metadata during attach/detach bug #1258033.

    """

    VERSION = "1.2.4"

    def __init__(self, *args, **kwargs):
        super(HP3PARFCDriver, self).__init__(*args, **kwargs)
        self.common = None
        self.configuration.append_config_values(hpcommon.hp3par_opts)
        self.configuration.append_config_values(san.san_opts)

    def _init_common(self):
        return hpcommon.HP3PARCommon(self.configuration)

    def _check_flags(self):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hp3par_api_url', 'hp3par_username',
                          'hp3par_password',
                          'san_ip', 'san_login', 'san_password']
        self.common.check_flags(self.configuration, required_flags)

    @utils.synchronized('3par', external=True)
    def get_volume_stats(self, refresh):
        self.common.client_login()
        try:
            stats = self.common.get_volume_stats(refresh)
            stats['storage_protocol'] = 'FC'
            stats['driver_version'] = self.VERSION
            backend_name = self.configuration.safe_get('volume_backend_name')
            stats['volume_backend_name'] = (backend_name or
                                            self.__class__.__name__)
            return stats
        finally:
            self.common.client_logout()

    def do_setup(self, context):
        self.common = self._init_common()
        self._check_flags()
        self.common.do_setup(context)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_flags()

    @utils.synchronized('3par', external=True)
    def create_volume(self, volume):
        self.common.client_login()
        try:
            metadata = self.common.create_volume(volume)
            return {'metadata': metadata}
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def create_cloned_volume(self, volume, src_vref):
        self.common.client_login()
        try:
            new_vol = self.common.create_cloned_volume(volume, src_vref)
            return {'metadata': new_vol}
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def delete_volume(self, volume):
        self.common.client_login()
        try:
            self.common.delete_volume(volume)
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        TODO: support using the size from the user.
        """
        self.common.client_login()
        try:
            metadata = self.common.create_volume_from_snapshot(volume,
                                                               snapshot)
            return {'metadata': metadata}
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def create_snapshot(self, snapshot):
        self.common.client_login()
        try:
            self.common.create_snapshot(snapshot)
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def delete_snapshot(self, snapshot):
        self.common.client_login()
        try:
            self.common.delete_snapshot(snapshot)
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        The  driver returns a driver_volume_type of 'fibre_channel'.
        The target_wwn can be a single entry or a list of wwns that
        correspond to the list of remote wwn(s) that will export the volume.
        Example return values:

            {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                }
            }


        Steps to export a volume on 3PAR
          * Create a host on the 3par with the target wwn
          * Create a VLUN for that HOST with the volume we want to export.

        """
        self.common.client_login()
        try:
            # we have to make sure we have a host
            host = self._create_host(volume, connector)

            # now that we have a host, create the VLUN
            vlun = self.common.create_vlun(volume, host)

            fc_ports = self.common.get_active_fc_target_ports()
            wwns = []

            for port in fc_ports:
                wwns.append(port['portWWN'])

            info = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_lun': vlun['lun'],
                             'target_discovered': True,
                             'target_wwn': wwns}}
            return info
        finally:
            self.common.client_logout()

    @utils.synchronized('3par', external=True)
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        self.common.client_login()
        try:
            hostname = self.common._safe_hostname(connector['host'])
            self.common.terminate_connection(volume, hostname,
                                             wwn=connector['wwpns'])
        finally:
            self.common.client_logout()

    def _create_3par_fibrechan_host(self, hostname, wwns, domain, persona_id):
        """Create a 3PAR host.

        Create a 3PAR host, if there is already a host on the 3par using
        the same wwn but with a different hostname, return the hostname
        used by 3PAR.
        """
        if domain is not None:
            command = ['createhost', '-persona', persona_id, '-domain', domain,
                       hostname]
        else:
            command = ['createhost', '-persona', persona_id, hostname]
        for wwn in wwns:
            command.append(wwn)

        out = self.common._cli_run(command)
        if out and len(out) > 1:
            return self.common.parse_create_host_error(hostname, out)

        return hostname

    def _modify_3par_fibrechan_host(self, hostname, wwn):
        mod_request = {'pathOperation': self.common.client.HOST_EDIT_ADD,
                       'FCWWNs': wwn}

        self.common.client.modifyHost(hostname, mod_request)

    def _create_host(self, volume, connector):
        """Creates or modifies existing 3PAR host."""
        host = None
        hostname = self.common._safe_hostname(connector['host'])
        cpg = self.common.get_cpg(volume, allowSnap=True)
        domain = self.common.get_domain(cpg)
        try:
            host = self.common._get_3par_host(hostname)
        except hpexceptions.HTTPNotFound as ex:
            # get persona from the volume type extra specs
            persona_id = self.common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            hostname = self._create_3par_fibrechan_host(hostname,
                                                        connector['wwpns'],
                                                        domain,
                                                        persona_id)
            host = self.common._get_3par_host(hostname)

        return self._add_new_wwn_to_host(host, connector['wwpns'])

    def _add_new_wwn_to_host(self, host, wwns):
        """Add wwns to a host if one or more don't exist.

        Identify if argument wwns contains any world wide names
        not configured in the 3PAR host path. If any are found,
        add them to the 3PAR host.
        """
        # get the currently configured wwns
        # from the host's FC paths
        host_wwns = []
        if 'FCPaths' in host:
            for path in host['FCPaths']:
                wwn = path.get('wwn', None)
                if wwn is not None:
                    host_wwns.append(wwn.lower())

        # lower case all wwns in the compare list
        compare_wwns = [x.lower() for x in wwns]

        # calculate wwns in compare list, but not in host_wwns list
        new_wwns = list(set(compare_wwns).difference(host_wwns))

        # if any wwns found that were not in host list,
        # add them to the host
        if (len(new_wwns) > 0):
            self._modify_3par_fibrechan_host(host['name'], new_wwns)
            host = self.common._get_3par_host(host['name'])
        return host

    @utils.synchronized('3par', external=True)
    def create_export(self, context, volume):
        pass

    @utils.synchronized('3par', external=True)
    def ensure_export(self, context, volume):
        pass

    @utils.synchronized('3par', external=True)
    def remove_export(self, context, volume):
        pass

    @utils.synchronized('3par', external=True)
    def extend_volume(self, volume, new_size):
        self.common.extend_volume(volume, new_size)

    @utils.synchronized('3par', external=True)
    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        self.common.attach_volume(volume, instance_uuid)

    @utils.synchronized('3par', external=True)
    def detach_volume(self, context, volume):
        self.common.detach_volume(volume)
