# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2011 Ken Pepple
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

"""Built-in volume type properties."""

import typing as ty

from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_utils import uuidutils

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import quota
from cinder import rpc
from cinder import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)
QUOTAS = quota.QUOTAS
ENCRYPTION_IGNORED_FIELDS = ['volume_type_id', 'created_at', 'updated_at',
                             'deleted_at', 'encryption_id']
DEFAULT_VOLUME_TYPE = "__DEFAULT__"

MIN_SIZE_KEY = "provisioning:min_vol_size"
MAX_SIZE_KEY = "provisioning:max_vol_size"


def create(context,
           name,
           extra_specs=None,
           is_public=True,
           projects=None,
           description=None):
    """Creates volume types."""
    extra_specs = extra_specs or {}
    projects = projects or []
    elevated = context if context.is_admin else context.elevated()
    try:
        type_ref = db.volume_type_create(elevated,
                                         dict(name=name,
                                              extra_specs=extra_specs,
                                              is_public=is_public,
                                              description=description),
                                         projects=projects)
    except db_exc.DBError:
        LOG.exception('DB error:')
        raise exception.VolumeTypeCreateFailed(name=name,
                                               extra_specs=extra_specs)
    return type_ref


def update(context, id, name, description, is_public=None):
    """Update volume type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    old_volume_type = get_volume_type(elevated, id)
    try:
        db.volume_type_update(elevated, id,
                              dict(name=name, description=description,
                                   is_public=is_public))
        # Rename resource in quota if volume type name is changed.
        if name:
            old_type_name = old_volume_type.get('name')
            if old_type_name != name:
                old_description = old_volume_type.get('description')
                old_public = old_volume_type.get('is_public')
                try:
                    QUOTAS.update_quota_resource(elevated,
                                                 old_type_name,
                                                 name)
                # Rollback the updated information to the original
                except db_exc.DBError:
                    db.volume_type_update(elevated, id,
                                          dict(name=old_type_name,
                                               description=old_description,
                                               is_public=old_public))
                    raise
    except db_exc.DBError:
        LOG.exception('DB error:')
        raise exception.VolumeTypeUpdateFailed(id=id)


def destroy(context, id):
    """Marks volume types as deleted.

    There must exist at least one volume type (i.e. the default type) in
    the deployment.
    This method achieves that by ensuring:
    1) the default_volume_type is set and is a valid one
    2) the type requested to delete isn't the default type

    :raises VolumeTypeDefaultDeletionError: when the type requested to
                                            delete is the default type
    """
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)

    projects_with_default_type = db.get_all_projects_with_default_type(
        context.elevated(), id)
    if len(projects_with_default_type) > 0:
        # don't allow delete if the type requested is a project default
        project_list = [p.project_id for p in projects_with_default_type]
        LOG.exception('Default type with %(volume_type_id)s is associated '
                      'with projects %(projects)s',
                      {'volume_type_id': id,
                       'projects': project_list})
        raise exception.VolumeTypeDefaultDeletionError(volume_type_id=id)

    # Default type *must* be set in order to delete any volume type.
    # If the default isn't set, the following call will raise
    # VolumeTypeDefaultMisconfiguredError exception which will error out the
    # delete operation.
    default_type = get_default_volume_type()
    # don't allow delete if the type requested is the conf default type
    if id == default_type.get('id'):
        raise exception.VolumeTypeDefaultDeletionError(volume_type_id=id)

    elevated = context if context.is_admin else context.elevated()
    return db.volume_type_destroy(elevated, id)


def get_all_types(context, inactive=0, filters=None, marker=None,
                  limit=None, sort_keys=None, sort_dirs=None,
                  offset=None, list_result=False):
    """Get all non-deleted volume_types.

    Pass true as argument if you want deleted volume types returned also.

    """
    vol_types = db.volume_type_get_all(context, inactive, filters=filters,
                                       marker=marker, limit=limit,
                                       sort_keys=sort_keys,
                                       sort_dirs=sort_dirs, offset=offset,
                                       list_result=list_result)
    return vol_types


def get_all_types_by_group(context, group_id):
    """Get all volume_types in a group."""
    vol_types = db.volume_type_get_all_by_group(context, group_id)
    return vol_types


def get_volume_type(ctxt, id, expected_fields=None):
    """Retrieves single volume type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.volume_type_get(ctxt, id, expected_fields=expected_fields)


def get_by_name_or_id(context, identity):
    """Retrieves volume type by id or name"""
    if uuidutils.is_uuid_like(identity):
        # both name and id can be in uuid format
        try:
            return get_volume_type(context, identity)
        except exception.VolumeTypeNotFound:
            try:
                # A user can create a type with the name in a UUID format,
                # so here we check for the uuid-like name.
                return get_volume_type_by_name(context, identity)
            except exception.VolumeTypeNotFoundByName:
                raise exception.VolumeTypeNotFound(volume_type_id=identity)
    return get_volume_type_by_name(context, identity)


def get_volume_type_by_name(context, name):
    """Retrieves single volume type by name."""
    if name is None:
        msg = _("name cannot be None")
        raise exception.InvalidVolumeType(reason=msg)

    return db.volume_type_get_by_name(context, name)


def get_default_volume_type(contxt=None):
    """Get the default volume type.

    :raises VolumeTypeDefaultMisconfiguredError: when the configured default
                                                 is not found
    """

    if contxt:
        project_default = db.project_default_volume_type_get(
            contxt, contxt.project_id)
        if project_default:
            return get_volume_type(contxt, project_default.volume_type_id)
    name = CONF.default_volume_type
    ctxt = context.get_admin_context()
    vol_type = {}
    try:
        vol_type = get_volume_type_by_name(ctxt, name)
    except (exception.VolumeTypeNotFoundByName, exception.InvalidVolumeType):
        # Couldn't find volume type with the name in default_volume_type
        # flag, record this issue and raise exception
        LOG.exception('Default volume type is not found. '
                      'Please check default_volume_type config:')
        raise exception.VolumeTypeDefaultMisconfiguredError(
            volume_type_name=name)

    return vol_type


def get_volume_type_extra_specs(volume_type_id, key=False):
    volume_type = get_volume_type(context.get_admin_context(),
                                  volume_type_id)
    extra_specs = volume_type['extra_specs']
    if key:
        if extra_specs.get(key):
            return extra_specs.get(key)
        else:
            return False
    else:
        return extra_specs


def is_public_volume_type(context, volume_type_id):
    """Return is_public boolean value of volume type"""
    volume_type = db.volume_type_get(context, volume_type_id)
    return volume_type['is_public']


@utils.if_notifications_enabled
def notify_about_volume_type_access_usage(context,
                                          volume_type_id,
                                          project_id,
                                          event_suffix,
                                          host=None):
    """Notify about successful usage type-access-(add/remove) command.

    :param context: security context
    :param volume_type_id: volume type uuid
    :param project_id: tenant uuid
    :param event_suffix: name of called operation access-(add/remove)
    :param host: hostname
    """
    notifier_info = {'volume_type_id': volume_type_id,
                     'project_id': project_id}

    if not host:
        host = CONF.host

    notifier = rpc.get_notifier("volume_type_project", host)
    notifier.info(context,
                  'volume_type_project.%s' % event_suffix,
                  notifier_info)


def add_volume_type_access(context, volume_type_id, project_id):
    """Add access to volume type for project_id."""
    if volume_type_id is None:
        msg = _("volume_type_id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    if is_public_volume_type(elevated, volume_type_id):
        msg = _("Type access modification is not applicable to public volume "
                "type.")
        raise exception.InvalidVolumeType(reason=msg)

    db.volume_type_access_add(elevated, volume_type_id, project_id)

    notify_about_volume_type_access_usage(context,
                                          volume_type_id,
                                          project_id,
                                          'access.add')


def remove_volume_type_access(context, volume_type_id, project_id):
    """Remove access to volume type for project_id."""
    if volume_type_id is None:
        msg = _("volume_type_id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    elevated = context if context.is_admin else context.elevated()
    if is_public_volume_type(elevated, volume_type_id):
        msg = _("Type access modification is not applicable to public volume "
                "type.")
        raise exception.InvalidVolumeType(reason=msg)

    db.volume_type_access_remove(elevated, volume_type_id, project_id)

    notify_about_volume_type_access_usage(context,
                                          volume_type_id,
                                          project_id,
                                          'access.remove')


def is_encrypted(context: context.RequestContext,
                 volume_type_id: str) -> bool:
    return get_volume_type_encryption(context, volume_type_id) is not None


def get_volume_type_encryption(context, volume_type_id):
    if volume_type_id is None:
        return None

    encryption = db.volume_type_encryption_get(context, volume_type_id)
    return encryption


def get_volume_type_qos_specs(volume_type_id):
    """Get all qos specs for given volume type."""
    ctxt = context.get_admin_context()
    res = db.volume_type_qos_specs_get(ctxt,
                                       volume_type_id)
    return res


def volume_types_diff(context: context.RequestContext,
                      vol_type_id1,
                      vol_type_id2) -> ty.Tuple[dict, bool]:
    """Returns a 'diff' of two volume types and whether they are equal.

    Returns a tuple of (diff, equal), where 'equal' is a boolean indicating
    whether there is any difference, and 'diff' is a dictionary with the
    following format:

    .. code-block:: default

        {
            'extra_specs': {'key1': (value_in_1st_vol_type,
                                     value_in_2nd_vol_type),
                            'key2': (value_in_1st_vol_type,
                                     value_in_2nd_vol_type),
                            {...}}
            'qos_specs': {'key1': (value_in_1st_vol_type,
                                   value_in_2nd_vol_type),
                          'key2': (value_in_1st_vol_type,
                                   value_in_2nd_vol_type),
                          {...}}
            'encryption': {'cipher': (value_in_1st_vol_type,
                                      value_in_2nd_vol_type),
                          {'key_size': (value_in_1st_vol_type,
                                        value_in_2nd_vol_type),
                           {...}}
        }
    """
    def _fix_qos_specs(qos_specs):
        if qos_specs:
            qos_specs.pop('id', None)
            qos_specs.pop('name', None)
            qos_specs.update(qos_specs.pop('specs', {}))

    def _fix_encryption_specs(encryption):
        if encryption:
            encryption = dict(encryption)
            for param in ENCRYPTION_IGNORED_FIELDS:
                encryption.pop(param, None)
        return encryption

    def _dict_diff(dict1: ty.Optional[dict],
                   dict2: ty.Optional[dict]) -> ty.Tuple[dict, bool]:
        res = {}
        equal = True
        if dict1 is None:
            dict1 = {}
        if dict2 is None:
            dict2 = {}
        for k, v in dict1.items():
            res[k] = (v, dict2.get(k))
            if k not in dict2 or res[k][0] != res[k][1]:
                equal = False
        for k, v in dict2.items():
            res[k] = (dict1.get(k), v)
            if k not in dict1 or res[k][0] != res[k][1]:
                equal = False
        return (res, equal)

    all_equal = True
    diff = {}
    vol_type_data = []
    for vol_type_id in (vol_type_id1, vol_type_id2):
        if vol_type_id is None:
            specs = {'extra_specs': None,
                     'qos_specs': None,
                     'encryption': None}
        else:
            specs = {}
            vol_type = get_volume_type(context, vol_type_id)
            specs['extra_specs'] = vol_type.get('extra_specs')
            qos_specs = get_volume_type_qos_specs(vol_type_id)
            specs['qos_specs'] = qos_specs.get('qos_specs')
            _fix_qos_specs(specs['qos_specs'])
            specs['encryption'] = get_volume_type_encryption(context,
                                                             vol_type_id)
            specs['encryption'] = _fix_encryption_specs(specs['encryption'])
        vol_type_data.append(specs)

    diff['extra_specs'], equal = _dict_diff(vol_type_data[0]['extra_specs'],
                                            vol_type_data[1]['extra_specs'])
    if not equal:
        all_equal = False
    diff['qos_specs'], equal = _dict_diff(vol_type_data[0]['qos_specs'],
                                          vol_type_data[1]['qos_specs'])
    if not equal:
        all_equal = False
    diff['encryption'], equal = _dict_diff(vol_type_data[0]['encryption'],
                                           vol_type_data[1]['encryption'])
    if not equal:
        all_equal = False

    return (diff, all_equal)


def volume_types_encryption_changed(context, vol_type_id1, vol_type_id2):
    """Return whether encryptions of two volume types are same."""
    def _get_encryption(enc):
        enc = dict(enc)
        for param in ENCRYPTION_IGNORED_FIELDS:
            enc.pop(param, None)
        return enc

    enc1 = get_volume_type_encryption(context, vol_type_id1)
    enc2 = get_volume_type_encryption(context, vol_type_id2)

    enc1_filtered = _get_encryption(enc1) if enc1 else None
    enc2_filtered = _get_encryption(enc2) if enc2 else None
    return enc1_filtered != enc2_filtered


def provision_filter_on_size(context, volume_type, size):
    """This function filters volume provisioning requests on size limits.

    If a volume type has provisioning size min/max set, this filter
    will ensure that the volume size requested is within the size
    limits specified in the volume type.
    """

    if not volume_type:
        volume_type = get_default_volume_type()

    if volume_type:
        size_int = int(size)
        extra_specs = volume_type.get('extra_specs', {})
        min_size = extra_specs.get(MIN_SIZE_KEY)
        if min_size and size_int < int(min_size):
            msg = _("Specified volume size of '%(req_size)d' is less "
                    "than the minimum required size of '%(min_size)s' "
                    "for volume type '%(vol_type)s'.") % {
                'req_size': size_int, 'min_size': min_size,
                'vol_type': volume_type['name']
            }
            raise exception.InvalidInput(reason=msg)

        max_size = extra_specs.get(MAX_SIZE_KEY)
        if max_size and size_int > int(max_size):
            msg = _("Specified volume size of '%(req_size)d' is "
                    "greater than the maximum allowable size of "
                    "'%(max_size)s' for volume type '%(vol_type)s'."
                    ) % {
                'req_size': size_int, 'max_size': max_size,
                'vol_type': volume_type['name']}
            raise exception.InvalidInput(reason=msg)
