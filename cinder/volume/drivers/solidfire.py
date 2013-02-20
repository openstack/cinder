# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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
import httplib
import json
import math
import random
import socket
import string
import time
import uuid

from oslo.config import cfg

from cinder import context
from cinder import exception
from cinder import flags
from cinder.openstack.common import log as logging
from cinder.volume.drivers.san.san import SanISCSIDriver
from cinder.volume import volume_types

VERSION = 1.2
LOG = logging.getLogger(__name__)

sf_opts = [
    cfg.BoolOpt('sf_emulate_512',
                default=True,
                help='Set 512 byte emulation on volume creation; '),

    cfg.BoolOpt('sf_allow_tenant_qos',
                default=False,
                help='Allow tenants to specify QOS on create'), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(sf_opts)


class SolidFire(SanISCSIDriver):
    """OpenStack driver to enable SolidFire cluster.

    Version history:
        1.0 - Initial driver
        1.1 - Refactor, clone support, qos by type and minor bug fixes

    """

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

    GB = math.pow(10, 9)

    def __init__(self, *args, **kwargs):
            super(SolidFire, self).__init__(*args, **kwargs)
            self._update_cluster_status()

    def _issue_api_request(self, method_name, params):
        """All API requests to SolidFire device go through this method.

        Simple json-rpc web based API calls.
        each call takes a set of paramaters (dict)
        and returns results in a dict as well.

        """
        max_simultaneous_clones = ['xMaxSnapshotsPerVolumeExceeded',
                                   'xMaxClonesPerVolumeExceeded',
                                   'xMaxSnapshotsPerNodeExceeded',
                                   'xMaxClonesPerNodeExceeded']
        host = FLAGS.san_ip
        # For now 443 is the only port our server accepts requests on
        port = 443

        cluster_admin = FLAGS.san_login
        cluster_password = FLAGS.san_password

        # NOTE(jdg): We're wrapping a retry loop for a know XDB issue
        # Shows up in very high request rates (ie create 1000 volumes)
        # we have to wrap the whole sequence because the request_id
        # can't be re-used
        retry_count = 5
        while retry_count > 0:
            request_id = int(uuid.uuid4())  # just generate a random number
            command = {'method': method_name,
                       'id': request_id}

            if params is not None:
                command['params'] = params

            payload = json.dumps(command, ensure_ascii=False)
            payload.encode('utf-8')
            header = {'Content-Type': 'application/json-rpc; charset=utf-8'}

            if cluster_password is not None:
                # base64.encodestring includes a newline character
                # in the result, make sure we strip it off
                auth_key = base64.encodestring('%s:%s' % (cluster_admin,
                                               cluster_password))[:-1]
                header['Authorization'] = 'Basic %s' % auth_key

            LOG.debug(_("Payload for SolidFire API call: %s"), payload)

            connection = httplib.HTTPSConnection(host, port)
            connection.request('POST', '/json-rpc/1.0', payload, header)
            response = connection.getresponse()

            data = {}
            if response.status != 200:
                connection.close()
                raise exception.SolidFireAPIException(status=response.status)

            else:
                data = response.read()
                try:
                    data = json.loads(data)
                except (TypeError, ValueError), exc:
                    connection.close()
                    msg = _("Call to json.loads() raised "
                            "an exception: %s") % exc
                    raise exception.SfJsonEncodeFailure(msg)

                connection.close()

            LOG.debug(_("Results of SolidFire API call: %s"), data)

            if 'error' in data:
                if data['error']['name'] in max_simultaneous_clones:
                    LOG.warning(_('Clone operation '
                                  'encountered: %s') % data['error']['name'])
                    LOG.warning(_(
                        'Waiting for outstanding operation '
                        'before retrying snapshot: %s') % params['name'])
                    time.sleep(5)
                    # Don't decrement the retry count for this one
                elif 'xDBVersionMismatch' in data['error']['name']:
                    LOG.debug(_('Detected xDBVersionMismatch, '
                                'retry %s of 5') % (5 - retry_count))
                    time.sleep(1)
                    retry_count -= 1
                else:
                    msg = _("API response: %s") % data
                    raise exception.SolidFireAPIException(msg)
            else:
                retry_count = 0

        return data

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
        data = self._issue_api_request('GetAccountByName', params)
        if 'result' in data and 'account' in data['result']:
            LOG.debug(_('Found solidfire account: %s'), sf_account_name)
            sfaccount = data['result']['account']
        return sfaccount

    def _get_sf_account_name(self, project_id):
        """Build the SolidFire account name to use."""
        return ('%s-%s' % (socket.gethostname(), project_id))

    def _get_sfaccount(self, project_id):
        sf_account_name = self._get_sf_account_name(project_id)
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            raise exception.SfAccountNotFound(account_name=sf_account_name)

        return sfaccount

    def _create_sfaccount(self, project_id):
        """Create account on SolidFire device if it doesn't already exist.

        We're first going to check if the account already exits, if it does
        just return it.  If not, then create it.

        """

        sf_account_name = self._get_sf_account_name(project_id)
        sfaccount = self._get_sfaccount_by_name(sf_account_name)
        if sfaccount is None:
            LOG.debug(_('solidfire account: %s does not exist, create it...'),
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
            raise exception.SolidFireAPIDataException(data=data)

        return data['result']

    def _do_export(self, volume):
        """Gets the associated account, retrieves CHAP info and updates."""
        sfaccount = self._get_sfaccount(volume['project_id'])

        model_update = {}
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                            sfaccount['targetSecret']))

        return model_update

    def _generate_random_string(self, length):
        """Generates random_string to use for CHAP password."""

        char_set = string.ascii_uppercase + string.digits
        return ''.join(random.sample(char_set, length))

    def _get_model_info(self, sfaccount, sf_volume_id):
        """Gets the connection info for specified account and volume."""
        cluster_info = self._get_cluster_info()
        iscsi_portal = cluster_info['clusterInfo']['svip'] + ':3260'
        chap_secret = sfaccount['targetSecret']

        volume_list = self._get_volumes_by_sfaccount(sfaccount['accountID'])
        iqn = None
        for v in volume_list:
            if v['volumeID'] == sf_volume_id:
                iqn = v['iqn']
                break

        model_update = {}
        # NOTE(john-griffith): SF volumes are always at lun 0
        model_update['provider_location'] = ('%s %s %s'
                                             % (iscsi_portal, iqn, 0))
        model_update['provider_auth'] = ('CHAP %s %s'
                                         % (sfaccount['username'],
                                         chap_secret))
        return model_update

    def _do_clone_volume(self, src_uuid, src_project_id, v_ref):
        """Create a clone of an existing volume.

        Currently snapshots are the same as clones on the SF cluster.
        Due to the way the SF cluster works there's no loss in efficiency
        or space usage between the two.  The only thing different right
        now is the restore snapshot functionality which has not been
        implemented in the pre-release version of the SolidFire Cluster.

        """
        attributes = {}
        qos = {}

        sfaccount = self._get_sfaccount(src_project_id)
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(src_uuid, params)
        if sf_vol is None:
            raise exception.VolumeNotFound(volume_id=uuid)

        if 'qos' in sf_vol:
            qos = sf_vol['qos']

        attributes = {'uuid': v_ref['id'],
                      'is_clone': 'True',
                      'src_uuid': 'src_uuid'}

        if qos:
            attributes['qos'] = qos

        params = {'volumeID': int(sf_vol['volumeID']),
                  'name': 'UUID-%s' % v_ref['id'],
                  'attributes': attributes,
                  'qos': qos}

        data = self._issue_api_request('CloneVolume', params)

        if (('result' not in data) or ('volumeID' not in data['result'])):
            raise exception.SolidFireAPIDataException(data=data)

        sf_volume_id = data['result']['volumeID']
        model_update = self._get_model_info(sfaccount, sf_volume_id)
        if model_update is None:
            mesg = _('Failed to get model update from clone')
            raise exception.SolidFireAPIDataException(mesg)

        return (data, sfaccount, model_update)

    def _do_volume_create(self, project_id, params):
        sfaccount = self._create_sfaccount(project_id)

        params['accountID'] = sfaccount['accountID']
        data = self._issue_api_request('CreateVolume', params)

        if (('result' not in data) or ('volumeID' not in data['result'])):
            raise exception.SolidFireAPIDataException(data=data)

        sf_volume_id = data['result']['volumeID']
        return self._get_model_info(sfaccount, sf_volume_id)

    def _set_qos_presets(self, volume):
        qos = {}
        valid_presets = self.sf_qos_dict.keys()

        #First look to see if they included a preset
        presets = [i.value for i in volume.get('volume_metadata')
                   if i.key == 'sf-qos' and i.value in valid_presets]
        if len(presets) > 0:
            if len(presets) > 1:
                LOG.warning(_('More than one valid preset was '
                              'detected, using %s') % presets[0])
            qos = self.sf_qos_dict[presets[0]]
        else:
            #look for explicit settings
            for i in volume.get('volume_metadata'):
                if i.key in self.sf_qos_keys:
                    qos[i.key] = int(i.value)
        return qos

    def _set_qos_by_volume_type(self, type_id, ctxt):
        qos = {}
        volume_type = volume_types.get_volume_type(ctxt, type_id)
        specs = volume_type.get('extra_specs')
        for key, value in specs.iteritems():
            if key in self.sf_qos_keys:
                qos[key] = int(value)
        return qos

    def _get_sf_volume(self, uuid, params):
        data = self._issue_api_request('ListVolumesForAccount', params)
        if 'result' not in data:
            raise exception.SolidFireAPIDataException(data=data)

        found_count = 0
        sf_volref = None
        for v in data['result']['volumes']:
            if uuid in v['name']:
                found_count += 1
                sf_volref = v
                LOG.debug(_("Mapped SolidFire volumeID %(sfid)s "
                            "to cinder ID %(uuid)s.") %
                          {'sfid': v['volumeID'],
                           'uuid': uuid})

        if found_count == 0:
            # NOTE(jdg): Previously we would raise here, but there are cases
            # where this might be a cleanup for a failed delete.
            # Until we get better states we'll just log an error
            LOG.error(_("Volume %s, not found on SF Cluster."), uuid)

        if found_count > 1:
            LOG.error(_("Found %(count)s volumes mapped to id: %(uuid)s.") %
                      {'count': found_count,
                       'uuid': uuid})
            raise exception.DuplicateSfVolumeNames(vol_name=uuid)

        return sf_volref

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

        if (FLAGS.sf_allow_tenant_qos and
                volume.get('volume_metadata')is not None):
            qos = self._set_qos_presets(volume)

        ctxt = context.get_admin_context()
        type_id = volume['volume_type_id']
        if type_id is not None:
            qos = self._set_qos_by_volume_type(ctxt, type_id)

        attributes = {'uuid': volume['id'],
                      'is_clone': 'False'}
        if qos:
            attributes['qos'] = qos

        params = {'name': 'UUID-%s' % volume['id'],
                  'accountID': None,
                  'sliceCount': slice_count,
                  'totalSize': int(volume['size'] * self.GB),
                  'enable512e': FLAGS.sf_emulate_512,
                  'attributes': attributes,
                  'qos': qos}

        return self._do_volume_create(volume['project_id'], params)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of an existing volume."""
        (data, sfaccount, model) = self._do_clone_volume(
            src_vref['id'],
            src_vref['project_id'],
            volume)

        return model

    def delete_volume(self, volume):
        """Delete SolidFire Volume from device.

        SolidFire allows multipe volumes with same name,
        volumeID is what's guaranteed unique.

        """

        LOG.debug(_("Enter SolidFire delete_volume..."))

        sfaccount = self._get_sfaccount(volume['project_id'])
        params = {'accountID': sfaccount['accountID']}

        sf_vol = self._get_sf_volume(volume['id'], params)

        if sf_vol is not None:
            params = {'volumeID': sf_vol['volumeID']}
            data = self._issue_api_request('DeleteVolume', params)

            if 'result' not in data:
                raise exception.SolidFireAPIDataException(data=data)
        else:
            LOG.error(_("Volume ID %s was not found on "
                        "the SolidFire Cluster!"), volume['id'])

        LOG.debug(_("Leaving SolidFire delete_volume"))

    def ensure_export(self, context, volume):
        """Verify the iscsi export info."""
        LOG.debug(_("Executing SolidFire ensure_export..."))
        return self._do_export(volume)

    def create_export(self, context, volume):
        """Setup the iscsi export info."""
        LOG.debug(_("Executing SolidFire create_export..."))
        return self._do_export(volume)

    def delete_snapshot(self, snapshot):
        """Delete the specified snapshot from the SolidFire cluster."""
        self.delete_volume(snapshot)

    def create_snapshot(self, snapshot):
        """Create a snapshot of a volume on the SolidFire cluster.

        Note that for SolidFire Clusters currently there is no snapshot
        implementation.  Due to the way SF does cloning there's no performance
        hit or extra space used.  The only thing that's lacking from this is
        the abilit to restore snaps.

        After GA a true snapshot implementation will be available with
        restore at which time we'll rework this appropriately.

        """
        (data, sfaccount, model) = self._do_clone_volume(
            snapshot['volume_id'],
            snapshot['project_id'],
            snapshot)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from the specified snapshot."""
        (data, sfaccount, model) = self._do_clone_volume(
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
            self._update_cluster_status()

        return self.cluster_stats

    def _update_cluster_status(self):
        """Retrieve status info for the Cluster."""

        LOG.debug(_("Updating cluster status info"))

        params = {}

        # NOTE(jdg): The SF api provides an UNBELIEVABLE amount
        # of stats data, this is just one of the calls
        results = self._issue_api_request('GetClusterCapacity', params)
        if 'result' not in results:
            LOG.error(_('Failed to get updated stats'))

        results = results['result']['clusterCapacity']
        free_capacity =\
            results['maxProvisionedSpace'] - results['usedSpace']

        data = {}
        data["volume_backend_name"] = self.__class__.__name__
        data["vendor_name"] = 'SolidFire Inc'
        data["driver_version"] = '1.2'
        data["storage_protocol"] = 'iSCSI'

        data['total_capacity_gb'] = results['maxProvisionedSpace']
        data['free_capacity_gb'] = free_capacity
        data['reserved_percentage'] = FLAGS.reserved_percentage
        data['QoS_support'] = True
        data['compression_percent'] =\
            results['compressionPercent']
        data['deduplicaton_percent'] =\
            results['deDuplicationPercent']
        data['thin_provision_percent'] =\
            results['thinProvisioningPercent']
        self.cluster_stats = data
