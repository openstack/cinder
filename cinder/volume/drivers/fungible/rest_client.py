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

from oslo_log import log as logging

from cinder import exception
from cinder.volume.drivers.fungible import constants
from cinder.volume.drivers.fungible import \
    swagger_api_client as swagger_client

LOG = logging.getLogger(__name__)


class RestClient(object):
    def __init__(self, configuration):
        """Initialize the api request fields."""
        self.configuration = configuration
        self.rest_ip = None
        self.rest_port = None
        self.is_configured = False

    @staticmethod
    def log_error(error_msg):
        """Raise exception with error message"""
        LOG.exception(error_msg)
        raise exception.VolumeBackendAPIException(data=error_msg)

    def do_setup(self):
        """Initial setup of API request variables"""
        get_config_value = self.configuration.safe_get
        self.client = swagger_client.Configuration()
        self.client.username = get_config_value("san_login")
        self.client.password = get_config_value("san_password")
        self.rest_ip = get_config_value("san_ip")
        self.rest_port = get_config_value("san_api_port")
        protocol = "https"
        self.client.host = f"{protocol}://{self.rest_ip}{constants.STATIC_URL}"
        self.client.verify_ssl = False
        if not self.configuration.api_enable_ssl:
            protocol = "http"
            self.client.host = (f"{protocol}://{self.rest_ip}:{self.rest_port}"
                                f"{constants.STATIC_URL}")
        LOG.info("REST server IP: %(ip)s, port: %(port)s, "
                 "username: %(user)s.",
                 {
                     "ip": self.rest_ip,
                     "port": self.rest_port,
                     "user": self.client.username,
                 })
        self.api_storage = swagger_client.StorageApi(
            swagger_client.ApiClient(self.client))
        self.api_gateway = swagger_client.ApigatewayApi(
            swagger_client.ApiClient(self.client))
        self.api_topology = swagger_client.TopologyApi(
            swagger_client.ApiClient(self.client))
        self.is_configured = True

    def check_for_setup_error(self):
        """Check status of fungible storage clusters."""
        api_response = self.api_gateway.get_fc_health().to_dict()
        return api_response

    def create_volume(self, volume, fungible_specs, volume_type,
                      snapshot=None):
        """Creates new volume using the specified parameters"""

        # Convert GB to bytes, Default 1 GB size
        volume_size = constants.BYTES_PER_GIB
        if volume['size']:
            volume_size = constants.BYTES_PER_GIB * volume['size']
        fungible_request_obj = {
            "name": volume['id'],
            "vol_type": volume_type.upper(),
            "capacity": volume_size,
            "is_clone": False,
            "encrypt": False,
            "qos_band": constants.QOS_BAND.get('silver'),
            "block_size": int(constants.BLOCK_SIZE_4K)
        }
        data_protection = {
            "num_failed_disks": 2,
            "num_data_disks": 4,
            "num_redundant_dpus": 1,
        }
        durable_param = {
            "compression_effort": 2,
            "snap_support": True,
            "space_allocation_policy": 'balanced',
        }
        # Create Volume From Snapshot
        if snapshot is not None:
            fungible_request_obj["is_clone"] = True
            fungible_request_obj["clone_source_volume_uuid"] = \
                snapshot['provider_id']

        errors = []
        # Validation check for Extraspecs
        self._validation_check(fungible_request_obj,
                               fungible_specs, volume_type, errors,
                               "ExtraSpecs", durable_param, data_protection)
        # Validation check for Metadata
        self._validation_check(fungible_request_obj,
                               volume.get('metadata', {}), volume_type, errors,
                               "Metadata", durable_param, data_protection)
        if len(errors) != 0:
            msg = "ERROR: "
            for error in errors:
                msg = msg + " | " + error
            self.log_error(error_msg=msg)

        LOG.info("create_volume: "
                 "fungible_request_obj=%(fungible_request_obj)s",
                 {'fungible_request_obj': fungible_request_obj})
        api_response = self.api_storage.create_volume(
            body_volume_intent_create=fungible_request_obj).to_dict()

        return api_response

    def _validation_check(self, fungible_obj, data, volume_type, errors,
                          prefix, durable_param, data_protection):
        if constants.FSC_KMIP_SECRET_KEY in data:
            if data[constants.FSC_KMIP_SECRET_KEY]:
                fungible_obj['encrypt'] = True
                fungible_obj['kmip_secret_key'] = data[
                    constants.FSC_KMIP_SECRET_KEY]

        if constants.FSC_BLK_SIZE in data:
            if data[constants.FSC_BLK_SIZE] in constants.BLOCK_SIZE:
                if (volume_type.upper() == constants.VOLUME_TYPE_RF1 and
                        data[constants.FSC_BLK_SIZE] !=
                        constants.BLOCK_SIZE_16K):
                    msg = (
                        f"{prefix} {constants.FSC_BLK_SIZE} value is invalid \
                        for the volume type specified")
                    errors.append(msg)
                else:
                    fungible_obj['block_size'] = int(
                        data[constants.FSC_BLK_SIZE])
            else:
                msg = (f"{prefix} {constants.FSC_BLK_SIZE} value is invalid")
                errors.append(msg)
        elif volume_type.upper() == constants.VOLUME_TYPE_RF1:
            # Set default block size for RF1 to 16K
            fungible_obj['block_size'] = int(constants.BLOCK_SIZE_16K)

        if constants.FSC_QOS_BAND in data:
            if data[constants.FSC_QOS_BAND].lower() in constants.QOS_BAND:
                fungible_obj['qos_band'] = constants.QOS_BAND.get(
                    data[constants.FSC_QOS_BAND].lower())
            else:
                msg = (f"{prefix} {constants.FSC_QOS_BAND} value is invalid")
                errors.append(msg)

        if (volume_type.upper() == constants.VOLUME_TYPE_RAW or
                volume_type.upper() == constants.VOLUME_TYPE_RF1):
            if constants.FSC_FD_IDS in data:
                ids = data[constants.FSC_FD_IDS].split(',', 2)
                if len(ids) <= 2:
                    ids = [item.strip() for item in ids]
                    fungible_obj['fault_domain_ids'] = ids
                else:
                    msg = (f"{prefix} {constants.FSC_FD_IDS} - "
                           f"Only two fault domain ids can be provided.")
                    errors.append(msg)

            if constants.FSC_FD_OP in data:
                if (data[constants.FSC_FD_OP].upper()
                        in constants.FSC_FD_OPS):
                    fungible_obj['fd_op'] = data[constants.FSC_FD_OP]
                else:
                    msg = (f"{prefix} {constants.FSC_FD_OP} "
                           f"value is invalid")
                    errors.append(msg)

        if (volume_type.upper() == constants.VOLUME_TYPE_REPLICA or
                volume_type.upper() == constants.VOLUME_TYPE_EC or
                volume_type.upper() == constants.VOLUME_TYPE_RF1):
            if constants.FSC_SPACE_ALLOCATION_POLICY in data:
                if (data[constants.FSC_SPACE_ALLOCATION_POLICY].lower()
                        in constants.SPACE_ALLOCATION_POLICY):
                    durable_param['space_allocation_policy'] = data[
                        constants.FSC_SPACE_ALLOCATION_POLICY]
                else:
                    msg = (f"{prefix} {constants.FSC_SPACE_ALLOCATION_POLICY}"
                           f" value is invalid")
                    errors.append(msg)

            if constants.FSC_COMPRESSION in data:
                if (data[constants.FSC_COMPRESSION].lower() ==
                        constants.FALSE):
                    durable_param['compression_effort'] = 0
                elif (data[constants.FSC_COMPRESSION].lower() ==
                      constants.TRUE):
                    durable_param['compression_effort'] = 2
                else:
                    msg = (f"{prefix} {constants.FSC_COMPRESSION} value is "
                           f"invalid")
                    errors.append(msg)

            if constants.FSC_SNAPSHOTS in data:
                if (data[constants.FSC_SNAPSHOTS].lower()
                        in constants.BOOLEAN):
                    if (data[constants.FSC_SNAPSHOTS].lower() ==
                            constants.FALSE):
                        durable_param['snap_support'] = False
                else:
                    msg = (f"{prefix} {constants.FSC_SNAPSHOTS} value is "
                           f"invalid")
                    errors.append(msg)

        if volume_type.upper() == constants.VOLUME_TYPE_EC:
            fungible_obj.update(durable_param)
            if constants.FSC_EC_SCHEME in data:
                if data[constants.FSC_EC_SCHEME] == constants.EC_8_2:
                    data_protection['num_data_disks'] = 8
                elif data[constants.FSC_EC_SCHEME] == constants.EC_4_2:
                    data_protection['num_data_disks'] = 4
                elif data[constants.FSC_EC_SCHEME] == constants.EC_2_1:
                    data_protection['num_data_disks'] = 2
                    data_protection['num_failed_disks'] = 1
                else:
                    msg = (f"{prefix} {constants.FSC_EC_SCHEME} value is "
                           f"invalid")
                    errors.append(msg)
            fungible_obj["data_protection"] = data_protection

        elif volume_type.upper() == constants.VOLUME_TYPE_REPLICA:
            fungible_obj.update(durable_param)
            data_protection = {
                "num_failed_disks": 1,
                "num_data_disks": 1,
                "num_redundant_dpus": 1,
            }
            fungible_obj["data_protection"] = data_protection

        elif volume_type.upper() == constants.VOLUME_TYPE_RF1:
            fungible_obj.update(durable_param)
            pass

    def delete_volume(self, volume_uuid):
        """Deletes the specified volume"""
        LOG.info("delete_volume: volume_uuid=%(volume_uuid)s",
                 {'volume_uuid': volume_uuid})
        api_response = self.api_storage.delete_volume(
            volume_uuid=volume_uuid).to_dict()

        return api_response

    def get_volume_detail(self, uuid):
        """Get volume details by uuid"""
        api_response = self.api_storage.get_volume(volume_uuid=uuid).to_dict()

        return api_response

    def get_host_uuid_from_host_nqn(self, host_nqn):
        """Get host uuid from the host_nqn supplied"""
        api_response = self.api_topology.get_host_id_list(
            host_nqn_contains=host_nqn).to_dict()

        host_uuids = api_response.get("data").get("host_uuids")
        if len(host_uuids) == 1:
            return host_uuids[0]
        else:
            return None

    def get_host_details(self, host_uuid):
        """Get host details for the host_uuid supplied"""
        api_response = self.api_topology.get_host_info(
            host_uuid=host_uuid).to_dict()

        host = api_response.get("data")
        return host

    def get_hosts_subset(self, host_uuids):
        """Get host details in a list for the list of host_uuids supplied"""
        request_obj = {
            "host_id_list": host_uuids
        }
        api_response = self.api_topology.fetch_hosts_with_ids(
            body_fetch_hosts_with_ids=request_obj).to_dict()

        hosts = api_response.get("data")
        return hosts

    def create_host(self, host_nqn):
        """Create host with the host_nqn supplied"""
        request_obj = {
            "host_name": host_nqn,
            "host_nqn": host_nqn,
            "fac_enabled": False
        }
        LOG.info("create_host: request_obj=%(request_obj)s",
                 {'request_obj': request_obj})
        api_response = self.api_topology.add_host(
            body_host_create=request_obj).to_dict()

        return api_response

    def attach_volume(self, uuid, host_uuid, fac_enabled, iops=False):
        """Attaches a volume to a host server,

        using the specified transport method
        """
        if fac_enabled:
            request_obj = {
                "transport": 'PCI',
                "host_uuid": host_uuid,
                "fnid": 3,
                "huid": 1,
                "ctlid": 0
            }
        else:
            request_obj = {
                "transport": 'TCP',
                "host_uuid": host_uuid
            }
        # high iops set when uploading, downloading or migrating volume
        if iops:
            request_obj["max_read_iops"] = self.configuration.safe_get(
                'iops_for_image_migration')

        LOG.info("attach_volume: uuid=%(uuid)s "
                 "request_obj=%(request_obj)s",
                 {'uuid': uuid, 'request_obj': request_obj})
        api_response = self.api_storage.attach_volume(
            volume_uuid=uuid,
            body_volume_attach=request_obj).to_dict()

        return api_response

    def detach_volume(self, port_uuid):
        """Detach the volume specified port"""
        LOG.info("detach_volume: port_uuid=%(port_uuid)s",
                 {'port_uuid': port_uuid})
        api_response = self.api_storage.delete_port(
            port_uuid=port_uuid).to_dict()

        return api_response

    def create_snapshot(self, uuid, snapshot_name):
        """Create snapshot of volume with specified uuid"""
        fungible_request_obj = {
            "name": snapshot_name
        }
        api_response = self.api_storage.create_snapshot(
            volume_uuid=uuid,
            body_volume_snapshot_create=fungible_request_obj).to_dict()

        return api_response

    def delete_snapshot(self, uuid):
        """Delete snapshot with specified uuid"""
        api_response = self.api_storage.delete_snapshot(
            snapshot_uuid=uuid).to_dict()

        return api_response

    def extend_volume(self, uuid, new_size):
        """Update volume size to new size"""
        fungible_request_obj = {
            "op": "UPDATE_CAPACITY",
            "capacity": constants.BYTES_PER_GIB * new_size,
        }
        api_response = self.api_storage.update_volume(
            volume_uuid=uuid,
            body_volume_update=fungible_request_obj).to_dict()

        return api_response

    def rename_volume(self, uuid, new_name):
        """Update volume name to new name"""
        fungible_request_obj = {
            "op": "RENAME_VOLUME",
            "new_vol_name": new_name,
        }
        api_response = self.api_storage.update_volume(
            volume_uuid=uuid,
            body_volume_update=fungible_request_obj).to_dict()

        return api_response

    def copy_volume(self, volumeId, src_vrefId):
        """Submit copy volume task."""
        payload = {
            "src_volume_uuid": src_vrefId,
            "dest_volume_uuid": volumeId,
            "timeout": self.configuration.safe_get(
                'fsc_clone_volume_timeout')
        }

        LOG.info("Volume clone payload: %(payload)s.", {'payload': payload})
        api_response = self.api_storage.create_volume_copy_task(
            body_create_volume_copy_task=payload).to_dict()

        return api_response

    def get_volume_copy_task(self, task_uuid):
        """Get volume copy task status"""
        api_response = self.api_storage.get_volume_copy_task(
            task_uuid).to_dict()

        return api_response

    def delete_volume_copy_task(self, task_uuid):
        """Delete volume copy task"""
        api_response = self.api_storage.delete_volume_copy_task(
            task_uuid).to_dict()

        return api_response

    def get_topology(self):
        api_response = self.api_topology.get_hierarchical_topology().to_dict()
        return api_response
