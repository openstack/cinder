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
This driver requires 3.1.3 firmware on the 3PAR array, using
the 3.x version of the hp3parclient.

You will need to install the python hp3parclient.
sudo pip install --upgrade "hp3parclient>=3.0"

Set the following in the cinder.conf file to enable the
3PAR Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_3par_fc.HP3PARFCDriver
"""

try:
    from hp3parclient import exceptions as hpexceptions
except ImportError:
    hpexceptions = None

from oslo_log import log as logging

from cinder import exception
from cinder.i18n import _, _LI
import cinder.volume.driver
from cinder.volume.drivers.san.hp import hp_3par_common as hpcommon
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils

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
        1.3.0 - Removed all SSH code.  We rely on the hp3parclient now.
        2.0.0 - Update hp3parclient API uses 3.0.x
        2.0.2 - Add back-end assisted volume migrate
        2.0.3 - Added initiator-target map for FC Zone Manager
        2.0.4 - Added support for managing/unmanaging of volumes
        2.0.5 - Only remove FC Zone on last volume detach
        2.0.6 - Added support for volume retype
        2.0.7 - Only one FC port is used when a single FC path
                is present.  bug #1360001
        2.0.8 - Fixing missing login/logout around attach/detach bug #1367429
        2.0.9 - Add support for pools with model update
        2.0.10 - Migrate without losing type settings bug #1356608
        2.0.11 - Removing locks bug #1381190
        2.0.12 - Fix queryHost call to specify wwns bug #1398206
        2.0.13 - Fix missing host name during attach bug #1398206
        2.0.14 - Removed usage of host name cache #1398914
        2.0.15 - Added support for updated detach_volume attachment.
        2.0.16 - Added encrypted property to initialize_connection #1439917
        2.0.17 - Improved VLUN creation and deletion logic. #1469816

    """

    VERSION = "2.0.17"

    def __init__(self, *args, **kwargs):
        super(HP3PARFCDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(hpcommon.hp3par_opts)
        self.configuration.append_config_values(san.san_opts)
        self.lookup_service = fczm_utils.create_lookup_service()

    def _init_common(self):
        return hpcommon.HP3PARCommon(self.configuration)

    def _login(self):
        common = self._init_common()
        common.do_setup(None)
        common.client_login()
        return common

    def _logout(self, common):
        common.client_logout()

    def _check_flags(self, common):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hp3par_api_url', 'hp3par_username',
                          'hp3par_password',
                          'san_ip', 'san_login', 'san_password']
        common.check_flags(self.configuration, required_flags)

    def get_volume_stats(self, refresh=False):
        common = self._login()
        try:
            stats = common.get_volume_stats(
                refresh,
                self.get_filter_function(),
                self.get_goodness_function())
            stats['storage_protocol'] = 'FC'
            stats['driver_version'] = self.VERSION
            backend_name = self.configuration.safe_get('volume_backend_name')
            stats['volume_backend_name'] = (backend_name or
                                            self.__class__.__name__)
            return stats
        finally:
            self._logout(common)

    def do_setup(self, context):
        common = self._init_common()
        common.do_setup(context)
        self._check_flags(common)
        common.check_for_setup_error()

    def check_for_setup_error(self):
        """Setup errors are already checked for in do_setup so return pass."""
        pass

    def create_volume(self, volume):
        common = self._login()
        try:
            return common.create_volume(volume)
        finally:
            self._logout(common)

    def create_cloned_volume(self, volume, src_vref):
        common = self._login()
        try:
            return common.create_cloned_volume(volume, src_vref)
        finally:
            self._logout(common)

    def delete_volume(self, volume):
        common = self._login()
        try:
            common.delete_volume(volume)
        finally:
            self._logout(common)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        TODO: support using the size from the user.
        """
        common = self._login()
        try:
            return common.create_volume_from_snapshot(volume, snapshot)
        finally:
            self._logout(common)

    def create_snapshot(self, snapshot):
        common = self._login()
        try:
            common.create_snapshot(snapshot)
        finally:
            self._logout(common)

    def delete_snapshot(self, snapshot):
        common = self._login()
        try:
            common.delete_snapshot(snapshot)
        finally:
            self._logout(common)

    @fczm_utils.AddFCZone
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
                    'encrypted': False,
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': '1234567890123',
                }
            }

            or

             {
                'driver_volume_type': 'fibre_channel'
                'data': {
                    'encrypted': False,
                    'target_discovered': True,
                    'target_lun': 1,
                    'target_wwn': ['1234567890123', '0987654321321'],
                }
            }


        Steps to export a volume on 3PAR
          * Create a host on the 3par with the target wwn
          * Create a VLUN for that HOST with the volume we want to export.

        """
        common = self._login()
        try:
            # we have to make sure we have a host
            host = self._create_host(common, volume, connector)

            target_wwns, init_targ_map, numPaths = \
                self._build_initiator_target_map(common, connector)

            # check if a VLUN already exists for this host
            existing_vlun = None
            try:
                vol_name = common._get_3par_vol_name(volume['id'])
                existing_vlun = common.client.getVLUN(vol_name)
            except hpexceptions.HTTPNotFound:
                # ignore, vlun will be created later
                pass

            vlun = None
            if not existing_vlun or host['name'] != existing_vlun['hostname']:
                # now that we have a host, create the VLUN
                if self.lookup_service is not None and numPaths == 1:
                    nsp = None
                    active_fc_port_list = common.get_active_fc_target_ports()
                    for port in active_fc_port_list:
                        if port['portWWN'].lower() == target_wwns[0].lower():
                            nsp = port['nsp']
                            break
                    vlun = common.create_vlun(volume, host, nsp)
                else:
                    vlun = common.create_vlun(volume, host)
            else:
                vlun = existing_vlun

            info = {'driver_volume_type': 'fibre_channel',
                    'data': {'target_lun': vlun['lun'],
                             'target_discovered': True,
                             'target_wwn': target_wwns,
                             'initiator_target_map': init_targ_map}}

            encryption_key_id = volume.get('encryption_key_id', None)
            info['data']['encrypted'] = encryption_key_id is not None

            return info
        finally:
            self._logout(common)

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        common = self._login()
        try:
            hostname = common._safe_hostname(connector['host'])
            common.terminate_connection(volume, hostname,
                                        wwn=connector['wwpns'])

            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}

            try:
                common.client.getHostVLUNs(hostname)
            except hpexceptions.HTTPNotFound:
                # No more exports for this host.
                LOG.info(_LI("Need to remove FC Zone, building initiator "
                             "target map"))

                target_wwns, init_targ_map, _numPaths = \
                    self._build_initiator_target_map(common, connector)

                info['data'] = {'target_wwn': target_wwns,
                                'initiator_target_map': init_targ_map}
            return info

        finally:
            self._logout(common)

    def _build_initiator_target_map(self, common, connector):
        """Build the target_wwns and the initiator target map."""

        fc_ports = common.get_active_fc_target_ports()
        all_target_wwns = []
        target_wwns = []
        init_targ_map = {}
        numPaths = 0

        for port in fc_ports:
            all_target_wwns.append(port['portWWN'])

        if self.lookup_service is not None:
            # use FC san lookup to determine which NSPs to use
            # for the new VLUN.
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector['wwpns'],
                all_target_wwns)

            for fabric_name in dev_map:
                fabric = dev_map[fabric_name]
                target_wwns += fabric['target_port_wwn_list']
                for initiator in fabric['initiator_port_wwn_list']:
                    if initiator not in init_targ_map:
                        init_targ_map[initiator] = []
                    init_targ_map[initiator] += fabric['target_port_wwn_list']
                    init_targ_map[initiator] = list(set(
                        init_targ_map[initiator]))
                    for _target in init_targ_map[initiator]:
                        numPaths += 1
            target_wwns = list(set(target_wwns))
        else:
            initiator_wwns = connector['wwpns']
            target_wwns = all_target_wwns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map, numPaths

    def _create_3par_fibrechan_host(self, common, hostname, wwns,
                                    domain, persona_id):
        """Create a 3PAR host.

        Create a 3PAR host, if there is already a host on the 3par using
        the same wwn but with a different hostname, return the hostname
        used by 3PAR.
        """
        # first search for an existing host
        host_found = None
        hosts = common.client.queryHost(wwns=wwns)

        if hosts and hosts['members'] and 'name' in hosts['members'][0]:
            host_found = hosts['members'][0]['name']

        if host_found is not None:
            return host_found
        else:
            persona_id = int(persona_id)
            common.client.createHost(hostname, FCWwns=wwns,
                                     optional={'domain': domain,
                                               'persona': persona_id})
            return hostname

    def _modify_3par_fibrechan_host(self, common, hostname, wwn):
        mod_request = {'pathOperation': common.client.HOST_EDIT_ADD,
                       'FCWWNs': wwn}

        common.client.modifyHost(hostname, mod_request)

    def _create_host(self, common, volume, connector):
        """Creates or modifies existing 3PAR host."""
        host = None
        hostname = common._safe_hostname(connector['host'])
        cpg = common.get_cpg(volume, allowSnap=True)
        domain = common.get_domain(cpg)
        try:
            host = common._get_3par_host(hostname)
        except hpexceptions.HTTPNotFound:
            # get persona from the volume type extra specs
            persona_id = common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            hostname = self._create_3par_fibrechan_host(common,
                                                        hostname,
                                                        connector['wwpns'],
                                                        domain,
                                                        persona_id)
            host = common._get_3par_host(hostname)

        return self._add_new_wwn_to_host(common, host, connector['wwpns'])

    def _add_new_wwn_to_host(self, common, host, wwns):
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
            self._modify_3par_fibrechan_host(common, host['name'], new_wwns)
            host = common._get_3par_host(host['name'])
        return host

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def extend_volume(self, volume, new_size):
        common = self._login()
        try:
            common.extend_volume(volume, new_size)
        finally:
            self._logout(common)

    def manage_existing(self, volume, existing_ref):
        common = self._login()
        try:
            return common.manage_existing(volume, existing_ref)
        finally:
            self._logout(common)

    def manage_existing_get_size(self, volume, existing_ref):
        common = self._login()
        try:
            return common.manage_existing_get_size(volume, existing_ref)
        finally:
            self._logout(common)

    def unmanage(self, volume):
        common = self._login()
        try:
            common.unmanage(volume)
        finally:
            self._logout(common)

    def attach_volume(self, context, volume, instance_uuid, host_name,
                      mountpoint):
        common = self._login()
        try:
            common.attach_volume(volume, instance_uuid)
        finally:
            self._logout(common)

    def detach_volume(self, context, volume, attachment=None):
        common = self._login()
        try:
            common.detach_volume(volume, attachment)
        finally:
            self._logout(common)

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type."""
        common = self._login()
        try:
            return common.retype(volume, new_type, diff, host)
        finally:
            self._logout(common)

    def migrate_volume(self, context, volume, host):
        if volume['status'] == 'in-use':
            protocol = host['capabilities']['storage_protocol']
            if protocol != 'FC':
                LOG.debug("3PAR FC driver cannot migrate in-use volume "
                          "to a host with storage_protocol=%s." % protocol)
                return False, None

        common = self._login()
        try:
            return common.migrate_volume(volume, host)
        finally:
            self._logout(common)

    def get_pool(self, volume):
        common = self._login()
        try:
            return common.get_cpg(volume)
        except hpexceptions.HTTPNotFound:
            reason = (_("Volume %s doesn't exist on array.") % volume)
            LOG.error(reason)
            raise exception.InvalidVolume(reason)
        finally:
            self._logout(common)
