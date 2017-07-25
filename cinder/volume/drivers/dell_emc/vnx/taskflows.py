# Copyright (c) 2016 EMC Corporation.
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

from oslo_log import log as logging
from oslo_utils import importutils


import taskflow.engines
from taskflow.patterns import linear_flow
from taskflow import task
from taskflow.types import failure

from cinder import exception
from cinder.i18n import _
from cinder.volume.drivers.dell_emc.vnx import common
from cinder.volume.drivers.dell_emc.vnx import const
from cinder.volume.drivers.dell_emc.vnx import utils

storops = importutils.try_import('storops')

LOG = logging.getLogger(__name__)


class MigrateLunTask(task.Task):
    """Starts a migration between two LUNs/SMPs.

    Reversion strategy: Cleanup the migration session
    """
    def __init__(self, name=None, provides=None, inject=None,
                 rebind=None):
        super(MigrateLunTask, self).__init__(name=name,
                                             provides=provides,
                                             inject=inject,
                                             rebind=rebind)

    def execute(self, client, src_id, dst_id, async_migrate, *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        dst_lun = client.get_lun(lun_id=dst_id)
        dst_wwn = dst_lun.wwn
        client.migrate_lun(src_id, dst_id)
        if not async_migrate:
            migrated = client.verify_migration(src_id, dst_id, dst_wwn)
            if not migrated:
                msg = _("Failed to migrate volume between source vol %(src)s"
                        " and dest vol %(dst)s.") % {
                            'src': src_id, 'dst': dst_id}
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)

    def revert(self, result, client, src_id, dst_id, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method)s: cleanup migration session: '
                    '%(src_id)s -> %(dst_id)s.',
                    {'method': method_name,
                     'src_id': src_id,
                     'dst_id': dst_id})
        client.cleanup_migration(src_id, dst_id)


class CreateLunTask(task.Task):
    """Creates a new lun task.

    Reversion strategy: Delete the lun.
    """
    def __init__(self, name=None, provides=('new_lun_id', 'new_lun_wwn'),
                 inject=None):
        super(CreateLunTask, self).__init__(name=name,
                                            provides=provides,
                                            inject=inject)
        if provides and not isinstance(provides, tuple):
            raise ValueError('Only tuple is allowed for [provides].')

    def execute(self, client, pool_name, lun_name, lun_size,
                provision, tier, ignore_thresholds=False,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        lun = client.create_lun(pool=pool_name,
                                name=lun_name,
                                size=lun_size,
                                provision=provision,
                                tier=tier,
                                ignore_thresholds=ignore_thresholds)
        return lun.lun_id, lun.wwn

    def revert(self, result, client, lun_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        if isinstance(result, failure.Failure):
            return
        else:
            LOG.warning('%(method_name)s: delete lun %(lun_name)s',
                        {'method_name': method_name, 'lun_name': lun_name})
            client.delete_lun(lun_name)


class CopySnapshotTask(task.Task):
    """Task to copy a volume snapshot/consistency group snapshot.

    Reversion Strategy: Delete the copied snapshot/cgsnapshot
    """
    def execute(self, client, snap_name, new_snap_name,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        client.copy_snapshot(snap_name,
                             new_snap_name)

    def revert(self, result, client, snap_name, new_snap_name,
               *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: delete the '
                    'copied snapshot %(new_name)s of '
                    '%(source_name)s.',
                    {'method_name': method_name,
                     'new_name': new_snap_name,
                     'source_name': snap_name})
        client.delete_snapshot(new_snap_name)


class CreateSMPTask(task.Task):
    """Creates a snap mount point (SMP) for the source snapshot.

    Reversion strategy: Delete the SMP.
    """
    def __init__(self, name=None, provides='smp_id', inject=None):
        super(CreateSMPTask, self).__init__(name=name,
                                            provides=provides,
                                            inject=inject)

    def execute(self, client, smp_name, base_lun_name,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)

        client.create_mount_point(base_lun_name, smp_name)
        lun = client.get_lun(name=smp_name)
        return lun.lun_id

    def revert(self, result, client, smp_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: delete mount point %(name)s',
                    {'method_name': method_name,
                     'name': smp_name})
        client.delete_lun(smp_name)


class AttachSnapTask(task.Task):
    """Attaches the snapshot to the SMP created before.

    Reversion strategy: Detach the SMP.
    """
    def execute(self, client, smp_name, snap_name,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        client.attach_snapshot(smp_name, snap_name)

    def revert(self, result, client, smp_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: detach mount point %(smp_name)s',
                    {'method_name': method_name,
                     'smp_name': smp_name})
        client.detach_snapshot(smp_name)


class CreateSnapshotTask(task.Task):
    """Creates a snapshot of a volume.

    Reversion Strategy: Delete the created snapshot.
    """
    def execute(self, client, snap_name, lun_id, keep_for=None,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        LOG.info('Create snapshot: %(snapshot)s: lun: %(lun)s',
                 {'snapshot': snap_name,
                  'lun': lun_id})
        client.create_snapshot(lun_id, snap_name, keep_for=keep_for)

    def revert(self, result, client, snap_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: '
                    'delete temp snapshot %(snap_name)s',
                    {'method_name': method_name,
                     'snap_name': snap_name})
        client.delete_snapshot(snap_name)


class ModifySnapshotTask(task.Task):
    """Task to modify a Snapshot to allow ReadWrite on it."""
    def execute(self, client, snap_name, keep_for=None,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        client.modify_snapshot(snap_name, allow_rw=True, keep_for=keep_for)

    def revert(self, result, client, snap_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: '
                    'setting snapshot %(snap_name)s to read-only.',
                    {'method_name': method_name,
                     'snap_name': snap_name})
        client.modify_snapshot(snap_name, allow_rw=False)


class WaitMigrationsTask(task.Task):
    """Task to wait migrations to be completed."""
    def __init__(self, src_id_template, dst_id_template,
                 dst_wwn_template, num_of_members, *args, **kwargs):
        self.migrate_tuples = [
            (src_id_template % x, dst_id_template % x, dst_wwn_template % x)
            for x in range(num_of_members)]
        src_id_keys = sorted(set(
            [src_id_template % i for i in range(num_of_members)]))
        dst_id_keys = sorted(set(
            [dst_id_template % i for i in range(num_of_members)]))
        dst_wwn_keys = sorted(set(
            [dst_wwn_template % i for i in range(num_of_members)]))

        super(WaitMigrationsTask, self).__init__(
            requires=(src_id_keys + dst_id_keys + dst_wwn_keys),
            *args, **kwargs)

    def execute(self, client, *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        for src_id_key, dst_id_key, dst_wwn_key in self.migrate_tuples:
            src_id = kwargs[src_id_key]
            dst_id = kwargs[dst_id_key]
            dst_wwn = kwargs[dst_wwn_key]
            migrated = client.verify_migration(src_id,
                                               dst_id,
                                               dst_wwn)
            if not migrated:
                msg = _("Failed to migrate volume %(src)s.") % {'src': src_id}
                raise exception.VolumeBackendAPIException(data=msg)


class CreateConsistencyGroupTask(task.Task):
    """Task to create a consistency group."""
    def __init__(self, lun_id_key_template, num_of_members,
                 *args, **kwargs):
        self.lun_id_keys = sorted(set(
            [lun_id_key_template % i for i in range(num_of_members)]))
        super(CreateConsistencyGroupTask, self).__init__(
            requires=self.lun_id_keys, *args, **kwargs)

    def execute(self, client, new_cg_name, *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        lun_ids = [kwargs[key] for key in self.lun_id_keys]
        client.create_consistency_group(new_cg_name,
                                        lun_ids)


class CreateCGSnapshotTask(task.Task):
    """Task to create a CG snapshot."""
    def __init__(self, provides='new_cg_snap_name', *args, **kwargs):
        super(CreateCGSnapshotTask, self).__init__(
            provides=provides, *args, **kwargs)

    def execute(self, client, cg_snap_name, cg_name, *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        return client.create_cg_snapshot(cg_snap_name, cg_name)

    def revert(self, client, cg_snap_name, cg_name, *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method_name)s: '
                    'deleting CG snapshot %(snap_name)s.',
                    {'method_name': method_name,
                     'snap_name': cg_snap_name})
        client.delete_cg_snapshot(cg_snap_name)


class CreateMirrorTask(task.Task):
    """Creates a MirrorView with primary lun for replication.

    Reversion strategy: Destroy the created MirrorView.
    """
    def execute(self, mirror, mirror_name, primary_lun_id,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        mirror.create_mirror(mirror_name, primary_lun_id)

    def revert(self, result, mirror, mirror_name,
               *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method)s: removing mirror '
                    'view %(name)s.',
                    {'method': method_name,
                     'name': mirror_name})
        mirror.delete_mirror(mirror_name)


class AddMirrorImageTask(task.Task):
    """Add the secondary image to MirrorView.

    Reversion strategy: Remove the secondary image.
    """
    def execute(self, mirror, mirror_name, secondary_lun_id,
                *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        mirror.add_image(mirror_name, secondary_lun_id)

    def revert(self, result, mirror, mirror_name,
               *args, **kwargs):
        method_name = '%s.revert' % self.__class__.__name__
        LOG.warning('%(method)s: removing secondary image '
                    'from %(name)s.',
                    {'method': method_name,
                     'name': mirror_name})
        mirror.remove_image(mirror_name)


class ExtendSMPTask(task.Task):
    """Extend the SMP if needed.

    If the SMP is thin and the new size is larger than the old one, then
    extend it.
    """
    def execute(self, client, smp_name, lun_size, *args, **kwargs):
        LOG.debug('%s.execute', self.__class__.__name__)
        smp = client.get_lun(name=smp_name)
        if lun_size > smp.total_capacity_gb:
            if smp.primary_lun.is_thin_lun:
                client.expand_lun(smp_name, lun_size)
            else:
                LOG.warning('Not extending the SMP: %s, because its base lun '
                            'is not thin.', smp_name)
        else:
            LOG.info('Not extending the SMP: %(smp)s, size: %(size)s, because'
                     'the new size: %(new_size)s is smaller.',
                     {'smp': smp_name, 'size': smp.total_capacity_gb,
                      'new_size': lun_size})


def run_migration_taskflow(client,
                           lun_id,
                           lun_name,
                           lun_size,
                           pool_name,
                           provision,
                           tier,
                           rate=const.MIGRATION_RATE_HIGH):
    # Step 1: create target LUN
    # Step 2: start and migrate migration session
    tmp_lun_name = utils.construct_tmp_lun_name(lun_name)
    flow_name = 'migrate_lun'
    store_spec = {'client': client,
                  'pool_name': pool_name,
                  'lun_name': tmp_lun_name,
                  'lun_size': lun_size,
                  'provision': provision,
                  'tier': tier,
                  'ignore_thresholds': True,
                  'src_id': lun_id,
                  'async_migrate': False,
                  }
    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(CreateLunTask(),
                  MigrateLunTask(rebind={'dst_id': 'new_lun_id'}))
    engine = taskflow.engines.load(
        work_flow, store=store_spec)
    engine.run()


def fast_create_volume_from_snapshot(client,
                                     snap_name,
                                     new_snap_name,
                                     lun_name,
                                     base_lun_name,
                                     pool_name):
    # Step 1: copy snapshot
    # Step 2: allow read/write for snapshot
    # Step 3: create smp LUN
    # Step 4: attach the snapshot
    flow_name = 'create_snapcopy_volume_from_snapshot'

    store_spec = {'client': client,
                  'snap_name': snap_name,
                  'new_snap_name': new_snap_name,
                  'pool_name': pool_name,
                  'smp_name': lun_name,
                  'base_lun_name': base_lun_name,
                  'ignore_thresholds': True,
                  }
    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(CopySnapshotTask(),
                  ModifySnapshotTask(rebind={'snap_name': 'new_snap_name'}),
                  CreateSMPTask(),
                  AttachSnapTask(rebind={'snap_name': 'new_snap_name'}))
    engine = taskflow.engines.load(
        work_flow, store=store_spec)
    engine.run()
    lun_id = engine.storage.fetch('smp_id')
    return lun_id


def create_volume_from_snapshot(client, src_snap_name, lun_name,
                                lun_size, base_lun_name, pool_name,
                                provision, tier, new_snap_name=None):
    # Step 1: Copy and modify snap(only for async migrate)
    # Step 2: Create smp from base lun
    # Step 3: Attach snapshot to smp
    # Step 4: Create new LUN
    # Step 5: migrate the smp to new LUN
    tmp_lun_name = '%s_dest' % lun_name
    flow_name = 'create_volume_from_snapshot'
    store_spec = {'client': client,
                  'snap_name': src_snap_name,
                  'new_snap_name': new_snap_name,
                  'smp_name': lun_name,
                  'lun_name': tmp_lun_name,
                  'lun_size': lun_size,
                  'base_lun_name': base_lun_name,
                  'pool_name': pool_name,
                  'provision': provision,
                  'tier': tier,
                  'keep_for': (common.SNAP_EXPIRATION_HOUR
                               if new_snap_name else None),
                  'async_migrate': True if new_snap_name else False,
                  }
    work_flow = linear_flow.Flow(flow_name)
    if new_snap_name:
        work_flow.add(CopySnapshotTask(),
                      ModifySnapshotTask(
                      rebind={'snap_name': 'new_snap_name'}))

    work_flow.add(CreateSMPTask(),
                  AttachSnapTask(rebind={'snap_name': 'new_snap_name'})
                  if new_snap_name else AttachSnapTask(),
                  ExtendSMPTask(),
                  CreateLunTask(),
                  MigrateLunTask(
                      rebind={'src_id': 'smp_id',
                              'dst_id': 'new_lun_id'}))
    engine = taskflow.engines.load(
        work_flow, store=store_spec)
    engine.run()
    lun_id = engine.storage.fetch('smp_id')
    return lun_id


def fast_create_cloned_volume(client, snap_name, lun_id,
                              lun_name, base_lun_name):
    flow_name = 'create_cloned_snapcopy_volume'
    store_spec = {
        'client': client,
        'snap_name': snap_name,
        'lun_id': lun_id,
        'smp_name': lun_name,
        'base_lun_name': base_lun_name}
    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(CreateSnapshotTask(),
                  CreateSMPTask(),
                  AttachSnapTask())
    engine = taskflow.engines.load(work_flow, store=store_spec)
    engine.run()
    lun_id = engine.storage.fetch('smp_id')
    return lun_id


def create_cloned_volume(client, snap_name, lun_id, lun_name,
                         lun_size, base_lun_name, pool_name,
                         provision, tier, async_migrate=False):
    tmp_lun_name = '%s_dest' % lun_name
    flow_name = 'create_cloned_volume'
    store_spec = {'client': client,
                  'snap_name': snap_name,
                  'lun_id': lun_id,
                  'smp_name': lun_name,
                  'lun_name': tmp_lun_name,
                  'lun_size': lun_size,
                  'base_lun_name': base_lun_name,
                  'pool_name': pool_name,
                  'provision': provision,
                  'tier': tier,
                  'keep_for': (common.SNAP_EXPIRATION_HOUR if
                               async_migrate else None),
                  'async_migrate': async_migrate,
                  }
    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(
        CreateSnapshotTask(),
        CreateSMPTask(),
        AttachSnapTask(),
        ExtendSMPTask(),
        CreateLunTask(),
        MigrateLunTask(
            rebind={'src_id': 'smp_id', 'dst_id': 'new_lun_id'}))
    engine = taskflow.engines.load(
        work_flow, store=store_spec)
    engine.run()
    if not async_migrate:
        client.delete_snapshot(snap_name)
    lun_id = engine.storage.fetch('smp_id')
    return lun_id


def create_cg_from_cg_snapshot(client, cg_name, src_cg_name,
                               cg_snap_name, src_cg_snap_name,
                               pool_name, lun_sizes, lun_names,
                               src_lun_names, specs_list, copy_snap=True):
    prepare_tasks = []
    store_spec = {}

    if copy_snap:
        flow_name = 'create_cg_from_cg_snapshot'
        temp_cg_snap = utils.construct_tmp_cg_snap_name(cg_name)
        snap_name = temp_cg_snap
        store_spec.update({'snap_name': src_cg_snap_name,
                           'new_snap_name': snap_name})
        prepare_tasks.append(
            CopySnapshotTask())
        prepare_tasks.append(
            ModifySnapshotTask(rebind={'snap_name': 'new_snap_name'}))
    else:
        flow_name = 'create_cg_from_cg'
        snap_name = cg_snap_name
        store_spec.update({'cg_name': src_cg_name,
                           'cg_snap_name': snap_name})
        prepare_tasks.append(CreateCGSnapshotTask())

    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(*prepare_tasks)
    new_src_id_template = 'new_src_id_%s'
    new_dst_id_template = 'new_dst_id_%s'
    new_dst_wwn_template = 'new_dst_wwn_%s'

    common_store_spec = {
        'client': client,
        'pool_name': pool_name,
        'ignore_thresholds': True,
        'new_cg_name': cg_name
    }
    store_spec.update(common_store_spec)

    # Create LUNs for CG
    for i, lun_name in enumerate(lun_names):
        sub_store_spec = {
            'lun_name': utils.construct_tmp_lun_name(lun_name),
            'lun_size': lun_sizes[i],
            'provision': specs_list[i].provision,
            'tier': specs_list[i].tier,
            'base_lun_name': src_lun_names[i],
            'smp_name': lun_name,
            'snap_name': snap_name,
            'async_migrate': True,
        }
        work_flow.add(CreateSMPTask(name="CreateSMPTask_%s" % i,
                                    inject=sub_store_spec,
                                    provides=new_src_id_template % i),
                      AttachSnapTask(name="AttachSnapTask_%s" % i,
                                     inject=sub_store_spec),
                      CreateLunTask(name="CreateLunTask_%s" % i,
                                    inject=sub_store_spec,
                                    provides=(new_dst_id_template % i,
                                              new_dst_wwn_template % i)),
                      MigrateLunTask(
                          name="MigrateLunTask_%s" % i,
                          inject=sub_store_spec,
                          rebind={'src_id': new_src_id_template % i,
                                  'dst_id': new_dst_id_template % i}))

    # Wait all migration session finished
    work_flow.add(WaitMigrationsTask(new_src_id_template,
                                     new_dst_id_template,
                                     new_dst_wwn_template,
                                     len(lun_names)),
                  CreateConsistencyGroupTask(new_src_id_template,
                                             len(lun_names)))
    engine = taskflow.engines.load(work_flow, store=store_spec)
    engine.run()
    # Fetch all created LUNs and add them into CG
    lun_id_list = []
    for i, lun_name in enumerate(lun_names):
        lun_id = engine.storage.fetch(new_src_id_template % i)
        lun_id_list.append(lun_id)

    client.delete_cg_snapshot(snap_name)
    return lun_id_list


def create_cloned_cg(client, cg_name, src_cg_name,
                     pool_name, lun_sizes, lun_names,
                     src_lun_names, specs_list):
    cg_snap_name = utils.construct_tmp_cg_snap_name(cg_name)
    return create_cg_from_cg_snapshot(
        client, cg_name, src_cg_name,
        cg_snap_name, None,
        pool_name, lun_sizes, lun_names,
        src_lun_names, specs_list, copy_snap=False)


def create_mirror_view(mirror_view, mirror_name,
                       primary_lun_id, pool_name,
                       lun_name, lun_size, provision, tier):
    flow_name = 'create_mirror_view'
    store_specs = {
        'mirror': mirror_view,
        'mirror_name': mirror_name,
        'primary_lun_id': primary_lun_id,
        'pool_name': pool_name,
        'lun_name': lun_name,
        'lun_size': lun_size,
        'provision': provision,
        'tier': tier,
        'ignore_thresholds': True
    }
    # NOTE: should create LUN on secondary device/array
    work_flow = linear_flow.Flow(flow_name)
    work_flow.add(CreateMirrorTask(),
                  CreateLunTask(
                      name='CreateSecondaryLunTask',
                      provides=('secondary_lun_id', 'secondary_lun_wwn'),
                      inject={'client': mirror_view.secondary_client}),
                  AddMirrorImageTask())
    engine = taskflow.engines.load(work_flow, store=store_specs)
    engine.run()
