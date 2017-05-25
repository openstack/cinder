# Copyright (c) 2016 FalconStor, Inc.
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
import random
import six
import time
import uuid

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
from six.moves import http_client

from cinder import exception
from cinder.i18n import _

FSS_BATCH = 'batch'
FSS_PHYSICALRESOURCE = 'physicalresource'
FSS_PHYSICALADAPTER = 'physicaladapter'
FSS_FCCLIENTINITIATORS = 'fcclientinitiators'
FSS_FC_TGT_WWPN = 'fctgtwwpn'
FSS_STORAGE_POOL = 'storagepool'
FSS_LOGICALRESOURCE = 'logicalresource'
FSS_SAN = 'sanresource'
FSS_MIRROR = 'mirror'
FSS_TIMEMARKPOLICY = 'timemarkpolicy'
FSS_TIMEMARK = 'timemark'
FSS_TIMEVIEW = 'timeview'
FSS_SNAPSHOT_RESOURCE = 'snapshotresource'
FSS_SNAPSHOT_GROUP = 'snapshotgroup'
FSS_CLIENT = 'client'
FSS_SANCLIENT = 'sanclient'
FSS_ISCSI_TARGET = 'iscsitarget'
FSS_ISCSI_CLIENT_INITIATORS = 'iscsiclientinitiators'
FSS_SERVER = 'server'
FSS_OPTIONS = 'options'
FSS_PORTAL = 'defaultiscsiportal'
FSS_PROPERTIES = 'properties'
FSS_HOST = 'host'
FSS_RETURN_CODE = 'rcs'
FSS_AUTH = 'auth'
FSS_LOGIN = 'login'
FSS_SINGLE_TYPE = 'single'

POST = 'POST'
GET = 'GET'
PUT = 'PUT'
DELETE = 'DELETE'
GROUP_PREFIX = 'OpenStack-'
PRODUCT_NAME = 'ipstor'
SESSION_COOKIE_NAME = 'session_id'
RETRY_LIST = ['107', '2147680512']

MAXSNAPSHOTS = 1000
OPERATION_TIMEOUT = 60 * 60
RETRY_CNT = 5
RETRY_INTERVAL = 15

LOG = logging.getLogger(__name__)


class RESTProxy(object):
    def __init__(self, config):
        self.fss_host = config.san_ip
        self.fss_defined_pools = config.fss_pools
        if config.additional_retry_list:
            RETRY_LIST.append(config.additional_retry_list)

        self.FSS = FSSRestCommon(config)
        self.session_id = None

    # naming
    def _get_vol_name_from_snap(self, snapshot):
        """Return the name of the snapshot that FSS will use."""
        return "cinder-%s" % snapshot["volume_id"]

    def _get_fss_volume_name(self, volume):
        """Return the name of the volume FSS will use."""
        return "cinder-%s" % volume["id"]

    def _get_group_name_from_id(self, id):
        return "cinder-consisgroup-%s" % id

    def _encode_name(self, name):
        uuid_str = name.replace("-", "")
        vol_uuid = uuid.UUID('urn:uuid:%s' % uuid_str)
        newuuid = (base64.urlsafe_b64encode(vol_uuid.bytes).
                   decode('utf-8').strip('='))
        return "cinder-%s" % newuuid

    def do_setup(self):
        self.session_id = self.FSS.fss_login()

    def _convert_size_to_gb(self, size):
        s = round(float(size) / units.Gi, 2)
        if s > 0:
            return s
        else:
            return 0

    def _convert_size_to_mb(self, size):
        return size * units.Ki

    def _get_pools_info(self):
        qpools = []
        poolinfo = {}
        total_capacity_gb = 0
        used_gb = 0
        try:
            output = self.list_pool_info()
            if output and "storagepools" in output['data']:
                for item in output['data']['storagepools']:
                    if item['name'].startswith(GROUP_PREFIX) and (
                            six.text_type(item['id']) in
                            self.fss_defined_pools.values()):
                        poolid = int(item['id'])
                        qpools.append(poolid)

            if not qpools:
                msg = _('The storage pool information is empty or not correct')
                raise exception.DriverNotInitialized(msg)

            # Query pool detail information
            for poolid in qpools:
                output = self.list_pool_info(poolid)
                total_capacity_gb += (
                    self._convert_size_to_gb(output['data']['size']))
                used_gb += (self._convert_size_to_gb(output['data']['used']))

        except Exception:
            msg = (_('Unexpected exception during get pools info.'))
            LOG.exception(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        poolinfo['total_capacity_gb'] = total_capacity_gb
        poolinfo['used_gb'] = used_gb
        poolinfo['QoS_support'] = False
        poolinfo['reserved_percentage'] = 0

        return poolinfo

    def list_pool_info(self, pool_id=None):
        return self.FSS.list_pool_info(pool_id)

    def list_physicaladapter_info(self, adapter_id=None):
        return self.FSS.list_physicaladapter_info(adapter_id)

    def _checking_adapter_type(self, id):
        adapter_type = ''
        output = self.list_physicaladapter_info()
        if "physicaladapters" in output['data']:
            physicaladapters = output['data']['physicaladapters']
            if physicaladapters['id'] == id:
                adapter_type = physicaladapters['type']
        return adapter_type

    def _selected_pool_id(self, pool_info, pool_type=None):
        _pool_id = 0
        if len(pool_info) == 1 and "A" in pool_info:
            _pool_id = pool_info['A']
        elif len(pool_info) == 2 and "P" in pool_info and "O" in pool_info:
            if pool_type:
                if pool_type == "P":
                    _pool_id = pool_info['P']
                elif pool_type == "O":
                    _pool_id = pool_info['O']
        return _pool_id

    def create_vdev(self, volume):
        sizemb = self._convert_size_to_mb(volume["size"])
        volume_name = self._get_fss_volume_name(volume)
        params = dict(category="virtual",
                      sizemb=sizemb,
                      name=volume_name)
        pool_id = self._selected_pool_id(self.fss_defined_pools, "P")
        params.update(storagepoolid=pool_id)
        return volume_name, self.FSS.create_vdev(params)

    def create_tv_from_cdp_tag(self, volume_metadata, volume):
        tv_vid = ''
        cdp_tag = ''

        if 'cdptag' in volume_metadata:
            tv_vid = str(volume_metadata['timeview']) + '_0'
            cdp_tag = str(volume_metadata['cdptag'])

        if 'rawtimestamp' in volume_metadata:
            tv_vid = '{0}_{1}'.format(str(volume_metadata['timeview']),
                                      str(volume_metadata['rawtimestamp']))
        volume_name = self._get_fss_volume_name(volume)
        sizemb = self._convert_size_to_mb(volume['size'])
        params = dict(name=volume_name,
                      automaticexpansion=dict(enabled=False),
                      timeviewcopy=True)
        if cdp_tag:
            params.update(cdpjournaltag=cdp_tag)

        pool_id = self._selected_pool_id(self.fss_defined_pools, "O")
        params.update(storage={'storagepoolid': pool_id, 'sizemb': sizemb})
        metadata = self.FSS.create_timeview(tv_vid, params)
        return volume_name, metadata

    def create_thin_vdev(self, volume_metadata, volume):
        thin_size = 0
        size = volume["size"]
        sizemb = self._convert_size_to_mb(size)
        params = {'category': 'virtual'}

        if 'thinprovisioned' in volume_metadata:
            if volume_metadata['thinprovisioned'] is False:
                msg = (_('If you want to create a thin provisioning volume,'
                         ' this param must be True.'))
                raise exception.VolumeBackendAPIException(msg)

        if 'thinsize' in volume_metadata:
            thin_size = int(volume_metadata['thinsize'])

        if size < 10:
            msg = _('The resource is a FSS thin device, minimum size is '
                    '10240 MB.')
            raise exception.VolumeBackendAPIException(msg)
        else:
            try:
                if thin_size > size:
                    msg = _('The allocated size must less than total size.')
                    raise exception.VolumeBackendAPIException(msg)
            except Exception:
                msg = _('The resource is a thin device, thin size is invalid.')
                raise exception.VolumeBackendAPIException(msg)

            thin_size = self._convert_size_to_mb(thin_size)
            thin_disk = dict(
                enabled=True,
                fullsizemb=sizemb)
            params.update(thinprovisioning=thin_disk)
            params.update(sizemb=thin_size)

        pool_id = self._selected_pool_id(self.fss_defined_pools, "P")
        params.update(storagepoolid=pool_id)
        volume_name = self._get_fss_volume_name(volume)
        params.update(name=volume_name)
        return volume_name, self.FSS.create_vdev(params)

    def create_vdev_with_mirror(self, volume_metadata, volume):

        if 'mirrored' in volume_metadata:
            if volume_metadata['mirrored'] is False:
                msg = _('If you want to create a mirrored volume, this param '
                        'must be True.')
                raise exception.VolumeBackendAPIException(data=msg)

        sizemb = self._convert_size_to_mb(volume["size"])
        volume_name = self._get_fss_volume_name(volume)
        params = {'category': 'virtual', 'sizemb': sizemb, 'name': volume_name}

        pool_id = self._selected_pool_id(self.fss_defined_pools, "P")
        params.update(storagepoolid=pool_id)
        metadata = self.FSS.create_vdev(params)
        if metadata:
            vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
            mirror_params = {'category': 'virtual',
                             'selectioncriteria': 'anydrive',
                             'mirrortarget': "virtual"}

            pool_id = self._selected_pool_id(self.fss_defined_pools, "O")
            mirror_params.update(storagepoolid=pool_id)

            ret = self.FSS.create_mirror(vid, mirror_params)
            if ret:
                return volume_name, metadata

    def _get_fss_vid_from_name(self, volume_name, fss_type=None):
        vid = []
        output = self.FSS.list_fss_volume_info()
        try:
            if "virtualdevices" in output['data']:
                for item in output['data']['virtualdevices']:
                    if item['name'] in volume_name:
                        vid.append(item['id'])
        except Exception:
            msg = (_('Can not find cinder volume - %(volumeName)s') %
                   {"volumeName": volume_name})
            raise exception.VolumeBackendAPIException(msg)

        if fss_type is not None and fss_type == FSS_SINGLE_TYPE:
            vid = ''.join(str(x) for x in vid)
        return vid

    def _get_fss_gid_from_name(self, group_name):
        gid = ''
        output = self.FSS.list_group_info()
        if "snapshotgroups" in output['data']:
            for item in output['data']['snapshotgroups']:
                if item['name'] == group_name:
                    gid = item['id']
                    break
            if gid == '':
                msg = (_('Can not find consistency group: %s.') % group_name)
                raise exception.VolumeBackendAPIException(msg)
        return gid

    def _get_fss_group_membercount(self, gid):
        membercount = 0
        output = self.FSS.list_group_info(gid)
        if "membercount" in output['data']:
            membercount = output['data']['membercount']
        return membercount

    def _get_vdev_id_from_group_id(self, group_id):
        vidlist = []
        output = self.FSS.list_group_info(group_id)
        if "virtualdevices" in output['data']:
            for item in output['data']['virtualdevices']:
                vidlist.append(item['id'])
        return vidlist

    def clone_volume(self, new_vol_name, source_volume_name):
        volume_metadata = {}
        new_vid = ''
        vid = self._get_fss_vid_from_name(source_volume_name, FSS_SINGLE_TYPE)
        mirror_params = dict(
            category='virtual',
            selectioncriteria='anydrive',
            mirrortarget="virtual"
        )
        pool_id = self._selected_pool_id(self.fss_defined_pools, "O")
        mirror_params.update(storagepoolid=pool_id)
        ret1 = self.FSS.create_mirror(vid, mirror_params)

        if ret1:
            if ret1['rc'] != 0:
                failed_ret = self.FSS.get_fss_error_code(ret1['rc'])
                raise exception.VolumeBackendAPIException(data=failed_ret)

        ret2 = self.FSS.sync_mirror(vid)
        self.FSS._random_sleep()
        if ret2['rc'] == 0:
            self.FSS._check_mirror_sync_finished(vid, OPERATION_TIMEOUT)
            ret3 = self.FSS.promote_mirror(vid, new_vol_name)
            if ret3 and ret3['rc'] == 0:
                new_vid = ret3['id']

        volume_metadata['FSS-vid'] = new_vid
        return volume_metadata

    def delete_vdev(self, volume):
        volume_name = self._get_fss_volume_name(volume)
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        if vid:
            return self.FSS.delete_vdev(vid)
        else:
            msg = _('vid is null. FSS failed to delete volume.')
            raise exception.VolumeBackendAPIException(data=msg)

    def create_snapshot(self, snapshot):
        snap_metadata = {}
        volume_name = self._get_vol_name_from_snap(snapshot)
        snap_name = snapshot["display_name"]
        size = snapshot['volume_size']
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        if not vid:
            msg = _('vid is null. FSS failed to create snapshot.')
            raise exception.VolumeBackendAPIException(data=msg)

        (snap, tm_policy, vdev_size) = (self.FSS.
                                        _check_if_snapshot_tm_exist(vid))
        if not snap:
            self.create_vdev_snapshot(vid, self._convert_size_to_mb(size))
        if not tm_policy:
            pool_id = self._selected_pool_id(self.fss_defined_pools, "O")
            self.FSS.create_timemark_policy(vid, storagepoolid=pool_id)
        if not snap_name:
            snap_name = "snap-%s" % time.strftime('%Y%m%d%H%M%S')

        if len(snap_name) > 32:
            snap_name = self._encode_name(snapshot["id"])

        self.FSS.create_timemark(vid, snap_name)
        snap_metadata['fss_tm_comment'] = snap_name
        return snap_metadata

    def delete_snapshot(self, snapshot):
        volume_name = self._get_vol_name_from_snap(snapshot)
        snap_name = snapshot["display_name"]
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)

        if not vid:
            msg = _('vid is null. FSS failed to delete snapshot')
            raise exception.VolumeBackendAPIException(data=msg)
        if not snap_name:
            if ('metadata' in snapshot and 'fss_tm_comment' in
               snapshot['metadata']):
                snap_name = snapshot['metadata']['fss_tm_comment']

        if len(snap_name) > 32:
            snap_name = self._encode_name(snapshot["id"])

        tm_info = self.FSS.get_timemark(vid)
        rawtimestamp = self._get_timestamp(tm_info, snap_name)
        if rawtimestamp:
            timestamp = '%s_%s' % (vid, rawtimestamp)
            self.FSS.delete_timemark(timestamp)

            final_tm_data = self.FSS.get_timemark(vid)
            if "timemark" in final_tm_data['data']:
                if not final_tm_data['data']['timemark']:
                    self.FSS.delete_timemark_policy(vid)
                    self.FSS.delete_vdev_snapshot(vid)

    def _get_timestamp(self, tm_data, encode_snap_name):
        timestamp = ''
        if "timemark" in tm_data['data']:
            for item in tm_data['data']['timemark']:
                if "comment" in item and item['comment'] == encode_snap_name:
                    timestamp = item['rawtimestamp']
                    break
        return timestamp

    def create_volume_from_snapshot(self, volume, snapshot):
        volume_metadata = {}
        volume_name = self._get_vol_name_from_snap(snapshot)
        snap_name = snapshot["display_name"]
        new_vol_name = self._get_fss_volume_name(volume)
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        if not vid:
            msg = _('vid is null. FSS failed to create_volume_from_snapshot.')
            raise exception.VolumeBackendAPIException(data=msg)

        if not snap_name:
            if ('metadata' in snapshot) and ('fss_tm_comment'
                                             in snapshot['metadata']):
                snap_name = snapshot['metadata']['fss_tm_comment']
        if len(snap_name) > 32:
            snap_name = self._encode_name(snapshot["id"])

        tm_info = self.FSS.get_timemark(vid)
        rawtimestamp = self._get_timestamp(tm_info, snap_name)
        if not rawtimestamp:
            msg = _('rawtimestamp is null. FSS failed to '
                    'create_volume_from_snapshot.')
            raise exception.VolumeBackendAPIException(data=msg)

        timestamp = '%s_%s' % (vid, rawtimestamp)
        pool_id = self._selected_pool_id(self.fss_defined_pools, "P")
        output = self.FSS.copy_timemark(
            timestamp, storagepoolid=pool_id, name=new_vol_name)
        if output['rc'] == 0:
            vid = output['id']
            self.FSS._random_sleep()
            if self.FSS._check_tm_copy_finished(vid, OPERATION_TIMEOUT):
                volume_metadata['FSS-vid'] = vid
                return volume_name, volume_metadata

    def extend_vdev(self, volume_name, vol_size, new_size):
        if new_size > vol_size:
            vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
            size = self._convert_size_to_mb(new_size - vol_size)
            params = dict(
                action='expand',
                sizemb=size
            )
            return self.FSS.extend_vdev(vid, params)

    def list_volume_info(self, vid):
        return self.FSS.list_fss_volume_info(vid)

    def rename_vdev(self, vid, new_vol_name):
        params = dict(
            action='update',
            name=new_vol_name
        )
        return self.FSS.rename_vdev(vid, params)

    def assign_iscsi_vdev(self, client_id, target_id, vid):
        params = dict(
            action="assign",
            virtualdeviceids=[vid],
            iscsi=dict(target=target_id)
        )
        return self.FSS.assign_vdev(client_id, params)

    def assign_fc_vdev(self, client_id, vid):
        params = dict(
            action="assign",
            virtualdeviceids=[vid],
            fc=dict(
                fcmapping='alltoall',
                accessmode='readwritenonexclusive')
        )
        return self.FSS.assign_vdev(client_id, params)

    def unassign_vdev(self, client_id, vid):
        params = dict(
            action="unassign",
            virtualdeviceid=vid
        )
        return self.FSS.unassign_vdev(client_id, params)

    def _create_vdev_snapshot(self, volume_name, size):
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        return self.create_vdev_snapshot(vid, self._convert_size_to_mb(size))

    def create_vdev_snapshot(self, vid, size):
        pool_id = self._selected_pool_id(self.fss_defined_pools, "O")
        params = dict(
            idlist=[vid],
            selectioncriteria='anydrive',
            policy='preserveall',
            sizemb=size,
            storagepoolid=pool_id
        )
        return self.FSS.create_vdev_snapshot(params)

    def create_group(self, group):
        group_name = self._get_group_name_from_id(group['id'])
        params = dict(
            name=group_name
        )
        return self.FSS.create_group(params)

    def destroy_group(self, group):
        group_name = self._get_group_name_from_id(group['id'])
        gid = self._get_fss_gid_from_name(group_name)
        return self.FSS.destroy_group(gid)

    def _add_volume_to_consistency_group(self, group_id, vol_name):
        self.set_group(group_id, addvollist=[vol_name])

    def set_group(self, group_id, **kwargs):
        group_name = self._get_group_name_from_id(group_id)
        gid = self._get_fss_gid_from_name(group_name)

        join_params = dict()
        leave_params = dict()
        if kwargs.get('addvollist'):
            joing_vid = self._get_fss_vid_from_name(kwargs['addvollist'])
            join_params.update(
                action='join',
                virtualdevices=joing_vid
            )
        if kwargs.get('remvollist'):
            leave_vid = self._get_fss_vid_from_name(kwargs['remvollist'])
            leave_params.update(
                action='leave',
                virtualdevices=leave_vid
            )
        return self.FSS.set_group(gid, join_params, leave_params)

    def create_cgsnapshot(self, cgsnapshot):
        group_name = self._get_group_name_from_id(
            cgsnapshot['consistencygroup_id'])
        gsnap_name = self._encode_name(cgsnapshot['id'])
        gid = self._get_fss_gid_from_name(group_name)
        vidlist = self._get_vdev_id_from_group_id(gid)
        pool_id = self._selected_pool_id(self.fss_defined_pools, "O")

        for vid in vidlist:
            (snap, tm_policy, sizemb) = (self.FSS.
                                         _check_if_snapshot_tm_exist(vid))
            if not snap:
                self.create_vdev_snapshot(vid, sizemb)
            if not tm_policy:
                self.FSS.create_timemark_policy(vid, storagepoolid=pool_id)

        group_tm_policy = self.FSS._check_if_group_tm_enabled(gid)
        if not group_tm_policy:
            self.create_group_timemark_policy(gid)

        self.create_group_timemark(gid, gsnap_name)

    def create_group_timemark_policy(self, gid):
        tm_params = dict(
            automatic=dict(enabled=False),
            maxtimemarkcount=MAXSNAPSHOTS
        )
        return self.FSS.create_group_timemark_policy(gid, tm_params)

    def create_group_timemark(self, gid, gsnap_name):
        params = dict(
            comment=gsnap_name,
            priority='medium',
            snapshotnotification=False
        )
        return self.FSS.create_group_timemark(gid, params)

    def delete_cgsnapshot(self, cgsnapshot):
        group_name = self._get_group_name_from_id(
            cgsnapshot['consistencygroup_id'])
        encode_snap_name = self._encode_name(cgsnapshot['id'])
        gid = self._get_fss_gid_from_name(group_name)

        if not gid:
            msg = _('gid is null. FSS failed to delete cgsnapshot.')
            raise exception.VolumeBackendAPIException(data=msg)

        if self._get_fss_group_membercount(gid) != 0:
            tm_info = self.FSS.get_group_timemark(gid)
            rawtimestamp = self._get_timestamp(tm_info, encode_snap_name)
            timestamp = '%s_%s' % (gid, rawtimestamp)
            self.delete_group_timemark(timestamp)

        final_tm_data = self.FSS.get_group_timemark(gid)
        if "timemark" in final_tm_data['data']:
            if not final_tm_data['data']['timemark']:
                self.FSS.delete_group_timemark_policy(gid)

    def delete_group_timemark(self, timestamp):
        params = dict(
            deleteallbefore=False
        )
        return self.FSS.delete_group_timemark(timestamp, params)

    def _check_iscsi_option(self):
        output = self.FSS.get_server_options()
        if "iscsitarget" in output['data']:
            if not output['data']['iscsitarget']:
                self.FSS.set_server_options('iscsitarget')

    def _check_fc_target_option(self):
        output = self.FSS.get_server_options()
        if "fctarget" in output['data']:
            if not output['data']['fctarget']:
                self.FSS.set_server_options('fctarget')

    def _check_iocluster_state(self):
        output = self.FSS.get_server_options()
        if 'iocluster' not in output['data']:
            msg = _('No iocluster information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        return output['data']['iocluster']

    def list_fc_target_wwpn(self):
        return self.FSS.list_fc_target_wwpn()

    def list_fc_client_initiators(self):
        return self.FSS.list_fc_client_initiators()

    def create_fc_client(self, cinder_host_name, free_initiator_wwpns):
        client_id = 0
        params = dict(
            name=cinder_host_name,
            protocoltype=["fc"],
            ipaddress=self.fss_host,
            ostype='linux',
            fcpolicy=dict(
                initiators=[free_initiator_wwpns],
                vsaenabled=False
            )
        )
        client_info = self.FSS.create_client(params)
        if client_info and client_info['rc'] == 0:
            client_id = client_info['id']
        return client_id

    def list_iscsi_target_info(self, target_id=None):
        return self.FSS.list_iscsi_target_info(target_id)

    def _check_fc_host_devices_empty(self, client_id):
        is_empty = False
        output = self.FSS.list_sanclient_info(client_id)
        if 'data' not in output:
            msg = _('No target in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if 'fcdevices' not in output['data']:
            msg = _('No fcdevices in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if len(output['data']['fcdevices']) == 0:
            is_empty = True
            self.FSS.delete_client(client_id)
        return is_empty

    def create_iscsi_client(self, cinder_host_name, initiator):
        params = dict(
            name=cinder_host_name,
            protocoltype=["iscsi"],
            ipaddress=self.fss_host,
            ostype='linux',
            iscsipolicy=dict(
                initiators=[initiator],
                authentication=dict(enabled=False,
                                    mutualchap=dict(enabled=False))
            )
        )
        return self.FSS.create_client(params)

    def create_iscsitarget(self, client_id, initiator, fss_hosts):
        params = dict(
            clientid=client_id,
            name=initiator,
            ipaddress=fss_hosts,
            accessmode='readwritenonexclusive'
        )
        return self.FSS.create_iscsitarget(params)

    def _get_iscsi_host(self, connector):
        target_info = self.list_iscsi_target_info()
        if 'data' not in target_info:
            msg = _('No data information in return info.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'iscsitargets' not in target_info['data']:
            msg = _('No iscsitargets in return info.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if target_info['data']['iscsitargets']:
            iscsitargets = target_info['data']['iscsitargets']
            for iscsitarget in iscsitargets:
                if connector["initiator"] in iscsitarget["name"]:
                    target_id = iscsitarget["id"]
                    client_id = iscsitarget["clientid"]
                    return client_id, target_id
        return None, None

    def _create_iscsi_host(self, host_name, initiator, fss_hosts):
        client_id = ''
        target_id = ''
        client_info = self.create_iscsi_client(host_name, initiator)
        if client_info and client_info['rc'] == 0:
            client_id = client_info['id']

        target_info = self.create_iscsitarget(client_id, initiator, fss_hosts)
        if target_info['rc'] == 0:
            target_id = target_info['id']
        return client_id, target_id

    def _get_fc_client_initiators(self, connector):
        fc_initiators_assigned = []
        fc_available_initiator = []
        fc_initiators_info = self.list_fc_client_initiators()
        if 'data' not in fc_initiators_info:
            raise ValueError(_('No data information in return info.'))

        if fc_initiators_info['data']:
            fc_initiators = fc_initiators_info['data']
            for fc_initiator in fc_initiators:
                if fc_initiator['wwpn'] in connector['wwpns']:
                    fc_available_initiator.append(str(fc_initiator['wwpn']))
                    fc_initiators_assigned.append(dict(
                        wwpn=str(fc_initiator['wwpn']),
                        assigned=fc_initiator['assigned']))
        return fc_available_initiator, fc_initiators_assigned

    def fc_initialize_connection(self, volume, connector, fss_hosts):
        """Connect the host and volume; return dict describing connection."""
        vid = 0
        fc_target_info = {}
        free_fc_initiator = None

        volume_name = self._get_fss_volume_name(volume)
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        if not vid:
            msg = (_('Can not find cinder volume - %s.') % volume_name)
            raise exception.VolumeBackendAPIException(msg)

        available_initiator, fc_initiators_info = (
            self._get_fc_client_initiators(connector))

        if fc_initiators_info is None:
            msg = _('No FC initiator can be added to host.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for fc_initiator in fc_initiators_info:
            value = fc_initiator['assigned']
            if len(value) == 0:
                free_fc_initiator = fc_initiator['wwpn']

        if free_fc_initiator is None:
            msg = _('No free FC initiator can be assigned to host.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        initiator = connector["initiator"]
        host_name = GROUP_PREFIX + '%s-' % connector["host"]

        initiator_name = initiator.split(':')
        idx = len(initiator_name) - 1
        client_host_name = host_name + initiator_name[
            idx] + '_FC-wwpn-' + free_fc_initiator

        client_id = self.create_fc_client(client_host_name, free_fc_initiator)

        try:
            self.assign_fc_vdev(client_id, vid)
            time.sleep(3)
        except FSSHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 2415984845 and "XML_ERROR_CLIENT_EXIST"
                                               in err.text):
                    ctxt.reraise = False
                LOG.warning('Assign volume failed with message: %(msg)s.',
                            {"msg": err.reason})
        finally:
            lun = self.FSS._get_fc_client_info(client_id, vid)

            fc_target_info['lun'] = lun
            fc_target_info['available_initiator'] = available_initiator

        if not fc_target_info:
            msg = _('Failed to get iSCSI target info for the LUN: %s.')
            raise exception.VolumeBackendAPIException(data=msg % volume_name)
        return fc_target_info

    def fc_terminate_connection(self, volume, connector):
        client_id = 0
        volume_name = self._get_fss_volume_name(volume)
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        output = self.list_volume_info(vid)
        if 'data' not in output:
            msg = _('No vdev information in given data')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'clients' not in output['data']:
            msg = _('No clients in vdev information.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        client_info = output['data']['clients']
        for fcclients in client_info:
            client_id = int(fcclients['id'])

        if client_id == 0:
            msg = _(
                'Can not find client id. The connection target name is %s.')
            raise exception.VolumeBackendAPIException(
                data=msg % connector["initiator"])
        try:
            self.unassign_vdev(client_id, vid)
        except FSSHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 2415984988 and
                        "XML_ERROR_VIRTUAL_DEV_NOT_ASSIGNED_TO_iSCSI_TARGET"
                        in err.text):
                    ctxt.reraise = False
                LOG.warning('Disconnection failed with message: %(msg)s.',
                            {"msg": err.reason})
        return client_id

    def initialize_connection_iscsi(self, volume, connector, fss_hosts):
        """Connect the host and volume; return dict describing connection."""
        vid = 0
        iscsi_target_info = {}
        self._check_iscsi_option()
        client_id, target_id = self._get_iscsi_host(connector)

        if target_id is None:
            initiator = connector["initiator"]
            host_name = GROUP_PREFIX + '%s-' % connector["host"]

            initiator_info = initiator.split(':')
            idx = len(initiator_info) - 1
            client_host_name = host_name + initiator_info[idx]

            client_id, target_id = self._create_iscsi_host(client_host_name,
                                                           initiator,
                                                           fss_hosts)
        volume_name = self._get_fss_volume_name(volume)
        try:
            vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
            if not vid:
                msg = (_('Can not find cinder volume - %(volumeName)s.') %
                       {"volumeName": volume_name})
                raise exception.VolumeBackendAPIException(msg)

            self.assign_iscsi_vdev(client_id, target_id, vid)
            time.sleep(3)
        except FSSHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 2415984989 and
                        "XML_ERROR_VIRTUAL_DEV_ASSIGNED_TO_iSCSI_TARGET" in
                        err.text):
                    ctxt.reraise = False
                LOG.warning("Assign volume failed with message: %(msg)s.",
                            {"msg": err.reason})
        finally:
            (lun, target_name) = self.FSS._get_iscsi_target_info(client_id,
                                                                 vid)
            iscsi_target_info['lun'] = lun
            iscsi_target_info['iqn'] = target_name

        if not iscsi_target_info:
            msg = _('Failed to get iSCSI target info for the LUN: %s')
            raise exception.VolumeBackendAPIException(data=msg % volume_name)
        return iscsi_target_info

    def terminate_connection_iscsi(self, volume, connector):
        volume_name = self._get_fss_volume_name(volume)
        vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
        client_id, target_id = self._get_iscsi_host(connector)
        if not client_id:
            msg = _('Can not find client id. The connection target name '
                    'is %s.')
            raise exception.VolumeBackendAPIException(
                data=msg % connector["initiator"])
        try:
            self.unassign_vdev(client_id, vid)
        except FSSHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                if (err.code == 2415984988 and
                        "XML_ERROR_VIRTUAL_DEV_NOT_ASSIGNED_TO_iSCSI_TARGET"
                        in err.text):
                    ctxt.reraise = False
                LOG.warning("Disconnection failed with message: %(msg)s.",
                            {"msg": err.reason})
        finally:
            is_empty = self.FSS._check_host_mapping_status(client_id,
                                                           target_id)

            if is_empty:
                self.FSS.delete_iscsi_target(target_id)
                self.FSS.delete_client(client_id)

    def _get_existing_volume_ref_vid(self, existing_ref):
        if 'source-id' in existing_ref:
            vid = existing_ref['source-id']
        else:
            reason = _("FSSISCSIDriver manage_existing requires vid to "
                       "identify an existing volume.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        vdev_info = self.list_volume_info(vid)
        if not vdev_info:
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=_("Unable to find volume with FSS vid =%s.") % vid)

        if 'data' not in vdev_info:
            msg = _('No vdev information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'sizemb' not in vdev_info['data']:
            msg = _('No vdev sizemb in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        return vdev_info['data']['sizemb']

    def _manage_existing_volume(self, vid, volume):
        new_vol_name = self._get_fss_volume_name(volume)
        try:
            self.rename_vdev(vid, new_vol_name)
        except FSSHTTPError as err:
            with excutils.save_and_reraise_exception() as ctxt:
                ctxt.reraise = False
            LOG.warning("Volume manage_existing_volume was unable "
                        "to rename the volume, error message: %s.",
                        err.reason)

    def unmanage(self, volume):
        volume_name = self._get_fss_volume_name(volume)
        unmanaged_vol_name = volume_name + "-unmanaged"
        try:
            vid = self._get_fss_vid_from_name(volume_name, FSS_SINGLE_TYPE)
            self.rename_vdev(vid, unmanaged_vol_name)
        except FSSHTTPError as err:
            LOG.warning("Volume unmanage was unable to rename the volume,"
                        " error message: %(msg)s.", {"msg": err.reason})


class FSSRestCommon(object):
    def __init__(self, config):
        self.hostip = config.san_ip
        self.username = config.san_login
        self.password = config.san_password
        self.session_id = None
        self.fss_debug = config.fss_debug

    def _fss_request(self, method, path, data=None):
        json_data = None
        url = "http://%(ip)s/%(product)s/%(path)s" % {
            "ip": self.hostip, "product": PRODUCT_NAME, "path": path}
        headers = {"Content-Type": "application/json"}
        if self.session_id is not None:
            cookie = dict(
                Cookie=SESSION_COOKIE_NAME + '=' + self.session_id
            )
            headers.update(cookie)

        if data is not None:
            request_body = json.dumps(data).encode("utf-8")
        else:
            request_body = None

        connection = http_client.HTTPConnection(self.hostip, 80, timeout=60)

        if self.fss_debug:
            LOG.info("[FSS_RESTAPI]====%(method)s@url=%(url)s ===="
                     "@request_body=%(body)s===",
                     {"method": method,
                      "url": url,
                      "body": request_body})

        attempt = 1
        while True:
            connection.request(method, url, request_body, headers)
            response = connection.getresponse()
            response_body = response.read()
            if response_body:
                try:
                    data = json.loads(response_body)
                    json_data = json.dumps(data)
                    json_data = json.loads(json_data.decode('utf8'))
                except ValueError:
                    pass

            if self.fss_debug:
                LOG.info("[FSS_RESTAPI]==@json_data: %s ==", json_data)

            if response.status == 200:
                return json_data
            elif response.status == 404:
                msg = (_('FSS REST API return failed, method=%(method)s, '
                         'uri=%(url)s, response=%(response)s') % {
                       "method": method,
                       "url": url,
                       "response": response_body})
                raise exception.VolumeBackendAPIException(msg)
            else:
                err_code = json_data['rc']
                if (attempt > RETRY_CNT) or (str(err_code) not in RETRY_LIST):
                    err_target = ("method=%(method)s, url=%(url)s, "
                                  "response=%(response)s" %
                                  {"method": method, "url": url,
                                   "response": response_body})
                    err_response = self.get_fss_error_code(err_code)
                    err = dict(
                        code=err_code,
                        text=err_response['key'],
                        reason=err_response['message']
                    )
                    raise FSSHTTPError(err_target, err)
                attempt += 1
                LOG.warning("Retry with rc: %s.", err_code)
                self._random_sleep(RETRY_INTERVAL)
                if err_code == 107:
                    self.fss_login()

    def _random_sleep(self, interval=60):
        nsleep = random.randint(10, interval * 10)
        value = round(float(nsleep) / 10, 2)
        time.sleep(value)

    #
    # REST API session management methods
    #
    def fss_login(self):
        url = '%s/%s' % (FSS_AUTH, FSS_LOGIN)
        params = dict(
            username=self.username,
            password=self.password,
            server=self.hostip
        )
        data = self._fss_request(POST, url, params)
        if 'id' in data:
            self.session_id = data['id']
        return self.session_id

    #
    # Physical Adapters management methods
    #

    def list_physicaladapter_info(self, adapter_id=None):
        url = '%s/%s' % (FSS_PHYSICALRESOURCE, FSS_PHYSICALADAPTER)
        if adapter_id is not None:
            url = '%s/%s/%s' % (FSS_PHYSICALRESOURCE,
                                FSS_PHYSICALADAPTER, adapter_id)
        return self._fss_request(GET, url)

    def list_fc_target_wwpn(self):
        url = '%s/%s/%s' % (FSS_PHYSICALRESOURCE, FSS_PHYSICALADAPTER,
                            FSS_FC_TGT_WWPN)
        tgt_wwpn = []
        output = self._fss_request(GET, url)
        if output['data']:
            tgt_wwpns = output['data']
            for tgt_alias_wwpn in tgt_wwpns:
                tgt_wwpn.append(
                    str(tgt_alias_wwpn['aliaswwpn'].replace('-', '')))
        return tgt_wwpn

    def list_fc_client_initiators(self):
        url = '%s/%s/%s' % (FSS_PHYSICALRESOURCE, FSS_PHYSICALADAPTER,
                            FSS_FCCLIENTINITIATORS)
        return self._fss_request(GET, url)

    #
    # storage pool management methods
    #

    def list_pool_info(self, pool_id=None):
        url = '%s/%s' % (FSS_PHYSICALRESOURCE, FSS_STORAGE_POOL)
        if pool_id is not None:
            url = '%s/%s/%s' % (FSS_PHYSICALRESOURCE,
                                FSS_STORAGE_POOL, pool_id)
        return self._fss_request(GET, url)

    #
    # Volume and snapshot management methods
    #

    def create_vdev(self, params):
        metadata = {}
        url = '%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN)
        output = self._fss_request(POST, url, params)
        if output:
            if output['rc'] == 0:
                metadata['FSS-vid'] = output['id']
        return metadata

    def _check_mirror_sync_finished(self, vid, timeout):
        starttime = time.time()
        while True:
            self._random_sleep()
            if time.time() > starttime + timeout:
                msg = (_('FSS get mirror sync timeout on vid: %s ') % vid)
                raise exception.VolumeBackendAPIException(data=msg)
            elif self._check_mirror_sync_status(vid):
                break

    def delete_vdev(self, vid):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN, vid)
        return self._fss_request(DELETE, url, dict(force=True))

    def extend_vdev(self, vid, params):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN, vid)
        return self._fss_request(PUT, url, params)

    def rename_vdev(self, vid, params):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN, vid)
        return vid, self._fss_request(PUT, url, params)

    def list_fss_volume_info(self, vid=None):
        url = '%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN)
        if vid is not None:
            url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SAN, vid)
        return self._fss_request(GET, url)

    def _get_fss_vid_from_name(self, volume_name, fss_type=None):
        vid = []
        output = self.list_fss_volume_info()
        try:
            if "virtualdevices" in output['data']:
                for item in output['data']['virtualdevices']:
                    if item['name'] in volume_name:
                        vid.append(item['id'])
        except Exception:
            msg = (_('Can not find cinder volume - %s') % volume_name)
            raise exception.VolumeBackendAPIException(msg)

        if fss_type is not None and fss_type == FSS_SINGLE_TYPE:
            vid = ''.join(str(x) for x in vid)
        return vid

    def _check_if_snapshot_tm_exist(self, vid):
        snapshotenabled = False
        timemarkenabled = False
        sizemb = 0
        output = self.list_fss_volume_info(vid)
        if "snapshotenabled" in output['data']:
            snapshotenabled = output['data']['snapshotenabled']
        if "timemarkenabled" in output['data']:
            timemarkenabled = output['data']['timemarkenabled']
        if "sizemb" in output['data']:
            sizemb = output['data']['sizemb']
        return (snapshotenabled, timemarkenabled, sizemb)

    def create_vdev_snapshot(self, params):
        url = '%s/%s/%s' % (FSS_BATCH, FSS_LOGICALRESOURCE,
                            FSS_SNAPSHOT_RESOURCE)
        return self._fss_request(POST, url, params)

    def create_timemark_policy(self, vid, **kwargs):
        url = '%s/%s/%s' % (FSS_BATCH, FSS_LOGICALRESOURCE, FSS_TIMEMARKPOLICY)
        params = dict(
            idlist=[vid],
            automatic=dict(enabled=False),
            maxtimemarkcount=MAXSNAPSHOTS,
            retentionpolicy=dict(mode='all'),
        )
        if kwargs.get('storagepoolid'):
            params.update(kwargs)
        return self._fss_request(POST, url, params)

    def create_timemark(self, vid, snap_name):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_TIMEMARK, vid)
        params = dict(
            comment=snap_name,
            priority='medium',
            snapshotnotification=False
        )
        return self._fss_request(POST, url, params)

    def get_timemark(self, vid):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_TIMEMARK, vid)
        return self._fss_request(GET, url)

    def delete_timemark(self, timestamp):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_TIMEMARK, timestamp)
        params = dict(
            deleteallbefore=False
        )
        return self._fss_request(DELETE, url, params)

    def delete_timemark_policy(self, vid):
        url = '%s/%s/%s' % (FSS_BATCH, FSS_LOGICALRESOURCE, FSS_TIMEMARKPOLICY)
        params = dict(
            idlist=[vid]
        )
        return self._fss_request(DELETE, url, params)

    def delete_vdev_snapshot(self, vid):
        url = '%s/%s/%s' % (FSS_BATCH, FSS_LOGICALRESOURCE,
                            FSS_SNAPSHOT_RESOURCE)
        params = dict(
            idlist=[vid]
        )
        return self._fss_request(DELETE, url, params)

    def copy_timemark(self, timestamp, **kwargs):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_TIMEMARK, timestamp)
        params = dict(
            action='copy',
            includetimeviewdata=False
        )
        params.update(kwargs)
        return self._fss_request(PUT, url, params)

    def get_timemark_copy_status(self, vid):
        url = '%s/%s/%s?type=operationstatus' % (
            FSS_LOGICALRESOURCE, FSS_TIMEMARK, vid)
        return self._fss_request(GET, url)

    def _check_tm_copy_status(self, vid):
        finished = False
        output = self.get_timemark_copy_status(vid)
        if output['timemarkoperationstatus']:
            timemark_status = output['timemarkoperationstatus']
            if timemark_status['operation'] == "copy":
                if timemark_status['status'] == 'completed':
                    finished = True
        return finished

    def _check_tm_copy_finished(self, vid, timeout):
        finished = False
        starttime = time.time()
        while True:
            self._random_sleep()
            if time.time() > starttime + timeout:
                msg = (_('FSS get timemark copy timeout on vid: %s') % vid)
                raise exception.VolumeBackendAPIException(data=msg)
            elif self._check_tm_copy_status(vid):
                finished = True
                return finished

    #
    # TimeView methods
    #

    def create_timeview(self, tv_vid, params):
        vid = ''
        volume_metadata = {}
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_TIMEVIEW, tv_vid)
        output = self._fss_request(POST, url, params)
        if output and output['rc'] == 0:
            if output['copyid'] == -1:
                vid = output['id']
            else:
                vid = output['copyid']
        volume_metadata['FSS-vid'] = vid
        return volume_metadata

    #
    # Mirror methods
    #

    def create_mirror(self, vid, pool_id):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_MIRROR, vid)
        params = dict(
            category='virtual',
            selectioncriteria='anydrive',
            mirrortarget="virtual"
        )
        params.update(pool_id)
        return self._fss_request(POST, url, params)

    def get_mirror_sync_status(self, vid):
        url = '%s/%s/%s?type=syncstatus' % (
            FSS_LOGICALRESOURCE, FSS_MIRROR, vid)
        return self._fss_request(GET, url)

    def _check_mirror_sync_status(self, vid):
        finished = False
        output = self.get_mirror_sync_status(vid)
        if output['mirrorsyncstatus']:
            mirrorsyncstatus = output['mirrorsyncstatus']
            if mirrorsyncstatus['status'] == "insync":
                if mirrorsyncstatus['percentage'] == 0:
                    finished = True
        return finished

    def _set_mirror(self, vid, **kwargs):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_MIRROR, vid)
        return self._fss_request(PUT, url, kwargs)

    def sync_mirror(self, vid):
        return self._set_mirror(vid, action='sync')

    def promote_mirror(self, vid, new_volume_name):
        return self._set_mirror(vid, action='promote', name=new_volume_name)

    #
    # Host management methods
    #

    def get_server_options(self):
        url = '%s/%s' % (FSS_SERVER, FSS_OPTIONS)
        return self._fss_request(GET, url)

    def set_server_options(self, action):
        url = '%s/%s' % (FSS_SERVER, FSS_OPTIONS)
        params = dict(
            action=action,
            enabled=True
        )
        return self._fss_request(PUT, url, params)

    def get_server_name(self):
        url = '%s/%s' % (FSS_SERVER, FSS_OPTIONS)
        return self._fss_request(GET, url)

    #
    # SAN Client management methods
    #

    def list_client_initiators(self):
        url = '%s/%s/%s' % (FSS_CLIENT, FSS_SANCLIENT,
                            FSS_ISCSI_CLIENT_INITIATORS)
        return self._fss_request(GET, url)

    def get_default_portal(self):
        url = '%s/%s/%s' % (FSS_SERVER, FSS_OPTIONS, FSS_PORTAL)
        return self._fss_request(GET, url)

    def create_client(self, params):
        url = '%s/%s' % (FSS_CLIENT, FSS_SANCLIENT)
        return self._fss_request(POST, url, params)

    def list_sanclient_info(self, client_id=None):
        url = '%s/%s' % (FSS_CLIENT, FSS_SANCLIENT)
        if client_id is not None:
            url = '%s/%s/%s' % (FSS_CLIENT, FSS_SANCLIENT,
                                client_id)
        return self._fss_request(GET, url)

    def assign_vdev(self, client_id, params):
        url = '%s/%s/%s' % (FSS_CLIENT, FSS_SANCLIENT, client_id)
        return self._fss_request(PUT, url, params)

    def unassign_vdev(self, client_id, params):
        url = '%s/%s/%s' % (FSS_CLIENT, FSS_SANCLIENT, client_id)
        return self._fss_request(PUT, url, params)

    def _get_iscsi_target_info(self, client_id, vid):
        lun = 0
        target_name = None
        output = self.list_sanclient_info(client_id)

        if 'data' not in output:
            msg = _('No target information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'iscsidevices' not in output['data']:
            msg = _('No iscsidevices information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for iscsidevices in output['data']['iscsidevices']:
            if int(vid) == int(iscsidevices['id']):
                lun = iscsidevices['lun']
                iscsitarget_info = iscsidevices['iscsitarget']
                for key, value in iscsitarget_info.items():
                    if key == 'name':
                        target_name = value

        return lun, target_name

    def _check_host_mapping_status(self, client_id, target_id):
        is_empty = False
        hosting_cnt = 0
        output = self.list_sanclient_info(client_id)
        if 'data' not in output:
            msg = _('No target in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'iscsidevices' not in output['data']:
            msg = _('No iscsidevices information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        if len(output['data']['iscsidevices']) == 0:
            is_empty = True
        else:
            for iscsidevices in output['data']['iscsidevices']:
                iscsitarget_info = iscsidevices['iscsitarget']
                for key, value in iscsitarget_info.items():
                    if key == 'id' and target_id == value:
                        hosting_cnt += 1

            if hosting_cnt == 0:
                is_empty = True
        return is_empty

    def list_iscsi_target_info(self, target_id=None):
        url = '%s/%s' % (FSS_CLIENT, FSS_ISCSI_TARGET)
        if target_id is not None:
            url = '%s/%s/%s' % (FSS_CLIENT, FSS_ISCSI_TARGET,
                                target_id)
        return self._fss_request(GET, url)

    def _get_iscsi_target_id(self, initiator_iqn):
        target_id = ''
        client_id = ''
        output = self.list_iscsi_target_info()

        if 'data' not in output:
            msg = _('No target in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'iscsitargets' not in output['data']:
            msg = _('No iscsitargets for target.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for targets in output['data']['iscsitargets']:
            if 'name' in targets:
                if initiator_iqn in targets['name']:
                    target_id = str(targets['id'])
                    client_id = str(targets['clientid'])
                    break
        return target_id, client_id

    def create_iscsitarget(self, params):
        url = '%s/%s' % (FSS_CLIENT, FSS_ISCSI_TARGET)
        return self._fss_request(POST, url, params)

    def delete_iscsi_target(self, target_id):
        url = '%s/%s/%s' % (FSS_CLIENT, FSS_ISCSI_TARGET, target_id)
        params = dict(
            force=True
        )
        return self._fss_request(DELETE, url, params)

    def delete_client(self, client_id):
        url = '%s/%s/%s' % (FSS_CLIENT, FSS_SANCLIENT, client_id)
        return self._fss_request(DELETE, url)

    def _get_fc_client_info(self, client_id, vid):
        lun = 0
        output = self.list_sanclient_info(client_id)
        if 'data' not in output:
            msg = _('No target information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        if 'fcdevices' not in output['data']:
            msg = _('No fcdevices information in given data.')
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        for fcdevices in output['data']['fcdevices']:
            if int(vid) == int(fcdevices['id']):
                lun = fcdevices['lun']

        return lun

    #
    # Group related methods
    #

    def create_group(self, params):
        url = '%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP)
        return self._fss_request(POST, url, params)

    def list_group_info(self, gid=None):
        if gid is not None:
            url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP, gid)
        else:
            url = '%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP)
        return self._fss_request(GET, url)

    def set_group(self, gid, join_params=None, leave_params=None):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP, gid)
        if join_params:
            self._fss_request(PUT, url, join_params)
        if leave_params:
            self._fss_request(PUT, url, leave_params)

    def create_group_timemark_policy(self, gid, params):
        url = '%s/%s/%s/%s' % (FSS_LOGICALRESOURCE,
                               FSS_SNAPSHOT_GROUP, FSS_TIMEMARKPOLICY, gid)
        return self._fss_request(POST, url, params)

    def _check_if_group_tm_enabled(self, gid):
        timemarkenabled = False
        output = self.list_group_info(gid)
        if "timemarkenabled" in output['data']:
            timemarkenabled = output['data']['timemarkenabled']
        return timemarkenabled

    def create_group_timemark(self, gid, params):
        url = '%s/%s/%s/%s' % (FSS_LOGICALRESOURCE,
                               FSS_SNAPSHOT_GROUP, FSS_TIMEMARK, gid)
        return self._fss_request(POST, url, params)

    def get_group_timemark(self, gid):
        url = '%s/%s/%s/%s' % (FSS_LOGICALRESOURCE,
                               FSS_SNAPSHOT_GROUP, FSS_TIMEMARK, gid)
        return self._fss_request(GET, url)

    def delete_group_timemark(self, timestamp, params):
        url = '%s/%s/%s/%s' % (FSS_LOGICALRESOURCE,
                               FSS_SNAPSHOT_GROUP, FSS_TIMEMARK, timestamp)
        return self._fss_request(DELETE, url, params)

    def delete_group_timemark_policy(self, gid):
        url = '%s/%s/%s/%s' % (FSS_LOGICALRESOURCE,
                               FSS_SNAPSHOT_GROUP, FSS_TIMEMARKPOLICY, gid)
        return self._fss_request(DELETE, url)

    def delete_snapshot_group(self, gid):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP, gid)
        return self._fss_request(DELETE, url)

    def destroy_group(self, gid):
        url = '%s/%s/%s' % (FSS_LOGICALRESOURCE, FSS_SNAPSHOT_GROUP, gid)
        return self._fss_request(DELETE, url)

    def get_fss_error_code(self, err_id):
        try:
            url = '%s/%s/%s' % (FSS_SERVER, FSS_RETURN_CODE, err_id)
            output = self._fss_request(GET, url)
            if output['rc'] == 0:
                return output
        except Exception:
            msg = (_('Can not find this error code:%s.') % err_id)
            raise exception.APIException(reason=msg)


class FSSHTTPError(Exception):

    def __init__(self, target, response):
        super(FSSHTTPError, self).__init__()
        self.target = target
        self.code = response['code']
        self.text = response['text']
        self.reason = response['reason']

    def __str__(self):
        msg = ("FSSHTTPError code {0} returned by REST at {1}: {2}\n{3}")
        return msg.format(self.code, self.target,
                          self.reason, self.text)
