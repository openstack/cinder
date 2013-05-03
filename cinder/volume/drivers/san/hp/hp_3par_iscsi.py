# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    (c) Copyright 2012-2013 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
#
#    Copyright 2012 OpenStack LLC
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
Volume driver for HP 3PAR Storage array. This driver requires 3.1.2 firmware
on the 3PAR array.

You will need to install the python hp3parclient.
sudo pip install hp3parclient

Set the following in the cinder.conf file to enable the
3PAR iSCSI Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_3par_iscsi.HP3PARISCSIDriver
"""

from hp3parclient import client
from hp3parclient import exceptions as hpexceptions

from cinder import exception
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
import cinder.volume.driver
from cinder.volume.drivers.san.hp import hp_3par_common as hpcommon
from cinder.volume.drivers.san import san

VERSION = 1.0
LOG = logging.getLogger(__name__)


class HP3PARISCSIDriver(cinder.volume.driver.ISCSIDriver):
    """OpenStack iSCSI driver to enable 3PAR storage array.

    Version history:
        1.0 - Initial driver

    """
    def __init__(self, *args, **kwargs):
        super(HP3PARISCSIDriver, self).__init__(*args, **kwargs)
        self.client = None
        self.common = None
        self.configuration.append_config_values(hpcommon.hp3par_opts)
        self.configuration.append_config_values(san.san_opts)

    def _init_common(self):
        return hpcommon.HP3PARCommon(self.configuration)

    def _check_flags(self):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hp3par_api_url', 'hp3par_username',
                          'hp3par_password', 'iscsi_ip_address',
                          'iscsi_port', 'san_ip', 'san_login',
                          'san_password']
        self.common.check_flags(self.configuration, required_flags)

    def _create_client(self):
        return client.HP3ParClient(self.configuration.hp3par_api_url)

    def get_volume_stats(self, refresh):
        stats = self.common.get_volume_stats(refresh, self.client)
        stats['storage_protocol'] = 'iSCSI'
        backend_name = self.configuration.safe_get('volume_backend_name')
        stats['volume_backend_name'] = backend_name or self.__class__.__name__
        return stats

    def do_setup(self, context):
        self.common = self._init_common()
        self._check_flags()
        self.client = self._create_client()
        if self.configuration.hp3par_debug:
            self.client.debug_rest(True)

        try:
            LOG.debug("Connecting to 3PAR")
            self.client.login(self.configuration.hp3par_username,
                              self.configuration.hp3par_password)
        except hpexceptions.HTTPUnauthorized as ex:
            LOG.warning("Failed to connect to 3PAR (%s) because %s" %
                       (self.configuration.hp3par_api_url, str(ex)))
            msg = _("Login to 3PAR array invalid")
            raise exception.InvalidInput(reason=msg)

        # make sure the CPG exists
        try:
            cpg = self.client.getCPG(self.configuration.hp3par_cpg)
        except hpexceptions.HTTPNotFound as ex:
            err = (_("CPG (%s) doesn't exist on array")
                   % self.configuration.hp3par_cpg)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        if ('domain' not in cpg and
            cpg['domain'] != self.configuration.hp3par_domain):
            err = "CPG's domain '%s' and config option hp3par_domain '%s' \
must be the same" % (cpg['domain'], self.configuration.hp3par_domain)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        # make sure ssh works.
        self._iscsi_discover_target_iqn(self.configuration.iscsi_ip_address)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_flags()

    @lockutils.synchronized('3par-vol', 'cinder-', True)
    def create_volume(self, volume):
        metadata = self.common.create_volume(volume, self.client)

        return {'provider_location': "%s:%s" %
                (self.configuration.iscsi_ip_address,
                 self.configuration.iscsi_port),
                'metadata': metadata}

    def create_cloned_volume(self, volume, src_vref):
        """ Clone an existing volume. """
        new_vol = self.common.create_cloned_volume(volume, src_vref,
                                                   self.client)
        return {'provider_location': "%s:%s" %
                (self.configuration.iscsi_ip_address,
                 self.configuration.iscsi_port),
                'metadata': new_vol}

    @lockutils.synchronized('3par-vol', 'cinder-', True)
    def delete_volume(self, volume):
        self.common.delete_volume(volume, self.client)

    @lockutils.synchronized('3par-vol', 'cinder-', True)
    def create_volume_from_snapshot(self, volume, snapshot):
        """
        Creates a volume from a snapshot.

        TODO: support using the size from the user.
        """
        self.common.create_volume_from_snapshot(volume, snapshot, self.client)

    @lockutils.synchronized('3par-snap', 'cinder-', True)
    def create_snapshot(self, snapshot):
        self.common.create_snapshot(snapshot, self.client)

    @lockutils.synchronized('3par-snap', 'cinder-', True)
    def delete_snapshot(self, snapshot):
        self.common.delete_snapshot(snapshot, self.client)

    @lockutils.synchronized('3par-attach', 'cinder-', True)
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
        # get the target_iqn on the 3par interface.
        target_iqn = self._iscsi_discover_target_iqn(
            self.configuration.iscsi_ip_address)

        # we have to make sure we have a host
        host = self._create_host(volume, connector)

        # now that we have a host, create the VLUN
        vlun = self.common.create_vlun(volume, host, self.client)

        info = {'driver_volume_type': 'iscsi',
                'data': {'target_portal': "%s:%s" %
                         (self.configuration.iscsi_ip_address,
                          self.configuration.iscsi_port),
                         'target_iqn': target_iqn,
                         'target_lun': vlun['lun'],
                         'target_discovered': True
                         }
                }
        return info

    @lockutils.synchronized('3par-attach', 'cinder-', True)
    def terminate_connection(self, volume, connector, force):
        """
        Driver entry point to unattach a volume from an instance.
        """
        self.common.delete_vlun(volume, connector, self.client)

    def _iscsi_discover_target_iqn(self, remote_ip):
        result = self.common._cli_run('showport -ids', None)

        iqn = None
        if result:
            # first line is header
            result = result[1:]
            for line in result:
                info = line.split(",")
                if info and len(info) > 2:
                    if info[1] == remote_ip:
                        iqn = info[2]

        return iqn

    def _create_3par_iscsi_host(self, hostname, iscsi_iqn, domain, persona_id):
        cmd = 'createhost -iscsi -persona %s -domain %s %s %s' % \
              (persona_id, domain, hostname, iscsi_iqn)
        out = self.common._cli_run(cmd, None)
        if out and len(out) > 1:
            if "already used by host" in out[1]:
                err = out[1].strip()
                info = _("The hostname must be called '%s'") % hostname
                raise exception.Duplicate3PARHost(err=err, info=info)

    def _modify_3par_iscsi_host(self, hostname, iscsi_iqn):
        # when using -add, you can not send the persona or domain options
        self.common._cli_run('createhost -iscsi -add %s %s'
                             % (hostname, iscsi_iqn), None)

    def _create_host(self, volume, connector):
        """
        This is a 3PAR host entry for exporting volumes
        via active VLUNs.
        """
        # make sure we don't have the host already
        host = None
        hostname = self.common._safe_hostname(connector['host'])
        try:
            host = self.common._get_3par_host(hostname)
            if not host['iSCSIPaths']:
                self._modify_3par_iscsi_host(hostname, connector['initiator'])
                host = self.common._get_3par_host(hostname)
        except hpexceptions.HTTPNotFound:
            # get persona from the volume type extra specs
            persona_id = self.common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            self._create_3par_iscsi_host(hostname, connector['initiator'],
                                         self.configuration.hp3par_domain,
                                         persona_id)
            host = self.common._get_3par_host(hostname)

        return host

    @lockutils.synchronized('3par-exp', 'cinder-', True)
    def create_export(self, context, volume):
        pass

    @lockutils.synchronized('3par-exp', 'cinder-', True)
    def ensure_export(self, context, volume):
        pass

    @lockutils.synchronized('3par-exp', 'cinder-', True)
    def remove_export(self, context, volume):
        pass
