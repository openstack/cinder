# Copyright (c) 2020 Dell Inc. or its subsidiaries.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Adapter for Dell EMC PowerStore Cinder driver."""

from oslo_log import log as logging
from oslo_utils import strutils

from cinder import coordination
from cinder import exception
from cinder.i18n import _
from cinder.objects import fields
from cinder.objects.group_snapshot import GroupSnapshot
from cinder.objects.snapshot import Snapshot
from cinder.volume.drivers.dell_emc.powerstore import client
from cinder.volume.drivers.dell_emc.powerstore import utils
from cinder.volume import manager
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
PROTOCOL_FC = "FC"
PROTOCOL_ISCSI = "iSCSI"
CHAP_MODE_SINGLE = "Single"


class CommonAdapter(object):
    def __init__(self,
                 backend_id,
                 backend_name,
                 ports,
                 **client_config):
        if isinstance(ports, str):
            ports = ports.split(",")
        self.allowed_ports = [port.strip().lower() for port in ports]
        self.backend_id = backend_id
        self.backend_name = backend_name
        self.client = client.PowerStoreClient(**client_config)
        self.storage_protocol = None
        self.use_chap_auth = False

    @staticmethod
    def initiators(connector):
        raise NotImplementedError

    def _port_is_allowed(self, port):
        """Check if port is in allowed ports list.

        If allowed ports are empty then all ports are allowed.

        :param port: iSCSI IP/FC WWN to check
        :return: is port allowed
        """

        if not self.allowed_ports:
            return True
        return port.lower() in self.allowed_ports

    def _get_connection_properties(self, volume_lun):
        raise NotImplementedError

    def check_for_setup_error(self):
        self.client.check_for_setup_error()
        if self.storage_protocol == PROTOCOL_ISCSI:
            chap_config = self.client.get_chap_config()
            if chap_config.get("mode") == CHAP_MODE_SINGLE:
                self.use_chap_auth = True
        LOG.debug("Successfully initialized PowerStore %(protocol)s adapter "
                  "for %(backend_id)s %(backend_name)s backend. "
                  "Allowed ports: %(allowed_ports)s. "
                  "Use CHAP authentication: %(use_chap_auth)s.",
                  {
                      "protocol": self.storage_protocol,
                      "backend_id": self.backend_id,
                      "backend_name": self.backend_name,
                      "allowed_ports": self.allowed_ports,
                      "use_chap_auth": self.use_chap_auth,
                  })

    def create_volume(self, volume):
        group_provider_id = None
        if (
                volume.group_id and
                volume_utils.is_group_a_cg_snapshot_type(volume.group)
        ):
            if volume.is_replicated():
                msg = _("Volume with enabled replication can not be added to "
                        "PowerStore volume group.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
            group_provider_id = self.client.get_vg_id_by_name(
                volume.group_id
            )
        if volume.is_replicated():
            pp_name = utils.get_protection_policy_from_volume(volume)
            pp_id = self.client.get_protection_policy_id_by_name(pp_name)
            replication_status = fields.ReplicationStatus.ENABLED
        else:
            pp_name = None
            pp_id = None
            replication_status = fields.ReplicationStatus.DISABLED
        LOG.debug("Create PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s. "
                  "Protection policy: %(pp_name)s. "
                  "Volume group id: %(group_id)s. ",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "pp_name": pp_name,
                      "group_id": volume.group_id,
                  })
        size_in_bytes = utils.gib_to_bytes(volume.size)
        provider_id = self.client.create_volume(volume.name,
                                                size_in_bytes,
                                                pp_id,
                                                group_provider_id)
        LOG.debug("Successfully created PowerStore volume %(volume_name)s of "
                  "size %(volume_size)s GiB with id %(volume_id)s on "
                  "Protection policy: %(pp_name)s. "
                  "Volume group id: %(group_id)s. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "pp_name": pp_name,
                      "group_id": volume.group_id,
                      "volume_provider_id": provider_id,
                  })
        return {
            "provider_id": provider_id,
            "replication_status": replication_status,
        }

    def delete_volume(self, volume):
        try:
            provider_id = self._get_volume_provider_id(volume)
        except exception.VolumeBackendAPIException:
            provider_id = None
        if not provider_id:
            LOG.warning("Volume %(volume_name)s with id %(volume_id)s "
                        "does not have provider_id thus does not "
                        "map to PowerStore volume.",
                        {
                            "volume_name": volume.name,
                            "volume_id": volume.id,
                        })
            return
        LOG.debug("Delete PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": provider_id,
                  })
        self._detach_volume_from_hosts(volume)
        self.client.delete_volume_or_snapshot(provider_id)
        LOG.debug("Successfully deleted PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": provider_id,
                  })

    def extend_volume(self, volume, new_size):
        provider_id = self._get_volume_provider_id(volume)
        LOG.debug("Extend PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s to "
                  "%(volume_new_size)s GiB. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "volume_new_size": new_size,
                      "volume_provider_id": provider_id,
                  })
        size_in_bytes = utils.gib_to_bytes(new_size)
        self.client.extend_volume(provider_id, size_in_bytes)
        LOG.debug("Successfully extended PowerStore volume %(volume_name)s "
                  "of size %(volume_size)s GiB with id "
                  "%(volume_id)s to %(volume_new_size)s GiB. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "volume_new_size": new_size,
                      "volume_provider_id": provider_id,
                  })

    def create_snapshot(self, snapshot):
        volume_provider_id = self._get_volume_provider_id(snapshot.volume)
        LOG.debug("Create PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume %(volume_name)s with id "
                  "%(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "volume_provider_id": volume_provider_id,
                  })
        self.client.create_snapshot(volume_provider_id, snapshot.name)
        LOG.debug("Successfully created PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "volume_provider_id": volume_provider_id,
                  })

    def delete_snapshot(self, snapshot):
        try:
            volume_provider_id = self._get_volume_provider_id(snapshot.volume)
        except exception.VolumeBackendAPIException:
            return
        LOG.debug("Delete PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "volume_provider_id": volume_provider_id,
                  })
        try:
            snapshot_provider_id = self.client.get_snapshot_id_by_name(
                volume_provider_id,
                snapshot.name
            )
        except exception.VolumeBackendAPIException:
            return
        self.client.delete_volume_or_snapshot(snapshot_provider_id,
                                              entity="snapshot")
        LOG.debug("Successfully deleted PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "volume_provider_id": volume_provider_id,
                  })

    def initialize_connection(self, volume, connector, **kwargs):
        connection_properties = self._connect_volume(volume, connector)
        LOG.debug("Connection properties for volume %(volume_name)s with id "
                  "%(volume_id)s: %(connection_properties)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "connection_properties": strutils.mask_password(
                          connection_properties
                      ),
                  })
        return connection_properties

    def terminate_connection(self, volume, connector, **kwargs):
        self._disconnect_volume(volume, connector)
        return {}

    def update_volume_stats(self):
        stats = {
            "volume_backend_name": self.backend_name,
            "storage_protocol": self.storage_protocol,
            "thick_provisioning_support": False,
            "thin_provisioning_support": True,
            "compression_support": True,
            "multiattach": True,
            "consistent_group_snapshot_enabled": True,
        }
        backend_stats = self.client.get_metrics()
        backend_total_capacity = utils.bytes_to_gib(
            backend_stats["physical_total"]
        )
        backend_free_capacity = (
            backend_total_capacity -
            utils.bytes_to_gib(backend_stats["physical_used"])
        )
        stats["total_capacity_gb"] = backend_total_capacity
        stats["free_capacity_gb"] = backend_free_capacity
        LOG.debug("Free capacity for backend '%(backend)s': "
                  "%(free)s GiB, total capacity: %(total)s GiB.",
                  {
                      "backend": self.backend_name,
                      "free": backend_free_capacity,
                      "total": backend_total_capacity,
                  })
        return stats

    def create_volume_from_source(self, volume, source):
        if isinstance(source, Snapshot):
            entity = "snapshot"
            source_size = source.volume_size
            source_volume_provider_id = self._get_volume_provider_id(
                source.volume
            )
            source_provider_id = self.client.get_snapshot_id_by_name(
                source_volume_provider_id,
                source.name
            )
        else:
            entity = "volume"
            source_size = source.size
            source_provider_id = self._get_volume_provider_id(source)
        if volume.is_replicated():
            pp_name = utils.get_protection_policy_from_volume(volume)
            pp_id = self.client.get_protection_policy_id_by_name(pp_name)
            replication_status = fields.ReplicationStatus.ENABLED
        else:
            pp_name = None
            pp_id = None
            replication_status = fields.ReplicationStatus.DISABLED
        LOG.debug("Create PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s from %(entity)s "
                  "%(entity_name)s with id %(entity_id)s. "
                  "Protection policy: %(pp_name)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_size": volume.size,
                      "entity": entity,
                      "entity_name": source.name,
                      "entity_id": source.id,
                      "pp_name": pp_name,
                  })
        volume_provider_id = self.client.clone_volume_or_snapshot(
            volume.name,
            source_provider_id,
            pp_id,
            entity
        )
        if volume.size > source_size:
            size_in_bytes = utils.gib_to_bytes(volume.size)
            self.client.extend_volume(volume_provider_id, size_in_bytes)
        LOG.debug("Successfully created PowerStore volume %(volume_name)s "
                  "of size %(volume_size)s GiB with id %(volume_id)s from "
                  "%(entity)s %(entity_name)s with id %(entity_id)s. "
                  "Protection policy %(pp_name)s. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_size": volume.size,
                      "entity": entity,
                      "entity_name": source.name,
                      "entity_id": source.id,
                      "pp_name": pp_name,
                      "volume_provider_id": volume_provider_id,
                  })
        return {
            "provider_id": volume_provider_id,
            "replication_status": replication_status,
        }

    def _filter_hosts_by_initiators(self, initiators):
        """Filter hosts by given list of initiators.

        If initiators are added to different hosts the exception will be
        raised. In this case one of the hosts should be deleted.

        :param initiators: list of initiators
        :return: PowerStore host object
        """

        LOG.debug("Query PowerStore %(protocol)s hosts.",
                  {
                      "protocol": self.storage_protocol,
                  })
        hosts = self.client.get_all_hosts(self.storage_protocol)
        hosts_found = utils.filter_hosts_by_initiators(hosts, initiators)
        if hosts_found:
            if len(hosts_found) > 1:
                hosts_names_found = [host["name"] for host in hosts_found]
                msg = (_("Initiators are added to different PowerStore hosts: "
                         "%(hosts_names_found)s. Remove all of the hosts "
                         "except one to proceed. Initiators will be modified "
                         "during the next volume attach procedure.")
                       % {"hosts_names_found": hosts_names_found, })
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            else:
                return hosts_found[0]

    @coordination.synchronized("powerstore-create-host")
    def _create_host_if_not_exist(self, connector):
        """Create PowerStore host if it does not exist.

        :param connector: connection properties
        :return: PowerStore host object, iSCSI CHAP credentials
        """

        initiators = self.initiators(connector)
        host = self._filter_hosts_by_initiators(initiators)
        if self.use_chap_auth:
            chap_credentials = utils.get_chap_credentials()
        else:
            chap_credentials = {}
        if host:
            self._modify_host_initiators(host, chap_credentials, initiators)
        else:
            host_name = utils.powerstore_host_name(
                connector,
                self.storage_protocol
            )
            LOG.debug("Create PowerStore host %(host_name)s. "
                      "Initiators: %(initiators)s.",
                      {
                          "host_name": host_name,
                          "initiators": initiators,
                      })
            ports = [
                {
                    "port_name": initiator,
                    "port_type": self.storage_protocol,
                    **chap_credentials,
                } for initiator in initiators
            ]
            host = self.client.create_host(host_name, ports)
            host["name"] = host_name
            LOG.debug("Successfully created PowerStore host %(host_name)s. "
                      "Initiators: %(initiators)s. PowerStore host id: "
                      "%(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators": initiators,
                          "host_provider_id": host["id"],
                      })
        return host, chap_credentials

    def _modify_host_initiators(self, host, chap_credentials, initiators):
        """Update PowerStore host initiators if needed.

        :param host: PowerStore host object
        :param chap_credentials: iSCSI CHAP credentials
        :param initiators: list of initiators
        :return: None
        """

        initiators_added = [
            initiator["port_name"] for initiator in host["host_initiators"]
        ]
        initiators_to_add = []
        initiators_to_modify = []
        initiators_to_remove = [
            initiator for initiator in initiators_added
            if initiator not in initiators
        ]
        for initiator in initiators:
            initiator_add_modify = {
                "port_name": initiator,
                **chap_credentials,
            }
            if initiator not in initiators_added:
                initiator_add_modify["port_type"] = self.storage_protocol
                initiators_to_add.append(initiator_add_modify)
            elif self.use_chap_auth:
                initiators_to_modify.append(initiator_add_modify)
        if initiators_to_remove:
            LOG.debug("Remove initiators from PowerStore host %(host_name)s. "
                      "Initiators: %(initiators_to_remove)s. "
                      "PowerStore host id: %(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_remove": initiators_to_remove,
                          "host_provider_id": host["id"],
                      })
            self.client.modify_host_initiators(
                host["id"],
                remove_initiators=initiators_to_remove
            )
            LOG.debug("Successfully removed initiators from PowerStore host "
                      "%(host_name)s. Initiators: %(initiators_to_remove)s. "
                      "PowerStore host id: %(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_remove": initiators_to_remove,
                          "host_provider_id": host["id"],
                      })
        if initiators_to_add:
            LOG.debug("Add initiators to PowerStore host %(host_name)s. "
                      "Initiators: %(initiators_to_add)s. PowerStore host id: "
                      "%(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_add": strutils.mask_password(
                              initiators_to_add
                          ),
                          "host_provider_id": host["id"],
                      })
            self.client.modify_host_initiators(
                host["id"],
                add_initiators=initiators_to_add
            )
            LOG.debug("Successfully added initiators to PowerStore host "
                      "%(host_name)s. Initiators: %(initiators_to_add)s. "
                      "PowerStore host id: %(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_add": strutils.mask_password(
                              initiators_to_add
                          ),
                          "host_provider_id": host["id"],
                      })
        if initiators_to_modify:
            LOG.debug("Modify initiators of PowerStore host %(host_name)s. "
                      "Initiators: %(initiators_to_modify)s. "
                      "PowerStore host id: %(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_modify": strutils.mask_password(
                              initiators_to_modify
                          ),
                          "host_provider_id": host["id"],
                      })
            self.client.modify_host_initiators(
                host["id"],
                modify_initiators=initiators_to_modify
            )
            LOG.debug("Successfully modified initiators of PowerStore host "
                      "%(host_name)s. Initiators: %(initiators_to_modify)s. "
                      "PowerStore host id: %(host_provider_id)s.",
                      {
                          "host_name": host["name"],
                          "initiators_to_modify": strutils.mask_password(
                              initiators_to_modify
                          ),
                          "host_provider_id": host["id"],
                      })

    def _attach_volume_to_host(self, host, volume):
        """Attach PowerStore volume to host.

        :param host: PowerStore host object
        :param volume: OpenStack volume object
        :return: attached volume logical number
        """

        provider_id = self._get_volume_provider_id(volume)
        LOG.debug("Attach PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s to host %(host_name)s. PowerStore volume id: "
                  "%(volume_provider_id)s, host id: %(host_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "host_name": host["name"],
                      "volume_provider_id": provider_id,
                      "host_provider_id": host["id"],
                  })
        self.client.attach_volume_to_host(host["id"], provider_id)
        volume_lun = self.client.get_volume_lun(host["id"], provider_id)
        LOG.debug("Successfully attached PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s to host %(host_name)s. "
                  "PowerStore volume id: %(volume_provider_id)s, "
                  "host id: %(host_provider_id)s. Volume LUN: "
                  "%(volume_lun)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "host_name": host["name"],
                      "volume_provider_id": provider_id,
                      "host_provider_id": host["id"],
                      "volume_lun": volume_lun,
                  })
        return volume_lun

    def _create_host_and_attach(self, connector, volume):
        """Create PowerStore host and attach volume.

        :param connector: connection properties
        :param volume: OpenStack volume object
        :return: iSCSI CHAP credentials, volume logical number
        """

        host, chap_credentials = self._create_host_if_not_exist(connector)
        return chap_credentials, self._attach_volume_to_host(host, volume)

    def _connect_volume(self, volume, connector):
        """Attach PowerStore volume and return it's connection properties.

        :param volume: OpenStack volume object
        :param connector: connection properties
        :return: volume connection properties
        """

        chap_credentials, volume_lun = self._create_host_and_attach(
            connector,
            volume
        )
        connection_properties = self._get_connection_properties(volume_lun)
        if self.use_chap_auth:
            connection_properties["data"]["auth_method"] = "CHAP"
            connection_properties["data"]["auth_username"] = (
                chap_credentials.get("chap_single_username")
            )
            connection_properties["data"]["auth_password"] = (
                chap_credentials.get("chap_single_password")
            )
        return connection_properties

    def _detach_volume_from_hosts(self, volume, hosts_to_detach=None):
        """Detach volume from PowerStore hosts.

        If hosts_to_detach is None, detach volume from all hosts.

        :param volume: OpenStack volume object
        :param hosts_to_detach: list of hosts to detach from
        :return: None
        """

        provider_id = self._get_volume_provider_id(volume)
        if hosts_to_detach is None:
            # Force detach. Get all mapped hosts and detach.
            hosts_to_detach = self.client.get_volume_mapped_hosts(provider_id)
        if not hosts_to_detach:
            # Volume is not attached to any host.
            return
        LOG.debug("Detach PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s from hosts. PowerStore volume id: "
                  "%(volume_provider_id)s, hosts ids: %(hosts_provider_ids)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": provider_id,
                      "hosts_provider_ids": hosts_to_detach,
                  })
        for host_id in hosts_to_detach:
            self.client.detach_volume_from_host(host_id, provider_id)
        LOG.debug("Successfully detached PowerStore volume "
                  "%(volume_name)s with id %(volume_id)s from hosts. "
                  "PowerStore volume id: %(volume_provider_id)s, "
                  "hosts ids: %(hosts_provider_ids)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": provider_id,
                      "hosts_provider_ids": hosts_to_detach,
                  })

    def _disconnect_volume(self, volume, connector):
        """Detach PowerStore volume.

        :param volume: OpenStack volume object
        :param connector: connection properties
        :return: None
        """

        if connector is None:
            self._detach_volume_from_hosts(volume)
        else:
            is_multiattached = utils.is_multiattached_to_host(
                volume.volume_attachment,
                connector["host"]
            )
            if is_multiattached:
                # Do not detach volume until it is attached to more than one
                # instance on the same host.
                return
            initiators = self.initiators(connector)
            host = self._filter_hosts_by_initiators(initiators)
            if host:
                self._detach_volume_from_hosts(volume, [host["id"]])

    def revert_to_snapshot(self, volume, snapshot):
        volume_provider_id = self._get_volume_provider_id(volume)
        snapshot_volume_provider_id = self._get_volume_provider_id(
            snapshot.volume
        )
        LOG.debug("Restore PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s from snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_provider_id": volume_provider_id,
                  })
        snapshot_provider_id = self.client.get_snapshot_id_by_name(
            snapshot_volume_provider_id,
            snapshot.name
        )
        self.client.restore_from_snapshot(volume_provider_id,
                                          snapshot_provider_id)
        LOG.debug("Successfully restored PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s from snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_provider_id": volume_provider_id,
                  })

    def _get_volume_provider_id(self, volume):
        """Get provider_id for volume.

        If the secondary backend is used after failover operation try to get
        volume provider_id from PowerStore API.

        :param volume: OpenStack volume object
        :return: volume provider_id
        """

        if (
                self.backend_id == manager.VolumeManager.FAILBACK_SENTINEL or
                not volume.is_replicated()
        ):
            return volume.provider_id
        else:
            return self.client.get_volume_id_by_name(volume.name)

    def teardown_volume_replication(self, volume):
        """Teardown replication for volume so it can be deleted.

        :param volume: OpenStack volume object
        :return: None
        """

        LOG.debug("Teardown replication for volume %(volume_name)s "
                  "with id %(volume_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                  })
        try:
            provider_id = self._get_volume_provider_id(volume)
            rep_session_id = self.client.get_volume_replication_session_id(
                provider_id
            )
        except exception.VolumeBackendAPIException:
            LOG.warning("Replication session for volume %(volume_name)s with "
                        "id %(volume_id)s is not found. Replication for "
                        "volume was not configured or was modified from "
                        "storage side.",
                        {
                            "volume_name": volume.name,
                            "volume_id": volume.id,
                        })
            return
        self.client.unassign_volume_protection_policy(provider_id)
        self.client.wait_for_replication_session_deletion(rep_session_id)

    def failover_host(self, volumes, groups, is_failback):
        volumes_updates = []
        groups_updates = []
        for volume in volumes:
            updates = self.failover_volume(volume, is_failback)
            if updates:
                volumes_updates.append(updates)
        return volumes_updates, groups_updates

    def failover_volume(self, volume, is_failback):
        error_status = (fields.ReplicationStatus.ERROR if is_failback else
                        fields.ReplicationStatus.FAILOVER_ERROR)
        try:
            provider_id = self._get_volume_provider_id(volume)
            rep_session_id = self.client.get_volume_replication_session_id(
                provider_id
            )
            failover_job_id = self.client.failover_volume_replication_session(
                rep_session_id,
                is_failback
            )
            failover_success = self.client.wait_for_failover_completion(
                failover_job_id
            )
            if is_failback:
                self.client.reprotect_volume_replication_session(
                    rep_session_id
                )
        except exception.VolumeBackendAPIException:
            failover_success = False
        if not failover_success:
            return {
                "volume_id": volume.id,
                "updates": {
                    "replication_status": error_status,
                },
            }

    @utils.is_group_a_cg_snapshot_type
    def create_group(self, group):
        LOG.debug("Create PowerStore volume group %(group_name)s with id "
                  "%(group_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                  })
        self.client.create_vg(group.id)
        LOG.debug("Successfully created PowerStore volume group "
                  "%(group_name)s with id %(group_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                  })

    @utils.is_group_a_cg_snapshot_type
    def delete_group(self, group):
        LOG.debug("Delete PowerStore volume group %(group_name)s with id "
                  "%(group_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                  })
        try:
            group_provider_id = self.client.get_vg_id_by_name(
                group.id
            )
        except exception.VolumeBackendAPIException:
            return None, None
        self.client.delete_volume_or_snapshot(group_provider_id,
                                              entity="volume group")
        LOG.debug("Successfully deleted PowerStore volume group "
                  "%(group_name)s with id %(group_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                  })
        return None, None

    @utils.is_group_a_cg_snapshot_type
    def update_group(self, group, add_volumes, remove_volumes):
        volumes_to_add = []
        for volume in add_volumes:
            if volume.is_replicated():
                msg = _("Volume with enabled replication can not be added to "
                        "PowerStore volume group.")
                LOG.error(msg)
                raise exception.InvalidVolume(reason=msg)
            volumes_to_add.append(self._get_volume_provider_id(volume))
        volumes_to_remove = [
            self._get_volume_provider_id(volume) for volume in remove_volumes
        ]
        LOG.debug("Update PowerStore volume group %(group_name)s with id "
                  "%(group_id)s. Add PowerStore volumes with ids: "
                  "%(volumes_to_add)s, remove PowerStore volumes with ids: "
                  "%(volumes_to_remove)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                      "volumes_to_add": volumes_to_add,
                      "volumes_to_remove": volumes_to_remove,
                  })
        group_provider_id = self.client.get_vg_id_by_name(group.id)
        if volumes_to_add:
            self.client.add_volumes_to_vg(group_provider_id,
                                          volumes_to_add)
        if volumes_to_remove:
            self.client.remove_volumes_from_vg(group_provider_id,
                                               volumes_to_remove)
        LOG.debug("Successfully updated PowerStore volume group "
                  "%(group_name)s with id %(group_id)s. "
                  "Add PowerStore volumes with ids: %(volumes_to_add)s, "
                  "remove PowerStore volumes with ids: %(volumes_to_remove)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                      "volumes_to_add": volumes_to_add,
                      "volumes_to_remove": volumes_to_remove,
                  })
        return None, None, None

    @utils.is_group_a_cg_snapshot_type
    def create_group_snapshot(self, group_snapshot):
        LOG.debug("Create PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume group %(group_name)s with id "
                  "%(group_id)s.",
                  {
                      "snapshot_name": group_snapshot.name,
                      "snapshot_id": group_snapshot.id,
                      "group_name": group_snapshot.group.name,
                      "group_id": group_snapshot.group.id,
                  })
        group_provider_id = self.client.get_vg_id_by_name(
            group_snapshot.group.id
        )
        self.client.create_vg_snapshot(
            group_provider_id,
            group_snapshot.id
        )
        LOG.debug("Successfully created PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume group %(group_name)s "
                  "with id %(group_id)s.",
                  {
                      "snapshot_name": group_snapshot.name,
                      "snapshot_id": group_snapshot.id,
                      "group_name": group_snapshot.group.name,
                      "group_id": group_snapshot.group.id,
                  })
        return None, None

    @utils.is_group_a_cg_snapshot_type
    def delete_group_snapshot(self, group_snapshot):
        LOG.debug("Delete PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume group %(group_name)s with "
                  "id %(group_id)s.",
                  {
                      "snapshot_name": group_snapshot.name,
                      "snapshot_id": group_snapshot.id,
                      "group_name": group_snapshot.group.name,
                      "group_id": group_snapshot.group.id,
                  })
        try:
            group_provider_id = self.client.get_vg_id_by_name(
                group_snapshot.group.id
            )
            group_snapshot_provider_id = (
                self.client.get_vg_snapshot_id_by_name(
                    group_provider_id,
                    group_snapshot.id
                ))
        except exception.VolumeBackendAPIException:
            return None, None
        self.client.delete_volume_or_snapshot(group_snapshot_provider_id,
                                              entity="volume group snapshot")
        LOG.debug("Successfully deleted PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume group %(group_name)s "
                  "with id %(group_id)s.",
                  {
                      "snapshot_name": group_snapshot.name,
                      "snapshot_id": group_snapshot.id,
                      "group_name": group_snapshot.group.name,
                      "group_id": group_snapshot.group.id,
                  })
        return None, None

    @utils.is_group_a_cg_snapshot_type
    def create_group_from_source(self,
                                 group,
                                 volumes,
                                 source,
                                 snapshots,
                                 source_vols):
        if isinstance(source, GroupSnapshot):
            entity = "volume group snapshot"
            group_provider_id = self.client.get_vg_id_by_name(
                source.group.id
            )
            source_provider_id = self.client.get_vg_snapshot_id_by_name(
                group_provider_id,
                source.id
            )
            source_vols = [snapshot.volume for snapshot in snapshots]
            base_clone_name = "%s.%s" % (group.id, source.id)
        else:
            entity = "volume group"
            source_provider_id = self.client.get_vg_id_by_name(source.id)
            base_clone_name = group.id
        LOG.debug("Create PowerStore volume group %(group_name)s with id "
                  "%(group_id)s from %(entity)s %(entity_name)s with id "
                  "%(entity_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                      "entity": entity,
                      "entity_name": source.name,
                      "entity_id": source.id,
                  })
        self.client.clone_vg_or_vg_snapshot(
            group.id,
            source_provider_id,
            entity
        )
        LOG.debug("Successfully created PowerStore volume group "
                  "%(group_name)s with id %(group_id)s from %(entity)s "
                  "%(entity_name)s with id %(entity_id)s.",
                  {
                      "group_name": group.name,
                      "group_id": group.id,
                      "entity": entity,
                      "entity_name": source.name,
                      "entity_id": source.id,
                  })
        updates = []
        for volume, source_vol in zip(volumes, source_vols):
            volume_name = "%s.%s" % (base_clone_name, source_vol.name)
            volume_provider_id = self.client.get_volume_id_by_name(volume_name)
            self.client.rename_volume(volume_provider_id, volume.name)
            volume_updates = {
                "id": volume.id,
                "provider_id": volume_provider_id,
                "replication_status": group.replication_status,
            }
            updates.append(volume_updates)
        return None, updates


class FibreChannelAdapter(CommonAdapter):
    def __init__(self, **kwargs):
        super(FibreChannelAdapter, self).__init__(**kwargs)
        self.storage_protocol = PROTOCOL_FC
        self.driver_volume_type = "fibre_channel"

    @staticmethod
    def initiators(connector):
        return utils.extract_fc_wwpns(connector)

    def _get_fc_targets(self):
        """Get available FC WWNs.

        :return: list of FC WWNs
        """

        wwns = []
        fc_ports = self.client.get_fc_port()
        for port in fc_ports:
            if self._port_is_allowed(port["wwn"]):
                wwns.append(utils.fc_wwn_to_string(port["wwn"]))
        if not wwns:
            msg = _("There are no accessible Fibre Channel targets on the "
                    "system.")
            raise exception.VolumeBackendAPIException(data=msg)
        return wwns

    def _get_connection_properties(self, volume_lun):
        """Fill connection properties dict with data to attach volume.

        :param volume_lun: attached volume logical unit number
        :return: connection properties
        """

        target_wwns = self._get_fc_targets()
        return {
            "driver_volume_type": self.driver_volume_type,
            "data": {
                "target_discovered": False,
                "target_lun": volume_lun,
                "target_wwn": target_wwns,
            }
        }


class iSCSIAdapter(CommonAdapter):
    def __init__(self, **kwargs):
        super(iSCSIAdapter, self).__init__(**kwargs)
        self.storage_protocol = PROTOCOL_ISCSI
        self.driver_volume_type = "iscsi"

    @staticmethod
    def initiators(connector):
        return [connector["initiator"]]

    def _get_iscsi_targets(self):
        """Get available iSCSI portals and IQNs.

        :return: iSCSI portals and IQNs
        """

        iqns = []
        portals = []
        ip_pool_addresses = self.client.get_ip_pool_address()
        for address in ip_pool_addresses:
            if self._port_is_allowed(address["address"]):
                portals.append(
                    utils.iscsi_portal_with_port(address["address"])
                )
                iqns.append(address["ip_port"]["target_iqn"])
        if not portals:
            msg = _("There are no accessible iSCSI targets on the "
                    "system.")
            raise exception.VolumeBackendAPIException(data=msg)
        return iqns, portals

    def _get_connection_properties(self, volume_lun):
        """Fill connection properties dict with data to attach volume.

        :param volume_lun: attached volume logical unit number
        :return: connection properties
        """

        iqns, portals = self._get_iscsi_targets()
        return {
            "driver_volume_type": self.driver_volume_type,
            "data": {
                "target_discovered": False,
                "target_portal": portals[0],
                "target_iqn": iqns[0],
                "target_lun": volume_lun,
                "target_portals": portals,
                "target_iqns": iqns,
                "target_luns": [volume_lun] * len(portals),
            },
        }
