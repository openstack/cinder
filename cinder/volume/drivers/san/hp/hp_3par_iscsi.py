# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    (c) Copyright 2012-2013 Hewlett-Packard Development Company, L.P.
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
3PAR iSCSI Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_3par_iscsi.HP3PARISCSIDriver
"""

import sys

from hp3parclient import exceptions as hpexceptions

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import utils
import cinder.volume.driver
from cinder.volume.drivers.san.hp import hp_3par_common as hpcommon
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)
DEFAULT_ISCSI_PORT = 3260


class HP3PARISCSIDriver(cinder.volume.driver.ISCSIDriver):
    """OpenStack iSCSI driver to enable 3PAR storage array.

    Version history:
        1.0   - Initial driver
        1.1   - QoS, extend volume, multiple iscsi ports, remove domain,
                session changes, faster clone, requires 3.1.2 MU2 firmware.
        1.2.0 - Updated the use of the hp3parclient to 2.0.0 and refactored
                the drivers to use the new APIs.
        1.2.1 - Synchronized extend_volume method.
        1.2.2 - Added try/finally around client login/logout.
        1.2.3 - log exceptions before raising
        1.2.4 - Fixed iSCSI active path bug #1224594
    """

    VERSION = "1.2.4"

    def __init__(self, *args, **kwargs):
        super(HP3PARISCSIDriver, self).__init__(*args, **kwargs)
        self.common = None
        self.configuration.append_config_values(hpcommon.hp3par_opts)
        self.configuration.append_config_values(san.san_opts)

    def _init_common(self):
        return hpcommon.HP3PARCommon(self.configuration)

    def _check_flags(self):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hp3par_api_url', 'hp3par_username',
                          'hp3par_password', 'san_ip', 'san_login',
                          'san_password']
        self.common.check_flags(self.configuration, required_flags)

    @utils.synchronized('3par', external=True)
    def get_volume_stats(self, refresh):
        self.common.client_login()
        try:
            stats = self.common.get_volume_stats(refresh)
            stats['storage_protocol'] = 'iSCSI'
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

        self.common.client_login()
        try:
            self.initialize_iscsi_ports()
        finally:
            self.common.client_logout()

    def initialize_iscsi_ports(self):
        # map iscsi_ip-> ip_port
        #             -> iqn
        #             -> nsp
        self.iscsi_ips = {}
        temp_iscsi_ip = {}

        # use the 3PAR ip_addr list for iSCSI configuration
        if len(self.configuration.hp3par_iscsi_ips) > 0:
            # add port values to ip_addr, if necessary
            for ip_addr in self.configuration.hp3par_iscsi_ips:
                ip = ip_addr.split(':')
                if len(ip) == 1:
                    temp_iscsi_ip[ip_addr] = {'ip_port': DEFAULT_ISCSI_PORT}
                elif len(ip) == 2:
                    temp_iscsi_ip[ip[0]] = {'ip_port': ip[1]}
                else:
                    msg = _("Invalid IP address format '%s'") % ip_addr
                    LOG.warn(msg)

        # add the single value iscsi_ip_address option to the IP dictionary.
        # This way we can see if it's a valid iSCSI IP. If it's not valid,
        # we won't use it and won't bother to report it, see below
        if (self.configuration.iscsi_ip_address not in temp_iscsi_ip):
            ip = self.configuration.iscsi_ip_address
            ip_port = self.configuration.iscsi_port
            temp_iscsi_ip[ip] = {'ip_port': ip_port}

        # get all the valid iSCSI ports from 3PAR
        # when found, add the valid iSCSI ip, ip port, iqn and nsp
        # to the iSCSI IP dictionary
        iscsi_ports = self.common.get_active_iscsi_target_ports()

        for port in iscsi_ports:
            ip = port['IPAddr']
            if ip in temp_iscsi_ip:
                ip_port = temp_iscsi_ip[ip]['ip_port']
                self.iscsi_ips[ip] = {'ip_port': ip_port,
                                      'nsp': port['nsp'],
                                      'iqn': port['iSCSIName']
                                      }
                del temp_iscsi_ip[ip]

        # if the single value iscsi_ip_address option is still in the
        # temp dictionary it's because it defaults to $my_ip which doesn't
        # make sense in this context. So, if present, remove it and move on.
        if (self.configuration.iscsi_ip_address in temp_iscsi_ip):
            del temp_iscsi_ip[self.configuration.iscsi_ip_address]

        # lets see if there are invalid iSCSI IPs left in the temp dict
        if len(temp_iscsi_ip) > 0:
            msg = (_("Found invalid iSCSI IP address(s) in configuration "
                     "option(s) hp3par_iscsi_ips or iscsi_ip_address '%s.'") %
                   (", ".join(temp_iscsi_ip)))
            LOG.warn(msg)

        if not len(self.iscsi_ips) > 0:
            msg = _('At least one valid iSCSI IP address must be set.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=(msg))

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
        """Clone an existing volume."""
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
        """
        Creates a volume from a snapshot.

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

        This driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value:

            {
                'driver_volume_type': 'iscsi'
                'data': {
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
        self.common.client_login()
        try:

            # we have to make sure we have a host
            host = self._create_host(volume, connector)

            # now that we have a host, create the VLUN
            vlun = self.common.create_vlun(volume, host)

            iscsi_ip = self._get_iscsi_ip(host['name'])

            iscsi_ip_port = self.iscsi_ips[iscsi_ip]['ip_port']
            iscsi_target_iqn = self.iscsi_ips[iscsi_ip]['iqn']
            info = {'driver_volume_type': 'iscsi',
                    'data': {'target_portal': "%s:%s" %
                             (iscsi_ip, iscsi_ip_port),
                             'target_iqn': iscsi_target_iqn,
                             'target_lun': vlun['lun'],
                             'target_discovered': True
                             }
                    }
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
                                             iqn=connector['initiator'])
        finally:
            self.common.client_logout()

    def _create_3par_iscsi_host(self, hostname, iscsi_iqn, domain, persona_id):
        """Create a 3PAR host.

        Create a 3PAR host, if there is already a host on the 3par using
        the same iqn but with a different hostname, return the hostname
        used by 3PAR.
        """
        if domain is not None:
            cmd = ['createhost', '-iscsi', '-persona', persona_id, '-domain',
                   domain, hostname, iscsi_iqn]
        else:
            cmd = ['createhost', '-iscsi', '-persona', persona_id, hostname,
                   iscsi_iqn]
        out = self.common._cli_run(cmd)
        if out and len(out) > 1:
            return self.common.parse_create_host_error(hostname, out)
        return hostname

    def _modify_3par_iscsi_host(self, hostname, iscsi_iqn):
        mod_request = {'pathOperation': self.common.client.HOST_EDIT_ADD,
                       'iSCSINames': [iscsi_iqn]}

        self.common.client.modifyHost(hostname, mod_request)

    def _create_host(self, volume, connector):
        """Creates or modifies existing 3PAR host."""
        # make sure we don't have the host already
        host = None
        hostname = self.common._safe_hostname(connector['host'])
        cpg = self.common.get_cpg(volume, allowSnap=True)
        domain = self.common.get_domain(cpg)
        try:
            host = self.common._get_3par_host(hostname)
            if 'iSCSIPaths' not in host or len(host['iSCSIPaths']) < 1:
                self._modify_3par_iscsi_host(hostname, connector['initiator'])
                host = self.common._get_3par_host(hostname)
        except hpexceptions.HTTPNotFound:
            # get persona from the volume type extra specs
            persona_id = self.common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            hostname = self._create_3par_iscsi_host(hostname,
                                                    connector['initiator'],
                                                    domain,
                                                    persona_id)
            host = self.common._get_3par_host(hostname)

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

    def _get_iscsi_ip(self, hostname):
        """Get an iSCSI IP address to use.

        Steps to determine which IP address to use.
          * If only one IP address, return it
          * If there is an active vlun, return the IP associated with it
          * Return IP with fewest active vluns
        """
        if len(self.iscsi_ips) == 1:
            return self.iscsi_ips.keys()[0]

        vluns = self.common.client.getVLUNs()
        # see if there is already a path to the
        # host, if so use it
        for vlun in vluns['members']:
            if vlun['active']:
                if vlun['hostname'] == hostname:
                    # this host already has a path, so use it
                    nsp = self.common.build_nsp(vlun['portPos'])
                    return self._get_ip_using_nsp(nsp)

        # no current path find least used port
        least_used_nsp = self._get_least_used_nsp(vluns['members'],
                                                  self._get_iscsi_nsps())

        if least_used_nsp is None:
            msg = _("Least busy iSCSI port not found, "
                    "using first iSCSI port in list.")
            LOG.warn(msg)
            return self.iscsi_ips.keys()[0]

        return self._get_ip_using_nsp(least_used_nsp)

    def _get_iscsi_nsps(self):
        """Return the list of candidate nsps."""
        nsps = []
        for value in self.iscsi_ips.values():
            nsps.append(value['nsp'])
        return nsps

    def _get_ip_using_nsp(self, nsp):
        """Return IP assiciated with given nsp."""
        for (key, value) in self.iscsi_ips.items():
            if value['nsp'] == nsp:
                return key

    def _get_least_used_nsp(self, vluns, nspss):
        """"Return the nsp that has the fewest active vluns."""
        # return only the nsp (node:server:port)
        # count the number of nsps
        nsp_counts = {}
        for nsp in nspss:
            # initialize counts to zero
            nsp_counts[nsp] = 0

        current_least_used_nsp = None

        for vlun in vluns:
            if vlun['active']:
                nsp = self.common.build_nsp(vlun['portPos'])
                if nsp in nsp_counts:
                    nsp_counts[nsp] = nsp_counts[nsp] + 1

        # identify key (nsp) of least used nsp
        current_smallest_count = sys.maxint
        for (nsp, count) in nsp_counts.iteritems():
            if count < current_smallest_count:
                current_least_used_nsp = nsp
                current_smallest_count = count

        return current_least_used_nsp

    @utils.synchronized('3par', external=True)
    def extend_volume(self, volume, new_size):
        self.common.extend_volume(volume, new_size)
