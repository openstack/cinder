# Copyright (c) 2016 QNAP Systems, Inc.
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
Volume driver for QNAP Storage.
This driver supports QNAP Storage for iSCSI.
"""
import base64
import eventlet
import functools
import re
import ssl
import time
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import timeutils
from oslo_utils import units
import six
from six.moves import http_client
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)

qnap_opts = [
    cfg.URIOpt('qnap_management_url',
               help='The URL to management QNAP Storage'),
    cfg.StrOpt('qnap_poolname',
               help='The pool name in the QNAP Storage'),
    cfg.StrOpt('qnap_storage_protocol',
               default='iscsi',
               help='Communication protocol to access QNAP storage'),
]

CONF = cfg.CONF
CONF.register_opts(qnap_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class QnapISCSIDriver(san.SanISCSIDriver):
    """OpenStack driver to enable QNAP Storage.

    Version history:
        1.0.0 - Initial driver (Only iSCSI)
    """

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "QNAP_CI"

    # TODO(smcginnis) Either remove this if CI requirement are met, or
    # remove this driver in the Queens release per normal deprecation
    SUPPORTED = False

    VERSION = '1.0.0'

    TIME_INTERVAL = 3

    def __init__(self, *args, **kwargs):
        """Initialize QnapISCSIDriver."""
        super(QnapISCSIDriver, self).__init__(*args, **kwargs)
        self.api_executor = None
        self.group_stats = {}
        self.configuration.append_config_values(qnap_opts)

    def _check_config(self):
        """Ensure that the flags we care about are set."""
        LOG.debug('in _check_config')
        required_config = ['qnap_management_url',
                           'san_login',
                           'san_password',
                           'qnap_poolname',
                           'qnap_storage_protocol']

        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                raise exception.InvalidConfigurationValue(
                    reason=_('%s is not set.') % attr)

    def do_setup(self, context):
        """Setup the QNAP Cinder volume driver."""
        self._check_config()
        self.ctxt = context
        LOG.debug('context: %s', context)

        # Setup API Executor
        try:
            self.api_executor = self.creat_api_executor()
        except Exception:
            LOG.error('Failed to create HTTP client. '
                      'Check ip, port, username, password'
                      ' and make sure the array version is compatible')
            msg = _('Failed to create HTTP client.')
            raise exception.VolumeDriverException(message=msg)

    def check_for_setup_error(self):
        """Check the status of setup."""
        pass

    def creat_api_executor(self):
        """Create api executor by nas model."""
        self.api_executor = QnapAPIExecutor(
            username=self.configuration.san_login,
            password=self.configuration.san_password,
            management_url=self.configuration.qnap_management_url)

        nas_model_name, internal_model_name, fw_version = (
            self.api_executor.get_basic_info(
                self.configuration.qnap_management_url))

        pattern = re.compile(r"^([A-Z]+)-?[A-Z]{0,2}(\d+)\d{2}(U|[a-z]*)")
        matches = pattern.match(nas_model_name)

        if not matches:
            return None
        model_type = matches.group(1)

        ts_model_types = [
            "TS", "SS", "IS", "TVS", "TDS", "TBS"
        ]
        tes_model_types = [
            "TES"
        ]
        es_model_types = [
            "ES"
        ]

        if model_type in ts_model_types:
            if (fw_version.startswith("4.2") or fw_version.startswith("4.3")):
                LOG.debug('Create TS API Executor')
                # modify the pool name to pool index
                self.configuration.qnap_poolname = (
                    self._get_ts_model_pool_id(
                        self.configuration.qnap_poolname))

                return (QnapAPIExecutorTS(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url))
        elif model_type in tes_model_types:
            if 'TS' in internal_model_name:
                if (fw_version.startswith("4.2") or
                        fw_version.startswith("4.3")):
                    LOG.debug('Create TS API Executor')
                    # modify the pool name to poole index
                    self.configuration.qnap_poolname = (
                        self._get_ts_model_pool_id(
                            self.configuration.qnap_poolname))
                    return (QnapAPIExecutorTS(
                        username=self.configuration.san_login,
                        password=self.configuration.san_password,
                        management_url=self.configuration.qnap_management_url))

            if (fw_version.startswith("1.1.2") or
                    fw_version.startswith("1.1.3")):
                LOG.debug('Create TES API Executor')
                return (QnapAPIExecutorTES(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url))
        elif model_type in es_model_types:
            if (fw_version.startswith("1.1.2") or
                    fw_version.startswith("1.1.3")):
                LOG.debug('Create ES API Executor')
                return (QnapAPIExecutor(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url))

        msg = _('Model not support')
        raise exception.VolumeDriverException(message=msg)

    def _get_ts_model_pool_id(self, pool_name):
        """Modify the pool name to poole index."""
        pattern = re.compile(r"^(\d+)+|^Storage Pool (\d+)+")
        matches = pattern.match(pool_name)
        LOG.debug('matches.group(1): %s', matches.group(1))
        LOG.debug('matches.group(2): %s', matches.group(2))
        if matches.group(1):
            return matches.group(1)
        else:
            return matches.group(2)

    def _gen_random_name(self):
        return "cinder-{0}".format(timeutils.
                                   utcnow().
                                   strftime('%Y%m%d%H%M%S%f'))

    def _get_volume_metadata(self, volume):
        volume_metadata = {}
        if 'volume_metadata' in volume:
            for metadata in volume['volume_metadata']:
                volume_metadata[metadata['key']] = metadata['value']
        return volume_metadata

    def _gen_lun_name(self):
        create_lun_name = ''
        while True:
            create_lun_name = self._gen_random_name()
            # If lunname with the name exists, need to change to
            # a different name
            created_lun = self.api_executor.get_lun_info(
                LUNName=create_lun_name)
            if created_lun is None:
                break
        return create_lun_name

    def create_volume(self, volume):
        """Create a new volume."""
        start_time = time.time()
        LOG.debug('in create_volume')
        LOG.debug('volume: %s', volume.__dict__)
        reserve = self.configuration.san_thin_provision

        # User could create two volume with the same name on horizon.
        # Therefore, We should not use displayname to create lun on nas.
        create_lun_name = self._gen_lun_name()

        create_lun_index = self.api_executor.create_lun(
            volume,
            self.configuration.qnap_poolname,
            create_lun_name,
            reserve)

        max_wait_sec = 600
        try_times = 0
        lun_naa = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNIndex=create_lun_index)
            if created_lun.find('LUNNAA') is not None:
                lun_naa = created_lun.find('LUNNAA').text

            try_times = try_times + 3
            eventlet.sleep(self.TIME_INTERVAL)
            if(try_times > max_wait_sec or lun_naa is not None):
                break

        LOG.debug('LUNNAA: %s', lun_naa)
        _metadata = self._get_volume_metadata(volume)
        _metadata['LUNNAA'] = lun_naa
        _metadata['LunName'] = create_lun_name

        elapsed_time = time.time() - start_time
        LOG.debug('create_volume elapsed_time: %s', elapsed_time)

        return {'metadata': _metadata}

    def delete_volume(self, volume):
        """Delete the specified volume."""
        start_time = time.time()
        LOG.debug('volume: %s', volume.__dict__)
        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        if lun_naa == '':
            LOG.debug('Volume %s does not exist.', volume.id)
            return

        del_lun = self.api_executor.get_lun_info(LUNNAA=lun_naa)
        if del_lun is None:
            LOG.debug('Volume %s does not exist.', lun_naa)
            return

        lun_index = del_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)

        # if lun is mapping at target, the delete action will fail
        if del_lun.find('LUNStatus').text == '2':
            target_index = (del_lun.find('LUNTargetList')
                            .find('row').find('targetIndex').text)
            LOG.debug('target_index: %s', target_index)
            self.api_executor.disable_lun(lun_index, target_index)
            self.api_executor.unmap_lun(lun_index, target_index)

        is_lun_busy = False
        while True:
            is_lun_busy = self.api_executor.delete_lun(lun_index)
            if not is_lun_busy:
                break

        elapsed_time = time.time() - start_time
        LOG.debug('delete_volume elapsed_time: %s', elapsed_time)

    def _get_lun_naa_from_volume_metadata(self, volume):
        lun_naa = ''
        for metadata in volume['volume_metadata']:
            if metadata['key'] == 'LUNNAA':
                lun_naa = metadata['value']
                break
        return lun_naa

    def _extend_lun(self, volume, lun_naa):
        LOG.debug('volume: %s', volume.__dict__)
        if lun_naa == '':
            lun_naa = self._get_lun_naa_from_volume_metadata(volume)

        LOG.debug('lun_naa: %s', lun_naa)
        selected_lun = self.api_executor.get_lun_info(
            LUNNAA=lun_naa)
        lun_index = selected_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)
        lun_name = selected_lun.find('LUNName').text
        LOG.debug('LUNName: %s', lun_name)
        lun_thin_allocate = selected_lun.find('LUNThinAllocate').text
        LOG.debug('LUNThinAllocate: %s', lun_thin_allocate)
        lun_path = ''
        if selected_lun.find('LUNPath') is not None:
            lun_path = selected_lun.find('LUNPath').text
            LOG.debug('LUNPath: %s', lun_path)
        lun_status = selected_lun.find('LUNStatus').text
        LOG.debug('LUNStatus: %s', lun_status)

        lun = {'LUNName': lun_name,
               'LUNCapacity': volume['size'],
               'LUNIndex': lun_index,
               'LUNThinAllocate': lun_thin_allocate,
               'LUNPath': lun_path,
               'LUNStatus': lun_status}
        self.api_executor.edit_lun(lun)

    def _create_snapshot_name(self, lun_index):
        create_snapshot_name = ''
        while True:
            # If snapshot with the name exists, need to change to
            # a different name
            create_snapshot_name = self._gen_random_name()
            snapshot = self.api_executor.get_snapshot_info(
                lun_index=lun_index, snapshot_name=create_snapshot_name)
            if snapshot is None:
                break
        return create_snapshot_name

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        LOG.debug('Entering create_cloned_volume...')
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('src_vref: %s', src_vref.__dict__)
        LOG.debug('volume_metadata: %s', volume['volume_metadata'])
        src_lun_naa = self._get_lun_naa_from_volume_metadata(src_vref)
        # Below is to clone a volume from a snapshot in the snapshot manager
        src_lun = self.api_executor.get_lun_info(
            LUNNAA=src_lun_naa)
        lun_index = src_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)

        # User could create two snapshot with the same name on horizon.
        # Therefore, we should not use displayname to create snapshot on nas.
        create_snapshot_name = self._create_snapshot_name(lun_index)

        self.api_executor.create_snapshot_api(lun_index, create_snapshot_name)
        created_snapshot = self.api_executor.get_snapshot_info(
            lun_index=lun_index, snapshot_name=create_snapshot_name)
        snapshot_id = created_snapshot.find('snapshot_id').text
        LOG.debug('snapshot_id: %s', snapshot_id)

        # User could create two volume with the same name on horizon.
        # Therefore, We should not use displayname to create lun on nas.
        while True:
            cloned_lun_name = self._gen_random_name()
            # If lunname with the name exists, need to change to
            # a different name
            cloned_lun = self.api_executor.get_lun_info(
                LUNName=cloned_lun_name)

            if cloned_lun is None:
                break

        self.api_executor.clone_snapshot(snapshot_id, cloned_lun_name)

        max_wait_sec = 600
        try_times = 0
        lun_naa = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNName=cloned_lun_name)
            if created_lun.find('LUNNAA') is not None:
                lun_naa = created_lun.find('LUNNAA').text

            try_times = try_times + 3
            eventlet.sleep(self.TIME_INTERVAL)
            if(try_times > max_wait_sec or lun_naa is not None):
                break

        LOG.debug('LUNNAA: %s', lun_naa)
        if (volume['size'] > src_vref['size']):
            self._extend_lun(volume, lun_naa)

        _metadata = self._get_volume_metadata(volume)
        _metadata['LUNNAA'] = lun_naa
        _metadata['LunName'] = cloned_lun_name
        return {'metadata': _metadata}

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        LOG.debug('snapshot: %s', snapshot.__dict__)
        LOG.debug('snapshot id: %s', snapshot['id'])

        # Below is to create snapshot in the snapshot manager
        LOG.debug('volume_metadata: %s', snapshot.volume['metadata'])
        volume_metadata = snapshot.volume['metadata']
        LOG.debug('lun_naa: %s', volume_metadata['LUNNAA'])
        lun_naa = volume_metadata['LUNNAA']
        src_lun = self.api_executor.get_lun_info(LUNNAA=lun_naa)
        lun_index = src_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)

        # User could create two snapshot with the same name on horizon.
        # Therefore, We should not use displayname to create snapshot on nas.
        create_snapshot_name = self._create_snapshot_name(lun_index)
        LOG.debug('create_snapshot_name: %s', create_snapshot_name)

        self.api_executor.create_snapshot_api(lun_index, create_snapshot_name)
        max_wait_sec = 600
        try_times = 0
        snapshot_id = ""
        while True:
            created_snapshot = self.api_executor.get_snapshot_info(
                lun_index=lun_index, snapshot_name=create_snapshot_name)
            if created_snapshot is not None:
                snapshot_id = created_snapshot.find('snapshot_id').text

            try_times = try_times + 3
            eventlet.sleep(self.TIME_INTERVAL)
            if(try_times > max_wait_sec or created_snapshot is not None):
                break

        LOG.debug('created_snapshot: %s', created_snapshot)
        LOG.debug('snapshot_id: %s', snapshot_id)

        _metadata = snapshot['metadata']
        _metadata['snapshot_id'] = snapshot_id
        _metadata['SnapshotName'] = create_snapshot_name
        return {'metadata': _metadata}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        LOG.debug('snapshot: %s', snapshot.__dict__)

        # Below is to delete snapshot in the snapshot manager
        snap_metadata = snapshot['metadata']
        if 'snapshot_id' not in snap_metadata:
            return
        LOG.debug('snapshot_id: %s', snap_metadata['snapshot_id'])
        snapshot_id = snap_metadata['snapshot_id']

        self.api_executor.api_delete_snapshot(snapshot_id)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        LOG.debug('in create_volume_from_snapshot')
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('snapshot: %s', snapshot.__dict__)
        # Below is to clone a volume from a snapshot in the snapshot manager
        snap_metadata = snapshot['metadata']
        if 'snapshot_id' not in snap_metadata:
            LOG.debug('Metadata of the snapshot is invalid')
            msg = _('Metadata of the snapshot is invalid')
            raise exception.VolumeDriverException(message=msg)
        LOG.debug('snapshot_id: %s', snap_metadata['snapshot_id'])
        snapshot_id = snap_metadata['snapshot_id']

        # User could create two volume with the same name on horizon.
        # Therefore, We should not use displayname to create lun on nas.
        create_lun_name = self._gen_lun_name()

        self.api_executor.clone_snapshot(
            snapshot_id, create_lun_name)

        max_wait_sec = 600
        try_times = 0
        lun_naa = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNName=create_lun_name)
            if created_lun.find('LUNNAA') is not None:
                lun_naa = created_lun.find('LUNNAA').text

            try_times = try_times + 3
            eventlet.sleep(self.TIME_INTERVAL)
            if(try_times > max_wait_sec or lun_naa is not None):
                break

        if (volume['size'] > snapshot['volume_size']):
            self._extend_lun(volume, lun_naa)

        _metadata = self._get_volume_metadata(volume)
        _metadata['LUNNAA'] = lun_naa
        _metadata['LunName'] = create_lun_name
        return {'metadata': _metadata}

    def get_volume_stats(self, refresh=False):
        """Get volume stats. This is more of getting group stats."""
        LOG.debug('in get_volume_stats')

        if refresh:
            backend_name = (self.configuration.safe_get(
                            'volume_backend_name') or
                            self.__class__.__name__)
            LOG.debug('backend_name=%(backend_name)s',
                      {'backend_name': backend_name})

            selected_pool = self.api_executor.get_specific_poolinfo(
                self.configuration.qnap_poolname)
            capacity_bytes = int(selected_pool.find('capacity_bytes').text)
            LOG.debug('capacity_bytes: %s GB', capacity_bytes / units.Gi)
            freesize_bytes = int(selected_pool.find('freesize_bytes').text)
            LOG.debug('freesize_bytes: %s GB', freesize_bytes / units.Gi)
            provisioned_bytes = int(selected_pool.find('allocated_bytes').text)
            driver_protocol = self.configuration.qnap_storage_protocol
            LOG.debug(
                'provisioned_bytes: %s GB', provisioned_bytes / units.Gi)
            self.group_stats = {'volume_backend_name': backend_name,
                                'vendor_name': 'QNAP',
                                'driver_version': self.VERSION,
                                'storage_protocol': driver_protocol}
            # single pool now, need support multiple pools in the future
            single_pool = dict(
                pool_name=self.configuration.qnap_poolname,
                total_capacity_gb=capacity_bytes / units.Gi,
                free_capacity_gb=freesize_bytes / units.Gi,
                provisioned_capacity_gb=provisioned_bytes / units.Gi,
                reserved_percentage=self.configuration.reserved_percentage,
                QoS_support=False)
            self.group_stats['pools'] = [single_pool]

            return self.group_stats

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        LOG.debug('Entering extend_volume volume=%(vol)s '
                  'new_size=%(size)s',
                  {'vol': volume['display_name'], 'size': new_size})

        volume['size'] = new_size
        self._extend_lun(volume, '')

    def initialize_connection(self, volume, connector):
        """Create a target with initiator iqn to attach a volume."""
        start_time = time.time()
        LOG.debug('in initialize_connection')
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('connector: %s', connector)

        lun_status = self.enum('createing', 'unmapped', 'mapped')

        ret = self.api_executor.get_iscsi_portal_info()
        root = ET.fromstring(ret['data'])
        iscsi_port = root.find('iSCSIPortal').find('servicePort').text
        LOG.debug('iscsiPort: %s', iscsi_port)
        target_iqn_prefix = root.find(
            'iSCSIPortal').find('targetIQNPrefix').text
        LOG.debug('targetIQNPrefix: %s', target_iqn_prefix)
        target_iqn_postfix = (root.find('iSCSIPortal').
                              find('targetIQNPostfix').text)
        LOG.debug('target_iqn_postfix: %s', target_iqn_postfix)

        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        if lun_naa == '':
            msg = (_("Volume %s does not exist.") % volume.id)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        LOG.debug('volume[name]: %s', volume['name'])
        LOG.debug('volume[display_name]: %s', volume['display_name'])

        selected_lun = self.api_executor.get_lun_info(LUNNAA=lun_naa)
        lun_index = selected_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)

        lun_owner = ''
        lun_slot_id = ''
        if selected_lun.find('lun_owner') is not None:
            lun_owner = selected_lun.find('lun_owner').text
            LOG.debug('lun_owner: %s', lun_owner)
            lun_slot_id = '0' if (lun_owner == 'SCA') else '1'
            LOG.debug('lun_slot_id: %s', lun_slot_id)

        ret = self.api_executor.get_all_iscsi_portal_setting()
        root = ET.fromstring(ret['data'])

        target_index = ''
        target_iqn = ''

        # find the targets have acl with connector['initiator']
        target_with_initiator_list = []
        target_acl_tree = root.find('targetACL')
        target_acl_list = target_acl_tree.findall('row')
        tmp_target_iqn = ''
        for targetACL in target_acl_list:
            tmp_target_iqn = targetACL.find('targetIQN').text
            # If lun and the targetiqn in different controller,
            # skip the targetiqn, in case lun in sca map to target of scb
            LOG.debug('lun_slot_id: %s', lun_slot_id)
            LOG.debug('tmp_target_iqn[-1]: %s', tmp_target_iqn[-1])
            if (lun_slot_id != ''):
                if (lun_slot_id != tmp_target_iqn[-1]):
                    LOG.debug('skip the targetiqn')
                    continue

            target_init_info_list = targetACL.findall('targetInitInfo')
            for targetInitInfo in target_init_info_list:
                if(targetInitInfo.find('initiatorIQN').text ==
                   connector['initiator']):
                    target_with_initiator_list.append(
                        targetACL.find('targetIndex').text)

        # find the target in target_with_initiator_list with ready status
        target_tree = root.find('iSCSITargetList')
        target_list = target_tree.findall('targetInfo')
        for target_with_initiator in target_with_initiator_list:
            for target in target_list:
                if(target_with_initiator == target.find('targetIndex').text):
                    if int(target.find('targetStatus').text) >= 0:
                        target_index = target_with_initiator
                        target_iqn = target.find('targetIQN').text

        # create a new target if no target has ACL connector['initiator']
        LOG.debug('exist target_index: %s', target_index)
        if not target_index:
            target_name = self._gen_random_name()
            LOG.debug('target_name: %s', target_name)
            target_index = self.api_executor.create_target(
                target_name, lun_owner)
            LOG.debug('targetIndex: %s', target_index)
            target_info = self.api_executor.get_target_info(target_index)
            target_iqn = target_info.find('targetIQN').text
            LOG.debug('target_iqn: %s', target_iqn)

            # TS NAS have to remove default ACL
            default_acl = target_iqn_prefix[:target_iqn_prefix.find(":") + 1]
            default_acl = default_acl + "all:iscsi.default.ffffff"
            LOG.debug('default_acl: %s', default_acl)
            self.api_executor.remove_target_init(target_iqn, default_acl)
            # add ACL
            self.api_executor.add_target_init(
                target_iqn, connector['initiator'])

        LOG.debug('LUNStatus: %s', selected_lun.find('LUNStatus').text)
        # lun does not map to any target
        if selected_lun.find('LUNStatus').text == str(lun_status.unmapped):
            self.api_executor.map_lun(lun_index, target_index)

        properties = {}
        properties['target_discovered'] = True
        properties['target_portal'] = (self.configuration.iscsi_ip_address +
                                       ':' + iscsi_port)

        properties['target_iqn'] = target_iqn
        LOG.debug('properties[target_iqn]: %s', properties['target_iqn'])
        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        LOG.debug('LUNNAA: %s', lun_naa)
        # LUNNumber of lun will be updated after map lun to target, so here
        # get lnu info again
        mapped_lun = self.api_executor.get_lun_info(LUNNAA=lun_naa)
        target_lun_id = int(mapped_lun.find('LUNTargetList').find(
            'row').find('LUNNumber').text)
        LOG.debug('target_lun_id: %s', target_lun_id)
        properties['target_lun'] = target_lun_id
        properties['volume_id'] = volume['id']  # used by xen currently

        """Below are settings for multipath"""
        target_iqns = []
        eth_list = self.api_executor.get_ethernet_ip(type='data')
        target_portals = []
        target_portals.append(
            self.configuration.iscsi_ip_address + ':' + iscsi_port)
        target_iqns.append(target_iqn)
        for eth in eth_list:
            if eth == self.configuration.iscsi_ip_address:
                continue
            target_portals.append(eth + ':' + iscsi_port)
            target_iqns.append(target_iqn)

        properties['target_portals'] = target_portals
        properties['target_iqns'] = target_iqns
        properties['target_luns'] = [target_lun_id] * len(target_portals)
        LOG.debug('properties: %s', properties)

        elapsed_time = time.time() - start_time
        LOG.debug('initialize_connection elapsed_time: %s', elapsed_time)

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def enum(self, *sequential, **named):
        """Enum method."""
        enums = dict(zip(sequential, range(len(sequential))), **named)
        return type('Enum', (), enums)

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        start_time = time.time()
        LOG.debug('in terminate_connection')
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('connector: %s', connector)

        # get lun index
        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        LOG.debug('lun_naa: %s', lun_naa)
        selected_lun = self.api_executor.get_lun_info(
            LUNNAA=lun_naa)
        lun_index = selected_lun.find('LUNIndex').text
        LOG.debug('LUNIndex: %s', lun_index)

        lun_status = self.enum('createing', 'unmapped', 'mapped')

        LOG.debug('LUNStatus: %s', selected_lun.find('LUNStatus').text)
        LOG.debug('lun_status.mapped: %s', six.text_type(lun_status.mapped))
        # lun does not map to any target
        if (selected_lun.find('LUNStatus').text) != (
                six.text_type(lun_status.mapped)):
            return

        target_index = (selected_lun.find('LUNTargetList')
                        .find('row').find('targetIndex').text)
        LOG.debug('target_index: %s', target_index)

        self.api_executor.disable_lun(lun_index, target_index)
        self.api_executor.unmap_lun(lun_index, target_index)

        elapsed_time = time.time() - start_time
        LOG.debug('terminate_connection elapsed_time : %s', elapsed_time)

    def update_migrated_volume(
            self, context, volume, new_volume, original_volume_status):
        """Return model update for migrated volume."""
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('new_volume: %s', new_volume.__dict__)
        LOG.debug('original_volume_status: %s', original_volume_status)

        _metadata = self._get_volume_metadata(new_volume)

        # metadata will not be swap after migration wiht liberty version
        # , and the metadata of new volume is diifferent with the metadata
        #  of original volume. Therefore, we need to update the migrated volume
        if not hasattr(new_volume, '_orig_metadata'):
            model_update = {'metadata': _metadata}
            return model_update


def _connection_checker(func):
    """Decorator to check session has expired or not."""
    @functools.wraps(func)
    def inner_connection_checker(self, *args, **kwargs):
        LOG.debug('in _connection_checker')
        for attempts in range(5):
            try:
                return func(self, *args, **kwargs)
            except exception.VolumeBackendAPIException as e:
                pattern = re.compile(
                    r".*Session id expired$")
                matches = pattern.match(six.text_type(e))
                if matches:
                    if attempts < 5:
                        LOG.debug('Session might have expired.'
                                  ' Trying to relogin')
                        self._login()
                        continue

                LOG.error('Re-throwing Exception %s', e)
                raise
    return inner_connection_checker


class QnapAPIExecutor(object):
    """Makes QNAP API calls for ES NAS."""

    def __init__(self, *args, **kwargs):
        """Init function."""
        self.sid = None
        self.username = kwargs['username']
        self.password = kwargs['password']
        self.ip, self.port, self.ssl = (
            self._parse_management_url(kwargs['management_url']))
        self._login()

    def _parse_management_url(self, management_url):
        pattern = re.compile(r"(http|https)\:\/\/(\S+)\:(\d+)")
        matches = pattern.match(management_url)
        if matches.group(1) == 'http':
            management_ssl = False
        else:
            management_ssl = True
        management_ip = matches.group(2)
        management_port = matches.group(3)
        return management_ip, management_port, management_ssl

    def get_basic_info(self, management_url):
        """Get the basic information of NAS."""
        LOG.debug('in get_basic_info')
        management_ip, management_port, management_ssl = (
            self._parse_management_url(management_url))
        connection = None
        if management_ssl:
            if hasattr(ssl, '_create_unverified_context'):
                context = ssl._create_unverified_context()
                connection = http_client.HTTPSConnection(management_ip,
                                                         port=management_port,
                                                         context=context)
            else:
                connection = http_client.HTTPSConnection(management_ip,
                                                         port=management_port)
        else:
            connection = (
                http_client.HTTPConnection(management_ip, management_port))

        connection.request('GET', '/cgi-bin/authLogin.cgi')
        response = connection.getresponse()
        data = response.read()
        LOG.debug('response data: %s', data)

        root = ET.fromstring(data)

        nas_model_name = root.find('model/displayModelName').text
        internal_model_name = root.find('model/internalModelName').text
        fw_version = root.find('firmware/version').text

        return nas_model_name, internal_model_name, fw_version

    def _execute_and_get_response_details(self, nas_ip, url, post_parm=None):
        """Will prepare response after executing an http request."""
        LOG.debug('port: %(port)s, ssl: %(ssl)s',
                  {'port': self.port, 'ssl': self.ssl})

        res_details = {}

        # Prepare the connection
        if self.ssl:
            if hasattr(ssl, '_create_unverified_context'):
                context = ssl._create_unverified_context()
                connection = http_client.HTTPSConnection(nas_ip,
                                                         port=self.port,
                                                         context=context)
            else:
                connection = http_client.HTTPSConnection(
                    nas_ip, port=self.port)
        else:
            connection = http_client.HTTPConnection(nas_ip, self.port)

        # Make the connection
        if post_parm is None:
            connection.request('GET', url)
        else:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "charset": "utf-8"}
            connection.request('POST', url, post_parm, headers)

        # Extract the response as the connection was successful
        start_time = time.time()
        response = connection.getresponse()
        elapsed_time = time.time() - start_time
        LOG.debug('cgi elapsed_time: %s', elapsed_time)
        # Read the response
        data = response.read()
        LOG.debug('response data: %s', data)
        # Extract http error msg if any
        error_details = None
        res_details['data'] = data
        res_details['error'] = error_details
        res_details['http_status'] = response.status

        connection.close()
        return res_details

    def execute_login(self):
        """Login and return sid."""
        params = {}
        params['user'] = self.username
        params['pwd'] = base64.b64encode(self.password.encode("utf-8"))
        params['serviceKey'] = '1'

        sanitized_params = {}

        for key in params:
            value = params[key]
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        url = ('/cgi-bin/authLogin.cgi?')

        res_details = self._execute_and_get_response_details(
            self.ip, url, sanitized_params)
        root = ET.fromstring(res_details['data'])
        session_id = root.find('authSid').text
        return session_id

    def _login(self):
        """Execute Https Login API."""
        self.sid = self.execute_login()
        LOG.debug('sid: %s', self.sid)

    def _get_res_details(self, url, **kwargs):
        sanitized_params = {}

        for key, value in kwargs.items():
            LOG.debug('%(key)s = %(val)s',
                      {'key': key, 'val': value})
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        sanitized_params = urllib.parse.urlencode(sanitized_params)
        LOG.debug('sanitized_params: %s', sanitized_params)
        url = url + sanitized_params
        LOG.debug('url: %s', url)

        res_details = self._execute_and_get_response_details(self.ip, url)

        return res_details

    @_connection_checker
    def create_lun(self, volume, pool_name, create_lun_name, reserve):
        """Create lun."""
        lun_thin_allocate = ''
        if reserve:
            lun_thin_allocate = '1'
        else:
            lun_thin_allocate = '0'

        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_lun_setting.cgi?',
            func='add_lun',
            FileIO='no',
            LUNThinAllocate=lun_thin_allocate,
            LUNName=create_lun_name,
            LUNPath=create_lun_name,
            poolID=pool_name,
            lv_ifssd='no',
            LUNCapacity=volume['size'],
            lv_threshold='80',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])

        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Create volume %s failed') % volume['display_name'])

        return root.find('result').text

    @_connection_checker
    def delete_lun(self, vol_id, *args, **kwargs):
        """Execute delete lun API."""
        LOG.debug('Deleting volume id %s', vol_id)
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_lun_setting.cgi?',
            func='remove_lun',
            run_background='1',
            ha_sync='1',
            LUNIndex=vol_id,
            sid=self.sid)

        data_set_is_busy = "-205041"
        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        # dataset is busy, retry to delete
        if root.find('result').text == data_set_is_busy:
            return True
        if root.find('result').text < '0':
            msg = (_('Volume %s delete failed') % vol_id)
            raise exception.VolumeBackendAPIException(data=msg)

        return False

    @_connection_checker
    def get_specific_poolinfo(self, pool_id):
        """Execute deleteInitiatorGrp API."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/disk_manage.cgi?',
            store='poolInfo',
            func='extra_get',
            poolID=pool_id,
            Pool_Info='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('get_specific_poolinfo failed'))

        pool_list = root.find('Pool_Index')
        pool_info_tree = pool_list.findall('row')
        for pool in pool_info_tree:
            if pool_id == pool.find('poolID').text:
                LOG.debug('poolID: %s', pool.find('poolID').text)
                return pool

    @_connection_checker
    def create_target(self, target_name, controller_name):
        """Create target on nas and return target index."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='add_target',
            targetName=target_name,
            targetAlias=target_name,
            bTargetDataDigest='0',
            bTargetHeaderDigest='0',
            bTargetClusterEnable='1',
            controller_name=controller_name,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Create target failed'))

        root = ET.fromstring(res_details['data'])
        target_index = root.find('result').text
        return target_index

    @_connection_checker
    def add_target_init(self, target_iqn, init_iqn):
        """Add target acl."""
        LOG.debug('targetIqn = %(tgt)s, initIqn = %(init)s',
                  {'tgt': target_iqn, 'init': init_iqn})
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='add_init',
            targetIQN=target_iqn,
            initiatorIQN=init_iqn,
            initiatorAlias=init_iqn,
            bCHAPEnable='0',
            CHAPUserName='',
            CHAPPasswd='',
            bMutualCHAPEnable='0',
            mutualCHAPUserName='',
            mutualCHAPPasswd='',
            ha_sync='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Add target acl failed'))

    def remove_target_init(self, target_iqn, init_iqn):
        """Remote target acl."""
        pass

    @_connection_checker
    def map_lun(self, lun_index, target_index):
        """Map lun to sepecific target."""
        LOG.debug('LUNIndex: %(lun)s, targetIndex: %(tgt)s',
                  {'lun': lun_index, 'tgt': target_index})
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='add_lun',
            LUNIndex=lun_index,
            targetIndex=target_index,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                "Map lun %(lun_index)s to target %(target_index)s failed") %
                {'lun_index': six.text_type(lun_index),
                 'target_index': six.text_type(target_index)})

    @_connection_checker
    def disable_lun(self, lun_index, target_index):
        """Disable lun from sepecific target."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='edit_lun',
            LUNIndex=lun_index,
            targetIndex=target_index,
            LUNEnable=0,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                'Disable lun %(lun_index)s from target %(target_index)s failed'
            ) % {'lun_index': lun_index, 'target_index': target_index})

    @_connection_checker
    def unmap_lun(self, lun_index, target_index):
        """Unmap lun to sepecific target."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='remove_lun',
            LUNIndex=lun_index,
            targetIndex=target_index,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                'Unmap lun %(lun_index)s from target %(target_index)s failed')
                % {'lun_index': lun_index, 'target_index': target_index})

    @_connection_checker
    def get_iscsi_portal_info(self):
        """Get iscsi portal info."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            iSCSI_portal='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        else:
            return res_details

    @_connection_checker
    def get_lun_info(self, **kwargs):
        """Execute get_lun_info API."""
        for key, value in kwargs.items():
            LOG.debug('%(key)s = %(val)s',
                      {'key': key, 'val': value})
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            lunList='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))

        if (('LUNIndex' in kwargs) or ('LUNName' in kwargs) or
           ('LUNNAA' in kwargs)):

            lun_list = root.find('iSCSILUNList')
            lun_info_tree = lun_list.findall('LUNInfo')
            for lun in lun_info_tree:
                if ('LUNIndex' in kwargs):
                    if (kwargs['LUNIndex'] == lun.find('LUNIndex').text):
                        LOG.debug('LUNIndex:%s',
                                  lun.find('LUNIndex').text)
                        return lun
                elif ('LUNName' in kwargs):
                    if (kwargs['LUNName'] == lun.find('LUNName').text):
                        LOG.debug('LUNName:%s', lun.find('LUNName').text)
                        return lun
                elif ('LUNNAA' in kwargs):
                    if (kwargs['LUNNAA'] == lun.find('LUNNAA').text):
                        LOG.debug('LUNNAA:%s', lun.find('LUNNAA').text)
                        return lun

        return None

    @_connection_checker
    def get_snapshot_info(self, **kwargs):
        """Execute get_snapshot_info API."""
        for key, value in kwargs.items():
            LOG.debug('%(key)s = %(val)s',
                      {'key': key, 'val': value})
        res_details = self._get_res_details(
            '/cgi-bin/disk/snapshot.cgi?',
            func='extra_get',
            LUNIndex=kwargs['lun_index'],
            snapshot_list='1',
            snap_start='0',
            snap_count='100',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Unexpected response from QNAP API'))

        snapshot_list = root.find('SnapshotList')
        if snapshot_list is None:
            return None
        snapshot_tree = snapshot_list.findall('row')
        for snapshot in snapshot_tree:
            if (kwargs['snapshot_name'] ==
                    snapshot.find('snapshot_name').text):
                LOG.debug('snapshot_name:%s', kwargs['snapshot_name'])
                return snapshot

        return None

    @_connection_checker
    def create_snapshot_api(self, lun_id, snapshot_name):
        """Execute CGI to create snapshot from source lun NAA."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/snapshot.cgi?',
            func='create_snapshot',
            lunID=lun_id,
            snapshot_name=snapshot_name,
            expire_min='0',
            vital='1',
            snapshot_type='0',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('create snapshot failed'))

    @_connection_checker
    def api_delete_snapshot(self, snapshot_id):
        """Execute CGI to delete snapshot from source lun NAA."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/snapshot.cgi?',
            func='del_snapshots',
            snapshotID=snapshot_id,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        # snapshot not exist
        if root.find('result').text == '-206021':
            return
        # lun not exist
        if root.find('result').text == '-200005':
            return
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('delete snapshot %s failed') % snapshot_id)

    @_connection_checker
    def clone_snapshot(self, snapshot_id, new_lunname):
        """Execute CGI to clone snapshot as unmap lun."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/snapshot.cgi?',
            func='clone_qsnapshot',
            by_lun='1',
            snapshotID=snapshot_id,
            new_name=new_lunname,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                'Clone lun %(lunname)s from snapshot %(snapshot_id)s failed'
            ) % {'lunname': new_lunname, 'snapshot_id': snapshot_id})

    @_connection_checker
    def edit_lun(self, lun):
        """Extend lun."""
        LOG.debug(
            'LUNName:%(name)s, LUNCapacity:%(cap)s, LUNIndex:%(id)s'), (
            {'name': lun['LUNName'],
             'cap': lun['LUNCapacity'],
             'id': lun['LUNIndex']})
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_lun_setting.cgi?',
            func='edit_lun',
            LUNName=lun['LUNName'],
            LUNCapacity=lun['LUNCapacity'],
            LUNIndex=lun['LUNIndex'],
            LUNThinAllocate=lun['LUNThinAllocate'],
            LUNPath=lun['LUNPath'],
            LUNStatus=lun['LUNStatus'],
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Extend lun %s failed') % lun['LUNIndex'])

    @_connection_checker
    def get_all_iscsi_portal_setting(self):
        """Execute get_all_iscsi_portal_setting API."""
        LOG.debug('in get_all_iscsi_portal_setting')
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='get_all',
            sid=self.sid)

        return res_details

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
        LOG.debug('in get_ethernet_ip')
        res_details = self._get_res_details(
            '/cgi-bin/sys/sysRequest.cgi?',
            subfunc='net_setting',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))

        if ('type' in kwargs):
            return_ip = []
            ip_list = root.find('func').find('ownContent')
            ip_list_tree = ip_list.findall('IPInfo')
            for IP in ip_list_tree:
                ipv4 = (IP.find('IP').find('IP1').text + '.' +
                        IP.find('IP').find('IP2').text + '.' +
                        IP.find('IP').find('IP3').text + '.' +
                        IP.find('IP').find('IP4').text)
                LOG.debug('ipv4 = %s', ipv4)
                if ((kwargs['type'] == 'data') and
                   (IP.find('isManagePort').text != '1') and
                   (IP.find('status').text == '1')):
                    return_ip.append(ipv4)
                elif ((kwargs['type'] == 'manage') and
                      (IP.find('isManagePort').text == '1') and
                      (IP.find('status').text == '1')):
                    return_ip.append(ipv4)
                elif ((kwargs['type'] == 'all') and
                      (IP.find('status').text == '1')):
                    return_ip.append(ipv4)
            LOG.debug('return_ip = %s', return_ip)

        return return_ip

    @_connection_checker
    def get_target_info(self, target_index):
        """Get target info."""
        LOG.debug('target_index: %s', target_index)
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            targetInfo=1,
            targetIndex=target_index,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Get target info failed'))

        target_list = root.find('targetInfo')
        target_tree = target_list.findall('row')
        for target in target_tree:
            if target_index == target.find('targetIndex').text:
                LOG.debug('targetIQN: %s',
                          target.find('targetIQN').text)
                return target


class QnapAPIExecutorTS(QnapAPIExecutor):
    """Makes QNAP API calls for TS NAS."""

    @_connection_checker
    def remove_target_init(self, target_iqn, init_iqn):
        """Remove target acl."""
        LOG.debug('targetIqn = %(tgt)s, initIqn = %(init)s',
                  {'tgt': target_iqn, 'init': init_iqn})
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='remove_init',
            targetIQN=target_iqn,
            initiatorIQN=init_iqn,
            ha_sync='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Remove target acl failed'))

    @_connection_checker
    def get_target_info(self, target_index):
        """Get nas target info."""
        LOG.debug('targetIndex: %s', target_index)
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            targetInfo=1,
            targetIndex=target_index,
            ha_sync='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Get target info failed'))

        target_list = root.find('targetInfo')
        target_tree = target_list.findall('row')
        for target in target_tree:
            if target_index == target.find('targetIndex').text:
                LOG.debug('targetIQN: %s',
                          target.find('targetIQN').text)
                return target

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
        LOG.debug('in get_ethernet_ip')
        res_details = self._get_res_details(
            '/cgi-bin/sys/sysRequest.cgi?',
            subfunc='net_setting',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))

        if ('type' in kwargs):
            return_ip = []
            ip_list = root.find('func').find('ownContent')
            ip_list_tree = ip_list.findall('IPInfo')
            for IP in ip_list_tree:
                ipv4 = (IP.find('IP').find('IP1').text + '.' +
                        IP.find('IP').find('IP2').text + '.' +
                        IP.find('IP').find('IP3').text + '.' +
                        IP.find('IP').find('IP4').text)
                LOG.debug('ipv4 = %s', ipv4)
                if (IP.find('status').text == '1'):
                    return_ip.append(ipv4)
            LOG.debug('return_ip = %s', return_ip)

        return return_ip

    @_connection_checker
    def get_snapshot_info(self, **kwargs):
        """Execute get_snapshot_info API."""
        for key, value in kwargs.items():
            LOG.debug('%(key)s = %(val)s',
                      {'key': key, 'val': value})
        LOG.debug('in get_ethernet_ip')
        res_details = self._get_res_details(
            '/cgi-bin/disk/snapshot.cgi?',
            func='extra_get',
            LUNIndex=kwargs['lun_index'],
            smb_snapshot_list='1',
            smb_snapshot='1',
            snapshot_list='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Unexpected response from QNAP API'))

        snapshot_list = root.find('SnapshotList')
        if snapshot_list is None:
            return None
        snapshot_tree = snapshot_list.findall('row')
        for snapshot in snapshot_tree:
            if (kwargs['snapshot_name'] ==
                    snapshot.find('snapshot_name').text):
                LOG.debug('snapshot_name:%s', kwargs['snapshot_name'])
                return snapshot

        return None

    @_connection_checker
    def create_target(self, target_name, controller_name):
        """Create target on nas and return target index."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='add_target',
            targetName=target_name,
            targetAlias=target_name,
            bTargetDataDigest='0',
            bTargetHeaderDigest='0',
            bTargetClusterEnable='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Create target failed'))

        root = ET.fromstring(res_details['data'])
        target_index = root.find('result').text
        return target_index


class QnapAPIExecutorTES(QnapAPIExecutor):
    """Makes QNAP API calls for TES NAS."""

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
        LOG.debug('in get_ethernet_ip')
        res_details = self._get_res_details(
            '/cgi-bin/sys/sysRequest.cgi?',
            subfunc='net_setting',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))

        if ('type' in kwargs):
            return_ip = []
            ip_list = root.find('func').find('ownContent')
            ip_list_tree = ip_list.findall('IPInfo')
            for IP in ip_list_tree:
                ipv4 = (IP.find('IP').find('IP1').text + '.' +
                        IP.find('IP').find('IP2').text + '.' +
                        IP.find('IP').find('IP3').text + '.' +
                        IP.find('IP').find('IP4').text)
                LOG.debug('ipv4 = %s', ipv4)
                if (IP.find('status').text == '1'):
                    return_ip.append(ipv4)
            LOG.debug('return_ip = %s', return_ip)

        return return_ip
