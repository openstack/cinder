# Copyright (c) 2013 - 2016 Huawei Technologies Co., Ltd.
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
Volume api for FusionStorage systems.
"""

import os
import re
import six

from oslo_log import log as logging

from cinder import utils

LOG = logging.getLogger(__name__)
fsc_conf_file = "/etc/cinder/volumes/fsc_conf"
fsc_cli = "fsc_cli"
fsc_ip = []
fsc_port = '10519'
manage_ip = "127.0.0.1"
CMD_BIN = fsc_cli

volume_info = {
    'result': '',
    'vol_name': '',
    'father_name': '',
    'status': '',
    'vol_size': '',
    'real_size': '',
    'pool_id': '',
    'create_time': ''}


snap_info = {
    'result': '',
    'snap_name': '',
    'father_name': '',
    'status': '',
    'snap_size': '',
    'real_size': '',
    'pool_id': '',
    'delete_priority': '',
    'create_time': ''}


pool_info = {
    'result': '',
    'pool_id': '',
    'total_capacity': '',
    'used_capacity': '',
    'alloc_capacity': ''}


class FSPythonApi(object):

    def __init__(self):
        LOG.debug("FSPythonApi init.")
        self.get_ip_port()
        self.res_idx = len('result=')

    def get_ip_port(self):
        LOG.debug("File fsc_conf_file is %s.", fsc_conf_file)
        if os.path.exists(fsc_conf_file):
            try:
                fsc_file = open(fsc_conf_file, 'r')
                full_txt = fsc_file.readlines()
                LOG.debug("Full_txt is %s.", full_txt)
                for line in full_txt:
                    if re.search('^vbs_url=', line):
                        tmp_vbs_url = line[8:]
                        return re.split(',', tmp_vbs_url)
            except Exception as e:
                LOG.debug("Get fsc ip failed, error=%s.", e)
            finally:
                fsc_file.close()
        else:
            LOG.debug("Fsc conf file not exist, file_name=%s.", fsc_conf_file)

    def get_manage_ip(self):
        LOG.debug("File fsc_conf_file is %s.", fsc_conf_file)
        if os.path.exists(fsc_conf_file):
            try:
                fsc_file = open(fsc_conf_file, 'r')
                full_txt = fsc_file.readlines()
                for line in full_txt:
                    if re.search('^manage_ip=', line):
                        manage_ip = line[len('manage_ip='):]
                        manage_ip = manage_ip.strip('\n')
                        return manage_ip
            except Exception as e:
                LOG.debug("Get manage ip failed, error=%s.", e)
            finally:
                fsc_file.close()
        else:
            LOG.debug("Fsc conf file not exist, file_name=%s.", fsc_conf_file)

    def get_dsw_manage_ip(self):
        return manage_ip

    def start_execute_cmd(self, cmd, full_result_flag):
        fsc_ip = self.get_ip_port()
        manage_ip = self.get_manage_ip()
        ip_num = len(fsc_ip)

        LOG.debug("fsc_ip is %s", fsc_ip)

        if ip_num <= 0:
            return None

        if ip_num > 3:
            ip_num = 3

        exec_result = ''
        result = ''
        if full_result_flag:
            for ip in fsc_ip:
                cmd_args = [CMD_BIN, '--manage_ip', manage_ip.replace(
                    '\n', ''), '--ip', ip.replace('\n', '')] + cmd.split()
                LOG.debug("Dsware cmd_args is %s.", cmd_args)

                exec_result, err = utils.execute(*cmd_args, run_as_root=True)
                exec_result = exec_result.split('\n')
                LOG.debug("Result is %s.", exec_result)
                if exec_result:
                    for line in exec_result:
                        if re.search('^result=0', line):
                            return exec_result
                        elif re.search('^result=50150007', line):
                            return 'result=0'
                        elif re.search('^result=50150008', line):
                            return 'result=0'
                        elif re.search('^result=50', line):
                            return exec_result
            return exec_result
        else:
            for ip in fsc_ip:
                cmd_args = [CMD_BIN, '--manage_ip', manage_ip.replace(
                    '\n', ''), '--ip', ip.replace('\n', '')] + cmd.split()
                LOG.debug("Dsware cmd_args is %s.", cmd_args)

                exec_result, err = utils.execute(*cmd_args, run_as_root=True)
                LOG.debug("Result is %s.", exec_result)
                exec_result = exec_result.split('\n')
                if exec_result:
                    for line in exec_result:
                        if re.search('^result=', line):
                            result = line
                            if re.search('^result=0', line):
                                return line
                            elif re.search('^result=50150007', line):
                                return 'result=0'
                            elif re.search('^result=50150008', line):
                                return 'result=0'
                            elif re.search('^result=50', line):
                                return line
            return result

    def create_volume(self, vol_name, pool_id, vol_size, thin_flag):
        cmd = '--op createVolume' + ' ' + '--volName' + ' ' + six.text_type(
            vol_name) + ' ' + '--poolId' + ' ' + six.text_type(
            pool_id) + ' ' + '--volSize' + ' ' + six.text_type(
            vol_size) + ' ' + '--thinFlag' + ' ' + six.text_type(thin_flag)

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def extend_volume(self, vol_name, new_vol_size):
        cmd = ''
        cmd = '--op expandVolume' + ' ' + '--volName' + ' ' + six.text_type(
            vol_name) + ' ' + '--volSize' + ' ' + six.text_type(new_vol_size)

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def create_volume_from_snap(self, vol_name, vol_size, snap_name):
        cmd = ('--op createVolumeFromSnap' + ' ') + (
            '--volName' + ' ') + six.text_type(
            vol_name) + ' ' + '--snapNameSrc' + ' ' + six.text_type(
            snap_name) + ' ' + '--volSize' + ' ' + six.text_type(vol_size)

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def create_fullvol_from_snap(self, vol_name, snap_name):
        cmd = ('--op createFullVolumeFromSnap' + ' ') + (
            '--volName' + ' ') + six.text_type(
            vol_name) + ' ' + '--snapName' + ' ' + six.text_type(snap_name)

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def create_volume_from_volume(self, vol_name, vol_size, src_vol_name):
        retcode = 1
        tmp_snap_name = six.text_type(vol_name) + '_tmp_snap'

        retcode = self.create_snapshot(tmp_snap_name, src_vol_name, 0)
        if 0 != retcode:
            return retcode

        retcode = self.create_volume(vol_name, 0, vol_size, 0)
        if 0 != retcode:
            self.delete_snapshot(tmp_snap_name)
            return retcode

        retcode = self.create_fullvol_from_snap(vol_name, tmp_snap_name)
        if 0 != retcode:
            self.delete_snapshot(tmp_snap_name)
            self.delete_volume(vol_name)
            return retcode

        return 0

    def create_clone_volume_from_volume(self, vol_name,
                                        vol_size, src_vol_name):
        retcode = 1
        tmp_snap_name = six.text_type(src_vol_name) + '_DT_clnoe_snap'

        retcode = self.create_snapshot(tmp_snap_name, src_vol_name, 0)
        if 0 != retcode:
            return retcode

        retcode = self.create_volume_from_snap(
            vol_name, vol_size, tmp_snap_name)
        if 0 != retcode:
            return retcode

        return 0

    def volume_info_analyze(self, vol_info):
        local_volume_info = volume_info

        if not vol_info:
            local_volume_info['result'] = 1
            return local_volume_info

        local_volume_info['result'] = 0

        vol_info_list = []
        vol_info_list = re.split(',', vol_info)
        for line in vol_info_list:
            line = line.replace('\n', '')
            if re.search('^vol_name=', line):
                local_volume_info['vol_name'] = line[len('vol_name='):]
            elif re.search('^father_name=', line):
                local_volume_info['father_name'] = line[len('father_name='):]
            elif re.search('^status=', line):
                local_volume_info['status'] = line[len('status='):]
            elif re.search('^vol_size=', line):
                local_volume_info['vol_size'] = line[len('vol_size='):]
            elif re.search('^real_size=', line):
                local_volume_info['real_size'] = line[len('real_size='):]
            elif re.search('^pool_id=', line):
                local_volume_info['pool_id'] = line[len('pool_id='):]
            elif re.search('^create_time=', line):
                local_volume_info['create_time'] = line[len('create_time='):]
            else:
                LOG.error("Analyze key not exist, key=%s.", line)
        return local_volume_info

    def query_volume(self, vol_name):
        tmp_volume_info = volume_info
        cmd = '--op queryVolume' + ' ' + '--volName' + ' ' + vol_name

        exec_result = self.start_execute_cmd(cmd, 1)
        if exec_result:
            for line in exec_result:
                if re.search('^result=', line):
                    if not re.search('^result=0', line):
                        tmp_volume_info['result'] = line[self.res_idx:]
                        return tmp_volume_info
                    for line in exec_result:
                        if re.search('^vol_name=' + vol_name, line):
                            tmp_volume_info = self.volume_info_analyze(line)
                            if six.text_type(0) == tmp_volume_info['status']:
                                tmp_snap_name = six.text_type(
                                    vol_name) + '_tmp_snap'
                                self.delete_snapshot(tmp_snap_name)
                            return tmp_volume_info

        tmp_volume_info['result'] = 1
        return tmp_volume_info

    def delete_volume(self, vol_name):
        cmd = '--op deleteVolume' + ' ' + '--volName' + ' ' + vol_name

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def create_snapshot(self, snap_name, vol_name, smart_flag):
        cmd = '--op createSnapshot' + ' ' + '--volName' + ' ' + six.text_type(
            vol_name) + ' ' + '--snapName' + ' ' + six.text_type(
            snap_name) + ' ' + '--smartFlag' + ' ' + six.text_type(smart_flag)

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def snap_info_analyze(self, info):
        local_snap_info = snap_info.copy()

        if not info:
            local_snap_info['result'] = 1
            return local_snap_info

        local_snap_info['result'] = 0

        snap_info_list = []
        snap_info_list = re.split(',', info)
        for line in snap_info_list:
            line = line.replace('\n', '')
            if re.search('^snap_name=', line):
                local_snap_info['snap_name'] = line[len('snap_name='):]
            elif re.search('^father_name=', line):
                local_snap_info['father_name'] = line[len('father_name='):]
            elif re.search('^status=', line):
                local_snap_info['status'] = line[len('status='):]
            elif re.search('^snap_size=', line):
                local_snap_info['snap_size'] = line[len('snap_size='):]
            elif re.search('^real_size=', line):
                local_snap_info['real_size'] = line[len('real_size='):]
            elif re.search('^pool_id=', line):
                local_snap_info['pool_id'] = line[len('pool_id='):]
            elif re.search('^delete_priority=', line):
                local_snap_info['delete_priority'] = line[
                    len('delete_priority='):]
            elif re.search('^create_time=', line):
                local_snap_info['create_time'] = line[len('create_time='):]
            else:
                LOG.error("Analyze key not exist, key=%s.", line)

        return local_snap_info

    def query_snap(self, snap_name):
        tmp_snap_info = snap_info.copy()
        cmd = '--op querySnapshot' + ' ' + '--snapName' + ' ' + snap_name

        exec_result = self.start_execute_cmd(cmd, 1)
        if exec_result:
            for line in exec_result:
                if re.search('^result=', line):
                    if not re.search('^result=0', line):
                        tmp_snap_info['result'] = line[self.res_idx:]
                        return tmp_snap_info
                    for line in exec_result:
                        if re.search('^snap_name=' + snap_name, line):
                            tmp_snap_info = self.snap_info_analyze(line)
                            return tmp_snap_info

        tmp_snap_info['result'] = 1
        return tmp_snap_info

    def delete_snapshot(self, snap_name):
        cmd = '--op deleteSnapshot' + ' ' + '--snapName' + ' ' + snap_name

        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            if re.search('^result=0', exec_result):
                return 0
            else:
                return exec_result[self.res_idx:]
        else:
            return 1

    def pool_info_analyze(self, info):
        local_pool_info = pool_info.copy()

        if not info:
            local_pool_info['result'] = 1
            return local_pool_info

        local_pool_info['result'] = 0

        pool_info_list = []
        pool_info_list = re.split(',', info)
        for line in pool_info_list:
            line = line.replace('\n', '')
            if re.search('^pool_id=', line):
                local_pool_info['pool_id'] = line[len('pool_id='):]
            elif re.search('^total_capacity=', line):
                local_pool_info['total_capacity'] = line[
                    len('total_capacity='):]
            elif re.search('^used_capacity=', line):
                local_pool_info['used_capacity'] = line[len('used_capacity='):]
            elif re.search('^alloc_capacity=', line):
                local_pool_info['alloc_capacity'] = line[
                    len('alloc_capacity='):]
            else:
                LOG.error("Analyze key not exist, key=%s.", line)
        return local_pool_info

    def query_pool_info(self, pool_id):
        tmp_pool_info = pool_info.copy()
        cmd = '--op queryPoolInfo' + ' ' + '--poolId' + ' ' + six.text_type(
            pool_id)
        LOG.debug("Pool id is %s.", pool_id)
        exec_result = self.start_execute_cmd(cmd, 1)
        if exec_result:
            for line in exec_result:
                if re.search('^result=', line):
                    if not re.search('^result=0', line):
                        tmp_pool_info['result'] = line[self.res_idx:]
                        return tmp_pool_info
                    for line in exec_result:
                        if re.search('^pool_id=' + six.text_type(pool_id),
                                     line):
                            tmp_pool_info = self.pool_info_analyze(line)
                            return tmp_pool_info

        tmp_pool_info['result'] = 1
        return tmp_pool_info

    def query_pool_type(self, pool_type):
        pool_list = []
        tmp_pool_info = {}
        result = 0
        cmd = ''
        cmd = '--op queryPoolType --poolType' + ' ' + pool_type
        LOG.debug("Query poolType: %s.", pool_type)
        exec_result = self.start_execute_cmd(cmd, 1)
        if exec_result:
            for line in exec_result:
                line = line.replace('\n', '')
                if re.search('^result=', line):
                    if not re.search('^result=0', line):
                        result = int(line[self.res_idx:])
                        break
                    for one_line in exec_result:
                        if re.search('^pool_id=', one_line):
                            tmp_pool_info = self.pool_info_analyze(one_line)
                            pool_list.append(tmp_pool_info)
                    break
        return (result, pool_list)

    def query_dsware_version(self):
        retcode = 2
        cmd = '--op getDSwareIdentifier'
        exec_result = self.start_execute_cmd(cmd, 0)
        if exec_result:
            # New version.
            if re.search('^result=0', exec_result):
                retcode = 0
            # Old version.
            elif re.search('^result=50500001', exec_result):
                retcode = 1
            # Failed!
            else:
                retcode = exec_result[self.res_idx:]
        return retcode
