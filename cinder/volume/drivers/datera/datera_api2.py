# Copyright 2017 Datera
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

import re
import uuid

import eventlet
import ipaddress
import six

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import units

from cinder import exception
from cinder.i18n import _
from cinder.volume import utils as volutils

import cinder.volume.drivers.datera.datera_common as datc

LOG = logging.getLogger(__name__)


class DateraApi(object):

    # =================
    # = Create Volume =
    # =================

    def _create_volume_2(self, volume):
        # Generate App Instance, Storage Instance and Volume
        # Volume ID will be used as the App Instance Name
        # Storage Instance and Volumes will have standard names
        policies = self._get_policies_for_resource(volume)
        num_replicas = int(policies['replica_count'])
        storage_name = policies['default_storage_name']
        volume_name = policies['default_volume_name']
        template = policies['template']

        if template:
            app_params = (
                {
                    'create_mode': "openstack",
                    # 'uuid': str(volume['id']),
                    'name': datc._get_name(volume['id']),
                    'app_template': '/app_templates/{}'.format(template)
                })
        else:

            app_params = (
                {
                    'create_mode': "openstack",
                    'uuid': str(volume['id']),
                    'name': datc._get_name(volume['id']),
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
        self._issue_api_request(
            datc.URL_TEMPLATES['ai'](),
            'post',
            body=app_params,
            api_version='2')
        self._update_qos(volume, policies)

    # =================
    # = Extend Volume =
    # =================

    def _extend_volume_2(self, volume, new_size):
        # Current product limitation:
        # If app_instance is bound to template resizing is not possible
        # Once policies are implemented in the product this can go away
        policies = self._get_policies_for_resource(volume)
        template = policies['template']
        if template:
            LOG.warning("Volume size not extended due to template binding:"
                        " volume: %(volume)s, template: %(template)s",
                        volume=volume, template=template)
            return

        # Offline App Instance, if necessary
        reonline = False
        app_inst = self._issue_api_request(
            datc.URL_TEMPLATES['ai_inst']().format(
                datc._get_name(volume['id'])),
            api_version='2')
        if app_inst['admin_state'] == 'online':
            reonline = True
            self._detach_volume_2(None, volume)
        # Change Volume Size
        app_inst = datc._get_name(volume['id'])
        data = {
            'size': new_size
        }
        store_name, vol_name = self._scrape_template(policies)
        self._issue_api_request(
            datc.URL_TEMPLATES['vol_inst'](
                store_name, vol_name).format(app_inst),
            method='put',
            body=data,
            api_version='2')
        # Online Volume, if it was online before
        if reonline:
            self._create_export_2(None, volume, None)

    # =================
    # = Cloned Volume =
    # =================

    def _create_cloned_volume_2(self, volume, src_vref):
        policies = self._get_policies_for_resource(volume)

        store_name, vol_name = self._scrape_template(policies)

        src = "/" + datc.URL_TEMPLATES['vol_inst'](
            store_name, vol_name).format(datc._get_name(src_vref['id']))
        data = {
            'create_mode': 'openstack',
            'name': datc._get_name(volume['id']),
            'uuid': str(volume['id']),
            'clone_src': src,
        }
        self._issue_api_request(
            datc.URL_TEMPLATES['ai'](), 'post', body=data, api_version='2')

        if volume['size'] > src_vref['size']:
            self._extend_volume_2(volume, volume['size'])

    # =================
    # = Delete Volume =
    # =================

    def _delete_volume_2(self, volume):
        self.detach_volume(None, volume)
        app_inst = datc._get_name(volume['id'])
        try:
            self._issue_api_request(datc.URL_TEMPLATES['ai_inst']().format(
                app_inst),
                method='delete',
                api_version='2')
        except exception.NotFound:
            LOG.info("Tried to delete volume %s, but it was not found in the "
                     "Datera cluster. Continuing with delete.",
                     datc._get_name(volume['id']))

    # =================
    # = Ensure Export =
    # =================

    def _ensure_export_2(self, context, volume, connector):
        return self._create_export_2(context, volume, connector)

    # =========================
    # = Initialize Connection =
    # =========================

    def _initialize_connection_2(self, volume, connector):
        # Now online the app_instance (which will online all storage_instances)
        multipath = connector.get('multipath', False)
        url = datc.URL_TEMPLATES['ai_inst']().format(
            datc._get_name(volume['id']))
        data = {
            'admin_state': 'online'
        }
        app_inst = self._issue_api_request(
            url, method='put', body=data, api_version='2')
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

    # =================
    # = Create Export =
    # =================

    def _create_export_2(self, context, volume, connector):
        # Online volume in case it hasn't been already
        url = datc.URL_TEMPLATES['ai_inst']().format(
            datc._get_name(volume['id']))
        data = {
            'admin_state': 'online'
        }
        self._issue_api_request(url, method='put', body=data, api_version='2')
        # Check if we've already setup everything for this volume
        url = (datc.URL_TEMPLATES['si']().format(datc._get_name(volume['id'])))
        storage_instances = self._issue_api_request(url, api_version='2')
        # Handle adding initiator to product if necessary
        # Then add initiator to ACL
        policies = self._get_policies_for_resource(volume)

        store_name, _ = self._scrape_template(policies)

        if (connector and
                connector.get('initiator') and
                not policies['acl_allow_all']):
            initiator_name = "OpenStack_{}_{}".format(
                self.driver_prefix, str(uuid.uuid4())[:4])
            initiator_group = datc.INITIATOR_GROUP_PREFIX + volume['id']
            found = False
            initiator = connector['initiator']
            current_initiators = self._issue_api_request(
                'initiators', api_version='2')
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
                                        conflict_ok=True,
                                        api_version='2')
            # Create initiator group with initiator in it
            initiator_path = "/initiators/{}".format(initiator)
            initiator_group_path = "/initiator_groups/{}".format(
                initiator_group)
            ig_data = {'name': initiator_group, 'members': [initiator_path]}
            self._issue_api_request("initiator_groups",
                                    method="post",
                                    body=ig_data,
                                    conflict_ok=True,
                                    api_version='2')
            # Create ACL with initiator group as reference for each
            # storage_instance in app_instance
            # TODO(_alastor_): We need to avoid changing the ACLs if the
            # template already specifies an ACL policy.
            for si_name in storage_instances.keys():
                acl_url = (datc.URL_TEMPLATES['si']() +
                           "/{}/acl_policy").format(
                    datc._get_name(volume['id']), si_name)
                existing_acl = self._issue_api_request(acl_url,
                                                       method="get",
                                                       api_version='2')
                data = {}
                data['initiators'] = existing_acl['initiators']
                data['initiator_groups'] = existing_acl['initiator_groups']
                data['initiator_groups'].append(initiator_group_path)
                self._issue_api_request(acl_url,
                                        method="put",
                                        body=data,
                                        api_version='2')

        if connector and connector.get('ip'):
            try:
                # Case where volume_type has non default IP Pool info
                if policies['ip_pool'] != 'default':
                    initiator_ip_pool_path = self._issue_api_request(
                        "access_network_ip_pools/{}".format(
                            policies['ip_pool']), api_version='2')['path']
                # Fallback to trying reasonable IP based guess
                else:
                    initiator_ip_pool_path = self._get_ip_pool_for_string_ip(
                        connector['ip'])

                ip_pool_url = datc.URL_TEMPLATES['si_inst'](
                    store_name).format(datc._get_name(volume['id']))
                ip_pool_data = {'ip_pool': initiator_ip_pool_path}
                self._issue_api_request(ip_pool_url,
                                        method="put",
                                        body=ip_pool_data,
                                        api_version='2')
            except exception.DateraAPIException:
                # Datera product 1.0 support
                pass

        # Check to ensure we're ready for go-time
        self._si_poll(volume, policies)

    # =================
    # = Detach Volume =
    # =================

    def _detach_volume_2(self, context, volume, attachment=None):
        url = datc.URL_TEMPLATES['ai_inst']().format(
            datc._get_name(volume['id']))
        data = {
            'admin_state': 'offline',
            'force': True
        }
        try:
            self._issue_api_request(url, method='put', body=data,
                                    api_version='2')
        except exception.NotFound:
            msg = ("Tried to detach volume %s, but it was not found in the "
                   "Datera cluster. Continuing with detach.")
            LOG.info(msg, volume['id'])
        # TODO(_alastor_): Make acl cleaning multi-attach aware
        self._clean_acl_2(volume)

    def _check_for_acl_2(self, initiator_path):
        """Returns True if an acl is found for initiator_path """
        # TODO(_alastor_) when we get a /initiators/:initiator/acl_policies
        # endpoint use that instead of this monstrosity
        initiator_groups = self._issue_api_request("initiator_groups",
                                                   api_version='2')
        for ig, igdata in initiator_groups.items():
            if initiator_path in igdata['members']:
                LOG.debug("Found initiator_group: %s for initiator: %s",
                          ig, initiator_path)
                return True
        LOG.debug("No initiator_group found for initiator: %s", initiator_path)
        return False

    def _clean_acl_2(self, volume):
        policies = self._get_policies_for_resource(volume)

        store_name, _ = self._scrape_template(policies)

        acl_url = (datc.URL_TEMPLATES["si_inst"](
            store_name) + "/acl_policy").format(datc._get_name(volume['id']))
        try:
            initiator_group = self._issue_api_request(
                acl_url, api_version='2')['initiator_groups'][0]
            initiator_iqn_path = self._issue_api_request(
                initiator_group.lstrip("/"))["members"][0]
            # Clear out ACL and delete initiator group
            self._issue_api_request(acl_url,
                                    method="put",
                                    body={'initiator_groups': []},
                                    api_version='2')
            self._issue_api_request(initiator_group.lstrip("/"),
                                    method="delete",
                                    api_version='2')
            if not self._check_for_acl_2(initiator_iqn_path):
                self._issue_api_request(initiator_iqn_path.lstrip("/"),
                                        method="delete",
                                        api_version='2')
        except (IndexError, exception.NotFound):
            LOG.debug("Did not find any initiator groups for volume: %s",
                      volume)

    # ===================
    # = Create Snapshot =
    # ===================

    def _create_snapshot_2(self, snapshot):
        policies = self._get_policies_for_resource(snapshot)

        store_name, vol_name = self._scrape_template(policies)

        url_template = datc.URL_TEMPLATES['vol_inst'](
            store_name, vol_name) + '/snapshots'
        url = url_template.format(datc._get_name(snapshot['volume_id']))

        snap_params = {
            'uuid': snapshot['id'],
        }
        snap = self._issue_api_request(url, method='post', body=snap_params,
                                       api_version='2')
        snapu = "/".join((url, snap['timestamp']))
        self._snap_poll(snapu)

    # ===================
    # = Delete Snapshot =
    # ===================

    def _delete_snapshot_2(self, snapshot):
        policies = self._get_policies_for_resource(snapshot)

        store_name, vol_name = self._scrape_template(policies)

        snap_temp = datc.URL_TEMPLATES['vol_inst'](
            store_name, vol_name) + '/snapshots'
        snapu = snap_temp.format(datc._get_name(snapshot['volume_id']))
        snapshots = self._issue_api_request(snapu, method='get',
                                            api_version='2')

        try:
            for ts, snap in snapshots.items():
                if snap['uuid'] == snapshot['id']:
                    url_template = snapu + '/{}'
                    url = url_template.format(ts)
                    self._issue_api_request(url, method='delete',
                                            api_version='2')
                    break
            else:
                raise exception.NotFound
        except exception.NotFound:
            msg = ("Tried to delete snapshot %s, but was not found in "
                   "Datera cluster. Continuing with delete.")
            LOG.info(msg, datc._get_name(snapshot['id']))

    # ========================
    # = Volume From Snapshot =
    # ========================

    def _create_volume_from_snapshot_2(self, volume, snapshot):
        policies = self._get_policies_for_resource(snapshot)

        store_name, vol_name = self._scrape_template(policies)

        snap_temp = datc.URL_TEMPLATES['vol_inst'](
            store_name, vol_name) + '/snapshots'
        snapu = snap_temp.format(datc._get_name(snapshot['volume_id']))
        snapshots = self._issue_api_request(snapu, method='get',
                                            api_version='2')
        for ts, snap in snapshots.items():
            if snap['uuid'] == snapshot['id']:
                found_ts = ts
                break
        else:
            raise exception.NotFound

        snap_url = (snap_temp + '/{}').format(
            datc._get_name(snapshot['volume_id']), found_ts)

        self._snap_poll(snap_url)

        src = "/" + snap_url
        app_params = (
            {
                'create_mode': 'openstack',
                'uuid': str(volume['id']),
                'name': datc._get_name(volume['id']),
                'clone_src': src,
            })
        self._issue_api_request(
            datc.URL_TEMPLATES['ai'](),
            method='post',
            body=app_params,
            api_version='2')

        if (volume['size'] > snapshot['volume_size']):
            self._extend_volume_2(volume, volume['size'])

    # ==========
    # = Manage =
    # ==========

    def _manage_existing_2(self, volume, existing_ref):
        existing_ref = existing_ref['source-name']
        if existing_ref.count(":") != 2:
            raise exception.ManageExistingInvalidReference(
                _("existing_ref argument must be of this format:"
                  "app_inst_name:storage_inst_name:vol_name"))
        app_inst_name = existing_ref.split(":")[0]
        LOG.debug("Managing existing Datera volume %s.  "
                  "Changing name to %s",
                  datc._get_name(volume['id']),
                  existing_ref)
        data = {'name': datc._get_name(volume['id'])}
        self._issue_api_request(datc.URL_TEMPLATES['ai_inst']().format(
            app_inst_name), method='put', body=data, api_version='2')

    # ===================
    # = Manage Get Size =
    # ===================

    def _manage_existing_get_size_2(self, volume, existing_ref):
        existing_ref = existing_ref['source-name']
        if existing_ref.count(":") != 2:
            raise exception.ManageExistingInvalidReference(
                _("existing_ref argument must be of this format:"
                  "app_inst_name:storage_inst_name:vol_name"))
        app_inst_name, si_name, vol_name = existing_ref.split(":")
        app_inst = self._issue_api_request(
            datc.URL_TEMPLATES['ai_inst']().format(app_inst_name),
            api_version='2')
        return self._get_size_2(volume, app_inst, si_name, vol_name)

    def _get_size_2(self, volume, app_inst=None, si_name=None, vol_name=None):
        """Helper method for getting the size of a backend object

        If app_inst is provided, we'll just parse the dict to get
        the size instead of making a separate http request
        """
        policies = self._get_policies_for_resource(volume)
        si_name = si_name if si_name else policies['default_storage_name']
        vol_name = vol_name if vol_name else policies['default_volume_name']
        if not app_inst:
            vol_url = datc.URL_TEMPLATES['ai_inst']().format(
                datc._get_name(volume['id']))
            app_inst = self._issue_api_request(vol_url)
        size = app_inst[
            'storage_instances'][si_name]['volumes'][vol_name]['size']
        return size

    # =========================
    # = Get Manageable Volume =
    # =========================

    def _get_manageable_volumes_2(self, cinder_volumes, marker, limit, offset,
                                  sort_keys, sort_dirs):
        LOG.debug("Listing manageable Datera volumes")
        app_instances = self._issue_api_request(
            datc.URL_TEMPLATES['ai'](), api_version='2').values()

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
            if re.match(datc.UUID4_RE, ai_name):
                cinder_id = ai_name.lstrip(datc.OS_PREFIX)
            if (not cinder_id and
                    ai_name.lstrip(datc.OS_PREFIX) not in cinder_volume_ids):
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

    # ============
    # = Unmanage =
    # ============

    def _unmanage_2(self, volume):
        LOG.debug("Unmanaging Cinder volume %s.  Changing name to %s",
                  volume['id'], datc._get_unmanaged(volume['id']))
        data = {'name': datc._get_unmanaged(volume['id'])}
        self._issue_api_request(datc.URL_TEMPLATES['ai_inst']().format(
            datc._get_name(volume['id'])),
            method='put',
            body=data,
            api_version='2')

    # ================
    # = Volume Stats =
    # ================

    def _get_volume_stats_2(self, refresh=False):
        if refresh or not self.cluster_stats:
            try:
                LOG.debug("Updating cluster stats info.")

                results = self._issue_api_request('system', api_version='2')

                if 'uuid' not in results:
                    LOG.error(
                        'Failed to get updated stats from Datera Cluster.')

                backend_name = self.configuration.safe_get(
                    'volume_backend_name')
                stats = {
                    'volume_backend_name': backend_name or 'Datera',
                    'vendor_name': 'Datera',
                    'driver_version': self.VERSION,
                    'storage_protocol': 'iSCSI',
                    'total_capacity_gb': (
                        int(results['total_capacity']) / units.Gi),
                    'free_capacity_gb': (
                        int(results['available_capacity']) / units.Gi),
                    'reserved_percentage': 0,
                }

                self.cluster_stats = stats
            except exception.DateraAPIException:
                LOG.error('Failed to get updated stats from Datera cluster.')
        return self.cluster_stats

    def _is_manageable(self, app_inst):
        if len(app_inst['storage_instances']) == 1:
            si = list(app_inst['storage_instances'].values())[0]
            if len(si['volumes']) == 1:
                return True
        return False

    # =========
    # = Login =
    # =========

    def _login_2(self):
        """Use the san_login and san_password to set token."""
        body = {
            'name': self.username,
            'password': self.password
        }

        # Unset token now, otherwise potential expired token will be sent
        # along to be used for authorization when trying to login.
        self.datera_api_token = None

        try:
            LOG.debug('Getting Datera auth token.')
            results = self._issue_api_request('login', 'put', body=body,
                                              sensitive=True, api_version='2')
            self.datera_api_token = results['key']
        except exception.NotAuthorized:
            with excutils.save_and_reraise_exception():
                LOG.error('Logging into the Datera cluster failed. Please '
                          'check your username and password set in the '
                          'cinder.conf and start the cinder-volume '
                          'service again.')

    # ===========
    # = Polling =
    # ===========

    def _snap_poll(self, url):
        eventlet.sleep(datc.DEFAULT_SNAP_SLEEP)
        TIMEOUT = 10
        retry = 0
        poll = True
        while poll and not retry >= TIMEOUT:
            retry += 1
            snap = self._issue_api_request(url, api_version='2')
            if snap['op_state'] == 'available':
                poll = False
            else:
                eventlet.sleep(1)
        if retry >= TIMEOUT:
            raise exception.VolumeDriverException(
                message=_('Snapshot not ready.'))

    def _si_poll(self, volume, policies):
        # Initial 4 second sleep required for some Datera versions
        eventlet.sleep(datc.DEFAULT_SI_SLEEP_API_2)
        TIMEOUT = 10
        retry = 0
        check_url = datc.URL_TEMPLATES['si_inst'](
            policies['default_storage_name']).format(
                datc._get_name(volume['id']))
        poll = True
        while poll and not retry >= TIMEOUT:
            retry += 1
            si = self._issue_api_request(check_url, api_version='2')
            if si['op_state'] == 'available':
                poll = False
            else:
                eventlet.sleep(1)
        if retry >= TIMEOUT:
            raise exception.VolumeDriverException(
                message=_('Resource not ready.'))

    # ============
    # = IP Pools =
    # ============

    def _get_ip_pool_for_string_ip(self, ip):
        """Takes a string ipaddress and return the ip_pool API object dict """
        pool = 'default'
        ip_obj = ipaddress.ip_address(six.text_type(ip))
        ip_pools = self._issue_api_request('access_network_ip_pools',
                                           api_version='2')
        for ip_pool, ipdata in ip_pools.items():
            for access, adata in ipdata['network_paths'].items():
                if not adata.get('start_ip'):
                    continue
                pool_if = ipaddress.ip_interface(
                    "/".join((adata['start_ip'], str(adata['netmask']))))
                if ip_obj in pool_if.network:
                    pool = ip_pool
        return self._issue_api_request(
            "access_network_ip_pools/{}".format(pool), api_version='2')['path']

    # =============
    # = Templates =
    # =============

    def _scrape_template(self, policies):
        sname = policies['default_storage_name']
        vname = policies['default_volume_name']

        template = policies['template']
        if template:
            result = self._issue_api_request(
                datc.URL_TEMPLATES['at']().format(template), api_version='2')
            sname, st = list(result['storage_templates'].items())[0]
            vname = list(st['volume_templates'].keys())[0]
        return sname, vname

    # =======
    # = QoS =
    # =======

    def _update_qos(self, resource, policies):
        url = datc.URL_TEMPLATES['vol_inst'](
            policies['default_storage_name'],
            policies['default_volume_name']) + '/performance_policy'
        url = url.format(datc._get_name(resource['id']))
        type_id = resource.get('volume_type_id', None)
        if type_id is not None:
            # Filter for just QOS policies in result. All of their keys
            # should end with "max"
            fpolicies = {k: int(v) for k, v in
                         policies.items() if k.endswith("max")}
            # Filter all 0 values from being passed
            fpolicies = dict(filter(lambda _v: _v[1] > 0, fpolicies.items()))
            if fpolicies:
                self._issue_api_request(url, 'post', body=fpolicies,
                                        api_version='2')
