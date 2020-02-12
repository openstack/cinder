# Copyright (c) 2018 Dell Inc. or its subsidiaries.
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
Driver for Dell EMC XtremIO Storage.
supported XtremIO version 2.4 and up

.. code-block:: none

  1.0.0 - initial release
  1.0.1 - enable volume extend
  1.0.2 - added FC support, improved error handling
  1.0.3 - update logging level, add translation
  1.0.4 - support for FC zones
  1.0.5 - add support for XtremIO 4.0
  1.0.6 - add support for iSCSI multipath, CA validation, consistency groups,
          R/O snapshots, CHAP discovery authentication
  1.0.7 - cache glance images on the array
  1.0.8 - support for volume retype, CG fixes
  1.0.9 - performance improvements, support force detach, support for X2
  1.0.10 - option to clean unused IGs
  1.0.11 - add support for multiattach
"""

import json
import math
import random
import requests
import string

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import strutils
from oslo_utils import units
import six
from six.moves import http_client

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume import utils as vutils
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF
XTREMIO_OPTS = [
    cfg.StrOpt('xtremio_cluster_name',
               default='',
               help='XMS cluster id in multi-cluster environment'),
    cfg.IntOpt('xtremio_array_busy_retry_count',
               default=5,
               help='Number of retries in case array is busy'),
    cfg.IntOpt('xtremio_array_busy_retry_interval',
               default=5,
               help='Interval between retries in case array is busy'),
    cfg.IntOpt('xtremio_volumes_per_glance_cache',
               default=100,
               help='Number of volumes created from each cached glance image'),
    cfg.BoolOpt('xtremio_clean_unused_ig',
                default=False,
                help='Should the driver remove initiator groups with no '
                     'volumes after the last connection was terminated. '
                     'Since the behavior till now was to leave '
                     'the IG be, we default to False (not deleting IGs '
                     'without connected volumes); setting this parameter '
                     'to True will remove any IG after terminating its '
                     'connection to the last volume.')]

CONF.register_opts(XTREMIO_OPTS, group=configuration.SHARED_CONF_GROUP)

RANDOM = random.Random()
OBJ_NOT_FOUND_ERR = 'obj_not_found'
VOL_NOT_UNIQUE_ERR = 'vol_obj_name_not_unique'
VOL_OBJ_NOT_FOUND_ERR = 'vol_obj_not_found'
ALREADY_MAPPED_ERR = 'already_mapped'
SYSTEM_BUSY = 'system_is_busy'
TOO_MANY_OBJECTS = 'too_many_objs'
TOO_MANY_SNAPSHOTS_PER_VOL = 'too_many_snapshots_per_vol'


XTREMIO_OID_NAME = 1
XTREMIO_OID_INDEX = 2


class XtremIOClient(object):
    def __init__(self, configuration, cluster_id):
        self.configuration = configuration
        self.cluster_id = cluster_id
        self.verify = (self.configuration.
                       safe_get('driver_ssl_cert_verify') or False)
        if self.verify:
            verify_path = (self.configuration.
                           safe_get('driver_ssl_cert_path') or None)
            if verify_path:
                self.verify = verify_path

    def get_base_url(self, ver):
        if ver == 'v1':
            return 'https://%s/api/json/types' % self.configuration.san_ip
        elif ver == 'v2':
            return 'https://%s/api/json/v2/types' % self.configuration.san_ip

    def req(self, object_type='volumes', method='GET', data=None,
            name=None, idx=None, ver='v1'):
        @utils.retry(exception.XtremIOArrayBusy,
                     self.configuration.xtremio_array_busy_retry_count,
                     self.configuration.xtremio_array_busy_retry_interval, 1)
        def _do_req(object_type, method, data, name, idx, ver):
            if not data:
                data = {}
            if name and idx:
                msg = _("can't handle both name and index in req")
                LOG.error(msg)
                raise exception.VolumeDriverException(message=msg)

            url = '%s/%s' % (self.get_base_url(ver), object_type)
            params = {}
            key = None
            if name:
                params['name'] = name
                key = name
            elif idx:
                url = '%s/%d' % (url, idx)
                key = str(idx)
            if method in ('GET', 'DELETE'):
                params.update(data)
                self.update_url(params, self.cluster_id)
            if method != 'GET':
                self.update_data(data, self.cluster_id)
                # data may include chap password
                LOG.debug('data: %s', strutils.mask_password(data))
            LOG.debug('%(type)s %(url)s', {'type': method, 'url': url})
            try:
                response = requests.request(
                    method, url, params=params, data=json.dumps(data),
                    verify=self.verify, auth=(self.configuration.san_login,
                                              self.configuration.san_password))
            except requests.exceptions.RequestException as exc:
                msg = (_('Exception: %s') % six.text_type(exc))
                raise exception.VolumeDriverException(message=msg)

            if (http_client.OK <= response.status_code <
                    http_client.MULTIPLE_CHOICES):
                if method in ('GET', 'POST'):
                    return response.json()
                else:
                    return ''

            self.handle_errors(response, key, object_type)
        return _do_req(object_type, method, data, name, idx, ver)

    def handle_errors(self, response, key, object_type):
        if response.status_code == http_client.BAD_REQUEST:
            error = response.json()
            err_msg = error.get('message')
            if err_msg.endswith(OBJ_NOT_FOUND_ERR):
                LOG.warning("object %(key)s of "
                            "type %(typ)s not found, %(err_msg)s",
                            {'key': key, 'typ': object_type,
                             'err_msg': err_msg, })
                raise exception.NotFound()
            elif err_msg == VOL_NOT_UNIQUE_ERR:
                LOG.error("can't create 2 volumes with the same name, %s",
                          err_msg)
                msg = _('Volume by this name already exists')
                raise exception.VolumeBackendAPIException(data=msg)
            elif err_msg == VOL_OBJ_NOT_FOUND_ERR:
                LOG.error("Can't find volume to map %(key)s, %(msg)s",
                          {'key': key, 'msg': err_msg, })
                raise exception.VolumeNotFound(volume_id=key)
            elif ALREADY_MAPPED_ERR in err_msg:
                raise exception.XtremIOAlreadyMappedError()
            elif err_msg == SYSTEM_BUSY:
                raise exception.XtremIOArrayBusy()
            elif err_msg in (TOO_MANY_OBJECTS, TOO_MANY_SNAPSHOTS_PER_VOL):
                raise exception.XtremIOSnapshotsLimitExceeded()
        msg = _('Bad response from XMS, %s') % response.text
        LOG.error(msg)
        raise exception.VolumeBackendAPIException(message=msg)

    def update_url(self, data, cluster_id):
        return

    def update_data(self, data, cluster_id):
        return

    def get_cluster(self):
        return self.req('clusters', idx=1)['content']

    def create_snapshot(self, src, dest, ro=False):
        """Create a snapshot of a volume on the array.

        XtreamIO array snapshots are also volumes.

        :src: name of the source volume to be cloned
        :dest: name for the new snapshot
        :ro: new snapshot type ro/regular. only applicable to Client4
        """
        raise NotImplementedError()

    def get_extra_capabilities(self):
        return {}

    def get_initiator(self, port_address):
        raise NotImplementedError()

    def add_vol_to_cg(self, vol_id, cg_id):
        pass

    def get_initiators_igs(self, port_addresses):
        ig_indexes = set()
        for port_address in port_addresses:
            initiator = self.get_initiator(port_address)
            ig_indexes.add(initiator['ig-id'][XTREMIO_OID_INDEX])

        return list(ig_indexes)

    def get_fc_up_ports(self):
        targets = [self.req('targets', name=target['name'])['content']
                   for target in self.req('targets')['targets']]
        return [target for target in targets
                if target['port-type'] == 'fc' and
                target["port-state"] == 'up']


class XtremIOClient3(XtremIOClient):
    def __init__(self, configuration, cluster_id):
        super(XtremIOClient3, self).__init__(configuration, cluster_id)
        self._portals = []

    def find_lunmap(self, ig_name, vol_name):
        try:
            lun_mappings = self.req('lun-maps')['lun-maps']
        except exception.NotFound:
            raise (exception.VolumeDriverException
                   (_("can't find lun-map, ig:%(ig)s vol:%(vol)s") %
                    {'ig': ig_name, 'vol': vol_name}))

        for lm_link in lun_mappings:
            idx = lm_link['href'].split('/')[-1]
            # NOTE(geguileo): There can be races so mapped elements retrieved
            # in the listing may no longer exist.
            try:
                lm = self.req('lun-maps', idx=int(idx))['content']
            except exception.NotFound:
                continue
            if lm['ig-name'] == ig_name and lm['vol-name'] == vol_name:
                return lm

        return None

    def num_of_mapped_volumes(self, initiator):
        cnt = 0
        for lm_link in self.req('lun-maps')['lun-maps']:
            idx = lm_link['href'].split('/')[-1]
            # NOTE(geguileo): There can be races so mapped elements retrieved
            # in the listing may no longer exist.
            try:
                lm = self.req('lun-maps', idx=int(idx))['content']
            except exception.NotFound:
                continue
            if lm['ig-name'] == initiator:
                cnt += 1
        return cnt

    def get_iscsi_portals(self):
        if self._portals:
            return self._portals

        iscsi_portals = [t['name'] for t in self.req('iscsi-portals')
                         ['iscsi-portals']]
        for portal_name in iscsi_portals:
            try:
                self._portals.append(self.req('iscsi-portals',
                                              name=portal_name)['content'])
            except exception.NotFound:
                raise (exception.VolumeBackendAPIException
                       (data=_("iscsi portal, %s, not found") % portal_name))

        return self._portals

    def create_snapshot(self, src, dest, ro=False):
        data = {'snap-vol-name': dest, 'ancestor-vol-id': src}

        self.req('snapshots', 'POST', data)

    def get_initiator(self, port_address):
        try:
            return self.req('initiators', 'GET', name=port_address)['content']
        except exception.NotFound:
            pass


class XtremIOClient4(XtremIOClient):
    def __init__(self, configuration, cluster_id):
        super(XtremIOClient4, self).__init__(configuration, cluster_id)
        self._cluster_name = None

    def req(self, object_type='volumes', method='GET', data=None,
            name=None, idx=None, ver='v2'):
        return super(XtremIOClient4, self).req(object_type, method, data,
                                               name, idx, ver)

    def get_extra_capabilities(self):
        return {'consistencygroup_support': True}

    def find_lunmap(self, ig_name, vol_name):
        try:
            return (self.req('lun-maps',
                             data={'full': 1,
                                   'filter': ['vol-name:eq:%s' % vol_name,
                                              'ig-name:eq:%s' % ig_name]})
                    ['lun-maps'][0])
        except (KeyError, IndexError):
            raise exception.VolumeNotFound(volume_id=vol_name)

    def num_of_mapped_volumes(self, initiator):
        return len(self.req('lun-maps',
                            data={'filter': 'ig-name:eq:%s' % initiator})
                   ['lun-maps'])

    def update_url(self, data, cluster_id):
        if cluster_id:
            data['cluster-name'] = cluster_id

    def update_data(self, data, cluster_id):
        if cluster_id:
            data['cluster-id'] = cluster_id

    def get_iscsi_portals(self):
        return self.req('iscsi-portals',
                        data={'full': 1})['iscsi-portals']

    def get_cluster(self):
        if not self.cluster_id:
            self.cluster_id = self.req('clusters')['clusters'][0]['name']

        return self.req('clusters', name=self.cluster_id)['content']

    def create_snapshot(self, src, dest, ro=False):
        data = {'snapshot-set-name': dest, 'snap-suffix': dest,
                'volume-list': [src],
                'snapshot-type': 'readonly' if ro else 'regular'}

        res = self.req('snapshots', 'POST', data, ver='v2')
        typ, idx = res['links'][0]['href'].split('/')[-2:]

        # rename the snapshot
        data = {'name': dest}
        try:
            self.req(typ, 'PUT', data, idx=int(idx))
        except exception.VolumeBackendAPIException:
            # reverting
            LOG.error('Failed to rename the created snapshot, reverting.')
            self.req(typ, 'DELETE', idx=int(idx))
            raise

    def add_vol_to_cg(self, vol_id, cg_id):
        add_data = {'vol-id': vol_id, 'cg-id': cg_id}
        self.req('consistency-group-volumes', 'POST', add_data, ver='v2')

    def get_initiator(self, port_address):
        inits = self.req('initiators',
                         data={'filter': 'port-address:eq:' + port_address,
                               'full': 1})['initiators']
        if len(inits) == 1:
            return inits[0]
        else:
            pass

    def get_fc_up_ports(self):
        return self.req('targets',
                        data={'full': 1,
                              'filter': ['port-type:eq:fc',
                                         'port-state:eq:up'],
                              'prop': 'port-address'})["targets"]


class XtremIOClient42(XtremIOClient4):
    def get_initiators_igs(self, port_addresses):
        init_filter = ','.join('port-address:eq:{}'.format(port_address) for
                               port_address in port_addresses)
        initiators = self.req('initiators',
                              data={'filter': init_filter,
                                    'full': 1, 'prop': 'ig-id'})['initiators']
        return list(set(ig_id['ig-id'][XTREMIO_OID_INDEX]
                        for ig_id in initiators))


class XtremIOVolumeDriver(san.SanDriver):
    """Executes commands relating to Volumes."""

    VERSION = '1.0.11'

    # ThirdPartySystems wiki
    CI_WIKI_NAME = "EMC_XIO_CI"

    driver_name = 'XtremIO'
    MIN_XMS_VERSION = [3, 0, 0]

    def __init__(self, *args, **kwargs):
        super(XtremIOVolumeDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(XTREMIO_OPTS)
        self.protocol = None
        self.backend_name = (self.configuration.safe_get('volume_backend_name')
                             or self.driver_name)
        self.cluster_id = (self.configuration.safe_get('xtremio_cluster_name')
                           or '')
        self.provisioning_factor = vutils.get_max_over_subscription_ratio(
            self.configuration.max_over_subscription_ratio,
            supports_auto=False)

        self.clean_ig = (self.configuration.safe_get('xtremio_clean_unused_ig')
                         or False)
        self._stats = {}
        self.client = XtremIOClient3(self.configuration, self.cluster_id)

    @staticmethod
    def get_driver_options():
        return XTREMIO_OPTS

    def _obj_from_result(self, res):
        typ, idx = res['links'][0]['href'].split('/')[-2:]
        return self.client.req(typ, idx=int(idx))['content']

    def check_for_setup_error(self):
        try:
            name = self.client.req('clusters')['clusters'][0]['name']
            cluster = self.client.req('clusters', name=name)['content']
            version_text = cluster['sys-sw-version']
        except exception.NotFound:
            msg = _("XtremIO not initialized correctly, no clusters found")
            raise (exception.VolumeBackendAPIException
                   (data=msg))
        ver = [int(n) for n in version_text.split('-')[0].split('.')]
        if ver < self.MIN_XMS_VERSION:
            msg = (_('Invalid XtremIO version %(cur)s,'
                     ' version %(min)s or up is required') %
                   {'min': self.MIN_XMS_VERSION,
                    'cur': ver})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)
        else:
            LOG.info('XtremIO Cluster version %s', version_text)
        client_ver = '3'
        if ver[0] >= 4:
            # get XMS version
            xms = self.client.req('xms', idx=1)['content']
            xms_version = tuple([int(i) for i in
                                 xms['sw-version'].split('-')[0].split('.')])
            LOG.info('XtremIO XMS version %s', version_text)
            if xms_version >= (4, 2):
                self.client = XtremIOClient42(self.configuration,
                                              self.cluster_id)
                client_ver = '4.2'
            else:
                self.client = XtremIOClient4(self.configuration,
                                             self.cluster_id)
                client_ver = '4'
        LOG.info('Using XtremIO Client %s', client_ver)

    def create_volume(self, volume):
        """Creates a volume."""
        data = {'vol-name': volume['id'],
                'vol-size': str(volume['size']) + 'g'
                }
        self.client.req('volumes', 'POST', data)

        # Add the volume to a cg in case volume requested a cgid or group_id.
        # If both cg_id and group_id exists in a volume. group_id will take
        # place.

        consistency_group = volume.get('consistencygroup_id')

        # if cg_id and group_id are both exists, we gives priority to group_id.
        if volume.get('group_id'):
            consistency_group = volume.get('group_id')

        if consistency_group:
            self.client.add_vol_to_cg(volume['id'],
                                      consistency_group)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        if snapshot.get('cgsnapshot_id'):
            # get array snapshot id from CG snapshot
            snap_by_anc = self._get_snapset_ancestors(snapshot.cgsnapshot)
            snapshot_id = snap_by_anc[snapshot['volume_id']]
        else:
            snapshot_id = snapshot['id']

        try:
            self.client.create_snapshot(snapshot_id, volume['id'])
        except exception.XtremIOSnapshotsLimitExceeded as e:
            raise exception.CinderException(e.message)

        # extend the snapped volume if requested size is larger then original
        if volume['size'] > snapshot['volume_size']:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                LOG.error('failed to extend volume %s, '
                          'reverting volume from snapshot operation',
                          volume['id'])
                # remove the volume in case resize failed
                self.delete_volume(volume)
                raise

        # add new volume to consistency group
        if (volume.get('consistencygroup_id') and
                self.client is XtremIOClient4):
            self.client.add_vol_to_cg(volume['id'],
                                      snapshot['consistencygroup_id'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        vol = self.client.req('volumes', name=src_vref['id'])['content']
        ctxt = context.get_admin_context()
        cache = self.db.image_volume_cache_get_by_volume_id(ctxt,
                                                            src_vref['id'])
        limit = self.configuration.safe_get('xtremio_volumes_per_glance_cache')
        if cache and limit and limit > 0 and limit <= vol['num-of-dest-snaps']:
            raise exception.SnapshotLimitReached(set_limit=limit)
        try:
            self.client.create_snapshot(src_vref['id'], volume['id'])
        except exception.XtremIOSnapshotsLimitExceeded as e:
            raise exception.CinderException(e.message)

        # extend the snapped volume if requested size is larger then original
        if volume['size'] > src_vref['size']:
            try:
                self.extend_volume(volume, volume['size'])
            except Exception:
                LOG.error('failed to extend volume %s, '
                          'reverting clone operation', volume['id'])
                # remove the volume in case resize failed
                self.delete_volume(volume)
                raise

        if volume.get('consistencygroup_id') and self.client is XtremIOClient4:
            self.client.add_vol_to_cg(volume['id'],
                                      volume['consistencygroup_id'])

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            self.client.req('volumes', 'DELETE', name=volume.name_id)
        except exception.NotFound:
            LOG.info("volume %s doesn't exist", volume.name_id)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.client.create_snapshot(snapshot.volume_id, snapshot.id, True)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            self.client.req('volumes', 'DELETE', name=snapshot.id)
        except exception.NotFound:
            LOG.info("snapshot %s doesn't exist", snapshot.id)

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        # as the volume name is used to id the volume we need to rename it
        name_id = None
        provider_location = None
        current_name = new_volume['id']
        original_name = volume['id']
        try:
            data = {'name': original_name}
            self.client.req('volumes', 'PUT', data, name=current_name)
        except exception.VolumeBackendAPIException:
            LOG.error('Unable to rename the logical volume '
                      'for volume: %s', original_name)
            # If the rename fails, _name_id should be set to the new
            # volume id and provider_location should be set to the
            # one from the new volume as well.
            name_id = new_volume['_name_id'] or new_volume['id']
            provider_location = new_volume['provider_location']

        return {'_name_id': name_id, 'provider_location': provider_location}

    def _update_volume_stats(self):
        sys = self.client.get_cluster()
        physical_space = int(sys["ud-ssd-space"]) / units.Mi
        used_physical_space = int(sys["ud-ssd-space-in-use"]) / units.Mi
        free_physical = physical_space - used_physical_space
        actual_prov = int(sys["vol-size"]) / units.Mi
        self._stats = {'volume_backend_name': self.backend_name,
                       'vendor_name': 'Dell EMC',
                       'driver_version': self.VERSION,
                       'storage_protocol': self.protocol,
                       'total_capacity_gb': physical_space,
                       'free_capacity_gb': free_physical,
                       'provisioned_capacity_gb': actual_prov,
                       'max_over_subscription_ratio': self.provisioning_factor,
                       'thin_provisioning_support': True,
                       'thick_provisioning_support': False,
                       'reserved_percentage':
                       self.configuration.reserved_percentage,
                       'QoS_support': False,
                       'multiattach': True,
                       }
        self._stats.update(self.client.get_extra_capabilities())

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()
        return self._stats

    def manage_existing(self, volume, existing_ref, is_snapshot=False):
        """Manages an existing LV."""
        lv_name = existing_ref['source-name']
        # Attempt to locate the volume.
        try:
            vol_obj = self.client.req('volumes', name=lv_name)['content']
            if (
                is_snapshot and
                (not vol_obj['ancestor-vol-id'] or
                 vol_obj['ancestor-vol-id'][XTREMIO_OID_NAME] !=
                 volume.volume_id)):
                kwargs = {'existing_ref': lv_name,
                          'reason': 'Not a snapshot of vol %s' %
                          volume.volume_id}
                raise exception.ManageExistingInvalidReference(**kwargs)
        except exception.NotFound:
            kwargs = {'existing_ref': lv_name,
                      'reason': 'Specified logical %s does not exist.' %
                      'snapshot' if is_snapshot else 'volume'}
            raise exception.ManageExistingInvalidReference(**kwargs)

        # Attempt to rename the LV to match the OpenStack internal name.
        self.client.req('volumes', 'PUT', data={'vol-name': volume['id']},
                        idx=vol_obj['index'])

    def manage_existing_get_size(self, volume, existing_ref,
                                 is_snapshot=False):
        """Return size of an existing LV for manage_existing."""
        # Check that the reference is valid
        if 'source-name' not in existing_ref:
            reason = _('Reference must contain source-name element.')
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref, reason=reason)
        lv_name = existing_ref['source-name']
        # Attempt to locate the volume.
        try:
            vol_obj = self.client.req('volumes', name=lv_name)['content']
        except exception.NotFound:
            kwargs = {'existing_ref': lv_name,
                      'reason': 'Specified logical %s does not exist.' %
                      'snapshot' if is_snapshot else 'volume'}
            raise exception.ManageExistingInvalidReference(**kwargs)
        # LV size is returned in gigabytes.  Attempt to parse size as a float
        # and round up to the next integer.
        lv_size = int(math.ceil(float(vol_obj['vol-size']) / units.Mi))

        return lv_size

    def unmanage(self, volume, is_snapshot=False):
        """Removes the specified volume from Cinder management."""
        # trying to rename the volume to [cinder name]-unmanged
        try:
            self.client.req('volumes', 'PUT', name=volume['id'],
                            data={'vol-name': volume['name'] + '-unmanged'})
        except exception.NotFound:
            LOG.info("%(typ)s with the name %(name)s wasn't found, "
                     "can't unmanage",
                     {'typ': 'Snapshot' if is_snapshot else 'Volume',
                      'name': volume['id']})
            raise exception.VolumeNotFound(volume_id=volume['id'])

    def manage_existing_snapshot(self, snapshot, existing_ref):
        self.manage_existing(snapshot, existing_ref, True)

    def manage_existing_snapshot_get_size(self, snapshot, existing_ref):
        return self.manage_existing_get_size(snapshot, existing_ref, True)

    def unmanage_snapshot(self, snapshot):
        self.unmanage(snapshot, True)

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        data = {'vol-size': six.text_type(new_size) + 'g'}
        try:
            self.client.req('volumes', 'PUT', data, name=volume['id'])
        except exception.NotFound:
            msg = _("can't find the volume to extend")
            raise exception.VolumeDriverException(message=msg)

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        tg_index = '1'

        if not connector:
            vol = self.client.req('volumes', name=volume.id)['content']
            # foce detach, unmap all IGs from volume
            IG_OID = 0
            ig_indexes = [lun_map[IG_OID][XTREMIO_OID_INDEX] for
                          lun_map in vol['lun-mapping-list']]
            LOG.info('Force detach volume %(vol)s from luns %(luns)s.',
                     {'vol': vol['name'], 'luns': ig_indexes})
        else:
            host = connector['host']
            attachment_list = volume.volume_attachment
            LOG.debug("Volume attachment list: %(atl)s. "
                      "Attachment type: %(at)s",
                      {'atl': attachment_list, 'at': type(attachment_list)})
            try:
                att_list = attachment_list.objects
            except AttributeError:
                att_list = attachment_list
            if att_list is not None:
                host_list = [att.connector['host'] for att in att_list if
                             att is not None and att.connector is not None]
                current_host_occurances = host_list.count(host)
                if current_host_occurances > 1:
                    LOG.info("Volume is attached to multiple instances on "
                             "this host. Not removing the lun map.")
                    return
            vol = self.client.req('volumes', name=volume.id,
                                  data={'prop': 'index'})['content']
            ig_indexes = self._get_ig_indexes_from_initiators(connector)

        for ig_idx in ig_indexes:
            lm_name = '%s_%s_%s' % (six.text_type(vol['index']),
                                    six.text_type(ig_idx),
                                    tg_index)
            LOG.debug('Removing lun map %s.', lm_name)
            try:
                self.client.req('lun-maps', 'DELETE', name=lm_name)
            except exception.NotFound:
                LOG.warning("terminate_connection: lun map not found")

        if self.clean_ig:
            for idx in ig_indexes:
                try:
                    ig = self.client.req('initiator-groups', 'GET',
                                         {'prop': 'num-of-vols'},
                                         idx=idx)['content']
                    if ig['num-of-vols'] == 0:
                        self.client.req('initiator-groups', 'DELETE', idx=idx)
                except (exception.NotFound,
                        exception.VolumeBackendAPIException):
                    LOG.warning('Failed to clean IG %d without mappings', idx)

    def _get_password(self):
        return vutils.generate_password(
            length=12,
            symbolgroups=(string.ascii_uppercase + string.digits))

    def create_lun_map(self, volume, ig, lun_num=None):
        try:
            data = {'ig-id': ig, 'vol-id': volume['id']}
            if lun_num:
                data['lun'] = lun_num
            res = self.client.req('lun-maps', 'POST', data)

            lunmap = self._obj_from_result(res)
            LOG.info('Created lun-map:\n%s', lunmap)
        except exception.XtremIOAlreadyMappedError:
            LOG.info('Volume already mapped, retrieving %(ig)s, %(vol)s',
                     {'ig': ig, 'vol': volume['id']})
            lunmap = self.client.find_lunmap(ig, volume['id'])
        return lunmap

    def _get_ig_name(self, connector):
        raise NotImplementedError()

    def _get_ig_indexes_from_initiators(self, connector):
        initiator_names = self._get_initiator_names(connector)
        return self.client.get_initiators_igs(initiator_names)

    def _get_initiator_names(self, connector):
        raise NotImplementedError()

    def create_consistencygroup(self, context, group):
        """Creates a consistency group.

        :param context: the context
        :param group: the group object to be created
        :returns: dict -- modelUpdate = {'status': 'available'}
        :raises: VolumeBackendAPIException
        """
        create_data = {'consistency-group-name': group['id']}
        self.client.req('consistency-groups', 'POST', data=create_data,
                        ver='v2')
        return {'status': fields.ConsistencyGroupStatus.AVAILABLE}

    def delete_consistencygroup(self, context, group, volumes):
        """Deletes a consistency group."""
        self.client.req('consistency-groups', 'DELETE', name=group['id'],
                        ver='v2')

        volumes_model_update = []

        for volume in volumes:
            self.delete_volume(volume)

            update_item = {'id': volume['id'],
                           'status': 'deleted'}

            volumes_model_update.append(update_item)

        model_update = {'status': group['status']}

        return model_update, volumes_model_update

    def _get_snapset_ancestors(self, snapset_name):
        snapset = self.client.req('snapshot-sets',
                                  name=snapset_name)['content']
        volume_ids = [s[XTREMIO_OID_INDEX] for s in snapset['vol-list']]
        return {v['ancestor-vol-id'][XTREMIO_OID_NAME]: v['name'] for v
                in self.client.req('volumes',
                                   data={'full': 1,
                                         'props':
                                         'ancestor-vol-id'})['volumes']
                if v['index'] in volume_ids}

    def create_consistencygroup_from_src(self, context, group, volumes,
                                         cgsnapshot=None, snapshots=None,
                                         source_cg=None, source_vols=None):
        """Creates a consistencygroup from source.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be created.
        :param volumes: a list of volume dictionaries in the group.
        :param cgsnapshot: the dictionary of the cgsnapshot as source.
        :param snapshots: a list of snapshot dictionaries in the cgsnapshot.
        :param source_cg: the dictionary of a consistency group as source.
        :param source_vols: a list of volume dictionaries in the source_cg.
        :returns: model_update, volumes_model_update
        """
        if not (cgsnapshot and snapshots and not source_cg or
                source_cg and source_vols and not cgsnapshot):
            msg = _("create_consistencygroup_from_src only supports a "
                    "cgsnapshot source or a consistency group source. "
                    "Multiple sources cannot be used.")
            raise exception.InvalidInput(msg)

        if cgsnapshot:
            snap_name = self._get_cgsnap_name(cgsnapshot)
            snap_by_anc = self._get_snapset_ancestors(snap_name)
            for volume, snapshot in zip(volumes, snapshots):
                real_snap = snap_by_anc[snapshot['volume_id']]
                self.create_volume_from_snapshot(
                    volume,
                    {'id': real_snap,
                     'volume_size': snapshot['volume_size']})

        elif source_cg:
            data = {'consistency-group-id': source_cg['id'],
                    'snapshot-set-name': group['id']}
            self.client.req('snapshots', 'POST', data, ver='v2')
            snap_by_anc = self._get_snapset_ancestors(group['id'])
            for volume, src_vol in zip(volumes, source_vols):
                snap_vol_name = snap_by_anc[src_vol['id']]
                self.client.req('volumes', 'PUT', {'name': volume['id']},
                                name=snap_vol_name)

        create_data = {'consistency-group-name': group['id'],
                       'vol-list': [v['id'] for v in volumes]}
        self.client.req('consistency-groups', 'POST', data=create_data,
                        ver='v2')

        return None, None

    def update_consistencygroup(self, context, group,
                                add_volumes=None, remove_volumes=None):
        """Updates a consistency group.

        :param context: the context of the caller.
        :param group: the dictionary of the consistency group to be updated.
        :param add_volumes: a list of volume dictionaries to be added.
        :param remove_volumes: a list of volume dictionaries to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """
        add_volumes = add_volumes if add_volumes else []
        remove_volumes = remove_volumes if remove_volumes else []
        for vol in add_volumes:
            add_data = {'vol-id': vol['id'], 'cg-id': group['id']}
            self.client.req('consistency-group-volumes', 'POST', add_data,
                            ver='v2')
        for vol in remove_volumes:
            remove_data = {'vol-id': vol['id'], 'cg-id': group['id']}
            self.client.req('consistency-group-volumes', 'DELETE', remove_data,
                            name=group['id'], ver='v2')
        return None, None, None

    def _get_cgsnap_name(self, cgsnapshot):

        group_id = cgsnapshot.get('group_id')
        if group_id is None:
            group_id = cgsnapshot.get('consistencygroup_id')

        return '%(cg)s%(snap)s' % {'cg': group_id
                                   .replace('-', ''),
                                   'snap': cgsnapshot['id'].replace('-', '')}

    def create_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Creates a cgsnapshot."""

        group_id = cgsnapshot.get('group_id')
        if group_id is None:
            group_id = cgsnapshot.get('consistencygroup_id')

        data = {'consistency-group-id': group_id,
                'snapshot-set-name': self._get_cgsnap_name(cgsnapshot)}
        self.client.req('snapshots', 'POST', data, ver='v2')

        return None, None

    def delete_cgsnapshot(self, context, cgsnapshot, snapshots):
        """Deletes a cgsnapshot."""
        self.client.req('snapshot-sets', 'DELETE',
                        name=self._get_cgsnap_name(cgsnapshot), ver='v2')
        return None, None

    def create_group(self, context, group):
        """Creates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :returns: model_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.create_consistencygroup(context, group)

    def delete_group(self, context, group, volumes):
        """Deletes a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param volumes: a list of volume objects in the group.
        :returns: model_update, volumes_model_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.delete_consistencygroup(context, group, volumes)

    def update_group(self, context, group,
                     add_volumes=None, remove_volumes=None):
        """Updates a group.

        :param context: the context of the caller.
        :param group: the group object.
        :param add_volumes: a list of volume objects to be added.
        :param remove_volumes: a list of volume objects to be removed.
        :returns: model_update, add_volumes_update, remove_volumes_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.update_consistencygroup(context, group, add_volumes,
                                            remove_volumes)

    def create_group_from_src(self, context, group, volumes,
                              group_snapshot=None, snapshots=None,
                              source_group=None, source_vols=None):
        """Creates a group from source.

        :param context: the context of the caller.
        :param group: the Group object to be created.
        :param volumes: a list of Volume objects in the group.
        :param group_snapshot: the GroupSnapshot object as source.
        :param snapshots: a list of snapshot objects in group_snapshot.
        :param source_group: the Group object as source.
        :param source_vols: a list of volume objects in the source_group.
        :returns: model_update, volumes_model_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.create_consistencygroup_from_src(context, group, volumes,
                                                     group_snapshot, snapshots,
                                                     source_group, source_vols)

    def create_group_snapshot(self, context, group_snapshot, snapshots):
        """Creates a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be created.
        :param snapshots: a list of Snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.create_cgsnapshot(context, group_snapshot, snapshots)

    def delete_group_snapshot(self, context, group_snapshot, snapshots):
        """Deletes a group_snapshot.

        :param context: the context of the caller.
        :param group_snapshot: the GroupSnapshot object to be deleted.
        :param snapshots: a list of snapshot objects in the group_snapshot.
        :returns: model_update, snapshots_model_update
        """

        # the driver treats a group as a CG internally.
        # We proxy the calls to the CG api.
        return self.delete_cgsnapshot(context, group_snapshot, snapshots)

    def _get_ig(self, name):
        try:
            return self.client.req('initiator-groups', 'GET',
                                   name=name)['content']
        except exception.NotFound:
            pass

    def _create_ig(self, name):
        # create an initiator group to hold the initiator
        data = {'ig-name': name}
        self.client.req('initiator-groups', 'POST', data)
        try:
            return self.client.req('initiator-groups', name=name)['content']
        except exception.NotFound:
            raise (exception.VolumeBackendAPIException
                   (data=_("Failed to create IG, %s") % name))


@interface.volumedriver
class XtremIOISCSIDriver(XtremIOVolumeDriver, driver.ISCSIDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSCSI target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """
    driver_name = 'XtremIO_ISCSI'

    def __init__(self, *args, **kwargs):
        super(XtremIOISCSIDriver, self).__init__(*args, **kwargs)
        self.protocol = 'iSCSI'

    def _add_auth(self, data, login_chap, discovery_chap):
        login_passwd, discovery_passwd = None, None
        if login_chap:
            data['initiator-authentication-user-name'] = 'chap_user'
            login_passwd = self._get_password()
            data['initiator-authentication-password'] = login_passwd
        if discovery_chap:
            data['initiator-discovery-user-name'] = 'chap_user'
            discovery_passwd = self._get_password()
            data['initiator-discovery-password'] = discovery_passwd
        return login_passwd, discovery_passwd

    def _create_initiator(self, connector, login_chap, discovery_chap):
        initiator = self._get_initiator_names(connector)[0]
        # create an initiator
        data = {'initiator-name': initiator,
                'ig-id': initiator,
                'port-address': initiator}
        l, d = self._add_auth(data, login_chap, discovery_chap)
        self.client.req('initiators', 'POST', data)
        return l, d

    def initialize_connection(self, volume, connector):
        try:
            sys = self.client.get_cluster()
        except exception.NotFound:
            msg = _("XtremIO not initialized correctly, no clusters found")
            raise exception.VolumeBackendAPIException(data=msg)
        login_chap = (sys.get('chap-authentication-mode', 'disabled') !=
                      'disabled')
        discovery_chap = (sys.get('chap-discovery-mode', 'disabled') !=
                          'disabled')
        initiator_name = self._get_initiator_names(connector)[0]
        initiator = self.client.get_initiator(initiator_name)
        if initiator:
            login_passwd = initiator['chap-authentication-initiator-password']
            discovery_passwd = initiator['chap-discovery-initiator-password']
            ig = self._get_ig(initiator['ig-id'][XTREMIO_OID_NAME])
        else:
            ig = self._get_ig(self._get_ig_name(connector))
            if not ig:
                ig = self._create_ig(self._get_ig_name(connector))
            (login_passwd,
             discovery_passwd) = self._create_initiator(connector,
                                                        login_chap,
                                                        discovery_chap)
        # if CHAP was enabled after the initiator was created
        if login_chap and not login_passwd:
            LOG.info('Initiator has no password while using chap, adding it.')
            data = {}
            (login_passwd,
             d_passwd) = self._add_auth(data, login_chap, discovery_chap and
                                        not discovery_passwd)
            discovery_passwd = (discovery_passwd if discovery_passwd
                                else d_passwd)
            self.client.req('initiators', 'PUT', data, idx=initiator['index'])

        # lun mappping
        lunmap = self.create_lun_map(volume, ig['ig-id'][XTREMIO_OID_NAME])

        properties = self._get_iscsi_properties(lunmap)

        if login_chap:
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = 'chap_user'
            properties['auth_password'] = login_passwd
        if discovery_chap:
            properties['discovery_auth_method'] = 'CHAP'
            properties['discovery_auth_username'] = 'chap_user'
            properties['discovery_auth_password'] = discovery_passwd
        LOG.debug('init conn params:\n%s',
                  strutils.mask_dict_password(properties))
        return {
            'driver_volume_type': 'iscsi',
            'data': properties
        }

    def _get_iscsi_properties(self, lunmap):
        """Gets iscsi configuration.

        :target_discovered:    boolean indicating whether discovery was used
        :target_iqn:    the IQN of the iSCSI target
        :target_portal:    the portal of the iSCSI target
        :target_lun:    the lun of the iSCSI target
        :volume_id:    the id of the volume (currently used by xen)
        :auth_method:, :auth_username:, :auth_password:
            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        multiple connection return
        :target_iqns, :target_portals, :target_luns, which contain lists of
        multiple values. The main portal information is also returned in
        :target_iqn, :target_portal, :target_lun for backward compatibility.
        """
        portals = self.client.get_iscsi_portals()
        if not portals:
            msg = _("XtremIO not configured correctly, no iscsi portals found")
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)
        portal = RANDOM.choice(portals)
        portal_addr = ('%(ip)s:%(port)d' %
                       {'ip': portal['ip-addr'].split('/')[0],
                        'port': portal['ip-port']})

        tg_portals = ['%(ip)s:%(port)d' % {'ip': p['ip-addr'].split('/')[0],
                                           'port': p['ip-port']}
                      for p in portals]
        properties = {'target_discovered': False,
                      'target_iqn': portal['port-address'],
                      'target_lun': lunmap['lun'],
                      'target_portal': portal_addr,
                      'target_iqns': [p['port-address'] for p in portals],
                      'target_portals': tg_portals,
                      'target_luns': [lunmap['lun']] * len(portals)}
        return properties

    def _get_initiator_names(self, connector):
        return [connector['initiator']]

    def _get_ig_name(self, connector):
        return connector['initiator']


@interface.volumedriver
class XtremIOFCDriver(XtremIOVolumeDriver,
                      driver.FibreChannelDriver):

    def __init__(self, *args, **kwargs):
        super(XtremIOFCDriver, self).__init__(*args, **kwargs)
        self.protocol = 'FC'
        self._targets = None

    def get_targets(self):
        if not self._targets:
            try:
                targets = self.client.get_fc_up_ports()
                self._targets = [target['port-address'].replace(':', '')
                                 for target in targets]
            except exception.NotFound:
                raise (exception.VolumeBackendAPIException
                       (data=_("Failed to get targets")))
        return self._targets

    def _get_free_lun(self, igs):
        luns = []
        for ig in igs:
            luns.extend(lm['lun'] for lm in
                        self.client.req('lun-maps',
                                        data={'full': 1, 'prop': 'lun',
                                              'filter': 'ig-name:eq:%s' % ig})
                        ['lun-maps'])
        uniq_luns = set(luns + [0])
        seq = range(len(uniq_luns) + 1)
        return min(set(seq) - uniq_luns)

    def initialize_connection(self, volume, connector):
        wwpns = self._get_initiator_names(connector)
        ig_name = self._get_ig_name(connector)
        i_t_map = {}
        found = []
        new = []
        for wwpn in wwpns:
            init = self.client.get_initiator(wwpn)
            if init:
                found.append(init)
            else:
                new.append(wwpn)
            i_t_map[wwpn.replace(':', '')] = self.get_targets()
        # get or create initiator group
        if new:
            ig = self._get_ig(ig_name)
            if not ig:
                ig = self._create_ig(ig_name)
            for wwpn in new:
                data = {'initiator-name': wwpn, 'ig-id': ig_name,
                        'port-address': wwpn}
                self.client.req('initiators', 'POST', data)
        igs = list(set([i['ig-id'][XTREMIO_OID_NAME] for i in found]))
        if new and ig['ig-id'][XTREMIO_OID_NAME] not in igs:
            igs.append(ig['ig-id'][XTREMIO_OID_NAME])

        if len(igs) > 1:
            lun_num = self._get_free_lun(igs)
        else:
            lun_num = None
        for ig in igs:
            lunmap = self.create_lun_map(volume, ig, lun_num)
            lun_num = lunmap['lun']
        conn_info = {'driver_volume_type': 'fibre_channel',
                     'data': {
                         'target_discovered': False,
                         'target_lun': lun_num,
                         'target_wwn': self.get_targets(),
                         'initiator_target_map': i_t_map}}
        fczm_utils.add_fc_zone(conn_info)
        return conn_info

    def terminate_connection(self, volume, connector, **kwargs):
        (super(XtremIOFCDriver, self)
         .terminate_connection(volume, connector, **kwargs))
        has_volumes = (not connector
                       or self.client.
                       num_of_mapped_volumes(self._get_ig_name(connector)) > 0)

        if has_volumes:
            data = {}
        else:
            i_t_map = {}
            for initiator in self._get_initiator_names(connector):
                i_t_map[initiator.replace(':', '')] = self.get_targets()
            data = {'target_wwn': self.get_targets(),
                    'initiator_target_map': i_t_map}

        conn_info = {'driver_volume_type': 'fibre_channel',
                     'data': data}
        fczm_utils.remove_fc_zone(conn_info)
        return conn_info

    def _get_initiator_names(self, connector):
        return [wwpn if ':' in wwpn else
                ':'.join(wwpn[i:i + 2] for i in range(0, len(wwpn), 2))
                for wwpn in connector['wwpns']]

    def _get_ig_name(self, connector):
        return connector['host']
