# Copyright 2017 Inspur Corp.
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
Volume driver for Inspur AS13000
"""

import ipaddress
import json
import random
import re
import time

import eventlet
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import requests

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import utils as volume_utils

LOG = logging.getLogger(__name__)

inspur_as13000_opts = [
    cfg.ListOpt(
        'as13000_ipsan_pools',
        default=['Pool0'],
        help='The Storage Pools Cinder should use, a comma separated list.'),
    cfg.IntOpt(
        'as13000_token_available_time',
        default=3300,
        min=600, max=3600,
        help='The effective time of token validity in seconds.'),
    cfg.StrOpt(
        'as13000_meta_pool',
        help='The pool which is used as a meta pool when creating a volume, '
             'and it should be a replication pool at present. '
             'If not set, the driver will choose a replication pool '
             'from the value of as13000_ipsan_pools.'),
]

CONF = cfg.CONF
CONF.register_opts(inspur_as13000_opts)


class RestAPIExecutor(object):
    def __init__(self, hostname, port, username, password):
        self._username = username
        self._password = password
        self._token = None
        self._baseurl = 'http://%s:%s/rest' % (hostname, port)

    def login(self):
        """Login the AS13000 and store the token."""
        self._token = self._login()
        LOG.debug('Login the AS13000.')

    def _login(self):
        """Do request to login the AS13000 and get the token."""
        method = 'security/token'
        params = {'name': self._username, 'password': self._password}
        token = self.send_rest_api(method=method, params=params,
                                   request_type='post').get('token')
        return token

    @utils.retry(exception.VolumeDriverException, interval=1, retries=3)
    def send_rest_api(self, method, params=None, request_type='post'):
        try:
            return self.send_api(method, params, request_type)
        except exception.VolumeDriverException:
            self.login()
            raise

    @staticmethod
    @utils.trace_method
    def do_request(cmd, url, header, data):
        """Send request to the storage and handle the response."""
        if cmd in ['post', 'get', 'put', 'delete']:
            req = getattr(requests, cmd)(url, data=data, headers=header)
        else:
            msg = (_('Unsupported cmd: %s.') % cmd)
            raise exception.VolumeBackendAPIException(msg)

        response = req.json()
        code = req.status_code
        LOG.debug('CODE: %(code)s, RESPONSE: %(response)s.',
                  {'code': code, 'response': response})

        if code != 200:
            msg = (_('Code: %(code)s, URL: %(url)s, Message: %(msg)s.')
                   % {'code': req.status_code,
                      'url': req.url,
                      'msg': req.text})
            LOG.error(msg)
            raise exception.VolumeDriverException(msg)

        return response

    @utils.trace
    def send_api(self, method, params=None, request_type='post'):
        if params:
            params = json.dumps(params)

        url = '%s/%s' % (self._baseurl, method)

        # header is not needed when the driver login the backend
        if method == 'security/token':
            if request_type == 'delete':
                header = {'X-Auth-Token': self._token}
            else:
                header = None
        else:
            if not self._token:
                self.login()
            header = {'X-Auth-Token': self._token}

        response = self.do_request(request_type, url, header, params)

        try:
            code = response.get('code')
            if code == 0:
                if request_type == 'get':
                    data = response.get('data')
                else:
                    if method == 'security/token':
                        data = response.get('data')
                    else:
                        data = response.get('message')
                        data = str(data).lower()
                        if hasattr(data, 'success'):
                            return
            elif code == 301:
                msg = _('Token is expired.')
                LOG.error(msg)
                raise exception.VolumeDriverException(msg)
            else:
                message = response.get('message')
                msg = (_('Unexpected RestAPI response: %(code)d %(msg)s.') % {
                       'code': code, 'msg': message})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(msg)
        except ValueError:
            msg = _("Deal with response failed.")
            raise exception.VolumeDriverException(msg)

        return data


@interface.volumedriver
class AS13000Driver(san.SanISCSIDriver):
    """Driver for Inspur AS13000 storage.

    .. code-block:: none

      Version history:
          1.0.0 - Initial driver

    """

    VENDOR = 'INSPUR'
    VERSION = '1.0.0'
    PROTOCOL = 'iSCSI'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = 'INSPUR_CI'

    def __init__(self, *args, **kwargs):
        super(AS13000Driver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(inspur_as13000_opts)
        self.hostname = self.configuration.san_ip
        self.port = self.configuration.safe_get('san_api_port') or 8088
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.token_available_time = (self.configuration.
                                     as13000_token_available_time)
        self.pools = self.configuration.as13000_ipsan_pools
        self.meta_pool = self.configuration.as13000_meta_pool
        self.pools_info = {}
        self.nodes = []
        self._token_time = 0
        # get the RestAPIExecutor
        self._rest = RestAPIExecutor(self.hostname,
                                     self.port,
                                     self.username,
                                     self.password)

    @staticmethod
    def get_driver_options():
        return inspur_as13000_opts

    @utils.trace
    def do_setup(self, context):
        # get tokens for the driver
        self._rest.login()
        self._token_time = time.time()

        # get available nodes in the backend
        for node in self._get_cluster_status():
            if node.get('healthStatus') == 1 and node.get('ip'):
                self.nodes.append(node)

        # collect pools info
        meta_pools = [self.meta_pool] if self.meta_pool else []
        self.pools_info = self._get_pools_info(self.pools + meta_pools)

        # setup the meta pool if it is not setted
        if not self.meta_pool:
            for pool_info in self.pools_info.values():
                if pool_info['type'] in (1, '1'):
                    self.meta_pool = pool_info['name']
                    break

        self._check_pools()

        self._check_meta_pool()

    @utils.trace
    def check_for_setup_error(self):
        """Do check to make sure service is available."""
        # check the required flags in conf
        required_flags = ['san_ip', 'san_login', 'san_password',
                          'as13000_ipsan_pools']
        for flag in required_flags:
            value = self.configuration.safe_get(flag)
            if not value:
                msg = (_('Required flag %s is not set.') % flag)
                LOG.error(msg)
                raise exception.InvalidConfigurationValue(option=flag,
                                                          value=value)

        # make sure at least one node can
        if not self.nodes:
            msg = _('No healthy nodes are available!')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def _check_pools(self):
        """Check the pool in conf exist in the AS13000."""
        if not set(self.pools).issubset(self.pools_info):
            pools = set(self.pools) - set(self.pools_info)
            msg = _('Pools %s do not exist.') % pools
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    def _check_meta_pool(self):
        """Check whether the meta pool is valid."""
        if not self.meta_pool:
            msg = _('Meta pool is not set.')
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if self.meta_pool not in self.pools_info:
            msg = _('Meta pool %s does not exist.') % self.meta_pool
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

        if self.pools_info[self.meta_pool]['type'] not in (1, '1'):
            msg = _('Meta pool %s is not a replication pool.') % self.meta_pool
            LOG.error(msg)
            raise exception.InvalidInput(reason=msg)

    @utils.trace
    def create_volume(self, volume):
        """Create volume in the backend."""
        pool = volume_utils.extract_host(volume.host, level='pool')
        size = volume.size * units.Ki
        name = self._trans_name_down(volume.name)

        method = 'block/lvm'
        request_type = "post"
        params = {
            "name": name,
            "capacity": size,
            "dataPool": pool,
            "dataPoolType": self.pools_info[pool]['type'],
            "metaPool": self.meta_pool
        }
        self._rest.send_rest_api(method=method, params=params,
                                 request_type=request_type)

    @utils.trace
    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a new volume base on a specific snapshot."""
        if snapshot.volume_size > volume.size:
            msg = (_("create_volume_from_snapshot: snapshot %(snapshot_name)s "
                     "size is %(snapshot_size)dGB and doesn't fit in target "
                     "volume %(volume_name)s of size %(volume_size)dGB.") %
                   {'snapshot_name': snapshot.name,
                    'snapshot_size': snapshot.volume_size,
                    'volume_name': volume.name,
                    'volume_size': volume.size})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)
        src_vol_name = self._trans_name_down(snapshot.volume_name)
        source_vol = snapshot.volume
        src_pool = volume_utils.extract_host(source_vol['host'],
                                             level='pool')
        dest_name = self._trans_name_down(volume.name)
        dest_pool = volume_utils.extract_host(volume.host, level='pool')
        snap_name = self._trans_name_down(snapshot.name)

        # lock the snapshot before clone from it
        self._snapshot_lock_op('lock', src_vol_name, snap_name, src_pool)

        # do clone from snap to a volume
        method = 'snapshot/volume/cloneLvm'
        request_type = 'post'
        params = {'originalLvm': src_vol_name,
                  'originalPool': src_pool,
                  'originalSnap': snap_name,
                  'name': dest_name,
                  'pool': dest_pool}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

        # do filling the cloned volume
        self._filling_volume(dest_name, dest_pool)

        # wait until the cloned volume has been filled
        self._wait_volume_filled(dest_name, dest_pool)

        # unlock the original snapshot
        self._snapshot_lock_op('unlock', src_vol_name, snap_name, src_pool)

        if volume.size > snapshot.volume_size:
            self.extend_volume(volume, volume.size)

    @utils.trace
    def create_cloned_volume(self, volume, src_vref):
        """Clone a volume."""
        if src_vref.size > volume.size:
            msg = (_("create_cloned_volume: source volume %(src_vol)s "
                     "size is %(src_size)dGB and doesn't fit in target "
                     "volume %(tgt_vol)s of size %(tgt_size)dGB.") %
                   {'src_vol': src_vref.name,
                    'src_size': src_vref.size,
                    'tgt_vol': volume.name,
                    'tgt_size': volume.size})
            LOG.error(msg)
            raise exception.InvalidInput(message=msg)
        dest_pool = volume_utils.extract_host(volume.host, level='pool')
        dest_vol_name = self._trans_name_down(volume.name)
        src_pool = volume_utils.extract_host(src_vref.host, level='pool')
        src_vol_name = self._trans_name_down(src_vref.name)

        method = 'block/lvm/clone'
        request_type = 'post'
        params = {'srcVolumeName': src_vol_name,
                  'srcPoolName': src_pool,
                  'destVolumeName': dest_vol_name,
                  'destPoolName': dest_pool}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

        if volume.size > src_vref.size:
            self.extend_volume(volume, volume.size)

    @utils.trace
    def extend_volume(self, volume, new_size):
        """Extend volume to new size."""
        name = self._trans_name_down(volume.name)
        if not self._check_volume(volume):
            msg = _('Extend Volume Failed: Volume %s does not exist.') % name
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        size = new_size * units.Ki
        pool = volume_utils.extract_host(volume.host, level='pool')

        method = 'block/lvm'
        request_type = 'put'
        params = {'pool': pool,
                  'name': name,
                  'newCapacity': size}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    def delete_volume(self, volume):
        """Delete volume from AS13000."""
        name = self._trans_name_down(volume.name)
        if not self._check_volume(volume):
            # if volume is not exist in backend, the driver will do
            # nothing but log it
            LOG.info('Tried to delete non-existent volume %(name)s.',
                     {'name': name})
            return

        pool = volume_utils.extract_host(volume.host, level='pool')

        method = 'block/lvm?pool=%s&lvm=%s' % (pool, name)
        request_type = 'delete'
        self._rest.send_rest_api(method=method, request_type=request_type)

    @utils.trace
    def create_snapshot(self, snapshot):
        """Create snapshot of volume in backend.

        The snapshot type of AS13000 is copy-on-write.
        """
        source_volume = snapshot.volume
        volume_name = self._trans_name_down(source_volume.name)
        if not self._check_volume(source_volume):
            msg = (_('create_snapshot: Source_volume %s does not exist.')
                   % volume_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        pool = volume_utils.extract_host(source_volume.host, level='pool')
        snapshot_name = self._trans_name_down(snapshot.name)

        method = 'snapshot/volume'
        request_type = 'post'
        params = {'snapName': snapshot_name,
                  'volumeName': volume_name,
                  'poolName': pool,
                  'snapType': 'r'}
        self._rest.send_rest_api(method=method, params=params,
                                 request_type=request_type)

    @utils.trace
    def delete_snapshot(self, snapshot):
        """Delete snapshot of volume."""
        source_volume = snapshot.volume
        volume_name = self._trans_name_down(source_volume.name)
        if self._check_volume(source_volume) is False:
            msg = (_('delete_snapshot: Source_volume %s does not exist.')
                   % volume_name)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        pool = volume_utils.extract_host(source_volume.host, level='pool')
        snapshot_name = self._trans_name_down(snapshot.name)

        method = ('snapshot/volume?snapName=%s&volumeName=%s&poolName=%s'
                  % (snapshot_name, volume_name, pool))
        request_type = 'delete'
        self._rest.send_rest_api(method=method, request_type=request_type)

    @utils.trace
    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If we haven't gotten stats yet or 'refresh' is True,
        run update the stats first.
        """
        if not self._stats or refresh:
            self._update_volume_stats()
        return self._stats

    @utils.trace
    def _update_volume_stats(self):
        """Update the backend stats including driver info and pools info."""

        # As _update_volume_stats runs periodically,
        # so we can do a check and refresh the token each time it runs.
        time_difference = time.time() - self._token_time
        if time_difference > self.token_available_time:
            self._rest.login()
            self._token_time = time.time()
            LOG.debug('Token of the Driver has been refreshed.')

        # update the backend stats
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['vendor_name'] = self.VENDOR
        data['driver_version'] = self.VERSION
        data['storage_protocol'] = self.PROTOCOL
        data['volume_backend_name'] = backend_name
        data['pools'] = self._get_pools_stats()

        self._stats = data
        LOG.debug('Update volume stats : %(stats)s.', {'stats': self._stats})

    def _build_target_portal(self, ip, port):
        """Build iSCSI portal for both IPV4 and IPV6."""
        addr = ipaddress.ip_address(ip)
        if addr.version == 4:
            ipaddr = ip
        else:
            ipaddr = '[%s]' % ip
        return '%(ip)s:%(port)s' % {'ip': ipaddr, 'port': port}

    @utils.trace
    def initialize_connection(self, volume, connector, **kwargs):
        """Initialize connection steps:

        1. check if the host exist in targets.
        2.1 if there is target that has the host, add the volume to the target.
        2.2 if not, create an target add host to host add volume to host.
        3. return the target info.
        """
        host_ip = connector['ip']
        multipath = connector.get("multipath", False)
        # Check if there host exist in targets
        host_exist, target_name, node_of_target = self._get_target_from_conn(
            host_ip)
        if not host_exist:
            # host doesn't exist, need create target and bind the host,

            # generate the target name
            _TARGET_NAME_PATTERN = 'target.inspur.%(host)s-%(padding)s'
            _padding = str(random.randint(0, 99999999)).zfill(8)
            target_name = _TARGET_NAME_PATTERN % {'host': connector['host'],
                                                  'padding': _padding}

            # decide the nodes to be used
            if multipath:
                node_of_target = [node['name'] for node in self.nodes]
            else:
                # single node
                node_of_target = [self.nodes[0]['name']]

            # create the target
            nodes = ','.join(node_of_target)
            self._create_target(target_node=nodes,
                                target_name=target_name)
            self._add_host_to_target(host_ip=host_ip,
                                     target_name=target_name)

        self._add_lun_to_target(target_name=target_name, volume=volume)
        if self.configuration.use_chap_auth:
            self._add_chap_to_target(target_name,
                                     self.configuration.chap_username,
                                     self.configuration.chap_password)

        lun_id = self._get_lun_id(volume, target_name)
        connection_data = {
            'target_discovered': True,
            'volume_id': volume.id,
        }

        portals = []
        for node_name in node_of_target:
            for node in self.nodes:
                if node['name'] == node_name:
                    portal = self._build_target_portal(node.get('ip'), '3260')
                    portals.append(portal)

        if multipath:
            connection_data.update({
                'target_portals': portals,
                'target_luns': [int(lun_id)] * len(portals),
                'target_iqns': [target_name] * len(portals)
            })
        else:
            # single node
            connection_data.update({
                'target_portal': portals[0],
                'target_lun': int(lun_id),
                'target_iqn': target_name
            })

        if self.configuration.use_chap_auth:
            connection_data['auth_method'] = 'CHAP'
            connection_data['auth_username'] = self.configuration.chap_username
            connection_data['auth_password'] = self.configuration.chap_password

        return {'driver_volume_type': 'iscsi', 'data': connection_data}

    @utils.trace
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete lun from target.

        If target has no any lun, driver will delete the target.
        """
        volume_name = self._trans_name_down(volume.name)
        target_name = None
        lun_id = None

        host_ip = None
        if connector and 'ip' in connector:
            host_ip = connector['ip']

        target_list = self._get_target_list()
        for target in target_list:
            if not host_ip or host_ip in target['hostIp']:
                for lun in target['lun']:
                    if volume_name == lun['lvm']:
                        target_name = target['name']
                        lun_id = lun['lunID']
                        break
                if lun_id is not None:
                    break
        if lun_id is None:
            return

        self._delete_lun_from_target(target_name=target_name,
                                     lun_id=lun_id)
        luns = self._get_lun_list(target_name)
        if not luns:
            self._delete_target(target_name)

    def _get_pools_info(self, pools):
        """Get the pools info."""
        method = 'block/pool?type=2'
        requests_type = 'get'
        pools_data = self._rest.send_rest_api(method=method,
                                              request_type=requests_type)
        pools_info = {}
        for pool_data in pools_data:
            if pool_data['name'] in pools:
                pools_info[pool_data['name']] = pool_data

        return pools_info

    @utils.trace
    def _get_pools_stats(self):
        """Generate the pool stat information."""
        pools_info = self._get_pools_info(self.pools)

        pools = []
        for pool_info in pools_info.values():
            total_capacity = pool_info.get('totalCapacity')
            total_capacity_gb = self._unit_convert(total_capacity)
            used_capacity = pool_info.get('usedCapacity')
            used_capacity_gb = self._unit_convert(used_capacity)
            free_capacity_gb = total_capacity_gb - used_capacity_gb

            pool = {
                'pool_name': pool_info.get('name'),
                'total_capacity_gb': total_capacity_gb,
                'free_capacity_gb': free_capacity_gb,
                'thin_provisioning_support': True,
                'thick_provisioning_support': False,
            }
            pools.append(pool)

        return pools

    @utils.trace
    def _get_target_from_conn(self, host_ip):
        """Get target information base on the host ip."""
        host_exist = False
        target_name = None
        node = None

        target_list = self._get_target_list()
        for target in target_list:
            if host_ip in target['hostIp']:
                host_exist = True
                target_name = target['name']
                node = target['node']
                break

        return host_exist, target_name, node

    @utils.trace
    def _get_target_list(self):
        """Get a list of all targets in the backend."""
        method = 'block/target/detail'
        request_type = 'get'
        data = self._rest.send_rest_api(method=method,
                                        request_type=request_type)
        return data

    @utils.trace
    def _create_target(self, target_name, target_node):
        """Create a target on the specified node."""
        method = 'block/target'
        request_type = 'post'
        params = {'name': target_name, 'nodeName': target_node}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    def _delete_target(self, target_name):
        """Delete all target of all the node."""
        method = 'block/target?name=%s' % target_name
        request_type = 'delete'
        self._rest.send_rest_api(method=method,
                                 request_type=request_type)

    @utils.trace
    def _add_chap_to_target(self, target_name, chap_username, chap_password):
        """Add CHAP to target."""
        method = 'block/chap/bond'
        request_type = 'post'
        params = {'target': target_name,
                  'user': chap_username,
                  'password': chap_password}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    def _add_host_to_target(self, host_ip, target_name):
        """Add the authority of host to target."""
        method = 'block/host'
        request_type = 'post'
        params = {'name': target_name, 'hostIp': host_ip}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    @utils.retry(exceptions=exception.VolumeDriverException,
                 interval=1,
                 retries=3)
    def _add_lun_to_target(self, target_name, volume):
        """Add volume to target."""
        pool = volume_utils.extract_host(volume.host, level='pool')
        volume_name = self._trans_name_down(volume.name)

        method = 'block/lun'
        request_type = 'post'
        params = {'name': target_name,
                  'pool': pool,
                  'lvm': volume_name}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    def _delete_lun_from_target(self, target_name, lun_id):
        """Delete lun from target_name."""
        method = 'block/lun?name=%s&id=%s&force=1' % (target_name, lun_id)
        request_type = 'delete'
        self._rest.send_rest_api(method=method, request_type=request_type)

    @utils.trace
    def _get_lun_list(self, target_name):
        """Get all lun list of the target."""
        method = 'block/lun?name=%s' % target_name
        request_type = 'get'
        return self._rest.send_rest_api(method=method,
                                        request_type=request_type)

    @utils.trace
    def _snapshot_lock_op(self, op, vol_name, snap_name, pool_name):
        """Lock or unlock a snapshot to protect the snapshot.

        op is 'lock' for lock and 'unlock' for unlock
        """
        method = 'snapshot/volume/%s' % op
        request_type = 'post'
        params = {'snapName': snap_name,
                  'volumeName': vol_name,
                  'poolName': pool_name}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.trace
    def _filling_volume(self, name, pool):
        """Filling a volume so that make it independently."""
        method = 'block/lvm/filling'
        request_type = 'post'
        params = {'pool': pool, 'name': name}
        self._rest.send_rest_api(method=method,
                                 params=params,
                                 request_type=request_type)

    @utils.retry(exception.VolumeDriverException, interval=5, retries=36)
    def _wait_volume_filled(self, name, pool):
        """Wait until the volume is filled."""
        volumes = self._get_volumes(pool)
        for vol in volumes:
            if name == vol['name']:
                if vol['lvmType'] == 1:
                    return
                else:
                    break
        msg = (_('Volume %s is not filled.') % name)
        raise exception.VolumeDriverException(msg)

    @utils.trace
    def _check_volume(self, volume):
        """Check if the volume exists in the backend."""
        pool = volume_utils.extract_host(volume.host, 'pool')
        volume_name = self._trans_name_down(volume.name)
        attempts = 3
        while attempts > 0:
            volumes = self._get_volumes(pool)
            attempts -= 1
            for vol in volumes:
                if volume_name == vol.get('name'):
                    return True
            eventlet.sleep(1)
        return False

    @utils.trace
    def _get_volumes(self, pool):
        """Get all the volumes in the pool."""
        method = 'block/lvm?pool=%s' % pool
        request_type = 'get'
        return self._rest.send_rest_api(method=method,
                                        request_type=request_type)

    @utils.trace
    def _get_cluster_status(self):
        """Get all nodes of the backend."""
        method = 'cluster/node'
        request_type = 'get'
        return self._rest.send_rest_api(method=method,
                                        request_type=request_type)

    @utils.trace
    def _get_lun_id(self, volume, target_name):
        """Get lun id of the voluem in a target."""
        pool = volume_utils.extract_host(volume.host, level='pool')
        volume_name = self._trans_name_down(volume.name)

        lun_id = None
        luns = self._get_lun_list(target_name)
        for lun in luns:
            mappinglvm = lun.get('mappingLvm')
            lun_name = mappinglvm.replace(r'%s/' % pool, '')
            if lun_name == volume_name:
                lun_id = lun.get('id')
        return lun_id

    def _trans_name_down(self, name):
        """Legitimize the name.

        Because AS13000 volume name is only allowed letters, numbers, and '_'.
        """
        return name.replace('-', '_')

    @utils.trace
    def _unit_convert(self, capacity):
        """Convert all units to GB.

        The capacity is a string in form like 100GB, 20TB, 100B,
        this routine will convert to GB unit.
        """
        capacity = capacity.upper()
        try:
            unit = re.findall(r'[A-Z]+', capacity)[0]
        except BaseException:
            unit = ''
        capacity = float(capacity.replace(unit, ''))

        size_gb = 0.0

        if unit in ['B', '']:
            size_gb = capacity / units.Gi
        elif unit in ['K', 'KB']:
            size_gb = capacity / units.Mi
        elif unit in ['M', 'MB']:
            size_gb = capacity / units.Ki
        elif unit in ['G', 'GB']:
            size_gb = capacity
        elif unit in ['T', 'TB']:
            size_gb = capacity * units.Ki
        elif unit in ['P', 'PB']:
            size_gb = capacity * units.Mi
        elif unit in ['E', 'EB']:
            size_gb = capacity * units.Gi

        return float('%.0f' % size_gb)
