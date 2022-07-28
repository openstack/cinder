#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import time

from oslo_log import log as logging
import requests

from cinder import exception
from cinder.i18n import _
from cinder.utils import retry
from cinder.volume.drivers.yadro import tatlin_api
from cinder.volume.drivers.yadro.tatlin_exception import TatlinAPIException

LOG = logging.getLogger(__name__)

retry_exc = (Exception,)


def InitTatlinClient(ip, port, username, password,
                     verify, api_retry_count,
                     wait_interval, wait_retry_count):
    access_api = TatlinAccessAPI(ip, port, username, password, verify)
    tatlin_version = access_api.get_tatlin_version()
    if tatlin_version <= (2, 3):
        return TatlinClientV23(access_api,
                               api_retry_count=api_retry_count,
                               wait_interval=wait_interval,
                               wait_retry_count=wait_retry_count)
    else:
        return TatlinClientV25(access_api,
                               api_retry_count=api_retry_count,
                               wait_interval=wait_interval,
                               wait_retry_count=wait_retry_count)


class TatlinAccessAPI:
    session = None
    ip = None
    port = None
    username = None
    password = None
    verify = False
    _api_version = None

    def __init__(self, ip, port, user, passwd, verify):
        self.ip = ip
        self.port = port
        self.username = user
        self.password = passwd
        self.verify = verify
        self._authenticate_access()

    def _authenticate_access(self):
        LOG.debug('Generating new Tatlin API session')

        self.session = requests.session()
        LOG.debug('SSL verification %s', self.session.verify)
        self.session.verify = self.verify
        if not self.verify:
            requests.packages.urllib3.disable_warnings()

        # Here 'address' will be only IPv4.
        response = self.session.post('https://%s:%d/auth/login'
                                     % (self.ip, self.port),
                                     data={'user': self.username,
                                           'secret': self.password},
                                     verify=self.verify)
        if response.status_code != requests.codes.ok:
            LOG.error('Failed to authenticate to remote cluster at %s for %s.',
                      self.ip, self.username)
            raise exception.NotAuthorized(_('Authentication failure.'))
        result = response.json()
        self.session.headers.update({'X-Auth-Token': result['token']})
        self.session.headers.update({'Content-Type': 'application/json'})

    def send_request(self, path, input_data, method):
        full_url = self._get_api(path)
        resp = self.session.request(
            method, full_url, verify=self.verify, json=input_data)
        LOG.debug('Tatlin response for method %s URL %s %s',
                  method, full_url, resp)
        if resp.status_code == requests.codes.unauthorized:
            LOG.info('Not authenticated. Logging in.')
            self._authenticate_access()
            resp = self.session.request(
                method, full_url, verify=self.verify, json=input_data)
        return resp

    def get_tatlin_version(self):
        if not self._api_version:
            responce = self.send_request(tatlin_api.TATLIN_VERSION,
                                         {}, 'GET')
            ver = responce.json()['build-version'].split('.')
            self._api_version = (int(ver[0]), int(ver[1]))
        LOG.debug('Tatlin version: %s', str(self._api_version))
        return self._api_version

    def _get_api(self, tail):
        return ('https://%s:%d/' % (self.ip, self.port)) + tail


class TatlinClientCommon:
    session = None
    _api = None
    access_api_retry_count = 1

    def __init__(self, tatlin_rest_api, api_retry_count,
                 wait_interval, wait_retry_count):
        self.session = None
        self._api = tatlin_rest_api
        self.access_api_retry_count = api_retry_count
        self.wait_interval = wait_interval
        self.wait_retry_count = wait_retry_count

    def add_vol_to_host(self, vol_id, host_id):
        LOG.debug('Adding volume %s to host %s', vol_id, host_id)
        if self._is_vol_on_host(vol_id, host_id):
            return
        path = tatlin_api.VOLUME_TO_HOST % (vol_id, host_id)
        try:
            self._access_api(path, {}, 'PUT',
                             pass_codes=[requests.codes.bad_request])
        except TatlinAPIException as exp:
            message = _('Unable to add volume %s to host %s error %s' %
                        (vol_id, host_id, exp.message))
            LOG.error(message)
            raise TatlinAPIException(500, message)

        if not self._is_vol_on_host(vol_id, host_id):
            raise exception.VolumeBackendAPIException(
                'Unable to add volume %s to host  %s' % (vol_id, host_id))
        return

    def remove_vol_from_host(self, vol_id, host_id):
        if not self._is_vol_on_host(vol_id, host_id):
            return
        path = tatlin_api.VOLUME_TO_HOST % (vol_id, host_id)
        try:
            LOG.debug('Removing volume %s from host %s', vol_id, host_id)
            self._access_api(path, {}, 'DELETE',
                             pass_codes=[requests.codes.not_found,
                                         requests.codes.bad_request])
        except TatlinAPIException as exp:
            message = _('Unable to remove volume %s from host %s error %s' %
                        (vol_id, host_id, exp.message))
            LOG.error(message)
            raise TatlinAPIException(500, message)

        if self._is_vol_on_host(vol_id, host_id):
            raise exception.VolumeBackendAPIException(
                'Volume %s still on host  %s' % (vol_id, host_id))
        return

    def create_volume(self,
                      vol_id, name,
                      size_in_byte,
                      pool_id,
                      lbaFormat='512e'):

        data = {"name": name,
                "size": size_in_byte,
                "poolId": pool_id,
                "deduplication": False,
                "compression": False,
                "alert_threshold": 0,
                "lbaFormat": lbaFormat
                }
        path = tatlin_api.RESOURCE % vol_id
        LOG.debug('Create volume: volume=%(v3)s path=%(v1)s body=%(v2)s',
                  {'v1': path, 'v2': data, 'v3': vol_id},)

        try:
            self._access_api(path, data, 'PUT')
        except TatlinAPIException as exp:
            message = _('Create volume %s failed due to %s' %
                        (id, exp.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def delete_volume(self, vol_id):
        LOG.debug('Delete volume %s', vol_id)
        path = tatlin_api.RESOURCE % vol_id
        try:
            self._access_api(path, {}, 'DELETE',
                             pass_codes=[requests.codes.not_found,
                                         requests.codes.bad_request])
        except TatlinAPIException as exp:
            message = _('Delete volume %s failed due to %s' %
                        (vol_id, exp.message))
            LOG.error(message)
            raise

    def extend_volume(self, vol_id, new_size_in_byte):
        path = tatlin_api.RESOURCE % vol_id
        data = {"new_size": new_size_in_byte}
        LOG.debug('Extending volume to %s ', new_size_in_byte)
        try:
            self._access_api(path, data, 'POST')
        except TatlinAPIException as exp:
            message = _('Unable to extend volume %s due to %s' %
                        (vol_id, exp.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def get_resource_mapping(self):
        try:
            result, status = self._access_api(tatlin_api.RESOURCE_MAPPING)
            return result
        except TatlinAPIException as exp:
            message = _(
                'TATLIN: Error getting resource mapping information %s' %
                exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def get_all_hosts(self):
        try:
            result, status = self._access_api(tatlin_api.HOSTS)
            return result
        except TatlinAPIException:
            message = _('Unable to get hosts configuration')
            raise exception.VolumeBackendAPIException(message=message)

    def get_host_info(self, host_id):
        try:
            result, stat = self._access_api(tatlin_api.HOSTS + '/' + host_id)
            LOG.debug('Host info for %s is %s', host_id, result)
            return result
        except TatlinAPIException as exp:
            message = _('Unable to get host info %s error %s' %
                        (host_id, exp.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def get_host_id(self, name):
        return self.get_host_id_by_name(name)

    def get_iscsi_cred(self):
        auth_path = tatlin_api.RESOURCE % 'auth'
        try:
            cred, status = self._access_api(auth_path)
        except TatlinAPIException as exp:
            message = _('Unable to get iscsi user cred due to %s' %
                        exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)
        return cred

    def get_host_group_info(self, group_id):
        try:
            result, status = self._access_api(tatlin_api.HOST_GROUPS + '/' +
                                              group_id)
            return result
        except TatlinAPIException as exp:
            message = _('Unable to get host group info %s error %s' %
                        (group_id, exp.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def get_host_group_id(self, name):
        try:
            result, status = self._access_api(tatlin_api.HOST_GROUPS)
            for h in result:
                LOG.debug('Host name: %s Host ID %s', h['name'], h['id'])
                if h['name'] == name:
                    return h['id']
        except TatlinAPIException as exp:
            message = (_('Unable to get id for host group %s error %s') %
                       (name, exp.message))
            LOG.error(message)
        raise exception.VolumeBackendAPIException(
            message='Unable to find host group id for %s' % name)

    def get_volume_ports(self, vol_id):
        if not self.is_volume_exists(vol_id):
            message = _('Unable to get volume info %s' % vol_id)
            LOG.error(message)
            return {}
        path = tatlin_api.RESOURCE % vol_id + '/ports'
        try:
            response, stat = self._access_api(path)
        except TatlinAPIException as exp:
            message = _('Unable to get ports for target %s '
                        'with %s error code: %s' %
                        (vol_id, exp.message, exp.code))
            LOG.error(message)
            return {}
        return response

    def get_resource_ports_array(self, volume_id):
        ports = self.get_volume_ports(volume_id)
        if ports == {}:
            return []
        res = []
        for p in ports:
            res.append(p['port'])
        LOG.debug('Volume %s port list %s', volume_id, res)
        return res

    def get_port_portal(self, portal_type):
        path = tatlin_api.IP_PORTS % portal_type
        try:
            result, stat = self._access_api(path)
        except TatlinAPIException as exp:
            message = _('Failed to get ports info due to %s' % exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)
        return result

    def is_volume_exists(self, vol_id):
        volume_path = tatlin_api.RESOURCE % vol_id
        LOG.debug('get personality statistic: volume_path=%(v1)s ',
                  {'v1': volume_path})
        try:
            volume_result, status = self._access_api(
                volume_path, {}, 'GET',
                pass_codes=[requests.codes.not_found])
            if status == requests.codes.not_found:
                message = _('Volume %s does not exist' % vol_id)
                LOG.debug(message)
                return False
        except TatlinAPIException as exp:
            message = _('Exception Unable to get volume info %s '
                        'due to %s stat: %s' %
                        (vol_id, exp.message, exp.code))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)
        LOG.debug('Volume %s exists', vol_id)
        return True

    def get_volume(self, vol_id):
        volume_path = tatlin_api.RESOURCE % vol_id
        LOG.debug('get personality statistic: volume_path=%(v1)s',
                  {'v1': volume_path})
        try:
            volume_result, stat = self._access_api(
                volume_path, {}, 'GET',
                pass_codes=[requests.codes.not_found])
            if stat == requests.codes.not_found:
                message = _('Unable to get volume info %s due to %s stat: %s' %
                            (vol_id, 'Volume not found', '404'))
                LOG.error(message)
                raise exception.VolumeBackendAPIException(message=message)
        except TatlinAPIException as exp:
            message = _('Unable to get volume info %s due to %s stat: %s' %
                        (vol_id, exp.message, exp.code))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)
        return volume_result

    def get_pool_id_by_name(self, pool_name):
        try:
            result, status = self._access_api(tatlin_api.POOLS)
        except TatlinAPIException as exp:
            message = _('Unable to get pool id for %s due to %s' %
                        pool_name, exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        for p in result:
            if p['name'] == pool_name:
                return p['id']

        message = _('Pool "%s" not found' % pool_name)
        LOG.error(message)
        raise exception.VolumeBackendAPIException(message=message)

    def get_pool_detail(self, pool_id):
        if not pool_id:
            return {}
        path = tatlin_api.POOLS + "/" + pool_id
        try:
            result, status = self._access_api(path)
        except TatlinAPIException as exp:
            message = _('Unable to get pool information for %s due to %s' %
                        (pool_id, exp.message))
            LOG.error(message)
            return {}
        return result

    def get_sys_statistic(self):
        try:
            sys_stat, status = self._access_api(tatlin_api.STATISTICS)
        except TatlinAPIException as exp:
            message = _('Unable to get system statistic due to %s' %
                        exp.message)
            LOG.error(message)
            raise
        return sys_stat

    def get_volume_info(self, vol_name):
        path = tatlin_api.RESOURCE_DETAIL % vol_name
        try:
            result, status = self._access_api(path)
        except TatlinAPIException as exp:
            message = _('Unable to get volume %s error %s' %
                        (vol_name, exp.message))
            LOG.error(message)
            raise exception.ManageExistingInvalidReference(message)

        return result

    def get_tatlin_version(self):
        return self._api.get_tatlin_version()

    def get_resource_count(self, p_id):
        raise NotImplementedError()

    def is_volume_ready(self, id):
        path = tatlin_api.RESOURCE_DETAIL % id
        try:
            result, status = self._access_api(path)
        except TatlinAPIException:
            return False

        for p in result:
            LOG.debug('Volume %s status: %s', id, p['status'])
            if p['status'] != 'ready':
                return False

        return True

    def get_volume_status(self, id):
        path = tatlin_api.RESOURCE_HEALTH % id
        try:
            result, status = self._access_api(path)
        except TatlinAPIException:
            return False

        for p in result:
            LOG.debug('Volume status: %s', p['status'])
            return p['status']

        return ''

    def set_port(self, vol_id, port):
        path = tatlin_api.RESOURCE % vol_id + "/ports/" + port
        try:
            self._access_api(path, {}, 'PUT',
                             pass_codes=[requests.codes.conflict])
        except TatlinAPIException as e:
            message = _('Unable to link port %s for volume %s error %s' %
                        (port, vol_id, e.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def export_volume(self, vol_id, eth_ports):
        raise NotImplementedError()

    def export_vol_to_port_list(self, vol_id, port_list):
        path = tatlin_api.RESOURCE % vol_id + "/ports/list"
        try:
            self._access_api(path,
                             port_list, 'PUT',
                             pass_codes=[
                                 requests.codes.conflict,
                                 requests.codes.bad_request])
        except TatlinAPIException as e:
            message = _('Unable to link ports %s for volume %s error %s' %
                        (port_list, vol_id, e.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def _access_api(self, path, input_data = None, method = None,
                    pass_codes=None):
        @retry(retry_exc, interval=1,
               retries=self.access_api_retry_count)
        def do_access_api(path, input_data, method,
                          pass_codes):
            if input_data is None:
                input_data = {}
            if method is None:
                method = 'GET'
            if pass_codes is None:
                pass_codes = []
            pass_codes = [requests.codes.ok] + pass_codes
            startTime = time.time()
            response = self._api.send_request(path, input_data, method)
            finishTime = time.time()
            duration = str((finishTime - startTime) * 1000) + ' ms'
            postfix = '[FAST]' if finishTime - startTime < 15 else '[SLOW]'
            try:
                result = response.json()
            except ValueError:
                result = {}
            if response.status_code not in pass_codes:
                message = _('Request: method: %s path: %s '
                            'failed with status: %s message: %s in %s %s' %
                            (method, path, str(response.status_code),
                             result, duration, postfix))

                LOG.debug(message)
                raise TatlinAPIException(response.status_code,
                                         message, path=path)
            LOG.debug(
                'Request %s %s successfully finished with %s code in %s %s',
                method, path, str(response.status_code), duration, postfix)
            return result, response.status_code
        return do_access_api(path, input_data, method,
                             pass_codes)

    def _is_vol_on_host(self, vol_id, host_id):
        LOG.debug('Check resource %s in host %s', vol_id, host_id)
        try:
            result, status = self._access_api(tatlin_api.RESOURCE_MAPPING)
        except TatlinAPIException as exp:
            raise exception.VolumeBackendAPIException(
                message=_('Tatlin API exception %s '
                          'while getting resource mapping' % exp.message))

        for entry in result:
            if 'host_id' in entry:
                if entry['resource_id'] == vol_id and \
                        entry['host_id'] == host_id:
                    LOG.debug('Volume %s already on host %s',
                              vol_id, host_id)
                    return True
        LOG.debug('Volume %s not on host %s', vol_id, host_id)
        return False

    def get_unassigned_ports(self, volume_id, eth_ports):
        cur_ports = self.get_resource_ports_array(volume_id)
        LOG.debug('VOLUME %s: Port needed %s actual %s',
                  volume_id, list(eth_ports.keys()), cur_ports)
        return list(set(eth_ports.keys()) - set(cur_ports))

    def is_port_assigned(self, volume_id, port):
        LOG.debug('VOLUME %s: Checking port %s ', volume_id, port)
        cur_ports = self._get_ports(volume_id)
        res = port in cur_ports
        LOG.debug('VOLUME %s: port %s assigned %s',
                  volume_id, port, str(res))
        return res

    def _check_group_mapping(self, vol_id, group_id):
        LOG.debug('Check resource %s in group %s', vol_id, group_id)
        try:
            result, status = self._access_api(tatlin_api.RESOURCE_MAPPING)
        except TatlinAPIException as exp:
            raise exception.VolumeBackendAPIException(
                message=_('Tatlin API exception %s '
                          'while getting resource mapping' % exp.message))

        for entry in result:
            if entry['resource_id'] == vol_id and \
                    entry['host_group_id'] == group_id:
                return True
        return False

    def update_qos(self, vol_id, iops, bandwith):
        pass

    def get_host_id_by_name(self, host_name):
        try:
            result, status = self._access_api(tatlin_api.HOSTS)
            for h in result:
                LOG.debug('For host %s Host name: %s Host ID %s',
                          host_name, h['name'], h['id'])
                if h['name'] == host_name:
                    return h['id']
        except TatlinAPIException as exp:
            message = _('Unable to get host information %s' % exp.message)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        raise exception.VolumeBackendAPIException(
            message='Unable to get host_id for host %s' % host_name)


class TatlinClientV25 (TatlinClientCommon):

    def update_qos(self, vol_id, iops, bandwith):
        path = tatlin_api.RESOURCE % vol_id
        data = {"limit_iops": int(iops),
                "limit_bw": int(bandwith),
                "tags": []}
        try:
            result, status = self._access_api(path, data, 'POST')
            LOG.debug('Responce %s stat %s', result, status)
        except TatlinAPIException as exp:
            message = (_('Unable to update QoS for volume %s due to %s') %
                       (vol_id, exp.message))
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def export_volume(self, vol_id, eth_ports):
        LOG.debug('VOLUME %s: Export to ports %s started',
                  vol_id, eth_ports)

        to_export = self.get_unassigned_ports(vol_id, eth_ports)
        if not to_export:
            LOG.debug('VOLUME %s: all ports already assigned', vol_id)
            return
        self.export_vol_to_port_list(vol_id, to_export)

        for i in range(self.wait_retry_count):
            if not self.get_unassigned_ports(vol_id, eth_ports):
                LOG.debug('VOLUME %s: Export ports %s finished',
                          vol_id, eth_ports)
                return
            time.sleep(self.wait_interval)

        message = (_('VOLUME %s: Unable to export volume to %s') %
                   (vol_id, eth_ports))
        raise exception.VolumeBackendAPIException(message=message)

    def get_resource_count(self, p_id):
        try:
            result, status = self._access_api(tatlin_api.RESOURCE_COUNT)
        except TatlinAPIException:
            message = _('Unable to get resource count')
            LOG.error(message)
            raise exception.ManageExistingInvalidReference(message)

        poll_resource = 0
        cluster_resources = 0
        for key in result:
            if key == p_id:
                poll_resource = result[key]
            cluster_resources = cluster_resources + result[key]
        return poll_resource, cluster_resources


class TatlinClientV23 (TatlinClientCommon):

    def export_volume(self, vol_id, eth_ports):
        LOG.debug('Export ports %s for volume %s started',
                  eth_ports, vol_id)
        for port in eth_ports:
            LOG.debug('Check port %s for volume %s', port, vol_id)
            if not self.is_port_assigned(vol_id, port):
                try:
                    self.set_port(vol_id, port)
                except TatlinAPIException as e:
                    raise exception.VolumeBackendAPIException(
                        message=e.message)
        LOG.debug('Export ports %s for volume %s finished',
                  eth_ports, vol_id)

        for i in range(self.wait_retry_count):
            if not self.get_unassigned_ports(vol_id, eth_ports):
                LOG.debug('VOLUME %s: Export ports %s finished',
                          vol_id, eth_ports)
                return
            time.sleep(self.wait_interval)

        message = (_('VOLUME %s: Unable to export volume to %s') %
                   (vol_id, eth_ports))
        raise exception.VolumeBackendAPIException(message=message)

    def get_resource_count(self, p_id):
        try:
            response, status = self._access_api(tatlin_api.ALL_RESOURCES)
            if response is not None:
                return 0, len(response)
        except TatlinAPIException:
            message = (_('Unable to get resource list'))
            LOG.error(message)
            return 0, 0
        return 0, 0
