# Copyright 2020 toyou Corp.
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
Testing for acs5000 san storage driver
"""

import copy
import json
import random
import time
from unittest import mock

from eventlet import greenthread
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_utils import excutils
from oslo_utils import units
import paramiko

from cinder import context
import cinder.db
from cinder import exception
from cinder import ssh_utils
from cinder.tests.unit import test
from cinder.tests.unit import utils as testutils
from cinder import utils as cinder_utils
from cinder.volume import configuration as conf
from cinder.volume.drivers.toyou.acs5000 import acs5000_common
from cinder.volume.drivers.toyou.acs5000 import acs5000_iscsi

POOLS_NAME = ['pool01', 'pool02']
VOLUME_PRE = acs5000_common.VOLUME_PREFIX
# luns number only for test
LUN_NUMS_AVAILABLE = range(0, 5)
# snapshot count on a volume, only for test
SNAPSHOTS_A_VOLUME = 3
# snapshot count on a system, only for test
SNAPSHOTS_ON_SYSTEM = 10
# volume count on a pool, only for test
VOLUME_LIMIT_ON_POOL = 10
# volume count on a pool, only for test
VOLUME_LIMIT_ON_SYSTEM = 16
# volume count on a system, only for test

CONF = cfg.CONF


class CommandSimulator(object):
    def __init__(self, pool_name):
        self._all_pools_name = {'acs5000_volpool_name': pool_name}
        self._pools_list = {
            'pool01': {
                'name': 'pool01',
                'capacity': '799090409472',
                'free_capacity': '795869184000',
                'used_capacity': '3221225472',
                'total_volumes': 0},
            'pool02': {
                'name': 'pool02',
                'capacity': '193273528320',
                'free_capacity': '190052302848',
                'used_capacity': '3221225472',
                'total_volumes': 0
            }}
        self._volumes_list = {}
        self._lun_maps_list = []
        self._snapshots_list = []
        self._controllers_list = [
            {'id': '0',
             'name': 'node1',
             'iscsi_name': 'iqn.2020-12.cn.com.toyou:'
                           'disk-array-000f12345:dev0.ctr1',
             'WWNN': '200008CA45D33768',
             'status': 'online'},
            {'id': '1',
             'name': 'node2',
             'iscsi_name': 'iqn.2020-04.cn.com.toyou:'
                           'disk-array-000f12345:dev0.ctr2',
             'WWNN': '200008CA45D33768',
             'status': 'online'}]
        self._ip_list = {
            '0': [{
                'ctrl_idx': 0,
                'id': 0,
                'name': 'lan1',
                'ip': '10.23.45.67',
                'mask': '255.255.255.0',
                'gw': ''
            }, {
                'ctrl_idx': 0,
                'id': 1,
                'name': 'lan2',
                'ip': '10.23.45.68',
                'mask': '255.255.255.0',
                'gw': ''
            }],
            '1': [{
                'ctrl_idx': 1,
                'id': 0,
                'name': 'lan1',
                'ip': '10.23.45.69',
                'mask': '255.255.255.0',
                'gw': ''
            }, {
                'ctrl_idx': 1,
                'id': 1,
                'name': 'lan2',
                'ip': '10.23.45.70',
                'mask': '255.255.255.0',
                'gw': ''
            }]
        }
        self._system_info = {'version': '3.1.2.345678',
                             'vendor': 'TOYOU',
                             'system_name': 'Disk-Array',
                             'system_id': 'TY123456789ABCDEF',
                             'code_level': '1',
                             'ip': '10.0.0.1'}

        self._error = {
            'success': (0, 'Success'),
            'unknown': (1, 'unknown error'),
            'pool_not_exist': (101, 'The pool does not exist '
                                    'on the system.'),
            'pool_exceeds_size': (102, 'The pool cannot provide '
                                       'more storage space'),
            'volume_not_exist': (303, 'The volume does not exist '
                                      'on the system.'),
            'source_volume_not_exist': (304, 'A clone relation needs '
                                             'a source volume.'),
            'target_volume_not_exist': (305, 'A clone relation needs '
                                             'a target volume.'),
            'source_size_larger_target': (306, 'The source volume '
                                               'must not be larger '
                                               'than the target volume'
                                               ' in a clone relation '),
            'volume_limit_pool': (307, 'A pool only supports 96 volumes'),
            'volume_limit_system': (308, 'A system only supports 96 volumes'),
            'volume_name_exist': (310, 'A volume with same name '
                                       'already exists on the system.'),
            'volume_extend_min': (321, 'A volume capacity shall not be'
                                       ' less than the current size'),
            'lun_not_exist': (401, 'The volume does not exist  '
                                   'on the system.'),
            'not_available_lun': (402, 'The system have no available lun.'),
            'snap_over_system': (503, 'The system snapshots maximum quantity '
                                      'has been reached.'),
            'snap_over_volume': (504, 'A volume snapshots maximum quantity '
                                      'has been reached.'),
            'snap_not_exist': (505, 'The snapshot does not exist '
                                    'on the system.')
        }
        self._command_function = {
            'sshGetSystem': 'get_system',
            'sshGetIpConnect': 'get_ip_connect',
            'sshGetPoolInfo': 'get_pool_info',
            'sshGetVolume': 'get_volume',
            'sshGetCtrInfo': 'ls_ctr_info',
            'sshCreateVolume': 'create_volume',
            'sshDeleteVolume': 'delete_volume',
            'sshCinderExtendVolume': 'extend_volume',
            'sshMkLocalClone': 'create_clone',
            'sshMkStartLocalClone': 'start_clone',
            'sshRemoveLocalClone': 'delete_clone',
            'sshMapVoltoHost': 'create_lun_map',
            'sshDeleteLunMap': 'delete_lun_map',
            'sshCreateSnapshot': 'create_snapshot',
            'sshDeleteSnapshot': 'delete_snapshot',
            'sshSetVolumeProperty': 'set_volume_property',
            'error_ssh': 'error_ssh'
        }
        self._volume_type = {
            '0': 'RAID Volume',
            '10': 'BACKUP'
        }

    @staticmethod
    def _json_return(rows=None, msg='', key=0):
        json_data = {'key': key,
                     'msg': msg,
                     'arr': rows}
        return (json.dumps(json_data), '')

    @staticmethod
    def _create_id(lists, key='id'):
        ids = []
        if isinstance(lists, list):
            for v in lists:
                ids.append(int(v[key]))
        elif isinstance(lists, dict):
            for v in lists.values():
                ids.append(int(v[key]))
        new_id = 'ffffffffff'
        while True:
            new_id = str(random.randint(1000000000, 9999999999))
            if new_id not in ids:
                break
        return new_id

    def _clone_thread(self, vol_name, setting=None):
        intval = 0.1
        loop_times = int(self._volumes_list[vol_name]['size_gb'])
        chunk = int(100 / loop_times)
        if setting:
            for k, value in setting.items():
                for v in value:
                    self._volumes_list[k][v[0]] = v[1]
                    time.sleep(v[2])

        self._volumes_list[vol_name]['status'] = 'Cloning'
        while loop_times > 0:
            # volumes may be deleted
            if vol_name in self._volumes_list:
                src_vol = self._volumes_list[vol_name]
            else:
                return
            if src_vol['clone'] not in self._volumes_list:
                self._volumes_list[vol_name]['status'] = 'Online'
                self._volumes_list[vol_name]['r'] = ''
                return
            progress = src_vol['r']
            if not progress:
                progress = 0
            src_vol['r'] = str(int(progress) + chunk)
            loop_times -= 1
            self._volumes_list[vol_name] = src_vol
            time.sleep(intval)
        self._volumes_list[vol_name]['status'] = 'Online'
        self._volumes_list[vol_name]['r'] = ''

    def execute_command(self, cmd_list, check_exit_code=True):
        command = cmd_list[2]
        if command in self._command_function:
            command = self._command_function[command]
        func = getattr(self, '_sim_' + command)
        kwargs = {}
        for i in range(3, len(cmd_list)):
            if cmd_list[i].startswith('--'):
                key = cmd_list[i][2:]
                value = ''
                if cmd_list[i + 1]:
                    value = cmd_list[i + 1]
                    i += 1
                if key in kwargs.keys():
                    if not isinstance(kwargs[key], list):
                        kwargs[key] = [kwargs[key]]

                    kwargs[key].append(value)
                else:
                    kwargs[key] = value
        try:
            out, err = func(**kwargs)
            return (out, err)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                if check_exit_code:
                    raise processutils.ProcessExecutionError(
                        exit_code=1,
                        stdout='out',
                        stderr=e,
                        cmd=' '.join(cmd_list))

    def _sim_get_system(self, **kwargs):
        return self._json_return(self._system_info)

    def _sim_get_ip_connect(self, **kwargs):
        return self._json_return(self._ip_list)

    def _sim_get_pool_info(self, **kwargs):
        pool_name = kwargs['poolName'].strip('\'\"')
        if pool_name in self._all_pools_name['acs5000_volpool_name']:
            vol_len = 0
            for vol in self._volumes_list.values():
                if vol['poolname'] == pool_name:
                    vol_len += 1
            if pool_name in self._pools_list:
                pool_data = self._pools_list[pool_name]
            else:
                pool_data = self._pools_list['pool01']
                pool_data['name'] = pool_name
            pool_data['total_volumes'] = str(vol_len)
            return self._json_return(pool_data)
        else:
            return self._json_return()

    def _sim_get_volume(self, **kwargs):
        rows = []
        if isinstance(kwargs['name'], list):
            volume_name = kwargs['name']
        else:
            volume_name = [kwargs['name']]
        for vol_name in volume_name:
            if vol_name in self._volumes_list.keys():
                rows.append(self._volumes_list[vol_name])

        return self._json_return(rows)

    def _sim_ls_ctr_info(self, **kwargs):
        return self._json_return(self._controllers_list)

    def _sim_create_volume(self, **kwargs):
        volume_name = kwargs['volumename']
        pool_name = kwargs['cinderPool']
        size = kwargs['volumesize']
        if volume_name in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_name_exist'][1],
                key=self._error['volume_name_exist'][0])
        elif len(self._volumes_list) >= VOLUME_LIMIT_ON_SYSTEM:
            return self._json_return(
                msg=self._error['volume_limit_system'][1],
                key=self._error['volume_limit_system'][0])

        volume_count_on_pool = 0
        for v in self._volumes_list.values():
            if v['poolname'] == pool_name:
                volume_count_on_pool += 1
        if volume_count_on_pool >= VOLUME_LIMIT_ON_POOL:
            return self._json_return(
                msg=self._error['volume_limit_pool'][1],
                key=self._error['volume_limit_pool'][0])
        avail_size = (int(self._pools_list[pool_name]['free_capacity'])
                      / units.Gi)
        if int(size) > avail_size:
            return self._json_return(
                msg=self._error['pool_exceeds_size'][1],
                key=self._error['pool_exceeds_size'][0])
        volume_info = {}
        volume_info['id'] = self._create_id(self._volumes_list)
        volume_info['name'] = volume_name
        volume_info['size_gb'] = size
        volume_info['status'] = 'Online'
        volume_info['health'] = 'Optimal'
        volume_info['r'] = ''
        volume_info['poolname'] = pool_name
        volume_info['has_clone'] = 0
        volume_info['clone'] = 'N/A'
        volume_info['clone_snap'] = 'N/A'
        type = kwargs['type']
        if type not in ('0', '10'):
            type = '0'
        volume_info['type'] = self._volume_type[type]
        self._volumes_list[volume_info['name']] = volume_info
        return self._json_return()

    def _sim_delete_volume(self, **kwargs):
        vol_name = kwargs['cinderVolume']
        if vol_name in self._volumes_list:
            del self._volumes_list[vol_name]
        return self._json_return()

    def _sim_extend_volume(self, **kwargs):
        vol_name = kwargs['cinderVolume']
        size = int(kwargs['extendsize'])
        if vol_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        volume = self._volumes_list[vol_name]
        curr_size = int(volume['size_gb'])
        pool = self._pools_list[volume['poolname']]
        avail_size = int(pool['free_capacity']) / units.Gi
        if curr_size > size:
            return self._json_return(
                msg=self._error['volume_extend_min'][1],
                key=self._error['volume_extend_min'][0])
        elif (size - curr_size) > avail_size:
            return self._json_return(
                msg=self._error['pool_exceeds_size'][1],
                key=self._error['pool_exceeds_size'][0])
        self._volumes_list[vol_name]['size_gb'] = str(size)
        return self._json_return()

    def _sim_create_clone(self, **kwargs):
        src_name = kwargs['cinderVolume']
        tgt_name = kwargs['cloneVolume']
        src_exist = False
        tgt_exist = False
        for vol in self._volumes_list.values():
            if (vol['name'] == src_name
                    and vol['type'] == self._volume_type['0']):
                src_exist = True
            elif (vol['name'] == tgt_name
                    and vol['type'] == self._volume_type['10']):
                tgt_exist = True
            if src_exist and tgt_exist:
                break
        if not src_exist:
            return self._json_return(
                msg=self._error['source_volume_not_exist'][1],
                key=self._error['source_volume_not_exist'][0])
        elif not tgt_exist:
            return self._json_return(
                msg=self._error['target_volume_not_exist'][1],
                key=self._error['target_volume_not_exist'][0])
        src_size = int(self._volumes_list[src_name]['size_gb'])
        tgt_size = int(self._volumes_list[tgt_name]['size_gb'])
        if src_size > tgt_size:
            return self._json_return(
                msg=self._error['source_size_larger_target'][1],
                key=self._error['source_size_larger_target'][0])
        tgt_volume = self._volumes_list[tgt_name]
        self._volumes_list[src_name]['has_clone'] = 1
        self._volumes_list[src_name]['clone'] = tgt_volume['name']
        return self._json_return()

    def _sim_start_clone(self, **kwargs):
        vol_name = kwargs['cinderVolume']
        snapshot = kwargs['snapshot']
        if len(snapshot) > 0:
            snap_found = False
            for snap in self._snapshots_list:
                if snap['name'] == snapshot:
                    snap_found = True
                    break
            if not snap_found:
                return self._json_return(
                    msg=self._error['snap_not_exist'][1],
                    key=self._error['snap_not_exist'][0])
        else:
            snapshot = ('clone-' + str(random.randint(100, 999)))
            tmp_snap = {'volume': vol_name,
                        'snapshot': snapshot}
            self._sim_create_snapshot(**tmp_snap)
        self._volumes_list[vol_name]['status'] = 'Queued'
        self._volumes_list[vol_name]['clone_snap'] = snapshot
        greenthread.spawn_n(self._clone_thread, vol_name)
        return self._json_return()

    def _sim_delete_clone(self, **kwargs):
        vol_name = kwargs['name']
        snapshot = kwargs['snapshot']
        if vol_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        self._volumes_list[vol_name]['has_clone'] = 0
        clone_volume = self._volumes_list[vol_name]['clone']
        self._volumes_list[vol_name]['clone'] = 'N/A'
        clone_snap = self._volumes_list[vol_name]['clone_snap']
        self._volumes_list[vol_name]['clone_snap'] = 'N/A'
        self._volumes_list[clone_volume]['type'] = self._volume_type['0']
        if len(snapshot) == 0:
            for snap in self._snapshots_list:
                if clone_snap == snap['name']:
                    self._snapshots_list.remove(snap)
                    break
        return self._json_return()

    def _sim_create_lun_map(self, **kwargs):
        volume_name = kwargs['cinderVolume']
        protocol = kwargs['protocol']
        hosts = kwargs['host']
        if volume_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        if isinstance(hosts, str):
            hosts = [hosts]
        volume = self._volumes_list[volume_name]
        available_luns = LUN_NUMS_AVAILABLE
        existed_lun = -1
        for lun_row in self._lun_maps_list:
            if lun_row['vd_id'] == volume['id']:
                if lun_row['host'] in hosts:
                    existed_lun = lun_row['lun']
                    hosts = [h for h in hosts if h != lun_row['host']]
            else:
                if lun_row['protocol'] == protocol:
                    available_luns = [lun for lun in available_luns
                                      if lun != lun_row['lun']]
        if hosts and existed_lun > -1:
            return self._json_return({'info': existed_lun})
        lun_info = {}
        lun_info['vd_id'] = volume['id']
        lun_info['vd_name'] = volume['name']
        lun_info['protocol'] = protocol
        if existed_lun > -1:
            lun_info['lun'] = existed_lun
        elif available_luns:
            lun_info['lun'] = available_luns[0]
        else:
            return self._json_return(
                msg=self._error['not_available_lun'][1],
                key=self._error['not_available_lun'][0])
        for host in hosts:
            lun_info['id'] = self._create_id(self._lun_maps_list)
            lun_info['host'] = host
            self._lun_maps_list.append(copy.deepcopy(lun_info))
        ret = {'lun': [],
               'iscsi_name': [],
               'portal': []}
        for ctr, ips in self._ip_list.items():
            for ip in ips:
                ret['lun'].append(lun_info['lun'])
                ret['portal'].append('%s:3260' % ip['ip'])
                for control in self._controllers_list:
                    if ctr == control['id']:
                        ret['iscsi_name'].append(control['iscsi_name'])
                        break
        return self._json_return(ret)

    def _sim_delete_lun_map(self, **kwargs):
        map_exist = False
        volume_name = kwargs['cinderVolume']
        protocol = kwargs['protocol']
        hosts = kwargs['cinderHost']
        if isinstance(hosts, str):
            hosts = [hosts]
        if volume_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        volume = self._volumes_list[volume_name]
        lun_maps_list = self._lun_maps_list
        self._lun_maps_list = []
        for row in lun_maps_list:
            if (row['vd_id'] == volume['id']
                    and row['protocol'] == protocol
                    and row['host'] in hosts):
                map_exist = True
            else:
                map_exist = False
                self._lun_maps_list.append(row)
        if not map_exist:
            return self._json_return(
                msg=self._error['lun_not_exist'][1],
                key=self._error['lun_not_exist'][0])
        else:
            return self._json_return()

    def _sim_create_snapshot(self, **kwargs):
        volume_name = kwargs['volume']
        snapshot_name = kwargs['snapshot']
        if volume_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        if len(self._snapshots_list) >= SNAPSHOTS_ON_SYSTEM:
            return self._json_return(
                msg=self._error['snap_over_system'][1],
                key=self._error['snap_over_system'][0])
        tag = -1
        volume_snap_count = 0
        for snap in self._snapshots_list:
            if snap['vd_name'] == volume_name:
                volume_snap_count += 1
                if int(snap['tag']) > tag:
                    tag = int(snap['tag'])
        if volume_snap_count >= SNAPSHOTS_A_VOLUME:
            return self._json_return(
                msg=self._error['snap_over_volume'][1],
                key=self._error['snap_over_volume'][0])
        volume = self._volumes_list[volume_name]
        snapshot = {}
        snapshot['id'] = self._create_id(self._snapshots_list)
        snapshot['name'] = snapshot_name
        snapshot['vd_id'] = volume['id']
        snapshot['vd_name'] = volume['name']
        snapshot['tag'] = tag + 1
        snapshot['create_time'] = ''
        self._snapshots_list.append(snapshot)
        return self._json_return()

    def _sim_delete_snapshot(self, **kwargs):
        volume_name = kwargs['volume']
        snapshot_name = kwargs['snapshot']
        if volume_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        snap_exist = False
        for snap in self._snapshots_list:
            if (snap['vd_name'] == volume_name
                    and snap['name'] == snapshot_name):
                snap_exist = True
                self._snapshots_list.remove(snap)
                break
        if not snap_exist:
            return self._json_return(
                msg=self._error['snap_not_exist'][1],
                key=self._error['snap_not_exist'][0])
        return self._json_return()

    def _sim_set_volume_property(self, **kwargs):
        volume_name = kwargs['volume']
        kwargs.pop('volume')
        if len(kwargs) == 0:
            raise exception.InvalidInput(
                reason=self._error['unknown'][1])
        new_name = volume_name
        if 'new_name' in kwargs:
            new_name = kwargs['new_name']
            kwargs.pop('new_name')
        if volume_name not in self._volumes_list:
            return self._json_return(
                msg=self._error['volume_not_exist'][1],
                key=self._error['volume_not_exist'][0])
        volume = self._volumes_list[volume_name]
        volume['name'] = new_name
        for k, v in kwargs.items():
            if k in volume:
                volume[k] = v
            else:
                return ('', self._error['unknown'][1])

        if volume_name != new_name:
            del self._volumes_list[volume_name]
            self._volumes_list[new_name] = volume
        else:
            self._volumes_list[volume_name] = volume
        return self._json_return()

    def _sim_error_ssh(self, **kwargs):
        error = kwargs['error']
        if error == 'json_error':
            return ('This text is used for json errors.', '')
        elif error == 'dict_error':
            return (json.dumps('This text is used for dict errors.'), '')
        elif error == 'keys_error':
            keys = {'msg': 'This text is used for keys errors'}
            return (json.dumps(keys), '')
        elif error == 'key_false':
            keys = {'msg': 'This text is used for key non-0 error',
                    'key': 1,
                    'arr': {}}
            return (json.dumps(keys), '')


class Acs5000ISCSIFakeDriver(acs5000_iscsi.Acs5000ISCSIDriver):
    def __init__(self, *args, **kwargs):
        super(Acs5000ISCSIFakeDriver, self).__init__(*args, **kwargs)

    def set_fake_storage(self, fake):
        self.fake_storage = fake

    def _run_ssh(self, cmd_list, check_exit_code=True):
        cinder_utils.check_ssh_injection(cmd_list)
        ret = self.fake_storage.execute_command(cmd_list, check_exit_code)

        return ret


class Acs5000ISCSIDriverTestCase(test.TestCase):
    @mock.patch.object(time, 'sleep')
    def setUp(self, mock_sleep):
        super(Acs5000ISCSIDriverTestCase, self).setUp()
        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.san_is_local = False
        self.configuration.san_ip = '23.44.56.78'
        self.configuration.san_login = 'cliuser'
        self.configuration.san_password = 'clipassword'
        self.configuration.acs5000_volpool_name = ['pool01']
        self.iscsi_driver = Acs5000ISCSIFakeDriver(
            configuration=self.configuration)
        initiator = 'test.iqn.%s' % str(random.randint(10000, 99999))
        self._connector = {'ip': '1.234.56.78',
                           'host': 'stack',
                           'wwpns': [],
                           'initiator': initiator}
        self.sim = CommandSimulator(POOLS_NAME)
        self.iscsi_driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self.db = cinder.db
        self.iscsi_driver.db = self.db
        self.iscsi_driver.get_driver_options()
        self.iscsi_driver.do_setup(None)
        self.iscsi_driver.check_for_setup_error()

    def _create_volume(self, **kwargs):
        prop = {'host': 'stack@ty1#%s' % POOLS_NAME[0],
                'size': 1,
                'volume_type_id': self.vt['id']}
        for p in prop.keys():
            if p not in kwargs:
                kwargs[p] = prop[p]
        vol = testutils.create_volume(self.ctxt, **kwargs)
        self.iscsi_driver.create_volume(vol)
        return vol

    def _delete_volume(self, volume):
        self.iscsi_driver.delete_volume(volume)
        self.db.volume_destroy(self.ctxt, volume['id'])

    def _assert_lun_exists(self, vol_id, exists):
        lun_maps = self.sim._lun_maps_list
        is_lun_defined = False
        luns = []
        volume_name = VOLUME_PRE + vol_id[-12:]
        for lun in lun_maps:
            if volume_name == lun['vd_name']:
                luns.append(lun)
        if len(luns):
            is_lun_defined = True
        self.assertEqual(exists, is_lun_defined)
        return luns

    def test_validate_connector(self):
        conn_neither = {'host': 'host'}
        conn_iscsi = {'host': 'host', 'initiator': 'iqn.123'}
        conn_fc = {'host': 'host', 'wwpns': 'fff123'}
        conn_both = {'host': 'host', 'initiator': 'iqn.123', 'wwpns': 'fff123'}

        self.iscsi_driver._state['enabled_protocols'] = set(['iSCSI'])
        self.iscsi_driver.validate_connector(conn_iscsi)
        self.iscsi_driver.validate_connector(conn_both)
        self.assertRaises(exception.InvalidConnectorException,
                          self.iscsi_driver.validate_connector, conn_fc)
        self.assertRaises(exception.InvalidConnectorException,
                          self.iscsi_driver.validate_connector, conn_neither)

    def test_initialize_connection(self):
        volume = self._create_volume()
        result = self.iscsi_driver.initialize_connection(volume,
                                                         self._connector)
        ip_connect = self.sim._ip_list
        ip_count = 0
        for ips in ip_connect.values():
            ip_count += len(ips)
        self.assertEqual('iscsi', result['driver_volume_type'])
        self.assertEqual(ip_count,
                         len(result['data']['target_iqns']))
        self.assertEqual(ip_count,
                         len(result['data']['target_portals']))
        self.assertEqual(volume['id'], result['data']['volume_id'])
        self.assertEqual(ip_count,
                         len(result['data']['target_portals']))
        self._delete_volume(volume)

    def test_initialize_connection_not_found(self):
        prop = {'host': 'stack@ty1#%s' % POOLS_NAME[0],
                'size': 1,
                'volume_type_id': self.vt['id']}
        vol = testutils.create_volume(self.ctxt, **prop)
        self.assertRaises(exception.VolumeNotFound,
                          self.iscsi_driver.initialize_connection,
                          vol, self._connector)
        self.db.volume_destroy(self.ctxt, vol['id'])

    def test_initialize_connection_failure(self):
        volume_list = []
        for i in LUN_NUMS_AVAILABLE:
            vol = self._create_volume()
            self.iscsi_driver.initialize_connection(
                vol, self._connector)
            volume_list.append(vol)

        vol = self._create_volume()
        self.assertRaises(exception.ISCSITargetAttachFailed,
                          self.iscsi_driver.initialize_connection,
                          vol, self._connector)
        self._delete_volume(vol)
        for v in volume_list:
            self.iscsi_driver.terminate_connection(
                v, self._connector)
            self._delete_volume(v)

    def test_initialize_connection_multi_host(self):
        connector = self._connector
        initiator1 = ('test.iqn.%s'
                      % str(random.randint(10000, 99999)))
        initiator2 = ('test.iqn.%s'
                      % str(random.randint(10000, 99999)))
        connector['initiator'] = [initiator1, initiator2]
        volume = self._create_volume()
        self.iscsi_driver.initialize_connection(
            volume, connector)
        lun_maps = self._assert_lun_exists(volume['id'], True)
        hosts = []
        for lun in lun_maps:
            hosts.append(lun['host'])
        self.assertIn(initiator1, hosts)
        self.assertIn(initiator2, hosts)
        self.iscsi_driver.terminate_connection(
            volume, connector)
        self._assert_lun_exists(volume['id'], False)
        self._delete_volume(volume)

    def test_terminate_connection(self):
        volume = self._create_volume()
        self.iscsi_driver.initialize_connection(volume,
                                                self._connector)
        self.iscsi_driver.terminate_connection(volume,
                                               self._connector)
        self._assert_lun_exists(volume['id'], False)
        self._delete_volume(volume)


class Acs5000CommonDriverTestCase(test.TestCase):
    @mock.patch.object(time, 'sleep')
    def setUp(self, mock_sleep):
        super(Acs5000CommonDriverTestCase, self).setUp()

        self.configuration = mock.Mock(conf.Configuration)
        self.configuration.san_is_local = False
        self.configuration.san_ip = '23.44.56.78'
        self.configuration.san_login = 'cliuser'
        self.configuration.san_password = 'clipassword'
        self.configuration.acs5000_volpool_name = POOLS_NAME
        self.configuration.acs5000_copy_interval = 0.01
        self.configuration.reserved_percentage = 0
        self._driver = Acs5000ISCSIFakeDriver(
            configuration=self.configuration)
        options = acs5000_iscsi.Acs5000ISCSIDriver.get_driver_options()
        config = conf.Configuration(options, conf.SHARED_CONF_GROUP)
        self.override_config('san_ip', '23.44.56.78', conf.SHARED_CONF_GROUP)
        self.override_config('san_login', 'cliuser', conf.SHARED_CONF_GROUP)
        self.override_config('san_password', 'clipassword',
                             conf.SHARED_CONF_GROUP)
        self.override_config('acs5000_volpool_name', POOLS_NAME,
                             conf.SHARED_CONF_GROUP)
        self._iscsi_driver = acs5000_iscsi.Acs5000ISCSIDriver(
            configuration=config)
        initiator = 'test.iqn.%s' % str(random.randint(10000, 99999))
        self._connector = {'ip': '1.234.56.78',
                           'host': 'stack',
                           'wwpns': [],
                           'initiator': initiator}
        self.sim = CommandSimulator(POOLS_NAME)
        self._driver.set_fake_storage(self.sim)
        self.ctxt = context.get_admin_context()

        self.db = cinder.db
        self._driver.db = self.db
        self._driver.do_setup(None)
        self._driver.check_for_setup_error()

    def _assert_vol_exists(self, name, exists):
        volume = self._driver._cmd.get_volume(VOLUME_PRE + name[-12:])
        is_vol_defined = False
        if volume:
            is_vol_defined = True
        self.assertEqual(exists, is_vol_defined)
        return volume

    def _assert_snap_exists(self, name, exists):
        snap_name = VOLUME_PRE + name[-12:]
        snapshot_list = self.sim._snapshots_list
        is_snap_defined = False
        snapshot = {}
        for snap in snapshot_list:
            if snap['name'] == snap_name:
                is_snap_defined = True
                snapshot = snap
                break
        self.assertEqual(exists, is_snap_defined)
        return snapshot

    def _create_volume(self, **kwargs):
        prop = {'host': 'stack@ty1#%s' % POOLS_NAME[0],
                'size': 1,
                'volume_type_id': self.vt['id']}
        driver = True
        if 'driver' in kwargs:
            if not kwargs['driver']:
                driver = False
            kwargs.pop('driver')
        for p in prop.keys():
            if p not in kwargs:
                kwargs[p] = prop[p]
        vol = testutils.create_volume(self.ctxt, **kwargs)
        if driver:
            self._driver.create_volume(vol)
        return vol

    def _delete_volume(self, volume, driver=True):
        if driver:
            self._driver.delete_volume(volume)
        self.db.volume_destroy(self.ctxt, volume['id'])

    def _create_snapshot(self, vol_id, driver=True):
        snap = testutils.create_snapshot(self.ctxt, vol_id)
        if driver:
            self._driver.create_snapshot(snap)
        return snap

    def _delete_snapshot(self, snap, driver=True):
        if driver:
            self._driver.delete_snapshot(snap)
        self.db.snapshot_destroy(self.ctxt, snap['id'])

    def test_run_ssh_failure(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._build_pool_stats,
                          'error_pool')
        ssh_cmd = ['cinder', 'storage', 'error_ssh', '--error', 'json_error']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.run_ssh_info, ssh_cmd)
        ssh_cmd = ['cinder', 'storage', 'error_ssh', '--error', 'dict_error']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.run_ssh_info, ssh_cmd)
        ssh_cmd = ['cinder', 'storage', 'error_ssh', '--error', 'keys_error']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.run_ssh_info, ssh_cmd)
        ssh_cmd = ['cinder', 'storage', 'error_ssh', '--error', 'key_false']
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.run_ssh_info, ssh_cmd)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_with_ip(self, mock_ssh_execute, mock_ssh_pool):
        ssh_cmd = ['cinder', 'storage', 'run_ssh']
        self._iscsi_driver._run_ssh(ssh_cmd)
        mock_ssh_pool.assert_called_once_with(
            self._iscsi_driver.configuration.san_ip,
            self._iscsi_driver.configuration.san_ssh_port,
            self._iscsi_driver.configuration.ssh_conn_timeout,
            self._iscsi_driver.configuration.san_login,
            password=self._iscsi_driver.configuration.san_password,
            min_size=self._iscsi_driver.configuration.ssh_min_pool_conn,
            max_size=self._iscsi_driver.configuration.ssh_max_pool_conn)

        mock_ssh_pool.side_effect = [paramiko.SSHException, mock.MagicMock()]
        self._iscsi_driver._run_ssh(ssh_cmd)
        mock_ssh_pool.assert_called_once_with(
            self._iscsi_driver.configuration.san_ip,
            self._iscsi_driver.configuration.san_ssh_port,
            self._iscsi_driver.configuration.ssh_conn_timeout,
            self._iscsi_driver.configuration.san_login,
            password=self._iscsi_driver.configuration.san_password,
            min_size=self._iscsi_driver.configuration.ssh_min_pool_conn,
            max_size=self._iscsi_driver.configuration.ssh_max_pool_conn)

    @mock.patch.object(ssh_utils, 'SSHPool')
    @mock.patch.object(processutils, 'ssh_execute')
    def test_run_ssh_with_exception(self, mock_ssh_execute, mock_ssh_pool):
        mock_ssh_execute.side_effect = [processutils.ProcessExecutionError,
                                        mock.MagicMock()]
        self.override_config('acs5000_volpool_name', None,
                             self._iscsi_driver.configuration.config_group)
        ssh_cmd = ['cinder', 'storage', 'run_ssh']
        self.assertRaises(processutils.ProcessExecutionError,
                          self._iscsi_driver._run_ssh, ssh_cmd)

    def test_do_setup(self):
        system_info = self.sim._system_info
        self.assertEqual(system_info['vendor'], self._driver._state['vendor'])
        self.assertIn('iSCSI', self._driver._state['enabled_protocols'])
        self.assertEqual(2, len(self._driver._state['storage_nodes']))

    def test_do_setup_no_pools(self):
        self._driver.pools = ['pool_error']
        self.assertRaises(exception.InvalidInput,
                          self._driver.do_setup, None)

    def test_create_volume(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        self._delete_volume(vol)

    def test_create_volume_same_name(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_volume, vol)
        self._delete_volume(vol)

    def test_create_volume_size_exceeds_limit(self):
        prop = {
            'host': 'stack@ty2#%s' % POOLS_NAME[1],
            'size': 200,
            'driver': False
        }
        self._driver.get_volume_stats()
        vol = self._create_volume(**prop)
        self._assert_vol_exists(vol['id'], False)
        self.assertRaises(exception.VolumeSizeExceedsLimit,
                          self._driver.create_volume,
                          vol)
        self._delete_volume(vol, False)

    def test_create_volume_number_exceeds_pool_limit(self):
        volume_list = []
        for i in range(VOLUME_LIMIT_ON_POOL):
            vol = self._create_volume()
            self._assert_vol_exists(vol['id'], True)
            volume_list.append(vol)
        vol = self._create_volume(driver=False)
        self.assertRaises(exception.VolumeLimitExceeded,
                          self._driver.create_volume,
                          vol)
        self._delete_volume(vol, False)
        for v in volume_list:
            self._delete_volume(v)

    def test_create_volume_number_exceeds_system_limit(self):
        volume_list = []
        volume_count_on_pool = int(VOLUME_LIMIT_ON_SYSTEM
                                   / len(POOLS_NAME))
        for i in range(volume_count_on_pool):
            for x in range(len(POOLS_NAME)):
                vol = self._create_volume(
                    host='stack@ty1#%s' % POOLS_NAME[x])
                self._assert_vol_exists(vol['id'], True)
                volume_list.append(vol)
        vol = self._create_volume(driver=False)
        self.assertRaises(exception.VolumeLimitExceeded,
                          self._driver.create_volume,
                          vol)
        self._delete_volume(vol, False)
        for v in volume_list:
            self._delete_volume(v)

    def test_delete_volume(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        self._delete_volume(vol)
        self._assert_vol_exists(vol['id'], False)

    def test_create_snapshot(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        snap = self._create_snapshot(vol['id'])
        self._assert_snap_exists(snap['id'], True)
        self._delete_snapshot(snap)
        self._delete_volume(vol)

    def test_create_snapshot_exceed_limit(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        snapshot_list = []
        for i in range(SNAPSHOTS_A_VOLUME):
            snap = self._create_snapshot(vol['id'])
            self._assert_snap_exists(snap['id'], True)
            snapshot_list.append(snap)
        snap = self._create_snapshot(vol['id'], False)
        self.assertRaises(exception.SnapshotLimitExceeded,
                          self._driver.create_snapshot, snap)
        self._delete_snapshot(snap, False)
        vol_list = [vol]
        snap_count = SNAPSHOTS_A_VOLUME
        while snap_count < SNAPSHOTS_ON_SYSTEM:
            vol = self._create_volume()
            vol_list.append(vol)
            for x in range(SNAPSHOTS_A_VOLUME):
                snap = self._create_snapshot(vol['id'])
                self._assert_snap_exists(snap['id'], True)
                snapshot_list.append(snap)
                snap_count += 1
                if snap_count >= SNAPSHOTS_ON_SYSTEM:
                    break

        vol = self._create_volume()
        vol_list.append(vol)
        snap = self._create_snapshot(vol['id'], False)
        self.assertRaises(exception.SnapshotLimitExceeded,
                          self._driver.create_snapshot, snap)
        for sp in snapshot_list:
            self._delete_snapshot(sp)
        for vol in vol_list:
            self._delete_volume(vol)

    def test_delete_snapshot(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        snap = self._create_snapshot(vol['id'])
        self._assert_snap_exists(snap['id'], True)
        self._delete_snapshot(snap)
        self._assert_snap_exists(snap['id'], False)
        self._delete_volume(vol)

    def test_delete_snapshot_not_found(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        snap = self._create_snapshot(vol['id'], False)
        self._assert_snap_exists(snap['id'], False)
        self.assertRaises(exception.SnapshotNotFound,
                          self._driver.delete_snapshot,
                          snap)
        self._delete_snapshot(snap, False)
        self._delete_volume(vol)

    def test_create_volume_from_snapshot(self):
        prop = {'size': 2}
        vol = self._create_volume(**prop)
        self._assert_vol_exists(vol['id'], True)
        snap = self._create_snapshot(vol['id'])
        self._assert_snap_exists(snap['id'], True)
        prop['driver'] = False
        new_vol = self._create_volume(**prop)
        self._driver.create_volume_from_snapshot(new_vol, snap)
        new_volume = self._assert_vol_exists(new_vol['id'], True)
        self.assertEqual(1, len(new_volume))
        self.assertEqual('2', new_volume[0]['size_gb'])
        self.assertEqual('RAID Volume', new_volume[0]['type'])
        self._delete_volume(new_vol)
        self._delete_snapshot(snap)
        self._delete_volume(vol)

    def test_create_volume_from_snapshot_not_found(self):
        vol = self._create_volume()
        self._assert_vol_exists(vol['id'], True)
        snap = self._create_snapshot(vol['id'], False)
        self._assert_snap_exists(snap['id'], False)
        new_vol = self._create_volume(driver=False)
        self._assert_vol_exists(new_vol['id'], False)
        self.assertRaises(exception.SnapshotNotFound,
                          self._driver.create_volume_from_snapshot,
                          new_vol, snap)
        self._delete_volume(new_vol, False)
        self._delete_snapshot(snap, False)
        self._delete_volume(vol)

    def test_create_snapshot_volume_not_found(self):
        vol = self._create_volume(driver=False)
        self._assert_vol_exists(vol['id'], False)
        self.assertRaises(exception.VolumeNotFound,
                          self._create_snapshot, vol['id'])
        self._delete_volume(vol, driver=False)

    def test_create_cloned_volume(self):
        src_volume = self._create_volume()
        self._assert_vol_exists(src_volume['id'], True)
        tgt_volume = self._create_volume(driver=False)
        self._driver.create_cloned_volume(tgt_volume, src_volume)
        volume = self._assert_vol_exists(tgt_volume['id'], True)
        self.assertEqual(1, len(volume))
        self.assertEqual('RAID Volume', volume[0]['type'])
        self._delete_volume(src_volume)
        self._delete_volume(tgt_volume)

    def test_create_cloned_volume_with_size(self):
        prop = {'size': 2}
        src_volume = self._create_volume(**prop)
        volume = self._assert_vol_exists(src_volume['id'], True)
        prop['driver'] = False
        tgt_volume = self._create_volume(**prop)
        self._driver.create_cloned_volume(tgt_volume, src_volume)
        clone_volume = self._assert_vol_exists(tgt_volume['id'], True)
        self.assertEqual(1, len(volume))
        self.assertEqual(1, len(clone_volume))
        self.assertEqual('RAID Volume', volume[0]['type'])
        self.assertEqual('RAID Volume', clone_volume[0]['type'])
        self.assertEqual('2', volume[0]['size_gb'])
        self.assertEqual('2', clone_volume[0]['size_gb'])
        self._delete_volume(src_volume)
        self._delete_volume(tgt_volume)

    def test_create_cloned_volume_size_failure(self):
        prop = {'size': 10}
        src_volume = self._create_volume(**prop)
        self._assert_vol_exists(src_volume['id'], True)
        prop = {'size': 5, 'driver': False}
        tgt_volume = self._create_volume(**prop)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.create_cloned_volume,
                          tgt_volume, src_volume)
        self._assert_vol_exists(tgt_volume['id'], False)
        self._delete_volume(src_volume)
        self._delete_volume(tgt_volume, False)

    def test_create_cloned_volume_failure(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._local_clone_copy,
                          None, None)
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._local_clone_copy,
                          'src_test', 'tgt_test')
        src_volume = self._create_volume()
        src_name = VOLUME_PRE + src_volume['id'][-12:]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._local_clone_copy,
                          src_name, 'tgt_test')
        self._delete_volume(src_volume)

    def test_wait_volume_copy(self):
        src_volume = self._create_volume(size=2)
        src_info = self._assert_vol_exists(src_volume['id'], True)[0]
        tgt_volume = self._create_volume(size=2)
        tgt_info = self._assert_vol_exists(tgt_volume['id'], True)[0]
        self._driver._cmd.set_volume_property(
            src_info['name'], {'status': 'Queued',
                               'clone_snap': tgt_info['name']})
        self._driver._cmd.set_volume_property(tgt_info['name'],
                                              {'type': 'BACKUP'})
        src_name = VOLUME_PRE + src_volume['id'][-12:]
        tgt_name = VOLUME_PRE + tgt_volume['id'][-12:]
        self._driver._cmd.create_clone(src_name, tgt_name)
        tgt_set = {
            tgt_name: [('status', 'Erasing', 0.2)],
            src_name: [('status', 'Erasing', 0.2)],
        }
        greenthread.spawn_n(self.sim._clone_thread,
                            src_name, tgt_set)
        ret = self._driver._wait_volume_copy(src_name, tgt_name,
                                             'test_func', 'test_action')
        self.assertTrue(ret)
        self._driver._cmd.set_volume_property(
            src_info['name'], {'status': 'error',
                               'clone_snap': tgt_info['name']})
        ret = self._driver._wait_volume_copy(src_name, tgt_name,
                                             'test_func', 'test_action')
        self.assertFalse(ret)
        self._driver._cmd.set_volume_property(
            src_info['name'], {'status': 'Online',
                               'clone_snap': tgt_info['name']})
        self._delete_volume(tgt_volume)
        self._assert_vol_exists(tgt_volume['id'], False)
        ret = self._driver._wait_volume_copy(src_name, tgt_name,
                                             'test_func', 'test_action')
        self.assertFalse(ret)
        self._driver._cmd.set_volume_property(src_info['name'],
                                              {'type': 'BACKUP'})
        ret = self._driver._wait_volume_copy(tgt_name, 'backup_test',
                                             'test_func', 'test_action')
        self.assertFalse(ret)
        self._delete_volume(src_volume)

    def test_extend_volume(self):
        volume = self._create_volume(size=10)
        vol_info = self._assert_vol_exists(volume['id'], True)
        self.assertEqual('10', vol_info[0]['size_gb'])
        self._driver.extend_volume(volume, '100')
        extend_vol = self._assert_vol_exists(volume['id'], True)
        self.assertEqual('100', extend_vol[0]['size_gb'])
        self._delete_volume(volume)

    def test_extend_volume_not_found(self):
        volume = self._create_volume(driver=False)
        self.assertRaises(exception.VolumeNotFound,
                          self._driver.extend_volume,
                          volume, 10)
        self._delete_volume(volume, False)

    def test_extend_volume_size_less(self):
        volume = self._create_volume(size=100)
        vol_info = self._assert_vol_exists(volume['id'], True)
        self.assertEqual('100', vol_info[0]['size_gb'])
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.extend_volume,
                          volume, '10')
        self._delete_volume(volume)

    def test_extend_volume_size_exceeds_limit(self):
        host = 'stack@ty2#%s' % POOLS_NAME[1]
        self._driver.get_volume_stats()
        volume = self._create_volume(size=10, host=host)
        vol_info = self._assert_vol_exists(volume['id'], True)
        self.assertEqual('10', vol_info[0]['size_gb'])
        self.assertEqual(POOLS_NAME[1], vol_info[0]['poolname'])
        self.assertRaises(exception.VolumeSizeExceedsLimit,
                          self._driver.extend_volume,
                          volume, '200')
        self._delete_volume(volume)

    def test_migrate_volume_same_pool(self):
        host = 'stack@ty1#%s' % POOLS_NAME[0]
        volume = self._create_volume(host=host)
        target_host = {
            'host': 'stack_new@ty1#%s' % POOLS_NAME[0],
            'capabilities': {
                'system_id': self.sim._system_info['system_id'],
                'pool_name': POOLS_NAME[0]
            }
        }
        ret = self._driver.migrate_volume(self.ctxt, volume, target_host)
        self.assertEqual((True, None), ret)

    def test_migrate_volume_different_system(self):
        host = 'stack@ty1#%s' % POOLS_NAME[0]
        volume = self._create_volume(host=host)
        target_host = {
            'host': 'stack_new@ty1#%s' % POOLS_NAME[0],
            'capabilities': {
                'system_id': 'test_system_id',
                'pool_name': POOLS_NAME[0]
            }
        }
        ret = self._driver.migrate_volume(self.ctxt, volume, target_host)
        self.assertEqual((False, None), ret)
        target_host = {
            'host': 'stack_new@ty1#%s' % POOLS_NAME[0],
            'capabilities': {
                'pool_name': POOLS_NAME[0]
            }
        }
        ret = self._driver.migrate_volume(self.ctxt, volume, target_host)
        self.assertEqual((False, None), ret)

    def test_migrate_volume_same_system_different_pool(self):
        host = 'stack@ty1#%s' % POOLS_NAME[0]
        volume = self._create_volume(host=host, size=2)
        target_host = {
            'host': 'stack_new@ty1#%s' % POOLS_NAME[1],
            'capabilities': {
                'system_id': self.sim._system_info['system_id'],
                'pool_name': POOLS_NAME[1]
            }
        }
        ret = self._driver.migrate_volume(self.ctxt, volume, target_host)
        self.assertEqual((True, None), ret)
        vol_info = self._assert_vol_exists(volume['id'], True)
        self.assertEqual(POOLS_NAME[1], vol_info[0]['poolname'])
        self.assertEqual('2', vol_info[0]['size_gb'])

    def test_get_volume_stats(self):
        self.assertEqual({}, self._driver._stats)
        self._driver.get_volume_stats()
        stats = self._driver._stats
        system_info = self.sim._system_info
        self.assertEqual(system_info['vendor'], stats['vendor_name'])

    def test_get_volume_none(self):
        ret = self._driver._cmd.get_volume('')
        self.assertEqual([], ret)
        ret = self._driver._cmd.get_volume('test_volume')
        self.assertEqual([], ret)

    def test_check_for_setup_error_failure(self):
        self._driver._state['system_name'] = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.check_for_setup_error)
        self._driver.do_setup(None)
        self._driver._state['system_id'] = None
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver.check_for_setup_error)
        self._driver.do_setup(None)
        self._driver._state['storage_nodes'] = []
        self.assertRaises(exception.VolumeDriverException,
                          self._driver.check_for_setup_error)
        self._driver.do_setup(None)
        self._driver._state['enabled_protocols'] = set()
        self.assertRaises(exception.InvalidInput,
                          self._driver.check_for_setup_error)
        self._driver.do_setup(None)
        self._driver.configuration.san_password = None
        self.assertRaises(exception.InvalidInput,
                          self._driver.check_for_setup_error)
        self._driver.do_setup(None)

    def test_build_pool_stats_no_pool(self):
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._build_pool_stats,
                          'pool_test')

    def test_set_volume_property_failure(self):
        volume = self._create_volume()
        self._assert_vol_exists(volume['id'], True)
        volume_name = VOLUME_PRE + volume['id'][-12:]
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.set_volume_property,
                          volume_name, {'error_key': 'error'})
        self.assertRaises(exception.VolumeBackendAPIException,
                          self._driver._cmd.set_volume_property,
                          volume_name, {})
        self._delete_volume(volume)
