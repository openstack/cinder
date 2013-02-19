# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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
on the 3PAR array. Set the following in the cinder.conf file to enable the
3PAR Fibre Channel Driver along with the required flags:

volume_driver=cinder.volume.drivers.san.hp.hp_3par_fc.HP3PARFCDriver
"""

from hp3parclient import client
from hp3parclient import exceptions as hpexceptions

from cinder import exception
from cinder import flags
from cinder.openstack.common import cfg
from cinder.openstack.common import lockutils
from cinder.openstack.common import log as logging
import cinder.volume.driver
from cinder.volume.drivers.san.hp.hp_3par_common import HP3PARCommon

VERSION = 1.0
LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS


class HP3PARFCDriver(cinder.volume.driver.FibreChannelDriver):
    """OpenStack Fibre Channel driver to enable 3PAR storage array.

    Version history:
        1.0 - Initial driver

    """

    def __init__(self, *args, **kwargs):
        super(HP3PARFCDriver, self).__init__(*args, **kwargs)
        self.client = None
        self.common = None

    def _init_common(self):
        return HP3PARCommon()

    def _check_flags(self):
        """Sanity check to ensure we have required options set."""
        required_flags = ['hp3par_api_url', 'hp3par_username',
                          'hp3par_password',
                          'san_ip', 'san_login', 'san_password']
        self.common.check_flags(FLAGS, required_flags)

    def _create_client(self):
        return client.HP3ParClient(FLAGS.hp3par_api_url)

    def get_volume_stats(self, refresh):
        stats = self.common.get_volume_stats(refresh, self.client)
        stats['storage_protocol'] = 'FC'
        stats['volume_backend_name'] = 'HP3PARFCDriver'
        return stats

    def do_setup(self, context):
        self.common = self._init_common()
        self._check_flags()
        self.client = self._create_client()
        if FLAGS.hp3par_debug:
            self.client.debug_rest(True)

        try:
            LOG.debug("Connecting to 3PAR")
            self.client.login(FLAGS.hp3par_username, FLAGS.hp3par_password)
        except hpexceptions.HTTPUnauthorized as ex:
            LOG.warning("Failed to connect to 3PAR (%s) because %s" %
                       (FLAGS.hp3par_api_url, str(ex)))
            msg = _("Login to 3PAR array invalid")
            raise exception.InvalidInput(reason=msg)

        # make sure the CPG exists
        try:
            cpg = self.client.getCPG(FLAGS.hp3par_cpg)
        except hpexceptions.HTTPNotFound as ex:
            err = _("CPG (%s) doesn't exist on array") % FLAGS.hp3par_cpg
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

        if 'domain' not in cpg and cpg['domain'] != FLAGS.hp3par_domain:
            err = "CPG's domain '%s' and config option hp3par_domain '%s' \
must be the same" % (cpg['domain'], FLAGS.hp3par_domain)
            LOG.error(err)
            raise exception.InvalidInput(reason=err)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met."""
        self._check_flags()

    def create_volume(self, volume):
        """ Create a new volume. """
        metadata = self.common.create_volume(volume, self.client, FLAGS)
        return {'metadata': metadata}

    def create_cloned_volume(self, volume, src_vref):
        """ Clone an existing volume. """
        new_vol = self.common.create_cloned_volume(volume, src_vref,
                                                   self.client, FLAGS)
        return {'metadata': new_vol}

    def delete_volume(self, volume):
        """ Delete a volume. """
        self.common.delete_volume(volume, self.client)

    def create_volume_from_snapshot(self, volume, snapshot):
        """
        Creates a volume from a snapshot.

        TODO: support using the size from the user.
        """
        self.common.create_volume_from_snapshot(volume, snapshot, self.client)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.common.create_snapshot(snapshot, self.client, FLAGS)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        self.common.delete_snapshot(snapshot, self.client)

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
        # we have to make sure we have a host
        host = self._create_host(volume, connector)

        # now that we have a host, create the VLUN
        vlun = self.common.create_vlun(volume, host, self.client)

        ports = self.common.get_ports()

        info = {'driver_volume_type': 'fibre_channel',
                'data': {'target_lun': vlun['lun'],
                         'target_discovered': True,
                         'target_wwn': ports['FC']}}
        return info

    def terminate_connection(self, volume, connector, force):
        """
        Driver entry point to unattach a volume from an instance.
        """
        self.common.delete_vlun(volume, connector, self.client)
        pass

    def _create_3par_fibrechan_host(self, hostname, wwn, domain, persona_id):
        out = self.common._cli_run('createhost -persona %s -domain %s %s %s'
                                   % (persona_id, domain,
                                      hostname, " ".join(wwn)), None)

    def _modify_3par_fibrechan_host(self, hostname, wwn):
        # when using -add, you can not send the persona or domain options
        out = self.common._cli_run('createhost -add %s %s'
                                   % (hostname, " ".join(wwn)), None)

    def _create_host(self, volume, connector):
        """
        This is a 3PAR host entry for exporting volumes
        via active VLUNs.
        """
        host = None
        hostname = self.common._safe_hostname(connector['host'])
        try:
            host = self.common._get_3par_host(hostname)
            if not host['FCPaths']:
                self._modify_3par_fibrechan_host(hostname, connector['wwpns'])
                host = self.common._get_3par_host(hostname)
        except hpexceptions.HTTPNotFound as ex:
            # get persona from the volume type extra specs
            persona_id = self.common.get_persona_type(volume)
            # host doesn't exist, we have to create it
            self._create_3par_fibrechan_host(hostname, connector['wwpns'],
                                             FLAGS.hp3par_domain, persona_id)
            host = self.common._get_3par_host(hostname)

        return host

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass
