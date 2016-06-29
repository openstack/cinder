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
import webob

from oslo_config import cfg
from oslo_log import log as logging

from keystoneclient.auth.identity.generic import token
from keystoneclient import client
from keystoneclient import exceptions
from keystoneclient import session

from cinder import db
from cinder import exception
from cinder.i18n import _, _LW

CONF = cfg.CONF
CONF.import_opt('auth_uri', 'keystonemiddleware.auth_token.__init__',
                'keystone_authtoken')

LOG = logging.getLogger(__name__)


class GenericProjectInfo(object):
    """Abstraction layer for Keystone V2 and V3 project objects"""
    def __init__(self, project_id, project_keystone_api_version,
                 project_parent_id=None,
                 project_subtree=None,
                 project_parent_tree=None,
                 is_admin_project=False):
        self.id = project_id
        self.keystone_api_version = project_keystone_api_version
        self.parent_id = project_parent_id
        self.subtree = project_subtree
        self.parents = project_parent_tree
        self.is_admin_project = is_admin_project


def get_volume_type_reservation(ctxt, volume, type_id,
                                reserve_vol_type_only=False):
    from cinder import quota
    QUOTAS = quota.QUOTAS
    # Reserve quotas for the given volume type
    try:
        reserve_opts = {'volumes': 1, 'gigabytes': volume['size']}
        QUOTAS.add_volume_type_opts(ctxt,
                                    reserve_opts,
                                    type_id)
        # If reserve_vol_type_only is True, just reserve volume_type quota,
        # not volume quota.
        if reserve_vol_type_only:
            reserve_opts.pop('volumes')
            reserve_opts.pop('gigabytes')
        # Note that usually the project_id on the volume will be the same as
        # the project_id in the context. But, if they are different then the
        # reservations must be recorded against the project_id that owns the
        # volume.
        project_id = volume['project_id']
        reservations = QUOTAS.reserve(ctxt,
                                      project_id=project_id,
                                      **reserve_opts)
    except exception.OverQuota as e:
        overs = e.kwargs['overs']
        usages = e.kwargs['usages']
        quotas = e.kwargs['quotas']

        def _consumed(name):
            return (usages[name]['reserved'] + usages[name]['in_use'])

        for over in overs:
            if 'gigabytes' in over:
                s_size = volume['size']
                d_quota = quotas[over]
                d_consumed = _consumed(over)
                LOG.warning(
                    _LW("Quota exceeded for %(s_pid)s, tried to create "
                        "%(s_size)sG volume - (%(d_consumed)dG of "
                        "%(d_quota)dG already consumed)"),
                    {'s_pid': ctxt.project_id,
                     's_size': s_size,
                     'd_consumed': d_consumed,
                     'd_quota': d_quota})
                raise exception.VolumeSizeExceedsAvailableQuota(
                    requested=s_size, quota=d_quota, consumed=d_consumed)
            elif 'volumes' in over:
                LOG.warning(
                    _LW("Quota exceeded for %(s_pid)s, tried to create "
                        "volume (%(d_consumed)d volumes "
                        "already consumed)"),
                    {'s_pid': ctxt.project_id,
                     'd_consumed': _consumed(over)})
                raise exception.VolumeLimitExceeded(
                    allowed=quotas[over])
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


def get_project_hierarchy(context, project_id, subtree_as_ids=False,
                          parents_as_ids=False, is_admin_project=False):
    """A Helper method to get the project hierarchy.

    Along with hierarchical multitenancy in keystone API v3, projects can be
    hierarchically organized. Therefore, we need to know the project
    hierarchy, if any, in order to do nested quota operations properly.
    If the domain is being used as the top most parent, it is filtered out from
    the parent tree and parent_id.
    """
    try:
        keystone = _keystone_client(context)
        generic_project = GenericProjectInfo(project_id, keystone.version)
        if keystone.version == 'v3':
            project = keystone.projects.get(project_id,
                                            subtree_as_ids=subtree_as_ids,
                                            parents_as_ids=parents_as_ids)

            generic_project.parent_id = None
            if project.parent_id != project.domain_id:
                generic_project.parent_id = project.parent_id

            generic_project.subtree = (
                project.subtree if subtree_as_ids else None)

            generic_project.parents = None
            if parents_as_ids:
                generic_project.parents = _filter_domain_id_from_parents(
                    project.domain_id, project.parents)

            generic_project.is_admin_project = is_admin_project
    except exceptions.NotFound:
        msg = (_("Tenant ID: %s does not exist.") % project_id)
        raise webob.exc.HTTPNotFound(explanation=msg)

    return generic_project


def get_parent_project_id(context, project_id):
    return get_project_hierarchy(context, project_id).parent_id


def get_all_projects(context):
    # Right now this would have to be done as cloud admin with Keystone v3
    return _keystone_client(context, (3, 0)).projects.list()


def get_all_root_project_ids(context):
    project_list = get_all_projects(context)

    # Find every project which does not have a parent, meaning it is the
    # root of the tree
    project_roots = [project.id for project in project_list
                     if not project.parent_id]

    return project_roots


def update_alloc_to_next_hard_limit(context, resources, deltas, res,
                                    expire, project_id):
    from cinder import quota
    QUOTAS = quota.QUOTAS
    reservations = []
    projects = get_project_hierarchy(context, project_id,
                                     parents_as_ids=True).parents
    hard_limit_found = False
    # Update allocated values up the chain til we hit a hard limit or run out
    # of parents
    while projects and not hard_limit_found:
        cur_proj_id = list(projects)[0]
        projects = projects[cur_proj_id]
        cur_quota_lim = QUOTAS.get_by_project_or_default(
            context, cur_proj_id, res)
        hard_limit_found = (cur_quota_lim != -1)
        cur_quota = {res: cur_quota_lim}
        cur_delta = {res: deltas[res]}
        try:
            reservations += db.quota_reserve(
                context, resources, cur_quota, cur_delta, expire,
                CONF.until_refresh, CONF.max_age, cur_proj_id,
                is_allocated_reserve=True)
        except exception.OverQuota:
            db.reservation_rollback(context, reservations)
            raise
    return reservations


def validate_setup_for_nested_quota_use(ctxt, resources,
                                        nested_quota_driver,
                                        fix_allocated_quotas=False):
    """Validates the setup supports using nested quotas.

    Ensures that Keystone v3 or greater is being used, that the current
    user is of the cloud admin role, and that the existing quotas make sense to
    nest in the current hierarchy (e.g. that no child quota would be larger
    than it's parent).

    :param resources: the quota resources to validate
    :param nested_quota_driver: nested quota driver used to validate each tree
    :param fix_allocated_quotas: if True, parent projects "allocated" total
        will be calculated based on the existing child limits and the DB will
        be updated. If False, an exception is raised reporting any parent
        allocated quotas are currently incorrect.
    """
    try:
        project_roots = get_all_root_project_ids(ctxt)

        # Now that we've got the roots of each tree, validate the trees
        # to ensure that each is setup logically for nested quotas
        for root in project_roots:
            root_proj = get_project_hierarchy(ctxt, root,
                                              subtree_as_ids=True)
            nested_quota_driver.validate_nested_setup(
                ctxt,
                resources,
                {root_proj.id: root_proj.subtree},
                fix_allocated_quotas=fix_allocated_quotas
            )
    except exceptions.VersionNotAvailable:
        msg = _("Keystone version 3 or greater must be used to get nested "
                "quota support.")
        raise exception.CinderException(message=msg)
    except exceptions.Forbidden:
        msg = _("Must run this command as cloud admin using "
                "a Keystone policy.json which allows cloud "
                "admin to list and get any project.")
        raise exception.CinderException(message=msg)


def _keystone_client(context, version=(3, 0)):
    """Creates and returns an instance of a generic keystone client.

    :param context: The request context
    :param version: version of Keystone to request
    :return: keystoneclient.client.Client object
    """
    auth_plugin = token.Token(
        auth_url=CONF.keystone_authtoken.auth_uri,
        token=context.auth_token,
        project_id=context.project_id)
    client_session = session.Session(auth=auth_plugin,
                                     verify=False if
                                     CONF.keystone_authtoken.insecure else
                                     (CONF.keystone_authtoken.cafile or True))
    return client.Client(auth_url=CONF.keystone_authtoken.auth_uri,
                         session=client_session, version=version)
