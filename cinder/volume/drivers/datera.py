# Copyright 2016 Datera
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

import functools
import json
import re
import uuid

import eventlet
import ipaddress
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units
import requests
import six

from cinder import context
from cinder import exception
from cinder.i18n import _, _LE, _LI
from cinder import interface
from cinder import utils
from cinder.volume.drivers.san import san
from cinder.volume import qos_specs
from cinder.volume import utils as volutils
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

d_opts = [
    cfg.StrOpt('datera_api_port',
               default='7717',
               help='Datera API port.'),
    cfg.StrOpt('datera_api_version',
               default='2',
               help='Datera API version.'),
    cfg.IntOpt('datera_num_replicas',
               default='3',
               deprecated_for_removal=True,
               help='Number of replicas to create of an inode.'),
    cfg.IntOpt('datera_503_timeout',
               default='120',
               help='Timeout for HTTP 503 retry messages'),
    cfg.IntOpt('datera_503_interval',
               default='5',
               help='Interval between 503 retries'),
    cfg.BoolOpt('datera_debug',
                default=False,
                help="True to set function arg and return logging"),
    cfg.BoolOpt('datera_acl_allow_all',
                default=False,
                deprecated_for_removal=True,
                help="True to set acl 'allow_all' on volumes "
                     "created"),
    cfg.BoolOpt('datera_debug_replica_count_override',
                default=False,
                help="ONLY FOR DEBUG/TESTING PURPOSES\n"
                     "True to set replica_count to 1")
]


CONF = cfg.CONF
CONF.import_opt('driver_use_ssl', 'cinder.volume.driver')
CONF.register_opts(d_opts)

DEFAULT_SI_SLEEP = 10
INITIATOR_GROUP_PREFIX = "IG-"
OS_PREFIX = "OS-"
UNMANAGE_PREFIX = "UNMANAGED-"

# Taken from this SO post :
# http://stackoverflow.com/a/18516125
# Using old-style string formatting because of the nature of the regex
# conflicting with new-style curly braces
UUID4_STR_RE = ("%s[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab]"
                "[a-f0-9]{3}-?[a-f0-9]{12}")
UUID4_RE = re.compile(UUID4_STR_RE % OS_PREFIX)

# Recursive dict to assemble basic url structure for the most common
# API URL endpoints. Most others are constructed from these
URL_TEMPLATES = {
    'ai': lambda: 'app_instances',
    'ai_inst': lambda: (URL_TEMPLATES['ai']() + '/{}'),
    'si': lambda: (URL_TEMPLATES['ai_inst']() + '/storage_instances'),
    'si_inst': lambda storage_name: (
        (URL_TEMPLATES['si']() + '/{}').format(
            '{}', storage_name)),
    'vol': lambda storage_name: (
        (URL_TEMPLATES['si_inst'](storage_name) + '/volumes')),
    'vol_inst': lambda storage_name, volume_name: (
        (URL_TEMPLATES['vol'](storage_name) + '/{}').format(
            '{}', volume_name))}


def _get_name(name):
    return "".join((OS_PREFIX, name))


def _get_unmanaged(name):
    return "".join((UNMANAGE_PREFIX, name))


def _authenticated(func):
    """Ensure the driver is authenticated to make a request.

    In do_setup() we fetch an auth token and store it. If that expires when
    we do API request, we'll fetch a new one.
    """
    @functools.wraps(func)
    def func_wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except exception.NotAuthorized:
            # Prevent recursion loop. After the self arg is the
            # resource_type arg from _issue_api_request(). If attempt to
            # login failed, we should just give up.
            if args[0] == 'login':
                raise

            # Token might've expired, get a new one, try again.
            self._login()
            return func(self, *args, **kwargs)
    return func_wrapper


@interface.volumedriver
@six.add_metaclass(utils.TraceWrapperWithABCMetaclass)
class DateraDriver(san.SanISCSIDriver):

    """The OpenStack Datera Driver

    Version history:
        1.0 - Initial driver
        1.1 - Look for lun-0 instead of lun-1.
        2.0 - Update For Datera API v2
        2.1 - Multipath, ACL and reorg
        2.2 - Capabilites List, Extended Volume-Type Support
              Naming convention change,
              Volume Manage/Unmanage support
    """
    VERSION = '2.2'

    CI_WIKI_NAME = "datera-ci"

    def __init__(self, *args, **kwargs):
        super(DateraDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(d_opts)
        self.username = self.configuration.san_login
        self.password = self.configuration.san_password
        self.cluster_stats = {}
        self.datera_api_token = None
        self.interval = self.configuration.datera_503_interval
        self.retry_attempts = (self.configuration.datera_503_timeout /
                               self.interval)
        self.driver_prefix = str(uuid.uuid4())[:4]
        self.datera_debug = self.configuration.datera_debug

        if self.datera_debug:
            utils.setup_tracing(['method'])

    def do_setup(self, context):
        # If we can't authenticate through the old and new method, just fail
        # now.
        if not all([self.username, self.password]):
            msg = _("san_login and/or san_password is not set for Datera "
                    "driver in the cinder.conf. Set this information and "
                    "start the cinder-volume service again.")
            LOG.error(msg)
            raise exception.InvalidInput(msg)

        self._login()

    @utils.retry(exception.VolumeDriverException, retries=3)
    def _wait_for_resource(self, id, resource_type, policies):
        result = self._issue_api_request(resource_type, 'get', id)
        if result['storage_instances'][
                policies['default_storage_name']]['volumes'][
                policies['default_volume_name']]['op_state'] == 'available':
            return
        else:
            raise exception.VolumeDriverException(
                message=_('Resource not ready.'))

    def _create_resource(self, resource, resource_type, body):

        result = None
        try:
            result = self._issue_api_request(resource_type, 'post', body=body)
        except exception.Invalid:
            type_id = resource.get('volume_type_id', None)
            if resource_type == 'volumes' and type_id:
                LOG.error(_LE("Creation request failed. Please verify the "
                              "extra-specs set for your volume types are "
                              "entered correctly."))
            raise
        else:
            policies = self._get_policies_for_resource(resource)
            # Handle updating QOS Policies
            if resource_type == URL_TEMPLATES['ai']():
                self._update_qos(resource, policies)
            if result['storage_instances'][policies['default_storage_name']][
                    'volumes'][policies['default_volume_name']][
                        'op_state'] == 'available':
                return
            self._wait_for_resource(_get_name(resource['id']),
                                    resource_type,
                                    policies)

    def create_volume(self, volume):
        """Create a logical volume."""
        # Generate App Instance, Storage Instance and Volume
        # Volume ID will be used as the App Instance Name
        # Storage Instance and Volumes will have standard names
        policies = self._get_policies_for_resource(volume)
        num_replicas = int(policies['replica_count'])
        storage_name = policies['default_storage_name']
        volume_name = policies['default_volume_name']

        app_params = (
            {
                'create_mode': "openstack",
                'uuid': str(volume['id']),
                'name': _get_name(volume['id']),
                'access_control_mode': 'deny_all',
                'storage_instances': {
                    storage_name: {
                        'name': storage_name,
                        'volumes': {
                            volume_name: {
                                'name': volume_name,
                                'size': volume['size'],
                                'replica_count': num_replicas,
                                'snapshot_policies': {
                                }
                            }
                        }
                    }
                }
            })
        self._create_resource(volume, URL_TEMPLATES['ai'](), body=app_params)

    def extend_volume(self, volume, new_size):
        # Offline App Instance, if necessary
        reonline = False
        app_inst = self._issue_api_request(
            URL_TEMPLATES['ai_inst']().format(_get_name(volume['id'])))
        if app_inst['admin_state'] == 'online':
            reonline = True
            self.detach_volume(None, volume, delete_initiator=False)
        # Change Volume Size
        app_inst = _get_name(volume['id'])
        data = {
            'size': new_size
        }
        policies = self._get_policies_for_resource(volume)
        self._issue_api_request(
            URL_TEMPLATES['vol_inst'](
                policies['default_storage_name'],
                policies['default_volume_name']).format(app_inst),
            method='put',
            body=data)
        # Online Volume, if it was online before
        if reonline:
            self.create_export(None, volume, None)

    def create_cloned_volume(self, volume, src_vref):
        policies = self._get_policies_for_resource(volume)
        src = "/" + URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']).format(_get_name(src_vref['id']))
        data = {
            'create_mode': 'openstack',
            'name': _get_name(volume['id']),
            'uuid': str(volume['id']),
            'clone_src': src,
        }
        self._issue_api_request(URL_TEMPLATES['ai'](), 'post', body=data)

        if volume['size'] > src_vref['size']:
            self.extend_volume(volume, volume['size'])

    def delete_volume(self, volume):
        self.detach_volume(None, volume)
        app_inst = _get_name(volume['id'])
        try:
            self._issue_api_request(URL_TEMPLATES['ai_inst']().format(
                app_inst),
                method='delete')
        except exception.NotFound:
            msg = _LI("Tried to delete volume %s, but it was not found in the "
                      "Datera cluster. Continuing with delete.")
            LOG.info(msg, _get_name(volume['id']))

    def ensure_export(self, context, volume, connector):
        """Gets the associated account, retrieves CHAP info and updates."""
        return self.create_export(context, volume, connector)

    def initialize_connection(self, volume, connector):
        # Now online the app_instance (which will online all storage_instances)
        multipath = connector.get('multipath', False)
        url = URL_TEMPLATES['ai_inst']().format(_get_name(volume['id']))
        data = {
            'admin_state': 'online'
        }
        app_inst = self._issue_api_request(url, method='put', body=data)
        storage_instances = app_inst["storage_instances"]
        si_names = list(storage_instances.keys())

        portal = storage_instances[si_names[0]]['access']['ips'][0] + ':3260'
        iqn = storage_instances[si_names[0]]['access']['iqn']
        if multipath:
            portals = [p + ':3260' for p in
                       storage_instances[si_names[0]]['access']['ips']]
            iqns = [iqn for _ in
                    storage_instances[si_names[0]]['access']['ips']]
            lunids = [self._get_lunid() for _ in
                      storage_instances[si_names[0]]['access']['ips']]

            return {
                'driver_volume_type': 'iscsi',
                'data': {
                    'target_discovered': False,
                    'target_iqn': iqn,
                    'target_iqns': iqns,
                    'target_portal': portal,
                    'target_portals': portals,
                    'target_lun': self._get_lunid(),
                    'target_luns': lunids,
                    'volume_id': volume['id'],
                    'discard': False}}
        else:
            return {
                'driver_volume_type': 'iscsi',
                'data': {
                    'target_discovered': False,
                    'target_iqn': iqn,
                    'target_portal': portal,
                    'target_lun': self._get_lunid(),
                    'volume_id': volume['id'],
                    'discard': False}}

    def create_export(self, context, volume, connector):
        # Online volume in case it hasn't been already
        url = URL_TEMPLATES['ai_inst']().format(_get_name(volume['id']))
        data = {
            'admin_state': 'online'
        }
        self._issue_api_request(url, method='put', body=data)
        # Check if we've already setup everything for this volume
        url = (URL_TEMPLATES['si']().format(_get_name(volume['id'])))
        storage_instances = self._issue_api_request(url)
        # Handle adding initiator to product if necessary
        # Then add initiator to ACL
        policies = self._get_policies_for_resource(volume)
        if (connector and
                connector.get('initiator') and
                not policies['acl_allow_all']):
            initiator_name = "OpenStack_{}_{}".format(
                self.driver_prefix, str(uuid.uuid4())[:4])
            initiator_group = INITIATOR_GROUP_PREFIX + volume['id']
            found = False
            initiator = connector['initiator']
            current_initiators = self._issue_api_request('initiators')
            for iqn, values in current_initiators.items():
                if initiator == iqn:
                    found = True
                    break
            # If we didn't find a matching initiator, create one
            if not found:
                data = {'id': initiator, 'name': initiator_name}
                # Try and create the initiator
                # If we get a conflict, ignore it because race conditions
                self._issue_api_request("initiators",
                                        method="post",
                                        body=data,
                                        conflict_ok=True)
            # Create initiator group with initiator in it
            initiator_path = "/initiators/{}".format(initiator)
            initiator_group_path = "/initiator_groups/{}".format(
                initiator_group)
            ig_data = {'name': initiator_group, 'members': [initiator_path]}
            self._issue_api_request("initiator_groups",
                                    method="post",
                                    body=ig_data,
                                    conflict_ok=True)
            # Create ACL with initiator group as reference for each
            # storage_instance in app_instance
            # TODO(_alastor_): We need to avoid changing the ACLs if the
            # template already specifies an ACL policy.
            for si_name in storage_instances.keys():
                acl_url = (URL_TEMPLATES['si']() + "/{}/acl_policy").format(
                    _get_name(volume['id']), si_name)
                data = {'initiator_groups': [initiator_group_path]}
                self._issue_api_request(acl_url,
                                        method="put",
                                        body=data)

        if connector and connector.get('ip'):
            try:
                # Case where volume_type has non default IP Pool info
                if policies['ip_pool'] != 'default':
                    initiator_ip_pool_path = self._issue_api_request(
                        "access_network_ip_pools/{}".format(
                            policies['ip_pool']))['path']
                # Fallback to trying reasonable IP based guess
                else:
                    initiator_ip_pool_path = self._get_ip_pool_for_string_ip(
                        connector['ip'])

                ip_pool_url = URL_TEMPLATES['si_inst'](
                    policies['default_storage_name']).format(
                    _get_name(volume['id']))
                ip_pool_data = {'ip_pool': initiator_ip_pool_path}
                self._issue_api_request(ip_pool_url,
                                        method="put",
                                        body=ip_pool_data)
            except exception.DateraAPIException:
                # Datera product 1.0 support
                pass

        # Check to ensure we're ready for go-time
        self._si_poll(volume, policies)

    def detach_volume(self, context, volume, attachment=None):
        url = URL_TEMPLATES['ai_inst']().format(_get_name(volume['id']))
        data = {
            'admin_state': 'offline',
            'force': True
        }
        try:
            self._issue_api_request(url, method='put', body=data)
        except exception.NotFound:
            msg = _LI("Tried to detach volume %s, but it was not found in the "
                      "Datera cluster. Continuing with detach.")
            LOG.info(msg, volume['id'])
        # TODO(_alastor_): Make acl cleaning multi-attach aware
        self._clean_acl(volume)

    def _check_for_acl(self, initiator_path):
        """Returns True if an acl is found for initiator_path """
        # TODO(_alastor_) when we get a /initiators/:initiator/acl_policies
        # endpoint use that instead of this monstrosity
        initiator_groups = self._issue_api_request("initiator_groups")
        for ig, igdata in initiator_groups.items():
            if initiator_path in igdata['members']:
                LOG.debug("Found initiator_group: %s for initiator: %s",
                          ig, initiator_path)
                return True
        LOG.debug("No initiator_group found for initiator: %s", initiator_path)
        return False

    def _clean_acl(self, volume):
        policies = self._get_policies_for_resource(volume)
        acl_url = (URL_TEMPLATES["si_inst"](
            policies['default_storage_name']) + "/acl_policy").format(
            _get_name(volume['id']))
        try:
            initiator_group = self._issue_api_request(acl_url)[
                'initiator_groups'][0]
            initiator_iqn_path = self._issue_api_request(
                initiator_group.lstrip("/"))["members"][0]
            # Clear out ACL and delete initiator group
            self._issue_api_request(acl_url,
                                    method="put",
                                    body={'initiator_groups': []})
            self._issue_api_request(initiator_group.lstrip("/"),
                                    method="delete")
            if not self._check_for_acl(initiator_iqn_path):
                self._issue_api_request(initiator_iqn_path.lstrip("/"),
                                        method="delete")
        except (IndexError, exception.NotFound):
            LOG.debug("Did not find any initiator groups for volume: %s",
                      volume)

    def create_snapshot(self, snapshot):
        policies = self._get_policies_for_resource(snapshot)
        url_template = URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/snapshots'
        url = url_template.format(_get_name(snapshot['volume_id']))

        snap_params = {
            'uuid': snapshot['id'],
        }
        self._issue_api_request(url, method='post', body=snap_params)

    def delete_snapshot(self, snapshot):
        policies = self._get_policies_for_resource(snapshot)
        snap_temp = URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/snapshots'
        snapu = snap_temp.format(_get_name(snapshot['volume_id']))
        snapshots = self._issue_api_request(snapu, method='get')

        try:
            for ts, snap in snapshots.items():
                if snap['uuid'] == snapshot['id']:
                    url_template = snapu + '/{}'
                    url = url_template.format(ts)
                    self._issue_api_request(url, method='delete')
                    break
            else:
                raise exception.NotFound
        except exception.NotFound:
            msg = _LI("Tried to delete snapshot %s, but was not found in "
                      "Datera cluster. Continuing with delete.")
            LOG.info(msg, _get_name(snapshot['id']))

    def create_volume_from_snapshot(self, volume, snapshot):
        policies = self._get_policies_for_resource(snapshot)
        snap_temp = URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/snapshots'
        snapu = snap_temp.format(_get_name(snapshot['volume_id']))
        snapshots = self._issue_api_request(snapu, method='get')
        for ts, snap in snapshots.items():
            if snap['uuid'] == snapshot['id']:
                found_ts = ts
                break
        else:
            raise exception.NotFound

        src = "/" + (snap_temp + '/{}').format(
            _get_name(snapshot['volume_id']), found_ts)
        app_params = (
            {
                'create_mode': 'openstack',
                'uuid': str(volume['id']),
                'name': _get_name(volume['id']),
                'clone_src': src,
            })
        self._issue_api_request(
            URL_TEMPLATES['ai'](),
            method='post',
            body=app_params)

    def manage_existing(self, volume, existing_ref):
        """Manage an existing volume on the Datera backend

        The existing_ref must be either the current name or Datera UUID of
        an app_instance on the Datera backend in a colon separated list with
        the storage instance name and volume name.  This means only
        single storage instances and single volumes are supported for
        managing by cinder.

        Eg.

        existing_ref['source-name'] == app_inst_name:storage_inst_name:vol_name

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume
        """
        existing_ref = existing_ref['source-name']
        if existing_ref.count(":") != 2:
            raise exception.ManageExistingInvalidReference(
                _("existing_ref argument must be of this format:"
                  "app_inst_name:storage_inst_name:vol_name"))
        app_inst_name = existing_ref.split(":")[0]
        LOG.debug("Managing existing Datera volume %(volume)s.  "
                  "Changing name to %(existing)s",
                  existing=existing_ref, volume=_get_name(volume['id']))
        data = {'name': _get_name(volume['id'])}
        self._issue_api_request(URL_TEMPLATES['ai_inst']().format(
            app_inst_name), method='put', body=data)

    def manage_existing_get_size(self, volume, existing_ref):
        """Get the size of an unmanaged volume on the Datera backend

        The existing_ref must be either the current name or Datera UUID of
        an app_instance on the Datera backend in a colon separated list with
        the storage instance name and volume name.  This means only
        single storage instances and single volumes are supported for
        managing by cinder.

        Eg.

        existing_ref == app_inst_name:storage_inst_name:vol_name

        :param volume:       Cinder volume to manage
        :param existing_ref: Driver-specific information used to identify a
                             volume on the Datera backend
        """
        existing_ref = existing_ref['source-name']
        if existing_ref.count(":") != 2:
            raise exception.ManageExistingInvalidReference(
                _("existing_ref argument must be of this format:"
                  "app_inst_name:storage_inst_name:vol_name"))
        app_inst_name, si_name, vol_name = existing_ref.split(":")
        app_inst = self._issue_api_request(
            URL_TEMPLATES['ai_inst']().format(app_inst_name))
        return self._get_size(volume, app_inst, si_name, vol_name)

    def _get_size(self, volume, app_inst=None, si_name=None, vol_name=None):
        """Helper method for getting the size of a backend object

        If app_inst is provided, we'll just parse the dict to get
        the size instead of making a separate http request
        """
        policies = self._get_policies_for_resource(volume)
        si_name = si_name if si_name else policies['default_storage_name']
        vol_name = vol_name if vol_name else policies['default_volume_name']
        if not app_inst:
            vol_url = URL_TEMPLATES['ai_inst']().format(
                _get_name(volume['id']))
            app_inst = self._issue_api_request(vol_url)
        size = app_inst[
            'storage_instances'][si_name]['volumes'][vol_name]['size']
        return size

    def get_manageable_volumes(self, cinder_volumes, marker, limit, offset,
                               sort_keys, sort_dirs):
        """List volumes on the backend available for management by Cinder.

        Returns a list of dictionaries, each specifying a volume in the host,
        with the following keys:
        - reference (dictionary): The reference for a volume, which can be
          passed to "manage_existing".
        - size (int): The size of the volume according to the storage
          backend, rounded up to the nearest GB.
        - safe_to_manage (boolean): Whether or not this volume is safe to
          manage according to the storage backend. For example, is the volume
          in use or invalid for any reason.
        - reason_not_safe (string): If safe_to_manage is False, the reason why.
        - cinder_id (string): If already managed, provide the Cinder ID.
        - extra_info (string): Any extra information to return to the user

        :param cinder_volumes: A list of volumes in this host that Cinder
                               currently manages, used to determine if
                               a volume is manageable or not.
        :param marker:    The last item of the previous page; we return the
                          next results after this value (after sorting)
        :param limit:     Maximum number of items to return
        :param offset:    Number of items to skip after marker
        :param sort_keys: List of keys to sort results by (valid keys are
                          'identifier' and 'size')
        :param sort_dirs: List of directions to sort by, corresponding to
                          sort_keys (valid directions are 'asc' and 'desc')
        """
        LOG.debug("Listing manageable Datera volumes")
        app_instances = self._issue_api_request(URL_TEMPLATES['ai']()).values()

        results = []

        cinder_volume_ids = [vol['id'] for vol in cinder_volumes]

        for ai in app_instances:
            ai_name = ai['name']
            reference = None
            size = None
            safe_to_manage = False
            reason_not_safe = None
            cinder_id = None
            extra_info = None
            if re.match(UUID4_RE, ai_name):
                cinder_id = ai_name.lstrip(OS_PREFIX)
            if (not cinder_id and
                    ai_name.lstrip(OS_PREFIX) not in cinder_volume_ids):
                safe_to_manage = self._is_manageable(ai)
            if safe_to_manage:
                si = list(ai['storage_instances'].values())[0]
                si_name = si['name']
                vol = list(si['volumes'].values())[0]
                vol_name = vol['name']
                size = vol['size']
                reference = {"source-name": "{}:{}:{}".format(
                    ai_name, si_name, vol_name)}

            results.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info})

        page_results = volutils.paginate_entries_list(
            results, marker, limit, offset, sort_keys, sort_dirs)

        return page_results

    def _is_manageable(self, app_inst):
        if len(app_inst['storage_instances']) == 1:
            si = list(app_inst['storage_instances'].values())[0]
            if len(si['volumes']) == 1:
                return True
        return False

    def unmanage(self, volume):
        """Unmanage a currently managed volume in Cinder

        :param volume:       Cinder volume to unmanage
        """
        LOG.debug("Unmanaging Cinder volume %s.  Changing name to %s",
                  volume['id'], _get_unmanaged(volume['id']))
        data = {'name': _get_unmanaged(volume['id'])}
        self._issue_api_request(URL_TEMPLATES['ai_inst']().format(
            _get_name(volume['id'])), method='put', body=data)

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update first.
        The name is a bit misleading as
        the majority of the data here is cluster
        data.
        """
        if refresh or not self.cluster_stats:
            try:
                self._update_cluster_stats()
            except exception.DateraAPIException:
                LOG.error(_LE('Failed to get updated stats from Datera '
                              'cluster.'))
        return self.cluster_stats

    def _update_cluster_stats(self):
        LOG.debug("Updating cluster stats info.")

        results = self._issue_api_request('system')

        if 'uuid' not in results:
            LOG.error(_LE('Failed to get updated stats from Datera Cluster.'))

        backend_name = self.configuration.safe_get('volume_backend_name')
        stats = {
            'volume_backend_name': backend_name or 'Datera',
            'vendor_name': 'Datera',
            'driver_version': self.VERSION,
            'storage_protocol': 'iSCSI',
            'total_capacity_gb': int(results['total_capacity']) / units.Gi,
            'free_capacity_gb': int(results['available_capacity']) / units.Gi,
            'reserved_percentage': 0,
        }

        self.cluster_stats = stats

    def _login(self):
        """Use the san_login and san_password to set token."""
        body = {
            'name': self.username,
            'password': self.password
        }

        # Unset token now, otherwise potential expired token will be sent
        # along to be used for authorization when trying to login.

        try:
            LOG.debug('Getting Datera auth token.')
            results = self._issue_api_request('login', 'put', body=body,
                                              sensitive=True)
            self.datera_api_token = results['key']
        except exception.NotAuthorized:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Logging into the Datera cluster failed. Please '
                              'check your username and password set in the '
                              'cinder.conf and start the cinder-volume '
                              'service again.'))

    def _get_lunid(self):
        return 0

    def _init_vendor_properties(self):
        """Create a dictionary of vendor unique properties.

        This method creates a dictionary of vendor unique properties
        and returns both created dictionary and vendor name.
        Returned vendor name is used to check for name of vendor
        unique properties.

        - Vendor name shouldn't include colon(:) because of the separator
          and it is automatically replaced by underscore(_).
          ex. abc:d -> abc_d
        - Vendor prefix is equal to vendor name.
          ex. abcd
        - Vendor unique properties must start with vendor prefix + ':'.
          ex. abcd:maxIOPS

        Each backend driver needs to override this method to expose
        its own properties using _set_property() like this:

        self._set_property(
            properties,
            "vendorPrefix:specific_property",
            "Title of property",
            _("Description of property"),
            "type")

        : return dictionary of vendor unique properties
        : return vendor name

        prefix: DF --> Datera Fabric
        """

        properties = {}

        if self.configuration.get('datera_debug_replica_count_override'):
            replica_count = 1
        else:
            replica_count = 3
        self._set_property(
            properties,
            "DF:replica_count",
            "Datera Volume Replica Count",
            _("Specifies number of replicas for each volume. Can only be "
              "increased once volume is created"),
            "integer",
            minimum=1,
            default=replica_count)

        self._set_property(
            properties,
            "DF:acl_allow_all",
            "Datera ACL Allow All",
            _("True to set acl 'allow_all' on volumes created.  Cannot be "
              "changed on volume once set"),
            "boolean",
            default=False)

        self._set_property(
            properties,
            "DF:ip_pool",
            "Datera IP Pool",
            _("Specifies IP pool to use for volume"),
            "string",
            default="default")

        # ###### QoS Settings ###### #
        self._set_property(
            properties,
            "DF:read_bandwidth_max",
            "Datera QoS Max Bandwidth Read",
            _("Max read bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:default_storage_name",
            "Datera Default Storage Instance Name",
            _("The name to use for storage instances created"),
            "string",
            default="storage-1")

        self._set_property(
            properties,
            "DF:default_volume_name",
            "Datera Default Volume Name",
            _("The name to use for volumes created"),
            "string",
            default="volume-1")

        self._set_property(
            properties,
            "DF:write_bandwidth_max",
            "Datera QoS Max Bandwidth Write",
            _("Max write bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:total_bandwidth_max",
            "Datera QoS Max Bandwidth Total",
            _("Max total bandwidth setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:read_iops_max",
            "Datera QoS Max iops Read",
            _("Max read iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:write_iops_max",
            "Datera QoS Max IOPS Write",
            _("Max write iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)

        self._set_property(
            properties,
            "DF:total_iops_max",
            "Datera QoS Max IOPS Total",
            _("Max total iops setting for volume qos, "
              "use 0 for unlimited"),
            "integer",
            minimum=0,
            default=0)
        # ###### End QoS Settings ###### #

        return properties, 'DF'

    def _get_policies_for_resource(self, resource):
        """Get extra_specs and qos_specs of a volume_type.

        This fetches the scoped keys from the volume type. Anything set from
         qos_specs will override key/values set from extra_specs.
        """
        type_id = resource.get('volume_type_id', None)
        # Handle case of volume with no type.  We still want the
        # specified defaults from above
        if type_id:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            specs = volume_type.get('extra_specs')
        else:
            volume_type = None
            specs = {}

        # Set defaults:
        policies = {k.lstrip('DF:'): str(v['default']) for (k, v)
                    in self._init_vendor_properties()[0].items()}

        if volume_type:
            # Populate updated value
            for key, value in specs.items():
                if ':' in key:
                    fields = key.split(':')
                    key = fields[1]
                    policies[key] = value

            qos_specs_id = volume_type.get('qos_specs_id')
            if qos_specs_id is not None:
                qos_kvs = qos_specs.get_qos_specs(ctxt, qos_specs_id)['specs']
                if qos_kvs:
                    policies.update(qos_kvs)
        # Cast everything except booleans int that can be cast
        for k, v in policies.items():
            # Handle String Boolean case
            if v == 'True' or v == 'False':
                policies[k] = policies[k] == 'True'
                continue
            # Int cast
            try:
                policies[k] = int(v)
            except ValueError:
                pass
        return policies

    def _si_poll(self, volume, policies):
        # Initial 4 second sleep required for some Datera versions
        eventlet.sleep(DEFAULT_SI_SLEEP)
        TIMEOUT = 10
        retry = 0
        check_url = URL_TEMPLATES['si_inst'](
            policies['default_storage_name']).format(_get_name(volume['id']))
        poll = True
        while poll and not retry >= TIMEOUT:
            retry += 1
            si = self._issue_api_request(check_url)
            if si['op_state'] == 'available':
                poll = False
            else:
                eventlet.sleep(1)
        if retry >= TIMEOUT:
            raise exception.VolumeDriverException(
                message=_('Resource not ready.'))

    def _update_qos(self, resource, policies):
        url = URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/performance_policy'
        url = url.format(_get_name(resource['id']))
        type_id = resource.get('volume_type_id', None)
        if type_id is not None:
            # Filter for just QOS policies in result. All of their keys
            # should end with "max"
            fpolicies = {k: int(v) for k, v in
                         policies.items() if k.endswith("max")}
            # Filter all 0 values from being passed
            fpolicies = dict(filter(lambda _v: _v[1] > 0, fpolicies.items()))
            if fpolicies:
                self._issue_api_request(url, 'post', body=fpolicies)

    def _get_ip_pool_for_string_ip(self, ip):
        """Takes a string ipaddress and return the ip_pool API object dict """
        pool = 'default'
        ip_obj = ipaddress.ip_address(six.text_type(ip))
        ip_pools = self._issue_api_request("access_network_ip_pools")
        for ip_pool, ipdata in ip_pools.items():
            for access, adata in ipdata['network_paths'].items():
                if not adata.get('start_ip'):
                    continue
                pool_if = ipaddress.ip_interface(
                    "/".join((adata['start_ip'], str(adata['netmask']))))
                if ip_obj in pool_if.network:
                    pool = ip_pool
        return self._issue_api_request(
            "access_network_ip_pools/{}".format(pool))['path']

    def _request(self, connection_string, method, payload, header, cert_data):
        LOG.debug("Endpoint for Datera API call: %s", connection_string)
        try:
            response = getattr(requests, method)(connection_string,
                                                 data=payload, headers=header,
                                                 verify=False, cert=cert_data)
            return response
        except requests.exceptions.RequestException as ex:
            msg = _(
                'Failed to make a request to Datera cluster endpoint due '
                'to the following reason: %s') % six.text_type(
                ex.message)
            LOG.error(msg)
            raise exception.DateraAPIException(msg)

    def _raise_response(self, response):
        msg = _('Request to Datera cluster returned bad status:'
                ' %(status)s | %(reason)s') % {
                    'status': response.status_code,
                    'reason': response.reason}
        LOG.error(msg)
        raise exception.DateraAPIException(msg)

    def _handle_bad_status(self,
                           response,
                           connection_string,
                           method,
                           payload,
                           header,
                           cert_data,
                           sensitive=False,
                           conflict_ok=False):
        if not sensitive:
            LOG.debug(("Datera Response URL: %s\n"
                       "Datera Response Payload: %s\n"
                       "Response Object: %s\n"),
                      response.url,
                      payload,
                      vars(response))
        if response.status_code == 404:
            raise exception.NotFound(response.json()['message'])
        elif response.status_code in [403, 401]:
            raise exception.NotAuthorized()
        elif response.status_code == 409 and conflict_ok:
            # Don't raise, because we're expecting a conflict
            pass
        elif response.status_code == 503:
            current_retry = 0
            while current_retry <= self.retry_attempts:
                LOG.debug("Datera 503 response, trying request again")
                eventlet.sleep(self.interval)
                resp = self._request(connection_string,
                                     method,
                                     payload,
                                     header,
                                     cert_data)
                if resp.ok:
                    return response.json()
                elif resp.status_code != 503:
                    self._raise_response(resp)
        else:
            self._raise_response(response)

    @_authenticated
    def _issue_api_request(self, resource_url, method='get', body=None,
                           sensitive=False, conflict_ok=False):
        """All API requests to Datera cluster go through this method.

        :param resource_url: the url of the resource
        :param method: the request verb
        :param body: a dict with options for the action_type
        :returns: a dict of the response from the Datera cluster
        """
        host = self.configuration.san_ip
        port = self.configuration.datera_api_port
        api_token = self.datera_api_token
        api_version = self.configuration.datera_api_version

        payload = json.dumps(body, ensure_ascii=False)
        payload.encode('utf-8')

        header = {'Content-Type': 'application/json; charset=utf-8',
                  'Datera-Driver': 'OpenStack-Cinder-{}'.format(self.VERSION)}

        protocol = 'http'
        if self.configuration.driver_use_ssl:
            protocol = 'https'

        if api_token:
            header['Auth-Token'] = api_token

        client_cert = self.configuration.driver_client_cert
        client_cert_key = self.configuration.driver_client_cert_key
        cert_data = None

        if client_cert:
            protocol = 'https'
            cert_data = (client_cert, client_cert_key)

        connection_string = '%s://%s:%s/v%s/%s' % (protocol, host, port,
                                                   api_version, resource_url)

        response = self._request(connection_string,
                                 method,
                                 payload,
                                 header,
                                 cert_data)

        data = response.json()

        if not response.ok:
            self._handle_bad_status(response,
                                    connection_string,
                                    method,
                                    payload,
                                    header,
                                    cert_data,
                                    conflict_ok=conflict_ok)

        return data
