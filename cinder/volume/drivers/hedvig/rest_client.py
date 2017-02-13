# Copyright (c) 2018 Hedvig, Inc.
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

"""
Rest Client for Hedvig Openstack implementation.
"""
import json
import random

from oslo_log import log as logging
from oslo_utils import units
from six.moves import http_client
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.hedvig import config

LOG = logging.getLogger(__name__)


class RestClient(object):
    def __init__(self, nodes, username, password, cluster):
        """Hedvig Rest Client

        :param node: hostname of one of the nodes in the cluster
        :param username:  username of the cluster
        :param password:  password of the cluster
        :param cluster:  clustername of the cluster
        """
        LOG.debug('init called with %s , %s', nodes, cluster)
        self.username = username
        self.password = password
        self.cluster = cluster
        self.nodes = nodes
        self.nodeMap = {}

    def connect(self):
        self.store_node_map(self.nodes)
        if len(self.nodeMap) is 0:
            msg = _('Unable to connect to the nodes')
            raise exception.VolumeDriverException(msg)

    def get_session_id(self, node):
        """Retrieves the session Id

        :param node: hostname of the node
        :return:  session ID which is valid for 15 minutes
        """
        LOG.debug("get_session_id called with node %s", node)
        data = {
            'request': {
                'type': 'Login',
                'category': 'UserManagement',
                'params': {
                    'userName': self.username,
                    'password': self.password,
                    'cluster': self.cluster
                }
            }
        }
        obj = self.query(data=data, node=node)
        if obj['status'] != 'ok':
            msg = _('GetSessionId failure')
            raise exception.VolumeDriverException(msg)
        return (obj['result']['sessionId']).encode('utf-8')

    def get_all_cluster_nodes(self, node):
        """Retrieves all the nodes present in the cluster

        :param node: hostname of the node
        :return:  nodes present in the cluster
        """
        LOG.debug("get_all_cluster_nodes called with node %s", node)
        data = {
            'request': {
                'type': 'ListClusterNodes',
                'category': 'VirtualDiskManagement',
                'sessionId': self.get_session_id(node),
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        return obj['result']

    def store_node_map(self, nodes):
        """Stores all the node information along with their sessionID in dict

        :param nodes: hostname of the nodes in the cluster
        """
        LOG.debug("store_node_map called with node %s", nodes)
        exitFlag = False
        node_list = []
        for n in nodes.split(','):
            node_list.append(n.strip())
        for node in node_list:
            try:
                LOG.debug("Attempting store_node_map with node %s", node)
                nodeList = self.get_all_cluster_nodes(node)
                exitFlag = True
                for node_ in nodeList:
                    self.nodeMap[node_] = self.get_session_id(node_)

            except urllib.error.HTTPError as e:
                if e.code == http_client.NOT_FOUND:
                    LOG.debug("Client not found")
                else:
                    LOG.debug("Client not available")

            except Exception:
                LOG.exception('Retrying store_node_map with next node')

            if exitFlag:
                return

    def refresh_session_ids(self):
        """In case of session failure , it  refreshes all the

        session ID stored in nodeMap
        """
        LOG.debug("refresh_session_ids called")
        if len(self.nodeMap.keys()) == 0:
            msg = _('NodeMap is empty')
            raise exception.VolumeDriverException(msg)
        for node, val in self.nodeMap.items():
            self.nodeMap[node] = self.get_session_id(node)

    def query(self, data, node):
        """Makes a rest query with given params

        :param data: json given as param to Rest call
        :param node:  hostname of the node
        :return: REST response
        """
        data = urllib.parse.urlencode(data)
        req = urllib.request.Request("http://%s/rest/" % node, data)
        response = urllib.request.urlopen(req)
        json_str = response.read()
        obj = json.loads(json_str)
        LOG.debug("Rest call output %s ", json_str)
        return obj

    def make_rest_call(self, data, node):
        """Makes a rest Call and retries it 5 times in case of rest failure

        :param data: json given as param to Rest call
        :param node: hostname of the node
        :return:
        """
        retryCount = 0
        while retryCount < config.Config.retryCount:
            retryCount = retryCount + 1
            try:
                LOG.debug("Rest call started with node %s "
                          "and data: %s", node, data)
                obj = self.query(data, node)
                if obj['status'] == 'ok' or obj['status'] == 'warning':
                    return obj
                # We need to refresh sessionIDs if earlier ones are expired
                elif 'session-failure' in obj['status']:
                    self.refresh_session_ids()
                    session_id = self.retrieve_session_id(node)
                    data['request']['sessionId'] = session_id

            except Exception as e:
                LOG.debug("Exception details: data - %s, node - %s "
                          "exception - %s", data, node, e.args)
                node = self.get_pages_host()
        else:
            msg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(msg)

    def create_vdisk(self, vDiskInfo):
        """Rest call to create a vdisk

        :param vDiskInfo: json passsed to the rest call
        """
        LOG.debug("create_vdisk called")
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)

        sizeInB = vDiskInfo['size'] / units.Gi

        sizeInJson = {'unit': "GB",
                      'value': float(sizeInB)}
        vDiskInfo['size'] = sizeInJson
        data = {
            'request': {
                'type': 'AddVirtualDisk',
                'category': 'VirtualDiskManagement',
                'params': vDiskInfo,
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        if obj['result'][0]['status'] != 'ok':
            errmsg = _('create_vdisk REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def resize_vdisk(self, vDiskName, value):
        """Rest Call to resize Vdisk

        :param vDiskName:  name of the vdisk
        :param unit: unit is GB for openstack
        :param value:  size of the resized vdisk in GB
        """
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        LOG.debug("resize_vdisk called")
        data = {
            'request': {
                'type': 'ResizeDisks',
                'category': 'VirtualDiskManagement',
                'params': {
                    'virtualDisks': [vDiskName.encode('utf-8')],
                    'size': {
                        'unit': "GB",
                        'value': value
                    },
                },
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)

        if obj['result'][0]['status'] != 'ok':
            errmsg = _('resize_vdisk REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def delete_vdisk(self, vDiskName):
        """Rest call to delete Vdisk

        :param vDiskName: name of the vdisk
        :return: Status of the rest call
        """
        LOG.debug("delete_vdisk called %s", vDiskName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'DeleteVDisk',
                'category': 'VirtualDiskManagement',
                'params': {
                    'virtualDisks': [vDiskName.encode('utf-8')],
                },
                'sessionId': sessionId,
            }
        }

        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok':
            if "couldn't be found" not in obj['message']:
                errmsg = _('REST call status - %s') % obj['status']
                raise exception.VolumeDriverException(errmsg)

    def get_lun(self, target, vDiskName):
        """Retrieve lun number

        :param target: hostname of the target
        :param vDiskName: name of the Vdisk
        :return: lun number
        """
        try:
            LOG.debug("get_lun called for vdisk %s", vDiskName)
            node = self.get_pages_host()
            sessionId = self.retrieve_session_id(node)
            data = {
                'request': {
                    'type': 'GetLun',
                    'category': 'VirtualDiskManagement',
                    'params': {
                        'virtualDisk': vDiskName.encode('utf-8'),
                        'target': target.encode('utf-8'),
                    },
                    'sessionId': sessionId,
                }
            }

            obj = self.make_rest_call(data=data, node=node)

            if obj['status'] != 'ok':
                return -1
            return obj['result']['lun']
        except Exception:
            return -1

    def get_iqn(self, host):
        """Retrieve IQN of the host.

        :param host: hostname
        :return: iqn of the host
        """
        LOG.debug("get_iqn called for host %s", host)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'GetIqn',
                'category': 'VirtualDiskManagement',
                'params': {
                    'host': host.encode('utf-8'),
                },
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok':
            if "IQN not found" in obj['message']:
                return "ALL"
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)
        return obj['result']['iqn']

    def add_lun(self, tgtHost, vDiskName, readonly):
        """Rest Call to Add Lun

        :param tgtHost: hostname of target
        :param vDiskName: name of vdisk
        :param readonly: boolean readonly value
        """
        LOG.debug(
            "add_lun called with target %s, vdisk %s", tgtHost, vDiskName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'AddLun',
                'category': 'VirtualDiskManagement',
                'params': {
                    'virtualDisks': [vDiskName.encode('utf-8')],
                    'targets': [tgtHost.encode('utf-8')],
                    'readonly': readonly,
                },
                'sessionId': sessionId,
            }
        }

        obj = self.make_rest_call(data=data, node=node)

        restCallStatus = obj['result'][0]['status']
        tgts = obj['result'][0]['targets']
        addLunStatus = tgts[0]['status']
        if restCallStatus != 'ok' or addLunStatus != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def unmap_lun(self, target, vDiskName):
        """Rest call to unmap Lun

        :param target: hostname of the target
        :param vDiskName: name of the vdisk
        :return: true if successful
        """
        LOG.debug("unmap_lun called with target %s, vdisk %s", target,
                  vDiskName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'UnmapLun',
                'category': 'VirtualDiskManagement',
                'params': {
                    'virtualDisk': vDiskName.encode('utf-8'),
                    'target': target.encode('utf-8'),
                },
                'sessionId': sessionId,
            }
        }

        obj = self.make_rest_call(data=data, node=node)

        if obj['status'] != 'ok':
            msg = "is not mapped to the specified controller"
            if(msg not in obj['message']):
                errmsg = _('REST call status - %s') % obj['status']
                raise exception.VolumeDriverException(errmsg)

        return True

    def add_access(self, host, vDiskName, type, address):
        """Rest Call to Add access

        :param host: hostname
        :param vDiskName: name of vdisk
        :param type: type is iqn for openstack
        :param address: iqn address
        """
        LOG.debug(
            "add_access called with param host %s, vdisk %s",
            host, vDiskName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'PersistACLAccess',
                'category': 'VirtualDiskManagement',
                'params': {
                    'virtualDisks': [vDiskName.encode('utf-8')],
                    'host': host.encode('utf-8'),
                    'type': type.encode('utf-8'),
                    'address': address.encode('utf-8')
                },
                'sessionId': sessionId,
            }
        }

        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok' or obj['result'][0]['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def create_snapshot(self, vDiskName, snapshotId):
        """Rest Call to create snapshot

        :param vDiskName: name of the vdisk
        :param snapshotId: snapshotId of the snapshot
        :return: status of the rest call
        """
        LOG.debug("create_snapshot called with vdisk %s", vDiskName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'MakeSnapshot',
                'category': 'SnapshotManagement',
                'params': {
                    'virtualDisks': [vDiskName.encode('utf-8')],
                },
                'sessionId': sessionId,
            }
        }
        if snapshotId:
            param = data['request']['params']
            param['openstackSID'] = snapshotId.encode('utf-8')
        obj = self.make_rest_call(data=data, node=node)

        if obj['status'] != 'ok' or obj['result'][0]['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

        return obj['result'][0]['snapshotName'].encode('utf-8')

    def clone_vdisk(self, srcVolName, dstVolName, size):
        """Rest Call to clone vdisk

        """
        LOG.debug("clonevdisk called vdisk %s, %s", srcVolName, dstVolName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'CloneVdisk',
                'category': 'SnapshotManagement',
                'params': {
                    'srcVolName': srcVolName.encode('utf-8'),
                    'cloneVolName': dstVolName.encode('utf-8'),
                    'size': size
                },
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def get_val_in_gb(self, value, unit):
        unitRef = {
            'B': 1,
            'KB': units.Ki,
            'MB': units.Mi,
            'GB': units.Gi,
            'TB': units.Ti,
            'PB': units.Pi
        }
        return value * unitRef[unit] / units.Gi

    def update_volume_stats(self):
        """Fetch cluster level details"""
        LOG.debug("Update volume stats called")
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'ClusterInformation',
                'category': 'ClusterWatch',
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

        total = obj['result']['capacity']['total']['value']
        used = obj['result']['capacity']['used']['value']
        capacity = obj['result']['capacity']
        total_unit = capacity['total']['units'].encode('utf-8')
        used_unit = capacity['used']['units'].encode('utf-8')
        total_capacity = self.get_val_in_gb(total, total_unit)
        used_capacity = self.get_val_in_gb(used, used_unit)
        free_capacity = total_capacity - used_capacity
        LOG.debug("total_capacity %s free_capactity %s", total_capacity,
                  free_capacity)
        return (total_capacity, free_capacity)

    def clone_hedvig_snapshot(self, dstVolName, snapshotID, srcVolName, size):
        """Rest Call to clone hedvig snapshot

        """
        LOG.debug("clone_hedvig_snapshot %s, %s", dstVolName, srcVolName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'CloneVdisk',
                'category': 'SnapshotManagement',
                'params': {
                    'cloneVolName': dstVolName.encode('utf-8'),
                    'openstackSID': snapshotID.encode('utf-8'),
                    'srcVolName': srcVolName.encode('utf-8'),
                    'size': size
                },
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)
        if obj['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def delete_snapshot(self, snapshotName, vDiskName, snapshotId):
        """Rest call to delete snapshot

        :param snapshotName:  name of the snapshot to be deleted
        """
        LOG.debug(
            "delete_snapshot called with snapshot %s", snapshotName)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        data = {
            'request': {
                'type': 'DeleteSnapshot',
                'category': 'SnapshotManagement',
                'params': {
                    'snapshotName': snapshotName.encode('utf-8'),
                    'openstackSID': snapshotId.encode('utf-8'),
                    'openstackVolName': vDiskName.encode('utf-8')
                },
                'sessionId': sessionId,
            }
        }
        obj = self.make_rest_call(data=data, node=node)

        if obj['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

    def list_targets(self, computeHost):
        """Rest Call to ListTargets for a given hostname

        :param computeHost:  hostname of the computeHost
        :return: list of targets
        """
        LOG.debug("list_targets called with computehost %s", computeHost)
        node = self.get_pages_host()
        sessionId = self.retrieve_session_id(node)
        targets = []
        data = {
            'request': {
                'type': 'ListTargets',
                'category': 'VirtualDiskManagement',
                'sessionId': sessionId,

            }
        }
        if computeHost:
            data['request']['params'] = {}
            data['request']['params']['computeHost'] = computeHost

        obj = self.make_rest_call(data=data, node=node)

        if obj['status'] != 'ok':
            errmsg = _('REST call status - %s') % obj['status']
            raise exception.VolumeDriverException(errmsg)

        for ch in obj['result']:
            if ch['protocol'] == 'block':
                targets.append(ch['target'])

        return targets

    def get_pages_host(self):
        """Returns a random host from nodemap

        :return:  hostname
        """
        LOG.debug("get_pages_host called")
        if not self.nodeMap:
            msg = _('NodeMap is empty')
            raise exception.VolumeDriverException(msg)
        return random.choice(self.nodeMap.keys())

    def retrieve_session_id(self, node):
        """returns sessionID of the given node

        :param node: hostname of the node
        :return:  session ID of  the given host
        """
        LOG.debug("retrieve_session_id called with node %s", node)
        if len(self.nodeMap.keys()) == 0:
            msg = _('NodeMap is empty')
            raise exception.VolumeDriverException(msg)
        return self.nodeMap[str(node)]
