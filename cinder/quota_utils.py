# Copyright 2013 OpenStack Foundation
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
from oslo_config import cfg
from oslo_log import log as logging

from cinder import exception

CONF = cfg.CONF
CONF.import_group('keystone_authtoken',
                  'keystonemiddleware.auth_token.__init__')

LOG = logging.getLogger(__name__)


def get_volume_type_reservation(ctxt, volume, type_id,
                                reserve_vol_type_only=False,
                                negative=False):
    from cinder import quota
    QUOTAS = quota.QUOTAS
    # Reserve quotas for the given volume type
    try:
        reserve_opts = {'volumes': 1, 'gigabytes': volume['size']}
        # When retyping a volume it may contain snapshots (if we are not
        # migrating it) and we need to account for its snapshots' size
        if volume.snapshots:
            reserve_opts['snapshots'] = len(volume.snapshots)
            if not CONF.no_snapshot_gb_quota:
                reserve_opts['gigabytes'] += sum(snap.volume_size
                                                 for snap in volume.snapshots)
        QUOTAS.add_volume_type_opts(ctxt,
                                    reserve_opts,
                                    type_id)
        # If reserve_vol_type_only is True, just reserve volume_type quota,
        # not volume quota.
        if reserve_vol_type_only:
            reserve_opts.pop('volumes')
            reserve_opts.pop('gigabytes')
            reserve_opts.pop('snapshots', None)

        if negative:
            for key, value in reserve_opts.items():
                reserve_opts[key] = -value

        # Note that usually the project_id on the volume will be the same as
        # the project_id in the context. But, if they are different then the
        # reservations must be recorded against the project_id that owns the
        # volume.
        project_id = volume['project_id']
        reservations = QUOTAS.reserve(ctxt,
                                      project_id=project_id,
                                      **reserve_opts)
    except exception.OverQuota as e:
        process_reserve_over_quota(ctxt, e,
                                   resource='volumes',
                                   size=volume.size)
    return reservations


def _filter_domain_id_from_parents(domain_id, tree):
    """Removes the domain_id from the tree if present"""
    new_tree = None
    if tree:
        parent, children = next(iter(tree.items()))
        # Don't add the domain id to the parents hierarchy
        if parent != domain_id:
            new_tree = {parent: _filter_domain_id_from_parents(domain_id,
                                                               children)}

    return new_tree


OVER_QUOTA_RESOURCE_EXCEPTIONS = {'snapshots': exception.SnapshotLimitExceeded,
                                  'backups': exception.BackupLimitExceeded,
                                  'volumes': exception.VolumeLimitExceeded,
                                  'groups': exception.GroupLimitExceeded}


def process_reserve_over_quota(context, over_quota_exception,
                               resource, size=None):
    """Handle OverQuota exception.

    Analyze OverQuota exception, and raise new exception related to
    resource type. If there are unexpected items in overs,
    UnexpectedOverQuota is raised.

    :param context: security context
    :param over_quota_exception: OverQuota exception
    :param resource: can be backups, snapshots, and volumes
    :param size: requested size in reservation
    """
    def _consumed(name):
        return (usages[name]['reserved'] + usages[name]['in_use'])

    overs = over_quota_exception.kwargs['overs']
    usages = over_quota_exception.kwargs['usages']
    quotas = over_quota_exception.kwargs['quotas']
    invalid_overs = []

    for over in overs:
        if 'gigabytes' in over:
            msg = ("Quota exceeded for %(s_pid)s, tried to create "
                   "%(s_size)dG %(s_resource)s (%(d_consumed)dG of "
                   "%(d_quota)dG already consumed).")
            LOG.warning(msg, {'s_pid': context.project_id,
                              's_size': size,
                              's_resource': resource[:-1],
                              'd_consumed': _consumed(over),
                              'd_quota': quotas[over]})
            if resource == 'backups':
                exc = exception.VolumeBackupSizeExceedsAvailableQuota
            else:
                exc = exception.VolumeSizeExceedsAvailableQuota
            raise exc(
                name=over,
                requested=size,
                consumed=_consumed(over),
                quota=quotas[over])
        if (resource in OVER_QUOTA_RESOURCE_EXCEPTIONS.keys() and
                resource in over):
            msg = ("Quota exceeded for %(s_pid)s, tried to create "
                   "%(s_resource)s (%(d_consumed)d %(s_resource)ss "
                   "already consumed).")
            LOG.warning(msg, {'s_pid': context.project_id,
                              'd_consumed': _consumed(over),
                              's_resource': resource[:-1]})
            raise OVER_QUOTA_RESOURCE_EXCEPTIONS[resource](
                allowed=quotas[over],
                name=over)
        invalid_overs.append(over)

    if invalid_overs:
        raise exception.UnexpectedOverQuota(name=', '.join(invalid_overs))
