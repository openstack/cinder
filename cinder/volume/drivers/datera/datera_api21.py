# Copyright 2020 Datera
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

import contextlib
import ipaddress
import math
import random
import time
import uuid

import eventlet
from os_brick import exception as brick_exception
from oslo_log import log as logging
from oslo_serialization import jsonutils as json
from oslo_utils import importutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder.image import image_utils
import cinder.volume.drivers.datera.datera_common as datc
from cinder.volume import volume_types
from cinder.volume import volume_utils as volutils

LOG = logging.getLogger(__name__)

dexceptions = importutils.try_import('dfs_sdk.exceptions')

API_VERSION = "2.1"


# The DateraAPI classes (2.1, 2.2) are enhanced by datera_common's lookup()
# decorator which generates members run-time. Therefore on the class we disable
# pylint's no-member check pylint: disable=no-member
class DateraApi(object):

    # =================
    # = Create Volume =
    # =================

    def _create_volume_2_1(self, volume):
        policies = self._get_policies_for_resource(volume)
        num_replicas = int(policies['replica_count'])
        storage_name = 'storage-1'
        volume_name = 'volume-1'
        template = policies['template']
        placement = policies['placement_mode']
        ip_pool = policies['ip_pool']

        name = datc.get_name(volume)

        if template:
            app_params = (
                {
                    'create_mode': 'openstack',
                    # 'uuid': str(volume['id']),
                    'name': name,
                    'app_template': {'path': '/app_templates/{}'.format(
                        template)}
                })
        else:

            app_params = (
                {
                    'create_mode': 'openstack',
                    'uuid': str(volume['id']),
                    'name': name,
                    'access_control_mode': 'deny_all',
                    'storage_instances': [
                        {
                            'name': storage_name,
                            'ip_pool': {'path': ('/access_network_ip_pools/'
                                                 '{}'.format(ip_pool))},
                            'volumes': [
                                {
                                    'name': volume_name,
                                    'size': volume['size'],
                                    'placement_mode': placement,
                                    'replica_count': num_replicas,
                                    'snapshot_policies': [
                                    ]
                                }
                            ]
                        }
                    ]
                })

        tenant = self.create_tenant(volume['project_id'])
        self.api.app_instances.create(tenant=tenant, **app_params)
        self._update_qos_2_1(volume, policies)
        self._add_vol_meta_2_1(volume)

    # =================
    # = Extend Volume =
    # =================

    def _extend_volume_2_1(self, volume, new_size):
        if volume['size'] >= new_size:
            LOG.warning("Volume size not extended due to original size being "
                        "greater or equal to new size.  Originial: "
                        "%(original)s, New: %(new)s", {
                            'original': volume['size'],
                            'new': new_size})
            return
        policies = self._get_policies_for_resource(volume)
        template = policies['template']
        if template:
            LOG.warning("Volume size not extended due to template binding."
                        " volume: %(volume)s, template: %(template)s",
                        {'volume': volume, 'template': template})
            return

        with self._offline_flip_2_1(volume):
            # Change Volume Size
            tenant = self.get_tenant(volume['project_id'])
            dvol = self.cvol_to_dvol(volume, tenant=tenant)
            dvol.set(tenant=tenant, size=new_size)

    # =================
    # = Cloned Volume =
    # =================

    def _create_cloned_volume_2_1(self, volume, src_vref):
        tenant = self.get_tenant(volume['project_id'])
        sdvol = self.cvol_to_dvol(src_vref, tenant=tenant)
        src = sdvol.path
        data = {
            'create_mode': 'openstack',
            'name': datc.get_name(volume),
            'uuid': str(volume['id']),
            'clone_volume_src': {'path': src},
        }
        tenant = self.get_tenant(volume['project_id'])
        self.api.app_instances.create(tenant=tenant, **data)

        if volume['size'] > src_vref['size']:
            self._extend_volume_2_1(volume, volume['size'])
        self._add_vol_meta_2_1(volume)

    # =================
    # = Delete Volume =
    # =================

    def _delete_volume_2_1(self, volume):
        try:
            tenant = self.get_tenant(volume['project_id'])
            ai = self.cvol_to_ai(volume, tenant=tenant)
            si = ai.storage_instances.list(tenant=tenant)[0]

            # Clear out ACL
            acl = si.acl_policy.get(tenant=tenant)
            acl.set(tenant=tenant, initiators=[])

            # Bring volume offline
            data = {
                'admin_state': 'offline',
                'force': True
            }
            ai.set(tenant=tenant, **data)

            ai.delete(tenant=tenant, force=True)
        except exception.NotFound:
            msg = ("Tried to delete volume %s, but it was not found in the "
                   "Datera cluster. Continuing with delete.")
            LOG.info(msg, datc.get_name(volume))

    # =================
    # = Ensure Export =
    # =================

    def _ensure_export_2_1(self, context, volume, connector=None):
        pass

    # =========================
    # = Initialize Connection =
    # =========================

    def _initialize_connection_2_1(self, volume, connector):
        # Now online the app_instance (which will online all storage_instances)
        multipath = connector.get('multipath', False)
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(volume, tenant=tenant)
        data = {
            'admin_state': 'online'
        }
        ai.set(tenant=tenant, **data)
        si = ai.storage_instances.list(tenant=tenant)[0]

        # randomize portal chosen
        choice = 0
        policies = self._get_policies_for_resource(volume)
        if policies["round_robin"]:
            choice = random.randint(0, 1)
        portal = si.access['ips'][choice] + ':3260'
        iqn = si.access['iqn']
        if multipath:
            portals = [p + ':3260' for p in si.access['ips']]
            iqns = [iqn for _ in si.access['ips']]
            lunids = [self._get_lunid() for _ in si.access['ips']]

            result = {
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
            result = {
                'driver_volume_type': 'iscsi',
                'data': {
                    'target_discovered': False,
                    'target_iqn': iqn,
                    'target_portal': portal,
                    'target_lun': self._get_lunid(),
                    'volume_id': volume['id'],
                    'discard': False}}

        if self.use_chap_auth:
            result['data'].update(
                auth_method="CHAP",
                auth_username=self.chap_username,
                auth_password=self.chap_password)

        return result

    # =================
    # = Create Export =
    # =================

    def _create_export_2_1(self, context, volume, connector):
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(volume, tenant=tenant)
        data = {
            'admin_state': 'offline',
            'force': True
        }
        ai.set(tenant=tenant, **data)
        si = ai.storage_instances.list(tenant=tenant)[0]
        policies = self._get_policies_for_resource(volume)
        if connector and connector.get('ip'):
            # Case where volume_type has non default IP Pool info
            if policies['ip_pool'] != 'default':
                initiator_ip_pool_path = self.api.access_network_ip_pools.get(
                    policies['ip_pool']).path
            # Fallback to trying reasonable IP based guess
            else:
                initiator_ip_pool_path = self._get_ip_pool_for_string_ip_2_1(
                    connector['ip'], tenant)

            ip_pool_data = {'ip_pool': {'path': initiator_ip_pool_path}}
            si.set(tenant=tenant, **ip_pool_data)
        data = {
            'admin_state': 'online'
        }
        ai.set(tenant=tenant, **data)
        # Check if we've already setup everything for this volume
        storage_instances = ai.storage_instances.list(tenant=tenant)
        # Handle adding initiator to product if necessary
        # Then add initiator to ACL
        if connector and connector.get('initiator'):
            initiator_name = "OpenStack-{}".format(str(uuid.uuid4())[:8])
            initiator = connector['initiator']
            dinit = None
            data = {'id': initiator, 'name': initiator_name}
            # Try and create the initiator
            # If we get a conflict, ignore it
            try:
                dinit = self.api.initiators.create(tenant=tenant, **data)
            except dexceptions.ApiConflictError:
                dinit = self.api.initiators.get(initiator, tenant=tenant)
            initiator_path = dinit['path']
            # Create ACL with initiator group as reference for each
            # storage_instance in app_instance
            # TODO(_alastor_): We need to avoid changing the ACLs if the
            # template already specifies an ACL policy.
            for si in storage_instances:
                existing_acl = si.acl_policy.get(tenant=tenant)
                data = {}
                # Grabbing only the 'path' key from each existing initiator
                # within the existing acl. eacli --> existing acl initiator
                eacli = []
                for acl in existing_acl['initiators']:
                    nacl = {}
                    nacl['path'] = acl['path']
                    eacli.append(nacl)
                data['initiators'] = eacli
                data['initiators'].append({"path": initiator_path})
                # Grabbing only the 'path' key from each existing initiator
                # group within the existing acl. eaclig --> existing
                # acl initiator group
                eaclig = []
                for acl in existing_acl['initiator_groups']:
                    nacl = {}
                    nacl['path'] = acl['path']
                    eaclig.append(nacl)
                data['initiator_groups'] = eaclig
                si.acl_policy.set(tenant=tenant, **data)
        if self.use_chap_auth:
            for si in storage_instances:
                data = {'type': 'chap',
                        'target_user_name': self.chap_username,
                        'target_pswd': self.chap_password}
                si.auth.set(tenant=tenant, **data)
        # Check to ensure we're ready for go-time
        self._si_poll_2_1(volume, si, tenant)
        self._add_vol_meta_2_1(volume, connector=connector)

    # =================
    # = Detach Volume =
    # =================

    def _detach_volume_2_1(self, context, volume, attachment=None):
        try:
            tenant = self.get_tenant(volume['project_id'])
            ai = self.cvol_to_ai(volume, tenant=tenant)
            # Clear out ACL for this specific attachment
            si = ai.storage_instances.list(tenant=tenant)[0]
            existing_acl = si.acl_policy.get(tenant=tenant)
            data = {}
            # Grabbing only the 'path' key from each existing initiator
            # within the existing acl. eacli --> existing acl initiator
            eacli = []
            for acl in existing_acl['initiators']:
                if (
                    attachment is not None
                    and attachment.connector is not None
                    and acl['path'].split('/')[-1]
                    == attachment.connector['initiator']
                ):
                    continue
                nacl = {}
                nacl['path'] = acl['path']
                eacli.append(nacl)
            data['initiators'] = eacli
            data['initiator_groups'] = existing_acl['initiator_groups']
            si.acl_policy.set(tenant=tenant, **data)

            if not eacli:
                # bring the application instance offline if there
                # are no initiators left.
                data = {
                    'admin_state': 'offline',
                    'force': True
                }
                ai.set(tenant=tenant, **data)

        except exception.NotFound:
            msg = ("Tried to detach volume %s, but it was not found in the "
                   "Datera cluster. Continuing with detach.")
            LOG.info(msg, volume['id'])

    # ===================
    # = Create Snapshot =
    # ===================

    def _create_snapshot_2_1(self, snapshot):

        dummy_vol = {'id': snapshot['volume_id'],
                     'project_id': snapshot['project_id']}
        tenant = self.get_tenant(dummy_vol['project_id'])
        dvol = self.cvol_to_dvol(dummy_vol, tenant=tenant)
        snap_params = {
            'uuid': snapshot['id'],
        }
        snap = dvol.snapshots.create(tenant=tenant, **snap_params)
        self._snap_poll_2_1(snap, tenant)

    # ===================
    # = Delete Snapshot =
    # ===================

    def _delete_snapshot_2_1(self, snapshot):
        # Handle case where snapshot is "managed"
        dummy_vol = {'id': snapshot['volume_id'],
                     'project_id': snapshot['project_id']}
        tenant = self.get_tenant(dummy_vol['project_id'])
        dvol = self.cvol_to_dvol(dummy_vol, tenant=tenant)

        snapshots = None

        # Shortcut if this is a managed snapshot
        provider_location = snapshot.get('provider_location')
        if provider_location:
            snap = dvol.snapshots.get(provider_location, tenant=tenant)
            snap.delete(tenant=tenant)
            return

        # Long-way.  UUID identification
        try:
            snapshots = dvol.snapshots.list(tenant=tenant)
        except exception.NotFound:
            msg = ("Tried to delete snapshot %s, but parent volume %s was "
                   "not found in Datera cluster. Continuing with delete.")
            LOG.info(msg,
                     datc.get_name(snapshot),
                     datc.get_name({'id': snapshot['volume_id']}))
            return

        try:
            for snap in snapshots:
                if snap.uuid == snapshot['id']:
                    snap.delete(tenant=tenant)
                    break
            else:
                raise exception.NotFound
        except exception.NotFound:
            msg = ("Tried to delete snapshot %s, but was not found in "
                   "Datera cluster. Continuing with delete.")
            LOG.info(msg, datc.get_name(snapshot))

    # ========================
    # = Volume From Snapshot =
    # ========================

    def _create_volume_from_snapshot_2_1(self, volume, snapshot):
        # Handle case where snapshot is "managed"
        dummy_vol = {'id': snapshot['volume_id'],
                     'project_id': snapshot['project_id']}
        tenant = self.get_tenant(dummy_vol['project_id'])
        dvol = self.cvol_to_dvol(dummy_vol, tenant=tenant)
        found_snap = None
        provider_location = snapshot.get('provider_location')
        if provider_location:
            found_snap = dvol.snapshots.get(provider_location, tenant=tenant)
        else:
            snapshots = dvol.snapshots.list(tenant=tenant)
            for snap in snapshots:
                if snap.uuid == snapshot['id']:
                    found_snap = snap
                    break
            else:
                raise exception.SnapshotNotFound(snapshot_id=snapshot['id'])

        self._snap_poll_2_1(found_snap, tenant)

        src = found_snap.path
        app_params = (
            {
                'create_mode': 'openstack',
                'uuid': str(volume['id']),
                'name': datc.get_name(volume),
                'clone_snapshot_src': {'path': src},
            })

        self.api.app_instances.create(tenant=tenant, **app_params)
        if (volume['size'] > snapshot['volume_size']):
            self._extend_volume_2_1(volume, volume['size'])
        self._add_vol_meta_2_1(volume)

    # ==========
    # = Retype =
    # ==========

    def _retype_2_1(self, ctxt, volume, new_type, diff, host):
        LOG.debug("Retype called\n"
                  "Volume: %(volume)s\n"
                  "NewType: %(new_type)s\n"
                  "Diff: %(diff)s\n"
                  "Host: %(host)s\n", {'volume': volume, 'new_type': new_type,
                                       'diff': diff, 'host': host})
        # We'll take the fast route only if the types share the same backend
        # And that backend matches this driver
        old_pol = self._get_policies_for_resource(volume)
        new_pol = self._get_policies_for_volume_type(new_type)
        if (host['capabilities']['volume_backend_name'].lower() ==
                self.backend_name.lower()):
            LOG.debug("Starting fast volume retype")

            if old_pol.get('template') or new_pol.get('template'):
                LOG.warning(
                    "Fast retyping between template-backed volume-types "
                    "unsupported.  Type1: %s, Type2: %s",
                    volume['volume_type_id'], new_type)

            self._update_qos_2_1(volume, new_pol, clear_old=True)
            tenant = self.get_tenant(volume['project_id'])
            dvol = self.cvol_to_dvol(volume, tenant=tenant)
            # Only replica_count ip_pool requires offlining the app_instance
            if (new_pol['replica_count'] != old_pol['replica_count'] or
                    new_pol['ip_pool'] != old_pol['ip_pool']):
                with self._offline_flip_2_1(volume):
                    vol_params = (
                        {
                            'placement_mode': new_pol['placement_mode'],
                            'replica_count': new_pol['replica_count'],
                        })
                    dvol.set(tenant=tenant, **vol_params)
            elif new_pol['placement_mode'] != old_pol['placement_mode']:
                vol_params = (
                    {
                        'placement_mode': new_pol['placement_mode'],
                    })
                dvol.set(tenant=tenant, **vol_params)
            self._add_vol_meta_2_1(volume)
            return True

        else:
            LOG.debug("Couldn't fast-retype volume between specified types")
            return False

    # ==========
    # = Manage =
    # ==========

    def _manage_existing_2_1(self, volume, existing_ref):
        # Only volumes created under the requesting tenant can be managed in
        # the v2.1+ API.  Eg.  If tenant A is the tenant for the volume to be
        # managed, it must also be tenant A that makes this request.
        # This will be fixed in a later API update
        existing_ref = existing_ref['source-name']
        app_inst_name, __, __, __ = datc._parse_vol_ref(existing_ref)
        LOG.debug("Managing existing Datera volume %s  "
                  "Changing name to %s",
                  datc.get_name(volume), existing_ref)
        # Rename AppInstance
        dummy_vol = {'id': app_inst_name,
                     'project_id': volume['project_id']}
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(dummy_vol, tenant=tenant)
        data = {'name': datc.get_name(volume)}
        ai.set(tenant=tenant, **data)
        self._add_vol_meta_2_1(volume)

    # ===================
    # = Manage Get Size =
    # ===================

    def _manage_existing_get_size_2_1(self, volume, existing_ref):
        existing_ref = existing_ref['source-name']
        app_inst_name, storage_inst_name, vol_name, __ = datc._parse_vol_ref(
            existing_ref)
        dummy_vol = {'id': app_inst_name,
                     'project_id': volume['project_id']}
        dvol = self.cvol_to_dvol(dummy_vol)
        return dvol.size

    # =========================
    # = Get Manageable Volume =
    # =========================

    def _list_manageable_2_1(self, cinder_volumes):
        # Use the first volume to determine the tenant we're working under
        if cinder_volumes:
            tenant = self.get_tenant(cinder_volumes[0]['project_id'])
        else:
            tenant = None
        app_instances = self.api.app_instances.list(tenant=tenant)

        results = []

        if cinder_volumes and 'volume_id' in cinder_volumes[0]:
            cinder_volume_ids = [vol['volume_id'] for vol in cinder_volumes]
        else:
            cinder_volume_ids = [vol['id'] for vol in cinder_volumes]

        for ai in app_instances:
            ai_name = ai['name']
            reference = None
            size = None
            safe_to_manage = False
            reason_not_safe = ""
            cinder_id = None
            extra_info = {}
            (safe_to_manage, reason_not_safe,
                cinder_id) = self._is_manageable_2_1(
                    ai, cinder_volume_ids, tenant)
            si = ai.storage_instances.list(tenant=tenant)[0]
            si_name = si.name
            vol = si.volumes.list(tenant=tenant)[0]
            vol_name = vol.name
            size = vol.size
            snaps = [(snap.utc_ts, snap.uuid)
                     for snap in vol.snapshots.list(tenant=tenant)]
            extra_info["snapshots"] = json.dumps(snaps)
            reference = {"source-name": "{}:{}:{}".format(
                ai_name, si_name, vol_name)}

            results.append({
                'reference': reference,
                'size': size,
                'safe_to_manage': safe_to_manage,
                'reason_not_safe': reason_not_safe,
                'cinder_id': cinder_id,
                'extra_info': extra_info})
        return results

    def _get_manageable_volumes_2_1(self, cinder_volumes, marker, limit,
                                    offset, sort_keys, sort_dirs):
        LOG.debug("Listing manageable Datera volumes")
        results = self._list_manageable_2_1(cinder_volumes)
        page_results = volutils.paginate_entries_list(
            results, marker, limit, offset, sort_keys, sort_dirs)

        return page_results

    def _is_manageable_2_1(self, ai, cinder_volume_ids, tenant):
        cinder_id = None
        ai_name = ai.name
        match = datc.UUID4_RE.match(ai_name)
        if match:
            cinder_id = match.group(1)
        if cinder_id and cinder_id in cinder_volume_ids:
            return (False,
                    "App Instance already managed by Cinder",
                    cinder_id)
        if len(ai.storage_instances.list(tenant=tenant)) == 1:
            si = ai.storage_instances.list(tenant=tenant)[0]
            if len(si['volumes']) == 1:
                return (True, "", cinder_id)
        return (False,
                "App Instance has more than one storage instance or volume",
                cinder_id)
    # ============
    # = Unmanage =
    # ============

    def _unmanage_2_1(self, volume):
        LOG.debug("Unmanaging Cinder volume %s.  Changing name to %s",
                  volume['id'], datc.get_unmanaged(volume['id']))
        data = {'name': datc.get_unmanaged(volume['id'])}
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(volume, tenant=tenant)
        ai.set(tenant=tenant, **data)

    # ===================
    # = Manage Snapshot =
    # ===================

    def _manage_existing_snapshot_2_1(self, snapshot, existing_ref):
        existing_ref = existing_ref['source-name']
        datc._check_snap_ref(existing_ref)
        LOG.debug("Managing existing Datera volume snapshot %s for volume %s",
                  existing_ref, datc.get_name({'id': snapshot['volume_id']}))
        return {'provider_location': existing_ref}

    def _manage_existing_snapshot_get_size_2_1(self, snapshot, existing_ref):
        existing_ref = existing_ref['source-name']
        datc._check_snap_ref(existing_ref)
        dummy_vol = {'id': snapshot['volume_id'],
                     'project_id': snapshot['project_id']}
        dvol = self.cvol_to_dvol(dummy_vol)
        return dvol.size

    def _get_manageable_snapshots_2_1(self, cinder_snapshots, marker, limit,
                                      offset, sort_keys, sort_dirs):
        LOG.debug("Listing manageable Datera snapshots")
        results = self._list_manageable_2_1(cinder_snapshots)
        snap_results = []
        snapids = set((snap['id'] for snap in cinder_snapshots))
        snaprefs = set((snap.get('provider_location')
                        for snap in cinder_snapshots))
        for volume in results:
            snaps = json.loads(volume["extra_info"]["snapshots"])
            for snapshot in snaps:
                reference = snapshot[0]
                uuid = snapshot[1]
                size = volume["size"]
                safe_to_manage = True
                reason_not_safe = ""
                cinder_id = ""
                extra_info = {}
                source_reference = volume["reference"]
                if uuid in snapids or reference in snaprefs:
                    safe_to_manage = False
                    reason_not_safe = _("already managed by Cinder")
                elif not volume['safe_to_manage'] and not volume['cinder_id']:
                    safe_to_manage = False
                    reason_not_safe = _("parent volume not safe to manage")
                snap_results.append({
                    'reference': {'source-name': reference},
                    'size': size,
                    'safe_to_manage': safe_to_manage,
                    'reason_not_safe': reason_not_safe,
                    'cinder_id': cinder_id,
                    'extra_info': extra_info,
                    'source_reference': source_reference})
        page_results = volutils.paginate_entries_list(
            snap_results, marker, limit, offset, sort_keys, sort_dirs)

        return page_results

    def _unmanage_snapshot_2_1(self, snapshot):
        return {'provider_location': None}

    # ====================
    # = Fast Image Clone =
    # ====================

    def _clone_image_2_1(self, context, volume, image_location, image_meta,
                         image_service):
        # We're not going to fast image clone if the feature is not enabled
        # and/or we can't reach the image being requested
        if (not self.image_cache or
                not self._image_accessible(context, volume, image_meta)):
            return None, False
        # Check to make sure we're working with a valid volume type
        try:
            found = volume_types.get_volume_type(context, self.image_type)
        except (exception.VolumeTypeNotFound, exception.InvalidVolumeType):
            found = None
        if not found:
            msg = "Invalid volume type: %s"
            LOG.error(msg, self.image_type)
            raise ValueError(_("Option datera_image_cache_volume_type_id must"
                               " be set to a valid volume_type id"))
        # Check image format
        fmt = image_meta.get('disk_format', '')
        if fmt.lower() != 'raw':
            LOG.debug("Image format is not RAW, image requires conversion "
                      "before clone.  Image format: [%s]", fmt)
            return None, False

        LOG.debug("Starting fast image clone")
        # TODO(_alastor_): determine if Datera is already an image backend
        # for this request and direct clone instead of caching

        # Dummy volume, untracked by Cinder
        src_vol = {'id': image_meta['id'],
                   'volume_type_id': self.image_type,
                   'size': volume['size'],
                   'project_id': volume['project_id']}

        # Determine if we have a cached version of the image
        cached = self._vol_exists_2_1(src_vol)

        if cached:
            tenant = self.get_tenant(src_vol['project_id'])
            ai = self.cvol_to_ai(src_vol, tenant=tenant)
            metadata = ai.metadata.get(tenant=tenant)
            # Check to see if the master image has changed since we created
            # The cached version
            ts = self._get_vol_timestamp_2_1(src_vol)
            mts = time.mktime(image_meta['updated_at'].timetuple())
            LOG.debug("Original image timestamp: %s, cache timestamp %s",
                      mts, ts)
            # If the image is created by Glance, we'll trust that even if the
            # timestamps don't match up, the data is ok to clone as it's not
            # managed by this driver
            if metadata.get('type') == 'image':
                LOG.debug("Found Glance volume-backed image for %s",
                          src_vol['id'])
            # If the master image time is greater than the volume creation
            # time, we invalidate the cache and delete the volume.  The
            # exception is if the cached volume was created by Glance.  We
            # NEVER want to delete this volume.  It's annotated with
            # 'type': 'image' in the metadata, so we'll check for that
            elif mts > ts and metadata.get('type') != 'image':
                LOG.debug("Cache is older than original image, deleting cache")
                cached = False
                self._delete_volume_2_1(src_vol)

        # If we don't have the image, we'll cache it
        if not cached:
            LOG.debug("No image cache found for: %s, caching image",
                      image_meta['id'])
            self._cache_vol_2_1(context, src_vol, image_meta, image_service)

        # Now perform the clone of the found image or newly cached image
        self._create_cloned_volume_2_1(volume, src_vol)
        # Force volume resize
        vol_size = volume['size']
        volume['size'] = 0
        self._extend_volume_2_1(volume, vol_size)
        volume['size'] = vol_size
        # Determine if we need to retype the newly created volume
        vtype_id = volume.get('volume_type_id')
        if vtype_id and self.image_type and vtype_id != self.image_type:
            vtype = volume_types.get_volume_type(context, vtype_id)
            LOG.debug("Retyping newly cloned volume from type: %s to type: %s",
                      self.image_type, vtype_id)
            diff, discard = volume_types.volume_types_diff(
                context, self.image_type, vtype_id)
            host = {'capabilities': {'vendor_name': self.backend_name}}
            self._retype_2_1(context, volume, vtype, diff, host)
        return None, True

    def _cache_vol_2_1(self, context, vol, image_meta, image_service):
        image_id = image_meta['id']
        # Pull down image and determine if valid
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

            vsize = int(
                math.ceil(float(data.virtual_size) / units.Gi))
            vol['size'] = vsize
            vtype = vol['volume_type_id']
            LOG.info("Creating cached image with volume type: %(vtype)s and "
                     "size %(size)s", {'vtype': vtype, 'size': vsize})
            self._create_volume_2_1(vol)
            with self._connect_vol(context, vol) as device:
                LOG.debug("Moving image %s to volume %s",
                          image_meta['id'], datc.get_name(vol))
                image_utils.convert_image(tmp_image,
                                          device,
                                          'raw',
                                          run_as_root=True)
                LOG.debug("Finished moving image %s to volume %s",
                          image_meta['id'], datc.get_name(vol))
                data = image_utils.qemu_img_info(device, run_as_root=True)
                if data.file_format != 'raw':
                    raise exception.ImageUnacceptable(
                        image_id=image_id,
                        reason=_(
                            "Converted to %(vol_format)s, but format is "
                            "now %(file_format)s") % {
                                'vol_format': 'raw',
                                'file_format': data.file_format})
        # TODO(_alastor_): Remove this snapshot creation when we fix
        # "created_at" attribute in the frontend
        # We don't actually care about the snapshot uuid, we just want
        # a single snapshot
        snapshot = {'id': str(uuid.uuid4()),
                    'volume_id': vol['id'],
                    'project_id': vol['project_id']}
        self._create_snapshot_2_1(snapshot)
        metadata = {'type': 'cached_image'}
        tenant = self.get_tenant(vol['project_id'])
        ai = self.cvol_to_ai(vol, tenant=tenant)
        ai.metadata.set(tenant=tenant, **metadata)
        # Cloning offline AI is ~4 seconds faster than cloning online AI
        self._detach_volume_2_1(None, vol)

    def _get_vol_timestamp_2_1(self, volume):
        tenant = self.get_tenant(volume['project_id'])
        dvol = self.cvol_to_dvol(volume, tenant=tenant)
        snapshots = dvol.snapshots.list(tenant=tenant)
        if len(snapshots) == 1:
            return float(snapshots[0].utc_ts)
        else:
            # We'll return 0 if we find no snapshots (or the incorrect number)
            # to ensure the timestamp comparison with the master copy fails
            # since the master copy will always have a timestamp > 0.
            LOG.debug("Number of snapshots found: %s", len(snapshots))
            return 0

    def _vol_exists_2_1(self, volume):
        LOG.debug("Checking if volume %s exists", volume['id'])
        try:
            ai = self.cvol_to_ai(volume)
            LOG.debug("Volume %s exists", volume['id'])
            return ai
        except exception.NotFound:
            LOG.debug("Volume %s not found", volume['id'])
            return None

    @contextlib.contextmanager
    def _connect_vol(self, context, vol):
        connector = None
        try:
            # Start connection, get the connector object and create the
            # export (ACL, IP-Pools, etc)
            conn = self._initialize_connection_2_1(
                vol, {'multipath': False})
            connector = volutils.brick_get_connector(
                conn['driver_volume_type'],
                use_multipath=False,
                device_scan_attempts=10,
                conn=conn)
            connector_info = {'initiator': connector.get_initiator()}
            self._create_export_2_1(None, vol, connector_info)
            retries = 10
            attach_info = conn['data']
            while True:
                try:
                    attach_info.update(
                        connector.connect_volume(conn['data']))
                    break
                except brick_exception.FailedISCSITargetPortalLogin:
                    retries -= 1
                    if not retries:
                        LOG.error("Could not log into portal before end of "
                                  "polling period")
                        raise
                    LOG.debug("Failed to login to portal, retrying")
                    eventlet.sleep(2)
            device_path = attach_info['path']
            yield device_path
        finally:
            # Close target connection
            if connector:
                # Best effort disconnection
                try:
                    connector.disconnect_volume(attach_info, attach_info)
                except Exception:
                    pass

    # ===========
    # = Polling =
    # ===========

    def _snap_poll_2_1(self, snap, tenant):
        eventlet.sleep(datc.DEFAULT_SNAP_SLEEP)
        TIMEOUT = 20
        retry = 0
        poll = True
        while poll and not retry >= TIMEOUT:
            retry += 1
            snap = snap.reload(tenant=tenant)
            if snap.op_state == 'available':
                poll = False
            else:
                eventlet.sleep(1)
        if retry >= TIMEOUT:
            raise exception.VolumeDriverException(
                message=_('Snapshot not ready.'))

    def _si_poll_2_1(self, volume, si, tenant):
        # Initial 4 second sleep required for some Datera versions
        eventlet.sleep(datc.DEFAULT_SI_SLEEP)
        TIMEOUT = 10
        retry = 0
        poll = True
        while poll and not retry >= TIMEOUT:
            retry += 1
            si = si.reload(tenant=tenant)
            if si.op_state == 'available':
                poll = False
            else:
                eventlet.sleep(1)
        if retry >= TIMEOUT:
            raise exception.VolumeDriverException(
                message=_('Resource not ready.'))

    # ================
    # = Volume Stats =
    # ================

    def _get_volume_stats_2_1(self, refresh=False):
        # cluster_stats is defined by datera_iscsi
        # pylint: disable=access-member-before-definition
        if refresh or not self.cluster_stats:
            try:
                LOG.debug("Updating cluster stats info.")

                results = self.api.system.get()

                if 'uuid' not in results:
                    LOG.error(
                        'Failed to get updated stats from Datera Cluster.')

                stats = {
                    'volume_backend_name': self.backend_name,
                    'vendor_name': 'Datera',
                    'driver_version': self.VERSION,
                    'storage_protocol': 'iSCSI',
                    'total_capacity_gb': (
                        int(results.total_capacity) / units.Gi),
                    'free_capacity_gb': (
                        int(results.available_capacity) / units.Gi),
                    'reserved_percentage': 0,
                    'QoS_support': True,
                }

                self.cluster_stats = stats
            except exception.DateraAPIException:
                LOG.error('Failed to get updated stats from Datera cluster.')
        return self.cluster_stats

    # =======
    # = QoS =
    # =======

    def _update_qos_2_1(self, volume, policies, clear_old=False):
        tenant = self.get_tenant(volume['project_id'])
        dvol = self.cvol_to_dvol(volume, tenant=tenant)
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            iops_per_gb = int(policies.get('iops_per_gb', 0))
            bandwidth_per_gb = int(policies.get('bandwidth_per_gb', 0))
            # Filter for just QOS policies in result. All of their keys
            # should end with "max"
            fpolicies = {k: int(v) for k, v in
                         policies.items() if k.endswith("max")}
            # Filter all 0 values from being passed
            fpolicies = {k: int(v) for k, v in
                         fpolicies.items() if v > 0}
            # Calculate and set iops/gb and bw/gb, but only if they don't
            # exceed total_iops_max and total_bw_max aren't set since they take
            # priority
            if iops_per_gb:
                ipg = iops_per_gb * volume['size']
                # Not using zero, because zero means unlimited
                im = fpolicies.get('total_iops_max', 1)
                r = ipg
                if ipg > im:
                    r = im
                fpolicies['total_iops_max'] = r
            if bandwidth_per_gb:
                bpg = bandwidth_per_gb * volume['size']
                # Not using zero, because zero means unlimited
                bm = fpolicies.get('total_bandwidth_max', 1)
                r = bpg
                if bpg > bm:
                    r = bm
                fpolicies['total_bandwidth_max'] = r
            if fpolicies or clear_old:
                try:
                    pp = dvol.performance_policy.get(tenant=tenant)
                    pp.delete(tenant=tenant)
                except dexceptions.ApiNotFoundError:
                    LOG.debug("No existing performance policy found")
            if fpolicies:
                dvol.performance_policy.create(tenant=tenant, **fpolicies)

    # ============
    # = IP Pools =
    # ============

    def _get_ip_pool_for_string_ip_2_1(self, ip, tenant):
        """Takes a string ipaddress and return the ip_pool API object dict """
        pool = 'default'
        ip_obj = ipaddress.ip_address(six.text_type(ip))
        ip_pools = self.api.access_network_ip_pools.list(tenant=tenant)
        for ipdata in ip_pools:
            for adata in ipdata['network_paths']:
                if not adata.get('start_ip'):
                    continue
                pool_if = ipaddress.ip_interface(
                    "/".join((adata['start_ip'], str(adata['netmask']))))
                if ip_obj in pool_if.network:
                    pool = ipdata.name
        return self.api.access_network_ip_pools.get(pool, tenant=tenant).path
    # ====================
    # = Volume Migration =
    # ====================

    def _update_migrated_volume_2_1(self, context, volume, new_volume,
                                    volume_status):
        """Rename the newly created volume to the original volume.

        So we can find it correctly.
        """
        tenant = self.get_tenant(new_volume['project_id'])
        ai = self.cvol_to_ai(new_volume, tenant=tenant)
        data = {'name': datc.get_name(volume)}
        ai.set(tenant=tenant, **data)
        return {'_name_id': None}

    @contextlib.contextmanager
    def _offline_flip_2_1(self, volume):
        reonline = False
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(volume, tenant=tenant)
        if ai.admin_state == 'online':
            reonline = True
        ai.set(tenant=tenant, admin_state='offline')
        yield
        if reonline:
            ai.set(tenant=tenant, admin_state='online')

    def _add_vol_meta_2_1(self, volume, connector=None):
        if not self.do_metadata:
            return
        metadata = {'host': volume.get('host', ''),
                    'display_name': datc.filter_chars(
                        volume.get('display_name', '')),
                    'bootable': str(volume.get('bootable', False)),
                    'availability_zone': volume.get('availability_zone', '')}
        if connector:
            metadata.update(connector)
        LOG.debug("Adding volume metadata: %s", metadata)
        tenant = self.get_tenant(volume['project_id'])
        ai = self.cvol_to_ai(volume, tenant=tenant)
        ai.metadata.set(tenant=tenant, **metadata)
