#    (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
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
HP LeftHand SAN ISCSI Driver.

The driver communicates to the backend aka Cliq via SSH to perform all the
operations on the SAN.
"""

from lxml import etree

from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils
from cinder.openstack.common import units
from cinder.volume.drivers.san.san import SanISCSIDriver


LOG = logging.getLogger(__name__)


class HPLeftHandCLIQProxy(SanISCSIDriver):
    """Executes commands relating to HP/LeftHand SAN ISCSI volumes.

    We use the CLIQ interface, over SSH.

    Rough overview of CLIQ commands used:

    :createVolume:    (creates the volume)

    :deleteVolume:    (deletes the volume)

    :modifyVolume:    (extends the volume)

    :createSnapshot:    (creates the snapshot)

    :deleteSnapshot:    (deletes the snapshot)

    :cloneSnapshot:    (creates the volume from a snapshot)

    :getVolumeInfo:    (to discover the IQN etc)

    :getSnapshotInfo:    (to discover the IQN etc)

    :getClusterInfo:    (to discover the iSCSI target IP address)

    The 'trick' here is that the HP SAN enforces security by default, so
    normally a volume mount would need both to configure the SAN in the volume
    layer and do the mount on the compute layer.  Multi-layer operations are
    not catered for at the moment in the cinder architecture, so instead we
    share the volume using CHAP at volume creation time.  Then the mount need
    only use those CHAP credentials, so can take place exclusively in the
    compute layer.

    Version history:
        1.0.0 - Initial driver
        1.1.0 - Added create/delete snapshot, extend volume, create volume
                from snapshot support.
        1.2.0 - Ported into the new HP LeftHand driver.
        1.2.1 - Fixed bug #1279897, HP LeftHand CLIQ proxy may return incorrect
                capacity values.
        1.2.2 - Fixed driver with Paramiko 1.13.0, bug #1298608.
    """

    VERSION = "1.2.2"

    device_stats = {}

    def __init__(self, *args, **kwargs):
        super(HPLeftHandCLIQProxy, self).__init__(*args, **kwargs)
        self.cluster_vip = None

    def do_setup(self, context):
        pass

    def check_for_setup_error(self):
        pass

    def get_version_string(self):
        return (_('CLIQ %(proxy_ver)s') % {'proxy_ver': self.VERSION})

    def _cliq_run(self, verb, cliq_args, check_exit_code=True):
        """Runs a CLIQ command over SSH, without doing any result parsing."""
        cmd_list = [verb]
        for k, v in cliq_args.items():
            cmd_list.append("%s=%s" % (k, v))

        return self._run_ssh(cmd_list, check_exit_code)

    def _cliq_run_xml(self, verb, cliq_args, check_cliq_result=True):
        """Runs a CLIQ command over SSH, parsing and checking the output."""
        cliq_args['output'] = 'XML'
        (out, _err) = self._cliq_run(verb, cliq_args, check_cliq_result)

        LOG.debug("CLIQ command returned %s", out)

        result_xml = etree.fromstring(out.encode('utf8'))
        if check_cliq_result:
            response_node = result_xml.find("response")
            if response_node is None:
                msg = (_("Malformed response to CLIQ command "
                         "%(verb)s %(cliq_args)s. Result=%(out)s") %
                       {'verb': verb, 'cliq_args': cliq_args, 'out': out})
                raise exception.VolumeBackendAPIException(data=msg)

            result_code = response_node.attrib.get("result")

            if result_code != "0":
                msg = (_("Error running CLIQ command %(verb)s %(cliq_args)s. "
                         " Result=%(out)s") %
                       {'verb': verb, 'cliq_args': cliq_args, 'out': out})
                raise exception.VolumeBackendAPIException(data=msg)

        return result_xml

    def _cliq_get_cluster_info(self, cluster_name):
        """Queries for info about the cluster (including IP)."""
        cliq_args = {}
        cliq_args['clusterName'] = cluster_name
        cliq_args['searchDepth'] = '1'
        cliq_args['verbose'] = '0'

        result_xml = self._cliq_run_xml("getClusterInfo", cliq_args)

        return result_xml

    def _cliq_get_cluster_vip(self, cluster_name):
        """Gets the IP on which a cluster shares iSCSI volumes."""
        cluster_xml = self._cliq_get_cluster_info(cluster_name)

        vips = []
        for vip in cluster_xml.findall("response/cluster/vip"):
            vips.append(vip.attrib.get('ipAddress'))

        if len(vips) == 1:
            return vips[0]

        _xml = etree.tostring(cluster_xml)
        msg = (_("Unexpected number of virtual ips for cluster "
                 " %(cluster_name)s. Result=%(_xml)s") %
               {'cluster_name': cluster_name, '_xml': _xml})
        raise exception.VolumeBackendAPIException(data=msg)

    def _cliq_get_volume_info(self, volume_name):
        """Gets the volume info, including IQN."""
        cliq_args = {}
        cliq_args['volumeName'] = volume_name
        result_xml = self._cliq_run_xml("getVolumeInfo", cliq_args)

        # Result looks like this:
        # <gauche version="1.0">
        #  <response description="Operation succeeded." name="CliqSuccess"
        #            processingTime="87" result="0">
        #    <volume autogrowPages="4" availability="online" blockSize="1024"
        #       bytesWritten="0" checkSum="false" clusterName="Cluster01"
        #       created="2011-02-08T19:56:53Z" deleting="false" description=""
        #       groupName="Group01" initialQuota="536870912" isPrimary="true"
        #       iscsiIqn="iqn.2003-10.com.lefthandnetworks:group01:25366:vol-b"
        #       maxSize="6865387257856" md5="9fa5c8b2cca54b2948a63d833097e1ca"
        #       minReplication="1" name="vol-b" parity="0" replication="2"
        #       reserveQuota="536870912" scratchQuota="4194304"
        #       serialNumber="9fa5c8b2cca54b2948a63d833097e1ca0000000000006316"
        #       size="1073741824" stridePages="32" thinProvision="true">
        #      <status description="OK" value="2"/>
        #      <permission access="rw"
        #            authGroup="api-34281B815713B78-(trimmed)51ADD4B7030853AA7"
        #            chapName="chapusername" chapRequired="true" id="25369"
        #            initiatorSecret="" iqn="" iscsiEnabled="true"
        #            loadBalance="true" targetSecret="supersecret"/>
        #    </volume>
        #  </response>
        # </gauche>

        # Flatten the nodes into a dictionary; use prefixes to avoid collisions
        volume_attributes = {}

        volume_node = result_xml.find("response/volume")
        for k, v in volume_node.attrib.items():
            volume_attributes["volume." + k] = v

        status_node = volume_node.find("status")
        if status_node is not None:
            for k, v in status_node.attrib.items():
                volume_attributes["status." + k] = v

        # We only consider the first permission node
        permission_node = volume_node.find("permission")
        if permission_node is not None:
            for k, v in status_node.attrib.items():
                volume_attributes["permission." + k] = v

        LOG.debug("Volume info: %(volume_name)s => %(volume_attributes)s" %
                  {'volume_name': volume_name,
                   'volume_attributes': volume_attributes})
        return volume_attributes

    def _cliq_get_snapshot_info(self, snapshot_name):
        """Gets the snapshot info, including IQN."""
        cliq_args = {}
        cliq_args['snapshotName'] = snapshot_name
        result_xml = self._cliq_run_xml("getSnapshotInfo", cliq_args)

        # Result looks like this:
        # <gauche version="1.0">
        #  <response description="Operation succeeded." name="CliqSuccess"
        #            processingTime="87" result="0">
        #    <snapshot applicationManaged="false" autogrowPages="32768"
        #       automatic="false" availability="online" bytesWritten="0"
        #       clusterName="CloudCluster1" created="2013-08-26T07:03:44Z"
        #       deleting="false" description="" groupName="CloudMgmtGroup1"
        #       id="730" initialQuota="536870912" isPrimary="true"
        #       iscsiIqn="iqn.2003-10.com.lefthandnetworks:cloudmgmtgroup1:73"
        #       md5="a64b4f850539c07fb5ce3cee5db1fcce" minReplication="1"
        #       name="snapshot-7849288e-e5e8-42cb-9687-9af5355d674b"
        #       replication="2" reserveQuota="536870912" scheduleId="0"
        #       scratchQuota="4194304" scratchWritten="0"
        #       serialNumber="a64b4f850539c07fb5ce3cee5db1fcce00000000000002da"
        #       size="2147483648" stridePages="32"
        #       volumeSerial="a64b4f850539c07fb5ce3cee5db1fcce00000000000002d">
        #      <status description="OK" value="2"/>
        #      <permission access="rw"
        #            authGroup="api-34281B815713B78-(trimmed)51ADD4B7030853AA7"
        #            chapName="chapusername" chapRequired="true" id="25369"
        #            initiatorSecret="" iqn="" iscsiEnabled="true"
        #            loadBalance="true" targetSecret="supersecret"/>
        #    </snapshot>
        #  </response>
        # </gauche>

        # Flatten the nodes into a dictionary; use prefixes to avoid collisions
        snapshot_attributes = {}

        snapshot_node = result_xml.find("response/snapshot")
        for k, v in snapshot_node.attrib.items():
            snapshot_attributes["snapshot." + k] = v

        status_node = snapshot_node.find("status")
        if status_node is not None:
            for k, v in status_node.attrib.items():
                snapshot_attributes["status." + k] = v

        # We only consider the first permission node
        permission_node = snapshot_node.find("permission")
        if permission_node is not None:
            for k, v in status_node.attrib.items():
                snapshot_attributes["permission." + k] = v

        LOG.debug("Snapshot info: %(name)s => %(attributes)s" %
                  {'name': snapshot_name, 'attributes': snapshot_attributes})
        return snapshot_attributes

    def create_volume(self, volume):
        """Creates a volume."""
        cliq_args = {}
        cliq_args['clusterName'] = self.configuration.san_clustername

        if self.configuration.san_thin_provision:
            cliq_args['thinProvision'] = '1'
        else:
            cliq_args['thinProvision'] = '0'

        cliq_args['volumeName'] = volume['name']
        if int(volume['size']) == 0:
            cliq_args['size'] = '100MB'
        else:
            cliq_args['size'] = '%sGB' % volume['size']

        self._cliq_run_xml("createVolume", cliq_args)

        return self._get_model_update(volume['name'])

    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['size'] = '%sGB' % new_size

        self._cliq_run_xml("modifyVolume", cliq_args)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        cliq_args = {}
        cliq_args['snapshotName'] = snapshot['name']
        cliq_args['volumeName'] = volume['name']

        self._cliq_run_xml("cloneSnapshot", cliq_args)

        return self._get_model_update(volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        cliq_args = {}
        cliq_args['snapshotName'] = snapshot['name']
        cliq_args['volumeName'] = snapshot['volume_name']
        cliq_args['inheritAccess'] = 1
        self._cliq_run_xml("createSnapshot", cliq_args)

    def delete_volume(self, volume):
        """Deletes a volume."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['prompt'] = 'false'  # Don't confirm
        try:
            self._cliq_get_volume_info(volume['name'])
        except processutils.ProcessExecutionError:
            LOG.error(_("Volume did not exist. It will not be deleted"))
            return
        self._cliq_run_xml("deleteVolume", cliq_args)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        cliq_args = {}
        cliq_args['snapshotName'] = snapshot['name']
        cliq_args['prompt'] = 'false'  # Don't confirm
        try:
            self._cliq_get_snapshot_info(snapshot['name'])
        except processutils.ProcessExecutionError:
            LOG.error(_("Snapshot did not exist. It will not be deleted"))
            return
        try:
            self._cliq_run_xml("deleteSnapshot", cliq_args)
        except Exception as ex:
            in_use_msg = 'cannot be deleted because it is a clone point'
            if in_use_msg in ex.message:
                raise exception.SnapshotIsBusy(ex)

            raise exception.VolumeBackendAPIException(ex)

    def local_path(self, volume):
        msg = _("local_path not supported")
        raise exception.VolumeBackendAPIException(data=msg)

    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host. HP VSA requires a volume to be assigned
        to a server.

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

        """
        self._create_server(connector)
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['serverName'] = connector['host']
        self._cliq_run_xml("assignVolumeToServer", cliq_args)

        iscsi_data = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_data
        }

    def _create_server(self, connector):
        cliq_args = {}
        cliq_args['serverName'] = connector['host']
        out = self._cliq_run_xml("getServerInfo", cliq_args, False)
        response = out.find("response")
        result = response.attrib.get("result")
        if result != '0':
            cliq_args = {}
            cliq_args['serverName'] = connector['host']
            cliq_args['initiator'] = connector['initiator']
            self._cliq_run_xml("createServer", cliq_args)

    def _get_model_update(self, volume_name):
        volume_info = self._cliq_get_volume_info(volume_name)
        cluster_name = volume_info['volume.clusterName']
        iscsi_iqn = volume_info['volume.iscsiIqn']

        # TODO(justinsb): Is this always 1? Does it matter?
        cluster_interface = '1'

        if not self.cluster_vip:
            self.cluster_vip = self._cliq_get_cluster_vip(cluster_name)
        iscsi_portal = self.cluster_vip + ":3260," + cluster_interface

        model_update = {}

        # NOTE(jdg): LH volumes always at lun 0 ?
        model_update['provider_location'] = ("%s %s %s" %
                                             (iscsi_portal,
                                              iscsi_iqn,
                                              0))
        return model_update

    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['serverName'] = connector['host']
        self._cliq_run_xml("unassignVolumeToServer", cliq_args)

    def get_volume_stats(self, refresh):
        if refresh:
            self._update_backend_status()

        return self.device_stats

    def _update_backend_status(self):
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['reserved_percentage'] = 0
        data['storage_protocol'] = 'iSCSI'
        data['vendor_name'] = 'Hewlett-Packard'

        result_xml = self._cliq_run_xml(
            "getClusterInfo", {
                'searchDepth': 1,
                'clusterName': self.configuration.san_clustername})
        cluster_node = result_xml.find("response/cluster")
        total_capacity = cluster_node.attrib.get("spaceTotal")
        free_capacity = cluster_node.attrib.get("unprovisionedSpace")
        GB = units.Gi

        data['total_capacity_gb'] = int(total_capacity) / GB
        data['free_capacity_gb'] = int(free_capacity) / GB
        self.device_stats = data

    def create_cloned_volume(self, volume, src_vref):
        raise NotImplementedError()

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def retype(self, context, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        """
        return False

    def migrate_volume(self, ctxt, volume, host):
        """Migrate the volume to the specified host.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        return (False, None)
