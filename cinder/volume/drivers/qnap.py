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
"""Volume driver for QNAP Storage.

This driver supports QNAP Storage for iSCSI.
"""
import base64
from collections import OrderedDict
import functools
import re
import threading
import time

import eventlet
from lxml import etree as ET
from oslo_concurrency import lockutils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import requests
import six
from six.moves import urllib

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.san import san

LOG = logging.getLogger(__name__)

qnap_opts = [
    cfg.URIOpt('qnap_management_url',
               help='The URL to management QNAP Storage. '
                    'Driver does not support IPv6 address in URL.'),
    cfg.StrOpt('qnap_poolname',
               help='The pool name in the QNAP Storage'),
    cfg.StrOpt('qnap_storage_protocol',
               default='iscsi',
               help='Communication protocol to access QNAP storage')
]

CONF = cfg.CONF
CONF.register_opts(qnap_opts, group=configuration.SHARED_CONF_GROUP)


@interface.volumedriver
class QnapISCSIDriver(san.SanISCSIDriver):
    """QNAP iSCSI based cinder driver


    .. code-block:: none

      Version History:
        1.0.0:
              Initial driver (Only iSCSI).
        1.2.001:
              Add supports for Thin Provisioning, SSD Cache, Deduplication,
              Compression and CHAP.
        1.2.002:
              Add support for QES fw 2.0.0.
        1.2.003:
              Add support for QES fw 2.1.0.
        1.2.004:
              Add support for QES fw on TDS series NAS model.
        1.2.005:
              Add support for QTS fw 4.4.0.

    NOTE: Set driver_ssl_cert_verify as True under backend section to
          enable SSL verification.
    """

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "QNAP_CI"

    VERSION = '1.2.005'

    TIME_INTERVAL = 3

    def __init__(self, *args, **kwargs):
        """Initialize QnapISCSIDriver."""
        super(QnapISCSIDriver, self).__init__(*args, **kwargs)
        self.api_executor = None
        self.group_stats = {}
        self.configuration.append_config_values(qnap_opts)
        self.cache_time = 0
        self.initiator = ''
        self.iscsi_port = ''
        self.target_index = ''
        self.target_iqn = ''
        self.target_iqns = []
        self.nasInfoCache = {}

    @classmethod
    def get_driver_options(cls):
        additional_opts = cls._get_oslo_driver_opts(
            'target_ip_address', 'san_login', 'san_password', 'use_chap_auth',
            'chap_username', 'chap_password', 'driver_ssl_cert_verify',
            'reserved_percentage')
        return qnap_opts + additional_opts

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
                raise exception.InvalidInput(
                    reason=_('%s is not set.') % attr)

        if not self.configuration.use_chap_auth:
            self.configuration.chap_username = ''
            self.configuration.chap_password = ''
        else:
            if not str.isalnum(self.configuration.chap_username):
                # invalid chap_username
                LOG.error('Username must be single-byte alphabet or number.')
                raise exception.InvalidInput(
                    reason=_('Username must be single-byte '
                             'alphabet or number.'))
            if not 12 <= len(self.configuration.chap_password) <= 16:
                # invalid chap_password
                LOG.error('Password must contain 12-16 characters.')
                raise exception.InvalidInput(
                    reason=_('Password must contain 12-16 characters.'))

    def do_setup(self, context):
        """Setup the QNAP Cinder volume driver."""
        self._check_config()
        self.ctxt = context
        LOG.debug('context: %s', context)

        # Setup API Executor
        try:
            self.api_executor = self.create_api_executor()
        except Exception:
            LOG.error('Failed to create HTTP client. '
                      'Check ip, port, username, password'
                      ' and make sure the array version is compatible')
            msg = _('Failed to create HTTP client.')
            raise exception.VolumeDriverException(message=msg)

    def check_for_setup_error(self):
        """Check the status of setup."""
        pass

    def create_api_executor(self):
        """Create api executor by nas model."""
        self.api_executor = QnapAPIExecutor(
            username=self.configuration.san_login,
            password=self.configuration.san_password,
            management_url=self.configuration.qnap_management_url,
            verify_ssl=self.configuration.driver_ssl_cert_verify)

        nas_model_name, internal_model_name, fw_version = (
            self.api_executor.get_basic_info(
                self.configuration.qnap_management_url))

        if (self.configuration.qnap_management_url not in self.nasInfoCache):
            self.nasInfoCache[self.configuration.qnap_management_url] = (
                nas_model_name, internal_model_name, fw_version)

        pattern = re.compile(r"^([A-Z]+)-?[A-Z]{0,2}(\d+)\d{2}(U|[a-z]*)")
        matches = pattern.match(nas_model_name)

        if not matches:
            return None
        model_type = matches.group(1)

        ts_model_types = [
            "TS", "SS", "IS", "TVS", "TBS"
        ]
        tes_model_types = [
            "TES", "TDS"
        ]
        es_model_types = [
            "ES"
        ]
        LOG.debug('fw_version: %s', fw_version)
        if model_type in ts_model_types:
            if (fw_version >= "4.2") and (fw_version <= "4.4.9999"):
                LOG.debug('Create TS API Executor')
                # modify the pool name to pool index
                self.configuration.qnap_poolname = (
                    self._get_ts_model_pool_id(
                        self.configuration.qnap_poolname))

                return (QnapAPIExecutorTS(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url,
                    verify_ssl=self.configuration.driver_ssl_cert_verify))
        elif model_type in tes_model_types:
            if 'TS' in internal_model_name:
                if (fw_version >= "4.2") and (fw_version <= "4.4.9999"):
                    LOG.debug('Create TS API Executor')
                    # modify the pool name to poole index
                    self.configuration.qnap_poolname = (
                        self._get_ts_model_pool_id(
                            self.configuration.qnap_poolname))
                    return (QnapAPIExecutorTS(
                        username=self.configuration.san_login,
                        password=self.configuration.san_password,
                        management_url=self.configuration.qnap_management_url,
                        verify_ssl=self.configuration.driver_ssl_cert_verify))
            elif "1.1.2" <= fw_version <= "2.1.9999":
                LOG.debug('Create TES API Executor')
                return (QnapAPIExecutorTES(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url,
                    verify_ssl=self.configuration.driver_ssl_cert_verify))
        elif model_type in es_model_types:
            if "1.1.2" <= fw_version <= "2.1.9999":
                LOG.debug('Create ES API Executor')
                return (QnapAPIExecutor(
                    username=self.configuration.san_login,
                    password=self.configuration.san_password,
                    management_url=self.configuration.qnap_management_url,
                    verify_ssl=self.configuration.driver_ssl_cert_verify))

        msg = _('Model not support')
        raise exception.VolumeDriverException(message=msg)

    def _get_ts_model_pool_id(self, pool_name):
        """Modify the pool name to poole index."""
        pattern = re.compile(r"^(\d+)+|^Storage Pool (\d+)+")
        matches = pattern.match(pool_name)
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
            # If lun name with the name exists, need to change to
            # a different name
            created_lun = self.api_executor.get_lun_info(
                LUNName=create_lun_name)
            if created_lun is None:
                break
        return create_lun_name

    def _parse_boolean_extra_spec(self, extra_spec_value):
        """Parse boolean value from extra spec.

        Parse extra spec values of the form '<is> True' , '<is> False',
        'True' and 'False'.
        """

        if not isinstance(extra_spec_value, six.string_types):
            extra_spec_value = six.text_type(extra_spec_value)

        match = re.match(r'^<is>\s*(?P<value>True|False)$',
                         extra_spec_value.strip(),
                         re.IGNORECASE)
        if match:
            extra_spec_value = match.group('value')
        return strutils.bool_from_string(extra_spec_value, strict=True)

    def create_volume(self, volume):
        """Create a new volume."""
        start_time = time.time()
        LOG.debug('in create_volume')
        LOG.debug('volume: %s', volume.__dict__)
        try:
            extra_specs = volume["volume_type"]["extra_specs"]
            LOG.debug('extra_spec: %s', extra_specs)
            qnap_thin_provision = self._parse_boolean_extra_spec(
                extra_specs.get('qnap_thin_provision', 'true'))
            qnap_compression = self._parse_boolean_extra_spec(
                extra_specs.get('qnap_compression', 'true'))
            qnap_deduplication = self._parse_boolean_extra_spec(
                extra_specs.get('qnap_deduplication', 'false'))
            qnap_ssd_cache = self._parse_boolean_extra_spec(
                extra_specs.get('qnap_ssd_cache', 'false'))
        except TypeError:
            LOG.debug('Unable to retrieve extra specs info. '
                      'Use default extra spec.')
            qnap_thin_provision = True
            qnap_compression = True
            qnap_deduplication = False
            qnap_ssd_cache = False

        LOG.debug('qnap_thin_provision: %(qnap_thin_provision)s '
                  'qnap_compression: %(qnap_compression)s '
                  'qnap_deduplication: %(qnap_deduplication)s '
                  'qnap_ssd_cache: %(qnap_ssd_cache)s',
                  {'qnap_thin_provision': qnap_thin_provision,
                   'qnap_compression': qnap_compression,
                   'qnap_deduplication': qnap_deduplication,
                   'qnap_ssd_cache': qnap_ssd_cache})

        if (qnap_deduplication and not qnap_thin_provision):
            LOG.debug('Dedupe cannot be enabled without thin_provisioning.')
            raise exception.VolumeBackendAPIException(
                data=_('Dedupe cannot be enabled without thin_provisioning.'))

        # User could create two volume with the same name on horizon.
        # Therefore, We should not use display name to create lun on nas.
        create_lun_name = self._gen_lun_name()

        create_lun_index = self.api_executor.create_lun(
            volume,
            self.configuration.qnap_poolname,
            create_lun_name,
            qnap_thin_provision,
            qnap_ssd_cache,
            qnap_compression,
            qnap_deduplication)

        max_wait_sec = 600
        try_times = 0
        lun_naa = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNIndex=create_lun_index)
            if (created_lun is not None and
                    created_lun.find('LUNNAA').text is not None):
                lun_naa = created_lun.find('LUNNAA').text

            try_times += 3
            if try_times > max_wait_sec or lun_naa:
                break
            eventlet.sleep(self.TIME_INTERVAL)

        LOG.debug('LUNNAA: %s', lun_naa)
        _metadata = self._get_volume_metadata(volume)

        _metadata['LUNIndex'] = create_lun_index
        _metadata['LUNNAA'] = lun_naa
        _metadata['LunName'] = create_lun_name

        elapsed_time = time.time() - start_time
        LOG.debug('create_volume elapsed_time: %s', elapsed_time)

        LOG.debug('create_volume volid: %(volid)s, metadata: %(meta)s',
                  {'volid': volume['id'], 'meta': _metadata})

        return {'metadata': _metadata}

    @lockutils.synchronized('delete_volume', 'cinder-', True)
    def delete_volume(self, volume):
        """Delete the specified volume."""
        start_time = time.time()
        LOG.debug('volume: %s', volume.__dict__)
        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        if lun_naa == '':
            LOG.debug('Volume %s does not exist.', volume.id)
            return

        lun_index = ''
        for metadata in volume['volume_metadata']:
            if metadata['key'] == 'LUNIndex':
                lun_index = metadata['value']
                break
        LOG.debug('LUNIndex: %s', lun_index)

        internal_model_name = (self.nasInfoCache
                               [self.configuration.qnap_management_url][1])
        LOG.debug('internal_model_name: %s', internal_model_name)
        fw_version = self.nasInfoCache[self.configuration
                                           .qnap_management_url][2]
        LOG.debug('fw_version: %s', fw_version)

        if 'TS' in internal_model_name.upper():
            LOG.debug('in TS FW: get_one_lun_info')
            ret = self.api_executor.get_one_lun_info(lun_index)
            del_lun = ET.fromstring(ret['data']).find('LUNInfo').find('row')
        elif 'ES' in internal_model_name.upper():
            if fw_version >= "1.1.2" and fw_version <= "1.1.3":
                LOG.debug('in ES FW before 1.1.2/1.1.3: get_lun_info')
                del_lun = self.api_executor.get_lun_info(
                    LUNIndex=lun_index)
            elif "1.1.4" <= fw_version <= "2.1.9999":
                LOG.debug('in ES FW after 1.1.4: get_one_lun_info')
                ret = self.api_executor.get_one_lun_info(lun_index)
                del_lun = (ET.fromstring(ret['data']).find('LUNInfo')
                           .find('row'))

        if del_lun is None:
            LOG.debug('Volume %s does not exist.', lun_naa)
            return

        # if lun is mapping at target, the delete action will fail
        if del_lun.find('LUNStatus').text == '2':
            target_index = (del_lun.find('LUNTargetList')
                            .find('row').find('targetIndex').text)
            LOG.debug('target_index: %s', target_index)
            self.api_executor.disable_lun(lun_index, target_index)
            self.api_executor.unmap_lun(lun_index, target_index)

        retry_delete = False
        while True:
            retry_delete = self.api_executor.delete_lun(lun_index)
            if not retry_delete:
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
            create_snapshot_name = 'Q%d' % int(time.time())
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
        lun_index = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNName=cloned_lun_name)
            if (created_lun is not None and
                    created_lun.find('LUNNAA') is not None):
                lun_naa = created_lun.find('LUNNAA').text
                lun_index = created_lun.find('LUNIndex').text
                LOG.debug('LUNIndex: %s', lun_index)

            try_times += 3
            if try_times > max_wait_sec or lun_naa:
                break
            eventlet.sleep(self.TIME_INTERVAL)

        LOG.debug('LUNNAA: %s', lun_naa)
        if (volume['size'] > src_vref['size']):
            self._extend_lun(volume, lun_naa)
        internal_model_name = (self.nasInfoCache
                               [self.configuration.qnap_management_url][1])

        if 'TS' in internal_model_name.upper():
            LOG.debug('in TS FW: delete_snapshot_api')
            self.api_executor.delete_snapshot_api(snapshot_id)
        elif 'ES' in internal_model_name.upper():
            LOG.debug('in ES FW: do nothing')
        _metadata = self._get_volume_metadata(volume)
        _metadata['LUNIndex'] = lun_index
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
            if (created_snapshot is not None and
                    created_snapshot.find('snapshot_id').text is not None):
                snapshot_id = created_snapshot.find('snapshot_id').text

            try_times += 3
            if try_times > max_wait_sec or snapshot_id:
                break
            eventlet.sleep(self.TIME_INTERVAL)

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

        self.api_executor.delete_snapshot_api(snapshot_id)

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
        lun_index = ""
        while True:
            created_lun = self.api_executor.get_lun_info(
                LUNName=create_lun_name)
            if (created_lun is not None and
                    created_lun.find('LUNNAA') is not None):
                lun_naa = created_lun.find('LUNNAA').text
                lun_index = created_lun.find('LUNIndex').text
                LOG.debug('LUNNAA: %s', lun_naa)
                LOG.debug('LUNIndex: %s', lun_index)

            try_times += 3
            if try_times > max_wait_sec or lun_naa:
                break
            eventlet.sleep(self.TIME_INTERVAL)

        if (volume['size'] > snapshot['volume_size']):
            self._extend_lun(volume, lun_naa)

        _metadata = self._get_volume_metadata(volume)
        _metadata['LUNIndex'] = lun_index
        _metadata['LUNNAA'] = lun_naa
        _metadata['LunName'] = create_lun_name
        return {'metadata': _metadata}

    def get_volume_stats(self, refresh=False):
        """Get volume stats. This is more of getting group stats."""
        LOG.debug('in get_volume_stats refresh: %s', refresh)

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
                QoS_support=False,
                qnap_thin_provision=["True", "False"],
                qnap_compression=["True", "False"],
                qnap_deduplication=["True", "False"],
                qnap_ssd_cache=["True", "False"])
            self.group_stats['pools'] = [single_pool]

        return self.group_stats

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        LOG.debug('Entering extend_volume volume=%(vol)s '
                  'new_size=%(size)s',
                  {'vol': volume['display_name'], 'size': new_size})

        volume['size'] = new_size
        self._extend_lun(volume, '')

    def _get_portal_info(self, volume, connector, lun_slot_id, lun_owner):
        """Get portal info."""
        # Cache portal info for twenty seconds
        # If connectors were the same then use the portal info which was cached
        LOG.debug('get into _get_portal_info')
        self.initiator = connector['initiator']
        ret = self.api_executor.get_iscsi_portal_info()
        root = ET.fromstring(ret['data'])
        iscsi_port = root.find('iSCSIPortal').find('servicePort').text
        LOG.debug('iscsiPort: %s', iscsi_port)
        target_iqn_prefix = root.find(
            'iSCSIPortal').find('targetIQNPrefix').text
        LOG.debug('targetIQNPrefix: %s', target_iqn_prefix)

        internal_model_name = (self.nasInfoCache
                               [self.configuration.qnap_management_url][1])
        LOG.debug('internal_model_name: %s', internal_model_name)
        fw_version = (self.nasInfoCache
                      [self.configuration.qnap_management_url][2])
        LOG.debug('fw_version: %s', fw_version)

        target_index = ''
        target_iqn = ''

        # create a new target if no target has ACL connector['initiator']
        LOG.debug('exist target_index: %s', target_index)
        if not target_index:
            target_name = self._gen_random_name()
            LOG.debug('target_name: %s', target_name)
            target_index = self.api_executor.create_target(
                target_name, lun_owner)
            LOG.debug('targetIndex: %s', target_index)

            retryCount = 0
            retrySleepTime = 2
            while retryCount <= 5:
                target_info = self.api_executor.get_target_info(target_index)
                if target_info.find('targetIQN').text is not None:
                    break
                eventlet.sleep(retrySleepTime)
                retrySleepTime = retrySleepTime + 2
                retryCount = retryCount + 1

            target_iqn = target_info.find('targetIQN').text
            LOG.debug('target_iqn: %s', target_iqn)

            # TS NAS have to remove default ACL
            default_acl = (
                target_iqn_prefix[:target_iqn_prefix.find(":") + 1])
            default_acl = default_acl + "all:iscsi.default.ffffff"
            LOG.debug('default_acl: %s', default_acl)
            self.api_executor.remove_target_init(target_iqn, default_acl)
            # add ACL
            self.api_executor.add_target_init(
                target_iqn, connector['initiator'],
                self.configuration.use_chap_auth,
                self.configuration.chap_username,
                self.configuration.chap_password)

        # Get information for multipath
        target_iqns = []
        slotid_list = []
        eth_list, slotid_list = Util.retriveFormCache(
            self.configuration.qnap_management_url,
            lambda: self.api_executor.get_ethernet_ip(type='data'),
            30)

        LOG.debug('slotid_list: %s', slotid_list)
        target_portals = []
        target_portals.append(
            self.configuration.target_ip_address + ':' + iscsi_port)
        # target_iqns.append(target_iqn)
        for index, eth in enumerate(eth_list):
            # TS NAS do not have slot_id
            if not slotid_list:
                target_iqns.append(target_iqn)
            else:
                # To support ALUA, target portal and target inq should
                # be consistent.
                # EX: 10.77.230.31:3260 at controller B and it should map
                # to the target at controller B
                target_iqns.append(
                    target_iqn[:-2] + '.' + slotid_list[index])

            if eth == self.configuration.target_ip_address:
                continue
            target_portals.append(eth + ':' + iscsi_port)

        self.iscsi_port = iscsi_port
        self.target_index = target_index
        self.target_iqn = target_iqn
        self.target_iqns = target_iqns
        self.target_portals = target_portals

        return (iscsi_port, target_index, target_iqn,
                target_iqns, target_portals)

    @lockutils.synchronized('create_export', 'cinder-', True)
    def create_export(self, context, volume, connector):
        start_time = time.time()
        LOG.debug('in create_export')
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('connector: %s', connector)

        lun_naa = self._get_lun_naa_from_volume_metadata(volume)
        if lun_naa == '':
            msg = (_("Volume %s does not exist.") % volume.id)
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        LOG.debug('volume[name]: %s', volume['name'])
        LOG.debug('volume[display_name]: %s', volume['display_name'])

        lun_index = ''
        for metadata in volume['volume_metadata']:
            if metadata['key'] == 'LUNIndex':
                lun_index = metadata['value']
                break
        LOG.debug('LUNIndex: %s', lun_index)
        internal_model_name = (self.nasInfoCache
                               [self.configuration.qnap_management_url][1])
        LOG.debug('internal_model_name: %s', internal_model_name)
        fw_version = self.nasInfoCache[self.configuration
                                           .qnap_management_url][2]
        LOG.debug('fw_version: %s', fw_version)
        if 'TS' in internal_model_name.upper():
            LOG.debug('in TS FW: get_one_lun_info')
            ret = self.api_executor.get_one_lun_info(lun_index)
            selected_lun = (ET.fromstring(ret['data']).find('LUNInfo')
                            .find('row'))
        elif 'ES' in internal_model_name.upper():
            if fw_version >= "1.1.2" and fw_version <= "1.1.3":
                LOG.debug('in ES FW before 1.1.2/1.1.3: get_lun_info')
                selected_lun = self.api_executor.get_lun_info(
                    LUNNAA=lun_naa)
            elif "1.1.4" <= fw_version <= "2.1.9999":
                LOG.debug('in ES FW after 1.1.4: get_one_lun_info')
                ret = self.api_executor.get_one_lun_info(lun_index)
                selected_lun = (ET.fromstring(ret['data']).find('LUNInfo')
                                .find('row'))

        lun_owner = ''
        lun_slot_id = ''
        if selected_lun.find('lun_owner') is not None:
            lun_owner = selected_lun.find('lun_owner').text
            LOG.debug('lun_owner: %s', lun_owner)
            lun_slot_id = '0' if (lun_owner == 'SCA') else '1'
            LOG.debug('lun_slot_id: %s', lun_slot_id)

        # LOG.debug('self.initiator: %s', self.initiator)
        LOG.debug('connector: %s', connector['initiator'])

        iscsi_port, target_index, target_iqn, target_iqns, target_portals = (
            self._get_portal_info(volume, connector, lun_slot_id, lun_owner))

        self.api_executor.map_lun(lun_index, target_index)

        max_wait_sec = 600
        try_times = 0
        LUNNumber = ""
        target_lun_id = -999
        while True:
            if 'TS' in internal_model_name.upper():
                LOG.debug('in TS FW: get_one_lun_info')
                ret = self.api_executor.get_one_lun_info(lun_index)
                root = ET.fromstring(ret['data'])
                target_lun_id = int(root.find('LUNInfo').find('row')
                                    .find('LUNTargetList').find('row')
                                    .find('LUNNumber').text)

                try_times += 3
                if try_times > max_wait_sec or target_lun_id != -999:
                    break
                eventlet.sleep(self.TIME_INTERVAL)

            elif 'ES' in internal_model_name.upper():
                if fw_version >= "1.1.2" and fw_version <= "1.1.3":
                    LOG.debug('in ES FW before 1.1.2/1.1.3: get_lun_info')
                    root = self.api_executor.get_lun_info(LUNNAA=lun_naa)
                    if len(list(root.find('LUNTargetList'))) != 0:
                        LUNNumber = root.find('LUNTargetList').find(
                            'row').find('LUNNumber').text
                    target_lun_id = int(LUNNumber)

                    try_times += 3
                    if try_times > max_wait_sec or LUNNumber:
                        break
                    eventlet.sleep(self.TIME_INTERVAL)
                elif "1.1.4" <= fw_version <= "2.1.9999":
                    LOG.debug('in ES FW after 1.1.4: get_one_lun_info')
                    ret = self.api_executor.get_one_lun_info(lun_index)
                    root = ET.fromstring(ret['data'])
                    target_lun_id = int(root.find('LUNInfo')
                                        .find('row').find('LUNTargetList')
                                        .find('row').find('LUNNumber').text)

                    try_times += 3
                    if try_times > max_wait_sec or target_lun_id != -999:
                        break
                    eventlet.sleep(self.TIME_INTERVAL)
                else:
                    break
            else:
                break

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = (self.configuration.target_ip_address +
                                       ':' + iscsi_port)
        properties['target_iqn'] = target_iqn
        LOG.debug('properties[target_iqn]: %s', properties['target_iqn'])

        LOG.debug('target_lun_id: %s', target_lun_id)
        properties['target_lun'] = target_lun_id
        properties['volume_id'] = volume['id']  # used by xen currently

        multipath = connector.get('multipath', False)
        if multipath:
            """Below are settings for multipath"""
            properties['target_portals'] = target_portals
            properties['target_iqns'] = target_iqns
            properties['target_luns'] = (
                [target_lun_id] * len(target_portals))
            LOG.debug('properties: %s', properties)

        provider_location = '%(host)s:%(port)s,1 %(name)s %(tgt_lun)s' % {
            'host': self.configuration.target_ip_address,
            'port': iscsi_port,
            'name': target_iqn,
            'tgt_lun': target_lun_id,
        }

        if self.configuration.use_chap_auth:
            provider_auth = 'CHAP %s %s' % (self.configuration.chap_username,
                                            self.configuration.chap_password)
        else:
            provider_auth = None

        elapsed_time = time.time() - start_time
        LOG.debug('create_export elapsed_time: %s', elapsed_time)

        LOG.debug('create_export volid: %(volid)s, provider_location: %(loc)s',
                  {'volid': volume['id'], 'loc': provider_location})

        return (
            {'provider_location': provider_location,
             'provider_auth': provider_auth})

    def initialize_connection(self, volume, connector):
        start_time = time.time()
        LOG.debug('in initialize_connection')

        if not volume['provider_location']:
            err = _("Param volume['provider_location'] is invalid.")
            raise exception.InvalidParameterValue(err=err)

        result = volume['provider_location'].split(' ')
        if len(result) < 2:
            raise exception.InvalidInput(reason=volume['provider_location'])

        data = result[0].split(',')
        if len(data) < 2:
            raise exception.InvalidInput(reason=volume['provider_location'])

        iqn = result[1]
        LOG.debug('iqn: %s', iqn)
        target_lun_id = int(result[2], 10)
        LOG.debug('target_lun_id: %d', target_lun_id)

        properties = {}
        properties['target_discovered'] = False
        properties['target_portal'] = (self.configuration.target_ip_address +
                                       ':' + self.iscsi_port)
        properties['target_iqn'] = iqn
        properties['target_lun'] = target_lun_id
        properties['volume_id'] = volume['id']  # used by xen currently

        if self.configuration.use_chap_auth:
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = self.configuration.chap_username
            properties['auth_password'] = self.configuration.chap_password

        elapsed_time = time.time() - start_time
        LOG.debug('initialize_connection elapsed_time: %s', elapsed_time)

        LOG.debug('initialize_connection volid:'
                  ' %(volid)s, properties: %(prop)s',
                  {'volid': volume['id'], 'prop': properties})

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
        lun_index = ''
        for metadata in volume['volume_metadata']:
            if metadata['key'] == 'LUNIndex':
                lun_index = metadata['value']
                break
        LOG.debug('LUNIndex: %s', lun_index)

        internal_model_name = (self.nasInfoCache
                               [self.configuration.qnap_management_url][1])
        LOG.debug('internal_model_name: %s', internal_model_name)
        fw_version = self.nasInfoCache[self.configuration
                                           .qnap_management_url][2]
        LOG.debug('fw_version: %s', fw_version)

        if 'TS' in internal_model_name.upper():
            LOG.debug('in TS FW: get_one_lun_info')
            ret = self.api_executor.get_one_lun_info(lun_index)
            selected_lun = (ET.fromstring(ret['data']).find('LUNInfo')
                            .find('row'))
        elif 'ES' in internal_model_name.upper():
            if fw_version >= "1.1.2" and fw_version <= "1.1.3":
                LOG.debug('in ES FW before 1.1.2/1.1.3: get_lun_info')
                selected_lun = self.api_executor.get_lun_info(
                    LUNIndex=lun_index)
            elif "1.1.4" <= fw_version <= "2.1.9999":
                LOG.debug('in ES FW after 1.1.4: get_one_lun_info')
                ret = self.api_executor.get_one_lun_info(lun_index)
                selected_lun = (ET.fromstring(ret['data']).find('LUNInfo')
                                .find('row'))

        lun_status = self.enum('creating', 'unmapped', 'mapped')

        LOG.debug('LUNStatus: %s', selected_lun.find('LUNStatus').text)
        LOG.debug('lun_status.mapped: %s', six.text_type(lun_status.mapped))
        # lun does not map to any target
        if (selected_lun.find('LUNStatus').text) != (
                six.text_type(lun_status.mapped)):
            return

        target_index = (selected_lun.find('LUNTargetList')
                        .find('row').find('targetIndex').text)
        LOG.debug('target_index: %s', target_index)

        start_time1 = time.time()
        self.api_executor.disable_lun(lun_index, target_index)
        elapsed_time1 = time.time() - start_time1
        LOG.debug('terminate_connection disable_lun elapsed_time : %s',
                  elapsed_time1)

        start_time2 = time.time()
        self.api_executor.unmap_lun(lun_index, target_index)
        elapsed_time2 = time.time() - start_time2
        LOG.debug('terminate_connection unmap_lun elapsed_time : %s',
                  elapsed_time2)

        elapsed_time = time.time() - start_time

        LOG.debug('terminate_connection elapsed_time : %s', elapsed_time)
        self.api_executor.delete_target(target_index)

    def update_migrated_volume(
            self, context, volume, new_volume, original_volume_status):
        """Return model update for migrated volume."""
        LOG.debug('volume: %s', volume.__dict__)
        LOG.debug('new_volume: %s', new_volume.__dict__)
        LOG.debug('original_volume_status: %s', original_volume_status)

        _metadata = self._get_volume_metadata(new_volume)

        # metadata will not be swap after migration with liberty version
        # and the metadata of new volume is different with the metadata
        # of original volume. Therefore, we need to update the migrated volume.
        if not hasattr(new_volume, '_orig_metadata'):
            model_update = {'metadata': _metadata}
            return model_update

    @utils.synchronized('_attach_volume')
    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False, ignore_errors=False):
        super(QnapISCSIDriver, self)._detach_volume(
            context, attach_info,
            volume, properties,
            force=force, remote=remote,
            ignore_errors=ignore_errors
        )

    @utils.synchronized('_attach_volume')
    def _attach_volume(self, context, volume, properties, remote=False):
        return super(QnapISCSIDriver, self)._attach_volume(context, volume,
                                                           properties, remote)


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
                    if attempts < 4:
                        LOG.debug('Session might have expired.'
                                  ' Trying to relogin')
                        self._login()
                        continue

                LOG.error('Re-throwing Exception %s', e)
                raise
    return inner_connection_checker


class QnapAPIExecutor(object):
    """Makes QNAP API calls for ES NAS."""
    es_create_lun_lock = threading.Lock()
    es_delete_lun_lock = threading.Lock()
    es_lun_locks = {}

    def __init__(self, *args, **kwargs):
        """Init function."""
        self.sid = None
        self.username = kwargs['username']
        self.password = kwargs['password']
        self.ip, self.port, self.ssl = (
            self._parse_management_url(kwargs['management_url']))
        self.verify_ssl = kwargs['verify_ssl']
        self._login()

    def _parse_management_url(self, management_url):
        # NOTE(Ibad): This parser isn't compatible with IPv6 address.
        # Typical IPv6 address will have : as delimiters and
        # URL is represented as https://[3ffe:2a00:100:7031::1]:8080
        # since the regular expression below uses : to identify ip and port
        # it won't work with IPv6 address.
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
        management_ip, management_port, management_ssl = (
            self._parse_management_url(management_url))

        response = self._get_response(management_ip, management_port,
                                      management_ssl, '/cgi-bin/authLogin.cgi')
        data = response.text

        root = ET.fromstring(data)

        nas_model_name = root.find('model/displayModelName').text
        internal_model_name = root.find('model/internalModelName').text
        fw_version = root.find('firmware/version').text

        return nas_model_name, internal_model_name, fw_version

    def _get_response(self, host_ip, host_port, use_ssl, action, body=None):
        """"Execute http request and return response."""
        method = 'GET'
        headers = None
        protocol = 'https' if use_ssl else 'http'
        verify = self.verify_ssl if use_ssl else False
        # NOTE(ibad): URL formed here isn't IPv6 compatible
        # we should surround host ip with [] when IPv6 is supported
        # so the final URL can be like https://[3ffe:2a00:100:7031::1]:8080
        url = '%s://%s:%s%s' % (protocol, host_ip, host_port, action)

        if body:
            method = 'POST'
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'charset': 'utf-8'
            }

        response = requests.request(method, url, data=body, headers=headers,
                                    verify=verify)

        return response

    def _execute_and_get_response_details(self, nas_ip, url, post_parm=None):
        """Will prepare response after executing an http request."""
        LOG.debug('_execute_and_get_response_details url: %s', url)
        LOG.debug('_execute_and_get_response_details post_parm: %s', post_parm)

        res_details = {}

        # Make the connection
        start_time2 = time.time()
        response = self._get_response(
            nas_ip, self.port, self.ssl, url, post_parm)
        elapsed_time2 = time.time() - start_time2
        LOG.debug('request elapsed_time: %s', elapsed_time2)

        # Read the response
        data = response.text
        LOG.debug('response status: %s', response.status_code)

        # Extract http error msg if any
        error_details = None
        res_details['data'] = data
        res_details['error'] = error_details
        res_details['http_status'] = response.status_code

        return res_details

    def execute_login(self):
        """Login and return sid."""
        params = OrderedDict(
            pwd=base64.b64encode(self.password.encode('utf-8')).decode(),
            serviceKey='1',
            user=self.username,
        )
        encoded_params = urllib.parse.urlencode(params)
        url = ('/cgi-bin/authLogin.cgi?')

        res_details = self._execute_and_get_response_details(
            self.ip, url, encoded_params)
        root = ET.fromstring(res_details['data'])
        LOG.debug('execute_login data: %s', res_details['data'])
        session_id = root.find('authSid').text
        LOG.debug('execute_login session_id: %s', session_id)
        return session_id

    def _login(self):
        """Execute Https Login API."""
        self.sid = self.execute_login()

    def _get_res_details(self, url, **kwargs):
        sanitized_params = OrderedDict()

        # Sort the dict of parameters
        params = utils.create_ordereddict(kwargs)

        for key, value in params.items():
            if value is not None:
                sanitized_params[key] = six.text_type(value)

        encoded_params = urllib.parse.urlencode(sanitized_params)
        url = url + encoded_params

        res_details = self._execute_and_get_response_details(self.ip, url)

        return res_details

    @_connection_checker
    def create_lun(self, volume, pool_name, create_lun_name, reserve,
                   ssd_cache, compress, dedup):
        """Create lun."""
        self.es_create_lun_lock.acquire()

        lun_thin_allocate = ''
        if reserve:
            lun_thin_allocate = '1'
        else:
            lun_thin_allocate = '0'

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_lun_setting.cgi?',
                func='add_lun',
                FileIO='no',
                LUNThinAllocate=lun_thin_allocate,
                LUNName=create_lun_name,
                LUNPath=create_lun_name,
                poolID=pool_name,
                lv_ifssd='yes' if ssd_cache else 'no',
                compression='1' if compress else '0',
                dedup='sha256' if dedup else 'off',
                LUNCapacity=volume['size'],
                lv_threshold='80',
                sid=self.sid)
        finally:
            self.es_create_lun_lock.release()

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

        self.es_delete_lun_lock.acquire()

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_lun_setting.cgi?',
                func='remove_lun',
                run_background='1',
                ha_sync='1',
                LUNIndex=vol_id,
                sid=self.sid)
        finally:
            self.es_delete_lun_lock.release()

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
        """Execute get specific poolinfo API."""
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
        targetIndex = root.find('result').text
        return targetIndex

    @_connection_checker
    def delete_target(self, target_index):
        """Delete target on nas."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='remove_target',
            targetIndex=target_index,
            sid=self.sid)
        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text != '0':
            raise exception.VolumeBackendAPIException(
                data=_('Delete target failed'))

    @_connection_checker
    def add_target_init(self, target_iqn, init_iqn, use_chap_auth,
                        chap_username, chap_password):
        """Add target acl."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='add_init',
            targetIQN=target_iqn,
            initiatorIQN=init_iqn,
            initiatorAlias=init_iqn,
            bCHAPEnable='1' if use_chap_auth else '0',
            CHAPUserName=chap_username,
            CHAPPasswd=chap_password,
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

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='add_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                sid=self.sid)
        finally:
            pass

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

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='edit_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                LUNEnable=0,
                sid=self.sid)
        finally:
            pass

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
        """Unmap lun from sepecific target."""

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='remove_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                sid=self.sid)
        finally:
            pass

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
                        return lun
                elif ('LUNName' in kwargs):
                    if (kwargs['LUNName'] == lun.find('LUNName').text):
                        return lun
                elif ('LUNNAA' in kwargs):
                    if (kwargs['LUNNAA'] == lun.find('LUNNAA').text):
                        return lun

        return None

    @_connection_checker
    def get_one_lun_info(self, lunID):
        """Execute get_one_lun_info API."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            lun_info='1',
            lunID=lunID,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        else:
            return res_details

    @_connection_checker
    def get_snapshot_info(self, **kwargs):
        """Execute get_snapshot_info API."""
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
                return snapshot

        return None

    @_connection_checker
    def create_snapshot_api(self, lun_id, snapshot_name):
        """Execute CGI to create snapshot from source lun."""
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
    def delete_snapshot_api(self, snapshot_id):
        """Execute CGI to delete snapshot by snapshot id."""
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
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='get_all',
            sid=self.sid)

        return res_details

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
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
            return_slot_id = []
            ip_list = root.find('func').find('ownContent')
            ip_list_tree = ip_list.findall('IPInfo')
            for IP in ip_list_tree:
                ipv4 = (IP.find('IP').find('IP1').text + '.' +
                        IP.find('IP').find('IP2').text + '.' +
                        IP.find('IP').find('IP3').text + '.' +
                        IP.find('IP').find('IP4').text)
                if ((kwargs['type'] == 'data') and
                    (IP.find('isManagePort').text != '1') and
                        (IP.find('status').text == '1')):
                    return_slot_id.append(IP.find('interfaceSlotid').text)
                    return_ip.append(ipv4)
                elif ((kwargs['type'] == 'manage') and
                      (IP.find('isManagePort').text == '1') and
                      (IP.find('status').text == '1')):
                    return_ip.append(ipv4)
                elif ((kwargs['type'] == 'all') and
                      (IP.find('status').text == '1')):
                    return_ip.append(ipv4)

        return return_ip, return_slot_id

    @_connection_checker
    def get_target_info(self, target_index):
        """Get target info."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            targetInfo=1,
            targetIndex=target_index,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        LOG.debug('ES get_target_info.authPassed: (%s)',
                  root.find('authPassed').text)
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
                return target

    @_connection_checker
    def get_target_info_by_initiator(self, initiatorIQN):
        """Get target info by initiatorIQN."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            initiatorIQN=initiatorIQN,
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            return "", ""

        target = root.find('targetACL').find('row')
        targetIndex = target.find('targetIndex').text
        targetIQN = target.find('targetIQN').text

        return targetIndex, targetIQN


class QnapAPIExecutorTS(QnapAPIExecutor):
    """Makes QNAP API calls for TS NAS."""
    create_lun_lock = threading.Lock()
    delete_lun_lock = threading.Lock()
    lun_locks = {}

    @_connection_checker
    def create_lun(self, volume, pool_name, create_lun_name, reserve,
                   ssd_cache, compress, dedup):
        """Create lun."""
        self.create_lun_lock.acquire()

        lun_thin_allocate = ''
        if reserve:
            lun_thin_allocate = '1'
        else:
            lun_thin_allocate = '0'

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_lun_setting.cgi?',
                func='add_lun',
                FileIO='no',
                LUNThinAllocate=lun_thin_allocate,
                LUNName=create_lun_name,
                LUNPath=create_lun_name,
                poolID=pool_name,
                lv_ifssd='yes' if ssd_cache else 'no',
                LUNCapacity=volume['size'],
                LUNSectorSize='512',
                lv_threshold='80',
                sid=self.sid)
        finally:
            self.create_lun_lock.release()

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
        self.delete_lun_lock.acquire()

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_lun_setting.cgi?',
                func='remove_lun',
                run_background='1',
                ha_sync='1',
                LUNIndex=vol_id,
                sid=self.sid)
        finally:
            self.delete_lun_lock.release()

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

    @lockutils.synchronized('map_unmap_lun_ts')
    @_connection_checker
    def map_lun(self, lun_index, target_index):
        """Map lun to sepecific target."""

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='add_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                sid=self.sid)
        finally:
            pass

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                "Map lun %(lun_index)s to target %(target_index)s failed") %
                {'lun_index': six.text_type(lun_index),
                 'target_index': six.text_type(target_index)})

        return root.find('result').text

    @_connection_checker
    def disable_lun(self, lun_index, target_index):
        """Disable lun from sepecific target."""

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='edit_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                LUNEnable=0,
                sid=self.sid)
        finally:
            pass

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
        """Unmap lun from sepecific target."""

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_target_setting.cgi?',
                func='remove_lun',
                LUNIndex=lun_index,
                targetIndex=target_index,
                sid=self.sid)
        finally:
            pass
#           self.lun_locks[lun_index].release()

        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(data=_(
                'Unmap lun %(lun_index)s from target %(target_index)s failed')
                % {'lun_index': lun_index, 'target_index': target_index})

    @_connection_checker
    def remove_target_init(self, target_iqn, init_iqn):
        """Remove target acl."""
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
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_portal_setting.cgi?',
            func='extra_get',
            targetInfo=1,
            targetIndex=target_index,
            ha_sync='1',
            sid=self.sid)

        root = ET.fromstring(res_details['data'])
        LOG.debug('TS get_target_info.authPassed: (%s)',
                  root.find('authPassed').text)
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
                return target

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
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
                if (IP.find('status').text == '1'):
                    return_ip.append(ipv4)

        return return_ip, None

    @_connection_checker
    def get_snapshot_info(self, **kwargs):
        """Execute get_snapshot_info API."""
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
                return snapshot

        return None

    @lockutils.synchronized('create_target_ts')
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
        targetIndex = root.find('result').text
        return targetIndex

    @_connection_checker
    def delete_target(self, target_index):
        """Delete target on nas."""
        res_details = self._get_res_details(
            '/cgi-bin/disk/iscsi_target_setting.cgi?',
            func='remove_target',
            targetIndex=target_index,
            sid=self.sid)
        root = ET.fromstring(res_details['data'])
        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text != target_index:
            raise exception.VolumeBackendAPIException(
                data=_('Delete target failed'))


class QnapAPIExecutorTES(QnapAPIExecutor):
    """Makes QNAP API calls for TES NAS."""
    tes_create_lun_lock = threading.Lock()

    @_connection_checker
    def create_lun(self, volume, pool_name, create_lun_name, reserve,
                   ssd_cache, compress, dedup):
        """Create lun."""
        self.tes_create_lun_lock.acquire()

        lun_thin_allocate = ''
        if reserve:
            lun_thin_allocate = '1'
        else:
            lun_thin_allocate = '0'

        try:
            res_details = self._get_res_details(
                '/cgi-bin/disk/iscsi_lun_setting.cgi?',
                func='add_lun',
                FileIO='no',
                LUNThinAllocate=lun_thin_allocate,
                LUNName=create_lun_name,
                LUNPath=create_lun_name,
                poolID=pool_name,
                lv_ifssd='yes' if ssd_cache else 'no',
                compression='1' if compress else '0',
                dedup='sha256' if dedup else 'off',
                sync='disabled',
                LUNCapacity=volume['size'],
                lv_threshold='80',
                sid=self.sid)
        finally:
            self.tes_create_lun_lock.release()

        root = ET.fromstring(res_details['data'])

        if root.find('authPassed').text == '0':
            raise exception.VolumeBackendAPIException(
                data=_('Session id expired'))
        if root.find('result').text < '0':
            raise exception.VolumeBackendAPIException(
                data=_('Create volume %s failed') % volume['display_name'])

        return root.find('result').text

    @_connection_checker
    def get_ethernet_ip(self, **kwargs):
        """Execute get_ethernet_ip API."""
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
                if (IP.find('status').text == '1'):
                    return_ip.append(ipv4)

        return return_ip, None


class Util(object):
    _dictCondRetriveFormCache = {}
    _dictCacheRetriveFormCache = {}
    _condRetriveFormCache = threading.Condition()

    @classmethod
    def retriveFormCache(cls, lockKey, func, keepTime=0):
        cond = None

        cls._condRetriveFormCache.acquire()
        try:
            if (lockKey not in cls._dictCondRetriveFormCache):
                cls._dictCondRetriveFormCache[lockKey] = threading.Condition()
            cond = cls._dictCondRetriveFormCache[lockKey]
        finally:
            cls._condRetriveFormCache.release()

        cond.acquire()
        try:
            if (lockKey not in cls._dictCacheRetriveFormCache):
                # store (startTime, result) in cache.
                result = func()
                cls._dictCacheRetriveFormCache[lockKey] = (time.time(), result)

            startTime, result = cls._dictCacheRetriveFormCache[lockKey]
            # check if the cache is time-out
            if ((time.time() - startTime) > keepTime):
                result = func()
                cls._dictCacheRetriveFormCache[lockKey] = (time.time(), result)

            return result
        finally:
            cond.release()

    @classmethod
    def retry(cls, func, retry=0, retryTime=30):
        if (retry == 0):
            retry = 9999  # max is 9999 times
        if (retryTime == 0):
            retryTime = 9999  # max is 9999 seconds
        startTime = time.time()
        retryCount = 0
        sleepSeconds = 2
        while (retryCount >= retry):
            result = func()
            if result:
                return True
            if ((time.time() - startTime) <= retryTime):
                return False  # more than retry times
            eventlet.sleep(sleepSeconds)
            sleepSeconds = sleepSeconds + 2
            retryCount = retryCount + 1
        return False  # more than retryTime
