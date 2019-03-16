# Copyright 2017 Veritas Technologies LLC.
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
Veritas Access Driver for ISCSI.

"""
import ast
import hashlib
import json
from random import randint

from defusedxml import minidom
from oslo_config import cfg
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import units
import requests
import requests.auth
from six.moves import http_client

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)


VA_VOL_OPTS = [
    cfg.BoolOpt('vrts_lun_sparse',
                default=True,
                help='Create sparse Lun.'),
    cfg.StrOpt('vrts_target_config',
               default='/etc/cinder/vrts_target.xml',
               help='VA config file.')
]


CONF = cfg.CONF
CONF.register_opts(VA_VOL_OPTS)


class NoAuth(requests.auth.AuthBase):
    """This is a 'authentication' handler.

    It exists for use with custom authentication systems, such as the
    one for the Access API, it simply passes the Authorization header as-is.

    The default authentication handler for requests will clobber the
    Authorization header.
    """

    def __call__(self, r):
        return r


@interface.volumedriver
class ACCESSIscsiDriver(driver.ISCSIDriver):
    """ACCESS Share Driver.

    Executes commands relating to ACCESS ISCSI.
    Supports creation of volumes on ACCESS.

    .. code-block:: none

     API version history:

        1.0 - Initial version.
    """

    VERSION = "1.0"
    # ThirdPartySytems wiki page
    CI_WIKI_NAME = "Veritas_Access_CI"
    DRIVER_VOLUME_TYPE = 'iSCSI'
    LUN_FOUND_INTERVAL = 30  # seconds

    def __init__(self, *args, **kwargs):
        # Parent sets db, host, _execute and base config
        super(ACCESSIscsiDriver, self).__init__(*args, **kwargs)

        self._va_ip = None
        self._port = None
        self._user = None
        self._pwd = None
        self.iscsi_port = None
        self._fs_list_str = '/fs'
        self._target_list_str = '/iscsi/target/list'
        self._target_status = '/iscsi/target/status'
        self._lun_create_str = '/iscsi/lun/create'
        self._lun_destroy_str = '/iscsi/lun/destroy'
        self._lun_list_str = '/iscsi/lun/list'
        self._lun_create_from_snap_str = '/iscsi/lun_from_snap/create'
        self._snapshot_create_str = '/iscsi/lun/snapshot/create'
        self._snapshot_destroy_str = '/iscsi/lun/snapshot/destroy'
        self._snapshot_list_str = '/iscsi/lun/snapshot/list'
        self._lun_clone_create_str = '/iscsi/lun/clone/create'
        self._lun_extend_str = '/iscsi/lun/growto'
        self._lun_shrink_str = '/iscsi/lun/shrinkto'
        self._lun_getid_str = '/iscsi/lun/getlunid'
        self._target_map_str = '/iscsi/target/map/add'
        self._target_list_status = '/iscsi/target/full_list'

        self.configuration.append_config_values(VA_VOL_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.backend_name = (self.configuration.safe_get('volume_'
                                                         'backend_name') or
                             'ACCESS_ISCSI')
        self.verify = (self.configuration.
                       safe_get('driver_ssl_cert_verify') or False)

        if self.verify:
            verify_path = (self.configuration.
                           safe_get('driver_ssl_cert_path') or None)
            if verify_path:
                self.verify = verify_path

    @staticmethod
    def get_driver_options():
        return VA_VOL_OPTS

    def do_setup(self, context):
        """Any initialization the volume driver does while starting."""
        super(ACCESSIscsiDriver, self).do_setup(context)

        required_config = ['san_ip',
                           'san_login',
                           'san_password',
                           'san_api_port']

        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                message = (_('config option %s is not set.') % attr)
                raise exception.InvalidInput(message=message)

        self._va_ip = self.configuration.san_ip
        self._user = self.configuration.san_login
        self._pwd = self.configuration.san_password
        self._port = self.configuration.san_api_port
        self._sparse_lun_support = self.configuration.vrts_lun_sparse
        self.target_info_file = self.configuration.vrts_target_config
        self.iscsi_port = self.configuration.target_port
        self.session = self._authenticate_access(self._va_ip, self._user,
                                                 self._pwd)

    def _get_va_lun_name(self, name):
        length = len(name)
        index = int(length / 2)
        name1 = name[:index]
        name2 = name[index:]
        crc1 = hashlib.md5(name1.encode('utf-8')).hexdigest()[:5]
        crc2 = hashlib.md5(name2.encode('utf-8')).hexdigest()[:5]
        return 'cinder' + '-' + crc1 + '-' + crc2

    def check_for_setup_error(self):
        """Check if veritas access target is online."""
        target_list = self._vrts_parse_xml_file(self.target_info_file)
        if not self._vrts_get_online_targets(target_list):
            message = ('ACCESSIscsiDriver setup error as '
                       'no target is online')
            raise exception.VolumeBackendAPIException(message=message)

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        pass

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def _vrts_get_iscsi_properties(self, volume, target_name):
        """Get target and LUN details."""
        lun_name = self._get_va_lun_name(volume.id)

        data = {}
        path = self._lun_getid_str
        provider = '%s:%s' % (self._va_ip, self._port)

        lun_id_list = self._access_api(self.session, provider, path,
                                       json.dumps(data), 'GET')

        if not lun_id_list:
            message = _('ACCESSIscsiDriver get LUN ID list '
                        'operation failed')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        for lun in ast.literal_eval(lun_id_list['output']):
            vrts_lun_name = lun['storage_object'].split('/')[3]
            if vrts_lun_name == lun_name:
                lun_id = int(lun['index'])

        target_list = self._vrts_parse_xml_file(self.target_info_file)
        authentication = False
        portal_ip = ""

        for target in target_list:
            if target_name == target['name']:
                portal_ip = target['portal_ip']
                if target['auth'] == '1':
                    auth_user = target['auth_user']
                    auth_password = target['auth_password']
                    authentication = True
                break

        if portal_ip == "":
            message = (_('ACCESSIscsiDriver initialize_connection '
                         'failed for %s as no portal ip was found')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        portal_list = portal_ip.split(',')

        target_portal_list = []
        for ip in portal_list:
            if netutils.is_valid_ipv6(ip):
                target_portal_list.append('[%s]:%s' % (ip,
                                                       str(self.iscsi_port)))
            else:
                target_portal_list.append('%s:%s' % (ip, str(self.iscsi_port)))

        iscsi_properties = {}
        iscsi_properties['target_discovered'] = True
        iscsi_properties['target_iqn'] = target_name
        iscsi_properties['target_portal'] = target_portal_list[0]
        if len(target_portal_list) > 1:
            iscsi_properties['target_portals'] = target_portal_list
        iscsi_properties['target_lun'] = lun_id
        iscsi_properties['volume_id'] = volume.id
        if authentication:
            iscsi_properties['auth_username'] = auth_user
            iscsi_properties['auth_password'] = auth_password
            iscsi_properties['auth_method'] = 'CHAP'

        return iscsi_properties

    def _get_vrts_lun_list(self):
        """Get Lun list."""
        data = {}
        path = self._lun_list_str
        provider = '%s:%s' % (self._va_ip, self._port)

        lun_list = self._access_api(self.session, provider, path,
                                    json.dumps(data), 'GET')

        if not lun_list:
            message = _('ACCESSIscsiDriver get LUN list '
                        'operation failed')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        return lun_list

    def _vrts_target_initiator_mapping(self, target_name, initiator_name):
        """Map target to initiator."""
        path = self._target_map_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["target_name"] = target_name
        data["initiator_name"] = initiator_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver target-initiator mapping '
                         'failed for target %s')
                       % target_name)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def initialize_connection(self, volume, connector, initiator_data=None):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in _vrts_get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'target_lun': 1,
                    'volume_id': '12345678-1234-4321-1234-123456789012',
                }
            }
        """
        lun_name = self._get_va_lun_name(volume.id)
        target = {'target_name': ''}

        def _inner():
            lun_list = self._get_vrts_lun_list()
            for lun in lun_list['output']['output']['luns']:
                if lun['lun_name'] == lun_name:
                    target['target_name'] = lun['target_name']
                    raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalWithTimeoutLoopingCall(_inner)
        try:
            timer.start(interval=5, timeout=self.LUN_FOUND_INTERVAL).wait()
        except loopingcall.LoopingCallTimeOut:
            message = (_('ACCESSIscsiDriver initialize_connection '
                         'failed for %s as no target was found')
                       % volume.id)

            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        self._vrts_target_initiator_mapping(target['target_name'],
                                            connector['initiator'])

        iscsi_properties = self._vrts_get_iscsi_properties(
            volume, target['target_name'])

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        pass

    def _vrts_parse_xml_file(self, filename):
        """VRTS target info.

        <VRTS>
        <VrtsTargets>
            <Target>
                <Name>iqn.2017-02.com.veritas:target03</Name>
                <PortalIP>10.182.174.188</PortalIP>
            </Target>
            <Target>
                <Name>iqn.2017-02.com.veritas:target04</Name>
                <PortalIP>10.182.174.189</PortalIP>
            </Target>
        </VrtsTargets>
        </VRST>

        :param filename: the configuration file
        :returns: list
        """
        myfile = open(filename, 'r')
        data = myfile.read()
        myfile.close()
        dom = minidom.parseString(data)

        mylist = []
        target = {}

        try:
            for trg in dom.getElementsByTagName('Target'):
                target['name'] = (trg.getElementsByTagName('Name')[0]
                                  .childNodes[0].nodeValue)
                target['portal_ip'] = (trg.getElementsByTagName('PortalIP')[0]
                                       .childNodes[0].nodeValue)
                target['auth'] = (trg.getElementsByTagName('Authentication')[0]
                                  .childNodes[0].nodeValue)
                if target['auth'] == '1':
                    target['auth_user'] = (trg.getElementsByTagName
                                           ('Auth_username')[0]
                                           .childNodes[0].nodeValue)
                    target['auth_password'] = (trg.getElementsByTagName
                                               ('Auth_password')[0]
                                               .childNodes[0].nodeValue)

                mylist.append(target)
                target = {}
        except IndexError:
            pass

        return mylist

    def _vrts_get_fs_list(self):
        """Get FS list."""
        path = self._fs_list_str
        provider = '%s:%s' % (self._va_ip, self._port)
        data = {}
        fs_list = self._access_api(self.session, provider, path,
                                   json.dumps(data), 'GET')

        if not fs_list:
            message = _('ACCESSIscsiDriver get FS list '
                        'operation failed')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        return fs_list

    def _vrts_get_online_targets(self, available_targets):
        """Out of available targets get list of targets which are online."""

        online_targets = []
        path = self._target_list_status
        provider = '%s:%s' % (self._va_ip, self._port)
        data = {}
        target_status_list = self._access_api(self.session, provider, path,
                                              json.dumps(data), 'GET')

        try:
            target_status_output = (ast.
                                    literal_eval(target_status_list['output']))
        except KeyError:
            message = _('ACCESSIscsiDriver get online target list '
                        'operation failed')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        for target in available_targets:
            if target['name'] in target_status_output.keys():
                if target_status_output[target['name']] == 'ONLINE':
                    online_targets.append(target)

        return online_targets

    def _vrts_get_targets_store(self):
        """Get target and its store list."""
        path = self._target_list_str
        provider = '%s:%s' % (self._va_ip, self._port)
        data = {}
        target_list = self._access_api(self.session, provider, path,
                                       json.dumps(data), 'GET')

        if not target_list:
            message = _('ACCESSIscsiDriver get target list '
                        'operation failed')
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        return target_list['output']['output']['targets']

    def _vrts_get_assigned_store(self, target, vrts_target_list):
        """Get the store mapped to given target."""
        for vrts_target in vrts_target_list:
            if vrts_target['wwn'] == target:
                return vrts_target['fs_list'][0]

    def _vrts_is_space_available_in_store(self, vol_size, store_name, fs_list):
        """Check whether space is available on store."""
        if self._sparse_lun_support:
            return True

        for fs in fs_list:
            if fs['name'] == store_name:
                fs_avilable_space = (int(fs['file_storage_capacity']) -
                                     int(fs['file_storage_used']))
                free_space = fs_avilable_space / units.Gi

                if free_space > vol_size:
                    return True
                break
        return False

    def _vrts_get_suitable_target(self, target_list, vol_size):
        """Get a suitable target for lun creation.

        Picking random target at first, if space is not available
        in first selected target then check each target one by one
        for suitable one.
        """

        target_count = len(target_list)

        incrmnt_pointer = 0
        target_index = randint(0, (target_count - 1))

        fs_list = self._vrts_get_fs_list()

        vrts_target_list = self._vrts_get_targets_store()

        store_name = self._vrts_get_assigned_store(
            target_list[target_index]['name'],
            vrts_target_list
        )

        if not self._vrts_is_space_available_in_store(
                vol_size, store_name, fs_list):
            while (incrmnt_pointer != target_count - 1):
                target_index = (target_index + 1) % target_count
                store_name = self._vrts_get_assigned_store(
                    target_list[target_index]['name'],
                    vrts_target_list
                )
                if self._vrts_is_space_available_in_store(
                        vol_size, store_name, fs_list):
                    return target_list[target_index]['name']
                incrmnt_pointer = incrmnt_pointer + 1
        else:
            return target_list[target_index]['name']

        return False

    def create_volume(self, volume):
        """Creates a Veritas Access Iscsi LUN."""
        create_dense = False
        if 'dense' in volume.metadata.keys():
            create_dense = strutils.bool_from_string(
                volume.metadata['dense'])

        lun_name = self._get_va_lun_name(volume.id)
        lun_size = '%sg' % volume.size
        path = self._lun_create_str
        provider = '%s:%s' % (self._va_ip, self._port)

        target_list = self._vrts_parse_xml_file(self.target_info_file)

        target_name = self._vrts_get_suitable_target(target_list, volume.size)

        if not target_name:
            message = (_('ACCESSIscsiDriver create volume failed %s '
                         'as no space is available') % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        data = {}
        data["lun_name"] = lun_name
        data["target_name"] = target_name
        data["size"] = lun_size
        if not self._sparse_lun_support or create_dense:
            data["option"] = "option=dense"

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver create volume failed %s')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def delete_volume(self, volume):
        """Deletes a Veritas Access Iscsi LUN."""
        lun_name = self._get_va_lun_name(volume.id)
        lun_list = self._get_vrts_lun_list()
        target_name = ""

        for lun in lun_list['output']['output']['luns']:
            if lun['lun_name'] == lun_name:
                target_name = lun['target_name']

        path = self._lun_destroy_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["target_name"] = target_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver delete volume failed %s')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def create_snapshot(self, snapshot):
        """Creates a snapshot of LUN."""
        lun_name = self._get_va_lun_name(snapshot.volume_id)
        snap_name = self._get_va_lun_name(snapshot.id)
        path = self._snapshot_create_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["snap_name"] = snap_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver create snapshot failed for %s')
                       % snapshot.volume_id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot of LUN."""
        lun_name = self._get_va_lun_name(snapshot.volume_id)
        snap_name = self._get_va_lun_name(snapshot.id)
        path = self._snapshot_destroy_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["snap_name"] = snap_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver delete snapshot failed for %s')
                       % snapshot.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the volume."""
        lun_name = self._get_va_lun_name(src_vref.id)
        cloned_lun_name = self._get_va_lun_name(volume.id)

        lun_found = False

        lun_list = self._get_vrts_lun_list()
        for lun in lun_list['output']['output']['luns']:
            if lun['lun_name'] == lun_name:
                store_name = lun['fs_name']
                lun_found = True
                break

        if not lun_found:
            message = (_('ACCESSIscsiDriver create cloned volume '
                         'failed %s as no source volume found') % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        fs_list = self._vrts_get_fs_list()

        if not self._vrts_is_space_available_in_store(volume.size, store_name,
                                                      fs_list):
            message = (_('ACCESSIscsiDriver create cloned volume '
                         'failed %s as no space is available') % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        path = self._lun_clone_create_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["clone_name"] = cloned_lun_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver create cloned '
                         'volume failed for %s')
                       % src_vref.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        if volume.size > src_vref.size:
            self._vrts_extend_lun(volume, volume.size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from snapshot."""
        LOG.debug('ACCESSIscsiDriver create_volume_from_snapshot called')

        lun_name = self._get_va_lun_name(volume.id)
        snap_name = self._get_va_lun_name(snapshot.id)

        path = self._snapshot_list_str
        provider = '%s:%s' % (self._va_ip, self._port)
        data = {}
        data["snap_name"] = snap_name
        snap_info = self._access_api(self.session, provider, path,
                                     json.dumps(data), 'GET')

        target_name = ""
        if snap_info:
            for snap in snap_info['output']['output']['snapshots']:
                if snap['snapshot_name'] == snap_name:
                    target_name = snap['target_name']
                    break

        if target_name == "":
            message = (_('ACCESSIscsiDriver create volume from snapshot '
                         'failed for volume %s as failed to gather '
                         'snapshot details')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        vrts_target_list = self._vrts_get_targets_store()
        store_name = self._vrts_get_assigned_store(
            target_name, vrts_target_list)

        fs_list = self._vrts_get_fs_list()

        if not self._vrts_is_space_available_in_store(volume.size, store_name,
                                                      fs_list):
            message = (_('ACCESSIscsiDriver create volume from snapshot '
                         'failed %s as no space is available') % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        path = self._lun_create_from_snap_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["snap_name"] = snap_name

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')

        if not result:
            message = (_('ACCESSIscsiDriver create volume from snapshot '
                         'failed for volume %s')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        if volume.size > snapshot.volume_size:
            self._vrts_extend_lun(volume, volume.size)

    def _vrts_extend_lun(self, volume, size):
        """Extend vrts LUN to given size."""
        lun_name = self._get_va_lun_name(volume.id)
        target = {'target_name': ''}

        def _inner():
            lun_list = self._get_vrts_lun_list()
            for lun in lun_list['output']['output']['luns']:
                if lun['lun_name'] == lun_name:
                    target['target_name'] = lun['target_name']
                    raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalWithTimeoutLoopingCall(_inner)

        try:
            timer.start(interval=5, timeout=self.LUN_FOUND_INTERVAL).wait()
        except loopingcall.LoopingCallTimeOut:
            return False

        lun_size = '%sg' % size
        path = self._lun_extend_str
        provider = '%s:%s' % (self._va_ip, self._port)

        data = {}
        data["lun_name"] = lun_name
        data["target_name"] = target['target_name']
        data["size"] = lun_size

        result = self._access_api(self.session, provider, path,
                                  json.dumps(data), 'POST')
        return result

    def extend_volume(self, volume, size):
        """Extend the volume to new size"""
        lun_name = self._get_va_lun_name(volume.id)
        lun_found = False

        lun_list = self._get_vrts_lun_list()
        for lun in lun_list['output']['output']['luns']:
            if lun['lun_name'] == lun_name:
                store_name = lun['fs_name']
                lun_found = True
                break

        if not lun_found:
            message = (_('ACCESSIscsiDriver extend volume '
                         'failed %s as no volume found at backend')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        fs_list = self._vrts_get_fs_list()

        if not self._vrts_is_space_available_in_store(size, store_name,
                                                      fs_list):
            message = (_('ACCESSIscsiDriver extend volume '
                         'failed %s as no space is available') % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

        result = self._vrts_extend_lun(volume, size)

        if not result:
            message = (_('ACCESSIscsiDriver extend '
                         'volume failed for %s')
                       % volume.id)
            LOG.error(message)
            raise exception.VolumeBackendAPIException(message=message)

    def _get_api(self, provider, tail):
        api_root = 'https://%s/api/access' % (provider)
        if tail == self._fs_list_str:
            api_root = 'https://%s/api' % (provider)

        return api_root + tail

    def _access_api(self, session, provider, path, input_data, method):
        """Returns False if failure occurs."""
        kwargs = {'data': input_data}
        if not isinstance(input_data, dict):
            kwargs['headers'] = {'Content-Type': 'application/json'}
        full_url = self._get_api(provider, path)
        response = session.request(method, full_url, **kwargs)
        if response.status_code == 401:
            LOG.debug('Generating new session.')
            self.session = self._authenticate_access(self._va_ip,
                                                     self._user, self._pwd)
            response = self.session.request(method, full_url, **kwargs)

        if response.status_code != http_client.OK:
            LOG.error('Access API operation failed with HTTP error code %s.',
                      str(response.status_code))
            return False
        result = response.json()
        return result

    def _authenticate_access(self, address, username, password):
        session = requests.session()
        session.verify = self.verify
        session.auth = NoAuth()

        # Here 'address' will be only IPv4.
        response = session.post('https://%s:%s/api/rest/authenticate'
                                % (address, self._port),
                                data={'username': username,
                                      'password': password})
        if response.status_code != http_client.OK:
            LOG.error('Failed to authenticate to remote cluster at %s as %s.',
                      address, username)
            raise exception.NotAuthorized(_('Authentication failure.'))
        result = response.json()
        session.headers.update({'Authorization': 'Bearer {}'
                                .format(result['token'])})
        session.headers.update({'Content-Type': 'application/json'})

        return session

    def _get_va_backend_capacity(self):
        """Get VA backend total and free capacity."""
        target_list = self._vrts_parse_xml_file(self.target_info_file)
        fs_list = self._vrts_get_fs_list()
        vrts_target_list = self._vrts_get_targets_store()

        total_space = 0
        free_space = 0

        target_name = []
        target_store = []

        for target in target_list:
            target_name.append(target['name'])

        for target in vrts_target_list:
            if target['wwn'] in target_name:
                target_store.append(target['fs_list'][0])

        for store in target_store:
            for fs in fs_list:
                if fs['name'] == store:
                    total_space = total_space + fs['file_storage_capacity']
                    fs_free_space = (fs['file_storage_capacity'] -
                                     fs['file_storage_used'])

                    if fs_free_space > free_space:
                        free_space = fs_free_space

        total_capacity = int(total_space) / units.Gi
        free_capacity = int(free_space) / units.Gi

        return (total_capacity, free_capacity)

    def get_volume_stats(self, refresh=False):
        """Retrieve status info from share volume group."""

        total_capacity, free_capacity = self._get_va_backend_capacity()
        backend_name = self.configuration.safe_get('volume_backend_name')
        res_percentage = self.configuration.safe_get('reserved_percentage')
        self._stats["volume_backend_name"] = backend_name or 'VeritasISCSI'
        self._stats["vendor_name"] = 'Veritas'
        self._stats["reserved_percentage"] = res_percentage or 0
        self._stats["driver_version"] = self.VERSION
        self._stats["storage_protocol"] = self.DRIVER_VOLUME_TYPE
        self._stats['total_capacity_gb'] = total_capacity
        self._stats['free_capacity_gb'] = free_capacity
        self._stats['thin_provisioning_support'] = True

        return self._stats
