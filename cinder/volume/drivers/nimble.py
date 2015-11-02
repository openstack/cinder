# Nimble Storage, Inc. (c) 2013-2014
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
Volume driver for Nimble Storage.

This driver supports Nimble Storage controller CS-Series.

"""
import functools
import random
import re
import six
import string
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import units
from six.moves import urllib
from suds import client

from cinder import exception
from cinder.i18n import _, _LE, _LI, _LW
from cinder.objects import volume
from cinder.volume.drivers.san import san
from cinder.volume import volume_types


DRIVER_VERSION = '2.0.2'
AES_256_XTS_CIPHER = 2
DEFAULT_CIPHER = 3
EXTRA_SPEC_ENCRYPTION = 'nimble:encryption'
EXTRA_SPEC_PERF_POLICY = 'nimble:perfpol-name'
EXTRA_SPEC_MULTI_INITIATOR = 'nimble:multi-initiator'
DEFAULT_PERF_POLICY_SETTING = 'default'
DEFAULT_ENCRYPTION_SETTING = 'no'
DEFAULT_MULTI_INITIATOR_SETTING = 'false'
DEFAULT_SNAP_QUOTA = sys.maxsize
VOL_EDIT_MASK = 4 + 16 + 32 + 64 + 256 + 512
MANAGE_EDIT_MASK = 1 + 262144
UNMANAGE_EDIT_MASK = 262144
AGENT_TYPE_OPENSTACK = 5
AGENT_TYPE_NONE = 1
SOAP_PORT = 5391
SM_ACL_APPLY_TO_BOTH = 3
SM_ACL_CHAP_USER_ANY = '*'
SM_SUBNET_DATA = 3
SM_SUBNET_MGMT_PLUS_DATA = 4
LUN_ID = '0'
WARN_LEVEL = 0.8

LOG = logging.getLogger(__name__)

nimble_opts = [
    cfg.StrOpt('nimble_pool_name',
               default='default',
               help='Nimble Controller pool name'),
    cfg.StrOpt('nimble_subnet_label',
               default='*',
               help='Nimble Subnet Label'), ]


CONF = cfg.CONF
CONF.register_opts(nimble_opts)


class NimbleDriverException(exception.VolumeDriverException):
    message = _("Nimble Cinder Driver exception")


class NimbleAPIException(exception.VolumeBackendAPIException):
    message = _("Unexpected response from Nimble API")


class NimbleISCSIDriver(san.SanISCSIDriver):

    """OpenStack driver to enable Nimble Controller.

    Version history:
        1.0 - Initial driver
        1.1.1 - Updated VERSION to Nimble driver version
        1.1.2 - Update snap-quota to unlimited
        2.0.0 - Added Extra Spec Capability
                Correct capacity reporting
                Added Manage/Unmanage volume support
        2.0.1 - Added multi-initiator support through extra-specs
        2.0.2 - Fixed supporting extra specs while cloning vols
    """

    VERSION = DRIVER_VERSION

    def __init__(self, *args, **kwargs):
        super(NimbleISCSIDriver, self).__init__(*args, **kwargs)
        self.APIExecutor = None
        self.group_stats = {}
        self.configuration.append_config_values(nimble_opts)

    def _check_config(self):
        """Ensure that the flags we care about are set."""
        required_config = ['san_ip', 'san_login', 'san_password']
        for attr in required_config:
            if not getattr(self.configuration, attr, None):
                raise exception.InvalidInput(reason=_('%s is not set.') %
                                             attr)

    def _get_discovery_ip(self, netconfig):
        """Get discovery ip."""
        subnet_label = self.configuration.nimble_subnet_label
        LOG.debug('subnet_label used %(netlabel)s, netconfig %(netconf)s',
                  {'netlabel': subnet_label, 'netconf': netconfig})
        ret_discovery_ip = ''
        for subnet in netconfig['subnet-list']:
            LOG.info(_LI('Exploring array subnet label %s'), subnet['label'])
            if subnet_label == '*':
                # Use the first data subnet, save mgmt+data for later
                if subnet['subnet-id']['type'] == SM_SUBNET_DATA:
                    LOG.info(_LI('Discovery ip %(disc_ip)s is used '
                                 'on data subnet %(net_label)s'),
                             {'disc_ip': subnet['discovery-ip'],
                              'net_label': subnet['label']})
                    return subnet['discovery-ip']
                elif (subnet['subnet-id']['type'] ==
                        SM_SUBNET_MGMT_PLUS_DATA):
                    LOG.info(_LI('Discovery ip %(disc_ip)s is found'
                                 ' on mgmt+data subnet %(net_label)s'),
                             {'disc_ip': subnet['discovery-ip'],
                              'net_label': subnet['label']})
                    ret_discovery_ip = subnet['discovery-ip']
            # If subnet is specified and found, use the subnet
            elif subnet_label == subnet['label']:
                LOG.info(_LI('Discovery ip %(disc_ip)s is used'
                             ' on subnet %(net_label)s'),
                         {'disc_ip': subnet['discovery-ip'],
                          'net_label': subnet['label']})
                return subnet['discovery-ip']
        if ret_discovery_ip:
            LOG.info(_LI('Discovery ip %s is used on mgmt+data subnet'),
                     ret_discovery_ip)
            return ret_discovery_ip
        else:
            raise NimbleDriverException(_('No suitable discovery ip found'))

    def _update_existing_vols_agent_type(self, context):
        LOG.debug("Updating existing volumes to have "
                  "agent_type = 'OPENSTACK'")
        backend_name = self.configuration.safe_get('volume_backend_name')
        all_vols = volume.VolumeList.get_all(
            context, None, None, None, None, {'status': 'available'})
        for vol in all_vols:
            if backend_name in vol.host:
                try:
                    self.APIExecutor.edit_vol(
                        vol.name,
                        UNMANAGE_EDIT_MASK,
                        {'agent-type': AGENT_TYPE_OPENSTACK})
                except NimbleAPIException:
                    LOG.warning(_LW('Error updating agent-type for '
                                    'volume %s.'), vol.name)

    def do_setup(self, context):
        """Setup the Nimble Cinder volume driver."""
        self._check_config()
        # Setup API Executor
        try:
            self.APIExecutor = NimbleAPIExecutor(
                username=self.configuration.san_login,
                password=self.configuration.san_password,
                ip=self.configuration.san_ip)
        except Exception:
            LOG.error(_LE('Failed to create SOAP client.'
                          'Check san_ip, username, password'
                          ' and make sure the array version is compatible'))
            raise
        self._update_existing_vols_agent_type(context)

    def _get_provider_location(self, volume_name):
        """Get volume iqn for initiator access."""
        vol_info = self.APIExecutor.get_vol_info(volume_name)
        iqn = vol_info['target-name']
        netconfig = self.APIExecutor.get_netconfig('active')
        target_ipaddr = self._get_discovery_ip(netconfig)
        iscsi_portal = target_ipaddr + ':3260'
        provider_location = '%s %s %s' % (iscsi_portal, iqn, LUN_ID)
        LOG.info(_LI('vol_name=%(name)s provider_location=%(loc)s'),
                 {'name': volume_name, 'loc': provider_location})
        return provider_location

    def _get_model_info(self, volume_name):
        """Get model info for the volume."""
        return (
            {'provider_location': self._get_provider_location(volume_name),
             'provider_auth': None})

    def create_volume(self, volume):
        """Create a new volume."""
        reserve = not self.configuration.san_thin_provision
        self.APIExecutor.create_vol(
            volume,
            self.configuration.nimble_pool_name, reserve)
        return self._get_model_info(volume['name'])

    def delete_volume(self, volume):
        """Delete the specified volume."""
        self.APIExecutor.online_vol(volume['name'], False,
                                    ignore_list=['SM-enoent'])
        self.APIExecutor.dissociate_volcoll(volume['name'],
                                            ignore_list=['SM-enoent'])
        self.APIExecutor.delete_vol(volume['name'], ignore_list=['SM-enoent'])

    def _generate_random_string(self, length):
        """Generates random_string."""
        char_set = string.ascii_lowercase
        return ''.join(random.sample(char_set, length))

    def _clone_volume_from_snapshot(self, volume, snapshot):
        """Clone volume from snapshot.

        Extend the volume if the size of the volume is more than the snapshot.
        """
        reserve = not self.configuration.san_thin_provision
        self.APIExecutor.clone_vol(volume, snapshot, reserve)
        if(volume['size'] > snapshot['volume_size']):
            vol_size = volume['size'] * units.Gi
            reserve_size = vol_size if reserve else 0
            self.APIExecutor.edit_vol(
                volume['name'],
                VOL_EDIT_MASK,  # mask for vol attributes
                {'size': vol_size,
                 'reserve': reserve_size,
                 'warn-level': int(vol_size * WARN_LEVEL),
                 'quota': vol_size,
                 'snap-quota': DEFAULT_SNAP_QUOTA})
        return self._get_model_info(volume['name'])

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        snapshot_name = ('openstack-clone-' +
                         volume['name'] + '-' +
                         self._generate_random_string(12))
        snapshot = {'volume_name': src_vref['name'],
                    'name': snapshot_name,
                    'volume_size': src_vref['size'],
                    'display_name': '',
                    'display_description': ''}
        self.APIExecutor.snap_vol(snapshot)
        self._clone_volume_from_snapshot(volume, snapshot)
        return self._get_model_info(volume['name'])

    def create_export(self, context, volume, connector):
        """Driver entry point to get the export info for a new volume."""
        return self._get_model_info(volume['name'])

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        return self._get_model_info(volume['name'])

    def create_snapshot(self, snapshot):
        """Create a snapshot."""
        self.APIExecutor.snap_vol(snapshot)

    def delete_snapshot(self, snapshot):
        """Delete a snapshot."""
        self.APIExecutor.online_snap(
            snapshot['volume_name'],
            False,
            snapshot['name'],
            ignore_list=['SM-ealready', 'SM-enoent'])
        self.APIExecutor.delete_snap(snapshot['volume_name'],
                                     snapshot['name'],
                                     ignore_list=['SM-enoent'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Create a volume from a snapshot."""
        self._clone_volume_from_snapshot(volume, snapshot)
        return self._get_model_info(volume['name'])

    def get_volume_stats(self, refresh=False):
        """Get volume stats. This is more of getting group stats."""
        if refresh:
            group_info = self.APIExecutor.get_group_config()
            if not group_info['spaceInfoValid']:
                raise NimbleDriverException(_('SpaceInfo returned by'
                                              'array is invalid'))
            total_capacity = (group_info['usableCapacity'] /
                              float(units.Gi))
            used_space = ((group_info['volUsageCompressed'] +
                          group_info['snapUsageCompressed'] +
                          group_info['unusedReserve']) /
                          float(units.Gi))
            free_space = total_capacity - used_space
            LOG.debug('total_capacity=%(capacity)f '
                      'used_space=%(used)f free_space=%(free)f',
                      {'capacity': total_capacity,
                       'used': used_space,
                       'free': free_space})
            backend_name = self.configuration.safe_get(
                'volume_backend_name') or self.__class__.__name__
            self.group_stats = {'volume_backend_name': backend_name,
                                'vendor_name': 'Nimble',
                                'driver_version': DRIVER_VERSION,
                                'storage_protocol': 'iSCSI'}
            # Just use a single pool for now, FIXME to support multiple
            # pools
            single_pool = dict(
                pool_name=backend_name,
                total_capacity_gb=total_capacity,
                free_capacity_gb=free_space,
                reserved_percentage=0,
                QoS_support=False)
            self.group_stats['pools'] = [single_pool]
        return self.group_stats

    def extend_volume(self, volume, new_size):
        """Extend an existing volume."""
        volume_name = volume['name']
        LOG.info(_LI('Entering extend_volume volume=%(vol)s '
                     'new_size=%(size)s'),
                 {'vol': volume_name, 'size': new_size})
        vol_size = int(new_size) * units.Gi
        reserve = not self.configuration.san_thin_provision
        reserve_size = vol_size if reserve else 0
        self.APIExecutor.edit_vol(
            volume_name,
            VOL_EDIT_MASK,  # mask for vol attributes
            {'size': vol_size,
             'reserve': reserve_size,
             'warn-level': int(vol_size * WARN_LEVEL),
             'quota': vol_size,
             'snap-quota': DEFAULT_SNAP_QUOTA})

    def _get_existing_volume_ref_name(self, existing_ref):
        """Returns the volume name of an existing ref"""

        vol_name = None
        if 'source-name' in existing_ref:
            vol_name = existing_ref['source-name']
        else:
            reason = _("Reference must contain source-name.")
            raise exception.ManageExistingInvalidReference(
                existing_ref=existing_ref,
                reason=reason)

        return vol_name

    def manage_existing(self, volume, external_ref):
        """Manage an existing nimble volume (import to cinder)"""

        # Get the volume name from the external reference
        target_vol_name = self._get_existing_volume_ref_name(external_ref)
        LOG.debug('Entering manage_existing. '
                  'Target_volume_name = %s', target_vol_name)

        # Get vol info from the volume name obtained from the reference
        vol_info = self.APIExecutor.get_vol_info(target_vol_name)

        # Check if volume is already managed by Openstack
        if vol_info['agent-type'] == AGENT_TYPE_OPENSTACK:
            msg = (_('Volume %s is already managed by Openstack.')
                   % target_vol_name)
            raise exception.ManageExistingAlreadyManaged(
                volume_ref=volume['id'])

        # If agent-type is not None then raise exception
        if vol_info['agent-type'] != AGENT_TYPE_NONE:
            msg = (_('Volume should have agent-type set as None.'))
            raise exception.InvalidVolume(reason=msg)

        new_vol_name = volume['name']

        if vol_info['online']:
            msg = (_('Volume %s is online. Set volume to offline for '
                     'managing using Openstack.') % target_vol_name)
            raise exception.InvalidVolume(reason=msg)

        # edit the volume
        self.APIExecutor.edit_vol(target_vol_name,
                                  MANAGE_EDIT_MASK,
                                  {'name': new_vol_name,
                                   'agent-type': AGENT_TYPE_OPENSTACK})

        # make the volume online after rename
        self.APIExecutor.online_vol(new_vol_name, True, ignore_list=[
            'SM-enoent'])

        return self._get_model_info(new_vol_name)

    def manage_existing_get_size(self, volume, external_ref):
        """Return size of an existing volume"""

        LOG.debug('Volume name : %(name)s  External ref : %(ref)s',
                  {'name': volume['name'], 'ref': external_ref})

        target_vol_name = self._get_existing_volume_ref_name(external_ref)

        # get vol info
        vol_info = self.APIExecutor.get_vol_info(target_vol_name)

        LOG.debug('Volume size : %(size)s  Volume-name : %(name)s',
                  {'size': vol_info['size'], 'name': vol_info['name']})

        return int(vol_info['size'] / units.Gi)

    def unmanage(self, volume):
        """Removes the specified volume from Cinder management."""

        vol_name = volume['name']
        LOG.info(_LI("Entering unmanage_volume volume = %s"), vol_name)

        # check agent type
        vol_info = self.APIExecutor.get_vol_info(vol_name)
        if vol_info['agent-type'] != AGENT_TYPE_OPENSTACK:
            msg = (_('Only volumes managed by Openstack can be unmanaged.'))
            raise exception.InvalidVolume(reason=msg)

        # update the agent-type to None
        self.APIExecutor.edit_vol(vol_name,
                                  UNMANAGE_EDIT_MASK,
                                  {'agent-type': AGENT_TYPE_NONE})

        # offline the volume
        self.APIExecutor.online_vol(vol_name, False, ignore_list=[
            'SM-enoent'])

    def _create_igroup_for_initiator(self, initiator_name):
        """Creates igroup for an initiator and returns the igroup name."""
        igrp_name = 'openstack-' + self._generate_random_string(12)
        LOG.info(_LI('Creating initiator group %(grp)s '
                     'with initiator %(iname)s'),
                 {'grp': igrp_name, 'iname': initiator_name})
        self.APIExecutor.create_initiator_group(igrp_name, initiator_name)
        return igrp_name

    def _get_igroupname_for_initiator(self, initiator_name):
        initiator_groups = self.APIExecutor.get_initiator_grp_list()
        for initiator_group in initiator_groups:
            if 'initiator-list' in initiator_group:
                if (len(initiator_group['initiator-list']) == 1 and
                    initiator_group['initiator-list'][0]['name'] ==
                        initiator_name):
                    LOG.info(_LI('igroup %(grp)s found for '
                                 'initiator %(iname)s'),
                             {'grp': initiator_group['name'],
                              'iname': initiator_name})
                    return initiator_group['name']
        LOG.info(_LI('No igroup found for initiator %s'), initiator_name)
        return ''

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance."""
        LOG.info(_LI('Entering initialize_connection volume=%(vol)s'
                     ' connector=%(conn)s location=%(loc)s'),
                 {'vol': volume,
                  'conn': connector,
                  'loc': volume['provider_location']})
        initiator_name = connector['initiator']
        initiator_group_name = self._get_igroupname_for_initiator(
            initiator_name)
        if not initiator_group_name:
            initiator_group_name = self._create_igroup_for_initiator(
                initiator_name)
        LOG.info(_LI('Initiator group name is %(grp)s for initiator '
                     '%(iname)s'),
                 {'grp': initiator_group_name, 'iname': initiator_name})
        self.APIExecutor.add_acl(volume, initiator_group_name)
        (iscsi_portal, iqn, lun_num) = volume['provider_location'].split()
        properties = {}
        properties['target_discovered'] = False  # whether discovery was used
        properties['target_portal'] = iscsi_portal
        properties['target_iqn'] = iqn
        properties['target_lun'] = lun_num
        properties['volume_id'] = volume['id']  # used by xen currently
        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance."""
        LOG.info(_LI('Entering terminate_connection volume=%(vol)s'
                     ' connector=%(conn)s location=%(loc)s.'),
                 {'vol': volume,
                  'conn': connector,
                  'loc': volume['provider_location']})
        initiator_name = connector['initiator']
        initiator_group_name = self._get_igroupname_for_initiator(
            initiator_name)
        if not initiator_group_name:
            raise NimbleDriverException(
                _('No initiator group found for initiator %s') %
                initiator_name)
        self.APIExecutor.remove_acl(volume, initiator_group_name)


def _response_checker(func):
    """Decorator function to check if the response of an API is positive."""
    @functools.wraps(func)
    def inner_response_checker(self, *args, **kwargs):
        response = func(self, *args, **kwargs)
        ignore_list = (kwargs['ignore_list']
                       if 'ignore_list' in kwargs else [])
        for err in response['err-list']['err-list']:
            err_str = self._get_err_str(err['code'])
            if err_str != 'SM-ok' and err_str not in ignore_list:
                msg = (_('API %(name)s failed with error string %(err)s')
                       % {'name': func.__name__, 'err': err_str})
                LOG.error(msg)
                raise NimbleAPIException(msg)
            return response
    return inner_response_checker


def _connection_checker(func):
    """Decorator to re-establish and re-run the api if session has expired."""
    @functools.wraps(func)
    def inner_connection_checker(self, *args, **kwargs):
        for attempts in range(2):
            try:
                return func(self, *args, **kwargs)
            except NimbleAPIException as e:
                if attempts < 1 and (re.search('SM-eaccess',
                                     six.text_type(e))):
                    LOG.info(_LI('Session might have expired.'
                                 ' Trying to relogin'))
                    self.login()
                    continue
                else:
                    LOG.error(_LE('Re-throwing Exception %s'), e)
                    raise
    return inner_connection_checker


class NimbleAPIExecutor(object):

    """Makes Nimble API calls."""

    def __init__(self, *args, **kwargs):
        self.sid = None
        self.username = kwargs['username']
        self.password = kwargs['password']

        wsdl_url = 'https://%s/wsdl/NsGroupManagement.wsdl' % (kwargs['ip'])
        LOG.debug('Using Nimble wsdl_url: %s', wsdl_url)
        self.err_string_dict = self._create_err_code_to_str_mapper(wsdl_url)
        self.client = client.Client(wsdl_url,
                                    username=self.username,
                                    password=self.password)
        soap_url = ('https://%(ip)s:%(port)s/soap' % {'ip': kwargs['ip'],
                                                      'port': SOAP_PORT})
        LOG.debug('Using Nimble soap_url: %s', soap_url)
        self.client.set_options(location=soap_url)
        self.login()

    def _create_err_code_to_str_mapper(self, wsdl_url):
        f = urllib.request.urlopen(wsdl_url)
        wsdl_file = f.read()
        err_enums = re.findall(
            r'<simpleType name="SmErrorType">(.*?)</simpleType>',
            wsdl_file,
            re.DOTALL)
        err_enums = ''.join(err_enums).split('\n')
        ret_dict = {}
        for enum in err_enums:
            m = re.search(r'"(.*?)"(.*?)= (\d+) ', enum)
            if m:
                ret_dict[int(m.group(3))] = m.group(1)
        return ret_dict

    def _get_err_str(self, code):
        if code in self.err_string_dict:
            return self.err_string_dict[code]
        else:
            return 'Unknown error Code: %s' % code

    @_response_checker
    def _execute_login(self):
        return self.client.service.login(req={
            'username': self.username,
            'password': self.password
        })

    def login(self):
        """Execute Https Login API."""
        response = self._execute_login()
        LOG.info(_LI('Successful login by user %s'), self.username)
        self.sid = response['authInfo']['sid']

    @_connection_checker
    @_response_checker
    def _execute_get_netconfig(self, name):
        return self.client.service.getNetConfig(request={'sid': self.sid,
                                                         'name': name})

    def get_netconfig(self, name):
        """Execute getNetConfig API."""
        response = self._execute_get_netconfig(name)
        return response['config']

    def _get_volumetype_extraspecs(self, volume):
        specs = {}

        type_id = volume['volume_type_id']
        if type_id is not None:
            specs = volume_types.get_volume_type_extra_specs(type_id)
        return specs

    def _get_extra_spec_values(self, extra_specs):
        """Nimble specific extra specs."""
        perf_policy_name = extra_specs.get(EXTRA_SPEC_PERF_POLICY,
                                           DEFAULT_PERF_POLICY_SETTING)
        encryption = extra_specs.get(EXTRA_SPEC_ENCRYPTION,
                                     DEFAULT_ENCRYPTION_SETTING)
        multi_initiator = extra_specs.get(EXTRA_SPEC_MULTI_INITIATOR,
                                          DEFAULT_MULTI_INITIATOR_SETTING)
        extra_specs_map = {}
        extra_specs_map[EXTRA_SPEC_PERF_POLICY] = perf_policy_name
        extra_specs_map[EXTRA_SPEC_ENCRYPTION] = encryption
        extra_specs_map[EXTRA_SPEC_MULTI_INITIATOR] = multi_initiator

        return extra_specs_map

    @_connection_checker
    @_response_checker
    def _execute_create_vol(self, volume, pool_name, reserve):
        # Set volume size, display name and description
        volume_size = volume['size'] * units.Gi
        reserve_size = volume_size if reserve else 0
        # Set volume description
        display_list = [getattr(volume, 'display_name', ''),
                        getattr(volume, 'display_description', '')]
        description = ':'.join(filter(None, display_list))
        # Limit description size to 254 characters
        description = description[:254]

        specs = self._get_volumetype_extraspecs(volume)
        extra_specs_map = self._get_extra_spec_values(specs)
        perf_policy_name = extra_specs_map[EXTRA_SPEC_PERF_POLICY]
        encrypt = extra_specs_map[EXTRA_SPEC_ENCRYPTION]
        multi_initiator = extra_specs_map[EXTRA_SPEC_MULTI_INITIATOR]
        # default value of cipher for encryption
        cipher = DEFAULT_CIPHER
        if encrypt.lower() == 'yes':
            cipher = AES_256_XTS_CIPHER

        LOG.debug('Creating a new volume=%(vol)s size=%(size)s'
                  ' reserve=%(reserve)s in pool=%(pool)s'
                  ' description=%(description)s with Extra Specs'
                  ' perfpol-name=%(perfpol-name)s'
                  ' encryption=%(encryption)s cipher=%(cipher)s'
                  ' agent-type=%(agent-type)s'
                  ' multi-initiator=%(multi-initiator)s',
                  {'vol': volume['name'],
                   'size': volume_size,
                   'reserve': reserve,
                   'pool': pool_name,
                   'description': description,
                   'perfpol-name': perf_policy_name,
                   'encryption': encrypt,
                   'cipher': cipher,
                   'agent-type': AGENT_TYPE_OPENSTACK,
                   'multi-initiator': multi_initiator})

        return self.client.service.createVol(
            request={'sid': self.sid,
                     'attr': {'name': volume['name'],
                              'description': description,
                              'size': volume_size,
                              'reserve': reserve_size,
                              'warn-level': int(volume_size * WARN_LEVEL),
                              'quota': volume_size,
                              'snap-quota': DEFAULT_SNAP_QUOTA,
                              'online': True,
                              'pool-name': pool_name,
                              'agent-type': AGENT_TYPE_OPENSTACK,
                              'perfpol-name': perf_policy_name,
                              'encryptionAttr': {'cipher': cipher},
                              'multi-initiator': multi_initiator}})

    def create_vol(self, volume, pool_name, reserve):
        """Execute createVol API."""
        response = self._execute_create_vol(volume, pool_name, reserve)
        LOG.info(_LI('Successfully create volume %s'), response['name'])
        return response['name']

    @_connection_checker
    @_response_checker
    def _execute_get_group_config(self):
        LOG.debug('Getting group config information')
        return self.client.service.getGroupConfig(request={'sid': self.sid})

    def get_group_config(self):
        """Execute getGroupConfig API."""
        response = self._execute_get_group_config()
        LOG.debug('Successfully retrieved group config information')
        return response['info']

    @_connection_checker
    @_response_checker
    def add_acl(self, volume, initiator_group_name):
        """Execute addAcl API."""
        LOG.info(_LI('Adding ACL to volume=%(vol)s with'
                     ' initiator group name %(igrp)s'),
                 {'vol': volume['name'],
                  'igrp': initiator_group_name})
        return self.client.service.addVolAcl(
            request={'sid': self.sid,
                     'volname': volume['name'],
                     'apply-to': SM_ACL_APPLY_TO_BOTH,
                     'chapuser': SM_ACL_CHAP_USER_ANY,
                     'initiatorgrp': initiator_group_name})

    @_connection_checker
    @_response_checker
    def remove_acl(self, volume, initiator_group_name):
        """Execute removeVolAcl API."""
        LOG.info(_LI('Removing ACL from volume=%(vol)s'
                     ' for initiator group %(igrp)s'),
                 {'vol': volume['name'],
                  'igrp': initiator_group_name})
        return self.client.service.removeVolAcl(
            request={'sid': self.sid,
                     'volname': volume['name'],
                     'apply-to': SM_ACL_APPLY_TO_BOTH,
                     'chapuser': SM_ACL_CHAP_USER_ANY,
                     'initiatorgrp': initiator_group_name})

    @_connection_checker
    @_response_checker
    def _execute_get_vol_info(self, vol_name):
        LOG.info(_LI('Getting volume information '
                     'for vol_name=%s'), vol_name)
        return self.client.service.getVolInfo(request={'sid': self.sid,
                                                       'name': vol_name})

    def get_vol_info(self, vol_name):
        """Execute getVolInfo API."""
        response = self._execute_get_vol_info(vol_name)
        LOG.info(_LI('Successfully got volume information for volume %s'),
                 vol_name)
        return response['vol']

    @_connection_checker
    @_response_checker
    def online_vol(self, vol_name, online_flag, *args, **kwargs):
        """Execute onlineVol API."""
        LOG.info(_LI('Setting volume %(vol)s to online_flag %(flag)s'),
                 {'vol': vol_name, 'flag': online_flag})
        return self.client.service.onlineVol(request={'sid': self.sid,
                                                      'name': vol_name,
                                                      'online': online_flag})

    @_connection_checker
    @_response_checker
    def online_snap(self, vol_name, online_flag, snap_name, *args, **kwargs):
        """Execute onlineSnap API."""
        LOG.info(_LI('Setting snapshot %(snap)s to online_flag %(flag)s'),
                 {'snap': snap_name, 'flag': online_flag})
        return self.client.service.onlineSnap(request={'sid': self.sid,
                                                       'vol': vol_name,
                                                       'name': snap_name,
                                                       'online': online_flag})

    @_connection_checker
    @_response_checker
    def dissociate_volcoll(self, vol_name, *args, **kwargs):
        """Execute dissocProtPol API."""
        LOG.info(_LI('Dissociating volume %s '), vol_name)
        return self.client.service.dissocProtPol(
            request={'sid': self.sid,
                     'vol-name': vol_name})

    @_connection_checker
    @_response_checker
    def delete_vol(self, vol_name, *args, **kwargs):
        """Execute deleteVol API."""
        LOG.info(_LI('Deleting volume %s '), vol_name)
        return self.client.service.deleteVol(request={'sid': self.sid,
                                                      'name': vol_name})

    @_connection_checker
    @_response_checker
    def snap_vol(self, snapshot):
        """Execute snapVol API."""
        volume_name = snapshot['volume_name']
        snap_name = snapshot['name']
        # Set snapshot description
        display_list = [getattr(snapshot, 'display_name', ''),
                        getattr(snapshot, 'display_description', '')]
        snap_description = ':'.join(filter(None, display_list))
        # Limit to 254 characters
        snap_description = snap_description[:254]
        LOG.info(_LI('Creating snapshot for volume_name=%(vol)s'
                     ' snap_name=%(name)s snap_description=%(desc)s'),
                 {'vol': volume_name,
                  'name': snap_name,
                  'desc': snap_description})
        return self.client.service.snapVol(
            request={'sid': self.sid,
                     'vol': volume_name,
                     'snapAttr': {'name': snap_name,
                                  'description': snap_description}})

    @_connection_checker
    @_response_checker
    def delete_snap(self, vol_name, snap_name, *args, **kwargs):
        """Execute deleteSnap API."""
        LOG.info(_LI('Deleting snapshot %s '), snap_name)
        return self.client.service.deleteSnap(request={'sid': self.sid,
                                                       'vol': vol_name,
                                                       'name': snap_name})

    @_connection_checker
    @_response_checker
    def clone_vol(self, volume, snapshot, reserve):
        """Execute cloneVol API."""
        volume_name = snapshot['volume_name']
        snap_name = snapshot['name']
        clone_name = volume['name']
        snap_size = snapshot['volume_size']
        reserve_size = snap_size * units.Gi if reserve else 0

        specs = self._get_volumetype_extraspecs(volume)
        extra_specs_map = self._get_extra_spec_values(specs)
        perf_policy_name = extra_specs_map.get(EXTRA_SPEC_PERF_POLICY)
        encrypt = extra_specs_map.get(EXTRA_SPEC_ENCRYPTION)
        multi_initiator = extra_specs_map.get(EXTRA_SPEC_MULTI_INITIATOR)
        # default value of cipher for encryption
        cipher = DEFAULT_CIPHER
        if encrypt.lower() == 'yes':
            cipher = AES_256_XTS_CIPHER

        LOG.info(_LI('Cloning volume from snapshot volume=%(vol)s '
                     'snapshot=%(snap)s clone=%(clone)s snap_size=%(size)s '
                     'reserve=%(reserve)s' 'agent-type=%(agent-type)s '
                     'perfpol-name=%(perfpol-name)s '
                     'encryption=%(encryption)s cipher=%(cipher)s '
                     'multi-initiator=%(multi-initiator)s'),
                 {'vol': volume_name,
                  'snap': snap_name,
                  'clone': clone_name,
                  'size': snap_size,
                  'reserve': reserve,
                  'agent-type': AGENT_TYPE_OPENSTACK,
                  'perfpol-name': perf_policy_name,
                  'encryption': encrypt,
                  'cipher': cipher,
                  'multi-initiator': multi_initiator})
        clone_size = snap_size * units.Gi
        return self.client.service.cloneVol(
            request={'sid': self.sid,
                     'name': volume_name,
                     'attr': {'name': clone_name,
                              'reserve': reserve_size,
                              'warn-level': int(clone_size * WARN_LEVEL),
                              'quota': clone_size,
                              'snap-quota': DEFAULT_SNAP_QUOTA,
                              'online': True,
                              'agent-type': AGENT_TYPE_OPENSTACK,
                              'perfpol-name': perf_policy_name,
                              'encryptionAttr': {'cipher': cipher},
                              'multi-initiator': multi_initiator},
                     'snap-name': snap_name})

    @_connection_checker
    @_response_checker
    def edit_vol(self, vol_name, mask, attr):
        """Execute editVol API."""
        LOG.info(_LI('Editing Volume %(vol)s with mask %(mask)s'),
                 {'vol': vol_name, 'mask': str(mask)})
        return self.client.service.editVol(request={'sid': self.sid,
                                                    'name': vol_name,
                                                    'mask': mask,
                                                    'attr': attr})

    @_connection_checker
    @_response_checker
    def _execute_get_initiator_grp_list(self):
        LOG.info(_LI('Getting getInitiatorGrpList'))
        return (self.client.service.getInitiatorGrpList(
            request={'sid': self.sid}))

    def get_initiator_grp_list(self):
        """Execute getInitiatorGrpList API."""
        response = self._execute_get_initiator_grp_list()
        LOG.info(_LI('Successfully retrieved InitiatorGrpList'))
        return (response['initiatorgrp-list']
                if 'initiatorgrp-list' in response else [])

    @_connection_checker
    @_response_checker
    def create_initiator_group(self, initiator_group_name, initiator_name):
        """Execute createInitiatorGrp API."""
        LOG.info(_LI('Creating initiator group %(igrp)s'
                     ' with one initiator %(iname)s'),
                 {'igrp': initiator_group_name, 'iname': initiator_name})
        return self.client.service.createInitiatorGrp(
            request={'sid': self.sid,
                     'attr': {'name': initiator_group_name,
                              'initiator-list': [{'label': initiator_name,
                                                  'name': initiator_name}]}})

    @_connection_checker
    @_response_checker
    def delete_initiator_group(self, initiator_group_name, *args, **kwargs):
        """Execute deleteInitiatorGrp API."""
        LOG.info(_LI('Deleting deleteInitiatorGrp %s '), initiator_group_name)
        return self.client.service.deleteInitiatorGrp(
            request={'sid': self.sid,
                     'name': initiator_group_name})
