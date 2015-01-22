# Copyright (c) 2014 Huawei Technologies Co., Ltd.
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
 Volume api for Huawei SDSHypervisor systems.
"""

import uuid


from oslo_config import cfg
from oslo_utils import units
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.huaweistorhyper import utils as storhyper_utils
from cinder.volume.drivers.huaweistorhyper import vbs_client
from cinder.volume import volume_types

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

QOS_KEY = ["Qos-high", "Qos-normal", "Qos-low"]

LINKED_CLONE_TYPE = 'linked'
FULL_CLONE_TYPE = 'full'

CHECK_VOLUME_DATA_FINISHED_INTERVAL = 10
CHECK_VOLUME_DELETE_FINISHED_INTERVAL = 2
CHECK_SNAPSHOT_DELETE_FINISHED_INTERVAL = 2

huawei_storhyper_opts = [
    cfg.StrOpt('cinder_huawei_sds_conf_file',
               default='/etc/cinder/cinder_huawei_storac_conf.xml',
               help='huawei storagehyper driver config file path'),
]

CONF.register_opts(huawei_storhyper_opts)


class StorACDriver(driver.VolumeDriver):

    VERSION = '1.0.0'
    del_complete_code = '-900079'

    def __init__(self, *args, **kwargs):
        super(StorACDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(huawei_storhyper_opts)
        self._conf_file = self.configuration.cinder_huawei_sds_conf_file
        LOG.debug('Conf_file is: ' + self._conf_file)
        self._vbs_client = vbs_client.VbsClient(self._conf_file)
        self._volume_stats = self._get_default_volume_stats()

    def check_for_setup_error(self):
        pass

    def initialize_connection(self, volume, connector):
        LOG.debug('Initialize connection.')
        properties = {}
        properties['volume_id'] = volume['name']
        return {'driver_volume_type': 'HUAWEISDSHYPERVISOR',
                'data': properties}

    def terminate_connection(self, volume, connector, **kwargs):
        """Terminate the map."""
        pass

    def create_volume(self, volume):
        """Create a new volume."""
        volume_name = volume['name']
        LOG.debug('Create volume, volume name: %s.' % volume_name)
        volume_size = self._size_translate(volume['size'])

        volume_info = self._create_storage_info('volume_info')
        volume_info['vol_name'] = volume_name
        volume_info['vol_size'] = volume_size
        volume_info['pool_id'] = self._get_volume_pool_id(volume['host'])
        self._update_volume_info_from_volume(volume_info, volume)
        self._send_request('CREATE_VOLUME_REQ',
                           volume_info,
                           'create volume error.')
        return {'provider_location': volume['name']}

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        tgt_vol_name = volume['name']
        src_snapshot_name = snapshot['name']
        LOG.debug('Create volume from snapshot: '
                  'tgt_vol_name: %(tgt_vol_name)s, '
                  'src_snapshot_name: %(src_snapshot_name)s, '
                  'vol_size: %(vol_size)s.'
                  % {'tgt_vol_name': tgt_vol_name,
                     'src_snapshot_name': src_snapshot_name,
                     'vol_size': volume['size']})
        self._create_linked_volume_from_snap(src_snapshot_name,
                                             tgt_vol_name,
                                             volume['size'])

        return {'provider_location': volume['name']}

    def create_cloned_volume(self, tgt_volume, src_volume):
        """Create a clone volume."""
        src_vol_name = src_volume['name']
        tgt_vol_name = tgt_volume['name']
        LOG.debug('Create cloned volume: src volume: %(src)s, '
                  'tgt volume: %(tgt)s.' % {'src': src_vol_name,
                                            'tgt': tgt_vol_name})

        src_vol_id = src_volume.get('provider_location')
        if not src_vol_id:
            err_msg = (_LE('Source volume %(name)s does not exist.')
                       % {'name': src_vol_name})
            LOG.error(err_msg)
            raise exception.VolumeNotFound(volume_id=src_vol_name)

        volume_info = self._create_target_volume(src_volume,
                                                 tgt_vol_name,
                                                 tgt_volume)
        tgt_vol_id = volume_info['vol_name']

        self.copy_volume_data(context.get_admin_context(), src_volume,
                              tgt_volume, remote=None)

        return {'provider_location': tgt_vol_id}

    def delete_volume(self, volume):
        """Delete a volume."""
        req_paras = {}
        req_paras['vol_name'] = volume['name']
        self._send_request('DELETE_VOLUME_REQ',
                           req_paras,
                           'Delete volume failed.')
        self._wait_for_volume_delete(volume['name'])

    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        LOG.debug('Extend volume: %s.' % volume['name'])
        volume_name = volume['name']
        new_volume_size = self._size_translate(new_size)
        volume_info = {"vol_name": volume_name,
                       "vol_size": new_volume_size}

        self._send_request('EXTEND_VOLUME_REQ',
                           volume_info,
                           'extend volume failed.')

    def get_volume_stats(self, refresh=False):
        """Get volume stats."""
        if refresh:
            try:
                self._get_volume_stats()
            except Exception as ex:
                self._volume_stats = self._get_default_volume_stats()
                msg = (_LE('Error from get volume stats: '
                           '%s, using default stats.') % ex)
                LOG.error(msg)
        return self._volume_stats

    def create_snapshot(self, snapshot):
        create_snapshot_req = {}
        create_snapshot_req['snap_name'] = snapshot['name']
        create_snapshot_req['vol_name'] = snapshot['volume_name']
        create_snapshot_req['smartflag'] = '1'

        self._send_request('CREATE_SNAPSHOT_REQ',
                           create_snapshot_req,
                           'create snapshot failed.')

        return {'provider_location': snapshot['name']}

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        """Delete SDS snapshot,ensure source volume is attached """
        source_volume_id = snapshot['volume_id']
        if not source_volume_id:
            self._delete_snapshot(snapshot)
            return

        is_volume_attached = self._is_volume_attached(source_volume_id)
        if is_volume_attached:
            LOG.debug('Volume is attached')
            self._delete_snapshot(snapshot)
        else:
            LOG.debug('Volume is not attached')
            source_volume = {'name': 'volume-' + source_volume_id,
                             'id': source_volume_id}
            properties = utils.brick_get_connector_properties()
            source_volume_attach_info = self._attach_volume(
                None, source_volume, properties, False)
            try:
                self._delete_snapshot(snapshot)
            except Exception as ex:
                err_msg = (_LE('Delete snapshot failed: '
                           '%s.') % ex)
                LOG.error(err_msg)
            self._detach_volume(
                None, source_volume_attach_info, source_volume,
                properties, False, False)

    def create_export(self, context, volume):
        """Export the volume."""
        pass

    def ensure_export(self, context, volume):
        """Synchronously recreate an export for a volume."""
        pass

    def remove_export(self, context, volume):
        """Remove an export for a volume."""
        pass

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        err_msg = ''
        temp_snapshot, temp_volume = self._create_temp_snap_and_volume(volume)
        try:
            self.create_snapshot(temp_snapshot)
            self._create_linked_volume_from_snap(temp_snapshot['name'],
                                                 temp_volume['name'],
                                                 temp_volume['size'])
            temp_volume['status'] = volume['status']
            super(StorACDriver, self).copy_volume_to_image(context,
                                                           temp_volume,
                                                           image_service,
                                                           image_meta)
        except Exception as ex:
            err_msg = (_LE('Copy volume to image failed: %s.') % ex)
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        finally:
            self._clean_copy_volume_data(temp_volume,
                                         temp_snapshot,
                                         'copy_volume_to_image')

    def copy_volume_data(self, context, src_vol, dest_vol, remote=None):
        err_msg = ''
        temp_snapshot, temp_volume = self._create_temp_snap_and_volume(src_vol)
        try:
            self.create_snapshot(temp_snapshot)
            self._create_linked_volume_from_snap(temp_snapshot['name'],
                                                 temp_volume['name'],
                                                 temp_volume['size'])
            temp_volume['status'] = src_vol['status']
            super(StorACDriver, self).copy_volume_data(context,
                                                       temp_volume,
                                                       dest_vol,
                                                       remote)
        except Exception as ex:
            err_msg = (_LE('Copy volume data failed: %s.') % ex)
            LOG.error(err_msg)
            raise exception.VolumeBackendAPIException(data=err_msg)
        finally:
            self._clean_copy_volume_data(temp_volume,
                                         temp_snapshot,
                                         'copy_volume_data')

    def _create_temp_snap_and_volume(self, src_vol):
        temp_snapshot = {'name': 'snapshot-' + six.text_type(uuid.uuid1()),
                         'volume_name': src_vol['name'],
                         'smartflag': '1',
                         'volume_id': src_vol['id']}
        temp_volume_id = six.text_type(uuid.uuid1())
        temp_volume = {'id': temp_volume_id,
                       'name': 'volume-' + temp_volume_id,
                       'size': src_vol['size']}
        return temp_snapshot, temp_volume

    def _clean_copy_volume_data(self, temp_volume, temp_snapshot, method):
        try:
            self.delete_volume(temp_volume)
        except Exception as ex:
            err_msg = (_LE('Delete temp volume failed '
                       'after %(method)s: %(ex)s.')
                       % {'ex': ex, 'method': method})
            LOG.error(err_msg)
        try:
            self.delete_snapshot(temp_snapshot)
        except Exception as ex:
            err_msg = (_LE('Delete temp snapshot failed '
                       'after %(method)s: %(ex)s.')
                       % {'ex': ex, 'method': method})
            LOG.error(err_msg)

    def _is_volume_attached(self, volume_id):
        if not volume_id:
            return False
        conn = {'driver_volume_type': 'HUAWEISDSHYPERVISOR',
                'data': {'volume_id': 'volume-' + volume_id}}
        use_multipath = self.configuration.use_multipath_for_image_xfer
        device_scan_attempts = self.configuration.num_volume_device_scan_tries
        protocol = conn['driver_volume_type']
        connector = utils.brick_get_connector(protocol,
                                              use_multipath=use_multipath,
                                              device_scan_attempts=
                                              device_scan_attempts,
                                              conn=conn)
        is_volume_attached = connector.is_volume_connected(
            conn['data']['volume_id'])
        return is_volume_attached

    def _create_target_volume(self, src_volume, tgt_vol_name, tgt_volume):
        if int(tgt_volume['size']) == 0:
            tgt_vol_size = self._size_translate(src_volume['size'])
        else:
            tgt_vol_size = self._size_translate(tgt_volume['size'])

        volume_info = self._create_storage_info('volume_info')
        volume_info['vol_name'] = tgt_vol_name
        volume_info['vol_size'] = tgt_vol_size
        volume_info['pool_id'] = self._get_volume_pool_id(tgt_volume['host'])

        self._update_volume_info_from_volume_type(volume_info,
                                                  tgt_volume['volume_type_id'])
        self._send_request('CREATE_VOLUME_REQ',
                           volume_info,
                           'create volume failed.')
        return volume_info

    def _create_linked_volume_from_snap(self, src_snapshot_name,
                                        tgt_vol_name, volume_size):
        vol_size = self._size_translate(volume_size)
        req_paras = {'vol_name': tgt_vol_name,
                     'vol_size': vol_size,
                     'snap_name_src': src_snapshot_name,
                     'vol_num': '1'}

        self._send_request('CREATE_VOLUME_FROM_SNAPSHOT_REQ',
                           req_paras,
                           'Create volume from snapshot failed.')

    def _get_volume_stats(self):
        """Retrieve stats info from volume group."""
        capacity = self._get_capacity()
        self._volume_stats['pools'] = capacity

        if len(capacity) == 1:
            for key, value in capacity[0].items():
                self._volume_stats[key] = value

    def _get_all_pool_capacity(self):
        pool_info = {}
        poolnum = len(self._volume_stats['pools_id'])
        pool_info['pool_num'] = six.text_type(poolnum)
        pool_info['pool_id'] = self._volume_stats['pools_id']
        result = self._send_request('QUERY_POOLS_CAPABILITY_REQ',
                                    pool_info,
                                    'Get storage capacity failed')
        return self._extract_pool_capacity_mapping_from_result(result)

    def _get_capacity(self):
        storage_capacity = []
        try:
            all_pool_policy = self._extract_pool_policy_mapping_from_config(
                self._conf_file)
            all_pool_capacity = self._get_all_pool_capacity()
            self._update_all_pool_capacity_from_policy(all_pool_capacity,
                                                       all_pool_policy)
            storage_capacity = all_pool_capacity.values()
        except exception.VolumeBackendAPIException as ex:
            msg = (_LE('Error from get block storage capacity: '
                   '%s.') % ex)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(msg)
        return storage_capacity

    def _delete_snapshot(self, snapshot):
        req_paras = {}
        req_paras['snap_name'] = snapshot['name']
        self._send_request('DELETE_SNAPSHOT_REQ',
                           req_paras,
                           'Delete snapshot error.')
        self._wait_for_snapshot_delete(snapshot['name'])

    def _create_default_volume_stats(self):
        default_volume_stats = {'tolerance_disk_failure': ['1', '2', '3'],
                                'tolerance_cache_failure': ['0', '1'],
                                'free_capacity_gb': 0,
                                'total_capacity_gb': 0,
                                'reserved_percentage': 0,
                                'vendor_name': 'Huawei',
                                'driver_version': self.VERSION,
                                'storage_protocol': 'StorageHypervisor',
                                'pools_id': []}
        backend_name = self.configuration.safe_get('volume_backend_name')
        default_volume_stats['volume_backend_name'] = (
            backend_name or self.__class__.__name__)
        return default_volume_stats

    def _get_default_volume_stats(self):
        default_volume_stats = self._create_default_volume_stats()
        self._update_default_volume_stats_from_config(default_volume_stats,
                                                      self._conf_file)
        return default_volume_stats

    def _wait_for_volume_delete(self, volume_name):
        """Wait for volume delete to complete."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_volume_delete_finished, volume_name)
        LOG.debug('Calling _wait_for_volume_delete: volume_name %s.'
                  % volume_name)
        ret = timer.start(
            interval=CHECK_VOLUME_DELETE_FINISHED_INTERVAL).wait()
        timer.stop()
        if not ret:
            msg = (_LE('Delete volume failed,volume_name: %s.')
                   % volume_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        LOG.debug('Finish _wait_for_volume_delete: volume_name %s.'
                  % volume_name)

    def _wait_for_snapshot_delete(self, snapshot_name):
        """Wait for snapshot delete to complete."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_snapshot_delete_finished, snapshot_name)
        LOG.debug('Calling _wait_for_snapshot_delete: snapshot_name %s.'
                  % snapshot_name)
        ret = timer.start(
            interval=CHECK_SNAPSHOT_DELETE_FINISHED_INTERVAL).wait()
        timer.stop()
        if not ret:
            msg = (_LE('Delete snapshot failed,snapshot_name: %s.')
                   % snapshot_name)
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(message=msg)

        LOG.debug('Finish _wait_for_snapshot_delete: snapshot_name %s.'
                  % snapshot_name)

    def _check_volume_delete_finished(self, volume_name):
        try:
            is_volume_exist = self._is_volume_exist(volume_name)
        except Exception as ex:
            msg = (_LE('Check volume_name delete finished failed: '
                   '%s.') % ex)
            LOG.error(msg)
            raise loopingcall.LoopingCallDone(retvalue=False)
        if not is_volume_exist:
            raise loopingcall.LoopingCallDone(retvalue=True)

    def _check_snapshot_delete_finished(self, snapshot_name):
        try:
            is_snapshot_exist = self._is_snapshot_exist(snapshot_name)
        except Exception as ex:
            msg = (_LE('Check snapshot delete finished failed: '
                   '%s.') % ex)
            LOG.error(msg)
            raise loopingcall.LoopingCallDone(retvalue=False)
        if not is_snapshot_exist:
            raise loopingcall.LoopingCallDone(retvalue=True)

    def _query_volume(self, volume_name):
        request_info = {'vol_name': volume_name}
        request_type = 'QUERY_VOLUME_REQ'
        rsp_str = self._vbs_client.send_message(
            storhyper_utils.serialize(request_type,
                                      request_info)
        )
        LOG.debug('%s received:%s.' % (request_type, repr(rsp_str)))
        result = storhyper_utils.deserialize(six.text_type(rsp_str),
                                             delimiter='\n')
        storhyper_utils.log_dict(result)
        return result

    def _is_volume_exist(self, volume_name):
        query_volume_result = self._query_volume(volume_name)
        if ((not query_volume_result) or
                ('retcode' not in query_volume_result) or
                (query_volume_result['retcode']
                 not in ('0', self.del_complete_code))):
            msg = _('%(err)s\n') % {'err': 'Query volume failed!'
                                           ' Invalid result code'}
            raise exception.VolumeBackendAPIException(data=msg)
        if query_volume_result['retcode'] == self.del_complete_code:
            return False
        if query_volume_result['retcode'] == '0':
            if 'volume0' not in query_volume_result:
                msg = _('%(err)s\n') % {'err': 'Query volume failed! '
                                               'Volume0 not exist!'}
                raise exception.VolumeBackendAPIException(data=msg)
            query_volume_result['volume0'] = \
                storhyper_utils.generate_dict_from_result(
                    query_volume_result['volume0'])
            if (('status' not in query_volume_result['volume0']) or
                    (query_volume_result['volume0']['status'] not in
                        ('1', '2', '10'))):
                msg = _('%(err)s\n') % {'err': 'Query volume failed!'
                                               ' Invalid volume status'}
                raise exception.VolumeBackendAPIException(data=msg)
            return True

    def _query_snapshot(self, snapshot_name):
        request_info = {'snap_name': snapshot_name}
        request_type = 'QUERY_SNAPSHOT_REQ'
        rsp_str = self._vbs_client.send_message(
            storhyper_utils.serialize(request_type,
                                      request_info)
        )
        LOG.debug('%s received:%s.' % (request_type, repr(rsp_str)))
        result = storhyper_utils.deserialize(six.text_type(rsp_str),
                                             delimiter='\n')
        storhyper_utils.log_dict(result)
        return result

    def _is_snapshot_exist(self, snapshot_name):
        query_snapshot_result = self._query_snapshot(snapshot_name)
        if ((not query_snapshot_result) or
                ('retcode' not in query_snapshot_result) or
                (query_snapshot_result['retcode']
                 not in ('0', self.del_complete_code))):
            msg = _('%(err)s\n') % {'err': 'Query snapshot failed!'}
            raise exception.VolumeBackendAPIException(data=msg)
        if query_snapshot_result['retcode'] == self.del_complete_code:
            return False
        if query_snapshot_result['retcode'] == '0':
            if 'snapshot0' not in query_snapshot_result:
                msg = _('%(err)s\n') % {'err': 'Query snapshot failed!'}
                raise exception.VolumeBackendAPIException(data=msg)
            query_snapshot_result['snapshot0'] =\
                storhyper_utils.generate_dict_from_result(
                    query_snapshot_result['snapshot0'])
            if (('status' not in query_snapshot_result['snapshot0']) or
                    (query_snapshot_result['snapshot0']['status'] not in
                        ('1', '2'))):
                msg = _('%(err)s\n') % {'err': 'Query snapshot failed!'}
                raise exception.VolumeBackendAPIException(data=msg)
            return True

    def _get_volume_pool_id(self, volume_host):
        if volume_host:
            if len(volume_host.split('#', 1)) == 2:
                return volume_host.split('#')[1]

        if len(self._volume_stats['pools_id']) == 1:
            return self._volume_stats['pools_id'][0]
        else:
            msg = (_LE("Get pool id failed, invalid pool id."))
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

    def _send_request(self, request_type, request_info, error_message):
        rsp_str = self._vbs_client.send_message(
            storhyper_utils.serialize(request_type, request_info))
        LOG.debug('%s received:%s.' % (request_type, repr(rsp_str)))
        result = storhyper_utils.deserialize(six.text_type(rsp_str),
                                             delimiter='\n')
        storhyper_utils.log_dict(result)
        if (len(result) < 0 or 'retcode' not in result
                or result['retcode'] != '0'):
            msg = _('%(err)s\n') % {'err': error_message}
            raise exception.VolumeBackendAPIException(data=msg)
        return result

    def _update_default_volume_stats_from_config(self,
                                                 default_volume_stats,
                                                 config_file):
            root = storhyper_utils.parse_xml_file(config_file)
            for child in root.find('policy').findall('*'):
                if child.tag == 'QoS_support':
                    if child.text.strip() == '0':
                        default_volume_stats[child.tag] = False
                    else:
                        default_volume_stats[child.tag] = True
                else:
                    default_volume_stats[child.tag] = child.text.strip()
            for child in root.find('capability').findall('*'):
                default_volume_stats[child.tag] = child.text.strip()
            pools = root.find('pools').findall('*')
            for pool in pools:
                for child in pool.findall('*'):
                    childtext = child.text.strip()
                    if child.tag == 'pool_id' and len(childtext) > 0:
                        default_volume_stats['pools_id'].append(childtext)

    def _update_all_pool_capacity_from_policy(self,
                                              all_pool_capacity,
                                              all_pool_policy):
        for pool_name in all_pool_capacity.keys():
            if pool_name in all_pool_policy:
                for pool_key, pool_value in all_pool_policy[pool_name].items():
                    all_pool_capacity[pool_name][pool_key] = pool_value

    def _extract_pool_policy_mapping_from_config(self, conf_file):
        pools_policy_mapping = {}
        root = storhyper_utils.parse_xml_file(conf_file)
        pools = root.find('pools').findall('*')
        for pool in pools:
            policy = {}
            pool_id = ''
            for child in pool.findall('*'):
                if child.tag == 'pool_id':
                    pool_id = child.text.strip()
                else:
                    policy[child.tag] = child.text.strip()
            pools_policy_mapping[pool_id] = policy
        return pools_policy_mapping

    def _extract_pool_capacity_mapping_from_result(self, result):
        pool_capacity_mapping = {}
        for key, value in result.items():
            if 'pool' in key and value:
                pool_capacity = {}
                pool_name = ''
                pool_str = value.replace('[', '').replace(']', '')
                paras = pool_str.split(',')
                for para in paras:
                    key = para.split('=')[0]
                    value = para.split('=')[1]
                    if key == 'stor_id':
                        pool_capacity['pool_name'] = six.text_type(value)
                        pool_name = six.text_type(value)
                    elif key == 'total_capacity':
                        pool_capacity['total_capacity_gb'] = int(value)
                    elif key == 'usable_capacity':
                        pool_capacity['free_capacity_gb'] = int(value)
                    elif key == 'raid_level':
                        pool_capacity['raid_level'] = int(value)
                    elif key == 'iops':
                        pool_capacity['iops'] = int(value)

                pool_capacity['allocated_capacity_gb'] = \
                    pool_capacity['total_capacity_gb'] \
                    - pool_capacity['free_capacity_gb']
                pool_capacity['reserved_percentage'] = 0
                pool_capacity_mapping[pool_name] = pool_capacity

        return pool_capacity_mapping

    def _size_translate(self, size):
            volume_size = '%s' % (size * units.Ki)
            return volume_size

    def _update_volume_info_from_volume_extra_specs(self, volume_info,
                                                    extra_specs):
        if not extra_specs:
            return

        for x in extra_specs:
            key = x['key']
            value = x['value']
            LOG.debug('Volume type: key=%(key)s  value=%(value)s.'
                      % {'key': key, 'value': value})
            if key in volume_info.keys():
                words = value.strip().split()
                volume_info[key] = words.pop()

    def _update_volume_info_from_volume(self, volume_info, volume):
        if not volume['volume_type_id']:
            return
        else:
            spec = volume['volume_type']['extra_specs']
            self._update_volume_info_from_volume_extra_specs(volume_info,
                                                             spec)
            self._update_volume_info_from_qos_specs(volume_info,
                                                    volume['volume_type'])

    def _update_volume_info_from_extra_specs(self,
                                             volume_info,
                                             extra_specs):
        if not extra_specs:
            return
        for key, value in extra_specs.items():
            LOG.debug('key=%(key)s  value=%(value)s.'
                      % {'key': key, 'value': value})
            if key in volume_info.keys():
                words = value.strip().split()
                volume_info[key] = words.pop()

    def _update_volume_info_from_qos_specs(self,
                                           volume_info,
                                           qos_specs):
        if not qos_specs:
            return
        if qos_specs.get('qos_specs'):
            if qos_specs['qos_specs'].get('specs'):
                qos_spec = qos_specs['qos_specs'].get('specs')
                for key, value in qos_spec.items():
                    LOG.debug('key=%(key)s  value=%(value)s.'
                              % {'key': key, 'value': value})
                    if key in QOS_KEY:
                        volume_info['IOClASSID'] = value.strip()
                        qos_level = key
                        if qos_level == 'Qos-high':
                            volume_info['IOPRIORITY'] = "3"
                        elif qos_level == 'Qos-normal':
                            volume_info['IOPRIORITY'] = "2"
                        elif qos_level == 'Qos-low':
                            volume_info['IOPRIORITY'] = "1"
                        else:
                            volume_info['IOPRIORITY'] = "2"

    def _update_volume_info_from_volume_type(self,
                                             volume_info,
                                             volume_type_id):
        if not volume_type_id:
            return
        else:
            volume_type = volume_types.get_volume_type(
                context.get_admin_context(), volume_type_id)
            extra_specs = volume_type.get('extra_specs')
            self._update_volume_info_from_extra_specs(volume_info, extra_specs)
            qos_specs = volume_types.get_volume_type_qos_specs(volume_type_id)
            self._update_volume_info_from_qos_specs(volume_info, qos_specs)

    def _create_storage_info(self, info_type):
        if info_type == 'volume_info':
            volume_info = {'vol_name': '',
                           'vol_size': '',
                           'pool_id': '0',
                           'thin_flag': '0',
                           'reserved': '0',
                           'volume_space_reserved': '0',
                           'force_provision_size': '0',
                           'iops': '100',
                           'max_iops': '100',
                           'min_iops': '0',
                           'cache_size': '0',
                           'repicate_num': '1',
                           'repicate_tolerant_num': '1',
                           'encrypt_algorithm': '0',
                           'consistency': '0',
                           'stor_space_level': '1',
                           'compress_algorithm': '0',
                           'deduplication': '0',
                           'snapshot': '0',
                           'backup_cycle': '0',
                           'tolerance_disk_failure': '0',
                           'tolerance_cache_failure': '1'}
            return volume_info
        else:
            LOG.error(_LE('Invalid info type.'))
            return None
