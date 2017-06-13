#  Copyright (c) 2016 IBM Corporation
#  All Rights Reserved.
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

from cinder import exception
from cinder.i18n import _

BLOCKS_PER_GIGABYTE = 2097152
XIV_LOG_PREFIX = "[IBM XIV STORAGE]:"
XIV_CONNECTION_TYPE_ISCSI = 'iscsi'
XIV_CONNECTION_TYPE_FC = 'fibre_channel'
XIV_CONNECTION_TYPE_FC_ECKD = 'fibre_channel_eckd'
CHAP_NONE = 'disabled'
CHAP_ENABLED = 'enabled'
STORAGE_DRIVER_XIV = 'xiv'
STORAGE_DRIVER_DS8K = 'ds8k'


CONF_KEYS = {
    'driver': "volume_driver",
    'proxy': "proxy",
    'user': "san_login",
    'password': "san_password",
    'storage_pool': "san_clustername",
    'address': "san_ip",
    'driver_version': "ibm_storage_driver_version",
    'volume_api_class': "volume_api_class",
    'volume_backend': "volume_backend_name",
    'connection_type': "connection_type",
    'management_ips': "management_ips",
    'chap': 'chap',
    'system_id': 'system_id',
    'replication_device': 'replication_device'
}
CONF_BACKEND_KEYS = {
    'user': "san_login",
    'password': "san_password",
    'storage_pool': "san_clustername",
    'address': "san_ip",
    'volume_backend': "volume_backend_name",
    'connection_type': "connection_type",
    'management_ips': "management_ips",
}
FLAG_KEYS = {
    'user': "user",
    'password': "password",
    'storage_pool': "vol_pool",
    'address': "address",
    'connection_type': "connection_type",
    'bypass_connection_check': "XIV_BYPASS_CONNECTION_CHECK",
    'management_ips': "management_ips"
}
METADATA_KEYS = {
    'ibm_storage_version': 'openstack_ibm_storage_driver_version',
    'openstack_version': 'openstack_version',
    'pool_host_key': 'openstack_compute_node_%(hostname)s',
    'pool_volume_os': 'openstack_volume_os',
    'pool_volume_hostname': 'openstack_volume_hostname'
}


def get_host_or_create_from_iqn(connector, connection=None):
    """Get host name.

    Return the hostname if existing at the connector (nova-compute info)
    If not, generate one from the IQN or HBA
    """
    if connection is None and connector.get('host', None):
        return connector['host']

    if connection != XIV_CONNECTION_TYPE_FC and 'initiator' in connector:
        try:
            initiator = connector['initiator']
            iqn_suffix = initiator.split('.')[-1].replace(":", "_")
        except Exception:
            if connector.get('initiator', 'None'):
                raise exception.VolumeDriverException(message=(
                    _("Initiator format: %(iqn)s")) %
                    {'iqn': connector.get('initiator', 'None')})
            else:
                raise exception.VolumeDriverException(
                    message=_("Initiator is missing from connector object"))
        return "nova-compute-%s" % iqn_suffix

    if connection != XIV_CONNECTION_TYPE_ISCSI and len(
        connector.get('wwpns', [])
    ) > 0:
        return "nova-compute-%s" % connector['wwpns'][0].replace(":", "_")

    raise exception.VolumeDriverException(
        message=_("Compute host missing either iSCSI initiator or FC wwpns"))


def gigabytes_to_blocks(gigabytes):
    return int(BLOCKS_PER_GIGABYTE * float(gigabytes))


def get_online_iscsi_ports(ibm_storage_cli):
    """Returns online iscsi ports."""
    iscsi_ports = [
        {
            'ip': p.get('address'),
            # ipinterface_list returns ports field in Gen3, and
            # port field in BlueRidge
            'port': p.get('ports', p.get('port')),
            'module': p.get('module')
        } for p in ibm_storage_cli.cmd.ipinterface_list()
        if p.type == 'iSCSI']

    iscsi_connected_ports = [
        {
            'port': p.index,
            'module': p.get('module_id')
        } for p in ibm_storage_cli.cmd.ipinterface_list_ports()
        if p.is_link_up == 'yes' and p.role == 'iSCSI']

    to_return = []
    for ip in iscsi_ports:
        if len([
            p for p in iscsi_connected_ports
            if (p.get('port') == ip.get('port') and
                p.get('module') == ip.get('module'))
        ]) > 0:
            to_return += [ip.get('ip')]

    return to_return
