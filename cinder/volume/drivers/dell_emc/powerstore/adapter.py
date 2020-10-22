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
from cinder.objects.snapshot import Snapshot
from cinder.volume.drivers.dell_emc.powerstore import client
from cinder.volume.drivers.dell_emc.powerstore import options
from cinder.volume.drivers.dell_emc.powerstore import utils
from cinder.volume import volume_utils


LOG = logging.getLogger(__name__)
PROTOCOL_FC = "FC"
PROTOCOL_ISCSI = "iSCSI"
CHAP_MODE_SINGLE = "Single"


class CommonAdapter(object):
    def __init__(self, active_backend_id, configuration):
        self.active_backend_id = active_backend_id
        self.appliances = None
        self.appliances_to_ids_map = {}
        self.client = None
        self.configuration = configuration
        self.storage_protocol = None
        self.allowed_ports = None
        self.use_chap_auth = None

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

    def _get_connection_properties(self, appliance_id, volume_lun):
        raise NotImplementedError

    def do_setup(self):
        self.appliances = (
            self.configuration.safe_get(options.POWERSTORE_APPLIANCES)
        )
        self.allowed_ports = [
            port.strip().lower() for port in
            self.configuration.safe_get(options.POWERSTORE_PORTS)
        ]
        self.client = client.PowerStoreClient(configuration=self.configuration)
        self.client.do_setup()

    def check_for_setup_error(self):
        self.client.check_for_setup_error()
        if not self.appliances:
            msg = _("PowerStore appliances must be set.")
            raise exception.VolumeBackendAPIException(data=msg)
        self.appliances_to_ids_map = {}
        for appliance_name in self.appliances:
            self.appliances_to_ids_map[appliance_name] = (
                self.client.get_appliance_id_by_name(appliance_name)
            )
        self.use_chap_auth = False
        if self.storage_protocol == PROTOCOL_ISCSI:
            chap_config = self.client.get_chap_config()
            if chap_config.get("mode") == CHAP_MODE_SINGLE:
                self.use_chap_auth = True
        LOG.debug("Successfully initialized PowerStore %(protocol)s adapter. "
                  "PowerStore appliances: %(appliances)s. "
                  "Allowed ports: %(allowed_ports)s. "
                  "Use CHAP authentication: %(use_chap_auth)s.",
                  {
                      "protocol": self.storage_protocol,
                      "appliances": self.appliances,
                      "allowed_ports": self.allowed_ports,
                      "use_chap_auth": self.use_chap_auth,
                  })

    def create_volume(self, volume):
        appliance_name = volume_utils.extract_host(volume.host, "pool")
        appliance_id = self.appliances_to_ids_map[appliance_name]
        LOG.debug("Create PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s on appliance "
                  "%(appliance_name)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "appliance_name": appliance_name,
                  })
        size_in_bytes = utils.gib_to_bytes(volume.size)
        provider_id = self.client.create_volume(appliance_id,
                                                volume.name,
                                                size_in_bytes)
        LOG.debug("Successfully created PowerStore volume %(volume_name)s of "
                  "size %(volume_size)s GiB with id %(volume_id)s on "
                  "appliance %(appliance_name)s. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "appliance_name": appliance_name,
                      "volume_provider_id": provider_id,
                  })
        return {
            "provider_id": provider_id,
        }

    def delete_volume(self, volume):
        if not volume.provider_id:
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
                      "volume_provider_id": volume.provider_id,
                  })
        self._detach_volume_from_hosts(volume)
        self.client.delete_volume_or_snapshot(volume.provider_id)
        LOG.debug("Successfully deleted PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": volume.provider_id,
                  })

    def extend_volume(self, volume, new_size):
        LOG.debug("Extend PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s to "
                  "%(volume_new_size)s GiB. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "volume_new_size": new_size,
                      "volume_provider_id": volume.provider_id,
                  })
        size_in_bytes = utils.gib_to_bytes(new_size)
        self.client.extend_volume(volume.provider_id, size_in_bytes)
        LOG.debug("Successfully extended PowerStore volume %(volume_name)s "
                  "of size %(volume_size)s GiB with id "
                  "%(volume_id)s to %(volume_new_size)s GiB. "
                  "PowerStore volume id: %(volume_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_size": volume.size,
                      "volume_id": volume.id,
                      "volume_new_size": new_size,
                      "volume_provider_id": volume.provider_id,
                  })

    def create_snapshot(self, snapshot):
        LOG.debug("Create PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume %(volume_name)s with id "
                  "%(volume_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "volume_provider_id": snapshot.volume.provider_id,
                  })
        snapshot_provider_id = self.client.create_snapshot(
            snapshot.volume.provider_id,
            snapshot.name)
        LOG.debug("Successfully created PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore snapshot id: "
                  "%(snapshot_provider_id)s, volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "snapshot_provider_id": snapshot_provider_id,
                      "volume_provider_id": snapshot.volume.provider_id,
                  })
        return {
            "provider_id": snapshot_provider_id,
        }

    def delete_snapshot(self, snapshot):
        LOG.debug("Delete PowerStore snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore snapshot id: "
                  "%(snapshot_provider_id)s, volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "snapshot_provider_id": snapshot.provider_id,
                      "volume_provider_id": snapshot.volume.provider_id,
                  })
        self.client.delete_volume_or_snapshot(snapshot.provider_id,
                                              entity="snapshot")
        LOG.debug("Successfully deleted PowerStore snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s of volume %(volume_name)s with "
                  "id %(volume_id)s. PowerStore snapshot id: "
                  "%(snapshot_provider_id)s, volume id: "
                  "%(volume_provider_id)s.",
                  {
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_name": snapshot.volume.name,
                      "volume_id": snapshot.volume.id,
                      "snapshot_provider_id": snapshot.provider_id,
                      "volume_provider_id": snapshot.volume.provider_id,
                  })

    def create_cloned_volume(self, volume, src_vref):
        LOG.debug("Clone PowerStore volume %(source_volume_name)s with id "
                  "%(source_volume_id)s to volume %(cloned_volume_name)s of "
                  "size %(cloned_volume_size)s GiB with id "
                  "%(cloned_volume_id)s. PowerStore source volume id: "
                  "%(source_volume_provider_id)s.",
                  {
                      "source_volume_name": src_vref.name,
                      "source_volume_id": src_vref.id,
                      "cloned_volume_name": volume.name,
                      "cloned_volume_size": volume.size,
                      "cloned_volume_id": volume.id,
                      "source_volume_provider_id": src_vref.provider_id,
                  })
        cloned_provider_id = self._create_volume_from_source(volume, src_vref)
        LOG.debug("Successfully cloned PowerStore volume "
                  "%(source_volume_name)s with id %(source_volume_id)s to "
                  "volume %(cloned_volume_name)s of size "
                  "%(cloned_volume_size)s GiB with id %(cloned_volume_id)s. "
                  "PowerStore source volume id: "
                  "%(source_volume_provider_id)s, "
                  "cloned volume id: %(cloned_volume_provider_id)s.",
                  {
                      "source_volume_name": src_vref.name,
                      "source_volume_id": src_vref.id,
                      "cloned_volume_name": volume.name,
                      "cloned_volume_size": volume.size,
                      "cloned_volume_id": volume.id,
                      "source_volume_provider_id": src_vref.provider_id,
                      "cloned_volume_provider_id": cloned_provider_id,
                  })
        return {
            "provider_id": cloned_provider_id,
        }

    def create_volume_from_snapshot(self, volume, snapshot):
        LOG.debug("Create PowerStore volume %(volume_name)s of size "
                  "%(volume_size)s GiB with id %(volume_id)s from snapshot "
                  "%(snapshot_name)s with id %(snapshot_id)s. PowerStore "
                  "snapshot id: %(snapshot_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_size": volume.size,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "snapshot_provider_id": snapshot.provider_id,
                  })
        volume_provider_id = self._create_volume_from_source(volume, snapshot)
        LOG.debug("Successfully created PowerStore volume %(volume_name)s "
                  "of size %(volume_size)s GiB with id %(volume_id)s from "
                  "snapshot %(snapshot_name)s with id %(snapshot_id)s. "
                  "PowerStore volume id: %(volume_provider_id)s, "
                  "snapshot id: %(snapshot_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_size": volume.size,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_provider_id": volume_provider_id,
                      "snapshot_provider_id": snapshot.provider_id,
                  })
        return {
            "provider_id": volume_provider_id,
        }

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
            "volume_backend_name": (
                self.configuration.safe_get("volume_backend_name") or
                "powerstore"
            ),
            "storage_protocol": self.storage_protocol,
            "thick_provisioning_support": False,
            "thin_provisioning_support": True,
            "compression_support": True,
            "multiattach": True,
            "pools": [],
        }
        backend_total_capacity = 0
        backend_free_capacity = 0
        for appliance_name in self.appliances:
            appliance_stats = self.client.get_appliance_metrics(
                self.appliances_to_ids_map[appliance_name]
            )
            appliance_total_capacity = utils.bytes_to_gib(
                appliance_stats["physical_total"]
            )
            appliance_free_capacity = (
                appliance_total_capacity -
                utils.bytes_to_gib(appliance_stats["physical_used"])
            )
            pool = {
                "pool_name": appliance_name,
                "total_capacity_gb": appliance_total_capacity,
                "free_capacity_gb": appliance_free_capacity,
                "thick_provisioning_support": False,
                "thin_provisioning_support": True,
                "compression_support": True,
                "multiattach": True,
            }
            backend_total_capacity += appliance_total_capacity
            backend_free_capacity += appliance_free_capacity
            stats["pools"].append(pool)
        stats["total_capacity_gb"] = backend_total_capacity
        stats["free_capacity_gb"] = backend_free_capacity
        LOG.debug("Free capacity for backend '%(backend)s': "
                  "%(free)s GiB, total capacity: %(total)s GiB.",
                  {
                      "backend": stats["volume_backend_name"],
                      "free": backend_free_capacity,
                      "total": backend_total_capacity,
                  })
        return stats

    def _create_volume_from_source(self, volume, source):
        """Create PowerStore volume from source (snapshot or another volume).

        :param volume: OpenStack volume object
        :param source: OpenStack source snapshot or volume
        :return: newly created PowerStore volume id
        """

        if isinstance(source, Snapshot):
            entity = "snapshot"
            source_size = source.volume_size
        else:
            entity = "volume"
            source_size = source.size
        volume_provider_id = self.client.clone_volume_or_snapshot(
            volume.name,
            source.provider_id,
            entity
        )
        if volume.size > source_size:
            size_in_bytes = utils.gib_to_bytes(volume.size)
            self.client.extend_volume(volume_provider_id, size_in_bytes)
        return volume_provider_id

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

        LOG.debug("Attach PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s to host %(host_name)s. PowerStore volume id: "
                  "%(volume_provider_id)s, host id: %(host_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "host_name": host["name"],
                      "volume_provider_id": volume.provider_id,
                      "host_provider_id": host["id"],
                  })
        self.client.attach_volume_to_host(host["id"], volume.provider_id)
        volume_lun = self.client.get_volume_lun(
            host["id"], volume.provider_id
        )
        LOG.debug("Successfully attached PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s to host %(host_name)s. "
                  "PowerStore volume id: %(volume_provider_id)s, "
                  "host id: %(host_provider_id)s. Volume LUN: "
                  "%(volume_lun)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "host_name": host["name"],
                      "volume_provider_id": volume.provider_id,
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

        appliance_name = volume_utils.extract_host(volume.host, "pool")
        appliance_id = self.appliances_to_ids_map[appliance_name]
        chap_credentials, volume_lun = self._create_host_and_attach(
            connector,
            volume
        )
        connection_properties = self._get_connection_properties(appliance_id,
                                                                volume_lun)
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

        if hosts_to_detach is None:
            # Force detach. Get all mapped hosts and detach.
            hosts_to_detach = self.client.get_volume_mapped_hosts(
                volume.provider_id
            )
        if not hosts_to_detach:
            # Volume is not attached to any host.
            return
        LOG.debug("Detach PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s from hosts. PowerStore volume id: "
                  "%(volume_provider_id)s, hosts ids: %(hosts_provider_ids)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": volume.provider_id,
                      "hosts_provider_ids": hosts_to_detach,
                  })
        for host_id in hosts_to_detach:
            self.client.detach_volume_from_host(host_id, volume.provider_id)
        LOG.debug("Successfully detached PowerStore volume "
                  "%(volume_name)s with id %(volume_id)s from hosts. "
                  "PowerStore volume id: %(volume_provider_id)s, "
                  "hosts ids: %(hosts_provider_ids)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "volume_provider_id": volume.provider_id,
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
        LOG.debug("Restore PowerStore volume %(volume_name)s with id "
                  "%(volume_id)s from snapshot %(snapshot_name)s with id "
                  "%(snapshot_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s, snapshot id: "
                  "%(snapshot_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_provider_id": volume.provider_id,
                      "snapshot_provider_id": snapshot.provider_id,
                  })
        self.client.restore_from_snapshot(volume.provider_id,
                                          snapshot.provider_id)
        LOG.debug("Successfully restored PowerStore volume %(volume_name)s "
                  "with id %(volume_id)s from snapshot %(snapshot_name)s "
                  "with id %(snapshot_id)s. PowerStore volume id: "
                  "%(volume_provider_id)s, snapshot id: "
                  "%(snapshot_provider_id)s.",
                  {
                      "volume_name": volume.name,
                      "volume_id": volume.id,
                      "snapshot_name": snapshot.name,
                      "snapshot_id": snapshot.id,
                      "volume_provider_id": volume.provider_id,
                      "snapshot_provider_id": snapshot.provider_id,
                  })


class FibreChannelAdapter(CommonAdapter):
    def __init__(self, active_backend_id, configuration):
        super(FibreChannelAdapter, self).__init__(active_backend_id,
                                                  configuration)
        self.storage_protocol = PROTOCOL_FC
        self.driver_volume_type = "fibre_channel"

    @staticmethod
    def initiators(connector):
        return utils.extract_fc_wwpns(connector)

    def _get_fc_targets(self, appliance_id):
        """Get available FC WWNs for PowerStore appliance.

        :param appliance_id: PowerStore appliance id
        :return: list of FC WWNs
        """

        wwns = []
        fc_ports = self.client.get_fc_port(appliance_id)
        for port in fc_ports:
            if self._port_is_allowed(port["wwn"]):
                wwns.append(utils.fc_wwn_to_string(port["wwn"]))
        if not wwns:
            msg = _("There are no accessible Fibre Channel targets on the "
                    "system.")
            raise exception.VolumeBackendAPIException(data=msg)
        return wwns

    def _get_connection_properties(self, appliance_id, volume_lun):
        """Fill connection properties dict with data to attach volume.

        :param appliance_id: PowerStore appliance id
        :param volume_lun: attached volume logical unit number
        :return: connection properties
        """

        target_wwns = self._get_fc_targets(appliance_id)
        return {
            "driver_volume_type": self.driver_volume_type,
            "data": {
                "target_discovered": False,
                "target_lun": volume_lun,
                "target_wwn": target_wwns,
            }
        }


class iSCSIAdapter(CommonAdapter):
    def __init__(self, active_backend_id, configuration):
        super(iSCSIAdapter, self).__init__(active_backend_id, configuration)
        self.storage_protocol = PROTOCOL_ISCSI
        self.driver_volume_type = "iscsi"

    @staticmethod
    def initiators(connector):
        return [connector["initiator"]]

    def _get_iscsi_targets(self, appliance_id):
        """Get available iSCSI portals and IQNs for PowerStore appliance.

        :param appliance_id: PowerStore appliance id
        :return: iSCSI portals and IQNs
        """

        iqns = []
        portals = []
        ip_pool_addresses = self.client.get_ip_pool_address(appliance_id)
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

    def _get_connection_properties(self, appliance_id, volume_lun):
        """Fill connection properties dict with data to attach volume.

        :param appliance_id: PowerStore appliance id
        :param volume_lun: attached volume logical unit number
        :return: connection properties
        """

        iqns, portals = self._get_iscsi_targets(appliance_id)
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
