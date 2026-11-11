# Copyright (c) 2025 NetApp, Inc. All rights reserved.
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
NetApp ASA r2 REST client for Data ONTAP.

This module provides the ASA r2 specific REST client that inherits from
the base REST client and overrides methods to implement ASA r2 specific
workflows when needed.
"""

import time

from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils

from cinder.i18n import _
from cinder.volume.drivers.netapp.dataontap.client import api as netapp_api
from cinder.volume.drivers.netapp.dataontap.client import client_cmode_rest
from cinder.volume.drivers.netapp import utils as netapp_utils
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)
DELETED_PREFIX = client_cmode_rest.DELETED_PREFIX

# A storage unit is a LUN or a namespace. The storage unit endpoint does not
# accept a new name, so renames have to go through the protocol endpoint.
STORAGE_UNIT_ENDPOINTS = {
    'lun': '/storage/luns',
    'namespace': '/storage/namespaces',
}

# Errors meaning the object is still referenced by a clone, so it cannot be
# deleted until every dependent clone has been split.
CLONE_DEPENDENCY_ERRORS = (
    netapp_api.EDELETE_SPLIT_CLONE,
    netapp_api.ERROR_VOLUME_BUSY,
    netapp_api.ESNAPSHOT_EXPIRED_OR_LOCK,
)

# Collection endpoint that returns snapshots of every storage unit in one
# call, instead of one call per storage unit.
ALL_STORAGE_UNIT_SNAPSHOTS = '/storage/storage-units/*/snapshots'


class RestClientASAr2(client_cmode_rest.RestClient,
                      metaclass=volume_utils.TraceWrapperMetaclass):
    """NetApp ASA r2 REST client for Data ONTAP.

    This client inherits from the base REST client and provides ASA r2
    specific functionality for disaggregated platform workflows.

    By default, all methods from the parent RestClient are called.
    Override methods only when ASA r2 specific functionality is required.
    The __getattr__ method automatically routes any missing methods to the
    parent class, eliminating the need to explicitly define every method.
    """

    def __init__(self, **kwargs):
        """Initialize the ASA r2 REST client.

        :param kwargs: Same parameters as the parent RestClient
        """
        LOG.info("Initializing NetApp ASA r2 REST client")
        self.config = None
        super(RestClientASAr2, self).__init__(**kwargs)
        self._init_asar2_features()

    def _init_asar2_features(self):
        """Initialize ASA r2 specific features.

        This method can be used to set up ASA r2 specific features
        and capabilities that are different from the standard ONTAP.
        """
        LOG.debug("Initializing ASA r2 specific features")

        # Remove features not supported in ASA r2 by setting them to False
        self.features.add_feature('SYSTEM_CONSTITUENT_METRICS',
                                  supported=False)
        self.features.add_feature('SYSTEM_METRICS', supported=False)
        # ASA r2 has no counter-based fallback, so always refresh via metrics.
        self.features.add_feature('NODE_METRICS', supported=True)

        # Add ASA r2 specific features here
        # For example, you might want to enable specific features
        # that are only available in ASA r2 environments

        # Example of adding ASA r2 specific features:
        # self.features.add_feature('ASA_R2_SPECIFIC_FEATURE', supported=True)
        # self.features.add_feature('ASA_R2_ENHANCED_CLONING', supported=True)
        LOG.debug("ASA r2 specific features initialized successfully")

    def __getattr__(self, name):
        """Log missing method call and return None."""
        LOG.error("Method '%s' not found in ASA r2 client", name)
        return None

    def get_performance_counter_info(self, object_name, counter_name):
        """ASA r2 doesn't support performance counter APIs as of now.

        TODO: Performance counter support will be added in upcoming releases.
        """
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    def get_performance_instance_uuids(self, object_name, node_name):
        """ASA r2 doesn't support performance counter APIs."""
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    def get_performance_counters(self, object_name, instance_uuids,
                                 counter_names):
        """ASA r2 doesn't support performance counter APIs."""
        msg = _('Performance counter APIs are not supported on ASA r2.')
        raise netapp_utils.NetAppDriverException(msg)

    # ASA r2 does not support ONTAPI, so we raise NotImplementedError
    def get_ontapi_version(self, cached=True):
        """ASA r2 doesn't support ONTAPI."""
        return (0, 0)

    def get_cluster_info(self):
        """Get cluster information for ASA r2."""
        query_args = {
            'fields': 'name,disaggregated',
        }

        try:
            response = self.send_request('/cluster',
                                         'get', query=query_args,
                                         enable_tunneling=False)
            return response
        except Exception as e:
            LOG.exception('Failed to get cluster information: %s', e)
            return None

    def get_aggregate_disk_types(self):
        """Get storage_types as array from all aggregates."""
        query = {
            'fields': 'name,block_storage.storage_type'
        }

        try:
            response = self.send_request('/storage/aggregates',
                                         'get', query=query,
                                         enable_tunneling=False)
            if not response or 'records' not in response:
                LOG.error('No records received from aggregate API')
                return None

            # Collect storage types from all aggregates
            storage_types = []
            if response['records']:
                for record in response['records']:
                    storage_type = (
                        record.get('block_storage', {}).get('storage_type'))
                    if storage_type:
                        storage_types.append(storage_type)

                LOG.debug('Aggregate storage types: %s', storage_types)
                return storage_types

            LOG.warning('No aggregate records found')
            return None

        except Exception as e:
            LOG.exception('Failed to get aggregate storage types: %s', e)
            msg = _('Failed to get aggregate storage types: %s')
            raise netapp_utils.NetAppDriverException(msg % e)

    def create_lun(self, volume_name, lun_name, size, metadata,
                   qos_policy_group_name=None,
                   qos_policy_group_is_adaptive=False):
        """Issues API request for creating LUN."""
        initial_size = size
        lun_name = lun_name.replace("-", "_")
        body = {
            'name': lun_name,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
        }
        if qos_policy_group_name:
            body['qos_policy.name'] = qos_policy_group_name

        try:
            self.send_request('/storage/luns', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning volume %(lun_name)s on cluster.'
                          ' Details: %(ex)s',
                          {
                              'lun_name': lun_name,
                              'ex': ex,
                          })

    def destroy_lun(self, path, force=True):
        """Destroys the LUN at the path."""
        lun_name = self._get_backend_storage_unit(path)
        self._destroy_storage_unit(lun_name, 'lun', force=force)

    def create_namespace(self, volume_name, namespace_name, size, metadata):
        """Issues API request for creating namespace"""

        initial_size = size
        namespace_name = namespace_name.replace("-", "_")
        body = {
            'name': namespace_name,
            'space.size': str(initial_size),
            'os_type': metadata['OsType'],
        }

        try:
            self.send_request('/storage/namespaces', 'post', body=body)
        except netapp_api.NaApiError as ex:
            with excutils.save_and_reraise_exception():
                LOG.error('Error provisioning namespace %(namespace_name)s'
                          ' on cluster Details: %(ex)s',
                          {
                              'namespace_name': namespace_name,
                              'ex': ex,
                          })

    def destroy_namespace(self, path, force=True):
        """Destroys the namespace at the path."""
        namespace_name = self._get_backend_storage_unit(path)
        self._destroy_storage_unit(namespace_name, 'namespace', force=force)

    def _destroy_storage_unit(self, name, unit_type, force=True):
        """Delete a LUN or namespace, deferring it if it still has clones.

        A storage unit that still has clones, including a cache volume, is
        renamed with the deleted prefix and this call returns. The periodic
        cleanup task deletes it once the clones are gone, and starts their
        splits while any clone remains.
        """
        # If the storage unit is not found on ONTAP, there is nothing to do.
        try:
            su_uuid = self._get_storage_unit_uuid(name)
        except netapp_utils.NetAppDriverException:
            LOG.error('Could not find storage unit %(name)s', {'name': name})
            return

        query = {'name': name}
        if unit_type == 'namespace':
            query['svm'] = self.vserver
        if force:
            query['allow_delete_while_mapped'] = 'true'
        endpoint = STORAGE_UNIT_ENDPOINTS[unit_type]

        try:
            # Wait only if this storage unit is already being split (for
            # example a clone whose parent snapshot was just deleted). With
            # require_split_start=False the wait returns immediately when no
            # split is in progress. See ONTAP bug #CONTAP-639582.
            self.wait_for_split_to_complete(
                su_uuid,
                wait_interval=self.config.netapp_clone_split_timeout)
            self.send_request(endpoint, 'delete', query=query)
        except netapp_api.NaApiError as e:
            with excutils.save_and_reraise_exception() as exc_context:
                if e.code in CLONE_DEPENDENCY_ERRORS:
                    self.mark_storage_unit_for_deletion(
                        name, unit_type, su_uuid=su_uuid)
                    exc_context.reraise = False

    def get_lun_map(self, path):
        """Gets the LUN map by LUN path."""
        lun_name = self._get_backend_storage_unit(path)
        return super().get_lun_map(lun_name)

    def map_lun(self, path, igroup_name, lun_id=None):
        """Maps LUN to the initiator and returns LUN id assigned."""
        lun_name = self._get_backend_storage_unit(path)
        return super().map_lun(lun_name, igroup_name, lun_id)

    def get_lun_by_args(self, path=None):
        """Retrieves LUN with specified args."""
        if path:
            if 'path' in path:
                lun_name = self._get_backend_storage_unit(path)
                path['path'] = lun_name
        return super().get_lun_by_args(path=path)

    def unmap_lun(self, path, igroup_name):
        """Unmaps a LUN from given initiator."""
        lun_name = self._get_backend_storage_unit(path)
        super().unmap_lun(lun_name, igroup_name)

    def map_namespace(self, path, subsystem_name):
        """Maps namespace to the host nqn and returns namespace uuid."""
        namespace_name = self._get_backend_storage_unit(path)
        return super().map_namespace(namespace_name, subsystem_name)

    def unmap_namespace(self, path, subsystem):
        """Unmaps a namespace from given subsystem."""
        namespace_name = self._get_backend_storage_unit(path)
        super().unmap_namespace(namespace_name, subsystem)

    def get_namespace_map(self, path):
        """Gets the namespace map using its path."""
        namespace_name = self._get_backend_storage_unit(path)
        return super().get_namespace_map(namespace_name)

    def do_direct_resize(self, path, new_size_bytes, force=True):
        """Resize the LUN."""
        lun_name = self._get_backend_storage_unit(path)
        if lun_name is not None:
            LOG.info('Resizing LUN %s directly to new size.', lun_name)
            body = {'name': lun_name, 'space.size': new_size_bytes}
            self._lun_update_by_path(lun_name, body)

    def namespace_resize(self, path, new_size_bytes):
        """Resize the namespace."""
        namespace_name = self._get_backend_storage_unit(path)
        if namespace_name is not None:
            body = {'space.size': new_size_bytes}
            query = {'name': namespace_name}
            self.send_request('/storage/namespaces',
                              'patch',
                              body=body,
                              query=query
                              )

    def get_lun_sizes_by_volume(self, volume_name):
        """"Gets the list of LUNs and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }

        response = self.send_request('/storage/luns/', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        luns = []
        for lun_info in response['records']:
            luns.append({
                'path': lun_info.get('name', ''),
                'size': float(lun_info.get('space', {}).get('size', 0))
            })
        return luns

    def get_namespace_sizes_by_volume(self, volume_name):
        """Gets the list of namespace and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }
        response = self.send_request('/storage/namespaces', 'get', query=query)

        namespaces = []
        for namespace_info in response.get('records', []):
            namespaces.append({
                'path': namespace_info.get('name', ''),
                'size': float(namespace_info.get('space', {}).get('size', 0))
            })

        return namespaces

    def get_aggregate_capacities(self, aggregate_names):
        """Gets capacity info for multiple aggregates."""

        return super().get_aggregate_capacities(aggregate_names)

    def create_snapshot(self, storage_unit, snapshot_name):
        """Creates a snapshot for the specified storage unit."""
        su_name = self._get_backend_storage_unit(storage_unit)
        storage_unit_uuid = self._get_storage_unit_uuid(su_name)
        body = {
            "name": snapshot_name,
        }
        su_get_api = f'storage/storage-units/{storage_unit_uuid}/snapshots'
        self.send_request(su_get_api, 'post', body=body)

    def delete_snapshot(self, storage_unit, snapshot_name):
        """Delete a snapshot for the specified storage unit.

        A snapshot that still has clones is renamed with the deleted prefix
        and this call returns. The periodic cleanup task deletes it once
        the clones are gone.
        """
        su_name = self._get_backend_storage_unit(storage_unit)
        try:
            su_uuid = self._get_storage_unit_uuid(su_name)
        except netapp_utils.NetAppDriverException:
            LOG.error('Could not find storage unit %(name)s',
                      {'name': storage_unit})
            return

        del_api = (f'storage/storage-units/'
                   f'{su_uuid}/snapshots?name={snapshot_name}')
        try:
            self.send_request(del_api, 'delete')
        except netapp_api.NaApiError as e:
            with excutils.save_and_reraise_exception() as exc_context:
                if (
                        e.code == netapp_api.ESNAPSHOT_EXPIRED_OR_LOCK
                ) or (e.code == netapp_api.ERROR_VOLUME_BUSY):
                    LOG.info('Snapshot %(snap)s on storage unit %(su)s '
                             'has clones. Marking it for deletion.',
                             {'snap': snapshot_name, 'su': su_name})
                    self.mark_snapshot_for_deletion(
                        su_name, snapshot_name, su_uuid=su_uuid)
                    exc_context.reraise = False
                elif e.code == netapp_api.ESNAPSHOT_NOT_FOUND:
                    LOG.debug("Snapshot %s was not found on ONTAP.",
                              snapshot_name)
                    exc_context.reraise = False

    def mark_snapshot_for_deletion(self, storage_unit, snapshot_name,
                                   su_uuid=None):
        """Rename a snapshot so the cleanup task deletes it later."""
        if snapshot_name.startswith(DELETED_PREFIX):
            return

        su_name = self._get_backend_storage_unit(storage_unit)
        if su_uuid is None:
            su_uuid = self._get_storage_unit_uuid(su_name)

        snapshot_uuid = self._get_snapshot_uuid(su_uuid, snapshot_name)
        if snapshot_uuid is None:
            LOG.debug('Snapshot %s was not found on ONTAP; nothing to mark '
                      'for deletion.', snapshot_name)
            return

        new_name = DELETED_PREFIX + snapshot_name
        self.send_request(
            f'/storage/storage-units/{su_uuid}/snapshots/{snapshot_uuid}',
            'patch', body={'name': new_name})
        LOG.info('Snapshot %(old)s on storage unit %(su)s renamed to '
                 '%(new)s. It will be deleted once its dependent clones '
                 'have been split.',
                 {'old': snapshot_name, 'su': su_name, 'new': new_name})

    def mark_storage_unit_for_deletion(self, name, unit_type, su_uuid=None):
        """Rename a LUN or namespace so the cleanup task deletes it later.

        The storage unit endpoint only accepts a name on create, so the
        rename goes through the protocol endpoint. A storage unit and its
        LUN or namespace are the same object and share a UUID, so the UUID
        already resolved for the storage unit can be reused here.
        """
        if name.startswith(DELETED_PREFIX):
            return

        endpoint = STORAGE_UNIT_ENDPOINTS.get(unit_type)
        if endpoint is None:
            msg = _('Cannot mark storage unit %(name)s for deletion: '
                    'unknown storage unit type %(type)s.')
            msg_args = {'name': name, 'type': unit_type}
            raise netapp_utils.NetAppDriverException(msg % msg_args)

        if su_uuid is None:
            su_uuid = self._get_storage_unit_uuid(name)

        new_name = DELETED_PREFIX + name
        self.send_request(f'{endpoint}/{su_uuid}', 'patch',
                          body={'name': new_name})
        LOG.info('Storage unit %(old)s renamed to %(new)s. It will be '
                 'deleted once its dependent clones have been split.',
                 {'old': name, 'new': new_name})

    def _get_snapshot_uuid(self, su_uuid, snapshot_name):
        """Return the UUID of a storage unit snapshot, or None."""
        query = {'name': snapshot_name, 'fields': 'uuid'}
        response = self.send_request(
            f'/storage/storage-units/{su_uuid}/snapshots', 'get', query=query)
        records = response.get('records', [])
        return records[0]['uuid'] if records else None

    def volume_clone_split_start(self, clone_volume_uuid):
        """Split clone volume"""
        body = {
            "clone": {
                "split_initiated": True
            }
        }
        return self.send_request(
            f'/storage/storage-units/{clone_volume_uuid}',
            'patch', body=body, wait_on_accepted=False
        )

    def _source_names(self, name):
        """Names a clone may still use for a source.

        Clones are created from the original name. A source marked for
        deletion has been renamed, so the original name is checked first.
        """
        names = []
        if name.startswith(DELETED_PREFIX):
            original = name[len(DELETED_PREFIX):]
            if original:
                names.append(original)
        if name not in names:
            names.append(name)
        return names

    def _get_clone_uuids(self, storage_unit_uuid=None, snapshot_uuid=None,
                         storage_unit_name=None, snapshot_name=None):
        """Return the UUIDs of the storage units cloned from a source.

        Snapshot clones are matched by snapshot name and storage unit name,
        which is how they are created. UUID filters are also accepted.
        """
        if not any((storage_unit_uuid, snapshot_uuid,
                    storage_unit_name, snapshot_name)):
            # Without a source filter this would match every storage unit in
            # the SVM and split all of them.
            return []

        query = {'fields': 'uuid'}
        if storage_unit_name:
            query['clone.source.storage_unit.name'] = storage_unit_name
        if snapshot_name:
            query['clone.source.snapshot.name'] = snapshot_name
        if storage_unit_uuid:
            query['clone.source.storage_unit.uuid'] = storage_unit_uuid
        if snapshot_uuid:
            query['clone.source.snapshot.uuid'] = snapshot_uuid

        response = self.get_records('/storage/storage-units/', query=query)
        return [record['uuid'] for record in response.get('records', [])
                if record.get('uuid')]

    def _clones_of_snapshot(self, storage_unit_name, snapshot_name):
        """Return clone UUIDs created from this snapshot."""
        for su_name in self._source_names(storage_unit_name):
            for snap_name in self._source_names(snapshot_name):
                clones = self._get_clone_uuids(
                    storage_unit_name=su_name, snapshot_name=snap_name)
                if clones:
                    return clones
        return []

    def _clones_of_storage_unit(self, storage_unit_name):
        """Return clone UUIDs created from this storage unit."""
        for su_name in self._source_names(storage_unit_name):
            clones = self._get_clone_uuids(storage_unit_name=su_name)
            if clones:
                return clones
        return []

    def _start_clone_splits(self, clone_uuids):
        """Start clone split jobs without waiting for them to finish."""
        for clone_uuid in clone_uuids:
            try:
                self.volume_clone_split_start(clone_uuid)
                LOG.debug('Started clone split for storage unit %s.',
                          clone_uuid)
            except Exception:
                LOG.exception('Failed to start clone split for storage '
                              'unit %s.', clone_uuid)

    def restore_snapshot(self, storage_unit, snapshot_name):
        """Restore a snapshot of the specified storage unit."""
        su_name = self._get_backend_storage_unit(storage_unit)
        su_uuid = self._get_storage_unit_uuid(su_name)
        body = {
            "restore_to": {
                "snapshot": {
                    "name": snapshot_name
                }
            }
        }
        self.send_request(f'storage/storage-units/{su_uuid}', 'patch',
                          body=body, wait_on_accepted=True)

    def get_snapshots_marked_for_deletion(self):
        """Get the storage unit snapshots that are marked for deletion."""
        fields = 'name,uuid,storage_unit.name,storage_unit.uuid'
        query = {
            'name': f'{DELETED_PREFIX}*',
            'svm.name': self.vserver,
            'fields': fields,
        }

        response = self.get_records(ALL_STORAGE_UNIT_SNAPSHOTS, query=query)
        return self._build_marked_snapshots(response.get('records', []))

    def _build_marked_snapshots(self, records):
        """Normalize snapshot records into the cleanup task's format."""
        snapshots = []
        for record in records:
            owner = record.get('storage_unit') or {}
            if not owner.get('uuid') or not owner.get('name'):
                LOG.debug('Skipping snapshot %s; its storage unit could not '
                          'be resolved.', record.get('name'))
                continue
            snapshots.append({
                'name': record['name'],
                'uuid': record['uuid'],
                'storage_unit_name': owner.get('name'),
                'storage_unit_uuid': owner.get('uuid'),
            })
        return snapshots

    def get_storage_units_marked_for_deletion(self):
        """Get the LUNs and namespaces that are marked for deletion."""
        query = {
            'name': f'{DELETED_PREFIX}*',
            'svm.name': self.vserver,
            'fields': 'name,uuid,type',
        }
        response = self.get_records('/storage/storage-units/', query=query)
        return [
            {
                'name': record.get('name'),
                'uuid': record.get('uuid'),
                'type': record.get('type'),
            }
            for record in response.get('records', []) if record.get('uuid')
        ]

    def delete_resources_marked_for_deletion(self):
        """Clean up snapshots and storage units renamed for deletion.

        A resource that still has clones has those splits started and is
        left for the next run. A resource with no clones is deleted.
        Snapshots are handled first because deleting one can release the
        last clone dependency on a storage unit queued behind it. One
        failure does not block the rest of the cleanup.
        """
        for snapshot in self.get_snapshots_marked_for_deletion():
            try:
                self._delete_marked_snapshot(snapshot)
            except Exception:
                LOG.exception('Could not delete snapshot %(snapshot)s on '
                              'storage unit %(su)s. It will be retried.',
                              {'snapshot': snapshot['name'],
                               'su': snapshot['storage_unit_name']})

        for storage_unit in self.get_storage_units_marked_for_deletion():
            try:
                self._delete_marked_storage_unit(storage_unit)
            except Exception:
                LOG.exception('Could not delete storage unit %s. It will be '
                              'retried.', storage_unit['name'])

    def _delete_marked_snapshot(self, snapshot):
        """Delete a renamed snapshot.

        The delete is attempted first. If it fails because clones still
        reference the snapshot, those splits are started and the snapshot
        is left for the next cleanup cycle.
        """
        su_uuid = snapshot['storage_unit_uuid']
        del_api = (f'storage/storage-units/{su_uuid}/snapshots'
                   f'?name={snapshot["name"]}')
        try:
            self.send_request(del_api, 'delete')
        except netapp_api.NaApiError as e:
            if e.code == netapp_api.ESNAPSHOT_NOT_FOUND:
                LOG.debug('Snapshot %s was not found on ONTAP.',
                          snapshot['name'])
                return
            if e.code not in (netapp_api.ESNAPSHOT_EXPIRED_OR_LOCK,
                              netapp_api.ERROR_VOLUME_BUSY):
                raise
            LOG.info('Snapshot %(snap)s on storage unit %(su)s still has '
                     'clones. Starting split and leaving it for the next '
                     'cleanup.',
                     {'snap': snapshot['name'],
                      'su': snapshot['storage_unit_name']})
            self._start_clone_splits(self._clones_of_snapshot(
                snapshot['storage_unit_name'], snapshot['name']))

    def _delete_marked_storage_unit(self, storage_unit):
        """Delete a renamed storage unit, or restart its clone splits.

        If the storage unit still has dependent clones, start their splits
        without waiting and do not delete it. The unit stays marked and is
        retried on the next cleanup cycle once the splits have finished.
        """
        clones = self._clones_of_storage_unit(storage_unit['name'])
        if clones:
            LOG.info('Storage unit %(name)s still has clones. Starting '
                     'split and leaving it for the next cleanup.',
                     {'name': storage_unit['name']})
            self._start_clone_splits(clones)
            return

        endpoint = STORAGE_UNIT_ENDPOINTS.get(storage_unit['type'])
        if endpoint is None:
            LOG.warning('Skipping storage unit %(name)s marked for deletion; '
                        'unknown storage unit type %(type)s.',
                        {'name': storage_unit['name'],
                         'type': storage_unit['type']})
            return

        query = {
            'name': storage_unit['name'],
            'allow_delete_while_mapped': 'true',
        }
        if storage_unit['type'] == 'namespace':
            query['svm'] = self.vserver

        self.send_request(endpoint, 'delete', query=query)

    def create_volume_from_snapshot(self, source, volume):
        """Clone a storage unit, optionally from a named snapshot.

        If source includes a snapshot name, clone from that snapshot.
        Otherwise ONTAP creates the temporary snapshot for the clone.
        """
        destination_name = self._get_backend_storage_unit(volume['name'])
        source_vol_name = self._get_backend_storage_unit(
            source['volume_name']
        )
        clone_source = {
            "storage_unit": {
                "name": source_vol_name,
            },
        }
        if source.get('name'):
            clone_source['snapshot'] = {
                "name": source['name'],
            }
        body = {
            "clone": {
                "is_flexclone": True,
                "source": clone_source,
                "split_initiated": False
            },
            "name": destination_name,
        }
        self.send_request("/storage/storage-units/", 'post', body=body)

    def wait_for_split_to_complete(self, su_uuid, wait_interval=600,
                                   require_split_start=False):
        """Waits for a split job to finish.

        :param su_uuid: Storage unit UUID.
        :param wait_interval: Max wait time in seconds.
        :param require_split_start: If True, require state transition to
                                    split_initiated=True before considering
                                    the split complete. Use this when the
                                    caller has just started a split job.
                                    If False, return immediately when no
                                    split is currently in progress.
        """

        initial_interval = 5
        max_interval = min(30, max(initial_interval, wait_interval // 12))
        elapsed = 0
        split_started = False

        def _next_interval(last_interval, remaining):
            next_interval = (
                initial_interval if last_interval == 0 else
                min(last_interval * 2, max_interval)
            )
            return min(next_interval, remaining)

        poll_interval = 0

        while True:
            query = {
                'fields': 'clone.split_initiated'
            }
            response = self.send_request(f'/storage/storage-units/{su_uuid}',
                                         'get', query=query)
            clone = response.get('clone') or {}
            split_initiated = strutils.bool_from_string(
                clone.get('split_initiated', False))

            LOG.debug('Split status for storage unit %(su_uuid)s - '
                      'started: %(started)s, split_initiated: '
                      '%(split_initiated)s',
                      {'su_uuid': su_uuid,
                       'started': split_started,
                       'split_initiated': split_initiated})

            if not split_started:
                if split_initiated:
                    split_started = True
                elif not require_split_start:
                    return

            elif not split_initiated:
                return

            remaining = wait_interval - elapsed
            if remaining <= 0:
                break

            poll_interval = _next_interval(poll_interval, remaining)
            LOG.debug('Waiting %(interval)s seconds before rechecking split '
                      'status for storage unit %(su_uuid)s.',
                      {'interval': poll_interval, 'su_uuid': su_uuid})
            time.sleep(poll_interval)
            elapsed += poll_interval

        msg = _("Split job for storage unit %(su_uuid)s did not reach the "
                "expected state within %(wait_interval)s seconds. Aborting.")
        msg_args = {'su_uuid': su_uuid, 'wait_interval': wait_interval}
        raise netapp_utils.NetAppDriverException(msg % msg_args)

    def set_config(self, config):
        self.config = config

    def _get_storage_unit_uuid(self, name):
        query = {'name': name, 'fields': 'uuid'}
        response = self.send_request('/storage/storage-units/',
                                     'get', query=query)
        records = response.get('records', [])
        if len(records) != 1:
            msg = _('Could not find storage unit with name %(name)s.')
            msg_args = {'name': name}
            raise netapp_utils.NetAppDriverException(msg % msg_args)
        return records[0]['uuid']

    def _get_backend_storage_unit(self, path):
        """Get the backend storage unit name."""
        paths = path.split("/")
        return paths[- 1].replace("-", "_")

    def get_vserver_aggregates(self):
        """Return list of aggregate names mapped to this SVM.

        Uses the SVM collection REST API (`/svm/svms`) filtered by SVM name
        and extracts the `aggregates` field from the matching record.
        """
        svm_name = self.vserver
        LOG.debug("Getting aggregates for SVM: %s", svm_name)
        query = {
            "name": svm_name,
            "fields": "name,uuid,aggregates",
            "return_timeout": 30,
        }

        try:
            # /api/svm/svms?name=<svm>&fields=name,uuid,aggregates
            resp = self.send_request("/svm/svms", "get", query=query)
        except Exception as e:
            msg = _("Failed to get aggregates for SVM %(svm)s: %(err)s") % {
                "svm": svm_name,
                "err": e,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)

        if not isinstance(resp, dict):
            msg = _("Unexpected response type when getting aggregates for "
                    "SVM %(svm)s: %(rtype)s") % {
                "svm": svm_name,
                "rtype": type(resp),
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)
        LOG.debug("Response for SVM aggregates request: %s", resp)
        records = resp.get("records")
        LOG.debug("SVM records retrieved: %s", records)
        if not records:
            msg = _("Failed to resolve SVM %(svm)s when "
                    "getting aggregates.") % {
                "svm": svm_name,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(data=msg)

        svm_record = records[0]
        aggrs = svm_record.get("aggregates") or []
        aggr_names = [aggr.get("name") for aggr in aggrs if aggr.get("name")]

        LOG.debug("SVM %s mapped aggregates: %s", svm_name, aggr_names)
        return aggr_names

    def get_storage_availability_zones(self):
        """Return list of storage availability zone names (SAZs).

        Calls /api/storage/availability-zones and extracts the *name*
        field from each record.
        """
        query = {
            'fields': 'name',
        }

        try:
            resp = self.send_request(
                '/storage/availability-zones', 'get',
                query=query, enable_tunneling=False,
            )
        except Exception as e:
            msg = _('Failed to get storage availability zones: %s') % e
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        if not isinstance(resp, dict):
            msg = _('Unexpected response type for availability zones: %s') % (
                type(resp),
            )
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        records = resp.get('records') or []
        saz_list = [r.get('name') for r in records if r.get('name')]

        LOG.debug('Retrieved storage availability zones: %s', saz_list)
        return saz_list

    def get_lun_sizes_by_svm(self):
        """"Gets the list of LUNs for an SVM and their sizes"""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name'
        }

        response = self.send_request('/storage/luns/', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        luns = []
        for lun_info in response['records']:
            luns.append({
                'path': lun_info.get('name', ''),
                'size': float(lun_info.get('space', {}).get('size', 0))
            })
        return luns

    def get_namespace_sizes_by_svm(self):
        """Gets the list of namespaces for an SVM and their sizes."""

        query = {
            'svm.name': self.vserver,
            'fields': 'space.size,name',
        }

        response = self.send_request('/storage/namespaces', 'get', query=query)

        num_records = response.get('num_records')
        if not num_records or str(num_records) == '0':
            return []

        namespaces = []
        for ns_info in response.get('records', []):
            size = ns_info.get('space', {}).get('size', 0)
            try:
                size = int(size)
            except (TypeError, ValueError):
                size = 0

            namespaces.append({
                'path': ns_info.get('name', ''),
                'size': size,
            })

        return namespaces

    def get_storage_units_by_svm(self, vserver):
        """Return storage units for the given SVM via REST.

        Each entry is a dict with:
        - 'name': storage unit name
        - 'uuid': storage unit uuid
        - 'provisioned-size': provisioned size in bytes (int), taken from
          'space.size'.
        """
        query = {
            'svm.name': vserver,
            'fields': 'name,uuid,space.size,type',
        }

        try:
            # /api/storage/storage-units?svm.name=<svm>&fields=name,uuid,space.size,type
            resp = self.send_request(
                '/storage/storage-units',
                'get',
                query=query,
            )
        except Exception as e:
            msg = _('Failed to get storage units for SVM %(svm)s: %(err)s') % {
                'svm': vserver,
                'err': e,
            }
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        if not isinstance(resp, dict):
            msg = _('Unexpected response type for storage units: %s') % (
                type(resp),
            )
            LOG.error(msg)
            raise netapp_utils.NetAppDriverException(msg)

        records = resp.get('records') or []
        storage_units = []

        for rec in records:
            space = rec.get('space') or {}
            size = space.get('size') or 0
            try:
                size = int(size)
            except (TypeError, ValueError):
                size = 0

            storage_units.append({
                'name': rec.get('name'),
                'uuid': rec.get('uuid'),
                'provisioned-size': size,
                'type': rec.get('type')
            })

        return storage_units
