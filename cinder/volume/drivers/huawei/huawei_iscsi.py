# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2012 Huawei Technologies Co., Ltd.
# Copyright (c) 2012 OpenStack LLC.
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
Volume driver for HUAWEI T series and Dorado storage systems.
"""

import re
import socket
import time

from oslo.config import cfg
from xml.etree import ElementTree as ET

from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver

LOG = logging.getLogger(__name__)

huawei_opt = [
    cfg.StrOpt('cinder_huawei_conf_file',
               default='/etc/cinder/cinder_huawei_conf.xml',
               help='config data for cinder huawei plugin')]

HOST_GROUP_NAME = 'HostGroup_OpenStack'
HOST_NAME_PREFIX = 'Host_'
HOST_PORT_PREFIX = 'HostPort_'
VOL_AND_SNAP_NAME_FREFIX = 'OpenStack_'
READBUFFERSIZE = 8192


class SSHConnection(utils.SSHPool):
    """An SSH connetion class .

    For some reasons, we can not use method ssh_execute defined in utils to
    send CLI commands. Here we define a new class inherited to SSHPool. Use
    method create() to build a new SSH client and use invoke_shell() to start
    an interactive shell session on the storage system.
    """

    def __init__(self, ip, port, login, password, conn_timeout,
                 privatekey=None, *args, **kwargs):
        self.ssh = None
        super(SSHConnection, self).__init__(ip, port, conn_timeout, login,
                                            password, privatekey=None,
                                            *args, **kwargs)

    def connect(self):
        """Create an SSH client and open an interactive SSH channel."""
        self.ssh = self.create()
        self.channel = self.ssh.invoke_shell()
        self.channel.resize_pty(600, 800)

    def close(self):
        """Close SSH connection."""
        self.channel.close()
        self.ssh.close()

    def read(self, timeout=None):
        """Read data from SSH channel."""
        result = ''
        user_flg = self.login + ':/>$'
        self.channel.settimeout(timeout)
        while True:
            try:
                result = result + self.channel.recv(READBUFFERSIZE)
            except socket.timeout:
                break
            else:
                # If we get the complete result string, then no need to wait
                # until time out.
                if re.search(user_flg, result) or re.search('(y/n)', result):
                    break
        return result

    def send_cmd(self, strcmd, timeout, waitstr=None):
        """Send SSH commands and return results."""
        info = ''
        self.channel.send(strcmd + '\n')
        result = self.read(timeout)
        info = '\r\n'.join(result.split('\r\n')[1:-1])
        return info


class HuaweiISCSIDriver(driver.ISCSIDriver):
    """Huawei T series and Dorado iSCSI volume driver."""

    def __init__(self, *args, **kwargs):
        super(HuaweiISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(huawei_opt)
        self.device_type = {}
        self.login_info = {}
        self.hostgroup_id = None

        # Flag to tell whether the other controller is available
        # if the current controller can not be connected to.
        self.controller_alterable = True

    def do_setup(self, context):
        """Check config file."""
        LOG.debug(_('do_setup.'))

        self._check_conf_file()
        # Create hostgroup.
        self.login_info = self._get_login_info()
        hostgroup_name = HOST_GROUP_NAME
        self.hostgroup_id = self._find_hostgroup(hostgroup_name)
        if not self.hostgroup_id:
            self._create_hostgroup(hostgroup_name)
            self.hostgroup_id = self._find_hostgroup(hostgroup_name)

    def check_for_setup_error(self):
        """Try to connect with device and get device type."""
        LOG.debug(_('check_for_setup_error.'))

        self.login_info = self._get_login_info()
        self.device_type = self._get_device_type()
        if not self.device_type['type']:
            err_msg = (_('check_for_setup_error: Can not get device type.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        LOG.debug(_('check_for_setup_error: Device type is:%(type)s, '
                    'version is:%(version)s.')
                  % {'type': self.device_type['type'],
                     'version': self.device_type['version']})

        # Now only version V1 is supported.
        if self.device_type['version'] != 'V100R':
            err_msg = (_('check_for_setup_error: Product version not right. '
                         'Please make sure the product version is V1.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def create_volume(self, volume):
        """Create a new volume."""
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('create_volume:volume name: %s.') % volume_name)

        self.login_info = self._get_login_info()
        if int(volume['size']) == 0:
            volume_sise = '100M'
        else:
            volume_sise = '%sG' % volume['size']

        self._create_volume(volume_name, volume_sise)

    def delete_volume(self, volume):
        """Delete a volume."""
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('delete_volume: volume name: %s.') % volume_name)

        self.login_info = self._get_login_info()
        volume_id = self._find_lun(volume_name)
        if volume_id:
            self._delete_volume(volume_name, volume_id)
        else:
            err_msg = (_('delete_volume:No need to delete volume.'
                         'Volume %(name)s does not exist.')
                       % {'name': volume['name']})
            LOG.error(err_msg)

    def create_export(self, context, volume):
        """Driver entry point to get the  export info for a new volume."""
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('create_export: volume name:%s') % volume['name'])

        lun_id = self._find_lun(volume_name)
        if not lun_id:
            err_msg = (_('create_export:Volume %(name)s does not exist.')
                       % {'name': volume_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        return {'provider_location': lun_id}

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for a existing volume."""
        pass

    def remove_export(self, context, volume_id):
        """Driver entry point to remove an export for a volume."""
        pass

    def initialize_connection(self, volume, connector):
        """Map a volume to a host and return target iSCSI information."""
        initiator_name = connector['initiator']
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('initialize_connection: volume name: %(volume)s. '
                    'initiator name: %(ini)s.')
                  % {'volume': volume_name,
                     'ini': initiator_name})

        host_name = HOST_NAME_PREFIX + str(hash(initiator_name))
        host_id = self._find_host_in_hostgroup(host_name, self.hostgroup_id)
        if not host_id:
            self._add_host(host_name, self.hostgroup_id)
            host_id = self._find_host_in_hostgroup(host_name,
                                                   self.hostgroup_id)

        # Create an initiator.
        added = self._check_initiator(initiator_name)
        if not added:
            self._add_initiator(initiator_name)

        # Add the initiator to host.
        port_name = HOST_PORT_PREFIX + str(hash(initiator_name))
        port_info = initiator_name
        portadded = False
        hostport_info = self._get_hostport_info(host_id)
        if hostport_info:
            for hostport in hostport_info:
                if hostport['info'] == initiator_name:
                    portadded = True
                    break
        if not portadded:
            self._add_hostport(port_name, host_id, port_info)

        LOG.debug(_('initialize_connection:host name: %(host)s,'
                    'initiator name: %(ini)s, '
                    'hostport name: %(port)s')
                  % {'host': host_name,
                     'ini': initiator_name,
                     'port': port_name})

        # Get target iSCSI iqn.
        iscsi_conf = self._get_iscsi_info()
        target_ip = None
        for ini in iscsi_conf['Initiator']:
            if ini['Name'] == initiator_name:
                target_ip = ini['TargetIP']
                break
        if not target_ip:
            target_ip = iscsi_conf['DefaultTargetIP']

        target_iqn = self._get_tgt_iqn(target_ip)
        if not target_iqn:
            err_msg = (_('initialize_connection:'
                         'Failed to find target iSCSI iqn.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        # Map a LUN to a host if not mapped.
        lun_id = self._find_lun(volume_name)
        if not lun_id:
            err_msg = (_('initialize_connection:Failed to find the '
                         'given volume. '
                         'volume name:%(volume)s.')
                       % {'volume': volume_name})
            raise exception.VolumeBackendAPIException(data=err_msg)

        hostlun_id = None
        map_info = self._get_map_info(host_id)
        # Make sure the hostLUN ID starts from 1.
        new_hostlun_id = 1
        new_hostlunid_found = False
        if map_info:
            for map in map_info:
                if map['devlunid'] == lun_id:
                    hostlun_id = map['hostlunid']
                    break
                elif not new_hostlunid_found:
                    if new_hostlun_id < int(map['hostlunid']):
                        new_hostlunid_found = True
                    else:
                        new_hostlun_id = int(map['hostlunid']) + 1
        # The LUN is not mapped to the host.
        if not hostlun_id:
            self._map_lun(lun_id, host_id, new_hostlun_id)
            hostlun_id = self._get_hostlunid(host_id, lun_id)

        # Return iSCSI properties.
        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = ('%s:%s' % (target_ip, '3260'))
        properties['target_iqn'] = target_iqn
        properties['target_lun'] = int(hostlun_id)
        properties['volume_id'] = volume['id']
        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return {'driver_volume_type': 'iscsi', 'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Delete map between a volume and a host."""
        initiator_name = connector['initiator']
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('terminate_connection:volume name: %(volume)s, '
                    'initiator name: %(ini)s.')
                  % {'volume': volume_name,
                     'ini': initiator_name})

        self.login_info = self._get_login_info()
        host_name = HOST_NAME_PREFIX + str(hash(initiator_name))
        host_id = self._find_host_in_hostgroup(host_name, self.hostgroup_id)
        if not host_id:
            err_msg = (_('terminate_connection:Host does not exist. '
                         'Host name:%(host)s.')
                       % {'host': host_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        # Delete host map.
        lun_id = self._find_lun(volume_name)
        if not lun_id:
            err_msg = (_('terminate_connection:volume does not exist.'
                         'volume name:%(volume)s')
                       % {'volume': volume_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        map_id = None
        mapnum = 0
        map_info = self._get_map_info(host_id)
        if map_info:
            mapnum = len(map_info)
            for map in map_info:
                if map['devlunid'] == lun_id:
                    map_id = map['mapid']
                    break
        if map_id:
            self._delete_map(map_id)
            mapnum = mapnum - 1
        else:
            LOG.error(_('terminate_connection:No map between host '
                        'and volume. Host name:%(hostname)s,'
                        'volume name:%(volumename)s.')
                      % {'hostname': host_name,
                         'volumename': volume_name})

        # Delete host initiator when no LUN mapped to it.
        portnum = 0
        hostportinfo = self._get_hostport_info(host_id)
        if hostportinfo:
            portnum = len(hostportinfo)
            for hostport in hostportinfo:
                if hostport['info'] == initiator_name and mapnum == 0:
                    self._delete_hostport(hostport['id'])
                    self._delete_initiator(initiator_name)
                    portnum = portnum - 1
                    break
        else:
            LOG.error(_('terminate_connection:No initiator is added '
                        'to the host. Host name:%(hostname)s')
                      % {'hostname': host_name})

        # Delete host when no initiator added to it.
        if portnum == 0:
            self._delete_host(host_id)

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        snapshot_name = self._name_translate(snapshot['name'])
        volume_name = self._name_translate(snapshot['volume_name'])

        LOG.debug(_('create_snapshot:snapshot name:%(snapshot)s, '
                    'volume name:%(volume)s.')
                  % {'snapshot': snapshot_name,
                     'volume': volume_name})

        self.login_info = self._get_login_info()
        if self.device_type['type'] == 'Dorado2100 G2':
            err_msg = (_('create_snapshot:Device does not support snapshot.'))

            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        if self._is_resource_pool_enough() is False:
            err_msg = (_('create_snapshot:'
                         'Resource pool needs 1GB valid size at least.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        lun_id = self._find_lun(volume_name)
        if not lun_id:
            err_msg = (_('create_snapshot:Volume does not exist.'
                         'Volume name:%(name)s')
                       % {'name': volume_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        self._create_snapshot(snapshot_name, lun_id)
        snapshot_id = self._find_snapshot(snapshot_name)
        if not snapshot_id:
            err_msg = (_('create_snapshot:Snapshot does not exist.'
                         'Snapshot name:%(name)s')
                       % {'name': snapshot_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        self._active_snapshot(snapshot_id)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        snapshot_name = self._name_translate(snapshot['name'])
        volume_name = self._name_translate(snapshot['volume_name'])

        LOG.debug(_('delete_snapshot:snapshot name:%(snapshot)s, '
                    'volume name:%(volume)s.')
                  % {'snapshot': snapshot_name,
                     'volume': volume_name})

        self.login_info = self._get_login_info()
        if self.device_type['type'] == 'Dorado2100 G2':
            err_msg = (_('delete_snapshot:Device does not support snapshot.'))
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        snapshot_id = self._find_snapshot(snapshot_name)
        if snapshot_id:
            self._disable_snapshot(snapshot_id)
            self._delete_snapshot(snapshot_id)
        else:
            err_msg = (_('delete_snapshot:Snapshot does not exist. '
                         'snapshot name:%(snap)s')
                       % {'snap': snapshot_name})
            LOG.debug(err_msg)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot.

        We use LUNcopy to create a new LUN from snapshot.
        """
        snapshot_name = self._name_translate(snapshot['name'])
        volume_name = self._name_translate(volume['name'])

        LOG.debug(_('create_volume_from_snapshot:snapshot '
                    'name:%(snapshot)s, '
                    'volume name:%(volume)s.')
                  % {'snapshot': snapshot_name,
                     'volume': volume_name})

        self.login_info = self._get_login_info()
        if self.device_type['type'].find('Dorado') > -1:
            err_msg = (_('create_volume_from_snapshot:Device does '
                         'not support create volume from snapshot. '
                         'Volume name:%(volume)s, '
                         'snapshot name:%(snapshot)s.')
                       % {'volume': volume_name,
                          'snapshot': snapshot_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        snapshot_id = self._find_snapshot(snapshot_name)
        if not snapshot_id:
            err_msg = (_('create_volume_from_snapshot:Snapshot does not exist.'
                         'Snapshot name:%(name)s')
                       % {'name': snapshot_name})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

        # Create a target LUN.
        if int(volume['size']) == 0:
            volume_size = '%sG' % snapshot['volume_size']
        else:
            volume_size = '%sG' % volume['size']

        self._create_volume(volume_name, volume_size)
        volume_id = self._find_lun(volume_name)
        luncopy_name = volume_name
        try:
            self._create_luncopy(luncopy_name, snapshot_id, volume_id)
            luncopy_id = self._find_luncopy(luncopy_name)
            self._start_luncopy(luncopy_id)
            self._wait_for_luncopy(luncopy_name)
        # If LUNcopy failed,we should delete the target volume.
        except Exception:
            with excutils.save_and_reraise_exception():
                self._delete_luncopy(luncopy_id)
                self._delete_volume(volume_name, volume_id)

        self._delete_luncopy(luncopy_id)

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_status()

        return self._stats

    def _check_conf_file(self):
        """Check the config file, make sure the key elements are set."""
        root = self._read_xml()
        try:
            IP1 = root.findtext('Storage/ControllerIP0')
            IP2 = root.findtext('Storage/ControllerIP1')
            username = root.findtext('Storage/UserName')
            pwd = root.findtext('Storage/UserPassword')
            pool = root.findall('LUN/StoragePool')

            isconfwrong = False
            if ((not IP1 and not IP2) or
                    (not username) or
                    (not pwd) or
                    (not pool)):
                isconfwrong = True

            elif not pool[0].attrib['Name']:
                isconfwrong = True

            if isconfwrong is True:
                err_msg = (_('Config file is wrong. '
                             'Controler IP, UserName, UserPassword and '
                             'StoragePool must be set.'))
                LOG.error(err_msg)
                raise exception.InvalidInput(reason=err_msg)

        except Exception as err:
            LOG.error(_('_check_conf_file: %s') % str(err))
            raise exception.VolumeBackendAPIException(data=err)

    def _read_xml(self):
        """Open xml file."""
        filename = self.configuration.cinder_huawei_conf_file
        try:
            tree = ET.parse(filename)
            root = tree.getroot()

        except Exception as err:
            LOG.error(_('_read_xml:%s') % err)
            raise exception.VolumeBackendAPIException(data=err)
        return root

    def _get_login_info(self):
        """Get login IP, username and password from config file."""
        logininfo = {}
        root = self._read_xml()
        try:
            logininfo['ControllerIP0'] = root.findtext('Storage/ControllerIP0')
            logininfo['ControllerIP1'] = root.findtext('Storage/ControllerIP1')
            logininfo['UserName'] = root.findtext('Storage/UserName')
            logininfo['UserPassword'] = root.findtext('Storage/UserPassword')

        except Exception as err:
            LOG.debug(_('_get_login_info error. %s') % err)
            raise exception.VolumeBackendAPIException(data=err)
        return logininfo

    def _get_lun_set_info(self):
        """Get parameters from config file for creating LUN."""
        # Default LUN set information
        lunsetinfo = {'LUNType': 'Thick',
                      'StripUnitSize': '64',
                      'WriteType': '1',
                      'MirrorSwitch': '1',
                      'PrefetchType': '3',
                      'PrefetchValue': '0',
                      'PrefetchTimes': '0',
                      'StoragePool': 'RAID_001'}

        root = self._read_xml()
        try:
            luntype = root.findtext('LUN/LUNType')
            if luntype in ['Thick', 'Thin']:
                lunsetinfo['LUNType'] = luntype
            elif luntype is not '' or luntype is not None:
                err_msg = (_('Config file is wrong. LUNType must be "Thin"'
                             ' or "Thick". LUNType:%(type)s')
                           % {'type': luntype})
                raise exception.VolumeBackendAPIException(data=err_msg)

            # Here we do not judge whether the parameters are right.
            # CLI will return error responses if the parameters not right.
            stripunitsize = root.findtext('LUN/StripUnitSize')
            if stripunitsize is not '' and stripunitsize is not None:
                lunsetinfo['StripUnitSize'] = stripunitsize
            writetype = root.findtext('LUN/WriteType')
            if writetype is not '' and writetype is not None:
                lunsetinfo['WriteType'] = writetype
            mirrorswitch = root.findtext('LUN/MirrorSwitch')
            if mirrorswitch is not '' and mirrorswitch is not None:
                lunsetinfo['MirrorSwitch'] = mirrorswitch

            if self.device_type['type'] == 'Tseries':
                pooltype = luntype
                prefetch = root.find('LUN/Prefetch')
                if ((prefetch is not None) and
                        (prefetch.attrib['Type'] != '')):
                    lunsetinfo['PrefetchType'] = prefetch.attrib['Type']
                    if lunsetinfo['PrefetchType'] == '1':
                        lunsetinfo['PrefetchValue'] = prefetch.attrib['Value']
                    elif lunsetinfo['PrefetchType'] == '2':
                        lunsetinfo['PrefetchTimes'] = prefetch.attrib['Value']
                else:
                    LOG.debug(_('_get_lun_set_info:Use default prefetch type. '
                                'Prefetch type:Intelligent.'))

            # No need to set Prefetch type for Dorado.
            elif self.device_type['type'] == 'Dorado5100':
                pooltype = 'Thick'
            elif self.device_type['type'] == 'Dorado2100 G2':
                return lunsetinfo

            poolsinfo = self._find_pool_info(pooltype)
            if not poolsinfo:
                err_msg = (_('_get_lun_set_info:No available pools! '
                             'Please check whether storage pool is created.'))
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            pools = root.findall('LUN/StoragePool')
            lunsetinfo['StoragePool'] = \
                self._get_maximum_pool(pools, poolsinfo, luntype)

        except Exception as err:
            LOG.error(_('_get_lun_set_info:%s') % err)
            raise exception.VolumeBackendAPIException(data=err)

        return lunsetinfo

    def _find_pool_info(self, pooltype):
        """Return pools information created in storage device."""
        if pooltype == 'Thick':
            cli_cmd = ('showrg')
        else:
            cli_cmd = ('showpool')

        out = self._execute_cli(cli_cmd)

        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        pools_list = []
        for i in range(6, len(en) - 2):
            r = en[i].split()
            pools_list.append(r)
        return pools_list

    def _get_maximum_pool(self, poolinconf, poolindev, luntype):
        """Get the maximum pool from config file.

        According to the given pools' name in config file,
        we select the pool of maximum free capacity.
        """
        maxpoolid = None
        maxpoolsize = 0
        if luntype == 'Thin':
            nameindex = 1
            sizeindex = 4
        else:
            nameindex = 5
            sizeindex = 3

        for pool in poolinconf:
            poolname = pool.attrib['Name']
            for pooldetail in poolindev:
                if pooldetail[nameindex] == poolname:
                    if int(float(pooldetail[sizeindex])) > maxpoolsize:
                        maxpoolid = pooldetail[0]
                        maxpoolsize = int(float(pooldetail[sizeindex]))
                    break
        if maxpoolid:
            return maxpoolid
        else:
            err_msg = (_('_get_maximum_pool:maxpoolid is None.'
                         'Please check config file and make sure '
                         'the "Name" in "StoragePool" is right.'))
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _get_iscsi_info(self):
        """Get iSCSI info from config file."""
        iscsiinfo = {}
        root = self._read_xml()
        try:
            iscsiinfo['DefaultTargetIP'] = \
                root.findtext('iSCSI/DefaultTargetIP')
            initiator_list = []
            for dic in root.findall('iSCSI/Initiator'):
                initiator_list.append(dic.attrib)
            iscsiinfo['Initiator'] = initiator_list

        except Exception as err:
            LOG.error(_('_get_iscsi_info:%s') % str(err))

        return iscsiinfo

    def _execute_cli(self, cmd):
        """Build SSH connection to execute CLI commands.

        If the connection to first controller time out,
        try to connect to the other controller.
        """
        user = self.login_info['UserName']
        pwd = self.login_info['UserPassword']
        while True:
            if self.controller_alterable:
                ip = self.login_info['ControllerIP0']
            else:
                ip = self.login_info['ControllerIP1']

            try:
                ssh = SSHConnection(ip, 22, user, pwd, 30)
                ssh.connect()
                while True:
                    out = ssh.send_cmd(cmd, 30)
                    if out.find('(y/n)') > -1:
                        cmd = 'y'
                    else:
                        break
                ssh.close()
            except Exception as err:
                if ((not self.controller_alterable) and
                        (str(err).find('timed out') > -1)):
                    self.controller_alterable = False

                    LOG.debug(_('_execute_cli:Connect to controller0 %(ctr0)s'
                                ' time out.Try to Connect to controller1 '
                                '%(ctr1)s.')
                              % {'ctr0': self.login_info['ControllerIP0'],
                                 'ctr1': self.login_info['ControllerIP1']})

                    continue
                else:
                    LOG.error(_('_execute_cli:%s') % err)
                    raise exception.VolumeBackendAPIException(data=err)

            index = out.find(user + ':/>')
            if index > -1:
                return out[index:]
            else:
                return out

    def _name_translate(self, name):
        """Form new names because of the 32-character limit on names."""
        newname = VOL_AND_SNAP_NAME_FREFIX + str(hash(name))

        LOG.debug(_('_name_translate:Name in cinder: %(old)s, '
                    'new name in storage system: %(new)s')
                  % {'old': name,
                     'new': newname})

        return newname

    def _find_lun(self, name):
        """Get the ID of a LUN with the given LUN name."""
        cli_cmd = ('showlun')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        if 'Dorado2100 G2' == self.device_type['type']:
            d = 2
        elif 'Dorado5100' == self.device_type['type']:
            d = 1
        else:
            d = 0

        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[6 - d] == name:
                return r[0]
        return None

    def _create_hostgroup(self, hostgroupname):
        """Create a host group."""
        cli_cmd = ('createhostgroup -n %(name)s'
                   % {'name': hostgroupname})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_create_hostgroup:Failed to Create hostgroup. '
                         'Hostgroup name: %(name)s. '
                         'out:%(out)s.')
                       % {'name': hostgroupname,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _find_hostgroup(self, groupname):
        """Get the given hostgroup ID."""
        cli_cmd = ('showhostgroup')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[1] == groupname:
                return r[0]
        return None

    def _add_host(self, hostname, hostgroupid):
        """Add a new host."""
        cli_cmd = ('addhost -group %(groupid)s -n %(hostname)s -t 0'
                   % {'groupid': hostgroupid,
                      'hostname': hostname})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_add_host:Failed to add host to hostgroup.'
                         'host name:%(host)s '
                         'hostgroup id:%(hostgroup)s '
                         'out:%(out)s')
                       % {'host': hostname,
                          'hostgroup': hostgroupid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _check_initiator(self, ininame):
        """Check whether the initiator is already added."""
        cli_cmd = ('showiscsiini -ini %(name)s'
                   % {'name': ininame})
        out = self._execute_cli(cli_cmd)
        if out.find('Initiator Information') > -1:
            return True
        else:
            return False

    def _add_initiator(self, ininame):
        """Add a new initiator to storage device."""
        cli_cmd = ('addiscsiini -n %(name)s'
                   % {'name': ininame})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_add_initiator:Failed to add initiator.'
                         'initiator name:%(name)s '
                         'out:%(out)s')
                       % {'name': ininame,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_initiator(self, ininame):
        """Delete an initiator."""
        cli_cmd = ('deliscsiini -n %(name)s'
                   % {'name': ininame})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_delete_initiator:ERROE:Failed to delete initiator.'
                         'initiator name:%(name)s '
                         'out:%(out)s')
                       % {'name': ininame,
                          'out': out})
            LOG.error(err_msg)

    def _find_host_in_hostgroup(self, hostname, hostgroupid):
        """Get the given host ID."""
        cli_cmd = ('showhost -group %(groupid)s'
                   % {'groupid': hostgroupid})
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) < 6:
            return None

        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[1] == hostname:
                return r[0]
        return None

    def _get_hostport_info(self, hostid):
        """Get hostports details of the given host."""
        cli_cmd = ('showhostport -host %(hostid)s'
                   % {'hostid': hostid})
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) < 6:
            return None

        hostportinfo = []
        list_key = ['id', 'name', 'info', 'type', 'hostid',
                    'linkstatus', 'multioathtype']
        for i in range(6, len(en) - 2):
            list_val = en[i].split()
            hostport_dic = dict(map(None, list_key, list_val))
            hostportinfo.append(hostport_dic)
        return hostportinfo

    def _add_hostport(self, portname, hostid, portinfo, multipathtype=0):
        """Add a host port."""
        cli_cmd = ('addhostport -host %(id)s -type 5 '
                   '-info %(info)s -n %(name)s -mtype %(mtype)s'
                   % {'id': hostid,
                      'info': portinfo,
                      'name': portname,
                      'mtype': multipathtype})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_add_hostport:Failed to add hostport. '
                         'port name:%(port)s'
                         'port information:%(info)s '
                         'host id:%(host)s'
                         'out:%(out)s')
                       % {'port': portname,
                          'info': portinfo,
                          'host': hostid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_hostport(self, portid):
        """Delete a host port."""
        cli_cmd = ('delhostport -force -p %(portid)s'
                   % {'portid': portid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_delete_hostport:Failed to delete host port. '
                         'port id:%(portid)s')
                       % {'portid': portid})
            LOG.error(err_msg)

    def _get_tgt_iqn(self, iscsiip):
        """Get target iSCSI iqn."""
        LOG.debug(_('_get_tgt_iqn:iSCSI IP is %s.') % iscsiip)
        cli_cmd = ('showiscsitgtname')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) < 4:
            return None

        index = en[4].find('iqn')
        iqn_prefix = en[4][index:]
        iqn_prefix.strip()
        iscsiip_info = self._get_iscsi_ip_info(iscsiip)
        if iscsiip_info:
            if iscsiip_info['ctrid'] == 'A':
                ctr = '0'
            elif iscsiip_info['ctrid'] == 'B':
                ctr = '1'

            interface = '0' + iscsiip_info['interfaceid']
            port = iscsiip_info['portid'].replace('P', '0')
            iqn_suffix = ctr + '02' + interface + port
            for i in range(0, len(iqn_suffix)):
                if iqn_suffix[i] != '0':
                    iqn_suffix = iqn_suffix[i:]
                    break
            if self.device_type['type'] == 'Tseries':
                iqn = iqn_prefix + ':' + iqn_suffix + ':' \
                    + iscsiip_info['ipaddress']
            elif self.device_type['type'] == "Dorado2100 G2":
                iqn = iqn_prefix + ":" + iscsiip_info['ipaddress'] + "-" \
                    + iqn_suffix
            else:
                iqn = iqn_prefix + ':' + iscsiip_info['ipaddress']

            LOG.debug(_('_get_tgt_iqn:iSCSI target iqn is:%s') % iqn)

            return iqn
        else:
            return None

    def _get_iscsi_ip_info(self, iscsiip):
        """Get iSCSI IP infomation of storage device."""
        cli_cmd = ('showiscsiip')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) < 6:
            return None

        iscsiIPinfo = {}
        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[3] == iscsiip:
                iscsiIPinfo['ctrid'] = r[0]
                iscsiIPinfo['interfaceid'] = r[1]
                iscsiIPinfo['portid'] = r[2]
                iscsiIPinfo['ipaddress'] = r[3]
                return iscsiIPinfo
        return None

    def _map_lun(self, lunid, hostid, new_hostlun_id):
        """Map a lun to a host.

        Here we give the hostlun ID which starts from 1.
        """
        cli_cmd = ('addhostmap -host %(hostid)s -devlun %(lunid)s'
                   '-hostlun %(hostlunid)s'
                   % {'hostid': hostid,
                      'lunid': lunid,
                      'hostlunid': new_hostlun_id})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_map_lun:Failed to add hostmap.'
                         'hostid:%(host)s'
                         'lunid:%(lun)s'
                         'hostlunid:%(hostlunid)s.'
                         'out:%(out)s')
                       % {'host': hostid,
                          'lun': lunid,
                          'hostlunid': new_hostlun_id,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _get_hostlunid(self, hostid, lunid):
        """Get the hostLUN ID of a LUN according host ID and LUN ID."""
        mapinfo = self._get_map_info(hostid)
        if mapinfo:
            for map in mapinfo:
                if map['devlunid'] == lunid:
                    return map['hostlunid']
        return None

    def _delete_map(self, mapid, attempts=1):
        """Remove the map."""
        cli_cmd = ('delhostmap -force -map %(mapid)s'
                   % {'mapid': mapid})
        while attempts >= 0:
            attempts -= 1
            out = self._execute_cli(cli_cmd)

            # We retry to delete host map 10s later if there are
            # IOs accessing the system.
            if re.search('command operates successfully', out):
                break
            else:
                if re.search('there are IOs accessing the system', out):
                    time.sleep(10)
                    LOG.debug(_('_delete_map:There are IOs accessing '
                                'the system. Retry to delete host map. '
                                'map id:%(mapid)s')
                              % {'mapid': mapid})
                    continue
                else:
                    err_msg = (_('_delete_map:Failed to delete host map.'
                                 ' mapid:%(mapid)s '
                                 'out:%(out)s')
                               % {'mapid': mapid,
                                  'out': out})
                    LOG.error(err_msg)
                    raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_host(self, hostid):
        """Delete a host."""
        cli_cmd = ('delhost -force -host %(hostid)s'
                   % {'hostid': hostid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('Error: Failed delete host,host id: %(hostid)s.'
                         'out:%(out)s')
                       % {'hostid': hostid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _get_map_info(self, hostid):
        """Get map infomation of the given host.

        This method return a map information list. Every item in the list
        is a dictionary. The dictionarie includes three keys: mapid,
        devlunid, hostlunid. These items are sorted by hostlunid value
        from small to large.
        """
        cli_cmd = ('showhostmap -host %(hostid)s'
                   % {'hostid': hostid})
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        mapinfo = []
        list_tmp = []
        list_key = ['mapid', 'devlunid', 'hostlunid']
        for i in range(6, len(en) - 2):
            list_tmp = en[i].split()
            list_val = [list_tmp[0], list_tmp[2], list_tmp[4]]
            dic = dict(map(None, list_key, list_val))
            inserted = False
            mapinfo_length = len(mapinfo)
            if mapinfo_length == 0:
                mapinfo.append(dic)
                continue
            for index in range(0, mapinfo_length):
                if (int(mapinfo[mapinfo_length - index - 1]['hostlunid']) <
                        int(dic['hostlunid'])):
                    mapinfo.insert(mapinfo_length - index, dic)
                    inserted = True
                    break
            if not inserted:
                mapinfo.insert(0, dic)
        return mapinfo

    def _get_device_type(self):
        """Get the storage device type and product version."""
        cli_cmd = ('showsys')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        for line in en:
            if re.search('Device Type', line):
                if re.search('T$', line):
                    device_type = 'Tseries'
                elif re.search('Dorado2100 G2$', line):
                    device_type = 'Dorado2100 G2'
                elif re.search('Dorado5100$', line):
                    device_type = 'Dorado5100'
                else:
                    device_type = None
                continue

            if re.search('Product Version', line):
                if re.search('V100R+', line):
                    product_version = 'V100R'
                else:
                    product_version = None
                break

        r = {'type': device_type, 'version': product_version}
        return r

    def _active_snapshot(self, snapshotid):
        """Active a snapshot."""
        cli_cmd = ('actvsnapshot -snapshot %(snapshotid)s'
                   % {'snapshotid': snapshotid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_active_snapshot:Failed to active snapshot. '
                         'snapshot id:%(name)s. '
                         'out:%(out)s')
                       % {'name': snapshotid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _disable_snapshot(self, snapshotid):
        """Disable a snapshot."""
        cli_cmd = ('disablesnapshot -snapshot %(snapshotid)s'
                   % {'snapshotid': snapshotid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_disable_snapshot:Failed to disable snapshot. '
                         'snapshot id:%(id)s. '
                         'out:%(out)s')
                       % {'id': snapshotid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_snapshot(self, snapshotid):
        """Delete a snapshot."""
        cli_cmd = ('delsnapshot -snapshot %(snapshotid)s'
                   % {'snapshotid': snapshotid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_delete_snapshot:Failed to delete snapshot. '
                         'snapshot id:%(id)s. '
                         'out:%(out)s')
                       % {'id': snapshotid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _create_volume(self, name, size):
        """Create a new volume with the given name and size."""
        lunsetinfo = self._get_lun_set_info()
        cli_cmd = ('createlun -n %(name)s -lunsize %(size)s '
                   '-wrtype %(wrtype)s '
                   % {'name': name,
                      'size': size,
                      'wrtype': lunsetinfo['WriteType']})

        # If write type is "write through", no need to set mirror switch.
        if lunsetinfo['WriteType'] != '2':
            cli_cmd = cli_cmd + ('-mirrorsw %(mirrorsw)s '
                                 % {'mirrorsw': lunsetinfo['MirrorSwitch']})

        # Differences exist between "Thin" and "thick" LUN for CLI commands.
        luntype = lunsetinfo['LUNType']
        if luntype == 'Thin':
            dorado2100g2_luntype = '2'
            Tseries = ('-pool %(pool)s '
                       % {'pool': lunsetinfo['StoragePool']})
        else:
            dorado2100g2_luntype = '3'
            Tseries = ('-rg %(raidgroup)s -susize %(susize)s '
                       % {'raidgroup': lunsetinfo['StoragePool'],
                          'susize': lunsetinfo['StripUnitSize']})

        prefetch_value_or_times = ''
        pretype = '-pretype %s ' % lunsetinfo['PrefetchType']
        # If constant prefetch, we should set prefetch value.
        if lunsetinfo['PrefetchType'] == '1':
            prefetch_value_or_times = '-value %s' % lunsetinfo['PrefetchValue']
        # If variable prefetch, we should set prefetch mutiple.
        elif lunsetinfo['PrefetchType'] == '2':
            prefetch_value_or_times = '-times %s' % lunsetinfo['PrefetchTimes']

        if self.device_type['type'] == 'Tseries':
            cli_cmd = cli_cmd + Tseries + pretype + prefetch_value_or_times

        elif self.device_type['type'] == 'Dorado5100':
            cli_cmd = cli_cmd + ('-rg %(raidgroup)s -susize %(susize)s'
                                 % {'raidgroup': lunsetinfo['StoragePool'],
                                    'susize': lunsetinfo['StripUnitSize']})

        elif self.device_type['type'] == 'Dorado2100 G2':
            cli_cmd = cli_cmd + ('-type %(type)s'
                                 % {'type': dorado2100g2_luntype})

        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_create_volume:Failed to Create volume. '
                         'volume name:%(name)s. '
                         'out:%(out)s')
                       % {'name': name,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _delete_volume(self, name, lunid):
        """Delete a volume."""
        cli_cmd = ('dellun -force -lun %s' % (lunid))
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_delete_volume:Failed to delete volume. '
                         'Volume name:%(name)s '
                         'out:%(out)s')
                       % {'name': name,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _create_luncopy(self, luncopyname, srclunid, tgtlunid):
        """Create a LUNcopy."""
        cli_cmd = ('createluncopy -n %(name)s -l 4 -slun %(srclunid)s '
                   '-tlun %(tgtlunid)s'
                   % {'name': luncopyname,
                      'srclunid': srclunid,
                      'tgtlunid': tgtlunid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_create_luncopy:Failed to Create LUNcopy. '
                         'LUNcopy name:%(name)s '
                         'out:%(out)s')
                       % {'name': luncopyname,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _start_luncopy(self, luncopyid):
        """Starte a LUNcopy."""
        cli_cmd = ('chgluncopystatus -luncopy %(luncopyid)s -start'
                   % {'luncopyid': luncopyid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_start_luncopy:Failed to start LUNcopy. '
                         'LUNcopy id:%(luncopyid)s '
                         'out:%(out)s')
                       % {'luncopyid': luncopyid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _find_luncopy(self, luncopyname):
        """Get the given LUNcopy's ID."""
        cli_cmd = ('showluncopy')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[0] == luncopyname:
                luncopyid = r[1]
                return luncopyid
        return None

    def _wait_for_luncopy(self, luncopyname):
        """Wait for LUNcopy to complete."""
        while True:
            luncopy_info = self._get_luncopy_info(luncopyname)
            if luncopy_info['state'] == 'Complete':
                break
            elif luncopy_info['status'] != 'Normal':
                err_msg = (_('_wait_for_luncopy:LUNcopy status isnot normal. '
                             'LUNcopy name:%(luncopyname)s')
                           % {'luncopyname': luncopyname})
                LOG.error(err_msg)
                raise exception.VolumeBackendAPIException(data=err_msg)

            time.sleep(10)

    def _get_luncopy_info(self, luncopyname):
        """Get LUNcopy information."""
        cli_cmd = ('showluncopy')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        luncopyinfo = {}
        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[0] == luncopyname:
                luncopyinfo['name'] = r[0]
                luncopyinfo['id'] = r[1]
                luncopyinfo['state'] = r[3]
                luncopyinfo['status'] = r[4]
                return luncopyinfo
        return None

    def _delete_luncopy(self, luncopyid):
        """Delete a LUNcopy."""
        cli_cmd = ('delluncopy -luncopy %(id)s'
                   % {'id': luncopyid})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_delete_luncopy:Failed to delete LUNcopy. '
                         'LUNcopy id:%(luncopyid)s '
                         'out:%(out)s')
                       % {'luncopyid': luncopyid,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _create_snapshot(self, snapshotname, srclunid):
        """Create a snapshot with snapshot name and source LUN ID."""
        cli_cmd = ('createsnapshot -lun %(lunid)s -n %(snapname)s'
                   % {'lunid': srclunid,
                      'snapname': snapshotname})
        out = self._execute_cli(cli_cmd)
        if not re.search('command operates successfully', out):
            err_msg = (_('_create_snapshot:Failed to Create snapshot. '
                         'Snapshot name:%(name)s '
                         'out:%(out)s')
                       % {'name': snapshotname,
                          'out': out})
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)

    def _find_snapshot(self, snapshotname):
        """Get the given snapshot ID."""
        cli_cmd = ('showsnapshot')
        out = self._execute_cli(cli_cmd)
        en = out.split('\r\n')
        if len(en) <= 6:
            return None

        for i in range(6, len(en) - 2):
            r = en[i].split()
            if r[0] == snapshotname:
                return r[1]
        return None

    def _is_resource_pool_enough(self):
        """Check whether resource pools' valid size is more than 1G."""
        cli_cmd = ('showrespool')
        out = self._execute_cli(cli_cmd)
        en = re.split('\r\n', out)
        if len(en) <= 6:
            LOG.error(_('_is_resource_pool_enough:Resource pool for snapshot'
                        'not be added.'))
            return False
        resource_pools = []
        list_key = ['pool id', 'size', 'usage', 'valid size',
                    'alarm threshold']
        for i in range(6, len(en) - 2):
            list_val = en[i].split()
            dic = dict(map(None, list_key, list_val))
            resource_pools.append(dic)

        for pool in resource_pools:
            if float(pool['valid size']) < 1024.0:
                return False
        return True

    def _update_volume_status(self):
        """Retrieve status info from volume group."""

        LOG.debug(_("Updating volume status"))
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or 'HuaweiISCSIDriver'
        data['vendor_name'] = 'Huawei'
        data['driver_version'] = '1.0'
        data['storage_protocol'] = 'iSCSI'

        data['total_capacity_gb'] = 'infinite'
        data['free_capacity_gb'] = self._get_free_capacity()
        data['reserved_percentage'] = 0

        self._stats = data

    def _get_free_capacity(self):
        """Get total free capacity of pools."""
        self.login_info = self._get_login_info()
        self.device_type = self._get_device_type()

        root = self._read_xml()
        lun_type = root.findtext('LUN/LUNType')
        if (self.device_type['type'] == 'Dorado5100' or not lun_type):
            lun_type = 'Thick'
        elif self.device_type['type'] == 'Dorado2100 G2':
            lun_type = 'Thin'
        poolinfo_dev = self._find_pool_info(lun_type)
        pools_conf = root.findall('LUN/StoragePool')
        total_free_capacity = 0
        for poolinfo in poolinfo_dev:
            if self.device_type['type'] == 'Dorado2100 G2':
                total_free_capacity += float(poolinfo[2])
                continue
            for pool in pools_conf:
                if ((self.device_type['type'] == 'Dorado5100') and
                        (poolinfo[5] == pool.attrib['Name'])):
                    total_free_capacity += float(poolinfo[3])
                    break
                else:
                    if ((lun_type == 'Thick') and
                            (poolinfo[5] == pool.attrib['Name'])):
                        total_free_capacity += float(poolinfo[3])
                        break
                    elif poolinfo[1] == pool.attrib['Name']:
                        total_free_capacity += float(poolinfo[4])
                        break

        return str(int(total_free_capacity / 1024))
