# Copyright 2016 ZTE Corporation. All rights reserved
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""
Volume driver for ZTE storage systems.
"""

import hashlib
import json

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import six
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.zte import zte_pub


LOG = logging.getLogger(__name__)

zte_opts = [
    cfg.IPOpt('zteControllerIP0', default=None,
              help='Main controller IP.'),
    cfg.IPOpt('zteControllerIP1', default=None,
              help='Slave controller IP.'),
    cfg.IPOpt('zteLocalIP', default=None, help='Local IP.'),
    cfg.StrOpt('zteUserName', default=None, help='User name.'),
    cfg.StrOpt('zteUserPassword', default=None, secret=True,
               help='User password.'),
    cfg.IntOpt('zteChunkSize', default=4,
               help='Virtual block size of pool. '
                    'Unit : KB. '
                    'Valid value :  4,  8, 16, 32, 64, 128, 256, 512. '),
    cfg.IntOpt('zteAheadReadSize', default=8, help='Cache readahead size.'),
    cfg.IntOpt('zteCachePolicy', default=1,
               help='Cache policy. '
                    '0, Write Back; 1, Write Through.'),
    cfg.IntOpt('zteSSDCacheSwitch', default=1,
               help='SSD cache switch. '
                    '0, OFF; 1, ON.'),
    cfg.ListOpt('zteStoragePool', default=[], help='Pool name list.'),
    cfg.IntOpt('ztePoolVoAllocatedPolicy', default=0,
               help='Pool volume allocated policy. '
                    '0, Auto; '
                    '1, High Performance Tier First; '
                    '2, Performance Tier First; '
                    '3, Capacity Tier First.'),
    cfg.IntOpt('ztePoolVolMovePolicy', default=0,
               help='Pool volume move policy.'
                    '0, Auto; '
                    '1, Highest Available; '
                    '2, Lowest Available; '
                    '3, No Relocation.'),
    cfg.BoolOpt('ztePoolVolIsThin', default=False,
                help='Whether it is a thin volume.'),
    cfg.IntOpt('ztePoolVolInitAllocatedCapacity', default=0,
               help='Pool volume init allocated Capacity.'
                    'Unit : KB. '),
    cfg.IntOpt('ztePoolVolAlarmThreshold', default=0,
               help='Pool volume alarm threshold. [0, 100]'),
    cfg.IntOpt('ztePoolVolAlarmStopAllocatedFlag', default=0,
               help='Pool volume alarm stop allocated flag.')
]

CONF = cfg.CONF
CONF.register_opts(zte_opts, group=configuration.SHARED_CONF_GROUP)


class ZTEVolumeDriver(driver.VolumeDriver):

    VERSION = "1.0.0"

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "ZTE_cinder2_CI"

    def __init__(self, *args, **kwargs):
        super(ZTEVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(zte_opts)
        self.url = ''
        self.login_info = {}
        self.session_id = ''

    def _get_md5(self, src_string):
        md5obj = hashlib.md5()
        md5obj.update(src_string.encode('UTF-8'))
        md5_string = md5obj.hexdigest()
        md5_string = md5_string[0:19]
        return md5_string

    def _call_method(self, method='', params=None):
        sid = self._get_sessionid()
        return self._call(sid, method, params)

    def _call(self, sessin_id='', method='', params=None):
        try:
            params = params or {}
            data = ("sessionID=" + sessin_id + "&method=" +
                    method + "&params=" + json.dumps(params))
            LOG.debug('Req Data: method %(method)s  data %(data)s.',
                      {'method': method, 'data': data})
            headers = {"Connection": "keep-alive",
                       "Content-Type": "application/x-www-form-urlencoded"}
            req = urllib.request.Request(self.url, data, headers)
            req.get_method = lambda: 'POST'
            # self.url used for req is coded to always use the HTTPS scheme
            response = urllib.request.urlopen(req,  # nosec
                                              timeout=
                                              zte_pub.ZTE_DEFAULT_TIMEOUT
                                              ).read()
            LOG.debug('Response Data: method %(method)s res %(res)s.',
                      {'method': method, 'res': response})
        except Exception:
            LOG.exception('Bad response from server.')
            msg = (_('_call failed.'))
            raise exception.VolumeBackendAPIException(data=msg)
        res_json = json.loads(response)
        return res_json

    def _get_server(self):
        controller_ip = (self.login_info['ControllerIP0']
                         or self.login_info['ControllerIP1'] or '')
        self.url = 'https://' + controller_ip + '/phpclient/client.php'
        LOG.debug('Set ZTE server is %s.', self.url)

    def _change_server(self):
        if (self.login_info['ControllerIP0'] and
                self.login_info['ControllerIP1']):
            controller_ip = (self.login_info['ControllerIP1']
                             if self.login_info['ControllerIP0'] in self.url
                             else self.login_info['ControllerIP0'])
            self.url = 'https://' + controller_ip + '/phpclient/client.php'

    def _user_login(self):
        loginfo = {'UserName': self.login_info['UserName'],
                   'UserPassword': self.login_info['UserPassword'],
                   'LocalIP': self.login_info['LocalIP'],
                   'LoginType': zte_pub.ZTE_WEB_LOGIN_TYPE}

        result = self._call('""', 'plat.session.signin', loginfo)

        if result['returncode'] in [zte_pub.ZTE_SUCCESS,
                                    zte_pub.ZTE_SESSION_EXIST]:
            self.session_id = result['data']['sessionID']
            return self.session_id
        else:
            err_msg = (
                _('Failed to login. Return code: %(ret)s.') % {
                    'ret': result['returncode']})
            raise exception.VolumeBackendAPIException(
                data=err_msg)

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        self.login_info = {
            'ControllerIP0': self.configuration.zteControllerIP0,
            'ControllerIP1': self.configuration.zteControllerIP1,
            'LocalIP': self.configuration.zteLocalIP,
            'UserName': self.configuration.zteUserName,
            'UserPassword': self.configuration.zteUserPassword}
        self._get_server()
        try:
            self.session_id = self._user_login()
        except exception.VolumeBackendAPIException:
            self._change_server()
            self.session_id = self._user_login()

    def check_for_setup_error(self):

        zteControllerIP0 = self.configuration.zteControllerIP0
        if zteControllerIP0 is None:
            msg = (_("Controller IP is missing for ZTE driver."))
            raise exception.VolumeBackendAPIException(data=msg)

        zteUserName = self.configuration.zteUserName
        if zteUserName is None:
            msg = (_("User Name is missing for ZTE driver."))
            raise exception.VolumeBackendAPIException(data=msg)

        zteUserPassword = self.configuration.zteUserPassword
        if zteUserPassword is None:
            msg = (_("User Password is missing for ZTE driver."))
            raise exception.VolumeBackendAPIException(data=msg)

    def _get_sessionid(self):
        try:
            sid = self.session_id
            ret = self._call(sid, 'plat.session.heartbeat')
            if ret['returncode'] == zte_pub.ZTE_SUCCESS:
                return sid
            else:
                LOG.info('heartbeat failed. Return code: %(ret)s.',
                         {'ret': ret['returncode']})
        except Exception:
            LOG.exception('_get_sessionid error.')

        self._change_server()
        return self._user_login()

    def _get_pool_list(self):
        pool_info_list = []

        for pool_name in self.configuration.zteStoragePool:
            if pool_name:
                ret = self._call_method(
                    'GetPoolInfo', {
                        'scPoolName': pool_name})
                pool_info = {'name': pool_name}
                if ((ret['returncode'] == zte_pub.ZTE_SUCCESS) and
                        (ret['data']['sdwState'] == zte_pub.ZTE_STATUS_OK)):
                    total_capacity = ret['data']['qwTotalCapacity']
                    free_capacitity = ret['data']['qwFreeCapacity']
                    pool_info['total'] = (
                        float(total_capacity) / units.Ki)
                    pool_info['free'] = (
                        float(free_capacitity) / units.Ki)
                    pool_info_list.append(pool_info)
        if not pool_info_list:
            err_msg = (_('No pool available.'))
            raise exception.VolumeBackendAPIException(data=err_msg)
        return pool_info_list

    def _find_pool_to_create_volume(self):
        pool_list = self._get_pool_list()
        pool = max(pool_list, key=lambda arg: arg['free'])
        return pool['name']

    def _create_volume_in_pool(self, volume_name, volume_size, pool_name):

        vol = {
            'scPoolName': pool_name,
            'scVolName': volume_name,
            'sdwStripeDepth': self.configuration.zteChunkSize,
            'qwCapacity': float(volume_size),
            'sdwCtrlPrefer': 0xFFFF,
            'sdwCachePolicy': self.configuration.zteCachePolicy,
            'sdwAheadReadSize': self.configuration.zteAheadReadSize,
            'sdwAllocPolicy': self.configuration.ztePoolVoAllocatedPolicy,
            'sdwMovePolicy': self.configuration.ztePoolVolMovePolicy,
            'udwIsThinVol': self.configuration.ztePoolVolIsThin,
            'uqwInitAllocedCapacity':
            self.configuration.ztePoolVolInitAllocatedCapacity,
            'sdwAlarmThreshold':
            self.configuration.ztePoolVolAlarmThreshold,
            'sdwAlarmStopAllocFlag':
            self.configuration.ztePoolVolAlarmStopAllocatedFlag,
            'dwSSDCacheSwitch': self.configuration.zteSSDCacheSwitch}

        ret = self._call_method('CreateVolOnPool', vol)
        if ret['returncode'] not in [zte_pub.ZTE_ERR_OBJECT_EXIST,
                                     zte_pub.ZTE_SUCCESS]:
            err_msg = (
                _('Create volume failed. Volume name: %(name)s. '
                  'Return code: %(ret)s.') %
                {'name': volume_name,
                 'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(
                data=err_msg)

    def _create_volume(self, volume_name, volume_size):
        pool_name = self._find_pool_to_create_volume()
        if pool_name:
            self._create_volume_in_pool(volume_name, volume_size, pool_name)
        else:
            msg = _('No pool available.')
            raise exception.VolumeDriverException(message=msg)

    def create_volume(self, volume):
        """Create a new volume."""
        volume_name = self._translate_volume_name(volume['name'])

        volume_size = float(volume['size'] * units.Mi)
        self._create_volume(volume_name, volume_size)

    def _delete_clone_volume(self, cloned_name):
        cloned_name += zte_pub.ZTE_CLONE_SUFFIX
        cvol_name = {'scCvolName': cloned_name}
        ret = self._call_method('DelCvol', cvol_name)

        if ret['returncode'] not in [zte_pub.ZTE_ERR_CLONE_OR_SNAP_NOT_EXIST,
                                     zte_pub.ZTE_ERR_VAS_OBJECT_NOT_EXIST,
                                     zte_pub.ZTE_SUCCESS]:
            err_msg = (_('Delete volume failed. Clone name: %(name)s. '
                         'Return code: %(ret)s.') %
                       {'name': cloned_name,
                        'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _remove_volume_from_group(self, volume):
        ret = self._call_method('GetGrpNamesOfVol', {'cVolName': volume})
        if ret['returncode'] == zte_pub.ZTE_SUCCESS:
            group_num = int(ret['data']['sdwMapGrpNum'])
            for index in range(0, group_num):
                group_name = ret['data']['cMapGrpNames'][index]
                lun_ID = ret['data']['sdwLunLocalId'][index]
                self._map_delete_lun(lun_ID, group_name)

    def _delete_volume(self, volume_name):
        vol_name = {'cVolName': volume_name}
        ret = self._call_method('DelVol', vol_name)
        if ret['returncode'] not in [zte_pub.ZTE_ERR_VOLUME_NOT_EXIST,
                                     zte_pub.ZTE_ERR_LUNDEV_NOT_EXIST,
                                     zte_pub.ZTE_SUCCESS]:
            err_msg = (_('Delete volume failed. Volume name: %(name)s.'
                         'Return code: %(ret)s.') %
                       {'name': volume_name,
                        'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def delete_volume(self, volume):
        """Delete a volume."""
        volume_name = self._translate_volume_name(volume['name'])
        LOG.debug('delete_volume: volume name: %s.', volume_name)

        self._delete_clone_relation_by_volname(volume_name, False)
        self._remove_volume_from_group(volume_name)
        self._delete_volume(volume_name)

    def _delete_cvol(self, cloned_name, issnapshot):
        cvol_name = {'scCvolName': cloned_name}
        ret = self._call_method('SyncForceDelCvol', cvol_name)
        if ret['returncode'] not in [zte_pub.ZTE_ERR_CLONE_OR_SNAP_NOT_EXIST,
                                     zte_pub.ZTE_ERR_VAS_OBJECT_NOT_EXIST,
                                     zte_pub.ZTE_SUCCESS]:
            err_msg = (_('_delete_cvol: Failed to delete clone vol. '
                         'cloned name: %(name)s with Return code: '
                         '%(ret)s.') %
                       {'name': cloned_name, 'ret': ret['returncode']})
            if ret['returncode'] == zte_pub.ZTE_VOLUME_TASK_NOT_FINISHED:
                if issnapshot:
                    raise exception.SnapshotIsBusy(snapshot_name=cloned_name)
                else:
                    raise exception.VolumeIsBusy(volume_name=cloned_name)
            else:
                raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_clone_relation_by_volname(self, volname, issnapshot):
        svol_name = {'scVolName': volname}
        LOG.debug('GetCvolNamesOnVol: volume name: %s.', volname)

        ret = self._call_method('GetCvolNamesOnVol', svol_name)
        data_info = ret['data']
        if ret['returncode'] == zte_pub.ZTE_SUCCESS:
            sccvolnames = data_info['scCvolNames']
            for i in range(0, ret['data']['sdwCvolNum']):
                cloned_name = sccvolnames[i]['scCvolName']
                self._delete_cvol(cloned_name, issnapshot)

        cloned_name = volname + zte_pub.ZTE_CLONE_SUFFIX
        self._delete_cvol(cloned_name, False)

    def _create_snapshot(
            self,
            snapshot_name,
            src_vol,
            src_vol_size,
            snapshot_mode):
        svol_paras = {
            'scVolName': src_vol,
            'scSnapName': snapshot_name,
            'sdwSnapType': 1,
            'swRepoSpaceAlarm': 60,
            'swRepoOverflowPolicy': 0,
            'sqwRepoCapacity': float(src_vol_size * units.Mi),
            'ucIsAgent': 0,
            'ucSnapMode': snapshot_mode,
            'is_private': 0,
            'ucIsAuto': 0}
        ret = self._call_method('CreateSvol', svol_paras)
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('Failed to create snap.snap name: %(snapname)s,'
                         'srvol name :%(srv)s with Return code: %(ret)s. ') %
                       {'snapname': snapshot_name,
                        'srv': src_vol,
                        'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_snapshot(self, snapshot):
        """create a snapshot from volume"""
        snapshot_name = self._translate_volume_name(snapshot['name'])
        volume_name = self._translate_volume_name(snapshot['volume_name'])
        volume_size = snapshot['volume_size']
        self._create_snapshot(snapshot_name,
                              volume_name,
                              volume_size,
                              zte_pub.ZTE_SNAPSHOT_MODE_RW)

    def _delete_snapshot(self, snapshot_name):
        svol_name = {'scSnapName': snapshot_name}

        ret = self._call_method('DelSvol', svol_name)
        if ret['returncode'] not in [zte_pub.ZTE_ERR_CLONE_OR_SNAP_NOT_EXIST,
                                     zte_pub.ZTE_ERR_VAS_OBJECT_NOT_EXIST,
                                     zte_pub.ZTE_SUCCESS]:
            err_msg = (_('_delete_snapshot:Failed to delete snap.'
                         'snap name: %(snapname)s with Return code: '
                         '%(ret)s.') %
                       {'snapname': snapshot_name,
                        'ret': ret['returncode']})
            if ret['returncode'] == zte_pub.ZTE_ERR_SNAP_EXIST_CLONE:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot_name)
            else:
                raise exception.VolumeBackendAPIException(data=err_msg)

    def delete_snapshot(self, snapshot):
        """delete a snapshot volume"""
        snapshot_name = self._translate_volume_name(snapshot['name'])
        self._delete_clone_relation_by_volname(snapshot_name, True)
        self._delete_snapshot(snapshot_name)

    def _extend_volume(self, volume_name, inc_size):
        ext_vol_paras = {'scVolName': volume_name,
                         'qwExpandCapacity':
                             float(inc_size * units.Ki)}

        ret = self._call_method('ExpandVolOnPool', ext_vol_paras)
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('_extend_volume:Failed to extend vol.vol name:'
                         '%(name)s with Return code: %(ret)s.') %
                       {'name': volume_name, 'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def extend_volume(self, volume, new_size):
        """extend volume size"""
        size_increase = (int(new_size)) - volume['size']
        volume_name = self._translate_volume_name(volume['name'])
        self._extend_volume(volume_name, size_increase)

    def _cloned_volume(self, cloned_name, src_name, vol_size, vol_type):
        self._create_volume(cloned_name, vol_size)

        cvol_paras = {
            'scCvolName': cloned_name + zte_pub.ZTE_CLONE_SUFFIX,
            'scBvolName': src_name,
            'scTargetName': cloned_name,
            'sdwInitSync': 1,
            'sdwProtectRestore': 0,
            'sdwPri': 0,
            'sdwPolicy': 0,
            'sdwBvolType': vol_type}

        ret = self._call_method('CreateCvol', cvol_paras)
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            self._delete_volume(cloned_name)
            err_msg = (_('_cloned_volume: Failed to clone vol. '
                         'vol name: %(name)s with Return code: %(ret)s. ') %
                       {'name': src_name,
                        'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_cloned_volume(self, volume, src_vref):
        """clone a volume"""
        bvol_name = self._translate_volume_name(src_vref['name'])
        cvol_name = self._translate_volume_name(volume['name'])
        if volume['size'] < src_vref['size']:
            err_msg = (_('Cloned volume size invalid. '
                         'Clone size: %(cloned_size)s. '
                         'Src volume size: %(volume_size)s.') %
                       {'cloned_size': volume['size'],
                        'volume_size': src_vref['size']})
            raise exception.VolumeDriverException(message=err_msg)
        else:
            volume_size = float(
                volume['size'] * units.Mi)

        try:
            self._cloned_volume(
                cvol_name,
                bvol_name,
                volume_size,
                zte_pub.ZTE_VOLUME)
        except Exception:
            self._delete_clone_relation_by_volname(bvol_name, False)
            self._cloned_volume(
                cvol_name,
                bvol_name,
                volume_size,
                zte_pub.ZTE_VOLUME)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create volume from snapshot """
        bvol_name = self._translate_volume_name(snapshot['name'])
        cvol_name = self._translate_volume_name(volume['name'])
        if volume['size'] < snapshot['volume_size']:
            err_msg = (
                _('Cloned volume size invalid. '
                  'Clone size: %(cloned_size)s. '
                  'Src volume size: %(volume_size)s.') %
                {'cloned_size': volume['size'],
                 'volume_size': snapshot['volume_size']})
            raise exception.VolumeDriverException(message=err_msg)
        else:
            volume_size = float(
                volume['size'] * units.Mi)

        try:
            self._cloned_volume(
                cvol_name,
                bvol_name,
                volume_size,
                zte_pub.ZTE_SNAPSHOT)
        except Exception:
            self._delete_clone_relation_by_volname(bvol_name, False)
            self._cloned_volume(
                cvol_name,
                bvol_name,
                volume_size,
                zte_pub.ZTE_SNAPSHOT)

    def create_export(self, context, volume, connector):
        """Exports the volume """
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for a existing volume."""
        pass

    def remove_export(self, context, volume_id):
        """Driver entry point to remove an export for a volume."""
        pass

    def get_volume_stats(self, refresh=False):
        """Get volume status."""
        if refresh:
            self._update_volume_status()

        return self._stats

    def _translate_host_name(self, host_name):
        new_name = 'host_' + six.text_type(self._get_md5(host_name))
        new_name = new_name.replace('-', 'R')
        LOG.debug('_translate_host_name: Name in cinder: %(old)s, '
                  'new name in storage system: %(new)s.',
                  {'old': host_name, 'new': new_name})

        return new_name

    def _translate_volume_name(self, vol_name):
        new_name = zte_pub.ZTE_VOL_NAME_PREFIX_NEW + six.text_type(
            self._get_md5(vol_name))
        new_name = new_name.replace('-', 'R')

        LOG.debug('_translate_volume_name: Name in cinder: %(old)s, '
                  'new name in storage system: %(new)s.',
                  {'old': vol_name, 'new': new_name})

        return new_name

    def _get_lunid_from_vol(self, volume_name, map_group_name):
        map_grp_info = {'cMapGrpName': map_group_name}
        ret = self._call_method('GetMapGrpInfo', map_grp_info)
        if ret['returncode'] == zte_pub.ZTE_SUCCESS:
            lun_num = int(ret['data']['sdwLunNum'])
            lun_info = ret['data']['tLunInfo']
            for count in range(0, lun_num):
                if volume_name == lun_info[count]['cVolName']:
                    return lun_info[count]['sdwLunId']
            return None
        elif ret['returncode'] == zte_pub.ZTE_ERR_GROUP_NOT_EXIST:
            return None
        else:
            err_msg = (_('_get_lunid_from_vol:Get lunid from vol fail. '
                         'Group name:%(name)s vol:%(vol)s '
                         'with Return code: %(ret)s.') %
                       {'name': map_group_name,
                        'vol': volume_name,
                        'ret': ret['returncode']})
            raise exception.VolumeDriverException(message=err_msg)

    def _get_group_lunnum(self, map_group_name):
        map_grp_info = {'cMapGrpName': map_group_name}
        ret = self._call_method('GetMapGrpInfo', map_grp_info)
        if ret['returncode'] == zte_pub.ZTE_SUCCESS:
            lun_num = ret['data']['sdwLunNum']
            return int(lun_num)
        elif ret['returncode'] == zte_pub.ZTE_ERR_GROUP_NOT_EXIST:
            return -1
        else:
            err_msg = (_('_get_group_lunnum:Get group info fail. '
                         'Group name:%(name)s with Return code: %(ret)s.') %
                       {'name': map_group_name, 'ret': ret['returncode']})
            raise exception.VolumeDriverException(message=err_msg)

    def _delete_group(self, map_group_name):
        # before delete the group, we must delete the hosts in group
        self._map_delete_host(map_group_name)

        map_grp_info = {'cMapGrpName': map_group_name}
        ret = self._call_method('DelMapGrp', map_grp_info)
        if ret['returncode'] not in [zte_pub.ZTE_SUCCESS,
                                     zte_pub.ZTE_ERR_GROUP_NOT_EXIST]:
            err_msg = (_('_delete_group:Del group fail. '
                         'Group name:%(name)s with Return code: %(ret)s.') %
                       {'name': map_group_name, 'ret': ret['returncode']})
            raise exception.VolumeDriverException(message=err_msg)

    def _map_add_lun(self, volume_name, map_group_name):
        add_vol_to_grp = {
            'cMapGrpName': map_group_name,
            'sdwLunId': 0,
            'cVolName': volume_name}
        ret = self._call_method('AddVolToGrp', add_vol_to_grp)

        if ret['returncode'] in [zte_pub.ZTE_SUCCESS,
                                 zte_pub.ZTE_VOLUME_IN_GROUP,
                                 zte_pub.ZTE_ERR_VOL_EXISTS]:
            return self._get_lunid_from_vol(volume_name, map_group_name)

        err_msg = (
            _(
                '_map_add_lun:fail to add vol to grp. group name:%(name)s'
                ' lunid:%(lun)s '
                'vol:%(vol)s with Return code: %(ret)s') %
            {'name': map_group_name,
             'lun': 0,
             'vol': volume_name,
             'ret': ret['returncode']})
        raise exception.VolumeDriverException(message=err_msg)

    def _update_volume_group_info(self):
        pool_list = self._get_pool_list()
        pool_info = {'total': 0, 'free': 0}

        for item in pool_list:
            pool_info['total'] += item['total']
            pool_info['free'] += item['free']
        return pool_info

    def _get_sysinfo(self):
        ret = self._call_method('GetSysInfo')
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('_get_sysinfo:get sys info failed. Return code: '
                         '%(ret)s.'),
                       {'ret': ret['returncode']})
            raise exception.VolumeDriverException(message=err_msg)

        return ret['data']

    def _update_volume_status(self):
        LOG.debug("Updating volume status")

        sys_info = self._get_sysinfo()
        backend_name = self.configuration.safe_get('volume_backend_name')
        pool_info = self._update_volume_group_info()
        data = {
            "volume_backend_name": backend_name or 'ZteISCSIDriver',
            'vendor_name': sys_info['cVendor'],
            'driver_version': sys_info['cVersionName'],
            'storage_protocol': 'iSCSI',
            'multiattach': False,
            'total_capacity_gb': pool_info['total'],
            'free_capacity_gb': pool_info['free'],
            'reserved_percentage': 0,
            'QoS_support': False}

        self._stats = data

    def _create_group(self, initiator_name, map_group_name):
        pass

    def _map_delete_host(self, map_group_name):
        pass

    def _map_delete_lun(self, lunid, initiator_name):
        pass


@interface.volumedriver
class ZteISCSIDriver(ZTEVolumeDriver, driver.ISCSIDriver):
    """Zte iSCSI volume driver."""

    # ThirdPartySystems wiki page
    WIKI_CI_NAME = "ZTE_cinder2_CI"

    # TODO(smcginnis) Remove driver in Queens if CI issues not fixed
    SUPPORTED = False

    def __init__(self, *args, **kwargs):
        super(ZteISCSIDriver, self).__init__(*args, **kwargs)

    def _map_lun(self, initiator_name, volume_name, map_group_name):
        self._create_group(initiator_name, map_group_name)
        return self._map_add_lun(volume_name, map_group_name)

    def _get_net_cfg_ips(self):
        ret = self._call_method('GetSystemNetCfg')
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('get_Net_Cfg failed. Return code: %(ret)s.') %
                       {'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

        targetips = []
        net_cfg_info = ret['data']['tSystemNetCfg']
        for item in range(ret['data']['sdwDeviceNum']):
            if (net_cfg_info[item]['udwRoleType'] == 0 and
                    net_cfg_info[item]['cIpAddr']):
                targetips.append(net_cfg_info[item]['cIpAddr'])
        return targetips

    @utils.synchronized('zte_locked_initialize_connection')
    def initialize_connection(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        initiator_name = connector['initiator']
        volume_name = self._translate_volume_name(volume['name'])

        LOG.debug('initialize_connection: Volume name: %(volume)s. '
                  'Initiator name: %(ini)s.',
                  {'volume': volume_name,
                   'ini': initiator_name})

        iscsi_conf = self._get_iscsi_info()
        target_ips = iscsi_conf['DefaultTargetIPs']

        target_portals = {}
        target_iqns = []
        for ip in target_ips:
            iqn = self._get_tgt_iqn(ip)
            if iqn:
                if iqn not in target_iqns:
                    target_iqns.append(iqn)
                    target_portals[iqn] = ['%s:%s' % (ip, '3260')]
                else:
                    target_portals[iqn].append('%s:%s' % (ip, '3260'))
        if not target_iqns:
            msg = (_('Failed to get target ip or iqn '
                     'for initiator %(ini)s, please check config file.') %
                   {'ini': initiator_name})
            raise exception.VolumeDriverException(message=msg)

        map_group_name = self._translate_grp_name(initiator_name)
        lunid = self._map_lun(initiator_name, volume_name, map_group_name)

        # Return iSCSI properties.
        properties = {
            'target_discovered': False,
            'target_portal': target_portals[
                target_iqns[0]][0],
            'target_iqn': target_iqns[0],
            'target_lun': lunid,
            'volume_id': volume['id']}

        if target_iqns and target_portals:
            properties['target_portals'] = target_portals
            properties['target_iqns'] = target_iqns

        return {'driver_volume_type': 'iscsi', 'data': properties}

    @utils.synchronized('zte_locked_initialize_connection')
    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        initiator_name = connector['initiator']
        volume_name = self._translate_volume_name(volume['name'])
        LOG.debug('volume name: %(volume)s, initiator name: %(ini)s.',
                  {'volume': volume_name,
                   'ini': initiator_name})

        map_group_name = self._translate_grp_name(initiator_name)
        lunid = self._get_lunid_from_vol(volume_name, map_group_name)
        self._map_delete_lun(lunid, initiator_name)

    def _get_iscsi_info(self):
        iscsi_info = {}
        try:
            iscsi_info['DefaultTargetIPs'] = self._get_net_cfg_ips()
            if not iscsi_info['DefaultTargetIPs']:
                err_msg = _('Can not get target ip address. ')
                raise exception.VolumeBackendAPIException(data=err_msg)
            initiator_list = []
            iscsi_info['Initiator'] = initiator_list

        except Exception:
            LOG.exception('_get_iscsi_info error.')
            raise

        return iscsi_info

    def _translate_grp_name(self, grp_name):
        new_name = zte_pub.ZTE_HOST_GROUP_NAME_PREFIX + six.text_type(
            self._get_md5(grp_name))
        new_name = new_name.replace('-', 'R')

        LOG.debug('_translate_grp_name:Name in cinder: %(old)s, '
                  'new name in storage system: %(new)s.',
                  {'old': grp_name,
                   'new': new_name})

        return new_name

    def _get_target_ip_ctrl(self, target_ip):
        LOG.debug('_get_target_ip_ctrl:target IP is %s.', target_ip)
        ret = self._call_method('GetSystemNetCfg')
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('_get_target_ip_ctrl:get iscsi port list fail. '
                         'with Return code: %(ret)s.') %
                       {'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)
        count = ret['data']['sdwDeviceNum']
        for index in range(0, count):
            systemnetcfg = ret['data']['tSystemNetCfg'][index]
            if target_ip == systemnetcfg['cIpAddr']:
                return systemnetcfg['udwCtrlId']
        return None

    def _get_tgt_iqn(self, iscsiip):
        # as the given iscsiip,we need to find it's ctrl number
        ip_ctrl = self._get_target_ip_ctrl(iscsiip)

        if ip_ctrl is None:
            LOG.exception('_get_tgt_iqn:get iscsi ip ctrl fail, '
                          'IP is %s.', iscsiip)
            return None

        # get the ctrl iqn
        ret = self._call_method('GetIscsiTargetName')
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            return None

        target_info = ret['data']['tIscsiTargetInfo']
        ctrl_count = ret['data']['udwCtrlCount']
        for index in range(0, ctrl_count):
            if ip_ctrl == target_info[index]['udwCtrlId']:
                return target_info[index]['cTgtName']
        return None

    def _create_group(self, initiator_name, map_group_name):

        map_grp_info = {'cMapGrpName': map_group_name}
        ret = self._call_method('CreateMapGrp', map_grp_info)

        if ((ret['returncode'] == zte_pub.ZTE_SUCCESS) or
                (ret['returncode'] == zte_pub.ZTE_ERR_GROUP_EXIST)):
            host_name = self._translate_host_name(initiator_name)
            host_info = {'cHostAlias': host_name, 'ucOs': 1, 'ucType': 1,
                         'cPortName': initiator_name,
                         'sdwMultiPathMode': 1, 'cMulChapPass': ''}

            # create host
            ret = self._call_method('CreateHost', host_info)
            if ret['returncode'] not in [zte_pub.ZTE_SUCCESS,
                                         zte_pub.ZTE_ERR_HOSTNAME_EXIST,
                                         zte_pub.ZTE_ERR_PORT_EXIST,
                                         zte_pub.ZTE_ERR_PORT_EXIST_OLD]:
                err_msg = (
                    _('create host failed. Host name:%(name)s '
                      'with Return code: %(ret)s.') %
                    {'name': host_name, 'ret': ret['returncode']})
                raise exception.VolumeBackendAPIException(data=err_msg)

            # If port deleted by user, add it.
            port_info = {
                'cHostAlias': host_name,
                'ucType': 1,
                'cPortName': initiator_name,
                'sdwMultiPathMode': 1,
                'cMulChapPass': ''}
            ret = self._call_method('AddPortToHost', port_info)
            if ret['returncode'] not in [zte_pub.ZTE_SUCCESS,
                                         zte_pub.ZTE_ERR_PORT_EXIST,
                                         zte_pub.ZTE_ERR_PORT_EXIST_OLD]:
                err_msg = (_('_create_group:add port failed. Port name: '
                             '%(name)s  with Return code: %(ret)s.') %
                           {'name': initiator_name,
                            'ret': ret['returncode']})
                raise exception.VolumeBackendAPIException(data=err_msg)

            host_in_grp = {
                'ucInitName': host_name,
                'cMapGrpName': map_group_name}
            ret = self._call_method('AddHostToGrp', host_in_grp)
            if ret['returncode'] not in [zte_pub.ZTE_SUCCESS,
                                         zte_pub.ZTE_ERR_HOST_EXIST,
                                         zte_pub.ZTE_ERR_HOST_EXIST_OLD]:
                self._delete_group(map_group_name)
                err_msg = (_('_create_group:add host to group failed. '
                             'group name:%(name)s init name :%(init)s '
                             'with Return code: %(ret)s.') %
                           {'name': map_group_name,
                            'init': host_name,
                            'ret': ret['returncode']})
                raise exception.VolumeBackendAPIException(data=err_msg)
        else:
            err_msg = (_('create group failed. Group name:%(name)s '
                         'with Return code: %(ret)s.') %
                       {'name': map_group_name,
                        'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _map_delete_lun(self, lunid, initiator_name):
        map_group_name = self._translate_grp_name(initiator_name)

        # lun not exist, no need to delete
        if (lunid != zte_pub.ZTE_LUNID_NULL
                and lunid is not None):
            del_vol_from_grp = {
                'cMapGrpName': map_group_name,
                'sdwLunId': lunid}
            ret = self._call_method('DelVolFromGrp', del_vol_from_grp)
            if ret['returncode'] != zte_pub.ZTE_SUCCESS:
                err_msg = (_('_map_lun:delete lunid from group failed. '
                             'group name:%(name)s lunid : %(lun)s '
                             'with Return code: %(ret)s.') %
                           {'name': map_group_name, 'lun': lunid,
                            'ret': ret['returncode']})
                raise exception.VolumeBackendAPIException(data=err_msg)

        # if no lun in group,then we will delete this group
        lun_num = self._get_group_lunnum(map_group_name)
        if lun_num == 0:
            self._delete_group(map_group_name)

    def _map_delete_host(self, map_group_name):

        map_grp_info = {'cMapGrpName': map_group_name}
        ret = self._call_method('GetMapGrpInfo', map_grp_info)
        if ret['returncode'] != zte_pub.ZTE_SUCCESS:
            err_msg = (_('_map_delete_host:get map group info failed. '
                         'group name:%(name)s with Return code: %(ret)s.') %
                       {'name': map_group_name, 'ret': ret['returncode']})
            raise exception.VolumeBackendAPIException(data=err_msg)

        sdwhostnum = ret['data']['sdwHostNum']

        if sdwhostnum > 0:
            thostinfo = ret['data']['tHostInfo']
            for hostindex in range(0, int(sdwhostnum)):
                initiator_name = thostinfo[hostindex]['ucHostName']
                host_in_grp = {
                    'ucInitName': initiator_name,
                    'cMapGrpName': map_group_name}
                ret = self._call_method('DelHostFromGrp', host_in_grp)
                if ret['returncode'] == zte_pub.ZTE_ERR_GROUP_NOT_EXIST:
                    continue
                if ret['returncode'] not in [zte_pub.ZTE_SUCCESS,
                                             zte_pub.ZTE_ERR_HOST_NOT_EXIST]:
                    msg = _('delete host from group failed. ')
                    raise exception.VolumeDriverException(message=msg)

                ret = self._call_method(
                    'GetHost', {"cHostAlias": initiator_name})
                if ret['returncode'] != zte_pub.ZTE_SUCCESS:
                    err_msg = (_('_map_delete_host:get host info failed. '
                                 'host name:%(name)s with Return code: '
                                 '%(ret)s.') %
                               {'name': initiator_name,
                                'ret': ret['returncode']})
                    raise exception.VolumeBackendAPIException(data=err_msg)

                return_data = ret['data']
                portnum = return_data['sdwPortNum']
                for portindex in range(0, int(portnum)):
                    port_host_info = {}
                    port_info = return_data['tPort']
                    port_name = port_info[portindex]['cPortName']
                    port_host_info['cPortName'] = port_name
                    port_host_info['cHostAlias'] = initiator_name

                    ret = self._call_method('DelPortFromHost', port_host_info)
                    if ret['returncode'] != zte_pub.ZTE_SUCCESS:
                        err_msg = (_('delete port from host failed. '
                                     'host name:%(name)s, port name:%(port)s '
                                     'with Return code: %(ret)s.') %
                                   {'name': initiator_name,
                                    'port': port_name,
                                    'ret': ret['returncode']})
                        raise exception.VolumeBackendAPIException(data=err_msg)

                ret = self._call_method(
                    'DelHost', {"cHostAlias": initiator_name})
                if (ret['returncode'] not
                    in [zte_pub.ZTE_SUCCESS,
                        zte_pub.ZTE_ERR_HOSTNAME_NOT_EXIST]):
                    err_msg = (_('_map_delete_host: delete host failed. '
                                 'host name:%(name)s with Return code: '
                                 '%(ret)s') %
                               {'name': initiator_name,
                                'ret': ret['returncode']})
                    raise exception.VolumeBackendAPIException(data=err_msg)
