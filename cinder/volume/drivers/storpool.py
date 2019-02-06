#    Copyright (c) 2014 - 2017 StorPool
#    All Rights Reserved.
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

"""StorPool block device driver"""

from __future__ import absolute_import

import platform

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils
from oslo_utils import units
import six

from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import driver
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)

storpool = importutils.try_import('storpool')
if storpool:
    from storpool import spapi
    from storpool import spconfig
    from storpool import spopenstack
    from storpool import sptypes


storpool_opts = [
    cfg.StrOpt('storpool_template',
               default=None,
               help='The StorPool template for volumes with no type.'),
    cfg.IntOpt('storpool_replication',
               default=3,
               help='The default StorPool chain replication value.  '
                    'Used when creating a volume with no specified type if '
                    'storpool_template is not set.  Also used for calculating '
                    'the apparent free space reported in the stats.'),
]

CONF = cfg.CONF
CONF.register_opts(storpool_opts)


@interface.volumedriver
class StorPoolDriver(driver.VolumeDriver):
    """The StorPool block device driver.

    Version history:

    .. code-block:: none

        0.1.0   - Initial driver
        0.2.0   - Bring the driver up to date with Kilo and Liberty:
                  - implement volume retyping and migrations
                  - use the driver.*VD ABC metaclasses
                  - bugfix: fall back to the configured StorPool template
        1.0.0   - Imported into OpenStack Liberty with minor fixes
        1.1.0   - Bring the driver up to date with Liberty and Mitaka:
                  - drop the CloneableVD and RetypeVD base classes
                  - enable faster volume copying by specifying
                    sparse_volume_copy=true in the stats report
        1.1.1   - Fix the internal _storpool_client_id() method to
                  not break on an unknown host name or UUID; thus,
                  remove the StorPoolConfigurationMissing exception.
        1.1.2   - Bring the driver up to date with Pike: do not
                  translate the error messages
        1.2.0   - Inherit from VolumeDriver, implement get_pool()
        1.2.1   - Implement interface.volumedriver, add CI_WIKI_NAME,
                  fix the docstring formatting
        1.2.2   - Reintroduce the driver into OpenStack Queens,
                  add ignore_errors to the internal _detach_volume() method

    """

    VERSION = '1.2.1'
    CI_WIKI_NAME = 'StorPool_CI'

    def __init__(self, *args, **kwargs):
        super(StorPoolDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(storpool_opts)
        self._sp_config = None
        self._ourId = None
        self._ourIdInt = None
        self._attach = None

    @staticmethod
    def get_driver_options():
        return storpool_opts

    def _backendException(self, e):
        return exception.VolumeBackendAPIException(data=six.text_type(e))

    def _template_from_volume(self, volume):
        default = self.configuration.storpool_template
        vtype = volume['volume_type']
        if vtype is not None:
            specs = volume_types.get_volume_type_extra_specs(vtype['id'])
            if specs is not None:
                return specs.get('storpool_template', default)
        return default

    def get_pool(self, volume):
        template = self._template_from_volume(volume)
        if template is None:
            return 'default'
        else:
            return 'template_' + template

    def create_volume(self, volume):
        size = int(volume['size']) * units.Gi
        name = self._attach.volumeName(volume['id'])
        template = self._template_from_volume(volume)
        try:
            if template is None:
                self._attach.api().volumeCreate({
                    'name': name,
                    'size': size,
                    'replication': self.configuration.storpool_replication
                })
            else:
                self._attach.api().volumeCreate({
                    'name': name,
                    'size': size,
                    'template': template
                })
        except spapi.ApiError as e:
            raise self._backendException(e)

    def _storpool_client_id(self, connector):
        hostname = connector['host']
        if hostname == self.host or hostname == CONF.host:
            hostname = platform.node()
        try:
            cfg = spconfig.SPConfig(section=hostname)
            return int(cfg['SP_OURID'])
        except KeyError:
            return 65
        except Exception as e:
            raise exception.StorPoolConfigurationInvalid(
                section=hostname, param='SP_OURID', error=e)

    def validate_connector(self, connector):
        return self._storpool_client_id(connector) >= 0

    def initialize_connection(self, volume, connector):
        return {'driver_volume_type': 'storpool',
                'data': {
                    'client_id': self._storpool_client_id(connector),
                    'volume': volume['id'],
                }}

    def terminate_connection(self, volume, connector, **kwargs):
        pass

    def create_snapshot(self, snapshot):
        volname = self._attach.volumeName(snapshot['volume_id'])
        name = self._attach.snapshotName('snap', snapshot['id'])
        try:
            self._attach.api().snapshotCreate(volname, {'name': name})
        except spapi.ApiError as e:
            raise self._backendException(e)

    def create_volume_from_snapshot(self, volume, snapshot):
        size = int(volume['size']) * units.Gi
        volname = self._attach.volumeName(volume['id'])
        name = self._attach.snapshotName('snap', snapshot['id'])
        try:
            self._attach.api().volumeCreate({
                'name': volname,
                'size': size,
                'parent': name
            })
        except spapi.ApiError as e:
            raise self._backendException(e)

    def create_cloned_volume(self, volume, src_vref):
        refname = self._attach.volumeName(src_vref['id'])
        snapname = self._attach.snapshotName('clone', volume['id'])
        try:
            self._attach.api().snapshotCreate(refname, {'name': snapname})
        except spapi.ApiError as e:
            raise self._backendException(e)

        size = int(volume['size']) * units.Gi
        volname = self._attach.volumeName(volume['id'])
        try:
            self._attach.api().volumeCreate({
                'name': volname,
                'size': size,
                'parent': snapname
            })
        except spapi.ApiError as e:
            raise self._backendException(e)
        finally:
            try:
                self._attach.api().snapshotDelete(snapname)
            except spapi.ApiError as e:
                # ARGH!
                LOG.error("Could not delete the temp snapshot %(name)s: "
                          "%(msg)s",
                          {'name': snapname, 'msg': e})

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def delete_volume(self, volume):
        name = self._attach.volumeName(volume['id'])
        try:
            self._attach.api().volumesReassign(
                json=[{"volume": name, "detach": "all"}])
            self._attach.api().volumeDelete(name)
        except spapi.ApiError as e:
            if e.name == 'objectDoesNotExist':
                pass
            else:
                raise self._backendException(e)

    def delete_snapshot(self, snapshot):
        name = self._attach.snapshotName('snap', snapshot['id'])
        try:
            self._attach.api().volumesReassign(
                json=[{"snapshot": name, "detach": "all"}])
            self._attach.api().snapshotDelete(name)
        except spapi.ApiError as e:
            if e.name == 'objectDoesNotExist':
                pass
            else:
                raise self._backendException(e)

    def check_for_setup_error(self):
        if storpool is None:
            msg = _('storpool libraries not found')
            raise exception.VolumeBackendAPIException(data=msg)

        self._attach = spopenstack.AttachDB(log=LOG)
        try:
            self._attach.api()
        except Exception as e:
            LOG.error("StorPoolDriver API initialization failed: %s", e)
            raise

    def get_volume_stats(self, refresh=False):
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        try:
            dl = self._attach.api().disksList()
            templates = self._attach.api().volumeTemplatesList()
        except spapi.ApiError as e:
            raise self._backendException(e)
        total = 0
        used = 0
        free = 0
        agSize = 512 * units.Mi
        for (id, desc) in dl.items():
            if desc.generationLeft != -1:
                continue
            total += desc.agCount * agSize
            used += desc.agAllocated * agSize
            free += desc.agFree * agSize * 4096 / (4096 + 128)

        # Report the free space as if all new volumes will be created
        # with StorPool replication 3; anything else is rare.
        free /= self.configuration.storpool_replication

        space = {
            'total_capacity_gb': total / units.Gi,
            'free_capacity_gb': free / units.Gi,
            'reserved_percentage': 0,
            'QoS_support': False,
        }

        pools = [dict(space, pool_name='default')]

        pools += [dict(space,
                       pool_name='template_' + t.name,
                       storpool_template=t.name
                       ) for t in templates]

        self._stats = {
            'volume_backend_name': self.configuration.safe_get(
                'volume_backend_name') or 'storpool',
            'vendor_name': 'StorPool',
            'driver_version': self.VERSION,
            'storage_protocol': 'storpool',

            'sparse_copy_volume': True,

            'pools': pools
        }

    def _attach_volume(self, context, volume, properties, remote=False):
        if remote:
            return super(StorPoolDriver, self)._attach_volume(
                context, volume, properties, remote=remote)
        req_id = context.request_id
        req = self._attach.get().get(req_id, None)
        if req is None:
            req = {
                'volume': self._attach.volumeName(volume['id']),
                'type': 'cinder-attach',
                'id': context.request_id,
                'rights': 2,
                'volsnap': False,
                'remove_on_detach': True
            }
            self._attach.add(req_id, req)
        name = req['volume']
        self._attach.sync(req_id, None)
        return {'device': {'path': '/dev/storpool/' + name,
                'storpool_attach_req': req_id}}, volume

    def _detach_volume(self, context, attach_info, volume, properties,
                       force=False, remote=False, ignore_errors=False):
        if remote:
            return super(StorPoolDriver, self)._detach_volume(
                context, attach_info, volume, properties,
                force=force, remote=remote, ignore_errors=ignore_errors)
        try:
            req_id = attach_info.get('device', {}).get(
                'storpool_attach_req', context.request_id)
            req = self._attach.get()[req_id]
            name = req['volume']
            self._attach.sync(req_id, name)
            if req.get('remove_on_detach', False):
                self._attach.remove(req_id)
        except BaseException:
            if not ignore_errors:
                raise

    def backup_volume(self, context, backup, backup_service):
        volume = self.db.volume_get(context, backup['volume_id'])
        req_id = context.request_id
        volname = self._attach.volumeName(volume['id'])
        name = self._attach.volsnapName(volume['id'], req_id)
        try:
            self._attach.api().snapshotCreate(volname, {'name': name})
        except spapi.ApiError as e:
            raise self._backendException(e)
        self._attach.add(req_id, {
            'volume': name,
            'type': 'backup',
            'id': req_id,
            'rights': 1,
            'volsnap': True
        })
        try:
            return super(StorPoolDriver, self).backup_volume(
                context, backup, backup_service)
        finally:
            self._attach.remove(req_id)
            try:
                self._attach.api().snapshotDelete(name)
            except spapi.ApiError as e:
                LOG.error(
                    'Could not remove the temp snapshot %(name)s for '
                    '%(vol)s: %(err)s',
                    {'name': name, 'vol': volname, 'err': e})

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        req_id = context.request_id
        volname = self._attach.volumeName(volume['id'])
        name = self._attach.volsnapName(volume['id'], req_id)
        try:
            self._attach.api().snapshotCreate(volname, {'name': name})
        except spapi.ApiError as e:
            raise self._backendException(e)
        self._attach.add(req_id, {
            'volume': name,
            'type': 'copy-from',
            'id': req_id,
            'rights': 1,
            'volsnap': True
        })
        try:
            return super(StorPoolDriver, self).copy_volume_to_image(
                context, volume, image_service, image_meta)
        finally:
            self._attach.remove(req_id)
            try:
                self._attach.api().snapshotDelete(name)
            except spapi.ApiError as e:
                LOG.error(
                    'Could not remove the temp snapshot %(name)s for '
                    '%(vol)s: %(err)s',
                    {'name': name, 'vol': volname, 'err': e})

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        req_id = context.request_id
        name = self._attach.volumeName(volume['id'])
        self._attach.add(req_id, {
            'volume': name,
            'type': 'copy-to',
            'id': req_id,
            'rights': 2
        })
        try:
            return super(StorPoolDriver, self).copy_image_to_volume(
                context, volume, image_service, image_id)
        finally:
            self._attach.remove(req_id)

    def extend_volume(self, volume, new_size):
        size = int(new_size) * units.Gi
        name = self._attach.volumeName(volume['id'])
        try:
            upd = sptypes.VolumeUpdateDesc(size=size)
            self._attach.api().volumeUpdate(name, upd)
        except spapi.ApiError as e:
            raise self._backendException(e)

    def ensure_export(self, context, volume):
        # Already handled by Nova's AttachDB, we hope.
        # Maybe it should move here, but oh well.
        pass

    def retype(self, context, volume, new_type, diff, host):
        update = {}

        if diff['encryption']:
            LOG.error('Retype of encryption type not supported.')
            return False

        templ = self.configuration.storpool_template
        repl = self.configuration.storpool_replication
        if diff['extra_specs']:
            for (k, v) in diff['extra_specs'].items():
                if k == 'volume_backend_name':
                    if v[0] != v[1]:
                        # Retype of a volume backend not supported yet,
                        # the volume needs to be migrated.
                        return False
                elif k == 'storpool_template':
                    if v[0] != v[1]:
                        if v[1] is not None:
                            update['template'] = v[1]
                        elif templ is not None:
                            update['template'] = templ
                        else:
                            update['replication'] = repl
                elif v[0] != v[1]:
                    LOG.error('Retype of extra_specs "%s" not '
                              'supported yet.', k)
                    return False

        if update:
            name = self._attach.volumeName(volume['id'])
            try:
                upd = sptypes.VolumeUpdateDesc(**update)
                self._attach.api().volumeUpdate(name, upd)
            except spapi.ApiError as e:
                raise self._backendException(e)

        return True

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        orig_id = volume['id']
        orig_name = self._attach.volumeName(orig_id)
        temp_id = new_volume['id']
        temp_name = self._attach.volumeName(temp_id)
        vols = {v.name: True for v in self._attach.api().volumesList()}
        if temp_name not in vols:
            LOG.error('StorPool update_migrated_volume(): it seems '
                      'that the StorPool volume "%(tid)s" was not '
                      'created as part of the migration from '
                      '"%(oid)s".', {'tid': temp_id, 'oid': orig_id})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}
        elif orig_name in vols:
            LOG.error('StorPool update_migrated_volume(): both '
                      'the original volume "%(oid)s" and the migrated '
                      'StorPool volume "%(tid)s" seem to exist on '
                      'the StorPool cluster.',
                      {'oid': orig_id, 'tid': temp_id})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}
        else:
            try:
                self._attach.api().volumeUpdate(temp_name,
                                                {'rename': orig_name})
                return {'_name_id': None}
            except spapi.ApiError as e:
                LOG.error('StorPool update_migrated_volume(): '
                          'could not rename %(tname)s to %(oname)s: '
                          '%(err)s',
                          {'tname': temp_name, 'oname': orig_name, 'err': e})
                return {'_name_id': new_volume['_name_id'] or new_volume['id']}
