# Copyright (c) 2016 by Kaminario Technologies, Ltd.
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
"""Volume driver for Kaminario K2 all-flash arrays."""
from oslo_log import log as logging

from cinder import coordination
from cinder.i18n import _
from cinder.objects import fields
from cinder.volume.drivers.kaminario import kaminario_common as common
from cinder.volume import volume_utils
from cinder.zonemanager import utils as fczm_utils

K2_REP_FAILED_OVER = fields.ReplicationStatus.FAILED_OVER
LOG = logging.getLogger(__name__)


class KaminarioFCDriver(common.KaminarioCinderDriver):
    """Kaminario K2 FC Volume Driver.

    Version history:
        1.0 - Initial driver
        1.1 - Added manage/unmanage and extra-specs support for nodedup
        1.2 - Added replication support
        1.3 - Added retype support
        1.4 - Added replication failback support
    """

    VERSION = '1.4'

    # ThirdPartySystems wiki page name
    CI_WIKI_NAME = "Kaminario_K2_CI"

    @volume_utils.trace
    def __init__(self, *args, **kwargs):
        super(KaminarioFCDriver, self).__init__(*args, **kwargs)
        self._protocol = 'FC'
        self.lookup_service = fczm_utils.create_lookup_service()

    @volume_utils.trace
    @coordination.synchronized('{self.k2_lock_name}')
    def initialize_connection(self, volume, connector):
        """Attach K2 volume to host."""
        # Check wwpns in host connector.
        if not connector.get('wwpns'):
            msg = _("No wwpns found in host connector.")
            LOG.error(msg)
            raise common.KaminarioCinderDriverException(reason=msg)
        # To support replication failback
        temp_client = None
        if (hasattr(volume, 'replication_status') and
                volume.replication_status == K2_REP_FAILED_OVER):
            temp_client = self.client
            self.client = self.target
        # Get target wwpns.
        target_wwpns = self.get_target_info(volume)
        # Map volume.
        lun = self.k2_initialize_connection(volume, connector)
        # Create initiator-target mapping.
        target_wwpns, init_target_map = self._build_initiator_target_map(
            connector, target_wwpns)
        # To support replication failback
        if temp_client:
            self.client = temp_client
        # Return target volume information.
        conn_info = {'driver_volume_type': 'fibre_channel',
                     'data': {"target_discovered": True,
                              "target_lun": lun,
                              "target_wwn": target_wwpns,
                              "initiator_target_map": init_target_map}}
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def get_hostname_initiator_pwwn(self, volume):
        init_host = None
        init_host_name = ""
        init_pwwn = []
        vol_map_rs = self.client.search("mappings", {"volume": volume})
        if hasattr(vol_map_rs, "hits") and vol_map_rs.total != 0:
            init_host = vol_map_rs.hits[0].host
            init_host_name = init_host.name
        if init_host is not None:
            host_fc_ports = self.client.search("host_fc_ports", host=init_host)
            if hasattr(host_fc_ports, "hits") and host_fc_ports.total != 0:
                for port in host_fc_ports.hits:
                    if port.pwwn:
                        init_pwwn.append((port.pwwn).replace(':', ''))
        return init_host_name, init_pwwn

    @volume_utils.trace
    @coordination.synchronized('{self.k2_lock_name}')
    def terminate_connection(self, volume, connector, **kwargs):
        if connector is None:
            host_name, init_pwwn = self.get_hostname_initiator_pwwn(volume)
        else:
            host_name = self.get_initiator_host_name(connector)

        # To support replication failback
        temp_client = None
        if (hasattr(volume, 'replication_status') and
                volume.replication_status == K2_REP_FAILED_OVER):
            temp_client = self.client
            self.client = self.target
        super(KaminarioFCDriver, self).terminate_connection(volume, connector)
        properties = {"driver_volume_type": "fibre_channel", "data": {}}
        host_rs = self.client.search("hosts", name=host_name)
        # In terminate_connection, host_entry is deleted if host
        # is not attached to any volume
        if host_rs.total == 0:
            # Get target wwpns.
            target_wwpns = self.get_target_info(volume)
            if connector is None:
                connector = {'wwpns': init_pwwn}
            target_wwpns, init_target_map = self._build_initiator_target_map(
                connector, target_wwpns)
            properties["data"] = {"target_wwn": target_wwpns,
                                  "initiator_target_map": init_target_map}
            fczm_utils.remove_fc_zone(properties)

        # To support replication failback
        if temp_client:
            self.client = temp_client
        return properties

    def get_target_info(self, volume):
        LOG.debug("Searching target wwpns in K2.")
        fc_ports_rs = self.client.search("system/fc_ports")
        target_wwpns = []
        if hasattr(fc_ports_rs, 'hits') and fc_ports_rs.total != 0:
            for port in fc_ports_rs.hits:
                if port.pwwn:
                    target_wwpns.append((port.pwwn).replace(':', ''))
        if not target_wwpns:
            msg = _("Unable to get FC target wwpns from K2.")
            LOG.error(msg)
            raise common.KaminarioCinderDriverException(reason=msg)
        return target_wwpns

    @volume_utils.trace
    def _get_host_object(self, connector):
        host_name = self.get_initiator_host_name(connector)
        LOG.debug("Searching initiator hostname: %s in K2.", host_name)
        host_rs = self.client.search("hosts", name=host_name)
        host_wwpns = connector['wwpns']
        if host_rs.total == 0:
            try:
                LOG.debug("Creating initiator hostname: %s in K2.", host_name)
                host = self.client.new("hosts", name=host_name,
                                       type="Linux").save()
            except Exception as ex:
                LOG.exception("Unable to create host : %s in K2.",
                              host_name)
                raise common.KaminarioCinderDriverException(reason=ex)
        else:
            # Use existing host.
            LOG.debug("Use existing initiator hostname: %s in K2.", host_name)
            host = host_rs.hits[0]
        # Adding host wwpn.
        for wwpn in host_wwpns:
            wwpn = ":".join([wwpn[i:i + 2] for i in range(0, len(wwpn), 2)])
            if self.client.search("host_fc_ports", pwwn=wwpn,
                                  host=host).total == 0:
                LOG.debug("Adding wwpn: %(wwpn)s to host: "
                          "%(host)s in K2.", {'wwpn': wwpn,
                                              'host': host_name})
                try:
                    self.client.new("host_fc_ports", pwwn=wwpn,
                                    host=host).save()
                except Exception as ex:
                    if host_rs.total == 0:
                        self._delete_host_by_name(host_name)
                    LOG.exception("Unable to add wwpn : %(wwpn)s to "
                                  "host: %(host)s in K2.",
                                  {'wwpn': wwpn, 'host': host_name})
                    raise common.KaminarioCinderDriverException(reason=ex)
        return host, host_rs, host_name

    def _build_initiator_target_map(self, connector, all_target_wwns):
        """Build the target_wwns and the initiator target map."""
        target_wwns = []
        init_targ_map = {}

        if self.lookup_service is not None:
            # use FC san lookup.
            dev_map = self.lookup_service.get_device_mapping_from_network(
                connector.get('wwpns'),
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
            target_wwns = list(set(target_wwns))
        else:
            initiator_wwns = connector.get('wwpns', [])
            target_wwns = all_target_wwns

            for initiator in initiator_wwns:
                init_targ_map[initiator] = target_wwns

        return target_wwns, init_targ_map
