# Copyright (c) 2012 - 2014 EMC Corporation.
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
Driver for EMC XtremIO Storage.
supported XtremIO version 2.4 and up

1.0.0 - initial release
1.0.1 - enable volume extend
1.0.2 - added FC support, improved error handling
1.0.3 - update logging level, add translation
1.0.4 - support for FC zones
1.0.5 - add support for XtremIO 4.0
1.0.6 - add support for iSCSI and CA validation
"""

import json
import math
import random
import requests
import string

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.zonemanager import utils as fczm_utils


LOG = logging.getLogger(__name__)

CONF = cfg.CONF
DEFAULT_PROVISIONING_FACTOR = 20.0
XTREMIO_OPTS = [
    cfg.StrOpt('xtremio_cluster_name',
               default='',
               help='XMS cluster id in multi-cluster environment')]

CONF.register_opts(XTREMIO_OPTS)

RANDOM = random.Random()
OBJ_NOT_FOUND_ERR = 'obj_not_found'
VOL_NOT_UNIQUE_ERR = 'vol_obj_name_not_unique'
VOL_OBJ_NOT_FOUND_ERR = 'vol_obj_not_found'
ALREADY_MAPPED_ERR = 'already_mapped'


class XtremIOClient(object):
    def __init__(self, configuration, cluster_id):
        self.configuration = configuration
        self.cluster_id = cluster_id
        self.verify = (self.configuration.
                       safe_get('driver_ssl_cert_verify')
                       or False)

    def get_base_url(self, ver):
        if ver == 'v1':
            return 'https://%s/api/json/types' % self.configuration.san_ip
        elif ver == 'v2':
            return 'https://%s/api/json/v2/types' % self.configuration.san_ip

    def req(self, object_type='volumes', request_typ='GET', data=None,
            name=None, idx=None, ver='v1'):
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
        if request_typ in ('GET', 'DELETE'):
            params.update(data)
            self.update_url(params, self.cluster_id)
        if request_typ != 'GET':
            self.update_data(data, self.cluster_id)
            LOG.debug('data: %s', data)
        LOG.debug('%(type)s %(url)s', {'type': request_typ, 'url': url})
        try:
            response = requests.request(request_typ, url, params=params,
                                        data=json.dumps(data),
                                        verify=self.verify,
                                        auth=(self.configuration.san_login,
                                              self.configuration.san_password))
        except requests.exceptions.RequestException as exc:
            msg = (_('Exception: %s') % six.text_type(exc))
            raise exception.VolumeDriverException(message=msg)

        if 200 <= response.status_code < 300:
            if request_typ in ('GET', 'POST'):
                return response.json()
            else:
                return ''

        self.handle_errors(response, key, object_type)

    def handle_errors(self, response, key, object_type):
        if response.status_code == 400:
            error = response.json()
            err_msg = error.get('message')
            if err_msg.endswith(OBJ_NOT_FOUND_ERR):
                LOG.warning(_LW("object %(key)s of "
                                "type %(typ)s not found, %(err_msg)s"),
                            {'key': key, 'typ': object_type,
                             'err_msg': err_msg, })
                raise exception.NotFound()
            elif err_msg == VOL_NOT_UNIQUE_ERR:
                LOG.error(_LE("can't create 2 volumes with the same name, %s"),
                          err_msg)
                msg = (_('Volume by this name already exists'))
                raise exception.VolumeBackendAPIException(data=msg)
            elif err_msg == VOL_OBJ_NOT_FOUND_ERR:
                LOG.error(_LE("Can't find volume to map %(key)s, %(msg)s"),
                          {'key': key, 'msg': err_msg, })
                raise exception.VolumeNotFound(volume_id=key)
            elif ALREADY_MAPPED_ERR in err_msg:
                raise exception.XtremIOAlreadyMappedError()
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


class XtremIOClient3(XtremIOClient):
    def __init__(self, configuration, cluster_id):
        super(XtremIOClient3, self).__init__(configuration, cluster_id)
        self._portals = []

    def find_lunmap(self, ig_name, vol_name):
        try:
            for lm_link in self.req('lun-maps')['lun-maps']:
                idx = lm_link['href'].split('/')[-1]
                lm = self.req('lun-maps', idx=int(idx))['content']
                if lm['ig-name'] == ig_name and lm['vol-name'] == vol_name:
                    return lm
        except exception.NotFound:
            raise (exception.VolumeDriverException
                   (_("can't find lunmap, ig:%(ig)s vol:%(vol)s") %
                    {'ig': ig_name, 'vol': vol_name}))

    def num_of_mapped_volumes(self, initiator):
        cnt = 0
        for lm_link in self.req('lun-maps')['lun-maps']:
            idx = lm_link['href'].split('/')[-1]
            lm = self.req('lun-maps', idx=int(idx))['content']
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


class XtremIOClient4(XtremIOClient):
    def __init__(self, configuration, cluster_id):
        super(XtremIOClient4, self).__init__(configuration, cluster_id)
        self._cluster_name = None

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
            msg = _LE('Failed to rename the created snapshot, reverting.')
            LOG.error(msg)
            self.req(typ, 'DELETE', idx=int(idx))
            raise


class XtremIOVolumeDriver(san.SanDriver):
    """Executes commands relating to Volumes."""

    VERSION = '1.0.6'
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
        self.provisioning_factor = (self.configuration.
                                    safe_get('max_over_subscription_ratio')
                                    or DEFAULT_PROVISIONING_FACTOR)
        self._stats = {}
        self.client = XtremIOClient3(self.configuration, self.cluster_id)

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
            LOG.info(_LI('XtremIO SW version %s'), version_text)
        if ver[0] >= 4:
            self.client = XtremIOClient4(self.configuration, self.cluster_id)

    def create_volume(self, volume):
        "Creates a volume"
        data = {'vol-name': volume['id'],
                'vol-size': str(volume['size']) + 'g'
                }

        self.client.req('volumes', 'POST', data)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.client.create_snapshot(snapshot.id, volume['id'])

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        self.client.create_snapshot(src_vref['id'], volume['id'])

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            self.client.req('volumes', 'DELETE', name=volume['id'])
        except exception.NotFound:
            LOG.info(_LI("volume %s doesn't exist"), volume['id'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.client.create_snapshot(snapshot.volume_id, snapshot.id, True)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            self.client.req('volumes', 'DELETE', name=snapshot.id)
        except exception.NotFound:
            LOG.info(_LI("snapshot %s doesn't exist"), snapshot.id)

    def _update_volume_stats(self):
        sys = self.client.get_cluster()
        physical_space = int(sys["ud-ssd-space"]) / units.Mi
        used_physical_space = int(sys["ud-ssd-space-in-use"]) / units.Mi
        free_physical = physical_space - used_physical_space
        actual_prov = int(sys["vol-size"]) / units.Mi
        self._stats = {'volume_backend_name': self.backend_name,
                       'vendor_name': 'EMC',
                       'driver_version': self.VERSION,
                       'storage_protocol': self.protocol,
                       'total_capacity_gb': physical_space,
                       'free_capacity_gb': (free_physical *
                                            self.provisioning_factor),
                       'provisioned_capacity_gb': actual_prov,
                       'max_over_subscription_ratio': self.provisioning_factor,
                       'thin_provisioning_support': True,
                       'thick_provisioning_support': False,
                       'reserved_percentage':
                       self.configuration.reserved_percentage,
                       'QoS_support': False}

    def get_volume_stats(self, refresh=False):
        """Get volume stats.
        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()
        return self._stats

    def manage_existing(self, volume, existing_ref):
        """Manages an existing LV."""
        lv_name = existing_ref['source-name']
        # Attempt to locate the volume.
        try:
            vol_obj = self.client.req('volumes', name=lv_name)['content']
        except exception.NotFound:
            kwargs = {'existing_ref': lv_name,
                      'reason': 'Specified logical volume does not exist.'}
            raise exception.ManageExistingInvalidReference(**kwargs)

        # Attempt to rename the LV to match the OpenStack internal name.
        self.client.req('volumes', 'PUT', data={'vol-name': volume['id']},
                        idx=vol_obj['index'])

    def manage_existing_get_size(self, volume, existing_ref):
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
                      'reason': 'Specified logical volume does not exist.'}
            raise exception.ManageExistingInvalidReference(**kwargs)
        # LV size is returned in gigabytes.  Attempt to parse size as a float
        # and round up to the next integer.
        lv_size = int(math.ceil(int(vol_obj['vol-size']) / units.Mi))

        return lv_size

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""
        # trying to rename the volume to [cinder name]-unmanged
        try:
            self.client.req('volumes', 'PUT', name=volume['id'],
                            data={'vol-name': volume['name'] + '-unmanged'})
        except exception.NotFound:
            LOG.info(_LI("Volume with the name %s wasn't found,"
                         " can't unmanage"),
                     volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

    def extend_volume(self, volume, new_size):
        """Extend an existing volume's size."""
        data = {'vol-size': six.text_type(new_size) + 'g'}
        try:
            self.client.req('volumes', 'PUT', data, name=volume['id'])
        except exception.NotFound:
            msg = _("can't find the volume to extend")
            raise (exception.VolumeDriverException(message=msg))

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector"""
        try:
            ig = self.client.req('initiator-groups',
                                 name=self._get_ig(connector))['content']
            tg = self.client.req('target-groups', name='Default')['content']
            vol = self.client.req('volumes', name=volume['id'])['content']

            lm_name = '%s_%s_%s' % (six.text_type(vol['index']),
                                    six.text_type(ig['index']),
                                    six.text_type(tg['index']))
            LOG.debug('removing lun map %s', lm_name)
            self.client.req('lun-maps', 'DELETE', name=lm_name)
        except exception.NotFound:
            LOG.warning(_LW("terminate_connection: lun map not found"))

    def _get_password(self):
        return ''.join(RANDOM.choice
                       (string.ascii_uppercase + string.digits)
                       for _ in range(12))

    def create_lun_map(self, volume, ig):
        try:
            res = self.client.req('lun-maps', 'POST',
                                  {'ig-id': ig['ig-id'][2],
                                   'vol-id': volume['id']})
            lunmap = self._obj_from_result(res)
            LOG.info(_LI('created lunmap\n%s'), lunmap)
        except exception.XtremIOAlreadyMappedError:
            LOG.info(_LI('volume already mapped,'
                         ' trying to retrieve it %(ig)s, %(vol)d'),
                     {'ig': ig['ig-id'][1], 'vol': volume['id']})
            lunmap = self.client.find_lunmap(ig['ig-id'][1], volume['id'])
        return lunmap

    def _get_ig(self, connector):
        raise NotImplementedError()


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

    def initialize_connection(self, volume, connector):
        try:
            sys = self.client.get_cluster()
        except exception.NotFound:
            msg = _("XtremIO not initialized correctly, no clusters found")
            raise exception.VolumeBackendAPIException(data=msg)
        use_chap = (sys.get('chap-authentication-mode', 'disabled') !=
                    'disabled')
        discovery_chap = (sys.get('chap-discovery-mode', 'disabled') !=
                          'disabled')
        initiator = self._get_initiator(connector)
        try:
            # check if the IG already exists
            ig = self.client.req('initiator-groups', 'GET',
                                 name=self._get_ig(connector))['content']
        except exception.NotFound:
            # create an initiator group to hold the initiator
            data = {'ig-name': self._get_ig(connector)}
            self.client.req('initiator-groups', 'POST', data)
            try:
                ig = self.client.req('initiator-groups',
                                     name=self._get_ig(connector))['content']
            except exception.NotFound:
                raise (exception.VolumeBackendAPIException
                       (data=_("Failed to create IG, %s") %
                        self._get_ig(connector)))
        try:
            init = self.client.req('initiators', 'GET',
                                   name=initiator)['content']
            if use_chap:
                chap_passwd = init['chap-authentication-initiator-'
                                   'password']
                # delete the initiator to create a new one with password
                if not chap_passwd:
                    LOG.info(_LI('initiator has no password while using chap,'
                                 'removing it'))
                    self.client.req('initiators', 'DELETE', name=initiator)
                    # check if the initiator already exists
                    raise exception.NotFound()
        except exception.NotFound:
            # create an initiator
            data = {'initiator-name': initiator,
                    'ig-id': initiator,
                    'port-address': initiator}
            if use_chap:
                data['initiator-authentication-user-name'] = 'chap_user'
                chap_passwd = self._get_password()
                data['initiator-authentication-password'] = chap_passwd
            if discovery_chap:
                data['initiator-discovery-user-name'] = 'chap_user'
                data['initiator-discovery-'
                     'password'] = self._get_password()
            self.client.req('initiators', 'POST', data)
        # lun mappping
        lunmap = self.create_lun_map(volume, ig)

        properties = self._get_iscsi_properties(lunmap)

        if use_chap:
            properties['auth_method'] = 'CHAP'
            properties['auth_username'] = 'chap_user'
            properties['auth_password'] = chap_passwd

        LOG.debug('init conn params:\n%s', properties)
        return {
            'driver_volume_type': 'iscsi',
            'data': properties
        }

    def _get_iscsi_properties(self, lunmap):
        """Gets iscsi configuration
        :target_discovered:    boolean indicating whether discovery was used
        :target_iqn:    the IQN of the iSCSI target
        :target_portal:    the portal of the iSCSI target
        :target_lun:    the lun of the iSCSI target
        :volume_id:    the id of the volume (currently used by xen)
        :auth_method:, :auth_username:, :auth_password:
            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        :access_mode:    the volume access mode allow client used
                         ('rw' or 'ro' currently supported)
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
                      'access_mode': 'rw',
                      'target_iqns': [p['port-address'] for p in portals],
                      'target_portals': tg_portals,
                      'target_luns': [lunmap['lun']] * len(portals)}
        return properties

    def _get_initiator(self, connector):
        return connector['initiator']

    def _get_ig(self, connector):
        return connector['initiator']


class XtremIOFibreChannelDriver(XtremIOVolumeDriver,
                                driver.FibreChannelDriver):

    def __init__(self, *args, **kwargs):
        super(XtremIOFibreChannelDriver, self).__init__(*args, **kwargs)
        self.protocol = 'FC'
        self._targets = None

    def get_targets(self):
        if not self._targets:
            try:
                target_list = self.client.req('targets')["targets"]
                targets = [self.client.req('targets',
                                           name=target['name'])['content']
                           for target in target_list
                           if '-fc' in target['name']]
                self._targets = [target['port-address'].replace(':', '')
                                 for target in targets
                                 if target['port-state'] == 'up']
            except exception.NotFound:
                raise (exception.VolumeBackendAPIException
                       (data=_("Failed to get targets")))
        return self._targets

    @fczm_utils.AddFCZone
    def initialize_connection(self, volume, connector):
        initiators = self._get_initiator(connector)
        ig_name = self._get_ig(connector)
        i_t_map = {}
        # get or create initiator group
        try:
            # check if the IG already exists
            ig = self.client.req('initiator-groups', name=ig_name)['content']
        except exception.NotFound:
            # create an initiator group to hold the the initiator
            data = {'ig-name': ig_name}
            self.client.req('initiator-groups', 'POST', data)
            try:
                ig = self.client.req('initiator-groups',
                                     name=ig_name)['content']
            except exception.NotFound:
                raise (exception.VolumeBackendAPIException
                       (data=_("Failed to create IG, %s") % ig_name))
        # get or create all initiators
        for initiator in initiators:
            try:
                self.client.req('initiators', name=initiator)['content']
            except exception.NotFound:
                # create an initiator
                data = {'initiator-name': initiator,
                        'ig-id': ig['name'],
                        'port-address': initiator}
                self.client.req('initiators', 'POST', data)
            i_t_map[initiator] = self.get_targets()

        lunmap = self.create_lun_map(volume, ig)
        return {'driver_volume_type': 'fibre_channel',
                'data': {
                    'target_discovered': True,
                    'target_lun': lunmap['lun'],
                    'target_wwn': self.get_targets(),
                    'access_mode': 'rw',
                    'initiator_target_map': i_t_map}}

    @fczm_utils.RemoveFCZone
    def terminate_connection(self, volume, connector, **kwargs):
        (super(XtremIOFibreChannelDriver, self)
         .terminate_connection(volume, connector, **kwargs))
        num_vols = self.client.num_of_mapped_volumes(self._get_ig(connector))
        if num_vols > 0:
            data = {}
        else:
            i_t_map = {}
            for initiator in self._get_initiator(connector):
                i_t_map[initiator] = self.get_targets()
            data = {'target_wwn': self.get_targets(),
                    'initiator_target_map': i_t_map}

        return {'driver_volume_type': 'fibre_channel',
                'data': data}

    def _get_initiator(self, connector):
        return connector['wwpns']

    def _get_ig(self, connector):
        return connector['host']
