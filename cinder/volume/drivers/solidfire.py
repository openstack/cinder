# All Rights Reserved.
# Copyright 2013 SolidFire Inc

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

import inspect
import json
import math
import random
import re
import socket
import string
import time
import warnings

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import timeutils
from oslo_utils import units
import requests
from requests.packages.urllib3 import exceptions
import six

from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
from cinder import interface
from cinder.objects import fields
from cinder import utils
from cinder.volume import configuration
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume.targets import iscsi as iscsi_driver
from cinder.volume import utils as vol_utils
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
               help='Create SolidFire accounts with this prefix. Any string '
                    'can be used here, but the string \"hostname\" is special '
                    'and will create a prefix using the cinder node hostname '
                    '(previous default behavior).  The default is NO prefix.'),

    cfg.StrOpt('sf_volume_prefix',
               default='UUID-',
               help='Create SolidFire volumes with this prefix. Volume names '
                    'are of the form <sf_volume_prefix><cinder-volume-id>.  '
                    'The default is to use a prefix of \'UUID-\'.'),

    cfg.StrOpt('sf_template_account_name',
               default='openstack-vtemplate',
               help='Account name on the SolidFire Cluster to use as owner of '
                    'template/cache volumes (created if does not exist).'),

    cfg.BoolOpt('sf_allow_template_caching',
                default=True,
                help='Create an internal cache of copy of images when '
                     'a bootable volume is created to eliminate fetch from '
                     'glance and qemu-conversion on subsequent calls.'),

    cfg.StrOpt('sf_svip',
               help='Overrides default cluster SVIP with the one specified. '
                    'This is required or deployments that have implemented '
                    'the use of VLANs for iSCSI networks in their cloud.'),

    cfg.BoolOpt('sf_enable_volume_mapping',
                default=True,
                help='Create an internal mapping of volume IDs and account.  '
                     'Optimizes lookups and performance at the expense of '
                     'memory, very large deployments may want to consider '
                     'setting to False.'),

    cfg.PortOpt('sf_api_port',
                default=443,
                help='SolidFire API port. Useful if the device api is behind '
                     'a proxy on a different port.'),

    cfg.BoolOpt('sf_enable_vag',
                default=False,
                help='Utilize volume access groups on a per-tenant basis.')]

CONF = cfg.CONF
CONF.register_opts(sf_opts, group=configuration.SHARED_CONF_GROUP)

# SolidFire API Error Constants
xExceededLimit = 'xExceededLimit'
xAlreadyInVolumeAccessGroup = 'xAlreadyInVolumeAccessGroup'
xVolumeAccessGroupIDDoesNotExist = 'xVolumeAccessGroupIDDoesNotExist'
xNotInVolumeAccessGroup = 'xNotInVolumeAccessGroup'


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


@interface.volumedriver
class SolidFireDriver(san.SanISCSIDriver):
    """OpenStack driver to enable SolidFire cluster.

    .. code-block:: default

      Version history:
          1.0 - Initial driver
          1.1 - Refactor, clone support, qos by type and minor bug fixes
          1.2 - Add xfr and retype support
          1.2.1 - Add export/import support
          1.2.2 - Catch VolumeNotFound on accept xfr
          2.0.0 - Move from httplib to requests
          2.0.1 - Implement SolidFire Snapshots
          2.0.2 - Implement secondary account
          2.0.3 - Implement cluster pairing
          2.0.4 - Implement volume replication
          2.0.5 - Try and deal with the stupid retry/clear issues from objects
                  and tflow
          2.0.6 - Add a lock decorator around the clone_image method
          2.0.7 - Add scaled IOPS
          2.0.8 - Add active status filter to get volume ops
          2.0.9 - Always purge on delete volume
          2.0.10 - Add response to debug on retryable errors

    """

    VERSION = '2.0.10'

    # ThirdPartySystems wiki page
    CI_WIKI_NAME = "NetApp_SolidFire_CI"

    driver_prefix = 'solidfire'

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
    sf_scale_qos_keys = ['scaledIOPS', 'scaleMin', 'scaleMax', 'scaleBurst']
    sf_iops_lim_min = {'minIOPS': 100, 'maxIOPS': 100, 'burstIOPS': 100}
    sf_iops_lim_max = {'minIOPS': 15000,
                       'maxIOPS': 200000,
                       'burstIOPS': 200000}
    cluster_stats = {}
    retry_exc_tuple = (exception.SolidFireRetryableException,
                       requests.exceptions.ConnectionError)
    retryable_errors = ['xDBVersionMismatch',
                        'xMaxSnapshotsPerVolumeExceeded',
                        'xMaxClonesPerVolumeExceeded',
                        'xMaxSnapshotsPerNodeExceeded',
                        'xMaxClonesPerNodeExceeded',
                        'xSliceNotRegistered',
                        'xNotReadyForIO']

    def __init__(self, *args, **kwargs):
        super(SolidFireDriver, self).__init__(*args, **kwargs)
        self.failed_over_id = kwargs.get('active_backend_id', None)
        self.active_cluster_info = {}
        self.configuration.append_config_values(sf_opts)
        self.template_account_id = None
        self.max_volumes_per_account = 1990
        self.volume_map = {}
        self.cluster_pairs = []
        self.replication_enabled = False
        self.failed_over = False
        self.target_driver = SolidFireISCSI(solidfire_driver=self,
                                            configuration=self.configuration)
        if self.failed_over_id:
            remote_info = self._get_remote_info_by_id(self.failed_over_id)
            if remote_info:
                self._set_active_cluster_info(remote_info['endpoint'])
            else:
                LOG.error('Failed to initialize SolidFire driver to '
                          'a remote cluster specified at id: %s',
                          self.failed_over_id)
        else:
            self._set_active_cluster_info()

        try:
            self._update_cluster_status()
        except exception.SolidFireAPIException:
            pass

        if self.configuration.sf_allow_template_caching:
            account = self.configuration.sf_template_account_name
            self.template_account_id = self._create_template_account(account)

        if not self.failed_over_id:
            self._set_cluster_pairs()

    def locked_image_id_operation(f, external=False):
        def lvo_inner1(inst, *args, **kwargs):
            lock_tag = inst.driver_prefix
            call_args = inspect.getcallargs(f, inst, *args, **kwargs)

            if call_args.get('image_meta'):
                image_id = call_args['image_meta']['id']
            else:
                err_msg = _('The decorated method must accept image_meta.')
                raise exception.VolumeBackendAPIException(data=err_msg)

            @utils.synchronized('%s-%s' % (lock_tag, image_id),
                                external=external)
            def lvo_inner2():
                return f(inst, *args, **kwargs)
            return lvo_inner2()
        return lvo_inner1

    def locked_source_id_operation(f, external=False):
        def lvo_inner1(inst, *args, **kwargs):
            lock_tag = inst.driver_prefix
            call_args = inspect.getcallargs(f, inst, *args, **kwargs)
            src_arg = call_args.get('source', None)
            if src_arg and src_arg.get('id', None):
                source_id = call_args['source']['id']
            else:
                err_msg = _('The decorated method must accept src_uuid.')
                raise exception.VolumeBackendAPIException(message=err_msg)

            @utils.synchronized('%s-%s' % (lock_tag, source_id),
                                external=external)
            def lvo_inner2():
                return f(inst, *args, **kwargs)
            return lvo_inner2()
        return lvo_inner1

    def __getattr__(self, attr):
        if hasattr(self.target_driver, attr):
            return getattr(self.target_driver, attr)
        else:
            msg = _('Attribute: %s not found.') % attr
            raise NotImplementedError(msg)

    def _get_remote_info_by_id(self, backend_id):
        remote_info = None
        for rd in self.configuration.get('replication_device', []):
            if rd.get('backend_id', None) == backend_id:
                remote_endpoint = self._build_endpoint_info(**rd)
                remote_info = self._get_remote_cluster_info(remote_endpoint)
                remote_info['endpoint'] = remote_endpoint
                if not remote_info['endpoint']['svip']:
                    remote_info['endpoint']['svip'] = (
                        remote_info['svip'] + ':3260')
        return remote_info

    def _create_remote_pairing(self, remote_device):
        try:
            pairing_info = self._issue_api_request('StartClusterPairing',
                                                   {}, version='8.0')['result']
            pair_id = self._issue_api_request(
                'CompleteClusterPairing',
                {'clusterPairingKey': pairing_info['clusterPairingKey']},
                version='8.0',
                endpoint=remote_device['endpoint'])['result']['clusterPairID']
        except exception.SolidFireAPIException as ex:
            if 'xPairingAlreadExists' in ex.msg:
                LOG.debug('Pairing already exists during init.')
            else:
                with excutils.save_and_reraise_exception():
                    LOG.error('Cluster pairing failed: %s', ex.msg)
        LOG.debug(('Initialized Cluster pair with ID: %s'), pair_id)
        remote_device['clusterPairID'] = pair_id
        return pair_id

    def _get_remote_cluster_info(self, remote_endpoint):
        return self._issue_api_request(
            'GetClusterInfo',
            {},
            endpoint=remote_endpoint)['result']['clusterInfo']

    def _set_cluster_pairs(self):
        if not self.configuration.get('replication_device', None):
            self.replication = False
            return

        existing_pairs = self._issue_api_request(
            'ListClusterPairs',
            {},
            version='8.0')['result']['clusterPairs']

        remote_pair = {}
        for rd in self.configuration.get('replication_device', []):
            remote_endpoint = self._build_endpoint_info(**rd)
            remote_info = self._get_remote_cluster_info(remote_endpoint)
            remote_info['endpoint'] = remote_endpoint
            if not remote_info['endpoint']['svip']:
                remote_info['endpoint']['svip'] = remote_info['svip'] + ':3260'

            for ep in existing_pairs:
                if rd['backend_id'] == ep['mvip']:
                    remote_pair = ep
                    LOG.debug("Found remote pair: %s", remote_pair)
                    remote_info['clusterPairID'] = ep['clusterPairID']
                    break

            if not remote_pair:
                # NOTE(jdg): create_remote_pairing sets the
                # clusterPairID in remote_info for us
                self._create_remote_pairing(remote_info)
            self.cluster_pairs.append(remote_info)
            LOG.debug("Setting replication_enabled to True.")
            self.replication_enabled = True

    def _set_active_cluster_info(self, endpoint=None):
        if not endpoint:
            self.active_cluster_info['endpoint'] = self._build_endpoint_info()
        else:
            self.active_cluster_info['endpoint'] = endpoint

        for k, v in self._issue_api_request(
                'GetClusterInfo',
                {})['result']['clusterInfo'].items():
            self.active_cluster_info[k] = v

        # Add a couple extra things that are handy for us
        self.active_cluster_info['clusterAPIVersion'] = (
            self._issue_api_request('GetClusterVersionInfo',
                                    {})['result']['clusterAPIVersion'])
        if self.configuration.get('sf_svip', None):
            self.active_cluster_info['svip'] = (
                self.configuration.get('sf_svip'))

    def _create_provider_id_string(self,
                                   resource_id,
                                   account_or_vol_id):
        # NOTE(jdg): We use the same format, but in the case
        # of snapshots, we don't have an account id, we instead
        # swap that with the parent volume id
        return "%s %s %s" % (resource_id,
                             account_or_vol_id,
                             self.active_cluster_info['uuid'])

    def _init_snapshot_mappings(self, srefs):
        updates = []
        sf_snaps = self._issue_api_request(
            'ListSnapshots', {}, version='6.0')['result']['snapshots']
        for s in srefs:
            seek_name = '%s%s' % (self.configuration.sf_volume_prefix, s['id'])
            sfsnap = next(
                (ss for ss in sf_snaps if ss['name'] == seek_name), None)
            if sfsnap:
                id_string = self._create_provider_id_string(
                    sfsnap['snapshotID'],
                    sfsnap['volumeID'])
                if s.get('provider_id') != id_string:
                    updates.append(
                        {'id': s['id'],
                         'provider_id': id_string})
        return updates

    def _init_volume_mappings(self, vrefs):
        updates = []
        sf_vols = self._issue_api_request('ListActiveVolumes',
                                          {})['result']['volumes']
        self.volume_map = {}
        for v in vrefs:
            seek_name = '%s%s' % (self.configuration.sf_volume_prefix, v['id'])
            sfvol = next(
                (sv for sv in sf_vols if sv['name'] == seek_name), None)
            if sfvol:
                if v.get('provider_id', 'nil') != sfvol['volumeID']:
                    updates.append(
                        {'id': v['id'],
                         'provider_id': self._create_provider_id_string(
                             sfvol['volumeID'], sfvol['accountID'])})

        return updates

    def update_provider_info(self, vrefs, snaprefs):
        volume_updates = self._init_volume_mappings(vrefs)
        snapshot_updates = self._init_snapshot_mappings(snaprefs)
        return (volume_updates, snapshot_updates)

    def _create_template_account(self, account_name):
        # We raise an API exception if the account doesn't exist

        # We need to take account_prefix settings into consideration
        # This just uses the same method to do template account create
        # as we use for any other OpenStack account
        account_name = self._get_sf_account_name(account_name)
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

        endpoint['mvip'] = (
            kwargs.get('mvip', self.configuration.san_ip))
        endpoint['login'] = (
            kwargs.get('login', self.configuration.san_login))
        endpoint['passwd'] = (
            kwargs.get('passwd', self.configuration.san_password))
        endpoint['port'] = (
            kwargs.get('port', self.configuration.sf_api_port))
        endpoint['url'] = 'https://%s:%s' % (endpoint['mvip'],
                                             endpoint['port'])
        endpoint['svip'] = kwargs.get('svip', self.configuration.sf_svip)
        if not endpoint.get('mvip', None) and kwargs.get('backend_id', None):
            endpoint['mvip'] = kwargs.get('backend_id')
        return endpoint

    @retry(retry_exc_tuple, tries=6)
    def _issue_api_request(self, method, params, version='1.0', endpoint=None):
        if params is None:
            params = {}
        if endpoint is None:
            endpoint = self.active_cluster_info['endpoint']

        payload = {'method': method, 'params': params}
        url = '%s/json-rpc/%s/' % (endpoint['url'], version)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", exceptions.InsecureRequestWarning)
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
            LOG.debug("API response: %s", response)
            raise exception.SolidFireRetryableException(message=msg)

        if 'error' in response:
            msg = _('API response: %s') % response
            raise exception.SolidFireAPIException(msg)

        return response

    def _get_active_volumes_by_sfaccount(self, account_id, endpoint=None):
        return [v for v in self._get_volumes_by_sfaccount(account_id, endpoint)
                if v['status'] == "active"]

    def _get_volumes_by_sfaccount(self, account_id, endpoint=None):
        """Get all volumes on cluster for specified account."""
        params = {'accountID': account_id}
        return self._issue_api_request(
            'ListVolumesForAccount',
            params,
            endpoint=endpoint)['result']['volumes']

    def _get_sfaccount_by_name(self, sf_account_name, endpoint=None):
        """Get SolidFire account object by name."""
        sfaccount = None
        params = {'username': sf_account_name}
        try:
            data = self._issue_api_request('GetAccountByName',
                                           params,
                                           endpoint=endpoint)
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
            self._issue_api_request('AddAccount', params)
            sfaccount = self._get_sfaccount_by_name(sf_account_name)

        return sfaccount

    def _generate_random_string(self, length):
        """Generates random_string to use for CHAP password."""

        char_set = string.ascii_uppercase + string.digits
        return ''.join(random.sample(char_set, length))

    def _get_model_info(self, sfaccount, sf_volume_id, endpoint=None):
        """Gets the connection info for specified account and volume."""
        if endpoint:
            iscsi_portal = endpoint['svip']
        else:
            iscsi_portal = self.active_cluster_info['svip']

        if ':' not in iscsi_portal:
            iscsi_portal += ':3260'

        chap_secret = sfaccount['targetSecret']

        found_volume = False
        iteration_count = 0
        while not found_volume and iteration_count < 600:
            volume_list = self._get_volumes_by_sfaccount(
                sfaccount['accountID'], endpoint=endpoint)
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
            LOG.error('Failed to retrieve volume SolidFire-'
                      'ID: %s in get_by_account!', sf_volume_id)
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
        model_update['provider_id'] = (
            self._create_provider_id_string(sf_volume_id,
                                            sfaccount['accountID']))
        return model_update

    def _snapshot_discovery(self, src_uuid, params, vref):
        # NOTE(jdg): First check the SF snapshots
        # if we don't find a snap by the given name, just move on to check
        # volumes.  This may be a running system that was updated from
        # before we did snapshots, so need to check both
        is_clone = False
        sf_vol = None
        snap_name = '%s%s' % (self.configuration.sf_volume_prefix, src_uuid)
        snaps = self._get_sf_snapshots()
        snap = next((s for s in snaps if s["name"] == snap_name), None)
        if snap:
            params['snapshotID'] = int(snap['snapshotID'])
            params['volumeID'] = int(snap['volumeID'])
            params['newSize'] = int(vref['size'] * units.Gi)
        else:
            sf_vol = self._get_sf_volume(src_uuid)
            if sf_vol is None:
                raise exception.VolumeNotFound(volume_id=src_uuid)
            params['volumeID'] = int(sf_vol['volumeID'])
            params['newSize'] = int(vref['size'] * units.Gi)
            is_clone = True
        return params, is_clone, sf_vol

    def _do_clone_volume(self, src_uuid,
                         vref, sf_src_snap=None):
        """Create a clone of an existing volume or snapshot."""
        attributes = {}
        sf_account = self._get_create_account(vref['project_id'])
        params = {'name': '%(prefix)s%(id)s' %
                  {'prefix': self.configuration.sf_volume_prefix,
                   'id': vref['id']},
                  'newAccountID': sf_account['accountID']}

        is_clone = False
        sf_vol = None
        if sf_src_snap:
            # In some scenarios we are passed the snapshot information that we
            # are supposed to clone.
            params['snapshotID'] = sf_src_snap['snapshotID']
            params['volumeID'] = sf_src_snap['volumeID']
            params['newSize'] = int(vref['size'] * units.Gi)
        else:
            params, is_clone, sf_vol = self._snapshot_discovery(src_uuid,
                                                                params,
                                                                vref)
        data = self._issue_api_request('CloneVolume', params, version='6.0')
        if (('result' not in data) or ('volumeID' not in data['result'])):
            msg = _("API response: %s") % data
            raise exception.SolidFireAPIException(msg)

        sf_volume_id = data['result']['volumeID']

        # NOTE(jdg): all attributes are copied via clone, need to do an update
        # to set any that were provided
        qos = self._retrieve_qos_setting(vref)
        params = {'volumeID': sf_volume_id}
        if qos:
            params['qos'] = qos
        create_time = vref['created_at'].isoformat()
        attributes = {'uuid': vref['id'],
                      'is_clone': 'True',
                      'src_uuid': src_uuid,
                      'created_at': create_time}

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

    def _do_volume_create(self, sf_account, params, endpoint=None):
        params['accountID'] = sf_account['accountID']
        sf_volid = self._issue_api_request(
            'CreateVolume', params, endpoint=endpoint)['result']['volumeID']
        return self._get_model_info(sf_account, sf_volid, endpoint=endpoint)

    def _do_snapshot_create(self, params):
        model_update = {}
        snapshot_id = self._issue_api_request(
            'CreateSnapshot', params, version='6.0')['result']['snapshotID']
        snaps = self._get_sf_snapshots()
        snap = (
            next((s for s in snaps if int(s["snapshotID"]) ==
                  int(snapshot_id)), None))
        model_update['provider_id'] = (
            self._create_provider_id_string(snap['snapshotID'],
                                            snap['volumeID']))
        return model_update

    def _set_qos_presets(self, volume):
        qos = {}
        valid_presets = self.sf_qos_dict.keys()

        # First look to see if they included a preset
        presets = [i.value for i in volume.get('volume_metadata')
                   if i.key == 'sf-qos' and i.value in valid_presets]
        if len(presets) > 0:
            if len(presets) > 1:
                LOG.warning('More than one valid preset was '
                            'detected, using %s', presets[0])
            qos = self.sf_qos_dict[presets[0]]
        else:
            # look for explicit settings
            for i in volume.get('volume_metadata'):
                if i.key in self.sf_qos_keys:
                    qos[i.key] = int(i.value)
        return qos

    def _set_qos_by_volume_type(self, ctxt, type_id, vol_size):
        qos = {}
        scale_qos = {}
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        qos_specs_id = volume_type.get('qos_specs_id')
        specs = volume_type.get('extra_specs')

        # NOTE(jdg): We prefer the qos_specs association
        # and over-ride any existing
        # extra-specs settings if present
        if qos_specs_id is not None:
            # Policy changes require admin context to get QoS specs
            # at the object layer (base:get_by_id), we can either
            # explicitly promote here, or pass in a context of None
            # and let the qos_specs api get an admin context for us
            # personally I prefer explicit, so here ya go.
            admin_ctxt = context.get_admin_context()
            kvs = qos_specs.get_qos_specs(admin_ctxt, qos_specs_id)['specs']
        else:
            kvs = specs

        for key, value in kvs.items():
            if ':' in key:
                fields = key.split(':')
                key = fields[1]
            if key in self.sf_qos_keys:
                qos[key] = int(value)
            if key in self.sf_scale_qos_keys:
                scale_qos[key] = value

        # look for the 'scaledIOPS' key and scale QoS if set
        if 'scaledIOPS' in scale_qos:
            scale_qos.pop('scaledIOPS')
            for key, value in scale_qos.items():
                if key == 'scaleMin':
                    qos['minIOPS'] = (qos['minIOPS'] +
                                      (int(value) * (vol_size - 1)))
                elif key == 'scaleMax':
                    qos['maxIOPS'] = (qos['maxIOPS'] +
                                      (int(value) * (vol_size - 1)))
                elif key == 'scaleBurst':
                    qos['burstIOPS'] = (qos['burstIOPS'] +
                                        (int(value) * (vol_size - 1)))
        # Cap the IOPS values at their limits
        capped = False
        for key, value in qos.items():
            if value > self.sf_iops_lim_max[key]:
                qos[key] = self.sf_iops_lim_max[key]
                capped = True
            if value < self.sf_iops_lim_min[key]:
                qos[key] = self.sf_iops_lim_min[key]
                capped = True
        if capped:
            LOG.debug("A SolidFire QoS value was capped at the defined limits")
        # Check that minIOPS <= maxIOPS <= burstIOPS
        if (qos.get('minIOPS', 0) > qos.get('maxIOPS', 0) or
                qos.get('maxIOPS', 0) > qos.get('burstIOPS', 0)):
            msg = (_("Scaled QoS error. Must be minIOPS <= maxIOPS <= "
                     "burstIOPS. Currently: Min: %(min)s, Max: "
                     "%(max)s, Burst: %(burst)s.") %
                   {"min": qos['minIOPS'],
                    "max": qos['maxIOPS'],
                    "burst": qos['burstIOPS']})
            raise exception.InvalidQoSSpecs(reason=msg)
        return qos

    def _get_sf_volume(self, uuid, params=None):
        if params:
            vols = [v for v in self._issue_api_request(
                'ListVolumesForAccount', params)['result']['volumes'] if
                v['status'] == "active"]
        else:
            vols = self._issue_api_request(
                'ListActiveVolumes', params)['result']['volumes']

        found_count = 0
        sf_volref = None
        for v in vols:
            # NOTE(jdg): In the case of "name" we can't
            # update that on manage/import, so we use
            # the uuid attribute
            meta = v.get('attributes')
            alt_id = ''
            if meta:
                alt_id = meta.get('uuid', '')

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
            LOG.error("Volume %s, not found on SF Cluster.", uuid)

        if found_count > 1:
            LOG.error("Found %(count)s volumes mapped to id: %(uuid)s.",
                      {'count': found_count,
                       'uuid': uuid})
            raise exception.DuplicateSfVolumeNames(vol_name=uuid)

        return sf_volref

    def _get_sf_snapshots(self, sf_volid=None):
        params = {}
        if sf_volid:
            params = {'volumeID': sf_volid}
        return self._issue_api_request(
            'ListSnapshots', params, version='6.0')['result']['snapshots']

    def _create_image_volume(self, context,
                             image_meta, image_service,
                             image_id):
        with image_utils.TemporaryImages.fetch(image_service,
                                               context,
                                               image_id) as tmp_image:
            data = image_utils.qemu_img_info(tmp_image)
            fmt = data.file_format
            if fmt is None:
                raise exception.ImageUnacceptable(
                    reason=_("'qemu-img info' parsing failed."),
                    image_id=image_id)

            backing_file = data.backing_file
            if backing_file is not None:
                raise exception.ImageUnacceptable(
                    image_id=image_id,
                    reason=_("fmt=%(fmt)s backed by:%(backing_file)s")
                    % {'fmt': fmt, 'backing_file': backing_file, })

            virtual_size = int(math.ceil(float(data.virtual_size) / units.Gi))
            attributes = {}
            attributes['image_info'] = {}
            attributes['image_info']['image_updated_at'] = (
                image_meta['updated_at'].isoformat())
            attributes['image_info']['image_name'] = (
                image_meta['name'])
            attributes['image_info']['image_created_at'] = (
                image_meta['created_at'].isoformat())
            attributes['image_info']['image_id'] = image_meta['id']
            params = {'name': 'OpenStackIMG-%s' % image_id,
                      'accountID': self.template_account_id,
                      'sliceCount': 1,
                      'totalSize': int(virtual_size * units.Gi),
                      'enable512e': self.configuration.sf_emulate_512,
                      'attributes': attributes,
                      'qos': {}}

            sf_account = self._issue_api_request(
                'GetAccountByID',
                {'accountID': self.template_account_id})['result']['account']
            template_vol = self._do_volume_create(sf_account, params)

            tvol = {}
            tvol['id'] = image_id
            tvol['provider_location'] = template_vol['provider_location']
            tvol['provider_auth'] = template_vol['provider_auth']

            try:
                connector = {'multipath': False}
                conn = self.initialize_connection(tvol, connector)
                attach_info = super(SolidFireDriver, self)._connect_device(
                    conn)
                properties = 'na'
                image_utils.convert_image(tmp_image,
                                          attach_info['device']['path'],
                                          'raw',
                                          run_as_root=True)
                data = image_utils.qemu_img_info(attach_info['device']['path'],
                                                 run_as_root=True)
                if data.file_format != 'raw':
                    raise exception.ImageUnacceptable(
                        image_id=image_id,
                        reason=_("Converted to %(vol_format)s, but format is "
                                 "now %(file_format)s") % {'vol_format': 'raw',
                                                           'file_format': data.
                                                           file_format})
            except Exception as exc:
                vol = self._get_sf_volume(image_id)
                LOG.error('Failed image conversion during '
                          'cache creation: %s',
                          exc)
                LOG.debug('Removing SolidFire Cache Volume (SF ID): %s',
                          vol['volumeID'])
                self._detach_volume(context, attach_info, tvol, properties)
                self._issue_api_request('DeleteVolume', params)
                self._issue_api_request('PurgeDeletedVolume', params)
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
        if not sf_vol:
            self._create_image_volume(context,
                                      image_meta,
                                      image_service,
                                      image_meta['id'])
            return

        if sf_vol['attributes']['image_info']['image_updated_at'] != (
                image_meta['updated_at'].isoformat()):
            params = {'accountID': self.template_account_id}
            params['volumeID'] = sf_vol['volumeID']
            self._issue_api_request('DeleteVolume', params)
            self._issue_api_request('PurgeDeletedVolume', params)
            self._create_image_volume(context,
                                      image_meta,
                                      image_service,
                                      image_meta['id'])

    def _get_sfaccounts_for_tenant(self, cinder_project_id):
        accounts = self._issue_api_request(
            'ListAccounts', {})['result']['accounts']

        # Note(jdg): On SF we map account-name to OpenStack's tenant ID
        # we use tenantID in here to get secondaries that might exist
        # Also: we expect this to be sorted, so we get the primary first
        # in the list
        return sorted([acc for acc in accounts if
                       cinder_project_id in acc['username']])

    def _get_all_active_volumes(self, cinder_uuid=None):
        params = {}
        volumes = self._issue_api_request('ListActiveVolumes',
                                          params)['result']['volumes']
        if cinder_uuid:
            vols = ([v for v in volumes if
                     cinder_uuid in v.name])
        else:
            vols = [v for v in volumes]

        return vols

    def _get_all_deleted_volumes(self, cinder_uuid=None):
        params = {}
        vols = self._issue_api_request('ListDeletedVolumes',
                                       params)['result']['volumes']
        if cinder_uuid:
            deleted_vols = ([v for v in vols if
                             cinder_uuid in v['name']])
        else:
            deleted_vols = [v for v in vols]
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

    def _get_create_account(self, proj_id):
        # Retrieve SolidFire accountID to be used for creating volumes.
        sf_accounts = self._get_sfaccounts_for_tenant(proj_id)
        if not sf_accounts:
            sf_account = self._create_sfaccount(proj_id)
        else:
            # Check availability for creates
            sf_account = self._get_account_create_availability(sf_accounts)
            if not sf_account:
                msg = _('Volumes/account exceeded on both primary and '
                        'secondary SolidFire accounts.')
                raise exception.SolidFireDriverException(msg)
        return sf_account

    def _get_volumes_for_account(self, sf_account_id, cinder_uuid=None):
        # ListVolumesForAccount gives both Active and Deleted
        # we require the solidfire accountID, uuid of volume
        # is optional
        vols = self._get_active_volumes_by_sfaccount(sf_account_id)
        if cinder_uuid:
            vlist = [v for v in vols if
                     cinder_uuid in v['name']]
        else:
            vlist = [v for v in vols]
        vlist = sorted(vlist, key=lambda k: k['volumeID'])
        return vlist

    def _create_vag(self, iqn, vol_id=None):
        """Create a volume access group(vag).

           Returns the vag_id.
        """
        vag_name = re.sub('[^0-9a-zA-Z]+', '-', iqn)
        params = {'name': vag_name,
                  'initiators': [iqn],
                  'volumes': [vol_id],
                  'attributes': {'openstack': True}}
        try:
            result = self._issue_api_request('CreateVolumeAccessGroup',
                                             params,
                                             version='7.0')
            return result['result']['volumeAccessGroupID']
        except exception.SolidFireAPIException as error:
            if xExceededLimit in error.msg:
                if iqn in error.msg:
                    # Initiator double registered.
                    return self._safe_create_vag(iqn, vol_id)
                else:
                    # VAG limit reached. Purge and start over.
                    self._purge_vags()
                    return self._safe_create_vag(iqn, vol_id)
            else:
                raise

    def _safe_create_vag(self, iqn, vol_id=None):
        # Potential race condition with simultaneous volume attaches to the
        # same host. To help avoid this, VAG creation makes a best attempt at
        # finding and using an existing VAG.

        vags = self._get_vags_by_name(iqn)
        if vags:
            # Filter through the vags and find the one with matching initiator
            vag = next((v for v in vags if iqn in v['initiators']), None)
            if vag:
                return vag['volumeAccessGroupID']
            else:
                # No matches, use the first result, add initiator IQN.
                vag_id = vags[0]['volumeAccessGroupID']
                return self._add_initiator_to_vag(iqn, vag_id)
        return self._create_vag(iqn, vol_id)

    def _base_get_vags(self):
        params = {}
        vags = self._issue_api_request(
            'ListVolumeAccessGroups',
            params,
            version='7.0')['result']['volumeAccessGroups']
        return vags

    def _get_vags_by_name(self, iqn):
        """Retrieve SolidFire volume access group objects by name.

           Returns an array of vags with a matching name value.
           Returns an empty array if there are no matches.
        """
        vags = self._base_get_vags()
        vag_name = re.sub('[^0-9a-zA-Z]+', '-', iqn)
        matching_vags = [vag for vag in vags if vag['name'] == vag_name]
        return matching_vags

    def _add_initiator_to_vag(self, iqn, vag_id):
        # Added a vag_id return as there is a chance that we might have to
        # create a new VAG if our target VAG is deleted underneath us.
        params = {"initiators": [iqn],
                  "volumeAccessGroupID": vag_id}
        try:
            self._issue_api_request('AddInitiatorsToVolumeAccessGroup',
                                    params,
                                    version='7.0')
            return vag_id
        except exception.SolidFireAPIException as error:
            if xAlreadyInVolumeAccessGroup in error.msg:
                return vag_id
            elif xVolumeAccessGroupIDDoesNotExist in error.msg:
                # No locking means sometimes a VAG can be removed by a parallel
                # volume detach against the same host.
                return self._safe_create_vag(iqn)
            else:
                raise

    def _add_volume_to_vag(self, vol_id, iqn, vag_id):
        # Added a vag_id return to be consistent with add_initiator_to_vag. It
        # isn't necessary but may be helpful in the future.
        params = {"volumeAccessGroupID": vag_id,
                  "volumes": [vol_id]}
        try:
            self._issue_api_request('AddVolumesToVolumeAccessGroup',
                                    params,
                                    version='7.0')
            return vag_id

        except exception.SolidFireAPIException as error:
            if xAlreadyInVolumeAccessGroup in error.msg:
                return vag_id
            elif xVolumeAccessGroupIDDoesNotExist in error.msg:
                return self._safe_create_vag(iqn, vol_id)
            else:
                raise

    def _remove_volume_from_vag(self, vol_id, vag_id):
        params = {"volumeAccessGroupID": vag_id,
                  "volumes": [vol_id]}
        try:
            self._issue_api_request('RemoveVolumesFromVolumeAccessGroup',
                                    params,
                                    version='7.0')
        except exception.SolidFireAPIException as error:
            if xNotInVolumeAccessGroup in error.msg:
                pass
            elif xVolumeAccessGroupIDDoesNotExist in error.msg:
                pass
            else:
                raise

    def _remove_volume_from_vags(self, vol_id):
        # Due to all sorts of uncertainty around multiattach, on volume
        # deletion we make a best attempt at removing the vol_id from VAGs.
        vags = self._base_get_vags()
        targets = [v for v in vags if vol_id in v['volumes']]
        for vag in targets:
            self._remove_volume_from_vag(vol_id, vag['volumeAccessGroupID'])

    def _remove_vag(self, vag_id):
        params = {"volumeAccessGroupID": vag_id}
        try:
            self._issue_api_request('DeleteVolumeAccessGroup',
                                    params,
                                    version='7.0')
        except exception.SolidFireAPIException as error:
            if xVolumeAccessGroupIDDoesNotExist not in error.msg:
                raise

    def _purge_vags(self, limit=10):
        # Purge up to limit number of VAGs that have no active volumes,
        # initiators, and an OpenStack attribute. Purge oldest VAGs first.
        vags = self._base_get_vags()
        targets = [v for v in vags if v['volumes'] == [] and
                   v['initiators'] == [] and
                   v['deletedVolumes'] == [] and
                   v['attributes'].get('openstack')]
        sorted_targets = sorted(targets,
                                key=lambda k: k['volumeAccessGroupID'])
        for vag in sorted_targets[:limit]:
            self._remove_vag(vag['volumeAccessGroupID'])

    @locked_image_id_operation
    def clone_image(self, context,
                    volume, image_location,
                    image_meta, image_service):
        """Clone an existing image volume."""
        public = False
        # Check out pre-requisites:
        # Is template caching enabled?
        if not self.configuration.sf_allow_template_caching:
            return None, False

        # NOTE(jdg): Glance V2 moved from is_public to visibility
        # so we check both, as we don't necessarily know or want
        # to care which we're using.  Will need to look at
        # future handling of things like shared and community
        # but for now, it's owner or public and that's it
        visibility = image_meta.get('visibility', None)
        if visibility and visibility == 'public':
            public = True
        elif image_meta.get('is_public', False):
            public = True
        else:
            if image_meta['owner'] == volume['project_id']:
                public = True
        if not public:
            LOG.warning("Requested image is not "
                        "accessible by current Tenant.")
            return None, False

        try:
            self._verify_image_volume(context,
                                      image_meta,
                                      image_service)
        except exception.SolidFireAPIException:
            return None, False

        # Ok, should be good to go now, try it again
        (data, sfaccount, model) = self._do_clone_volume(image_meta['id'],
                                                         volume)
        return model, True

    def _retrieve_qos_setting(self, volume):
        qos = {}
        if (self.configuration.sf_allow_tenant_qos and
                volume.get('volume_metadata')is not None):
            qos = self._set_qos_presets(volume)

        ctxt = context.get_admin_context()
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            qos = self._set_qos_by_volume_type(ctxt, type_id,
                                               volume.get('size'))
        return qos

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

        sf_account = self._get_create_account(volume['project_id'])
        qos = self._retrieve_qos_setting(volume)

        create_time = volume['created_at'].isoformat()
        attributes = {'uuid': volume['id'],
                      'is_clone': 'False',
                      'created_at': create_time}

        vname = '%s%s' % (self.configuration.sf_volume_prefix, volume['id'])
        params = {'name': vname,
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
            vname = '%s%s' % (self.configuration.sf_volume_prefix, v)
            params['name'] = vname
            params['attributes']['migration_uuid'] = volume['id']
            params['attributes']['uuid'] = v

        model_update = self._do_volume_create(sf_account, params)
        try:
            rep_settings = self._retrieve_replication_settings(volume)
            if self.replication_enabled and rep_settings:
                volume['volumeID'] = (
                    int(model_update['provider_id'].split()[0]))
                self._replicate_volume(volume, params,
                                       sf_account, rep_settings)
        except exception.SolidFireAPIException:
            # NOTE(jdg): Something went wrong after the source create, due to
            # the way TFLOW works and it's insistence on retrying the same
            # command over and over coupled with the fact that the introduction
            # of objects now sets host to None on failures we'll end up with an
            # orphaned volume on the backend for every one of these segments
            # that fail, for n-retries.  Sad Sad Panda!!  We'll just do it
            # ourselves until we can get a general fix in Cinder further up the
            # line
            with excutils.save_and_reraise_exception():
                sf_volid = int(model_update['provider_id'].split()[0])
                self._issue_api_request('DeleteVolume', {'volumeID': sf_volid})
                self._issue_api_request('PurgeDeletedVolume',
                                        {'volumeID': sf_volid})
        return model_update

    def _retrieve_replication_settings(self, volume):
        rep_data = {}
        ctxt = context.get_admin_context()
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            rep_data = self._set_rep_by_volume_type(ctxt, type_id)
        return rep_data

    def _set_rep_by_volume_type(self, ctxt, type_id):
        rep_opts = {}
        type_ref = volume_types.get_volume_type(ctxt, type_id)
        specs = type_ref.get('extra_specs')

        if specs.get('replication', 'disabled').lower() == 'enabled':
            rep_opts['targets'] = specs.get(
                'solidfire:replication_targets', self.cluster_pairs[0])
        return rep_opts

    def _replicate_volume(self, volume, src_params,
                          parent_sfaccount, rep_info):
        params = {}

        # TODO(jdg): Right now we just go to first pair,
        # need to add parsing of rep_info eventually
        # in other words "rep_info" is not used yet!
        tgt_endpoint = self.cluster_pairs[0]['endpoint']
        LOG.debug("Replicating volume on remote cluster: %s", tgt_endpoint)
        params['attributes'] = src_params['attributes']
        params['username'] = self._get_sf_account_name(volume['project_id'])
        try:
            params['initiatorSecret'] = parent_sfaccount['initiatorSecret']
            params['targetSecret'] = parent_sfaccount['targetSecret']
            self._issue_api_request(
                'AddAccount',
                params,
                endpoint=tgt_endpoint)['result']['accountID']
        except exception.SolidFireAPIException as ex:
            if 'xDuplicateUsername' not in ex.msg:
                raise

        remote_account = (
            self._get_sfaccount_by_name(params['username'],
                                        endpoint=tgt_endpoint))

        # Create the volume on the remote cluster w/same params as original
        params = src_params
        params['accountID'] = remote_account['accountID']
        LOG.debug("Create remote volume on: %(endpoint)s with account: "
                  "%(account)s",
                  {'endpoint': tgt_endpoint['url'], 'account': remote_account})
        model_update = self._do_volume_create(
            remote_account, params, endpoint=tgt_endpoint)

        tgt_sfid = int(model_update['provider_id'].split()[0])
        params = {'volumeID': tgt_sfid, 'access': 'replicationTarget'}
        self._issue_api_request('ModifyVolume',
                                params,
                                '8.0',
                                endpoint=tgt_endpoint)

        # Enable volume pairing
        LOG.debug("Start volume pairing on volume ID: %s",
                  volume['volumeID'])
        params = {'volumeID': volume['volumeID']}
        rep_key = self._issue_api_request('StartVolumePairing',
                                          params,
                                          '8.0')['result']['volumePairingKey']
        params = {'volumeID': tgt_sfid,
                  'volumePairingKey': rep_key}
        LOG.debug("Issue CompleteVolumePairing request on remote: "
                  "%(endpoint)s, %(parameters)s",
                  {'endpoint': tgt_endpoint['url'], 'parameters': params})
        self._issue_api_request('CompleteVolumePairing',
                                params,
                                '8.0',
                                endpoint=tgt_endpoint)
        LOG.debug("Completed volume pairing.")
        return model_update

    @locked_source_id_operation
    def create_cloned_volume(self, volume, source):
        """Create a clone of an existing volume."""
        (_data, _sfaccount, model) = self._do_clone_volume(
            source['id'],
            volume)

        return model

    def delete_volume(self, volume):
        """Delete SolidFire Volume from device.

         SolidFire allows multiple volumes with same name,
         volumeID is what's guaranteed unique.

        """
        sf_vol = None
        accounts = self._get_sfaccounts_for_tenant(volume['project_id'])
        if accounts is None:
            LOG.error("Account for Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "delete_volume operation!", volume['id'])
            LOG.error("This usually means the volume was never "
                      "successfully created.")
            return

        for acc in accounts:
            vols = self._get_volumes_for_account(acc['accountID'],
                                                 volume.name_id)
            # Check for migration magic here
            if (not vols and (volume.name_id != volume.id)):
                vols = self._get_volumes_for_account(acc['accountID'],
                                                     volume.id)

            if vols:
                sf_vol = vols[0]
                break

        if sf_vol is not None:
            for vp in sf_vol.get('volumePairs', []):
                LOG.debug("Deleting paired volume on remote cluster...")
                pair_id = vp['clusterPairID']
                for cluster in self.cluster_pairs:
                    if cluster['clusterPairID'] == pair_id:
                        params = {'volumeID': vp['remoteVolumeID']}
                        LOG.debug("Issue Delete request on cluster: "
                                  "%(remote)s with params: %(parameters)s",
                                  {'remote': cluster['endpoint']['url'],
                                   'parameters': params})
                        self._issue_api_request('DeleteVolume', params,
                                                endpoint=cluster['endpoint'])
                        self._issue_api_request('PurgeDeletedVolume', params,
                                                endpoint=cluster['endpoint'])

            if sf_vol['status'] == 'active':
                params = {'volumeID': sf_vol['volumeID']}
                self._issue_api_request('DeleteVolume', params)
                self._issue_api_request('PurgeDeletedVolume', params)
            if volume.get('multiattach'):
                self._remove_volume_from_vags(sf_vol['volumeID'])
        else:
            LOG.error("Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "delete_volume operation!", volume['id'])

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot from the SolidFire cluster."""
        sf_snap_name = '%s%s' % (self.configuration.sf_volume_prefix,
                                 snapshot['id'])
        accounts = self._get_sfaccounts_for_tenant(snapshot['project_id'])
        snap = None
        for acct in accounts:
            params = {'accountID': acct['accountID']}
            sf_vol = self._get_sf_volume(snapshot['volume_id'], params)
            if sf_vol:
                sf_snaps = self._get_sf_snapshots(sf_vol['volumeID'])
                snap = next((s for s in sf_snaps if s["name"] == sf_snap_name),
                            None)
                if snap:
                    params = {'snapshotID': snap['snapshotID']}
                    self._issue_api_request('DeleteSnapshot',
                                            params,
                                            version='6.0')
                    return
        LOG.warning(
            "Snapshot %s not found, old style clones may not be deleted.",
            snapshot.id)

    def create_snapshot(self, snapshot):
        sfaccount = self._get_sfaccount(snapshot['project_id'])
        if sfaccount is None:
            LOG.error("Account for Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "create_snapshot operation!", snapshot['volume_id'])

        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(snapshot['volume_id'], params)

        if sf_vol is None:
            raise exception.VolumeNotFound(volume_id=snapshot['volume_id'])
        params = {'volumeID': sf_vol['volumeID'],
                  'name': '%s%s' % (self.configuration.sf_volume_prefix,
                                    snapshot['id'])}
        return self._do_snapshot_create(params)

    @locked_source_id_operation
    def create_volume_from_snapshot(self, volume, source):
        """Create a volume from the specified snapshot."""
        if source.get('group_snapshot_id'):
            # We're creating a volume from a snapshot that resulted from a
            # consistency group snapshot. Because of the way that SolidFire
            # creates cgsnaps, we have to search for the correct snapshot.
            group_snapshot_id = source.get('group_snapshot_id')
            snapshot_id = source.get('volume_id')
            sf_name = self.configuration.sf_volume_prefix + group_snapshot_id
            sf_group_snap = self._get_group_snapshot_by_name(sf_name)
            return self._create_clone_from_sf_snapshot(snapshot_id,
                                                       group_snapshot_id,
                                                       sf_group_snap,
                                                       volume)

        (_data, _sfaccount, model) = self._do_clone_volume(
            source['id'],
            volume)

        return model

    # Consistency group helpers
    def _sf_create_group_snapshot(self, name, sf_volumes):
        # Group snapshot is our version of a consistency group snapshot.
        vol_ids = [vol['volumeID'] for vol in sf_volumes]
        params = {'name': name,
                  'volumes': vol_ids}
        snapshot_id = self._issue_api_request('CreateGroupSnapshot',
                                              params,
                                              version='7.0')
        return snapshot_id['result']

    def _group_snapshot_creator(self, gsnap_name, src_vol_ids):
        # Common helper that takes in an array of OpenStack Volume UUIDs and
        # creates a SolidFire group snapshot with them.
        vol_names = [self.configuration.sf_volume_prefix + vol_id
                     for vol_id in src_vol_ids]
        active_sf_vols = self._get_all_active_volumes()
        target_vols = [vol for vol in active_sf_vols
                       if vol['name'] in vol_names]
        if len(src_vol_ids) != len(target_vols):
            msg = (_("Retrieved a different amount of SolidFire volumes for "
                     "the provided Cinder volumes. Retrieved: %(ret)s "
                     "Desired: %(des)s") % {"ret": len(target_vols),
                                            "des": len(src_vol_ids)})
            raise exception.SolidFireDriverException(msg)

        result = self._sf_create_group_snapshot(gsnap_name, target_vols)
        return result

    def _create_temp_group_snapshot(self, source_cg, source_vols):
        # Take a temporary snapshot to create the volumes for a new
        # consistency group.
        gsnap_name = ("%(prefix)s%(id)s-tmp" %
                      {"prefix": self.configuration.sf_volume_prefix,
                       "id": source_cg['id']})
        vol_ids = [vol['id'] for vol in source_vols]
        self._group_snapshot_creator(gsnap_name, vol_ids)
        return gsnap_name

    def _list_group_snapshots(self):
        result = self._issue_api_request('ListGroupSnapshots',
                                         {},
                                         version='7.0')
        return result['result']['groupSnapshots']

    def _get_group_snapshot_by_name(self, name):
        target_snaps = self._list_group_snapshots()
        target = next((snap for snap in target_snaps
                       if snap['name'] == name), None)
        return target

    def _delete_group_snapshot(self, gsnapid):
        params = {'groupSnapshotID': gsnapid}
        self._issue_api_request('DeleteGroupSnapshot',
                                params,
                                version='7.0')

    def _delete_cgsnapshot_by_name(self, snap_name):
        # Common function used to find and delete a snapshot.
        target = self._get_group_snapshot_by_name(snap_name)
        if not target:
            msg = _("Failed to find group snapshot named: %s") % snap_name
            raise exception.SolidFireDriverException(msg)
        self._delete_group_snapshot(target['groupSnapshotID'])

    def _find_linked_snapshot(self, target_uuid, group_snap):
        # Because group snapshots name each individual snapshot the group
        # snapshot name, we have to trawl through the SolidFire snapshots to
        # find the SolidFire snapshot from the group that is linked with the
        # SolidFire volumeID that is linked to the Cinder snapshot source
        # volume.
        source_vol = self._get_sf_volume(target_uuid)
        target_snap = next((sn for sn in group_snap['members']
                            if sn['volumeID'] == source_vol['volumeID']), None)
        return target_snap

    def _create_clone_from_sf_snapshot(self, target_uuid, src_uuid,
                                       sf_group_snap, vol):
        # Find the correct SolidFire backing snapshot.
        sf_src_snap = self._find_linked_snapshot(target_uuid,
                                                 sf_group_snap)
        _data, _sfaccount, model = self._do_clone_volume(src_uuid,
                                                         vol,
                                                         sf_src_snap)
        model['id'] = vol['id']
        model['status'] = 'available'
        return model

    def _map_sf_volumes(self, cinder_volumes, endpoint=None):
        """Get a list of SolidFire volumes.

        Creates a list of SolidFire volumes based
        on matching a list of cinder volume ID's,
        also adds an 'cinder_id' key to match cinder.
        """
        vols = self._issue_api_request(
            'ListActiveVolumes', {},
            endpoint=endpoint)['result']['volumes']
        vlist = (
            [sfvol for sfvol in vols for cv in cinder_volumes if cv['id'] in
             sfvol['name']])
        for v in vlist:
            v['cinder_id'] = v['name'].split(
                self.configuration.sf_volume_prefix)[1]
        return vlist

    # Generic Volume Groups.
    def create_group(self, ctxt, group):
        # SolidFire does not have the concept of volume groups. We're going to
        # play along with the group song and dance. There will be a lot of
        # no-ops because of this.
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return {'status': fields.GroupStatus.AVAILABLE}

        # Blatantly ripping off this pattern from other drivers.
        raise NotImplementedError()

    def create_group_from_src(self, ctxt, group, volumes, group_snapshots=None,
                              snapshots=None, source_group=None,
                              source_vols=None):
        # At this point this is just a pass-through.
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self._create_consistencygroup_from_src(
                ctxt,
                group,
                volumes,
                group_snapshots,
                snapshots,
                source_group,
                source_vols)

        # Default implementation handles other scenarios.
        raise NotImplementedError()

    def create_group_snapshot(self, ctxt, group_snapshot, snapshots):
        # This is a pass-through to the old consistency group stuff.
        if vol_utils.is_group_a_cg_snapshot_type(group_snapshot):
            return self._create_cgsnapshot(ctxt, group_snapshot, snapshots)

        # Default implementation handles other scenarios.
        raise NotImplementedError()

    def delete_group(self, ctxt, group, volumes):
        # Delete a volume group. SolidFire does not track volume groups,
        # however we do need to actually remove the member volumes of the
        # group. Right now only consistent volume groups are supported.
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self._delete_consistencygroup(ctxt, group, volumes)

        # Default implementation handles other scenarios.
        raise NotImplementedError()

    def update_group(self, ctxt, group, add_volumes=None, remove_volumes=None):
        # Regarding consistency groups SolidFire does not track volumes, so
        # this is a no-op. In the future with replicated volume groups this
        # might actually do something.
        if vol_utils.is_group_a_cg_snapshot_type(group):
            return self._update_consistencygroup(ctxt,
                                                 group,
                                                 add_volumes,
                                                 remove_volumes)

        # Default implementation handles other scenarios.
        raise NotImplementedError()

    def _create_consistencygroup_from_src(self, ctxt, group, volumes,
                                          cgsnapshot, snapshots,
                                          source_cg, source_vols):
        if cgsnapshot and snapshots:
            sf_name = self.configuration.sf_volume_prefix + cgsnapshot['id']
            sf_group_snap = self._get_group_snapshot_by_name(sf_name)

            # Go about creating volumes from provided snaps.
            vol_models = []
            for vol, snap in zip(volumes, snapshots):
                vol_models.append(self._create_clone_from_sf_snapshot(
                    snap['volume_id'],
                    snap['id'],
                    sf_group_snap,
                    vol))
            return ({'status': fields.GroupStatus.AVAILABLE},
                    vol_models)

        elif source_cg and source_vols:
            # Create temporary group snapshot.
            gsnap_name = self._create_temp_group_snapshot(source_cg,
                                                          source_vols)
            try:
                sf_group_snap = self._get_group_snapshot_by_name(gsnap_name)
                # For each temporary snapshot clone the volume.
                vol_models = []
                for vol in volumes:
                    vol_models.append(self._create_clone_from_sf_snapshot(
                        vol['source_volid'],
                        vol['source_volid'],
                        sf_group_snap,
                        vol))
            finally:
                self._delete_cgsnapshot_by_name(gsnap_name)
            return {'status': fields.GroupStatus.AVAILABLE}, vol_models

    def _create_cgsnapshot(self, ctxt, cgsnapshot, snapshots):
        vol_ids = [snapshot['volume_id'] for snapshot in snapshots]
        vol_names = [self.configuration.sf_volume_prefix + vol_id
                     for vol_id in vol_ids]
        active_sf_vols = self._get_all_active_volumes()
        target_vols = [vol for vol in active_sf_vols
                       if vol['name'] in vol_names]
        if len(snapshots) != len(target_vols):
            msg = (_("Retrieved a different amount of SolidFire volumes for "
                     "the provided Cinder snapshots. Retrieved: %(ret)s "
                     "Desired: %(des)s") % {"ret": len(target_vols),
                                            "des": len(snapshots)})
            raise exception.SolidFireDriverException(msg)
        snap_name = self.configuration.sf_volume_prefix + cgsnapshot['id']
        self._sf_create_group_snapshot(snap_name, target_vols)
        return None, None

    def _update_consistencygroup(self, context, group,
                                 add_volumes=None, remove_volumes=None):
        # Similar to create_consistencygroup, SolidFire's lack of a consistency
        # group object means there is nothing to update on the cluster.
        return None, None, None

    def _delete_cgsnapshot(self, ctxt, cgsnapshot, snapshots):
        snap_name = self.configuration.sf_volume_prefix + cgsnapshot['id']
        self._delete_cgsnapshot_by_name(snap_name)
        return None, None

    def _delete_consistencygroup(self, ctxt, group, volumes):
        # TODO(chris_morrell): exception handling and return correctly updated
        # volume_models.
        for vol in volumes:
            self.delete_volume(vol)

        return None, None

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
            LOG.error("Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "extend_volume operation!", volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        params = {
            'volumeID': sf_vol['volumeID'],
            'totalSize': int(new_size * units.Gi)
        }
        self._issue_api_request('ModifyVolume',
                                params, version='5.0')

    def _update_cluster_status(self):
        """Retrieve status info for the Cluster."""
        params = {}

        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'SolidFire Inc'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'
        data['consistencygroup_support'] = True
        data['consistent_group_snapshot_enabled'] = True
        data['replication_enabled'] = self.replication_enabled
        if self.replication_enabled:
            data['replication'] = 'enabled'
        data['active_cluster_mvip'] = self.active_cluster_info['mvip']
        data['reserved_percentage'] = self.configuration.reserved_percentage
        data['QoS_support'] = True

        try:
            results = self._issue_api_request('GetClusterCapacity', params)
        except exception.SolidFireAPIException:
            data['total_capacity_gb'] = 0
            data['free_capacity_gb'] = 0
            self.cluster_stats = data
            return

        results = results['result']['clusterCapacity']
        free_capacity = (
            results['maxProvisionedSpace'] - results['usedSpace'])

        data['total_capacity_gb'] = (
            float(results['maxProvisionedSpace'] / units.Gi))

        data['free_capacity_gb'] = float(free_capacity / units.Gi)
        data['compression_percent'] = (
            results['compressionPercent'])
        data['deduplicaton_percent'] = (
            results['deDuplicationPercent'])
        data['thin_provision_percent'] = (
            results['thinProvisioningPercent'])
        self.cluster_stats = data

    def initialize_connection(self, volume, connector):
        """Initialize the connection and return connection info.

           Optionally checks and utilizes volume access groups.
        """
        properties = self._sf_initialize_connection(volume, connector)
        properties['data']['discard'] = True
        return properties

    def attach_volume(self, context, volume,
                      instance_uuid, host_name,
                      mountpoint):

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error("Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "attach_volume operation!", volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        attributes = sf_vol['attributes']
        attributes['attach_time'] = volume.get('attach_time', None)
        attributes['attached_to'] = instance_uuid
        params = {
            'volumeID': sf_vol['volumeID'],
            'attributes': attributes
        }

        self._issue_api_request('ModifyVolume', params)

    def terminate_connection(self, volume, properties, force):
        return self._sf_terminate_connection(volume,
                                             properties,
                                             force)

    def detach_volume(self, context, volume, attachment=None):
        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error("Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "detach_volume operation!", volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])

        attributes = sf_vol['attributes']
        attributes['attach_time'] = None
        attributes['attached_to'] = None
        params = {
            'volumeID': sf_vol['volumeID'],
            'attributes': attributes
        }

        self._issue_api_request('ModifyVolume', params)

    def accept_transfer(self, context, volume,
                        new_user, new_project):

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}
        sf_vol = self._get_sf_volume(volume['id'], params)
        if sf_vol is None:
            LOG.error("Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "accept_transfer operation!", volume['id'])
            raise exception.VolumeNotFound(volume_id=volume['id'])
        if new_project != volume['project_id']:
            # do a create_sfaccount here as this tenant
            # may not exist on the cluster yet
            sfaccount = self._create_sfaccount(new_project)

        params = {
            'volumeID': sf_vol['volumeID'],
            'accountID': sfaccount['accountID']
        }
        self._issue_api_request('ModifyVolume',
                                params, version='5.0')

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
        qos = self._set_qos_by_volume_type(ctxt, new_type['id'],
                                           volume.get('size'))

        if qos:
            params['qos'] = qos

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
        vols = self._issue_api_request(
            'ListActiveVolumes', params)['result']['volumes']

        sf_ref = vols[0]
        sfaccount = self._create_sfaccount(volume['project_id'])

        attributes = {}
        qos = self._retrieve_qos_setting(volume)

        import_time = volume['created_at'].isoformat()
        attributes = {'uuid': volume['id'],
                      'is_clone': 'False',
                      'os_imported_at': import_time,
                      'old_name': sfname}

        params = {'name': volume['name'],
                  'volumeID': sf_ref['volumeID'],
                  'accountID': sfaccount['accountID'],
                  'enable512e': self.configuration.sf_emulate_512,
                  'attributes': attributes,
                  'qos': qos}

        self._issue_api_request('ModifyVolume',
                                params, version='5.0')

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
        vols = self._issue_api_request(
            'ListActiveVolumes', params)['result']['volumes']
        return int(math.ceil(float(vols[0]['totalSize']) / units.Gi))

    def unmanage(self, volume):
        """Mark SolidFire Volume as unmanaged (export from Cinder)."""
        sfaccount = self._get_sfaccount(volume['project_id'])
        if sfaccount is None:
            LOG.error("Account for Volume ID %s was not found on "
                      "the SolidFire Cluster while attempting "
                      "unmanage operation!", volume['id'])
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

        self._issue_api_request('ModifyVolume',
                                params, version='5.0')

    def _failover_volume(self, remote_vol, remote):
        """Modify remote volume to R/W mode."""
        self._issue_api_request(
            'RemoveVolumePair',
            {'volumeID': remote_vol['volumeID']},
            endpoint=remote['endpoint'], version='7.0')

        params = {'volumeID': remote_vol['volumeID'],
                  'access': 'readWrite'}
        self._issue_api_request('ModifyVolume', params,
                                endpoint=remote['endpoint'])

    def failover_host(self, context, volumes, secondary_id=None, groups=None):
        """Failover to replication target."""
        volume_updates = []
        remote = None

        if secondary_id:
            for rc in self.cluster_pairs:
                if rc['mvip'] == secondary_id:
                    remote = rc
                    break
            if not remote:
                LOG.error("SolidFire driver received failover_host "
                          "but was unable to find specified replication "
                          "pair with id: %s.", secondary_id)
                raise exception.InvalidReplicationTarget
        else:
            remote = self.cluster_pairs[0]

        if not remote or not self.replication_enabled:
            LOG.error("SolidFire driver received failover_host "
                      "request, however replication is NOT "
                      "enabled, or there are no available "
                      "targets to fail-over to.")
            raise exception.UnableToFailOver(reason=_("Failover requested "
                                                      "on non replicated "
                                                      "backend."))

        remote_vols = self._map_sf_volumes(volumes,
                                           endpoint=remote['endpoint'])
        primary_vols = self._map_sf_volumes(volumes)
        for v in volumes:
            remote_vlist = [sfv for sfv in remote_vols
                            if sfv['cinder_id'] == v['id']]

            if len(remote_vlist) > 0:
                remote_vol = remote_vlist[0]
                self._failover_volume(remote_vol, remote)
                primary_vol = [sfv for sfv in primary_vols if
                               sfv['cinder_id'] == v['id']][0]
                if len(primary_vol['volumePairs']) > 0:
                    self._issue_api_request(
                        'RemoveVolumePair',
                        {'volumeID': primary_vol['volumeID']},
                        version='7.0')
                iqn = remote_vol['iqn']
                volume_updates.append(
                    {'volume_id': v['id'],
                     'updates': {
                     'provider_location': ('%s %s %s' %
                                           (remote['endpoint']['svip'],
                                            iqn,
                                            0)),
                     'replication_status': 'failed-over'}})
            else:
                volume_updates.append({'volume_id': v['id'],
                                       'updates': {'status': 'error', }})

        # FIXME(jdg): This introduces a problem for us, up until now our driver
        # has been pretty much stateless and has allowed customers to run
        # active/active HA c-vol services with SolidFire.  The introduction of
        # the active_cluster and failed_over attributes is going to break that
        # but for now that's going to be the trade off of using replciation
        self.active_cluster_info = remote
        self.failed_over = True
        return remote['mvip'], volume_updates, []

    def freeze_backend(self, context):
        """Freeze backend notification."""
        pass

    def thaw_backend(self, context):
        """Thaw backend notification."""
        pass


class SolidFireISCSI(iscsi_driver.SanISCSITarget):
    def __init__(self, *args, **kwargs):
        super(SolidFireISCSI, self).__init__(*args, **kwargs)
        self.sf_driver = kwargs.get('solidfire_driver')

    def __getattr__(self, attr):
        if hasattr(self.sf_driver, attr):
            return getattr(self.sf_driver, attr)
        else:
            msg = _('Attribute: %s not found.') % attr
            raise NotImplementedError(msg)

    def _do_iscsi_export(self, volume):
        sfaccount = self._get_sfaccount(volume['project_id'])
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

    def _sf_initialize_connection(self, volume, connector):
        """Initialize the connection and return connection info.

           Optionally checks and utilizes volume access groups.
        """
        if self.configuration.sf_enable_vag:
            iqn = connector['initiator']
            provider_id = volume['provider_id']
            vol_id = int(provider_id.split()[0])

            # safe_create_vag may opt to reuse vs create a vag, so we need to
            # add our vol_id.
            vag_id = self._safe_create_vag(iqn, vol_id)
            self._add_volume_to_vag(vol_id, iqn, vag_id)

        # Continue along with default behavior
        return super(SolidFireISCSI, self).initialize_connection(volume,
                                                                 connector)

    def _sf_terminate_connection(self, volume, properties, force):
        """Terminate the volume connection.

           Optionally remove volume from volume access group.
           If the VAG is empty then the VAG is also removed.
        """
        if self.configuration.sf_enable_vag:
            iqn = properties['initiator']
            vag = self._get_vags_by_name(iqn)
            provider_id = volume['provider_id']
            vol_id = int(provider_id.split()[0])

            if vag and not volume['multiattach']:
                # Multiattach causes problems with removing volumes from VAGs.
                # Compromise solution for now is to remove multiattach volumes
                # from VAGs during volume deletion.
                vag = vag[0]
                vag_id = vag['volumeAccessGroupID']
                if [vol_id] == vag['volumes']:
                    self._remove_vag(vag_id)
                elif vol_id in vag['volumes']:
                    self._remove_volume_from_vag(vol_id, vag_id)

        return super(SolidFireISCSI, self).terminate_connection(volume,
                                                                properties,
                                                                force=force)
