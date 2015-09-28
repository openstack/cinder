# Copyright (c) 2014, 2015, Oracle and/or its affiliates. All rights reserved.
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
ZFS Storage Appliance Cinder Volume Driver
"""
import ast
import base64
import math

from oslo_config import cfg
from oslo_log import log
from oslo_utils import units
import six

from cinder import exception
from cinder import utils
from cinder.i18n import _, _LE, _LI, _LW
from cinder.volume import driver
from cinder.volume.drivers.san import san
from cinder.volume.drivers.zfssa import zfssarest
from cinder.volume import volume_types

import taskflow.engines
from taskflow.patterns import linear_flow as lf
from taskflow import task

CONF = cfg.CONF
LOG = log.getLogger(__name__)

ZFSSA_OPTS = [
    cfg.StrOpt('zfssa_pool',
               help='Storage pool name.'),
    cfg.StrOpt('zfssa_project',
               help='Project name.'),
    cfg.StrOpt('zfssa_lun_volblocksize', default='8k',
               choices=['512', '1k', '2k', '4k', '8k', '16k', '32k', '64k',
                        '128k'],
               help='Block size.'),
    cfg.BoolOpt('zfssa_lun_sparse', default=False,
                help='Flag to enable sparse (thin-provisioned): True, False.'),
    cfg.StrOpt('zfssa_lun_compression', default='off',
               choices=['off', 'lzjb', 'gzip-2', 'gzip', 'gzip-9'],
               help='Data compression.'),
    cfg.StrOpt('zfssa_lun_logbias', default='latency',
               choices=['latency', 'throughput'],
               help='Synchronous write bias.'),
    cfg.StrOpt('zfssa_initiator_group', default='',
               help='iSCSI initiator group.'),
    cfg.StrOpt('zfssa_initiator', default='',
               help='iSCSI initiator IQNs. (comma separated)'),
    cfg.StrOpt('zfssa_initiator_user', default='',
               help='iSCSI initiator CHAP user (name).'),
    cfg.StrOpt('zfssa_initiator_password', default='',
               help='Secret of the iSCSI initiator CHAP user.', secret=True),
    cfg.StrOpt('zfssa_initiator_config', default='',
               help='iSCSI initiators configuration.'),
    cfg.StrOpt('zfssa_target_group', default='tgt-grp',
               help='iSCSI target group name.'),
    cfg.StrOpt('zfssa_target_user', default='',
               help='iSCSI target CHAP user (name).'),
    cfg.StrOpt('zfssa_target_password', default='', secret=True,
               help='Secret of the iSCSI target CHAP user.'),
    cfg.StrOpt('zfssa_target_portal',
               help='iSCSI target portal (Data-IP:Port, w.x.y.z:3260).'),
    cfg.StrOpt('zfssa_target_interfaces',
               help='Network interfaces of iSCSI targets. (comma separated)'),
    cfg.IntOpt('zfssa_rest_timeout',
               help='REST connection timeout. (seconds)'),
    cfg.StrOpt('zfssa_replication_ip', default='',
               help='IP address used for replication data. (maybe the same as '
                    'data ip)'),
    cfg.BoolOpt('zfssa_enable_local_cache', default=True,
                help='Flag to enable local caching: True, False.'),
    cfg.StrOpt('zfssa_cache_project', default='os-cinder-cache',
               help='Name of ZFSSA project where cache volumes are stored.')

]

CONF.register_opts(ZFSSA_OPTS)

ZFSSA_LUN_SPECS = {
    'zfssa:volblocksize',
    'zfssa:sparse',
    'zfssa:compression',
    'zfssa:logbias',
}


def factory_zfssa():
    return zfssarest.ZFSSAApi()


class ZFSSAISCSIDriver(driver.ISCSIDriver):
    """ZFSSA Cinder iSCSI volume driver.

    Version history:
    1.0.1:
        Backend enabled volume migration.
        Local cache feature.
    """
    VERSION = '1.0.1'
    protocol = 'iSCSI'

    def __init__(self, *args, **kwargs):
        super(ZFSSAISCSIDriver, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(ZFSSA_OPTS)
        self.configuration.append_config_values(san.san_opts)
        self.zfssa = None
        self.tgt_zfssa = None
        self._stats = None
        self.tgtiqn = None

    def _get_target_alias(self):
        """return target alias."""
        return self.configuration.zfssa_target_group

    def do_setup(self, context):
        """Setup - create multiple elements.

        Project, initiators, initiatorgroup, target and targetgroup.
        """
        lcfg = self.configuration
        LOG.info(_LI('Connecting to host: %s.'), lcfg.san_ip)
        self.zfssa = factory_zfssa()
        self.tgt_zfssa = factory_zfssa()
        self.zfssa.set_host(lcfg.san_ip, timeout=lcfg.zfssa_rest_timeout)
        auth_str = base64.encodestring('%s:%s' %
                                       (lcfg.san_login,
                                        lcfg.san_password))[:-1]
        self.zfssa.login(auth_str)

        self.zfssa.create_project(lcfg.zfssa_pool, lcfg.zfssa_project,
                                  compression=lcfg.zfssa_lun_compression,
                                  logbias=lcfg.zfssa_lun_logbias)

        if lcfg.zfssa_enable_local_cache:
            self.zfssa.create_project(lcfg.zfssa_pool,
                                      lcfg.zfssa_cache_project,
                                      compression=lcfg.zfssa_lun_compression,
                                      logbias=lcfg.zfssa_lun_logbias)
            schemas = [
                {'property': 'image_id',
                 'description': 'OpenStack image ID',
                 'type': 'String'},
                {'property': 'updated_at',
                 'description': 'Most recent updated time of image',
                 'type': 'String'}]
            self.zfssa.create_schemas(schemas)

        if (lcfg.zfssa_initiator_config != ''):
            initiator_config = ast.literal_eval(lcfg.zfssa_initiator_config)
            for initiator_group in initiator_config:
                zfssa_initiator_group = initiator_group
                for zfssa_initiator in initiator_config[zfssa_initiator_group]:
                    self.zfssa.create_initiator(zfssa_initiator['iqn'],
                                                zfssa_initiator_group + '-' +
                                                zfssa_initiator['iqn'],
                                                chapuser=
                                                zfssa_initiator['user'],
                                                chapsecret=
                                                zfssa_initiator['password'])
                    if (zfssa_initiator_group != 'default'):
                        self.zfssa.add_to_initiatorgroup(
                            zfssa_initiator['iqn'],
                            zfssa_initiator_group)
        else:
            LOG.warning(_LW('zfssa_initiator_config not found. '
                            'Using deprecated configuration options.'))
            if (lcfg.zfssa_initiator != '' and
                (lcfg.zfssa_initiator_group == '' or
                 lcfg.zfssa_initiator_group == 'default')):
                LOG.warning(_LW('zfssa_initiator: %(ini)s'
                                ' wont be used on '
                                'zfssa_initiator_group= %(inigrp)s.'),
                            {'ini': lcfg.zfssa_initiator,
                             'inigrp': lcfg.zfssa_initiator_group})

            # Setup initiator and initiator group
            if (lcfg.zfssa_initiator != '' and
               lcfg.zfssa_initiator_group != '' and
               lcfg.zfssa_initiator_group != 'default'):
                for initiator in lcfg.zfssa_initiator.split(','):
                    self.zfssa.create_initiator(
                        initiator, lcfg.zfssa_initiator_group + '-' +
                        initiator, chapuser=lcfg.zfssa_initiator_user,
                        chapsecret=lcfg.zfssa_initiator_password)
                    self.zfssa.add_to_initiatorgroup(
                        initiator, lcfg.zfssa_initiator_group)

        # Parse interfaces
        interfaces = []
        for interface in lcfg.zfssa_target_interfaces.split(','):
            if interface == '':
                continue
            interfaces.append(interface)

        # Setup target and target group
        iqn = self.zfssa.create_target(
            self._get_target_alias(),
            interfaces,
            tchapuser=lcfg.zfssa_target_user,
            tchapsecret=lcfg.zfssa_target_password)

        self.zfssa.add_to_targetgroup(iqn, lcfg.zfssa_target_group)

    def check_for_setup_error(self):
        """Check that driver can login.

        Check also pool, project, initiators, initiatorgroup, target and
        targetgroup.
        """
        lcfg = self.configuration

        self.zfssa.verify_pool(lcfg.zfssa_pool)
        self.zfssa.verify_project(lcfg.zfssa_pool, lcfg.zfssa_project)

        if (lcfg.zfssa_initiator_config != ''):
            initiator_config = ast.literal_eval(lcfg.zfssa_initiator_config)
            for initiator_group in initiator_config:
                zfssa_initiator_group = initiator_group
                for zfssa_initiator in initiator_config[zfssa_initiator_group]:
                    self.zfssa.verify_initiator(zfssa_initiator['iqn'])
        else:
            if (lcfg.zfssa_initiator != '' and
               lcfg.zfssa_initiator_group != '' and
               lcfg.zfssa_initiator_group != 'default'):
                for initiator in lcfg.zfssa_initiator.split(','):
                    self.zfssa.verify_initiator(initiator)

            self.zfssa.verify_target(self._get_target_alias())

    def _get_provider_info(self, volume, lun=None):
        """Return provider information."""
        lcfg = self.configuration
        project = lcfg.zfssa_project
        if ((lcfg.zfssa_enable_local_cache is True) and
                (volume['name'].startswith('os-cache-vol-'))):
            project = lcfg.zfssa_cache_project

        if lun is None:
            lun = self.zfssa.get_lun(lcfg.zfssa_pool,
                                     project,
                                     volume['name'])

        if isinstance(lun['number'], list):
            lun['number'] = lun['number'][0]

        if self.tgtiqn is None:
            self.tgtiqn = self.zfssa.get_target(self._get_target_alias())

        loc = "%s %s %s" % (lcfg.zfssa_target_portal, self.tgtiqn,
                            lun['number'])
        LOG.debug('_get_provider_info: provider_location: %s', loc)
        provider = {'provider_location': loc}
        if lcfg.zfssa_target_user != '' and lcfg.zfssa_target_password != '':
            provider['provider_auth'] = ('CHAP %s %s' %
                                         (lcfg.zfssa_target_user,
                                          lcfg.zfssa_target_password))

        return provider

    def create_volume(self, volume):
        """Create a volume on ZFSSA."""
        LOG.debug('zfssa.create_volume: volume=' + volume['name'])
        lcfg = self.configuration
        volsize = str(volume['size']) + 'g'
        specs = self._get_voltype_specs(volume)
        self.zfssa.create_lun(lcfg.zfssa_pool,
                              lcfg.zfssa_project,
                              volume['name'],
                              volsize,
                              lcfg.zfssa_target_group,
                              specs)

    def delete_volume(self, volume):
        """Deletes a volume with the given volume['name']."""
        LOG.debug('zfssa.delete_volume: name=%s', volume['name'])
        lcfg = self.configuration

        try:
            lun2del = self.zfssa.get_lun(lcfg.zfssa_pool,
                                         lcfg.zfssa_project,
                                         volume['name'])
        except exception.VolumeBackendAPIException as ex:
            # NOTE(jdg): This will log an error and continue
            # if for some reason the volume no longer exists
            # on the backend
            if 'Error Getting Volume' in ex.message:
                LOG.error(_LE("Volume ID %s was not found on "
                              "the zfssa device while attempting "
                              "delete_volume operation."), volume['id'])
                return

        # Delete clone temp snapshot. see create_cloned_volume()
        if 'origin' in lun2del and 'id' in volume:
            if lun2del['nodestroy']:
                self.zfssa.set_lun_props(lcfg.zfssa_pool,
                                         lcfg.zfssa_project,
                                         volume['name'],
                                         nodestroy=False)

            tmpsnap = 'tmp-snapshot-%s' % volume['id']
            if lun2del['origin']['snapshot'] == tmpsnap:
                self.zfssa.delete_snapshot(lcfg.zfssa_pool,
                                           lcfg.zfssa_project,
                                           lun2del['origin']['share'],
                                           lun2del['origin']['snapshot'])
                return

        self.zfssa.delete_lun(pool=lcfg.zfssa_pool,
                              project=lcfg.zfssa_project,
                              lun=volume['name'])

        if ('origin' in lun2del and
                lun2del['origin']['project'] == lcfg.zfssa_cache_project):
            self._check_origin(lun2del, volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot of a volume.

        Snapshot name: snapshot['name']
        Volume name: snapshot['volume_name']
        """
        LOG.debug('zfssa.create_snapshot: snapshot=%s', snapshot['name'])
        lcfg = self.configuration
        self.zfssa.create_snapshot(lcfg.zfssa_pool,
                                   lcfg.zfssa_project,
                                   snapshot['volume_name'],
                                   snapshot['name'])

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        LOG.debug('zfssa.delete_snapshot: snapshot=%s', snapshot['name'])
        lcfg = self.configuration
        numclones = self.zfssa.num_clones(lcfg.zfssa_pool,
                                          lcfg.zfssa_project,
                                          snapshot['volume_name'],
                                          snapshot['name'])
        if numclones > 0:
            LOG.error(_LE('Snapshot %s: has clones'), snapshot['name'])
            raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])

        self.zfssa.delete_snapshot(lcfg.zfssa_pool,
                                   lcfg.zfssa_project,
                                   snapshot['volume_name'],
                                   snapshot['name'])

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot - clone a snapshot."""
        LOG.debug('zfssa.create_volume_from_snapshot: volume=%s',
                  volume['name'])
        LOG.debug('zfssa.create_volume_from_snapshot: snapshot=%s',
                  snapshot['name'])
        if not self._verify_clone_size(snapshot, volume['size'] * units.Gi):
            exception_msg = (_('Error verifying clone size on '
                               'Volume clone: %(clone)s '
                               'Size: %(size)d on'
                               'Snapshot: %(snapshot)s')
                             % {'clone': volume['name'],
                                'size': volume['size'],
                                'snapshot': snapshot['name']})
            LOG.error(exception_msg)
            raise exception.InvalidInput(reason=exception_msg)

        lcfg = self.configuration
        self.zfssa.clone_snapshot(lcfg.zfssa_pool,
                                  lcfg.zfssa_project,
                                  snapshot['volume_name'],
                                  snapshot['name'],
                                  lcfg.zfssa_project,
                                  volume['name'])

    def _update_volume_status(self):
        """Retrieve status info from volume group."""
        LOG.debug("Updating volume status")
        self._stats = None
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Oracle'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = self.protocol

        lcfg = self.configuration
        (avail, total) = self.zfssa.get_project_stats(lcfg.zfssa_pool,
                                                      lcfg.zfssa_project)
        if avail is None or total is None:
            return

        host = lcfg.san_ip
        pool = lcfg.zfssa_pool
        project = lcfg.zfssa_project
        auth_str = base64.encodestring('%s:%s' %
                                       (lcfg.san_login,
                                        lcfg.san_password))[:-1]
        zfssa_tgt_group = lcfg.zfssa_target_group
        repl_ip = lcfg.zfssa_replication_ip

        data['location_info'] = "%s:%s:%s:%s:%s:%s" % (host, auth_str, pool,
                                                       project,
                                                       zfssa_tgt_group,
                                                       repl_ip)

        data['total_capacity_gb'] = int(total) / units.Gi
        data['free_capacity_gb'] = int(avail) / units.Gi
        data['reserved_percentage'] = 0
        data['QoS_support'] = False
        self._stats = data

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_status()
        return self._stats

    def create_export(self, context, volume, connector):
        pass

    def remove_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def extend_volume(self, volume, new_size):
        """Driver entry point to extent volume size."""
        LOG.debug('extend_volume: volume name: %s', volume['name'])
        lcfg = self.configuration
        self.zfssa.set_lun_props(lcfg.zfssa_pool,
                                 lcfg.zfssa_project,
                                 volume['name'],
                                 volsize=new_size * units.Gi)

    def create_cloned_volume(self, volume, src_vref):
        """Create a clone of the specified volume."""
        zfssa_snapshot = {'volume_name': src_vref['name'],
                          'name': 'tmp-snapshot-%s' % volume['id']}
        self.create_snapshot(zfssa_snapshot)
        try:
            self.create_volume_from_snapshot(volume, zfssa_snapshot)
        except exception.VolumeBackendAPIException:
            LOG.error(_LE('Clone Volume:'
                          '%(volume)s failed from source volume:'
                          '%(src_vref)s'),
                      {'volume': volume['name'],
                       'src_vref': src_vref['name']})
            # Cleanup snapshot
            self.delete_snapshot(zfssa_snapshot)

    def clone_image(self, context, volume,
                    image_location, image_meta,
                    image_service):
        """Create a volume efficiently from an existing image.

        Verify the image ID being used:

        (1) If there is no existing cache volume, create one and transfer
        image data to it. Take a snapshot.

        (2) If a cache volume already exists, verify if it is either alternated
        or updated. If so try to remove it, raise exception if removal fails.
        Create a new cache volume as in (1).

        Clone a volume from the cache volume and returns it to Cinder.
        """
        LOG.debug('Cloning image %(image)s to volume %(volume)s',
                  {'image': image_meta['id'], 'volume': volume['name']})
        lcfg = self.configuration
        if not lcfg.zfssa_enable_local_cache:
            return None, False

        # virtual_size is the image's actual size when stored in a volume
        # virtual_size is expected to be updated manually through glance
        try:
            virtual_size = int(image_meta['properties'].get('virtual_size'))
        except Exception:
            LOG.error(_LE('virtual_size property is not set for the image.'))
            return None, False
        cachevol_size = int(math.ceil(float(virtual_size) / units.Gi))
        if cachevol_size > volume['size']:
            exception_msg = (_LE('Image size %(img_size)dGB is larger '
                                 'than volume size %(vol_size)dGB.'),
                             {'img_size': cachevol_size,
                              'vol_size': volume['size']})
            LOG.error(exception_msg)
            return None, False

        specs = self._get_voltype_specs(volume)
        cachevol_props = {'size': cachevol_size}

        try:
            cache_vol, cache_snap = self._verify_cache_volume(context,
                                                              image_meta,
                                                              image_service,
                                                              specs,
                                                              cachevol_props)
            # A cache volume and a snapshot should be ready by now
            # Create a clone from the cache volume
            self.zfssa.clone_snapshot(lcfg.zfssa_pool,
                                      lcfg.zfssa_cache_project,
                                      cache_vol,
                                      cache_snap,
                                      lcfg.zfssa_project,
                                      volume['name'])
            if cachevol_size < volume['size']:
                self.extend_volume(volume, volume['size'])
        except exception.VolumeBackendAPIException as exc:
            exception_msg = (_LE('Cannot clone image %(image)s to '
                                 'volume %(volume)s. Error: %(error)s.'),
                             {'volume': volume['name'],
                              'image': image_meta['id'],
                              'error': exc.message})
            LOG.error(exception_msg)
            return None, False

        return None, True

    @utils.synchronized('zfssaiscsi', external=True)
    def _verify_cache_volume(self, context, img_meta,
                             img_service, specs, cachevol_props):
        """Verify if we have a cache volume that we want.

        If we don't, create one.
        If we do, check if it's been updated:
          * If so, delete it and recreate a new volume
          * If not, we are good.

        If it's out of date, delete it and create a new one.
        After the function returns, there should be a cache volume available,
        ready for cloning.

        There needs to be a file lock here, otherwise subsequent clone_image
        requests will fail if the first request is still pending.
        """
        lcfg = self.configuration
        cachevol_name = 'os-cache-vol-%s' % img_meta['id']
        cachesnap_name = 'image-%s' % img_meta['id']
        cachevol_meta = {
            'cache_name': cachevol_name,
            'snap_name': cachesnap_name,
        }
        cachevol_props.update(cachevol_meta)
        cache_vol, cache_snap = None, None
        updated_at = six.text_type(img_meta['updated_at'].isoformat())
        LOG.debug('Verifying cache volume %s:', cachevol_name)

        try:
            cache_vol = self.zfssa.get_lun(lcfg.zfssa_pool,
                                           lcfg.zfssa_cache_project,
                                           cachevol_name)
            cache_snap = self.zfssa.get_lun_snapshot(lcfg.zfssa_pool,
                                                     lcfg.zfssa_cache_project,
                                                     cachevol_name,
                                                     cachesnap_name)
        except exception.VolumeNotFound:
            # There is no existing cache volume, create one:
            return self._create_cache_volume(context,
                                             img_meta,
                                             img_service,
                                             specs,
                                             cachevol_props)
        except exception.SnapshotNotFound:
            exception_msg = (_('Cache volume %(cache_vol)s'
                               'does not have snapshot %(cache_snap)s.'),
                             {'cache_vol': cachevol_name,
                              'cache_snap': cachesnap_name})
            LOG.error(exception_msg)
            raise exception.VolumeBackendAPIException(data=exception_msg)

        # A cache volume does exist, check if it's updated:
        if ((cache_vol['updated_at'] != updated_at) or
                (cache_vol['image_id'] != img_meta['id'])):
            # The cache volume is updated, but has clones:
            if cache_snap['numclones'] > 0:
                exception_msg = (_('Cannot delete '
                                   'cache volume: %(cachevol_name)s. '
                                   'It was updated at %(updated_at)s '
                                   'and currently has %(numclones)s '
                                   'volume instances.'),
                                 {'cachevol_name': cachevol_name,
                                  'updated_at': updated_at,
                                  'numclones': cache_snap['numclones']})
                LOG.error(exception_msg)
                raise exception.VolumeBackendAPIException(data=exception_msg)

            # The cache volume is updated, but has no clone, so we delete it
            # and re-create a new one:
            self.zfssa.delete_lun(lcfg.zfssa_pool,
                                  lcfg.zfssa_cache_project,
                                  cachevol_name)
            return self._create_cache_volume(context,
                                             img_meta,
                                             img_service,
                                             specs,
                                             cachevol_props)

        return cachevol_name, cachesnap_name

    def _create_cache_volume(self, context, img_meta,
                             img_service, specs, cachevol_props):
        """Create a cache volume from an image.

        Returns names of the cache volume and its snapshot.
        """
        lcfg = self.configuration
        cachevol_size = int(cachevol_props['size'])
        lunsize = "%sg" % six.text_type(cachevol_size)
        lun_props = {
            'custom:image_id': img_meta['id'],
            'custom:updated_at': (
                six.text_type(img_meta['updated_at'].isoformat())),
        }
        lun_props.update(specs)

        cache_vol = {
            'name': cachevol_props['cache_name'],
            'id': img_meta['id'],
            'size': cachevol_size,
        }
        LOG.debug('Creating cache volume %s.', cache_vol['name'])

        try:
            self.zfssa.create_lun(lcfg.zfssa_pool,
                                  lcfg.zfssa_cache_project,
                                  cache_vol['name'],
                                  lunsize,
                                  lcfg.zfssa_target_group,
                                  lun_props)
            super(ZFSSAISCSIDriver, self).copy_image_to_volume(context,
                                                               cache_vol,
                                                               img_service,
                                                               img_meta['id'])
            self.zfssa.create_snapshot(lcfg.zfssa_pool,
                                       lcfg.zfssa_cache_project,
                                       cache_vol['name'],
                                       cachevol_props['snap_name'])
        except Exception as exc:
            exc_msg = (_('Fail to create cache volume %(volume)s. '
                         'Error: %(err)s'),
                       {'volume': cache_vol['name'],
                        'err': six.text_type(exc)})
            LOG.error(exc_msg)
            self.zfssa.delete_lun(lcfg.zfssa_pool,
                                  lcfg.zfssa_cache_project,
                                  cache_vol['name'])
            raise exception.VolumeBackendAPIException(data=exc_msg)

        return cachevol_props['cache_name'], cachevol_props['snap_name']

    def local_path(self, volume):
        """Not implemented."""
        pass

    def backup_volume(self, context, backup, backup_service):
        """Not implemented."""
        pass

    def restore_backup(self, context, backup, volume, backup_service):
        """Not implemented."""
        pass

    def _verify_clone_size(self, snapshot, size):
        """Check whether the clone size is the same as the parent volume."""
        lcfg = self.configuration
        lun = self.zfssa.get_lun(lcfg.zfssa_pool,
                                 lcfg.zfssa_project,
                                 snapshot['volume_name'])
        return lun['size'] == size

    def initialize_connection(self, volume, connector):
        lcfg = self.configuration
        init_groups = self.zfssa.get_initiator_initiatorgroup(
            connector['initiator'])
        if ((lcfg.zfssa_enable_local_cache is True) and
                (volume['name'].startswith('os-cache-vol-'))):
            project = lcfg.zfssa_cache_project
        else:
            project = lcfg.zfssa_project

        for initiator_group in init_groups:
            self.zfssa.set_lun_initiatorgroup(lcfg.zfssa_pool,
                                              project,
                                              volume['name'],
                                              initiator_group)
        iscsi_properties = {}
        provider = self._get_provider_info(volume)

        (target_portal, iqn, lun) = provider['provider_location'].split()
        iscsi_properties['target_discovered'] = False
        iscsi_properties['target_portal'] = target_portal
        iscsi_properties['target_iqn'] = iqn
        iscsi_properties['target_lun'] = lun
        iscsi_properties['volume_id'] = volume['id']

        if 'provider_auth' in provider:
            (auth_method, auth_username, auth_password) = provider[
                'provider_auth'].split()
            iscsi_properties['auth_method'] = auth_method
            iscsi_properties['auth_username'] = auth_username
            iscsi_properties['auth_password'] = auth_password

        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to terminate a connection for a volume."""
        LOG.debug('terminate_connection: volume name: %s.', volume['name'])
        lcfg = self.configuration
        project = lcfg.zfssa_project
        if ((lcfg.zfssa_enable_local_cache is True) and
                (volume['name'].startswith('os-cache-vol-'))):
            project = lcfg.zfssa_cache_project
        self.zfssa.set_lun_initiatorgroup(lcfg.zfssa_pool,
                                          project,
                                          volume['name'],
                                          '')

    def _get_voltype_specs(self, volume):
        """Get specs suitable for volume creation."""
        vtype = volume.get('volume_type_id', None)
        extra_specs = None
        if vtype:
            extra_specs = volume_types.get_volume_type_extra_specs(vtype)

        return self._get_specs(extra_specs)

    def _get_specs(self, xspecs):
        """Return a dict with extra specs and/or config values."""
        result = {}
        for spc in ZFSSA_LUN_SPECS:
            val = None
            prop = spc.split(':')[1]
            cfg = 'zfssa_lun_' + prop
            if xspecs:
                val = xspecs.pop(spc, None)

            if val is None:
                val = self.configuration.safe_get(cfg)

            if val is not None and val != '':
                result.update({prop: val})

        return result

    def migrate_volume(self, ctxt, volume, host):
        LOG.debug('Attempting ZFSSA enabled volume migration. volume: %(id)s, '
                  'host: %(host)s, status=%(status)s.',
                  {'id': volume['id'],
                   'host': host,
                   'status': volume['status']})

        lcfg = self.configuration
        default_ret = (False, None)

        if volume['status'] != "available":
            LOG.debug('Only available volumes can be migrated using backend '
                      'assisted migration. Defaulting to generic migration.')
            return default_ret

        if (host['capabilities']['vendor_name'] != 'Oracle' or
                host['capabilities']['storage_protocol'] != self.protocol):
            LOG.debug('Source and destination drivers need to be Oracle iSCSI '
                      'to use backend assisted migration. Defaulting to '
                      'generic migration.')
            return default_ret

        if 'location_info' not in host['capabilities']:
            LOG.debug('Could not find location_info in capabilities reported '
                      'by the destination driver. Defaulting to generic '
                      'migration.')
            return default_ret

        loc_info = host['capabilities']['location_info']

        try:
            (tgt_host, auth_str, tgt_pool, tgt_project, tgt_tgtgroup,
             tgt_repl_ip) = loc_info.split(':')
        except ValueError:
            LOG.error(_LE("Location info needed for backend enabled volume "
                          "migration not in correct format: %s. Continuing "
                          "with generic volume migration."), loc_info)
            return default_ret

        if tgt_repl_ip == '':
            msg = _LE("zfssa_replication_ip not set in cinder.conf. "
                      "zfssa_replication_ip is needed for backend enabled "
                      "volume migration. Continuing with generic volume "
                      "migration.")
            LOG.error(msg)
            return default_ret

        src_pool = lcfg.zfssa_pool
        src_project = lcfg.zfssa_project

        try:
            LOG.info(_LI('Connecting to target host: %s for backend enabled '
                         'migration.'), tgt_host)
            self.tgt_zfssa.set_host(tgt_host)
            self.tgt_zfssa.login(auth_str)

            # Verify that the replication service is online
            try:
                self.zfssa.verify_service('replication')
                self.tgt_zfssa.verify_service('replication')
            except exception.VolumeBackendAPIException:
                return default_ret

            # ensure that a target group by the same name exists on the target
            # system also, if not, use default migration.
            lun = self.zfssa.get_lun(src_pool, src_project, volume['name'])

            if lun['targetgroup'] != tgt_tgtgroup:
                return default_ret

            tgt_asn = self.tgt_zfssa.get_asn()
            src_asn = self.zfssa.get_asn()

            # verify on the source system that the destination has been
            # registered as a replication target
            tgts = self.zfssa.get_replication_targets()
            targets = []
            for target in tgts['targets']:
                if target['asn'] == tgt_asn:
                    targets.append(target)

            if targets == []:
                LOG.debug('Target host: %(host)s for volume migration '
                          'not configured as a replication target '
                          'for volume: %(vol)s.',
                          {'host': tgt_repl_ip,
                           'vol': volume['name']})
                return default_ret

            # Multiple ips from the same appliance may be configured
            # as different targets
            for target in targets:
                if target['address'] == tgt_repl_ip + ':216':
                    break

            if target['address'] != tgt_repl_ip + ':216':
                LOG.debug('Target with replication ip: %s not configured on '
                          'the source appliance for backend enabled volume '
                          'migration. Proceeding with default migration.',
                          tgt_repl_ip)
                return default_ret

            flow = lf.Flow('zfssa_volume_migration').add(
                MigrateVolumeInit(),
                MigrateVolumeCreateAction(provides='action_id'),
                MigrateVolumeSendReplUpdate(),
                MigrateVolumeSeverRepl(),
                MigrateVolumeMoveVol(),
                MigrateVolumeCleanUp()
            )
            taskflow.engines.run(flow,
                                 store={'driver': self,
                                        'tgt_zfssa': self.tgt_zfssa,
                                        'tgt_pool': tgt_pool,
                                        'tgt_project': tgt_project,
                                        'volume': volume, 'tgt_asn': tgt_asn,
                                        'src_zfssa': self.zfssa,
                                        'src_asn': src_asn,
                                        'src_pool': src_pool,
                                        'src_project': src_project,
                                        'target': target})

            return(True, None)

        except Exception:
            LOG.error(_LE("Error migrating volume: %s"), volume['name'])
            raise

    def update_migrated_volume(self, ctxt, volume, new_volume,
                               original_volume_status):
        """Return model update for migrated volume.

        :param volume: The original volume that was migrated to this backend
        :param new_volume: The migration volume object that was created on
                           this backend as part of the migration process
        :param original_volume_status: The status of the original volume
        :return model_update to update DB with any needed changes
        """

        lcfg = self.configuration
        original_name = CONF.volume_name_template % volume['id']
        current_name = CONF.volume_name_template % new_volume['id']

        LOG.debug('Renaming migrated volume: %(cur)s to %(org)s',
                  {'cur': current_name,
                   'org': original_name})
        self.zfssa.set_lun_props(lcfg.zfssa_pool, lcfg.zfssa_project,
                                 current_name, name=original_name)
        return {'_name_id': None}

    @utils.synchronized('zfssaiscsi', external=True)
    def _check_origin(self, lun, volname):
        """Verify the cache volume of a bootable volume.

        If the cache no longer has clone, it will be deleted.
        There is a small lag between the time a clone is deleted and the number
        of clones being updated accordingly. There is also a race condition
        when multiple volumes (clones of a cache volume) are deleted at once,
        leading to the number of clones reported incorrectly. The file lock is
        here to avoid such issues.
        """
        lcfg = self.configuration
        cache = lun['origin']
        numclones = -1
        if (cache['snapshot'].startswith('image-') and
                cache['share'].startswith('os-cache-vol')):
            try:
                numclones = self.zfssa.num_clones(lcfg.zfssa_pool,
                                                  lcfg.zfssa_cache_project,
                                                  cache['share'],
                                                  cache['snapshot'])
            except Exception:
                LOG.debug('Cache volume is already deleted.')
                return

            LOG.debug('Checking cache volume %(name)s, numclones = %(clones)d',
                      {'name': cache['share'], 'clones': numclones})

        # Sometimes numclones still hold old values even when all clones
        # have been deleted. So we handle this situation separately here:
        if numclones == 1:
            try:
                self.zfssa.get_lun(lcfg.zfssa_pool,
                                   lcfg.zfssa_project,
                                   volname)
                # The volume does exist, so return
                return
            except exception.VolumeNotFound:
                # The volume is already deleted
                numclones = 0

        if numclones == 0:
            self.zfssa.delete_lun(lcfg.zfssa_pool,
                                  lcfg.zfssa_cache_project,
                                  cache['share'])


class MigrateVolumeInit(task.Task):
    def execute(self, src_zfssa, volume, src_pool, src_project):
        LOG.debug('Setting inherit flag on source backend to False.')
        src_zfssa.edit_inherit_replication_flag(src_pool, src_project,
                                                volume['name'], set=False)

    def revert(self, src_zfssa, volume, src_pool, src_project, **kwargs):
        LOG.debug('Rollback: Setting inherit flag on source appliance to '
                  'True.')
        src_zfssa.edit_inherit_replication_flag(src_pool, src_project,
                                                volume['name'], set=True)


class MigrateVolumeCreateAction(task.Task):
    def execute(self, src_zfssa, volume, src_pool, src_project, target,
                tgt_pool):
        LOG.debug('Creating replication action on source appliance.')
        action_id = src_zfssa.create_replication_action(src_pool,
                                                        src_project,
                                                        target['label'],
                                                        tgt_pool,
                                                        volume['name'])

        self._action_id = action_id
        return action_id

    def revert(self, src_zfssa, **kwargs):
        if hasattr(self, '_action_id'):
            LOG.debug('Rollback: deleting replication action on source '
                      'appliance.')
            src_zfssa.delete_replication_action(self._action_id)


class MigrateVolumeSendReplUpdate(task.Task):
    def execute(self, src_zfssa, action_id):
        LOG.debug('Sending replication update from source appliance.')
        src_zfssa.send_repl_update(action_id)
        LOG.debug('Deleting replication action on source appliance.')
        src_zfssa.delete_replication_action(action_id)
        self._action_deleted = True


class MigrateVolumeSeverRepl(task.Task):
    def execute(self, tgt_zfssa, src_asn, action_id, driver):
        source = tgt_zfssa.get_replication_source(src_asn)
        if not source:
            err = (_('Source with host ip/name: %s not found on the '
                     'target appliance for backend enabled volume '
                     'migration, procedding with default migration.'),
                   driver.configuration.san_ip)
            LOG.error(err)
            raise exception.VolumeBackendAPIException(data=err)
        LOG.debug('Severing replication package on destination appliance.')
        tgt_zfssa.sever_replication(action_id, source['name'],
                                    project=action_id)


class MigrateVolumeMoveVol(task.Task):
    def execute(self, tgt_zfssa, tgt_pool, tgt_project, action_id, volume):
        LOG.debug('Moving LUN to destination project on destination '
                  'appliance.')
        tgt_zfssa.move_volume(tgt_pool, action_id, volume['name'], tgt_project)
        LOG.debug('Deleting temporary project on destination appliance.')
        tgt_zfssa.delete_project(tgt_pool, action_id)
        self._project_deleted = True

    def revert(self, tgt_zfssa, tgt_pool, tgt_project, action_id, volume,
               **kwargs):
        if not hasattr(self, '_project_deleted'):
            LOG.debug('Rollback: deleting temporary project on destination '
                      'appliance.')
            tgt_zfssa.delete_project(tgt_pool, action_id)


class MigrateVolumeCleanUp(task.Task):
    def execute(self, driver, volume, tgt_zfssa):
        LOG.debug('Finally, delete source volume on source appliance.')
        driver.delete_volume(volume)
        tgt_zfssa.logout()
