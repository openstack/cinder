#    Copyright (c) 2014 - 2019 StorPool
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

import platform

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units

from cinder.common import constants
from cinder import context
from cinder import exception
from cinder.i18n import _
from cinder import interface
from cinder.volume import configuration
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
CONF.register_opts(storpool_opts, group=configuration.SHARED_CONF_GROUP)


class StorPoolConfigurationInvalid(exception.CinderException):
    message = _("Invalid parameter %(param)s in the %(section)s section "
                "of the /etc/storpool.conf file: %(error)s")


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
        1.2.3   - Advertise some more driver capabilities.
        2.0.0   - Implement revert_to_snapshot().
    """

    VERSION = '2.0.0'
    CI_WIKI_NAME = 'StorPool_distributed_storage_CI'

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
        return exception.VolumeBackendAPIException(data=str(e))

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
            raise StorPoolConfigurationInvalid(
                section=hostname, param='SP_OURID', error=e)

    def validate_connector(self, connector):
        return self._storpool_client_id(connector) >= 0

    def initialize_connection(self, volume, connector):
        return {'driver_volume_type': 'storpool',
                'data': {
                    'client_id': self._storpool_client_id(connector),
                    'volume': volume['id'],
                    'access_mode': 'rw',
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
        size = int(volume['size']) * units.Gi
        volname = self._attach.volumeName(volume['id'])

        src_volume = self.db.volume_get(
            context.get_admin_context(),
            src_vref['id'],
        )
        src_template = self._template_from_volume(src_volume)

        template = self._template_from_volume(volume)
        LOG.debug('clone volume id %(vol_id)r template %(template)r', {
            'vol_id': volume['id'],
            'template': template,
        })
        if template == src_template:
            LOG.info('Using baseOn to clone a volume into the same template')
            try:
                self._attach.api().volumeCreate({
                    'name': volname,
                    'size': size,
                    'baseOn': refname,
                })
            except spapi.ApiError as e:
                raise self._backendException(e)

            return None

        snapname = self._attach.snapshotName('clone', volume['id'])
        LOG.info(
            'A transient snapshot for a %(src)s -> %(dst)s template change',
            {'src': src_template, 'dst': template})
        try:
            self._attach.api().snapshotCreate(refname, {'name': snapname})
        except spapi.ApiError as e:
            if e.name != 'objectExists':
                raise self._backendException(e)

        try:
            try:
                self._attach.api().snapshotUpdate(
                    snapname,
                    {'template': template},
                )
            except spapi.ApiError as e:
                raise self._backendException(e)

            try:
                self._attach.api().volumeCreate({
                    'name': volname,
                    'size': size,
                    'parent': snapname
                })
            except spapi.ApiError as e:
                raise self._backendException(e)

            try:
                self._attach.api().snapshotUpdate(
                    snapname,
                    {'tags': {'transient': '1.0'}},
                )
            except spapi.ApiError as e:
                raise self._backendException(e)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    LOG.warning(
                        'Something went wrong, removing the transient snapshot'
                    )
                    self._attach.api().snapshotDelete(snapname)
                except spapi.ApiError as e:
                    LOG.error(
                        'Could not delete the %(name)s snapshot: %(err)s',
                        {'name': snapname, 'err': str(e)}
                    )

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
            'multiattach': True,
            'QoS_support': False,
            'thick_provisioning_support': False,
            'thin_provisioning_support': True,
        }

        pools = [dict(space, pool_name='default')]

        pools += [dict(space,
                       pool_name='template_' + t.name,
                       storpool_template=t.name
                       ) for t in templates]

        self._stats = {
            # Basic driver properties
            'volume_backend_name': self.configuration.safe_get(
                'volume_backend_name') or 'storpool',
            'vendor_name': 'StorPool',
            'driver_version': self.VERSION,
            'storage_protocol': constants.STORPOOL,
            # Driver capabilities
            'clone_across_pools': True,
            'sparse_copy_volume': True,
            # The actual pools data
            'pools': pools
        }

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
            # Check for the StorPool extra specs. We intentionally ignore any
            # other extra_specs because the cinder scheduler should not even
            # call us if there's a serious mismatch between the volume types.
            if diff['extra_specs'].get('volume_backend_name'):
                v = diff['extra_specs'].get('volume_backend_name')
                if v[0] != v[1]:
                    # Retype of a volume backend not supported yet,
                    # the volume needs to be migrated.
                    return False
            if diff['extra_specs'].get('storpool_template'):
                v = diff['extra_specs'].get('storpool_template')
                if v[0] != v[1]:
                    if v[1] is not None:
                        update['template'] = v[1]
                    elif templ is not None:
                        update['template'] = templ
                    else:
                        update['replication'] = repl

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

        if orig_name in vols:
            LOG.debug('StorPool update_migrated_volume(): both '
                      'the original volume "%(oid)s" and the migrated '
                      'StorPool volume "%(tid)s" seem to exist on '
                      'the StorPool cluster.',
                      {'oid': orig_id, 'tid': temp_id})
            int_name = temp_name + '--temp--mig'
            LOG.debug('Trying to swap volume names, intermediate "%(int)s"',
                      {'int': int_name})
            try:
                LOG.debug('- rename "%(orig)s" to "%(int)s"',
                          {'orig': orig_name, 'int': int_name})
                self._attach.api().volumeUpdate(orig_name,
                                                {'rename': int_name})

                LOG.debug('- rename "%(temp)s" to "%(orig)s"',
                          {'temp': temp_name, 'orig': orig_name})
                self._attach.api().volumeUpdate(temp_name,
                                                {'rename': orig_name})

                LOG.debug('- rename "%(int)s" to "%(temp)s"',
                          {'int': int_name, 'temp': temp_name})
                self._attach.api().volumeUpdate(int_name,
                                                {'rename': temp_name})
                return {'_name_id': None}
            except spapi.ApiError as e:
                LOG.error('StorPool update_migrated_volume(): '
                          'could not rename a volume: '
                          '%(err)s',
                          {'err': e})
                return {'_name_id': new_volume['_name_id'] or new_volume['id']}

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

    def revert_to_snapshot(self, context, volume, snapshot):
        volname = self._attach.volumeName(volume['id'])
        snapname = self._attach.snapshotName('snap', snapshot['id'])
        try:
            rev = sptypes.VolumeRevertDesc(toSnapshot=snapname)
            self._attach.api().volumeRevert(volname, rev)
        except spapi.ApiError as e:
            LOG.error('StorPool revert_to_snapshot(): could not revert '
                      'the %(vol_id)s volume to the %(snap_id)s snapshot: '
                      '%(err)s',
                      {'vol_id': volume['id'],
                       'snap_id': snapshot['id'],
                       'err': e})
            raise self._backendException(e)
