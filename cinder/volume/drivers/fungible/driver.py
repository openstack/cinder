#    (c)  Copyright 2022 Fungible, Inc. All rights reserved.
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

"""Volume driver for Fungible Storage Cluster"""

import json
import os
import time

from oslo_config import cfg
from oslo_log import log
from oslo_utils import excutils

from cinder.common import constants as cinderconstants
from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.objects import fields
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.fungible import constants
from cinder.volume.drivers.fungible import rest_client as rest_api
from cinder.volume.drivers.fungible import swagger_api_client as swagger_client
from cinder.volume.drivers.san import san
from cinder.volume import volume_types
from cinder.volume import volume_utils

LOG = log.getLogger(__name__)

fungible_opts = [
    cfg.PortOpt('nvme_connect_port',
                default=4420,
                help='The port number to be used'
                     ' when doing nvme connect from host'),
    cfg.BoolOpt('api_enable_ssl',
                default=True,
                help='Specify whether to use SSL'
                     ' or not when accessing the composer APIs'),
    cfg.IntOpt('iops_for_image_migration',
               default=250000,
               help='Maximum read IOPS that volume can get'
                    ' when reading data from the volume during'
                    ' host assisted migration'),
    cfg.IntOpt('fsc_clone_volume_timeout',
               default=1800,
               help='Create clone volume timeout in seconds')
]
CONF = cfg.CONF
CONF.register_opts(fungible_opts)


@interface.volumedriver
class FungibleDriver(driver.BaseVD):
    """Fungible Storage driver

    Fungible driver is a volume driver for Fungible Storage.

    Version history:
        1.0.0 - First source driver version
    """

    VERSION = constants.VERSION
    CI_WIKI_NAME = "Fungible_Storage_CI"

    def __init__(self, *args, **kwargs):
        """Initialize the driver."""
        super(FungibleDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(san.san_opts)
        self.configuration.append_config_values(fungible_opts)
        self.rest_client = None
        self.use_multipath = True

    def do_setup(self, context):
        """Initial setup of driver variables"""
        self.rest_client = rest_api.RestClient(self.configuration)
        self.rest_client.do_setup()

    @staticmethod
    def get_driver_options():
        additional_opts = driver.BaseVD._get_oslo_driver_opts(
            "san_ip", "san_login", "san_password", "san_api_port"
        )
        return fungible_opts + additional_opts

    @staticmethod
    def wait_for_device(device_path):
        time.sleep(1)  # wait for a second
        time_to_wait = 4  # 4 seconds
        time_counter = 0
        while not os.path.exists(device_path):
            time.sleep(1)  # wait for a second
            time_counter += 1
            if time_counter > time_to_wait:
                break

    def check_for_setup_error(self):
        """Verify that requirements are in place to use

        Fungible Storage Backend.
        """

        try:
            # backend call for health check
            fungible_res = self.rest_client.check_for_setup_error()
            if fungible_res["status"]:
                LOG.info(
                    "Backend Storage Api Status is %(message)s",
                    {'message': fungible_res['message']})
            else:
                LOG.error(
                    "Backend api status is : %(status)s",
                    {'status': fungible_res['status']})
                raise exception.VolumeBackendAPIException(
                    data=_(
                        "Backend Storage Api Status is "
                        "%(message)s, Error Message: %(err_msg)s)")
                    % {
                        "message": fungible_res["message"],
                        "err_msg": fungible_res["error_message"]
                    }
                )
        except swagger_client.ApiException as e:
            LOG.error(
                "[check_for_setup_error]Request to BackendApi Failed -> %s",
                e.body
            )
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to get backend api status, "
                    "error message: %(error)s." %
                    {'error': error['error_message']}
                )
            )
        except Exception as e:
            LOG.error("[check_for_setup_error]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to get backend api response: %(args)s" %
                    {
                        'args': e.args
                    }
                )
            )

    @staticmethod
    def _get_volume_type_extra_specs(self, volume):
        """Get the Volume type using volume_type_id

        :param: volume object
        :return: volume type & extra specs
        """

        specs = {}
        vol_type = ""
        ctxt = context.get_admin_context()
        type_id = volume["volume_type_id"]
        if type_id:
            LOG.debug("[_get_volume_type_extra_specs]type_id=%s", type_id)
            # get volume type name by volume type id
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            LOG.debug("[_get_volume_type_extra_specs]volume_type=%s",
                      volume_type)
            specs = volume_type.get("extra_specs")
            if constants.FSC_VOL_TYPE in specs:
                vol_type = volume_type.get(
                    "extra_specs").get(constants.FSC_VOL_TYPE)
            else:
                error_msg = (
                    "Key %(type)s was not found in extraspecs" %
                    {
                        'type': constants.FSC_VOL_TYPE
                    }
                )
                LOG.error("[create_volume]Error occurred: %s", error_msg)
                raise exception.VolumeBackendAPIException(
                    data=_(
                        "Failed to create volume %(display_name)s: "
                        "%(error)s." %
                        {'error': error_msg,
                            'display_name': volume.display_name}
                    )
                )

            for key, value in specs.items():
                specs[key] = value
        return specs, vol_type

    def _get_dpu_enabled_host_list(self, ports):
        host_uuid_list = list(
            map(lambda port: port["host_uuid"], ports.values()))
        hosts = self.rest_client.get_hosts_subset(host_uuid_list)
        hosts_fac_enabled = {host["host_uuid"]:
                             host["fac_enabled"] for host in hosts}
        return hosts_fac_enabled

    def create_volume(self, volume):
        """Create volume on Fungible storage backend.

        :param volume: volume to be created
        :return: volume model updates
        """
        fungible_specs = {}
        volume_type = ""
        if "volume_type_id" in volume:
            fungible_specs, volume_type = self._get_volume_type_extra_specs(
                self, volume
            )

        # request fungible to create a volume
        try:
            fungible_res = self.rest_client.create_volume(
                volume, fungible_specs, volume_type
            )
            provider_id = fungible_res["data"]["uuid"]
            # preparing model updates dict to return
            model_updates = {"provider_id": provider_id,
                             "size": volume["size"]}
            LOG.info(
                "Volume created successfully %s. "
                "Volume size: %s. ", volume['id'], volume["size"]
            )
            return model_updates
        except swagger_client.ApiException as e:
            LOG.error(
                "[create_volume]Request to BackendApi Failed -> %s", e.body)
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create volume %(display_name)s: "
                    "%(error)s." %
                    {'error': error['error_message'],
                     'display_name': volume['display_name']}
                )
            )
        except Exception as e:
            LOG.error("[create_volume]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create volume %(name)s: %(args)s" %
                    {
                        'name': volume['display_name'],
                        'args': e.args
                    }
                )
            )

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create Volume on Fungible storage backend

        Args:
            volume: volume to be created
            snapshot: source snapshot from which the volume to be created

        Returns:: volume model updates
        """
        volume_type = ""
        fungible_specs = {}
        if "volume_type_id" in volume:
            fungible_specs, volume_type = self._get_volume_type_extra_specs(
                self, volume
            )

        # request fungible to create a volume
        try:
            fungible_res = self.rest_client.create_volume(
                volume, fungible_specs, volume_type, snapshot
            )
            provider_id = fungible_res["data"]["uuid"]
            # preparing model updates dict to return
            model_updates = {"provider_id": provider_id,
                             "size": volume["size"]}
            LOG.info(
                "Volume created from snapshot successfully with volume "
                "ID: %s. Volume size: %s. ",
                volume['id'], volume['size']
            )
            return model_updates
        except swagger_client.ApiException as e:
            LOG.error(
                "[create_volume_from_snapshot]Request to BackendApi "
                "Failed -> %s", e.body
            )
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create volume from snapshot with volume "
                    "ID: %(name)s: %(error)s." %
                    {'name': volume['display_name'],
                     'error': error['error_message']}
                )
            )
        except Exception as e:
            LOG.error("[create_volume_from_snapshot]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create volume %(name)s: %(args)s" %
                    {
                        'name': volume['display_name'],
                        'args': e.args
                    }
                )
            )

    def delete_volume(self, volume):
        """Delete the available volume

        :param volume: volume to be deleted
        :return: none
        """
        LOG.info("Request to delete volume : %s.", volume['id'])
        if "provider_id" in volume:
            if volume["provider_id"]:
                # request fungible to delete volume
                try:
                    del_res = self.rest_client.delete_volume(
                        volume["provider_id"])
                    LOG.info("Volume delete : %s.", del_res['message'])
                except swagger_client.ApiException as e:
                    LOG.error(
                        "[delete_volume]Request to BackendApi Failed -> %s",
                        e.body
                    )
                    error = json.loads(e.body)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to delete volume "
                            "{volume['display_name']}: "
                            "%(error)s." %
                            {'error': error['error_message']}
                        )
                    )
                except Exception as e:
                    LOG.error("[delete_volume]Error occurred: %s", e)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to delete volume %(name)s: %(args)s" %
                            {
                                'name': volume['display_name'],
                                'args': e.args
                            }
                        )
                    )
            else:
                LOG.info("Volume backend UUID not found in volume details.")
        else:
            raise exception.VolumeBackendAPIException(
                data=_("Failed to delete volume: %s." % volume["id"])
            )

    def create_cloned_volume(self, volume, src_vref):
        """Create volume from volume

        :param volume: volume to be created
        :param src_vref: source volume
        :return: volume model updates
        Logic:
            1. create new volume.
            2. add copy volume task.
            3. in loop check for task status
            4. delete volume copy task
        """

        snapshot_id = None
        try:
            src_volume_uuid = src_vref["provider_id"]

            # create a snapshot to copy the data from
            fungible_res = self.rest_client.create_snapshot(
                src_volume_uuid, src_volume_uuid
            )
            snapshot_id = fungible_res["data"]["uuid"]

            # create new volume.
            new_volume = self.create_volume(volume)
            new_volume_uuid = new_volume.get("provider_id")
            LOG.info(
                "[clone_volume] new volume is created."
                " volume uuid: %s", new_volume_uuid
            )
            # prepare response to return
            model_updates = {"provider_id": new_volume_uuid,
                             "size": volume["size"]}
            # add task to copy volume
            add_task_response = self.rest_client.copy_volume(
                new_volume_uuid, snapshot_id
            )

            # check task status in loop
            task_uuid = add_task_response["data"]["task_uuid"]
            LOG.info(
                "[clone_volume] Copy volume task is added. task_uuid: %s",
                task_uuid
            )
            status = "RUNNING"
            error_message = ""
            sleep_for_seconds = 1
            while status == "RUNNING":
                # Wait before checking for the task status
                # This is done to reduce number of api calls to backend
                # Wait time is increased exponentially to a maximum of 8 secs
                time.sleep(sleep_for_seconds)
                if sleep_for_seconds < 8:
                    sleep_for_seconds = sleep_for_seconds * 2
                task_response = self.rest_client.get_volume_copy_task(
                    task_uuid)
                status = task_response["data"]["task_state"]
                error_message = task_response.get("error_message")

            LOG.info(
                "[clone_volume] Copy volume task with task_uuid:"
                " %s is complete. status: %s", task_uuid, status
            )

            # delete the snapshot created for data copy
            if snapshot_id:
                fungible_res = self.rest_client.delete_snapshot(
                    snapshot_id
                )
                snapshot_id = None
                LOG.info(
                    "Snapshot deleted successfully: %s.",
                    fungible_res['message']
                )

            if status == "FAILED":
                # Delete the new volume created since the data copy failed
                del_res = self.rest_client.delete_volume(new_volume_uuid)
                LOG.info("Volume delete : %s.", del_res['message'])
                raise exception.VolumeBackendAPIException(
                    data=_(
                        "Failed to create new volume %(new_volume_uuid)s: "
                        "from source volume %(src_volume_uuid)s %(error)s." %
                        {
                            'new_volume_uuid': new_volume_uuid,
                            'src_volume_uuid': src_volume_uuid,
                            'error': error_message
                        }
                    )
                )

            try:
                self.rest_client.delete_volume_copy_task(task_uuid)
            except swagger_client.ApiException as e:
                # Just log warning as volume copy is already completed.
                LOG.warning(
                    "[clone_volume] request to delete task %s"
                    " to BackendApi Failed "
                    "-> %s", task_uuid, e.body
                )
        except swagger_client.ApiException as e:
            LOG.error("[clone_volume] request to BackendApi Failed. %s",
                      e.body)
            error = json.loads(e.body)
            # delete the snapshot created for data copy
            if snapshot_id:
                fungible_res = self.rest_client.delete_snapshot(
                    snapshot_id
                )
                snapshot_id = None
                LOG.info(
                    "Snapshot deleted successfully: %s.",
                    fungible_res['message']
                )
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create new volume %(new_volume_uuid)s: "
                    "from source volume %(src_volume_uuid)s %(error)s." %
                    {
                        'new_volume_uuid': new_volume_uuid,
                        'src_volume_uuid': src_volume_uuid,
                        'error': error['error_message']
                    }
                )
            )
        except Exception as e:
            # delete the snapshot created for data copy
            if snapshot_id:
                fungible_res = self.rest_client.delete_snapshot(
                    snapshot_id
                )
                snapshot_id = None
                LOG.info(
                    "Snapshot deleted successfully: %s.",
                    fungible_res['message']
                )
            LOG.error("[create_clone_volume]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create volume %(name)s: %(args)s" %
                    {
                        'name': volume['display_name'],
                        'args': e.args
                    }
                )
            )

        return model_updates

    def ensure_export(self, context, volume):
        pass

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def initialize_connection(self, volume, connector):
        """Initialize connection and return connection info.

        :param volume: the volume object
        :param connector: the connector object
        :return: connection info dict
        """
        # check for nqn in connector
        host_nqn = connector.get("nqn")
        if not host_nqn:
            host_name = connector.get("host")
            if host_name:
                host_nqn = "nqn.2015-09.com.host:" + host_name
        if not host_nqn:
            raise exception.VolumeBackendAPIException(
                data=_("initialize_connection error: no host nqn available!")
            )

        provider_id = volume.get("provider_id")
        LOG.info("initialize_connection - provider_id=%s", provider_id)

        if not provider_id:
            raise exception.VolumeBackendAPIException(
                data=_("initialize_connection error: no uuid available!")
            )
        try:
            img_mig_iops = False
            # high iops set to true when volume is uploading to image
            # or downloading from image
            if constants.FSC_IOPS_IMG_MIG in connector:
                img_mig_iops = connector.get(constants.FSC_IOPS_IMG_MIG)

            # high iops set to true when volume is migrating
            mig_status = [
                fields.VolumeMigrationStatus.SUCCESS,
            ]
            if volume.get("migration_status") is not None:
                if volume.get("migration_status") not in mig_status:
                    img_mig_iops = True

            # get host_uuid from the host_nqn
            LOG.info("initialize_connection - host_nqn=%s", host_nqn)
            host_uuid = self.rest_client.get_host_uuid_from_host_nqn(host_nqn)
            # create host if it does not exists
            if host_uuid is None:
                host_create_response = self.rest_client.create_host(host_nqn)
                host_uuid = host_create_response["data"]["uuid"]

            LOG.info("initialize_connection - host_uuid=%s", host_uuid)
            host = self.rest_client.get_host_details(host_uuid)

            # request composer to attach volume
            self.rest_client.attach_volume(
                uuid=provider_id,
                host_uuid=host_uuid,
                fac_enabled=host["fac_enabled"],
                iops=img_mig_iops,
            )

            if host["fac_enabled"] is False:
                volume_details = self.rest_client.get_volume_detail(
                    uuid=provider_id)

                target_nqn = volume_details.get("data").get("subsys_nqn")
                get_config_value = self.configuration.safe_get
                port = get_config_value("nvme_connect_port")

                topology_response = self.rest_client.get_topology()
                LOG.info(
                    "initialize_connection - topology_response=%s",
                    topology_response
                )

                str_portals = []
                # find primary dpu ip
                primary_dpu = volume_details.get("data").get("dpu")
                LOG.info("initialize_connection - primary_dpu=%s",
                         primary_dpu)
                if primary_dpu:
                    if topology_response["status"] is True:
                        topology_data = topology_response.get("data")
                        for device in topology_data.values():
                            for dpu in device["dpus"]:
                                if dpu["uuid"] == primary_dpu:
                                    portal_ip = str(dpu["dataplane_ip"])
                                    portal_port = str(port)
                                    portal_transport = "tcp"
                                    str_portals.append(
                                        (
                                            portal_ip,
                                            portal_port,
                                            portal_transport
                                        )
                                    )
                # find secondary dpu ip
                secondary_dpu = volume_details.get("data").get("secy_dpu")
                LOG.info(
                    "initialize_connection - secondary_dpu=%s", secondary_dpu)
                if secondary_dpu:
                    if topology_response["status"] is True:
                        topology_data = topology_response.get("data")
                        for device in topology_data.values():
                            for dpu in device["dpus"]:
                                if dpu["uuid"] == secondary_dpu:
                                    portal_ip = str(dpu["dataplane_ip"])
                                    portal_port = str(port)
                                    portal_transport = "tcp"
                                    str_portals.append(
                                        (
                                            portal_ip,
                                            portal_port,
                                            portal_transport
                                        )
                                    )

                # preparing connection info dict to return
                vol_nguid = provider_id.replace("-", "")
                data = {
                    "vol_uuid": provider_id,
                    "target_nqn": str(target_nqn),
                    "host_nqn": host_nqn,
                    "portals": str_portals,
                    "volume_nguid": vol_nguid,
                }
                conn_info = {"driver_volume_type": "nvmeof", "data": data}
                LOG.info("initialize_connection - conn_info=%s", conn_info)
            else:
                raise exception.VolumeBackendAPIException(
                    data=_("FAC enabled hosts are not supported")
                )

            return conn_info
        except swagger_client.ApiException as e:
            LOG.error(
                "[initialize_connection]Request to BackendApi Failed -> %s",
                e.body
            )
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to attach the volume %(name)s: %(error)s." %
                    {
                        'name': volume.get('display_name'),
                        'error': error['error_message']
                    }
                )
            )
        except Exception as e:
            LOG.error("[initialize_connection]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to attach volume %(name)s: %(args)s" %
                    {
                        'name': volume.get('display_name'),
                        'args': e.args
                    }
                )
            )

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate connection for detaching the port from volume.

        :param volume: the volume object
        :param connector: the connector object
        """
        provider_id = volume.get("provider_id")
        LOG.info("terminate_connection - provider_id=%s", provider_id)
        if not provider_id:
            raise exception.VolumeBackendAPIException(
                data=_("terminate_connection error: no provider_id available.")
            )

        try:
            volume_details = self.rest_client.get_volume_detail(
                uuid=provider_id)
            LOG.info("terminate_connection - volume_details=%s",
                     volume_details)

            if connector is None:
                # None connector means force-detach
                # Remove all ports from backend
                ports = volume_details["data"]["ports"]

                if ports:
                    # Get the host details for each attachment
                    hosts_fac_enabled = self._get_dpu_enabled_host_list(ports)
                    # request composer to detach volume
                    for port_id in ports.keys():
                        if (
                            ports.get(port_id)["transport"] == "PCI"
                            or not hosts_fac_enabled[
                                ports.get(port_id)["host_uuid"]
                            ]
                        ):
                            self.rest_client.detach_volume(port_id)

                LOG.info("Removed all the ports from storage backend.")
                return

            host_nqn = connector.get("nqn")
            if not host_nqn:
                host_name = connector.get("host")
                if host_name:
                    host_nqn = "nqn.2015-09.com.host:" + host_name
            if not host_nqn:
                raise exception.VolumeBackendAPIException(
                    data=_("terminate_connection error: "
                           "no host nqn available.")
                )

            # get host_uuid from the host_nqn
            LOG.info("terminate_connection - host_nqn=%s", host_nqn)
            host_uuid = self.rest_client.get_host_uuid_from_host_nqn(host_nqn)
            LOG.info("terminate_connection - host_uuid=%s", host_uuid)

            ports = volume_details["data"]["ports"]
            if host_uuid and ports:
                port_ids = [
                    port
                    for port in ports.keys()
                    if ports.get(port)["host_uuid"] == host_uuid
                ]
                # request fungible to detach volume
                if port_ids:
                    # Get the host details for each attachment
                    hosts_fac_enabled = self._get_dpu_enabled_host_list(ports)
                    # request composer to detach volume
                    for port_id in port_ids:
                        if (
                            ports.get(port_id)["transport"] == "PCI"
                            or not hosts_fac_enabled[
                                ports.get(port_id)["host_uuid"]
                            ]
                        ):
                            self.rest_client.detach_volume(port_id)
                    LOG.info(
                        "Volume detached successfully. \
                            provider_id=%s", provider_id
                    )
                else:
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "terminate_connection error: "
                            "required port is not available for detach."
                        )
                    )
            else:
                raise exception.VolumeBackendAPIException(
                    data=_(
                        "terminate_connection error: "
                        "Volume not attached to any ports."
                    )
                )
        except swagger_client.ApiException as e:
            LOG.error(
                "[terminate_connection]Request to BackendApi Failed -> %s",
                e.body
            )
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to detach the volume "
                    "%(name)s: %(error)s." %
                    {
                        'name': volume.get('display_name'),
                        'error': error['error_message']
                    }
                )
            )
        except Exception as e:
            LOG.error("[terminate_connection]Error occurred: %s", e)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to detach volume %(name)s: %(args)s" %
                    {
                        'name': volume.get('display_name'),
                        'args': e.args
                    }
                )
            )

    def create_snapshot(self, snapshot):
        """Create volume snapshot on storage backend.

        :param snapshot: volume snapshot to be created
        :return: snapshot model updates
        """
        if "provider_id" in snapshot.volume:
            if snapshot.volume.provider_id:
                try:
                    # request fungible to create snapshot
                    fungible_res = self.rest_client.create_snapshot(
                        snapshot.volume.provider_id, snapshot.id
                    )
                    provider_id = fungible_res["data"]["uuid"]
                    # fungible model updates dict to return
                    model_updates = {
                        "provider_id": provider_id,
                    }
                    LOG.info(
                        "Snapshot created successfully %s. ",
                        snapshot.id)
                    return model_updates
                except swagger_client.ApiException as e:
                    LOG.error(
                        "[create_snapshot]Request to BackendApi Failed -> %s",
                        e.body
                    )
                    error = json.loads(e.body)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to create the snapshot "
                            "%(name)s: %(error)s."
                        ) % {
                            'name': snapshot.display_name,
                            'error': error['error_message']
                        }
                    )
                except Exception as e:
                    LOG.error("[create_snapshot]Error occurred: %s", e)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to create snapshot %(name)s: %(args)s" %
                            {
                                'name': snapshot.display_name,
                                'args': e.args
                            }
                        )
                    )
            else:
                raise exception.VolumeBackendAPIException(
                    data=_(
                        "Failed to create snapshot: volume provider_id "
                        "not found in snapshot's volume details."
                    )
                )
        else:
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to create snapshot, volume provider_id attribute "
                    "not found in snapshot details :%s." % snapshot.id
                )
            )

    def delete_snapshot(self, snapshot):
        """Delete snapshot from storage backend.

        :param snapshot: snapshot to be deleted
        """
        LOG.info("Request to delete snapshot : %s.", snapshot['id'])
        if "provider_id" in snapshot:
            if snapshot["provider_id"]:
                try:
                    # request fungible to delete snapshot
                    fungible_res = self.rest_client.delete_snapshot(
                        snapshot["provider_id"]
                    )
                    LOG.info(
                        "Snapshot deleted successfully: %s.",
                        fungible_res['message']
                    )
                except swagger_client.ApiException as e:
                    LOG.error(
                        "[delete_snapshot]Request to BackendApi Failed -> %s",
                        e.body
                    )
                    error = json.loads(e.body)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to delete the snapshot "
                            "%(name)s: %(error)s." %
                            {
                                'name': snapshot['display_name'],
                                'error': error['error_message']
                            }
                        )
                    )
                except Exception as e:
                    LOG.error("[delete_snapshot]Error occurred: %s", e)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to delete snapshot %(name)s: %(args)s" %
                            {
                                'name': snapshot['display_name'],
                                'args': e.args
                            }
                        )
                    )
            else:
                LOG.info("Snapshot backend UUID not found in snapshot "
                         "details.")
        else:
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to delete snapshot, provider_id attribute "
                    "not found in snapshot details :%s." % snapshot["id"]
                )
            )

    def extend_volume(self, volume, new_size):
        """Extend size of existing fungible volume.

        :param volume: volume to be extended
        :param new_size: volume size after extending
        """
        LOG.info("Request to extend volume : %s.", volume['id'])
        if "provider_id" in volume:
            if volume["provider_id"]:
                try:
                    # request fungible to extend volume
                    self.rest_client.extend_volume(
                        volume["provider_id"], new_size)
                    LOG.info(
                        "Volume %s is resized successfully", volume['id'])
                except swagger_client.ApiException as e:
                    LOG.error(
                        "[extend_volume]Request to BackendApi Failed -> %s",
                        e.body
                    )
                    error = json.loads(e.body)
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to extend the volume "
                            "%(name)s: %(error)s." %
                            {
                                'name': volume.get('display_name'),
                                'error': error['error_message']
                            }
                        )
                    )
                except Exception as e:
                    LOG.error("[extend_volume]Error occurred: {e}")
                    raise exception.VolumeBackendAPIException(
                        data=_(
                            "Failed to extend volume %(name)s: %(args)s" %
                            {
                                'name': volume.get('display_name'),
                                'args': e.args
                            }
                        )
                    )
            else:
                LOG.warning(
                    "Volume backend UUID not found in volume details.")
        else:
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to extend volume, provider_id attribute "
                    "not found in volume details :%s." % volume["id"]
                )
            )

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""
        LOG.info(
            "Copy volume %s to image on "
            "image service %s. Image meta: %s.",
            volume['id'], image_service, image_meta
        )

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        if hasattr(utils, "brick_get_connector_properties"):
            properties = utils.brick_get_connector_properties(
                use_multipath, enforce_multipath
            )
        else:
            properties = volume_utils.brick_get_connector_properties(
                use_multipath, enforce_multipath
            )
        # added iops parameter in properties to
        # perform high iops while uploading volume to image
        properties[constants.FSC_IOPS_IMG_MIG] = True
        attach_info, volume = self._attach_volume(context, volume, properties)

        try:
            # Wait until the device path appears
            self.wait_for_device(attach_info["device"]["path"])
            image_utils.upload_volume(
                context,
                image_service,
                image_meta,
                attach_info["device"]["path"],
                compress=True,
            )
            LOG.debug(
                "Copy volume %s to image complete",
                volume['id']
            )
        finally:
            # Since attached volume was not used for writing we can force
            # detach it
            self._detach_volume(
                context, attach_info, volume, properties, force=True,
                ignore_errors=True
            )

    def copy_image_to_volume(self, context, volume, image_service, image_id,
                             disable_sparse=False):
        """Fetch the image from image_service and write it to the volume."""
        LOG.info(
            "Copy image %s from image service %s "
            "to volume %s.", image_id, image_service, volume['id']
        )

        use_multipath = self.configuration.use_multipath_for_image_xfer
        enforce_multipath = self.configuration.enforce_multipath_for_image_xfer
        if hasattr(utils, "brick_get_connector_properties"):
            properties = utils.brick_get_connector_properties(
                use_multipath, enforce_multipath
            )
        else:
            properties = volume_utils.brick_get_connector_properties(
                use_multipath, enforce_multipath
            )
        # added iops parameter in properties to
        # perform high iops while downloading image to volume
        properties[constants.FSC_IOPS_IMG_MIG] = True
        attach_info, volume = self._attach_volume(context, volume, properties)
        try:
            # Wait until the device path appears
            self.wait_for_device(attach_info["device"]["path"])
            image_utils.fetch_to_raw(
                context,
                image_service,
                image_id,
                attach_info["device"]["path"],
                self.configuration.volume_dd_blocksize,
                size=volume["size"],
                disable_sparse=disable_sparse,
            )
            LOG.debug(
                "Copy image %s to volume %s complete",
                image_id, volume['id']
            )
        except exception.ImageTooBig:
            with excutils.save_and_reraise_exception():
                LOG.exception(
                    "Copying image %(image_id)s to "
                    "volume failed due to insufficient available "
                    "space.",
                    {"image_id": image_id},
                )
        finally:
            self._detach_volume(context, attach_info,
                                volume, properties, force=True)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Update volume name of new fungible volume.

        Original volume is renamed first since fungible does not allow
        multiple volumes to have same name.
        """
        try:
            new_name = volume["id"]
            LOG.info("Rename volume from %s to %s.", new_volume['id'],
                     new_name)
            LOG.info("Update backend volume name to %s", new_name)
            # if new volume provider id is None, # volume will not be renamed.
            if new_volume["provider_id"]:
                # if original provider id is None & volume host doesn't match,
                # original volume will not be renamed
                if volume["provider_id"] and (volume["host"] ==
                                              new_volume["host"]):
                    try:
                        self.rest_client.rename_volume(
                            volume["provider_id"], "migrating_" + new_name
                        )
                    except swagger_client.ApiException as e:
                        LOG.warning(
                            "Failed to rename the original volume %s.",
                            e.body
                        )
                else:
                    LOG.warning(
                        "Original volume backend UUID not found in "
                        "volume details."
                    )
                self.rest_client.rename_volume(
                    new_volume["provider_id"], new_name)
            else:
                LOG.warning(
                    "New volume backend UUID not found in volume details.")
            return {"_name_id": None}
        except swagger_client.ApiException as e:
            LOG.error(
                "[update_migrated_volume]Request to BackendApi Failed -> %s",
                e.body
            )
            error = json.loads(e.body)
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to rename the volume %(name)s:"
                    " %(error)s." %
                    {
                        'name': volume.get('display_name'),
                        'error': error['error_message']
                    }
                )
            )
        except Exception as e:
            LOG.error("[update_migrated_volume]Error occurred: {e}")
            raise exception.VolumeBackendAPIException(
                data=_(
                    "Failed to rename volume %(name)s: %(args)s" %
                    {
                        'name': volume.get('display_name'),
                        'args': e.args
                    }
                )
            )

    def get_volume_stats(self, refresh=False):
        """Get the volume stats"""
        data = {
            "volume_backend_name":
            self.configuration.safe_get("volume_backend_name"),
            "vendor_name": "Fungible Inc.",
            "driver_version": self.VERSION,
            "storage_protocol": cinderconstants.NVMEOF_TCP,
            "total_capacity_gb": "unknown",
            "free_capacity_gb": "unknown",
        }
        return data
