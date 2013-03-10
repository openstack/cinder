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
"""
HP Lefthand SAN ISCSI Driver.

The driver communicates to the backend aka Cliq via SSH to perform all the
operations on the SAN.
"""
from lxml import etree

from cinder import exception
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san.san import SanISCSIDriver


LOG = logging.getLogger(__name__)


class HpSanISCSIDriver(SanISCSIDriver):
    """Executes commands relating to HP/Lefthand SAN ISCSI volumes.

    We use the CLIQ interface, over SSH.

    Rough overview of CLIQ commands used:

    :createVolume:    (creates the volume)

    :getVolumeInfo:    (to discover the IQN etc)

    :getClusterInfo:    (to discover the iSCSI target IP address)

    :assignVolumeChap:    (exports it with CHAP security)

    The 'trick' here is that the HP SAN enforces security by default, so
    normally a volume mount would need both to configure the SAN in the volume
    layer and do the mount on the compute layer.  Multi-layer operations are
    not catered for at the moment in the cinder architecture, so instead we
    share the volume using CHAP at volume creation time.  Then the mount need
    only use those CHAP credentials, so can take place exclusively in the
    compute layer.
    """

    stats = {'driver_version': '1.0',
             'free_capacity_gb': 'unknown',
             'reserved_percentage': 0,
             'storage_protocol': 'iSCSI',
             'total_capacity_gb': 'unknown',
             'vendor_name': 'Hewlett-Packard',
             'volume_backend_name': 'HpSanISCSIDriver'}

    def __init__(self, *args, **kwargs):
        super(HpSanISCSIDriver, self).__init__(*args, **kwargs)
        self.cluster_vip = None

    def _cliq_run(self, verb, cliq_args, check_exit_code=True):
        """Runs a CLIQ command over SSH, without doing any result parsing"""
        cliq_arg_strings = []
        for k, v in cliq_args.items():
            cliq_arg_strings.append(" %s=%s" % (k, v))
        cmd = verb + ''.join(cliq_arg_strings)

        return self._run_ssh(cmd, check_exit_code)

    def _cliq_run_xml(self, verb, cliq_args, check_cliq_result=True):
        """Runs a CLIQ command over SSH, parsing and checking the output"""
        cliq_args['output'] = 'XML'
        (out, _err) = self._cliq_run(verb, cliq_args, check_cliq_result)

        LOG.debug(_("CLIQ command returned %s"), out)

        result_xml = etree.fromstring(out)
        if check_cliq_result:
            response_node = result_xml.find("response")
            if response_node is None:
                msg = (_("Malformed response to CLIQ command "
                         "%(verb)s %(cliq_args)s. Result=%(out)s") %
                       locals())
                raise exception.VolumeBackendAPIException(data=msg)

            result_code = response_node.attrib.get("result")

            if result_code != "0":
                msg = (_("Error running CLIQ command %(verb)s %(cliq_args)s. "
                         " Result=%(out)s") %
                       locals())
                raise exception.VolumeBackendAPIException(data=msg)

        return result_xml

    def _cliq_get_cluster_info(self, cluster_name):
        """Queries for info about the cluster (including IP)"""
        cliq_args = {}
        cliq_args['clusterName'] = cluster_name
        cliq_args['searchDepth'] = '1'
        cliq_args['verbose'] = '0'

        result_xml = self._cliq_run_xml("getClusterInfo", cliq_args)

        return result_xml

    def _cliq_get_cluster_vip(self, cluster_name):
        """Gets the IP on which a cluster shares iSCSI volumes"""
        cluster_xml = self._cliq_get_cluster_info(cluster_name)

        vips = []
        for vip in cluster_xml.findall("response/cluster/vip"):
            vips.append(vip.attrib.get('ipAddress'))

        if len(vips) == 1:
            return vips[0]

        _xml = etree.tostring(cluster_xml)
        msg = (_("Unexpected number of virtual ips for cluster "
                 " %(cluster_name)s. Result=%(_xml)s") %
               locals())
        raise exception.VolumeBackendAPIException(data=msg)

    def _cliq_get_volume_info(self, volume_name):
        """Gets the volume info, including IQN"""
        cliq_args = {}
        cliq_args['volumeName'] = volume_name
        result_xml = self._cliq_run_xml("getVolumeInfo", cliq_args)

        # Result looks like this:
        #<gauche version="1.0">
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
        #</gauche>

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

        LOG.debug(_("Volume info: %(volume_name)s => %(volume_attributes)s") %
                  locals())
        return volume_attributes

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

        volume_info = self._cliq_get_volume_info(volume['name'])
        cluster_name = volume_info['volume.clusterName']
        iscsi_iqn = volume_info['volume.iscsiIqn']

        #TODO(justinsb): Is this always 1? Does it matter?
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

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        raise NotImplementedError()

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        raise NotImplementedError()

    def delete_volume(self, volume):
        """Deletes a volume."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['prompt'] = 'false'  # Don't confirm
        try:
            volume_info = self._cliq_get_volume_info(volume['name'])
        except exception.ProcessExecutionError:
            LOG.error("Volume did not exist. It will not be deleted")
            return
        self._cliq_run_xml("deleteVolume", cliq_args)

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

        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
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

    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['serverName'] = connector['host']
        self._cliq_run_xml("unassignVolumeToServer", cliq_args)

    def get_volume_stats(self, refresh):
        if refresh:
            cliq_args = {}
            result_xml = self._cliq_run_xml("getClusterInfo", cliq_args)
            cluster_node = result_xml.find("response/cluster")
            total_capacity = cluster_node.attrib.get("spaceTotal")
            free_capacity = cluster_node.attrib.get("unprovisionedSpace")
            GB = 1073741824

            self.stats['total_capacity_gb'] = int(total_capacity) / GB
            self.stats['free_capacity_gb'] = int(free_capacity) / GB

        return self.stats
