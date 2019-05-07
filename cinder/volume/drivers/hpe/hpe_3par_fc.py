#    (c) Copyright 2013-2015 Hewlett Packard Enterprise Development LP
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
"""Volume driver for HPE 3PAR Storage array.

This driver requires 3.1.3 or later firmware on the 3PAR array, using
the 4.x version of the hpe3parclient.

You will need to install the python hpe3parclient.
sudo pip install --upgrade "hpe3parclient>=4.0"

Set the following in the cinder.conf file to enable the
3PAR Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.hpe.hpe_3par_fc.HPE3PARFCDriver
"""

try:
    from hpe3parclient import exceptions as hpeexceptions
except ImportError:
    hpeexceptions = None

from oslo_log import log as logging
from oslo_utils.excutils import save_and_reraise_exception

from cinder import interface
from cinder import utils
from cinder.volume.drivers.hpe import hpe_3par_base as hpebasedriver
from cinder.zonemanager import utils as fczm_utils

LOG = logging.getLogger(__name__)

# EXISTENT_PATH error code returned from hpe3parclient
EXISTENT_PATH = 73


@interface.volumedriver
class HPE3PARFCDriver(hpebasedriver.HPE3PARDriverBase):
    """OpenStack Fibre Channel driver to enable 3PAR storage array.

    Version history:

    .. code-block:: none

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
        2.0.18 - Changed initialize_connection to use getHostVLUNs. #1475064
        2.0.19 - Adds consistency group support
        2.0.20 - Update driver to use ABC metaclasses
        2.0.21 - Added update_migrated_volume. bug # 1492023
        3.0.0 - Rebranded HP to HPE.
        3.0.1 - Remove db access for consistency groups
        3.0.2 - Adds v2 managed replication support
        3.0.3 - Adds v2 unmanaged replication support
        3.0.4 - Adding manage/unmanage snapshot support
        3.0.5 - Optimize array ID retrieval
        3.0.6 - Update replication to version 2.1
        3.0.7 - Remove metadata that tracks the instance ID. bug #1572665
        3.0.8 - NSP feature, creating FC Vlun as match set instead of
                host sees. bug #1577993
        3.0.9 - Handling HTTP conflict 409, host WWN/iSCSI name already used
                by another host, while creating 3PAR FC Host. bug #1597454
        3.0.10 - Added Entry point tracing
        3.0.11 - Handle manage and unmanage hosts present. bug #1648067
        3.0.12 - Adds consistency group capability in generic volume groups.
        4.0.0 - Adds base class.
        4.0.1 - Added check to remove FC zones. bug #1730720
        4.0.2 - Create one vlun in single path configuration. bug #1727176
        4.0.3 - Create FC vlun as host sees. bug #1734505
        4.0.4 - Handle force detach case. bug #1686745
        4.0.5 - Set proper backend on subsequent operation, after group
                failover. bug #1773069
        4.0.6 - Set NSP for single path attachments. Bug #1809249

    """

    VERSION = "4.0.5"

    # The name of the CI wiki page.
    CI_WIKI_NAME = "HPE_Storage_CI"

    def __init__(self, *args, **kwargs):
        super(HPE3PARFCDriver, self).__init__(*args, **kwargs)
        self.lookup_service = fczm_utils.create_lookup_service()
        self.protocol = 'FC'

    @utils.trace
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
        array_id = self.get_volume_replication_driver_data(volume)
        common = self._login(array_id=array_id)
        try:
            # we have to make sure we have a host
            host = self._create_host(common, volume, connector)
            target_wwns, init_targ_map, numPaths = (
                self._build_initiator_target_map(common, connector))

            multipath = connector.get('multipath')
            LOG.debug("multipath: %s", multipath)
            user_target = None
            if not multipath:
                user_target = self._get_user_target(common)
                initiator = connector.get('wwpns')[0]
                if user_target is None:
                    target_wwns = target_wwns[:1]
                    init_targ_map[initiator] = init_targ_map[initiator][:1]
                else:
                    target_wwns = [user_target]
                    init_targ_map[initiator] = [user_target]

            # check if a VLUN already exists for this host
            existing_vlun = common.find_existing_vlun(volume, host)

            vlun = None
            if existing_vlun is None:
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
            fczm_utils.add_fc_zone(info)
            return info
        finally:
            self._logout(common)

    @utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        array_id = self.get_volume_replication_driver_data(volume)
        common = self._login(array_id=array_id)
        try:
            is_force_detach = connector is None
            if is_force_detach:
                common.terminate_connection(volume, None, None)
                # TODO(sonivi): remove zones, if not required
                # for now, do not remove zones
                zone_remove = False
            else:
                hostname = common._safe_hostname(connector['host'])
                common.terminate_connection(volume, hostname,
                                            wwn=connector['wwpns'])

                zone_remove = True
                try:
                    vluns = common.client.getHostVLUNs(hostname)
                except hpeexceptions.HTTPNotFound:
                    # No more exports for this host.
                    pass
                else:
                    # Vlun exists, so check for wwpn entry.
                    for wwpn in connector.get('wwpns'):
                        for vlun in vluns:
                            if (vlun.get('active') and
                                    vlun.get('remoteName') == wwpn.upper()):
                                zone_remove = False
                                break

            info = {'driver_volume_type': 'fibre_channel',
                    'data': {}}

            if zone_remove:
                LOG.info("Need to remove FC Zone, building initiator "
                         "target map")
                target_wwns, init_targ_map, _numPaths = \
                    self._build_initiator_target_map(common, connector)

                info['data'] = {'target_wwn': target_wwns,
                                'initiator_target_map': init_targ_map}
                fczm_utils.remove_fc_zone(info)
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
            try:
                common.client.createHost(hostname, FCWwns=wwns,
                                         optional={'domain': domain,
                                                   'persona': persona_id})
            except hpeexceptions.HTTPConflict as path_conflict:
                msg = "Create FC host caught HTTP conflict code: %s"
                LOG.exception(msg, path_conflict.get_code())
                with save_and_reraise_exception(reraise=False) as ctxt:
                    if path_conflict.get_code() is EXISTENT_PATH:
                        # Handle exception : EXISTENT_PATH - host WWN/iSCSI
                        # name already used by another host
                        hosts = common.client.queryHost(wwns=wwns)
                        if hosts and hosts['members'] and (
                                'name' in hosts['members'][0]):
                            hostname = hosts['members'][0]['name']
                        else:
                            # re rasise last caught exception
                            ctxt.reraise = True
                    else:
                        # re rasise last caught exception
                        # for other HTTP conflict
                        ctxt.reraise = True
            return hostname

    def _modify_3par_fibrechan_host(self, common, hostname, wwn):
        mod_request = {'pathOperation': common.client.HOST_EDIT_ADD,
                       'FCWWNs': wwn}
        try:
            common.client.modifyHost(hostname, mod_request)
        except hpeexceptions.HTTPConflict as path_conflict:
            msg = ("Modify FC Host %(hostname)s caught "
                   "HTTP conflict code: %(code)s")
            LOG.exception(msg,
                          {'hostname': hostname,
                           'code': path_conflict.get_code()})

    def _create_host(self, common, volume, connector):
        """Creates or modifies existing 3PAR host."""
        host = None
        hostname = common._safe_hostname(connector['host'])
        cpg = common.get_cpg(volume, allowSnap=True)
        domain = common.get_domain(cpg)
        if not connector.get('multipath'):
            connector['wwpns'] = connector['wwpns'][:1]
        try:
            host = common._get_3par_host(hostname)
            # Check whether host with wwn of initiator present on 3par
            hosts = common.client.queryHost(wwns=connector['wwpns'])
            host, hostname = common._get_prioritized_host_on_3par(host,
                                                                  hosts,
                                                                  hostname)
        except hpeexceptions.HTTPNotFound:
            # get persona from the volume type extra specs
            persona_id = common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            hostname = self._create_3par_fibrechan_host(common,
                                                        hostname,
                                                        connector['wwpns'],
                                                        domain,
                                                        persona_id)
            host = common._get_3par_host(hostname)
            return host
        else:
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

    def _get_user_target(self, common):
        target_nsp = common.config.hpe3par_target_nsp

        if not target_nsp:
            return None

        # Get target wwn from target nsp
        fc_ports = common.get_active_fc_target_ports()

        target_wwn = None
        for port in fc_ports:
            nsp = port['nsp']
            if target_nsp == nsp:
                target_wwn = port['portWWN']
                break

        if not target_wwn:
            LOG.warning("Did not get wwn for target nsp: "
                        "%(nsp)s", {'nsp': target_nsp})

        return target_wwn
