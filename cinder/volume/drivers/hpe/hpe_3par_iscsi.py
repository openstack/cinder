#    (c) Copyright 2012-2015 Hewlett Packard Enterprise Development LP
#    All Rights Reserved.
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
Volume driver for HPE 3PAR Storage array.
This driver requires 3.1.3 or later firmware on the 3PAR array, using
the 4.x version of the hpe3parclient.

You will need to install the python hpe3parclient.
sudo pip install --upgrade "hpe3parclient>=4.0"

Set the following in the cinder.conf file to enable the
3PAR iSCSI Driver along with the required flags:

volume_driver=cinder.volume.drivers.hpe.hpe_3par_iscsi.HPE3PARISCSIDriver
"""

import re
import sys

try:
    from hpe3parclient import exceptions as hpeexceptions
except ImportError:
    hpeexceptions = None

from oslo_log import log as logging
from oslo_utils.excutils import save_and_reraise_exception

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume.drivers.hpe import hpe_3par_base as hpebasedriver
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)

# EXISTENT_PATH error code returned from hpe3parclient
EXISTENT_PATH = 73
DEFAULT_ISCSI_PORT = 3260
CHAP_USER_KEY = "HPQ-cinder-CHAP-name"
CHAP_PASS_KEY = "HPQ-cinder-CHAP-secret"


@interface.volumedriver
class HPE3PARISCSIDriver(hpebasedriver.HPE3PARDriverBase):
    """OpenStack iSCSI driver to enable 3PAR storage array.

    Version history:

    .. code-block:: none

        1.0   - Initial driver
        1.1   - QoS, extend volume, multiple iscsi ports, remove domain,
                session changes, faster clone, requires 3.1.2 MU2 firmware.
        1.2.0 - Updated the use of the hp3parclient to 2.0.0 and refactored
                the drivers to use the new APIs.
        1.2.1 - Synchronized extend_volume method.
        1.2.2 - Added try/finally around client login/logout.
        1.2.3 - log exceptions before raising
        1.2.4 - Fixed iSCSI active path bug #1224594
        1.2.5 - Added metadata during attach/detach bug #1258033
        1.2.6 - Use least-used iscsi n:s:p for iscsi volume attach bug #1269515
                This update now requires 3.1.2 MU3 firmware
        1.3.0 - Removed all SSH code.  We rely on the hp3parclient now.
        2.0.0 - Update hp3parclient API uses 3.0.x
        2.0.2 - Add back-end assisted volume migrate
        2.0.3 - Added support for managing/unmanaging of volumes
        2.0.4 - Added support for volume retype
        2.0.5 - Added CHAP support, requires 3.1.3 MU1 firmware
                and hp3parclient 3.1.0.
        2.0.6 - Fixing missing login/logout around attach/detach bug #1367429
        2.0.7 - Add support for pools with model update
        2.0.8 - Migrate without losing type settings bug #1356608
        2.0.9 - Removing locks bug #1381190
        2.0.10 - Add call to queryHost instead SSH based findHost #1398206
        2.0.11 - Added missing host name during attach fix #1398206
        2.0.12 - Removed usage of host name cache #1398914
        2.0.13 - Update LOG usage to fix translations.  bug #1384312
        2.0.14 - Do not allow a different iSCSI IP (hp3par_iscsi_ips) to be
                 used during live-migration.  bug #1423958
        2.0.15 - Added support for updated detach_volume attachment.
        2.0.16 - Added encrypted property to initialize_connection #1439917
        2.0.17 - Python 3 fixes
        2.0.18 - Improved VLUN creation and deletion logic. #1469816
        2.0.19 - Changed initialize_connection to use getHostVLUNs. #1475064
        2.0.20 - Adding changes to support 3PAR iSCSI multipath.
        2.0.21 - Adds consistency group support
        2.0.22 - Update driver to use ABC metaclasses
        2.0.23 - Added update_migrated_volume. bug # 1492023
        3.0.0 - Rebranded HP to HPE.
        3.0.1 - Python 3 support
        3.0.2 - Remove db access for consistency groups
        3.0.3 - Fix multipath dictionary key error. bug #1522062
        3.0.4 - Adds v2 managed replication support
        3.0.5 - Adds v2 unmanaged replication support
        3.0.6 - Adding manage/unmanage snapshot support
        3.0.7 - Optimize array ID retrieval
        3.0.8 - Update replication to version 2.1
        3.0.9 - Use same LUN ID for each VLUN path #1551994
        3.0.10 - Remove metadata that tracks the instance ID. bug #1572665
        3.0.11 - _create_3par_iscsi_host() now accepts iscsi_iqn as list only.
                 Bug #1590180
        3.0.12 - Added entry point tracing
        3.0.13 - Handling HTTP conflict 409, host WWN/iSCSI name already used
                by another host, while creating 3PAR iSCSI Host. bug #1642945
        3.0.14 - Handle manage and unmanage hosts present. bug #1648067
        3.0.15 - Adds consistency group capability in generic volume groups.
        3.0.16 - Get host from os-brick connector. bug #1690244
        4.0.0 - Adds base class.
        4.0.1 - Update CHAP on host record when volume is migrated
                to new compute host. bug # 1737181
        4.0.2 - Handle force detach case. bug #1686745
        4.0.3 - Set proper backend on subsequent operation, after group
                failover. bug #1773069
        4.0.4 - Added Peer Persistence feature
        4.0.5 - Added Primera array check. bug #1849525
        4.0.6 - Allow iSCSI support for Primera 4.2 onwards

    """

    VERSION = "4.0.6"

    # The name of the CI wiki page.
    CI_WIKI_NAME = "HPE_Storage_CI"

    def __init__(self, *args, **kwargs):
        super(HPE3PARISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = 'iSCSI'

    def _do_setup(self, common):
        client_obj = common.client
        is_primera = client_obj.is_primera_array()
        if is_primera:
            api_version = client_obj.getWsApiVersion()
            array_version = api_version['build']
            LOG.debug("array version: %(version)s",
                      {'version': array_version})
            if array_version < 40200000:
                err_msg = (_('The iSCSI driver is not supported for '
                             'Primera %(version)s. It is supported '
                             'for Primera 4.2 or higher versions.')
                           % {'version': array_version})
                LOG.error(err_msg)
                raise NotImplementedError()

        self.iscsi_ips = {}
        common.client_login()
        try:
            self.initialize_iscsi_ports(common)
        finally:
            self._logout(common)

    def initialize_iscsi_ports(self, common,
                               remote_target=None, remote_client=None):
        # map iscsi_ip-> ip_port
        #             -> iqn
        #             -> nsp
        iscsi_ip_list = {}
        temp_iscsi_ip = {}

        if remote_target:
            backend_conf = remote_target
        else:
            backend_conf = common._client_conf

        # use the 3PAR ip_addr list for iSCSI configuration
        if len(backend_conf['hpe3par_iscsi_ips']) > 0:
            # add port values to ip_addr, if necessary
            for ip_addr in backend_conf['hpe3par_iscsi_ips']:
                ip = ip_addr.split(':')
                if len(ip) == 1:
                    temp_iscsi_ip[ip_addr] = {'ip_port': DEFAULT_ISCSI_PORT}
                elif len(ip) == 2:
                    temp_iscsi_ip[ip[0]] = {'ip_port': ip[1]}
                else:
                    LOG.warning("Invalid IP address format '%s'", ip_addr)

        # add the single value iscsi_ip_address option to the IP dictionary.
        # This way we can see if it's a valid iSCSI IP. If it's not valid,
        # we won't use it and won't bother to report it, see below
        if 'iscsi_ip_address' in backend_conf:
            if (backend_conf['iscsi_ip_address'] not in temp_iscsi_ip):
                ip = backend_conf['iscsi_ip_address']
                ip_port = backend_conf['iscsi_port']
                temp_iscsi_ip[ip] = {'ip_port': ip_port}

        # get all the valid iSCSI ports from 3PAR
        # when found, add the valid iSCSI ip, ip port, iqn and nsp
        # to the iSCSI IP dictionary
        iscsi_ports = common.get_active_iscsi_target_ports(remote_client)

        for port in iscsi_ports:
            ip = port['IPAddr']
            if ip in temp_iscsi_ip:
                ip_port = temp_iscsi_ip[ip]['ip_port']
                iscsi_ip_list[ip] = {'ip_port': ip_port,
                                     'nsp': port['nsp'],
                                     'iqn': port['iSCSIName']}
                del temp_iscsi_ip[ip]

        # if the single value iscsi_ip_address option is still in the
        # temp dictionary it's because it defaults to $my_ip which doesn't
        # make sense in this context. So, if present, remove it and move on.
        if 'iscsi_ip_address' in backend_conf:
            if backend_conf['iscsi_ip_address'] in temp_iscsi_ip:
                del temp_iscsi_ip[backend_conf['iscsi_ip_address']]

        # lets see if there are invalid iSCSI IPs left in the temp dict
        if len(temp_iscsi_ip) > 0:
            LOG.warning("Found invalid iSCSI IP address(s) in "
                        "configuration option(s) hpe3par_iscsi_ips or "
                        "target_ip_address '%s.'",
                        (", ".join(temp_iscsi_ip)))

        if not len(iscsi_ip_list):
            msg = _('At least one valid iSCSI IP address must be set.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if remote_target:
            self.iscsi_ips[remote_target['hpe3par_api_url']] = iscsi_ip_list
        else:
            self.iscsi_ips[common._client_conf['hpe3par_api_url']] = (
                iscsi_ip_list)

    def _initialize_connection_common(self, volume, connector, common,
                                      host, iscsi_ips, ready_ports,
                                      target_portals, target_iqns, target_luns,
                                      remote_client=None):

        # Target portal ips are defined in cinder.conf.
        target_portal_ips = iscsi_ips.keys()

        # Collect all existing VLUNs for this volume/host combination.
        existing_vluns = common.find_existing_vluns(volume, host,
                                                    remote_client)

        # Cycle through each ready iSCSI port and determine if a new
        # VLUN should be created or an existing one used.
        lun_id = None
        for port in ready_ports:
            iscsi_ip = port['IPAddr']
            if iscsi_ip in target_portal_ips:
                vlun = None
                # check for an already existing VLUN matching the
                # nsp for this iSCSI IP. If one is found, use it
                # instead of creating a new VLUN.
                for v in existing_vluns:
                    portPos = common.build_portPos(
                        iscsi_ips[iscsi_ip]['nsp'])
                    if v['portPos'] == portPos:
                        vlun = v
                        break
                else:
                    vlun = common.create_vlun(
                        volume, host, iscsi_ips[iscsi_ip]['nsp'],
                        lun_id=lun_id, remote_client=remote_client)

                    # We want to use the same LUN ID for every port
                    if lun_id is None:
                        lun_id = vlun['lun']

                iscsi_ip_port = "%s:%s" % (
                    iscsi_ip, iscsi_ips[iscsi_ip]['ip_port'])
                target_portals.append(iscsi_ip_port)
                target_iqns.append(port['iSCSIName'])
                target_luns.append(vlun['lun'])
            else:
                LOG.warning("iSCSI IP: '%s' was not found in "
                            "hpe3par_iscsi_ips list defined in "
                            "cinder.conf.", iscsi_ip)

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host.

        This driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value:

        .. code-block:: default

            {
                'driver_volume_type': 'iscsi',
                'data': {
                    'encrypted': False,
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_protal': '127.0.0.1:3260',
                    'volume_id': 1,
                }
            }

        Steps to export a volume on 3PAR
          * Get the 3PAR iSCSI iqn
          * Create a host on the 3par
          * create vlun on the 3par
        """
        LOG.debug("volume id: %(volume_id)s",
                  {'volume_id': volume['id']})
        array_id = self.get_volume_replication_driver_data(volume)
        common = self._login(array_id=array_id)
        try:
            # If the volume has been failed over, we need to reinitialize
            # iSCSI ports so they represent the new array.
            if volume.get('replication_status') == 'failed-over' and (
               common._client_conf['hpe3par_api_url'] not in self.iscsi_ips):
                self.initialize_iscsi_ports(common)

            # Grab the correct iSCSI ports
            iscsi_ips = self.iscsi_ips[common._client_conf['hpe3par_api_url']]

            # we have to make sure we have a host
            host, username, password, cpg = self._create_host(
                common,
                volume,
                connector)

            multipath = connector.get('multipath')
            LOG.debug("multipath: %(multipath)s",
                      {'multipath': multipath})
            if multipath:
                ready_ports = common.client.getiSCSIPorts(
                    state=common.client.PORT_STATE_READY)

                target_portals = []
                target_iqns = []
                target_luns = []

                self._initialize_connection_common(
                    volume, connector, common,
                    host, iscsi_ips, ready_ports,
                    target_portals, target_iqns, target_luns)

                if volume.get('replication_status') == 'enabled':
                    LOG.debug('This is a replication setup')

                    remote_target = common._replication_targets[0]
                    replication_mode = remote_target['replication_mode']
                    quorum_witness_ip = (
                        remote_target.get('quorum_witness_ip'))

                    if replication_mode == 1:
                        LOG.debug('replication_mode is sync')
                        if quorum_witness_ip:
                            LOG.debug('quorum_witness_ip is present')
                            LOG.debug('Peer Persistence has been configured')
                        else:
                            LOG.debug('Since quorum_witness_ip is absent, '
                                      'considering this as Active/Passive '
                                      'replication')
                    else:
                        LOG.debug('Active/Passive replication has been '
                                  'configured')

                    if replication_mode == 1 and quorum_witness_ip:
                        remote_client = (
                            common._create_replication_client(remote_target))

                        self.initialize_iscsi_ports(
                            common, remote_target, remote_client)
                        remote_iscsi_ips = (
                            self.iscsi_ips[remote_target['hpe3par_api_url']])

                        # we have to make sure we have a host
                        host, username, password, cpg = (
                            self._create_host(
                                common, volume, connector,
                                remote_target, cpg, remote_client))

                        ready_ports = remote_client.getiSCSIPorts(
                            state=remote_client.PORT_STATE_READY)

                        self._initialize_connection_common(
                            volume, connector, common,
                            host, remote_iscsi_ips, ready_ports,
                            target_portals, target_iqns, target_luns,
                            remote_client)

                        common._destroy_replication_client(remote_client)

                info = {'driver_volume_type': 'iscsi',
                        'data': {'target_portals': target_portals,
                                 'target_iqns': target_iqns,
                                 'target_luns': target_luns,
                                 'target_discovered': True
                                 }
                        }
            else:
                least_used_nsp = None

                # check if a VLUN already exists for this host
                existing_vlun = common.find_existing_vlun(volume, host)

                if existing_vlun:
                    # We override the nsp here on purpose to force the
                    # volume to be exported out the same IP as it already is.
                    # This happens during nova live-migration, we want to
                    # disable the picking of a different IP that we export
                    # the volume to, or nova complains.
                    least_used_nsp = common.build_nsp(existing_vlun['portPos'])

                if not least_used_nsp:
                    least_used_nsp = self._get_least_used_nsp_for_host(
                        common,
                        host['name'])

                vlun = None
                if existing_vlun is None:
                    # now that we have a host, create the VLUN
                    vlun = common.create_vlun(volume, host, least_used_nsp)
                else:
                    vlun = existing_vlun

                if least_used_nsp is None:
                    LOG.warning("Least busy iSCSI port not found, "
                                "using first iSCSI port in list.")
                    iscsi_ip = list(iscsi_ips)[0]
                else:
                    iscsi_ip = self._get_ip_using_nsp(least_used_nsp, common)

                iscsi_ip_port = iscsi_ips[iscsi_ip]['ip_port']
                iscsi_target_iqn = iscsi_ips[iscsi_ip]['iqn']
                info = {'driver_volume_type': 'iscsi',
                        'data': {'target_portal': "%s:%s" %
                                 (iscsi_ip, iscsi_ip_port),
                                 'target_iqn': iscsi_target_iqn,
                                 'target_lun': vlun['lun'],
                                 'target_discovered': True
                                 }
                        }

            if common._client_conf['hpe3par_iscsi_chap_enabled']:
                info['data']['auth_method'] = 'CHAP'
                info['data']['auth_username'] = username
                info['data']['auth_password'] = password

            encryption_key_id = volume.get('encryption_key_id', None)
            info['data']['encrypted'] = encryption_key_id is not None

            return info
        finally:
            self._logout(common)

    @volume_utils.trace
    @coordination.synchronized('3par-{volume.id}')
    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to detach a volume from an instance."""
        array_id = self.get_volume_replication_driver_data(volume)
        common = self._login(array_id=array_id)
        try:
            is_force_detach = connector is None

            remote_client = None
            multipath = False
            if connector:
                multipath = connector.get('multipath')
            LOG.debug("multipath: %(multipath)s",
                      {'multipath': multipath})
            if multipath:
                if volume.get('replication_status') == 'enabled':
                    LOG.debug('This is a replication setup')

                    remote_target = common._replication_targets[0]
                    replication_mode = remote_target['replication_mode']
                    quorum_witness_ip = (
                        remote_target.get('quorum_witness_ip'))

                    if replication_mode == 1:
                        LOG.debug('replication_mode is sync')
                        if quorum_witness_ip:
                            LOG.debug('quorum_witness_ip is present')
                            LOG.debug('Peer Persistence has been configured')
                        else:
                            LOG.debug('Since quorum_witness_ip is absent, '
                                      'considering this as Active/Passive '
                                      'replication')
                    else:
                        LOG.debug('Active/Passive replication has been '
                                  'configured')

                    if replication_mode == 1 and quorum_witness_ip:
                        remote_client = (
                            common._create_replication_client(remote_target))

            if is_force_detach:
                common.terminate_connection(volume, None, None)
            else:
                hostname = common._safe_hostname(connector, self.configuration)
                common.terminate_connection(
                    volume,
                    hostname,
                    iqn=connector['initiator'],
                    remote_client=remote_client)
            self._clear_chap_3par(common, volume)
        finally:
            self._logout(common)

    def _clear_chap_3par(self, common, volume):
        """Clears CHAP credentials on a 3par volume.

        Ignore exceptions caused by the keys not being present on a volume.
        """
        vol_name = common._get_3par_vol_name(volume)

        try:
            common.client.removeVolumeMetaData(vol_name, CHAP_USER_KEY)
        except hpeexceptions.HTTPNotFound:
            pass
        except Exception:
            raise

        try:
            common.client.removeVolumeMetaData(vol_name, CHAP_PASS_KEY)
        except hpeexceptions.HTTPNotFound:
            pass
        except Exception:
            raise

    def _create_3par_iscsi_host(self, common, hostname, iscsi_iqn, domain,
                                persona_id, remote_client=None):
        """Create a 3PAR host.

        Create a 3PAR host, if there is already a host on the 3par using
        the same iqn but with a different hostname, return the hostname
        used by 3PAR.
        """
        # first search for an existing host
        host_found = None

        if remote_client:
            client_obj = remote_client
        else:
            client_obj = common.client

        hosts = client_obj.queryHost(iqns=iscsi_iqn)

        if hosts and hosts['members'] and 'name' in hosts['members'][0]:
            host_found = hosts['members'][0]['name']

        if host_found is not None:
            return host_found
        else:
            persona_id = int(persona_id)
            try:
                client_obj.createHost(hostname, iscsiNames=iscsi_iqn,
                                      optional={'domain': domain,
                                                'persona': persona_id})
            except hpeexceptions.HTTPConflict as path_conflict:
                msg = "Create iSCSI host caught HTTP conflict code: %s"
                with save_and_reraise_exception(reraise=False) as ctxt:
                    if path_conflict.get_code() is EXISTENT_PATH:
                        # Handle exception : EXISTENT_PATH - host WWN/iSCSI
                        # name already used by another host
                        hosts = client_obj.queryHost(iqns=iscsi_iqn)
                        if hosts and hosts['members'] and (
                                'name' in hosts['members'][0]):
                            hostname = hosts['members'][0]['name']
                        else:
                            # re-raise last caught exception
                            ctxt.reraise = True
                            LOG.exception(msg, path_conflict.get_code())
                    else:
                        # re-raise last caught exception
                        # for other HTTP conflict
                        ctxt.reraise = True
                        LOG.exception(msg, path_conflict.get_code())
            return hostname

    def _modify_3par_iscsi_host(self, common, hostname, iscsi_iqn):
        mod_request = {'pathOperation': common.client.HOST_EDIT_ADD,
                       'iSCSINames': [iscsi_iqn]}

        common.client.modifyHost(hostname, mod_request)

    def _set_3par_chaps(self, common, hostname, volume, username, password):
        """Sets a 3PAR host's CHAP credentials."""
        if not common._client_conf['hpe3par_iscsi_chap_enabled']:
            return

        mod_request = {'chapOperation': common.client.HOST_EDIT_ADD,
                       'chapOperationMode': common.client.CHAP_INITIATOR,
                       'chapName': username,
                       'chapSecret': password}
        common.client.modifyHost(hostname, mod_request)

    def _create_host(self, common, volume, connector,
                     remote_target=None, src_cpg=None, remote_client=None):
        """Creates or modifies existing 3PAR host."""
        # make sure we don't have the host already
        host = None
        domain = None
        username = None
        password = None
        hostname = common._safe_hostname(connector, self.configuration)

        if remote_target:
            cpg = common._get_cpg_from_cpg_map(
                remote_target['cpg_map'], src_cpg)
            cpg_obj = remote_client.getCPG(cpg)
            if 'domain' in cpg_obj:
                domain = cpg_obj['domain']
        else:
            cpg = common.get_cpg(volume, allowSnap=True)
            domain = common.get_domain(cpg)

        if not remote_target:
            # Get the CHAP secret if CHAP is enabled
            if common._client_conf['hpe3par_iscsi_chap_enabled']:
                vol_name = common._get_3par_vol_name(volume)
                username = common.client.getVolumeMetaData(
                    vol_name, CHAP_USER_KEY)['value']
                password = common.client.getVolumeMetaData(
                    vol_name, CHAP_PASS_KEY)['value']

        try:
            if remote_target:
                host = remote_client.getHost(hostname)
            else:
                host = common._get_3par_host(hostname)
                # Check whether host with iqn of initiator present on 3par
                hosts = common.client.queryHost(iqns=[connector['initiator']])
                host, hostname = (
                    common._get_prioritized_host_on_3par(
                        host, hosts, hostname))
        except hpeexceptions.HTTPNotFound:
            # get persona from the volume type extra specs
            persona_id = common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            hostname = self._create_3par_iscsi_host(common,
                                                    hostname,
                                                    [connector['initiator']],
                                                    domain,
                                                    persona_id,
                                                    remote_client)
        else:
            if not remote_target:
                if 'iSCSIPaths' not in host or len(host['iSCSIPaths']) < 1:
                    self._modify_3par_iscsi_host(
                        common, hostname,
                        connector['initiator'])
                elif (not host['initiatorChapEnabled'] and
                        common._client_conf['hpe3par_iscsi_chap_enabled']):
                    LOG.warning("Host exists without CHAP credentials set and "
                                "has iSCSI attachments but CHAP is enabled. "
                                "Updating host with new CHAP credentials.")

        if remote_target:
            host = remote_client.getHost(hostname)
        else:
            # set/update the chap details for the host
            self._set_3par_chaps(common, hostname, volume, username, password)
            host = common._get_3par_host(hostname)
        return host, username, password, cpg

    def _do_export(self, common, volume, connector):
        """Gets the associated account, generates CHAP info and updates."""
        model_update = {}

        if not common._client_conf['hpe3par_iscsi_chap_enabled']:
            model_update['provider_auth'] = None
            return model_update

        # CHAP username will be the hostname
        chap_username = connector['host']

        chap_password = None
        try:
            # Get all active VLUNs for the host
            vluns = common.client.getHostVLUNs(chap_username)

            # Host has active VLUNs... is CHAP enabled on host?
            host_info = common.client.getHost(chap_username)

            if not host_info['initiatorChapEnabled']:
                LOG.warning("Host has no CHAP key, but CHAP is enabled.")

        except hpeexceptions.HTTPNotFound:
            chap_password = volume_utils.generate_password(16)
            LOG.warning("No host or VLUNs exist. Generating new "
                        "CHAP key.")
        else:
            # Get a list of all iSCSI VLUNs and see if there is already a CHAP
            # key assigned to one of them.  Use that CHAP key if present,
            # otherwise create a new one.  Skip any VLUNs that are missing
            # CHAP credentials in metadata.
            chap_exists = False
            active_vluns = 0

            for vlun in vluns:
                if not vlun['active']:
                    continue

                active_vluns += 1

                # iSCSI connections start with 'iqn'.
                if ('remoteName' in vlun and
                        re.match('iqn.*', vlun['remoteName'])):
                    try:
                        chap_password = common.client.getVolumeMetaData(
                            vlun['volumeName'], CHAP_PASS_KEY)['value']
                        chap_exists = True
                        break
                    except hpeexceptions.HTTPNotFound:
                        LOG.debug("The VLUN %s is missing CHAP credentials "
                                  "but CHAP is enabled. Skipping.",
                                  vlun['remoteName'])
                else:
                    LOG.warning("Non-iSCSI VLUN detected.")

            if not chap_exists:
                chap_password = volume_utils.generate_password(16)
                LOG.warning("No VLUN contained CHAP credentials. "
                            "Generating new CHAP key.")

        # Add CHAP credentials to the volume metadata
        vol_name = common._get_3par_vol_name(volume)
        common.client.setVolumeMetaData(
            vol_name, CHAP_USER_KEY, chap_username)
        common.client.setVolumeMetaData(
            vol_name, CHAP_PASS_KEY, chap_password)

        model_update['provider_auth'] = ('CHAP %s %s' %
                                         (chap_username, chap_password))

        return model_update

    @volume_utils.trace
    def create_export(self, context, volume, connector):
        common = self._login()
        try:
            return self._do_export(common, volume, connector)
        finally:
            self._logout(common)

    @volume_utils.trace
    def ensure_export(self, context, volume):
        """Ensure the volume still exists on the 3PAR.

        Also retrieves CHAP credentials, if present on the volume
        """
        common = self._login()
        try:
            vol_name = common._get_3par_vol_name(volume)
            common.client.getVolume(vol_name)
        except hpeexceptions.HTTPNotFound:
            LOG.error("Volume %s doesn't exist on array.", vol_name)
        else:
            metadata = common.client.getAllVolumeMetaData(vol_name)

            username = None
            password = None
            model_update = {}
            model_update['provider_auth'] = None

            for member in metadata['members']:
                if member['key'] == CHAP_USER_KEY:
                    username = member['value']
                elif member['key'] == CHAP_PASS_KEY:
                    password = member['value']

            if username and password:
                model_update['provider_auth'] = ('CHAP %s %s' %
                                                 (username, password))

            return model_update
        finally:
            self._logout(common)

    def _get_least_used_nsp_for_host(self, common, hostname):
        """Get the least used NSP for the current host.

        Steps to determine which NSP to use.
            * If only one iSCSI NSP, return it
            * If there is already an active vlun to this host, return its NSP
            * Return NSP with fewest active vluns
        """

        iscsi_nsps = self._get_iscsi_nsps(common)
        # If there's only one path, use it
        if len(iscsi_nsps) == 1:
            return iscsi_nsps[0]

        # Try to reuse an existing iscsi path to the host
        vluns = common.client.getVLUNs()
        for vlun in vluns['members']:
            if vlun['active']:
                if vlun['hostname'] == hostname:
                    temp_nsp = common.build_nsp(vlun['portPos'])
                    if temp_nsp in iscsi_nsps:
                        # this host already has an iscsi path, so use it
                        return temp_nsp

        # Calculate the least used iscsi nsp
        least_used_nsp = self._get_least_used_nsp(common,
                                                  vluns['members'],
                                                  self._get_iscsi_nsps(common))
        return least_used_nsp

    def _get_iscsi_nsps(self, common):
        """Return the list of candidate nsps."""
        nsps = []
        iscsi_ips = self.iscsi_ips[common._client_conf['hpe3par_api_url']]
        for value in iscsi_ips.values():
            nsps.append(value['nsp'])
        return nsps

    def _get_ip_using_nsp(self, nsp, common):
        """Return IP associated with given nsp."""
        iscsi_ips = self.iscsi_ips[common._client_conf['hpe3par_api_url']]
        for (key, value) in iscsi_ips.items():
            if value['nsp'] == nsp:
                return key

    def _get_least_used_nsp(self, common, vluns, nspss):
        """Return the nsp that has the fewest active vluns."""
        # return only the nsp (node:server:port)
        # count the number of nsps
        nsp_counts = {}
        for nsp in nspss:
            # initialize counts to zero
            nsp_counts[nsp] = 0

        current_least_used_nsp = None

        for vlun in vluns:
            if vlun['active']:
                nsp = common.build_nsp(vlun['portPos'])
                if nsp in nsp_counts:
                    nsp_counts[nsp] = nsp_counts[nsp] + 1

        # identify key (nsp) of least used nsp
        current_smallest_count = sys.maxsize
        for (nsp, count) in nsp_counts.items():
            if count < current_smallest_count:
                current_least_used_nsp = nsp
                current_smallest_count = count
        return current_least_used_nsp
