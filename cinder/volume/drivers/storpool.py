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

from os_brick.initiator import storpool_utils
from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import excutils
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
        2.1.0   - Use the new API client in os-brick to communicate with the
                  StorPool API instead of packages `storpool` and
                  `storpool.spopenstack`

    """

    VERSION = '2.1.0'
    CI_WIKI_NAME = 'StorPool_distributed_storage_CI'

    def __init__(self, *args, **kwargs):
        super(StorPoolDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(storpool_opts)
        self._sp_config = None
        self._ourId = None
        self._ourIdInt = None
        self._sp_api = None
        self._volume_prefix = None

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
        name = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])
        template = self._template_from_volume(volume)

        create_request = {'name': name, 'size': size}
        if template is not None:
            create_request['template'] = template
        else:
            create_request['replication'] = \
                self.configuration.storpool_replication

        try:
            self._sp_api.volume_create(create_request)
        except storpool_utils.StorPoolAPIError as e:
            raise self._backendException(e)

    def _storpool_client_id(self, connector):
        hostname = connector['host']
        if hostname == self.host or hostname == CONF.host:
            hostname = platform.node()
        try:
            cfg = storpool_utils.get_conf(section=hostname)
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
        volname = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, snapshot['volume_id'])
        name = storpool_utils.os_to_sp_snapshot_name(
            self._volume_prefix, 'snap', snapshot['id'])
        try:
            self._sp_api.snapshot_create(volname, {'name': name})
        except storpool_utils.StorPoolAPIError as e:
            raise self._backendException(e)

    def create_volume_from_snapshot(self, volume, snapshot):
        size = int(volume['size']) * units.Gi
        volname = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])
        name = storpool_utils.os_to_sp_snapshot_name(
            self._volume_prefix, 'snap', snapshot['id'])
        try:
            self._sp_api.volume_create({
                'name': volname,
                'size': size,
                'parent': name
            })
        except storpool_utils.StorPoolAPIError as e:
            raise self._backendException(e)

    def create_cloned_volume(self, volume, src_vref):
        refname = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, src_vref['id'])
        size = int(volume['size']) * units.Gi
        volname = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])

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
                self._sp_api.volume_create({
                    'name': volname,
                    'size': size,
                    'baseOn': refname,
                })
            except storpool_utils.StorPoolAPIError as e:
                raise self._backendException(e)

            return None

        snapname = storpool_utils.os_to_sp_snapshot_name(
            self._volume_prefix, 'clone', volume['id'])
        LOG.info(
            'A transient snapshot for a %(src)s -> %(dst)s template change',
            {'src': src_template, 'dst': template})
        try:
            self._sp_api.snapshot_create(refname, {'name': snapname})
        except storpool_utils.StorPoolAPIError as e:
            if e.name != 'objectExists':
                raise self._backendException(e)

        try:
            try:
                self._sp_api.snapshot_update(
                    snapname,
                    {'template': template},
                )
            except storpool_utils.StorPoolAPIError as e:
                raise self._backendException(e)

            try:
                self._sp_api.volume_create({
                    'name': volname,
                    'size': size,
                    'parent': snapname
                })
            except storpool_utils.StorPoolAPIError as e:
                raise self._backendException(e)

            try:
                self._sp_api.snapshot_update(
                    snapname,
                    {'tags': {'transient': '1.0'}},
                )
            except storpool_utils.StorPoolAPIError as e:
                raise self._backendException(e)
        except Exception:
            with excutils.save_and_reraise_exception():
                try:
                    LOG.warning(
                        'Something went wrong, removing the transient snapshot'
                    )
                    self._sp_api.snapshot_delete(snapname)
                except storpool_utils.StorPoolAPIError as e:
                    LOG.error(
                        'Could not delete the %(name)s snapshot: %(err)s',
                        {'name': snapname, 'err': str(e)}
                    )

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def delete_volume(self, volume):
        name = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])
        try:
            self._sp_api.volumes_reassign([{"volume": name, "detach": "all"}])
            self._sp_api.volume_delete(name)
        except storpool_utils.StorPoolAPIError as e:
            if e.name == 'objectDoesNotExist':
                pass
            else:
                raise self._backendException(e)

    def delete_snapshot(self, snapshot):
        name = storpool_utils.os_to_sp_snapshot_name(
            self._volume_prefix, 'snap', snapshot['id'])
        try:
            self._sp_api.volumes_reassign(
                [{"snapshot": name, "detach": "all"}])
            self._sp_api.snapshot_delete(name)
        except storpool_utils.StorPoolAPIError as e:
            if e.name == 'objectDoesNotExist':
                pass
            else:
                raise self._backendException(e)

    def check_for_setup_error(self):
        try:
            self._sp_config = storpool_utils.get_conf()
            self._sp_api = storpool_utils.StorPoolAPI(
                self._sp_config["SP_API_HTTP_HOST"],
                self._sp_config["SP_API_HTTP_PORT"],
                self._sp_config["SP_AUTH_TOKEN"])
            self._volume_prefix = self._sp_config.get(
                "SP_OPENSTACK_VOLUME_PREFIX", "os")
        except Exception as e:
            LOG.error("StorPoolDriver API initialization failed: %s", e)
            raise

    def _update_volume_stats(self):
        try:
            dl = self._sp_api.disks_list()
            templates = self._sp_api.volume_templates_list()
        except storpool_utils.StorPoolAPIError as e:
            raise self._backendException(e)
        total = 0
        used = 0
        free = 0
        agSize = 512 * units.Mi
        for (id, desc) in dl.items():
            if desc['generationLeft'] != -1:
                continue
            total += desc['agCount'] * agSize
            used += desc['agAllocated'] * agSize
            free += desc['agFree'] * agSize * 4096 / (4096 + 128)

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
                       pool_name='template_' + t['name'],
                       storpool_template=t['name']
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
        name = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])
        try:
            self._sp_api.volume_update(name, {'size': size})
        except storpool_utils.StorPoolAPIError as e:
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
            name = storpool_utils.os_to_sp_volume_name(
                self._volume_prefix, volume['id'])
            try:
                self._sp_api.volume_update(name, **update)
            except storpool_utils.StorPoolAPIError as e:
                raise self._backendException(e)

        return True

    def update_migrated_volume(self, context, volume, new_volume,
                               original_volume_status):
        orig_id = volume['id']
        orig_name = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, orig_id)
        temp_id = new_volume['id']
        temp_name = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, temp_id)
        vols = {v['name']: True for v in self._sp_api.volumes_list()}
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
                self._sp_api.volume_update(orig_name, {'rename': int_name})

                LOG.debug('- rename "%(temp)s" to "%(orig)s"',
                          {'temp': temp_name, 'orig': orig_name})
                self._sp_api.volume_update(temp_name, {'rename': orig_name})

                LOG.debug('- rename "%(int)s" to "%(temp)s"',
                          {'int': int_name, 'temp': temp_name})
                self._sp_api.volume_update(int_name, {'rename': temp_name})
                return {'_name_id': None}
            except storpool_utils.StorPoolAPIError as e:
                LOG.error('StorPool update_migrated_volume(): '
                          'could not rename a volume: '
                          '%(err)s',
                          {'err': e})
                return {'_name_id': new_volume['_name_id'] or new_volume['id']}

        try:
            self._sp_api.volume_update(temp_name, {'rename': orig_name})
            return {'_name_id': None}
        except storpool_utils.StorPoolAPIError as e:
            LOG.error('StorPool update_migrated_volume(): '
                      'could not rename %(tname)s to %(oname)s: '
                      '%(err)s',
                      {'tname': temp_name, 'oname': orig_name, 'err': e})
            return {'_name_id': new_volume['_name_id'] or new_volume['id']}

    def revert_to_snapshot(self, context, volume, snapshot):
        volname = storpool_utils.os_to_sp_volume_name(
            self._volume_prefix, volume['id'])
        snapname = storpool_utils.os_to_sp_snapshot_name(
            self._volume_prefix, 'snap', snapshot['id'])
        try:
            self._sp_api.volume_revert(volname, {'toSnapshot': snapname})
        except storpool_utils.StorPoolAPIError as e:
            LOG.error('StorPool revert_to_snapshot(): could not revert '
                      'the %(vol_id)s volume to the %(snap_id)s snapshot: '
                      '%(err)s',
                      {'vol_id': volume['id'],
                       'snap_id': snapshot['id'],
                       'err': e})
            raise self._backendException(e)
