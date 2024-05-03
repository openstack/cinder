# Copyright 2023 toyou Corp.
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
import base64
import json
import time

from oslo_log import log as logging
from oslo_utils import netutils
import requests

from cinder import exception
from cinder.i18n import _

LOG = logging.getLogger(__name__)


class TydsClient(object):
    def __init__(self, hostname, port, username, password):
        """Initializes a new instance of the TydsClient.

        :param hostname: IP address of the Toyou distributed storage system.
        :param port: The port to connect to the Toyou distributed storage
        system.
        :param username: The username for authentication.
        :param password: The password for authentication.
        """
        self._username = username
        self._password = base64.standard_b64encode(password.encode('utf-8')
                                                   ).decode('utf-8')
        self._baseurl = f"http://{hostname}:{port}/api"
        self._snapshot_count = 999
        self._token = None
        self._token_expiration = 0
        self._ip = self._get_local_ip()

    def get_token(self):
        if self._token and time.time() < self._token_expiration:
            # Token is not expired, directly return the existing Token
            return self._token

        # Token has expired or has not been obtained before,
        # retrieving the Token again
        self._token = self.login()
        self._token_expiration = time.time() + 710 * 60
        return self._token

    def send_http_api(self, url, params=None, method='post'):
        """Send an HTTP API request to the storage.

        :param url: The URL for the API request.
        :param params: The parameters for the API request.
        :param method: The HTTP method for the API request. Default is 'post'.

        :return: The response from the API request.

        :raises VolumeBackendAPIException: If the API request fails.

        """
        if params:
            params = json.dumps(params)

        url = f"{self._baseurl}/{url}"
        header = {
            'Authorization': self.get_token(),
            'Content-Type': 'application/json'
        }

        LOG.debug(
            "Toyou Cinder Driver Requests: http_process header: %(header)s "
            "url: %(url)s method: %(method)s",
            {'header': header, 'url': url, 'method': method}
        )

        response = self.do_request(method, url, header, params)
        return response

    @staticmethod
    def _get_local_ip():
        """Get the local IP address.

        :return: The local IP address.

        """
        return netutils.get_my_ipv4()

    def login(self):
        """Perform login to obtain an authentication token.

        :return: The authentication token.

        :raises VolumeBackendAPIException: If the login request fails or the
                                            authentication token cannot be
                                            obtained.

        """
        params = {
            'REMOTE_ADDR': self._ip,
            'username': self._username,
            'password': self._password
        }
        data = json.dumps(params)
        url = f"{self._baseurl}/auth/login/"
        response = self.do_request(method='post',
                                   url=url,
                                   header={'Content-Type': 'application/json'},
                                   data=data)
        self._token = response.get('token')
        return self._token

    @staticmethod
    def do_request(method, url, header, data):
        """Send request to the storage and handle the response.

        :param method: The HTTP method to use for the request. Valid methods
                       are 'post', 'get', 'put', and 'delete'.
        :param url: The URL to send the request to.
        :param header: The headers to include in the request.
        :param data: The data to send in the request body.

        :return: The response data returned by the storage system.

        :raises VolumeBackendAPIException: If the request fails or the response
                                            from the storage system is not as
                                            expected.

        """
        valid_methods = ['post', 'get', 'put', 'delete']
        if method not in valid_methods:
            raise exception.VolumeBackendAPIException(
                data=_('Unsupported request type: %s.') % method
            )

        try:
            req = getattr(requests, method)(url, data=data, headers=header)
            req.raise_for_status()
            response = req.json()
        except requests.exceptions.RequestException as e:
            msg = (_('Request to %(url)s failed: %(error)s') %
                   {'url': url, 'error': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)
        except ValueError as e:
            msg = (_('Failed to parse response from %(url)s: %(error)s') %
                   {'url': url, 'error': str(e)})
            raise exception.VolumeBackendAPIException(data=msg)

        LOG.debug('URL: %(url)s, TYPE: %(type)s, CODE: %(code)s, '
                  'RESPONSE: %(response)s.',
                  {'url': req.url,
                   'type': method,
                   'code': req.status_code,
                   'response': response})
        # Response Error
        if response.get('code') != '0000':
            msg = (_('ERROR RESPONSE: %(response)s URL: %(url)s PARAMS: '
                     '%(params)s.') %
                   {'response': response, 'url': url, 'params': data})
            raise exception.VolumeBackendAPIException(data=msg)
        # return result
        return response.get('data')

    def get_pools(self):
        """Query pool information.

        :return: A list of pool information.

        """
        url = 'pool/pool/'
        response = self.send_http_api(url=url, method='get')
        pool_list = response.get('poolList', [])
        return pool_list

    def get_volumes(self):
        """Query volume information.

        :return: A list of volume information.

        """
        url = 'block/blocks'
        vol_list = self.send_http_api(url=url, method='get').get('blockList')
        return vol_list

    def create_volume(self, vol_name, size, pool_name, stripe_size):
        """Create a volume.

        :param vol_name: The name of the volume.
        :param size: The size of the volume in MB.
        :param pool_name: The name of the pool to create the volume in.
        :param stripe_size: The stripe size of the volume.
        :return: The response from the API call.

        """
        url = 'block/blocks/'
        params = {'blockName': vol_name,
                  'sizeMB': size,
                  'poolName': pool_name,
                  'stripSize': stripe_size}
        return self.send_http_api(url=url, method='post', params=params)

    def delete_volume(self, vol_id):
        """Delete a volume.

        :param vol_id: The ID of the volume to delete.

        """
        url = 'block/recycle/forceCreate/'
        params = {'id': [vol_id]}
        self.send_http_api(url=url, method='post', params=params)

    def extend_volume(self, vol_name, pool_name, size_mb):
        """Extend the size of a volume.

        :param vol_name: The name of the volume to extend.
        :param pool_name: The name of the pool where the volume resides.
        :param size_mb: The new size of the volume in MB.

        """
        url = 'block/blocks/%s/' % vol_name
        params = {'blockName': vol_name,
                  'sizeMB': size_mb,
                  'poolName': pool_name}
        self.send_http_api(url=url, method='put', params=params)

    def create_clone_volume(self, *args):
        """Create a clone of a volume.

        :param args: The arguments needed for cloning a volume.
            Args:
                - pool_name: The name of the source pool.
                - block_name: The name of the source block.
                - block_id: The ID of the source block.
                - target_pool_name: The name of the target pool.
                - target_pool_id: The ID of the target pool.
                - target_block_name: The name of the target block.

        """
        pool_name, block_name, block_id, target_pool_name, target_pool_id, \
            target_block_name = args
        params = {
            'poolName': pool_name,
            'blockName': block_name,
            'blockId': block_id,
            'copyType': 0,  # 0 means shallow copy, currently copy volume first
            # default shallow copy, 1 means deep copy
            'metapoolName': 'NULL',
            'targetMetapoolName': 'NULL',
            'targetPoolName': target_pool_name,
            'targetPoolId': target_pool_id,
            'targetBlockName': target_block_name
        }
        url = 'block/block/copy/'
        self.send_http_api(url=url, params=params)

    def get_snapshot(self, volume_id=None):
        """Get a list of snapshots.

        :param volume_id: The ID of the volume to filter snapshots (default:
                          None).
        :return: The list of snapshots.

        """
        url = 'block/snapshot?pageNumber=1'
        if volume_id:
            url += '&blockId=%s' % volume_id
        url += '&pageSize=%s'
        response = self.send_http_api(
            url=url % self._snapshot_count, method='get')
        if self._snapshot_count < int(response.get('total')):
            self._snapshot_count = int(response.get('total'))
            response = self.send_http_api(
                url=url % self._snapshot_count, method='get')
        snapshot_list = response.get('snapShotList')
        return snapshot_list

    def create_snapshot(self, name, volume_id, comment=''):
        """Create a snapshot of a volume.

        :param name: The name of the snapshot.
        :param volume_id: The ID of the volume to create a snapshot from.
        :param comment: The optional comment for the snapshot (default: '').

        """
        url = 'block/snapshot/'
        params = {'sourceBlock': volume_id,
                  'snapShotName': name,
                  'remark': comment}
        self.send_http_api(url=url, method='post', params=params)

    def delete_snapshot(self, snapshot_id):
        """Delete a snapshot.

        :param snapshot_id: The ID of the snapshot to delete.

        """
        url = 'block/snapshot/%s/' % snapshot_id
        self.send_http_api(url=url, method='delete')

    def create_volume_from_snapshot(self, volume_name, pool_name,
                                    snapshot_name, source_volume_name,
                                    source_pool_name):
        """Create a volume from a snapshot.

        :param volume_name: The name of the new volume.
        :param pool_name: The name of the pool for the new volume.
        :param snapshot_name: The name of the snapshot to create the volume
                              from.
        :param source_volume_name: The name of the source volume (snapshot's
                                   origin).
        :param source_pool_name: The name of the pool for the source volume.

        """
        url = 'block/clone/'
        params = {'cloneBlockName': volume_name,
                  'targetPoolName': pool_name,
                  'snapName': snapshot_name,
                  'blockName': source_volume_name,
                  'poolName': source_pool_name,
                  'targetMetapoolName': 'NULL'}
        self.send_http_api(url=url, method='post', params=params)

    def get_clone_progress(self, volume_id, volume_name):
        """Get the progress of a volume clone operation.

        :param volume_id: The ID of the volume being cloned.
        :param volume_name: The name of the volume being cloned.
        :return: The progress of the clone operation.

        """
        url = 'block/clone/progress/'
        params = {'blockId': volume_id,
                  'blockName': volume_name}
        progress = self.send_http_api(url=url, method='post', params=params)
        return progress

    def get_copy_progress(self, block_id, block_name, target_block_name):
        """Get the progress of a block copy operation.

        :param block_id: The ID of the block being copied.
        :param block_name: The name of the block being copied.
        :param target_block_name: The name of the target block.
        :return: The progress of the copy operation.

        """
        url = 'block/block/copyprogress/'
        params = {
            'blockId': block_id,
            'blockName': block_name,
            'targetBlockName': target_block_name
        }

        progress_data = self.send_http_api(url=url, params=params)
        return progress_data

    def create_initiator_group(self, group_name, client):
        """Create an initiator group.

        :param group_name: The name of the initiator group.
        :param client: The client information for the initiator group.
        """
        url = 'iscsi/client-group/'
        params = {
            'group_name': group_name,
            'client': client,
            'chap_auth': 0,
            'mode': 'ISCSI'
        }
        self.send_http_api(url=url, params=params)

    def delete_initiator_group(self, group_id):
        """Delete an initiator group.

        :param group_id: The ID of the initiator group.
        :return: The response from the API call.
        """
        url = 'iscsi/client-group/?group_id=%s' % group_id
        return self.send_http_api(url=url, method='delete')

    def get_initiator_list(self):
        """Get the list of initiators.

        :return: The list of initiators.
        """
        url = 'iscsi/client-group/'
        res = self.send_http_api(url=url, method='get')
        initiator_list = res.get('client_group_list')
        return initiator_list

    def get_target(self):
        """Get the list of target hosts.

        :return: The list of target hosts.
        """
        url = '/host/host/'
        res = self.send_http_api(url=url, method='get')
        target = res.get('hostList')
        return target

    def create_target(self, group_name, target_list, vols_info):
        """Create a target.

        :param group_name: The name of the initiator group.
        :param target_list: The list of target hosts.
        :param vols_info: The information of the volumes.
        :return: The response from the API call.
        """
        url = 'iscsi/target/'
        params = {"group_name": group_name,
                  "chap_auth": 0,
                  "write_cache": 1,
                  "hostName": ",".join(target_list),
                  "block": vols_info}
        return self.send_http_api(url=url, params=params, method='post')

    def delete_target(self, target_name):
        """Delete a target.

        :param target_name: The name of the target.
        :return: The response from the API call.
        """
        url = 'iscsi/target/?targetIqn=%s' % target_name
        return self.send_http_api(url=url, method='delete')

    def modify_target(self, target_name, target_list, vol_info):
        """Modify a target.

        :param target_name: The name of the target.
        :param target_list: The list of target hosts.
        :param vol_info: The information of the volumes.
        :return: The response from the API call.
        """
        url = 'iscsi/target/'
        params = {
            "targetIqn": target_name,
            "chap_auth": 0,
            "hostName": target_list,
            "block": vol_info
        }
        return self.send_http_api(url=url, params=params, method='put')

    def get_initiator_target_connections(self):
        """Get the list of IT (Initiator-Target) connections.

        :return: The list of IT connections.
        """
        url = 'iscsi/target/'
        res = self.send_http_api(url=url, method='get')
        target_list = res.get('target_list')
        return target_list

    def generate_config(self, target_name):
        """Generate configuration for a target.

        :param target_name: The name of the target.
        """
        url = 'iscsi/target-config/'
        params = {
            'targetName': target_name
        }
        self.send_http_api(url=url, params=params, method='post')

    def restart_service(self, host_name):
        """Restart the iSCSI service on a host.

        :param host_name: The name of the host.
        """
        url = 'iscsi/service/restart/'
        params = {
            "hostName": host_name
        }
        self.send_http_api(url=url, params=params, method='post')
