# Copyright (c) 2016 EMC Corporation
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

"""Built-in group type properties."""


from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
import webob

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
DEFAULT_CGSNAPSHOT_TYPE = "default_cgsnapshot_type"


def create(context,
           name,
           group_specs=None,
           is_public=True,
           projects=None,
           description=None):
    """Creates group types."""
    group_specs = group_specs or {}
    projects = projects or []
    elevated = context if context.is_admin else context.elevated()
    try:
        type_ref = db.group_type_create(elevated,
                                        dict(name=name,
                                             group_specs=group_specs,
                                             is_public=is_public,
                                             description=description),
                                        projects=projects)
    except db_exc.DBError:
        LOG.exception('DB error:')
        raise exception.GroupTypeCreateFailed(name=name,
                                              group_specs=group_specs)
    return type_ref


def update(context, id, name, description, is_public=None):
    """Update group type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidGroupType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    try:
        db.group_type_update(elevated, id,
                             dict(name=name, description=description,
                                  is_public=is_public))
    except db_exc.DBError:
        LOG.exception('DB error:')
        raise exception.GroupTypeUpdateFailed(id=id)


def destroy(context, id):
    """Marks group types as deleted."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidGroupType(reason=msg)
    else:
        elevated = context if context.is_admin else context.elevated()
        try:
            db.group_type_destroy(elevated, id)
        except exception.GroupTypeInUse as e:
            msg = _('Target group type is still in use. %s') % e
            raise webob.exc.HTTPBadRequest(explanation=msg)


def get_all_group_types(context, inactive=0, filters=None, marker=None,
                        limit=None, sort_keys=None, sort_dirs=None,
                        offset=None, list_result=False):
    """Get all non-deleted group_types.

    Pass true as argument if you want deleted group types returned also.

    """
    grp_types = db.group_type_get_all(context, inactive, filters=filters,
                                      marker=marker, limit=limit,
                                      sort_keys=sort_keys,
                                      sort_dirs=sort_dirs, offset=offset,
                                      list_result=list_result)
    return grp_types


def get_group_type(ctxt, id, expected_fields=None):
    """Retrieves single group type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidGroupType(reason=msg)

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.group_type_get(ctxt, id, expected_fields=expected_fields)


def get_group_type_by_name(context, name):
    """Retrieves single group type by name."""
    if name is None:
        msg = _("name cannot be None")
        raise exception.InvalidGroupType(reason=msg)

    return db.group_type_get_by_name(context, name)


def get_default_group_type():
    """Get the default group type."""
    name = CONF.default_group_type
    grp_type = {}

    if name is not None:
        ctxt = context.get_admin_context()
        try:
            grp_type = get_group_type_by_name(ctxt, name)
        except exception.GroupTypeNotFoundByName:
            # Couldn't find group type with the name in default_group_type
            # flag, record this issue and move on
            LOG.exception('Default group type is not found. '
                          'Please check default_group_type config.')

    return grp_type


def get_default_cgsnapshot_type():
    """Get the default group type for migrating cgsnapshots.

    Get the default group type for migrating consistencygroups to
    groups and cgsnapshots to group_snapshots.
    """

    grp_type = {}

    ctxt = context.get_admin_context()
    try:
        grp_type = get_group_type_by_name(ctxt, DEFAULT_CGSNAPSHOT_TYPE)
    except exception.GroupTypeNotFoundByName:
        # Couldn't find DEFAULT_CGSNAPSHOT_TYPE group type.
        # Record this issue and move on.
        LOG.exception('Default cgsnapshot type %s is not found.',
                      DEFAULT_CGSNAPSHOT_TYPE)

    return grp_type


def is_default_cgsnapshot_type(group_type_id):
    cgsnap_type = get_default_cgsnapshot_type()
    return cgsnap_type and group_type_id == cgsnap_type['id']


def get_group_type_specs(group_type_id, key=False):
    group_type = get_group_type(context.get_admin_context(),
                                group_type_id)
    group_specs = group_type['group_specs']
    if key:
        if group_specs.get(key):
            return group_specs.get(key)
        else:
            return False
    else:
        return group_specs


def is_public_group_type(context, group_type_id):
    """Return is_public boolean value of group type"""
    group_type = db.group_type_get(context, group_type_id)
    return group_type['is_public']


def add_group_type_access(context, group_type_id, project_id):
    """Add access to group type for project_id."""
    if group_type_id is None:
        msg = _("group_type_id cannot be None")
        raise exception.InvalidGroupType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    if is_public_group_type(elevated, group_type_id):
        msg = _("Type access modification is not applicable to public group "
                "type.")
        raise exception.InvalidGroupType(reason=msg)
    return db.group_type_access_add(elevated, group_type_id, project_id)


def remove_group_type_access(context, group_type_id, project_id):
    """Remove access to group type for project_id."""
    if group_type_id is None:
        msg = _("group_type_id cannot be None")
        raise exception.InvalidGroupType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    if is_public_group_type(elevated, group_type_id):
        msg = _("Type access modification is not applicable to public group "
                "type.")
        raise exception.InvalidGroupType(reason=msg)
    return db.group_type_access_remove(elevated, group_type_id, project_id)
