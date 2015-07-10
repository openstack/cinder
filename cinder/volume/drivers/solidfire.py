# Copyright 2013 SolidFire Inc
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

import json
import math
import random
import socket
import string
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import units
import requests
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.image import image_utils
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume.targets import iscsi as iscsi_driver
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

sf_opts = [
    cfg.BoolOpt('sf_emulate_512',
                default=True,
                help='Set 512 byte emulation on volume creation; '),

    cfg.BoolOpt('sf_allow_tenant_qos',
                default=False,
                help='Allow tenants to specify QOS on create'),

    cfg.StrOpt('sf_account_prefix',
               default=None,
               help='Create SolidFire accounts with this prefix. Any string '
                    'can be used here, but the string \"hostname\" is special '
                    'and will create a prefix using the cinder node hostname '
                    '(previous default behavior).  The default is NO prefix.'),

    cfg.StrOpt('sf_template_account_name',
               default='openstack-vtemplate',
               help='Account name on the SolidFire Cluster to use as owner of '
                    'template/cache volumes (created if does not exist).'),

    cfg.BoolOpt('sf_allow_template_caching',
                default=True,
                help='Create an internal cache of copy of images when '
                     'a bootable volume is created to eliminate fetch from '
                     'glance and qemu-conversion on subsequent calls.'),

    cfg.IntOpt('sf_api_port',
               default=443,
               help='SolidFire API port. Useful if the device api is behind '
                    'a proxy on a different port.')]


CONF = cfg.CONF
CONF.register_opts(sf_opts)


def retry(exc_tuple, tries=5, delay=1, backoff=2):
    def retry_dec(f):
        @six.wraps(f)
        def func_retry(*args, **kwargs):
            _tries, _delay = tries, delay
            while _tries > 1:
                try:
                    return f(*args, **kwargs)
                except exc_tuple:
                    time.sleep(_delay)
                    _tries -= 1
                    _delay *= backoff
                    LOG.debug('Retrying %(args)s, %(tries)s attempts '
                              'remaining...',
                              {'args': args, 'tries': _tries})
            # NOTE(jdg): Don't log the params passed here
            # some cmds like createAccount will have sensitive
            # info in the params, grab only the second tuple
            # which should be the Method
            msg = (_('Retry count exceeded for command: %s') %
                    (args[1],))
            LOG.error(msg)
            raise exception.SolidFireAPIException(message=msg)
        return func_retry
    return retry_dec


class SolidFireDriver(san.SanISCSIDriver):
    """OpenStack driver to enable SolidFire cluster.

    Version history:
        1.0 - Initial driver
        1.1 - Refactor, clone support, qos by type and minor bug fixes
        1.2 - Add xfr and retype support
        1.2.1 - Add export/import support
        1.2.2 - Catch VolumeNotFound on accept xfr
        2.0.0 - Move from httplib to requests
        2.0.1 - Implement SolidFire Snapshots
        2.0.2 - Implement secondary account

    """

    VERSION = '2.0.2'

    sf_qos_dict = {'slow': {'minIOPS': 100,
                            'maxIOPS': 200,
                            'burstIOPS': 200},
                   'medium': {'minIOPS': 200,
                              'maxIOPS': 400,
                              'burstIOPS': 400},
                   'fast': {'minIOPS': 500,
                            'maxIOPS': 1000,
                            'burstIOPS': 1000},
                   'performant': {'minIOPS': 2000,
                                  'maxIOPS': 4000,
                                  'burstIOPS': 4000},
                   'off': None}

    sf_qos_keys = ['minIOPS', 'maxIOPS', 'burstIOPS']
    cluster_stats = {}
    retry_exc_tuple = (exception.SolidFireRetryableException,
                       requests.exceptions.ConnectionError)
    retryable_errors = ['xDBVersionMismatch',
                        'xMaxSnapshotsPerVolumeExceeded',
                        'xMaxClonesPerVolumeExceeded',
                        'xMaxSnapshotsPerNodeExceeded',
                        'xMaxClonesPerNodeExceeded',
                        'xNotReadyForIO']

    def __init__(self, *args, **kwargs):
        super(SolidFireDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(sf_opts)
        self._endpoint = self._build_endpoint_info()
        self.template_account_id = None
        self.max_volumes_per_account = 1990
        try:
            self._update_cluster_status()
        except exception.SolidFireAPIException:
            pass
        if self.configuration.sf_allow_template_caching:
            account = self.configuration.sf_template_account_name
            self.template_account_id = self._create_template_account(account)
        self.target_driver = (
            importutils.import_object(
                'cinder.volume.drivers.solidfire.SolidFireISCSI',
                solidfire_driver=self,
                configuration=self.configuration))

    def _create_template_account(self, account_name):
        # We raise an API exception if the account doesn't exist
        try:
            id = self._issue_api_request(
                'GetAccountByName',
                {'username': account_name})['result']['account']['accountID']
        except exception.SolidFireAPIException:
            chap_secret = self._generate_random_string(12)
            params = {'username': account_name,
                      'initiatorSecret': chap_secret,
                      'targetSecret': chap_secret,
                      'attributes': {}}
            id = self._issue_api_request('AddAccount',
                                         params)['result']['accountID']
        return id

    def _build_endpoint_info(self, **kwargs):
        endpoint = {}

        endpoint['mvip'] =\
            kwargs.get('mvip', self.configuration.san_ip)
        endpoint['login'] =\
            kwargs.get('login', self.configuration.san_login)
        endpoint['passwd'] =\
            kwargs.get('passwd', self.configuration.san_password)
        endpoint['port'] =\
            kwargs.get('port', self.configuration.sf_api_port)
        endpoint['url'] = 'https://%s:%s' % (endpoint['mvip'],
                                             endpoint['port'])

        # TODO(jdg): consider a call to GetAPI and setting version
        return endpoint

    @retry(retry_exc_tuple, tries=6)
    def _issue_api_request(self, method, params, version='1.0', endpoint=None):
        if params is None:
            params = {}

        if endpoint is None:
            endpoint = self._endpoint
        payload = {'method': method, 'params': params}

        url = '%s/json-rpc/%s/' % (endpoint['url'], version)
        req = requests.post(url,
                            data=json.dumps(payload),
                            auth=(endpoint['login'], endpoint['passwd']),
                            verify=False,
                            timeout=30)

        response = req.json()
        req.close()
        if (('error' in response) and
                (response['error']['name'] in self.retryable_errors)):
            msg = ('Retryable error (%s) encountered during '
                   'SolidFire API call.' % response['error']['name'])
            LOG.debug(msg)
            raise exception.SolidFireRetryableException(message=msg)

        if 'error' in response:
            msg = _('API response: %s') % response
            raise exception.SolidFireAPIException(msg)

        return response

    def _get_volumes_by_sfaccount(self, account_id):
        """Get all volumes on cluster for specified account."""
        params = {'accountID': account_id}
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' in data:
            return data['result']['volumes']

    def _get_sfaccount_by_name(self, sf_account_name):
        """Get SolidFire account object by name."""
        sfaccount = None
        params = {'username': sf_account_name}
        try:
            data = self._issue_api_request('GetAccountByName', params)
            if 'result' in data and 'account' in data['result']:
                LOG.debug('Found solidfire account: %s', sf_account_name)
                sfaccount = data['result']['account']
        except exception.SolidFireAPIException as ex:
            if 'xUnknownAccount' in ex.msg:
                return sfaccount
            else:
                raise
        return sfaccount

    def _get_sf_account_name(self, project_id):
        """Build the SolidFire account name to use."""
        prefix = self.configuration.sf_account_prefix or ''
        if prefix == 'hostname':
            prefix = socket.gethostname()
        return '%s%s%s' % (prefix, '-' if prefix else '', project_id)

    def _get_sfaccount(self, project_id):
        sf_account_name = self._get_sf_account_name(project_id)
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            raise exception.SolidFireAccountNotFound(
                account_name=sf_account_name)

        return sfaccount

    def _create_sfaccount(self, project_id):
        """Create account on SolidFire device if it doesn't already exist.

        We're first going to check if the account already exists, if it does
        just return it.  If not, then create it.

        """

        sf_account_name = self._get_sf_account_name(project_id)
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            LOG.debug('solidfire account: %s does not exist, create it...',
                      sf_account_name)
            chap_secret = self._generate_random_string(12)
            params = {'username': sf_account_name,
                      'initiatorSecret': chap_secret,
                      'targetSecret': chap_secret,
                      'attributes': {}}
            data = self._issue_api_request('AddAccount', params)
            if 'result' in data:
                sfaccount = self._get_sfaccount_by_name(sf_account_name)

        return sfaccount

    def _get_cluster_info(self):
        """Query the SolidFire cluster for some property info."""
        params = {}
        data = self._issue_api_request('GetClusterInfo', params)
        if 'result' not in data:
            msg = _("API response: %s") % data
            raise exception.SolidFireAPIException(msg)

        return data['result']

    def _generate_random_string(self, length):
        """Generates random_string to use for CHAP password."""

        char_set = string.ascii_uppercase + string.digits
        return ''.join(random.sample(char_set, length))

    def _get_model_info(self, sfaccount, sf_volume_id):
        """Gets the connection info for specified account and volume."""
        cluster_info = self._get_cluster_info()
        iscsi_portal = cluster_info['clusterInfo']['svip'] + ':3260'
        chap_secret = sfaccount['targetSecret']

        found_volume = False
        iteration_count = 0
        while not found_volume and iteration_count < 600:
            volume_list = self._get_volumes_by_sfaccount(
                sfaccount['accountID'])
            iqn = None
            for v in volume_list:
                if v['volumeID'] == sf_volume_id:
                    iqn = v['iqn']
                    found_volume = True
                    break
            if not found_volume:
                time.sleep(2)
            iteration_count += 1

        if not found_volume:
            LOG.error(_LE('Failed to retrieve volume SolidFire-'
                          'ID: %s in get_by_account!'), sf_volume_id)
            raise exception.VolumeNotFound(volume_id=sf_volume_id)

        model_update = {}
        # NOTE(john-griffith): SF volumes are always at lun 0
        model_update['provider_location'] = ('%s %s %s'
                                             % (iscsi_portal, iqn, 0))
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                            chap_secret))
        if not self.configuration.sf_emulate_512:
            model_update['provider_geometry'] = ('%s %s' % (4096, 4096))
        model_update['provider_id'] = ('%s' % sf_volume_id)

        return model_update

    def _do_clone_volume(self, src_uuid,
                         src_project_id,
                         vref):
        """Create a clone of an existing volume or snapshot. """
        attributes = {}
        qos = {}

        sf_accounts = self._get_sfaccounts_for_tenant(vref['project_id'])
        if not sf_accounts:
            sf_account = self._create_sfaccount(vref['project_id'])
        else:
            # Check availability for creates
            sf_account = self._get_account_create_availability(sf_accounts)
            if not sf_account:
                # TODO(jdg): We're not doing tertiaries, so fail
                msg = _('volumes/account exceeded on both primary '
                        'and secondary SolidFire accounts')
                raise exception.SolidFireDriverException(msg)

        params = {'name': 'UUID-%s' % vref['id'],
                  'newAccountID': sf_account['accountID']}

        # NOTE(jdg): First check the SF snapshots
        # if we don't find a snap by the given name, just move on to check
        # volumes.  This may be a running system that was updated from
        # before we did snapshots, so need to check both
        is_clone = False
        snap_name = 'UUID-%s' % src_uuid
        snaps = self._get_sf_snapshots()
        snap = next((s for s in snaps if s["name"] == snap_name), None)
        if snap:
            params['snapshotID'] = int(snap['snapshotID'])
            params['volumeID'] = int(snap['volumeID'])
            params['newSize'] = int(vref['size'] * units.Gi)
        else:
            sf_vol = self._get_sf_volume(
                src_uuid, {'accountID': sf_account['accountID']})
            if sf_vol is None:
                raise exception.VolumeNotFound(volume_id=src_uuid)
            params['volumeID'] = int(sf_vol['volumeID'])
            params['newSize'] = int(vref['size'] * units.Gi)
            is_clone = True

        data = self._issue_api_request('CloneVolume', params, version='6.0')
        if (('result' not in data) or ('volumeID' not in data['result'])):
            msg = _("API response: %s") % data
            raise exception.SolidFireAPIException(msg)

        sf_volume_id = data['result']['volumeID']
        if (self.configuration.sf_allow_tenant_qos and
                vref.get('volume_metadata')is not None):
            qos = self._set_qos_presets(vref)

        ctxt = context.get_admin_context()
        type_id = vref.get('volume_type_id', None)
        if type_id is not None:
            qos = self._set_qos_by_volume_type(ctxt, type_id)

        # NOTE(jdg): all attributes are copied via clone, need to do an update
        # to set any that were provided
        params = {'volumeID': sf_volume_id}

        create_time = vref['created_at'].isoformat()
        attributes = {'uuid': vref['id'],
                      'is_clone': 'True',
                      'src_uuid': src_uuid,
                      'created_at': create_time}
        if qos:
            params['qos'] = qos
            for k, v in qos.items():
                attributes[k] = str(v)

        params['attributes'] = attributes
        data = self._issue_api_request('ModifyVolume', params)

        model_update = self._get_model_info(sf_account, sf_volume_id)
        if model_update is None:
            mesg = _('Failed to get model update from clone')
            raise exception.SolidFireAPIException(mesg)

        # Increment the usage count, just for data collection
        # We're only doing this for clones, not create_from snaps
        if is_clone:
            data = self._update_attributes(sf_vol)
        return (data, sf_account, model_update)

    def _update_attributes(self, sf_vol):
        cloned_count = sf_vol['attributes'].get('cloned_count', 0)
        cloned_count += 1
        attributes = sf_vol['attributes']
        attributes['cloned_count'] = cloned_count

        params = {'volumeID': int(sf_vol['volumeID'])}
        params['attributes'] = attributes
        return self._issue_api_request('ModifyVolume', params)

    def _do_volume_create(self, sf_account, params):
        data = self._issue_api_request('CreateVolume', params)
        if (('result' not in data) or ('volumeID' not in data['result'])):
            msg = _("Failed volume create: %s") % data
            raise exception.SolidFireAPIException(msg)

        sf_volume_id = data['result']['volumeID']
        return self._get_model_info(sf_account, sf_volume_id)

    def _do_snapshot_create(self, params):
        data = self._issue_api_request('CreateSnapshot', params, version='6.0')
        if (('result' not in data) or ('snapshotID' not in data['result'])):
            msg = _("Failed snapshot create: %s") % data
            raise exception.SolidFireAPIException(msg)
        return data['result']['snapshotID']

    def _set_qos_presets(self, volume):
        qos = {}
        valid_presets = self.sf_qos_dict.keys()

        # First look to see if they included a preset
        presets = [i.value for i in volume.get('volume_metadata')
                   if i.key == 'sf-qos' and i.value in valid_presets]
        if len(presets) > 0:
            if len(presets) > 1:
                LOG.warning(_LW('More than one valid preset was '
                                'detected, using %s'), presets[0])
            qos = self.sf_qos_dict[presets[0]]
        else:
            # look for explicit settings
            for i in volume.get('volume_metadata'):
                if i.key in self.sf_qos_keys:
                    qos[i.key] = int(i.value)
        return qos

    def _set_qos_by_volume_type(self, ctxt, type_id):
        qos = {}
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        qos_specs_id = volume_type.get('qos_specs_id')
        specs = volume_type.get('extra_specs')

        # NOTE(jdg): We prefer the qos_specs association
        # and over-ride any existing
        # extra-specs settings if present
        if qos_specs_id is not None:
            kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
        else:
            kvs = specs

        for key, value in kvs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.sf_qos_keys:
                qos[key] = int(value)
        return qos

    def _get_sf_volume(self, uuid, params):
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' not in data:
            msg = _("Failed to get SolidFire Volume: %s") % data
            raise exception.SolidFireAPIException(msg)

        found_count = 0
        sf_volref = None
        for v in data['result']['volumes']:
            # NOTE(jdg): In the case of "name" we can't
            # update that on manage/import, so we use
            # the uuid attribute
            meta = v.get('attributes')
            alt_id = meta.get('uuid', 'empty')

            if uuid in v['name'] or uuid in alt_id:
                found_count += 1
                sf_volref = v
                LOG.debug("Mapped SolidFire volumeID %(volume_id)s "
                          "to cinder ID %(uuid)s.",
                          {'volume_id': v['volumeID'], 'uuid': uuid})

        if found_count == 0:
            # NOTE(jdg): Previously we would raise here, but there are cases
            # where this might be a cleanup for a failed delete.
            # Until we get better states we'll just log an error
            LOG.error(_LE("Volume %s, not found on SF Cluster."), uuid)

        if found_count > 1:
            LOG.error(_LE("Found %(count)s volumes mapped to id: %(uuid)s."),
                      {'count': found_count,
                       'uuid': uuid})
            raise exception.DuplicateSfVolumeNames(vol_name=uuid)

        return sf_volref

    def _get_sf_snapshots(self, sf_volid=None):
        params = {}
        if sf_volid:
            params = {'volumeID': sf_volid}
        data = self._issue_api_request('ListSnapshots', params, version='6.0')
        if 'result' not in data:
            msg = _("Failed to get SolidFire Snapshot: %s") % data
            raise exception.SolidFireAPIException(msg)
        return data['result']['snapshots']

    def _create_image_volume(self, context,
                             image_meta, image_service,
                             image_id):
        # NOTE(jdg): It's callers responsibility to ensure that
        # the optional properties.virtual_size is set on the image
        # before we get here
        virt_size = int(image_meta['properties'].get('virtual_size'))
        min_sz_in_bytes =\
            math.ceil(virt_size / float(units.Gi)) * float(units.Gi)
        min_sz_in_gig = math.ceil(min_sz_in_bytes / float(units.Gi))

        attributes = {}
        attributes['image_info'] = {}
        attributes['image_info']['image_updated_at'] =\
            image_meta['updated_at'].isoformat()
        attributes['image_info']['image_name'] =\
            image_meta['name']
        attributes['image_info']['image_created_at'] =\
            image_meta['created_at'].isoformat()
        attributes['image_info']['image_id'] = image_meta['id']
        params = {'name': 'OpenStackIMG-%s' % image_id,
                  'accountID': self.template_account_id,
                  'sliceCount': 1,
                  'totalSize': int(min_sz_in_bytes),
                  'enable512e': self.configuration.sf_emulate_512,
                  'attributes': attributes,
                  'qos': {}}

        sf_account = self._issue_api_request(
            'GetAccountByID',
            {'accountID': self.template_account_id})

        template_vol = self._do_volume_create(sf_account, params)
        tvol = {}
        tvol['id'] = image_id
        tvol['provider_location'] = template_vol['provider_location']
        tvol['provider_auth'] = template_vol['provider_auth']

        connector = 'na'
        conn = self.initialize_connection(tvol, connector)
        attach_info = super(SolidFireDriver, self)._connect_device(conn)
        properties = 'na'

        try:
            image_utils.fetch_to_raw(context,
                                     image_service,
                                     image_id,
                                     attach_info['device']['path'],
                                     self.configuration.volume_dd_blocksize,
                                     size=min_sz_in_gig)
        except Exception as exc:
            params['volumeID'] = template_vol['volumeID']
            LOG.error(_LE('Failed image conversion during cache creation: %s'),
                      exc)
            LOG.debug('Removing SolidFire Cache Volume (SF ID): %s',
                      template_vol['volumeID'])

            self._detach_volume(context, attach_info, tvol, properties)
            self._issue_api_request('DeleteVolume', params)
            return

        self._detach_volume(context, attach_info, tvol, properties)
        sf_vol = self._get_sf_volume(image_id, params)
        LOG.debug('Successfully created SolidFire Image Template '
                  'for image-id: %s', image_id)
        return sf_vol

    def _verify_image_volume(self, context, image_meta, image_service):
        # This method just verifies that IF we have a cache volume that
        # it's still up to date and current WRT the image in Glance
        # ie an image-update hasn't occurred since we grabbed it

        # If it's out of date, just delete it and we'll create a new one
        # Any other case we don't care and just return without doing anything

        params = {'accountID': self.template_account_id}
        sf_vol = self._get_sf_volume(image_meta['id'], params)
        if sf_vol is None:
            return

        # Check updated_at field, delete copy and update if needed
        if sf_vol['attributes']['image_info']['image_updated_at'] ==\
                image_meta['updated_at'].isoformat():
            return
        else:
            # Bummer, it's been updated, delete it
            params = {'accountID': self.template_account_id}
            params['volumeID'] = sf_vol['volumeID']
            data = self._issue_api_request('DeleteVolume', params)
            if 'result' not in data:
                msg = _("Failed to delete SolidFire Image-Volume: %s") % data
                raise exception.SolidFireAPIException(msg)

            if not self._create_image_volume(context,
                                             image_meta,
                                             image_service,
                                             image_meta['id']):
                msg = _("Failed to create SolidFire Image-Volume")
                raise exception.SolidFireAPIException(msg)

    def _get_sfaccounts_for_tenant(self, cinder_project_id):
        data = self._issue_api_request('ListAccounts', {})
        if 'result' not in data:
            msg = _("API response: %s") % data
            raise exception.SolidFireAPIException(msg)

        # Note(jdg): On SF we map account-name to OpenStack's tenant ID
        # we use tenantID in here to get secondaries that might exist
        # Also: we expect this to be sorted, so we get the primary first
        # in the list
        return sorted([acc for acc in data['result']['accounts'] if
                       cinder_project_id in acc['username']])

    def _get_all_active_volumes(self, cinder_uuid=None):
        params = {}
        data = self._issue_api_request('ListActiveVolumes',
                                       params)
        if 'result' not in data:
            msg = _("Failed get active SolidFire volumes: %s") % data
            raise exception.SolidFireAPIException(msg)
        if cinder_uuid:
            deleted_vols = ([v for v in data['result']['volumes'] if
                             cinder_uuid in v.name])
        else:
            deleted_vols = [v for v in data['result']['volumes']]
        return deleted_vols

    def _get_all_deleted_volumes(self, cinder_uuid=None):
        params = {}
        data = self._issue_api_request('ListDeletedVolumes',
                                       params)
        if 'result' not in data:
            msg = _("Failed get Deleted SolidFire volumes: %s") % data
            raise exception.SolidFireAPIException(msg)
        if cinder_uuid:
            deleted_vols = ([v for v in data['result']['volumes'] if
                             cinder_uuid in v['name']])
        else:
            deleted_vols = [v for v in data['result']['volumes']]
        return deleted_vols

    def _get_account_create_availability(self, accounts):
        # we'll check both the primary and the secondary
        # if it exists and return whichever one has count
        # available.
        for acc in accounts:
            if self._get_volumes_for_account(
                    acc['accountID']) > self.max_volumes_per_account:
                return acc
        if len(accounts) == 1:
            sfaccount = self._create_sfaccount(accounts[0]['name'] + '_')
            return sfaccount
        return None

    def _get_volumes_for_account(self, sf_account_id, cinder_uuid=None):
        # ListVolumesForAccount gives both Active and Deleted
        # we require the solidfire accountID, uuid of volume
        # is optional
        params = {'accountID': sf_account_id}
        response = self._issue_api_request('ListVolumesForAccount',
                                           params)
        if cinder_uuid:
            vlist = [v for v in response['result']['volumes'] if
                     cinder_uuid in v['name']]
        else:
            vlist = [v for v in response['result']['volumes']]
        vlist = sorted(vlist, key=lambda k: k['volumeID'])
        return vlist

    def clone_image(self, context,
                    volume, image_location,
                    image_meta, image_service):

        # Check out pre-requisites:
        # Is template caching enabled?
        if not self.configuration.sf_allow_template_caching:
            return None, False

        # Is the image owned by this tenant or public?
        if ((not image_meta.get('is_public', False)) and
                (image_meta['owner'] != volume['project_id'])):
                LOG.warning(_LW("Requested image is not "
                                "accessible by current Tenant."))
                return None, False

        # Is virtual_size property set on the image?
        if ((not image_meta.get('properties', None)) or
                (not image_meta['properties'].get('virtual_size', None))):
            LOG.info(_LI('Unable to create cache volume because image: %s '
                         'does not include properties.virtual_size'),
                     image_meta['id'])
            return None, False

        try:
            self._verify_image_volume(context,
                                      image_meta,
                                      image_service)
        except exception.SolidFireAPIException:
            return None, False

        account = self.configuration.sf_template_account_name
        try:
            (data, sfaccount, model) = self._do_clone_volume(image_meta['id'],
                                                             account,
                                                             volume)
        except exception.VolumeNotFound:
            if self._create_image_volume(context,
                                         image_meta,
                                         image_service,
                                         image_meta['id']) is None:
                # We failed, dump out
                return None, False

            # Ok, should be good to go now, try it again
            (data, sfaccount, model) = self._do_clone_volume(image_meta['id'],
                                                             account,
                                                             volume)

        return model, True

    def create_volume(self, volume):
        """Create volume on SolidFire device.

        The account is where CHAP settings are derived from, volume is
        created and exported.  Note that the new volume is immediately ready
        for use.

        One caveat here is that an existing user account must be specified
        in the API call to create a new volume.  We use a set algorithm to
        determine account info based on passed in cinder volume object.  First
        we check to see if the account already exists (and use it), or if it
        does not already exist, we'll go ahead and create it.

        """
        slice_count = 1
        attributes = {}
        qos = {}

        if (self.configuration.sf_allow_tenant_qos and
                volume.get('volume_metadata')is not None):
            qos = self._set_qos_presets(volume)

        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        if type_id is not None:
            qos = self._set_qos_by_volume_type(ctxt, type_id)

        create_time = volume['created_at'].isoformat()
        attributes = {'uuid': volume['id'],
                      'is_clone': 'False',
                      'created_at': create_time}
        if qos:
            for k, v in qos.items():
                attributes[k] = str(v)

        sf_accounts = self._get_sfaccounts_for_tenant(volume['project_id'])
        if not sf_accounts:
            sf_account = self._create_sfaccount(volume['project_id'])
        else:
            sf_account = self._get_account_create_availability(sf_accounts)

        params = {'name': 'UUID-%s' % volume['id'],
                  'accountID': sf_account['accountID'],
                  'sliceCount': slice_count,
                  'totalSize': int(volume['size'] * units.Gi),
                  'enable512e': self.configuration.sf_emulate_512,
                  'attributes': attributes,
                  'qos': qos}

        # NOTE(jdg): Check if we're a migration tgt, if so
        # use the old volume-id here for the SF Name
        migration_status = volume.get('migration_status', None)
        if migration_status and 'target' in migration_status:
            k, v = migration_status.split(':')
            params['name'] = 'UUID-%s' % v
            params['attributes']['migration_uuid'] = volume['id']
            params['attributes']['uuid'] = v
        return self._do_volume_create(sf_account, params)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of an existing volume."""
        (_data, _sfaccount, model) = self._do_clone_volume(
            src_vref['id'],
            src_vref['project_id'],
            volume)

        return model

    def delete_volume(self, volume):
        """Delete SolidFire Volume from device.

        SolidFire allows multiple volumes with same name,
        volumeID is what's guaranteed unique.

        """
        accounts = self._get_sfaccounts_for_tenant(volume['project_id'])
        if accounts is None:
            LOG.error(_LE("Account for Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "delete_volume operation!"), volume['id'])
            LOG.error(_LE("This usually means the volume was never "
                          "successfully created."))
            return

        for acc in accounts:
            sf_vol = self._get_volumes_for_account(acc['accountID'],
                                                   volume['id'])[0]
            if sf_vol:
                break

        if sf_vol is not None:
            params = {'volumeID': sf_vol['volumeID']}
            data = self._issue_api_request('DeleteVolume', params)

            if 'result' not in data:
                msg = _("Failed to delete SolidFire Volume: %s") % data
                raise exception.SolidFireAPIException(msg)
        else:
            LOG.error(_LE("Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "delete_volume operation!"), volume['id'])

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot from the SolidFire cluster."""
        sf_snap_name = 'UUID-%s' % snapshot['id']
        accounts = self._get_sfaccounts_for_tenant(snapshot['project_id'])
        snap = None
        for a in accounts:
            params = {'accountID': a['accountID']}
            sf_vol = self._get_sf_volume(snapshot['volume_id'], params)
            sf_snaps = self._get_sf_snapshots(sf_vol['volumeID'])
            snap = next((s for s in sf_snaps if s["name"] == sf_snap_name),
                        None)
            if snap:
                params = {'snapshotID': snap['snapshotID']}
                data = self._issue_api_request('DeleteSnapshot',
                                               params,
                                               version='6.0')
                if 'result' not in data:
                    msg = (_("Failed to delete SolidFire Snapshot: %s") %
                           data)
                    raise exception.SolidFireAPIException(msg)
                return
        # Make sure it's not "old style" using clones as snaps
        LOG.debug("Snapshot not found, checking old style clones.")
        self.delete_volume(snapshot)

    def create_snapshot(self, snapshot):
        sfaccount = self._get_sfaccount(snapshot['project_id'])
        if sfaccount is None:
            LOG.error(_LE("Account for Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "create_snapshot operation!"), snapshot['volume_id'])

        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(snapshot['volume_id'], params)

        if sf_vol is None:
            raise exception.VolumeNotFound(volume_id=snapshot['volume_id'])
        params = {'volumeID': sf_vol['volumeID'],
                  'name': 'UUID-%s' % snapshot['id']}

        self._do_snapshot_create(params)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from the specified snapshot."""
        (_data, _sfaccount, model) = self._do_clone_volume(
            snapshot['id'],
            snapshot['project_id'],
            volume)

        return model

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data
        """
        if refresh:
            try:
                self._update_cluster_status()
            except exception.SolidFireAPIException:
                pass

        return self.cluster_stats

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)

        if sf_vol is None:
            LOG.error(_LE("Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "extend_volume operation!"), volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        params = {
            'volumeID': sf_vol['volumeID'],
            'totalSize': int(new_size * units.Gi)
        }
        data = self._issue_api_request('ModifyVolume',
                                       params, version='5.0')

        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

    def _update_cluster_status(self):
        """Retrieve status info for the Cluster."""
        params = {}

        # NOTE(jdg): The SF api provides an UNBELIEVABLE amount
        # of stats data, this is just one of the calls
        results = self._issue_api_request('GetClusterCapacity', params)
        if 'result' not in results:
            LOG.error(_LE('Failed to get updated stats'))

        results = results['result']['clusterCapacity']
        free_capacity =\
            results['maxProvisionedSpace'] - results['usedSpace']

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'SolidFire Inc'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'

        data['total_capacity_gb'] =\
            float(results['maxProvisionedSpace'] / units.Gi)

        data['free_capacity_gb'] = float(free_capacity / units.Gi)
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = True
        data['compression_percent'] =\
            results['compressionPercent']
        data['deduplicaton_percent'] =\
            results['deDuplicationPercent']
        data['thin_provision_percent'] =\
            results['thinProvisioningPercent']
        self.cluster_stats = data

    def attach_volume(self, context, volume,
                      instance_uuid, host_name,
                      mountpoint):

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error(_LE("Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "attach_volume operation!"), volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        attributes = sf_vol['attributes']
        attributes['attach_time'] = volume.get('attach_time', None)
        attributes['attached_to'] = instance_uuid
        params = {
            'volumeID': sf_vol['volumeID'],
            'attributes': attributes
        }

        data = self._issue_api_request('ModifyVolume', params)

        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

    def detach_volume(self, context, volume, attachment=None):
        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error(_LE("Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "detach_volume operation!"), volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        attributes = sf_vol['attributes']
        attributes['attach_time'] = None
        attributes['attached_to'] = None
        params = {
            'volumeID': sf_vol['volumeID'],
            'attributes': attributes
        }

        data = self._issue_api_request('ModifyVolume', params)

        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

    def accept_transfer(self, context, volume,
                        new_user, new_project):

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error(_LE("Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "accept_transfer operation!"), volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])
        if new_project != volume['project_id']:
            # do a create_sfaccount here as this tenant
            # may not exist on the cluster yet
            sfaccount = self._create_sfaccount(new_project)

        params = {
            'volumeID': sf_vol['volumeID'],
            'accountID': sfaccount['accountID']
        }
        data = self._issue_api_request('ModifyVolume',
                                       params, version='5.0')

        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        volume['project_id'] = new_project
        volume['user_id'] = new_user
        return self.target_driver.ensure_export(context, volume, None)

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities (Not Used).

        """
        qos = {}
        attributes = {}

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(volume['id'], params)

        if sf_vol is None:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        attributes = sf_vol['attributes']
        attributes['retyped_at'] = timeutils.utcnow().isoformat()
        params = {'volumeID': sf_vol['volumeID']}
        qos = self._set_qos_by_volume_type(ctxt, new_type['id'])

        if qos:
            params['qos'] = qos
            for k, v in qos.items():
                attributes[k] = str(v)
            params['attributes'] = attributes

        self._issue_api_request('ModifyVolume', params)
        return True

    def manage_existing(self, volume, external_ref):
        """Manages an existing SolidFire Volume (import to Cinder).

        Renames the Volume to match the expected name for the volume.
        Also need to consider things like QoS, Emulation, account/tenant.
        """

        sfid = external_ref.get('source-id', None)
        sfname = external_ref.get('name', None)
        if sfid is None:
            raise exception.SolidFireAPIException(_("Manage existing volume "
                                                    "requires 'source-id'."))

        # First get the volume on the SF cluster (MUST be active)
        params = {'startVolumeID': sfid,
                  'limit': 1}
        data = self._issue_api_request('ListActiveVolumes', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)
        sf_ref = data['result']['volumes'][0]

        sfaccount = self._create_sfaccount(volume['project_id'])

        attributes = {}
        qos = {}
        if (self.configuration.sf_allow_tenant_qos and
                volume.get('volume_metadata')is not None):
            qos = self._set_qos_presets(volume)

        ctxt = context.get_admin_context()
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            qos = self._set_qos_by_volume_type(ctxt, type_id)

        import_time = volume['created_at'].isoformat()
        attributes = {'uuid': volume['id'],
                      'is_clone': 'False',
                      'os_imported_at': import_time,
                      'old_name': sfname}
        if qos:
            for k, v in qos.items():
                attributes[k] = str(v)

        params = {'name': volume['name'],
                  'volumeID': sf_ref['volumeID'],
                  'accountID': sfaccount['accountID'],
                  'enable512e': self.configuration.sf_emulate_512,
                  'attributes': attributes,
                  'qos': qos}

        data = self._issue_api_request('ModifyVolume',
                                       params, version='5.0')
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        return self._get_model_info(sfaccount, sf_ref['volumeID'])

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing LV for manage_existing.

        existing_ref is a dictionary of the form:
        {'name': <name of existing volume on SF Cluster>}
        """

        sfid = external_ref.get('source-id', None)
        if sfid is None:
            raise exception.SolidFireAPIException(_("Manage existing get size "
                                                    "requires 'id'."))

        params = {'startVolumeID': int(sfid),
                  'limit': 1}
        data = self._issue_api_request('ListActiveVolumes', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)
        sf_ref = data['result']['volumes'][0]
        return int(sf_ref['totalSize']) / int(units.Gi)

    def unmanage(self, volume):
        """Mark SolidFire Volume as unmanaged (export from Cinder)."""

        sfaccount = self._get_sfaccount(volume['project_id'])
        if sfaccount is None:
            LOG.error(_LE("Account for Volume ID %s was not found on "
                          "the SolidFire Cluster while attempting "
                          "unmanage operation!"), volume['id'])
            raise exception.SolidFireAPIException(_("Failed to find account "
                                                    "for volume."))

        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        export_time = timeutils.utcnow().isoformat()
        attributes = sf_vol['attributes']
        attributes['os_exported_at'] = export_time
        params = {'volumeID': int(sf_vol['volumeID']),
                  'attributes': attributes}

        data = self._issue_api_request('ModifyVolume',
                                       params, version='5.0')
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

    # #### Interface methods for transport layer #### #

    # TODO(jdg): SolidFire can mix and do iSCSI and FC on the
    # same cluster, we'll modify these later to check based on
    # the volume info if we need an FC target driver or an
    # iSCSI target driver
    def ensure_export(self, context, volume):
        return self.target_driver.ensure_export(context, volume, None)

    def create_export(self, context, volume):
        return self.target_driver.create_export(
            context,
            volume,
            None)

    def remove_export(self, context, volume):
        return self.target_driver.remove_export(context, volume)

    def initialize_connection(self, volume, connector):
        return self.target_driver.initialize_connection(volume, connector)

    def validate_connector(self, connector):
        return self.target_driver.validate_connector(connector)

    def terminate_connection(self, volume, connector, **kwargs):
        return self.target_driver.terminate_connection(volume, connector,
                                                       **kwargs)


class SolidFireISCSI(iscsi_driver.SanISCSITarget):
    def __init__(self, *args, **kwargs):
        super(SolidFireISCSI, self).__init__(*args, **kwargs)
        self.sf_driver = kwargs.get('solidfire_driver')

    def _do_iscsi_export(self, volume):
        sfaccount = self.sf_driver._get_sfaccount(volume['project_id'])
        model_update = {}
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                            sfaccount['targetSecret']))

        return model_update

    def create_export(self, context, volume, volume_path):
        return self._do_iscsi_export(volume)

    def ensure_export(self, context, volume, volume_path):
        try:
            return self._do_iscsi_export(volume)
        except exception.SolidFireAPIException:
            return None

    # Following are abc's that we make sure are caught and
    # paid attention to.  In our case we don't use them
    # so just stub them out here.
    def remove_export(self, context, volume):
        pass

    def terminate_connection(self, volume, connector, **kwargs):
        pass
