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


from oslo_config import cfg
from oslo_db import exception as db_exc
from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _, _LE


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def create(context,
           name,
           extra_specs=None,
           is_public=True,
           projects=None,
           description=None):
    """Creates volume types."""
    extra_specs = extra_specs or {}
    projects = projects or []
    try:
        type_ref = db.volume_type_create(context,
                                         dict(name=name,
                                              extra_specs=extra_specs,
                                              is_public=is_public,
                                              description=description),
                                         projects=projects)
    except db_exc.DBError:
        LOG.exception(_LE('DB error:'))
        raise exception.VolumeTypeCreateFailed(name=name,
                                               extra_specs=extra_specs)
    return type_ref


def update(context, id, name, description, is_public=None):
    """Update volume type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    try:
        type_updated = db.volume_type_update(context,
                                             id,
                                             dict(name=name,
                                                  description=description,
                                                  is_public=is_public))
    except db_exc.DBError:
        LOG.exception(_LE('DB error:'))
        raise exception.VolumeTypeUpdateFailed(id=id)
    return type_updated


def destroy(context, id):
    """Marks volume types as deleted."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    else:
        db.volume_type_destroy(context, id)


def get_all_types(context, inactive=0, search_opts=None):
    """Get all non-deleted volume_types.

    Pass true as argument if you want deleted volume types returned also.

    """
    search_opts = search_opts or {}
    filters = {}

    if 'is_public' in search_opts:
        filters['is_public'] = search_opts['is_public']
        del search_opts['is_public']

    vol_types = db.volume_type_get_all(context, inactive, filters=filters)

    if search_opts:
        LOG.debug("Searching by: %s", search_opts)

        def _check_extra_specs_match(vol_type, searchdict):
            for k, v in searchdict.items():
                if (k not in vol_type['extra_specs'].keys()
                        or vol_type['extra_specs'][k] != v):
                    return False
            return True

        # search_option to filter_name mapping.
        filter_mapping = {'extra_specs': _check_extra_specs_match}

        result = {}
        for type_name, type_args in vol_types.items():
            # go over all filters in the list
            for opt, values in search_opts.items():
                try:
                    filter_func = filter_mapping[opt]
                except KeyError:
                    # no such filter - ignore it, go to next filter
                    continue
                else:
                    if filter_func(type_args, values):
                        result[type_name] = type_args
                        break
        vol_types = result
    return vol_types


def get_volume_type(ctxt, id, expected_fields=None):
    """Retrieves single volume type by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.volume_type_get(ctxt, id, expected_fields=expected_fields)


def get_volume_type_by_name(context, name):
    """Retrieves single volume type by name."""
    if name is None:
        msg = _("name cannot be None")
        raise exception.InvalidVolumeType(reason=msg)

    return db.volume_type_get_by_name(context, name)


def get_default_volume_type():
    """Get the default volume type."""
    name = CONF.default_volume_type
    vol_type = {}

    if name is not None:
        ctxt = context.get_admin_context()
        try:
            vol_type = get_volume_type_by_name(ctxt, name)
        except exception.VolumeTypeNotFoundByName:
            # Couldn't find volume type with the name in default_volume_type
            # flag, record this issue and move on
            # TODO(zhiteng) consider add notification to warn admin
            LOG.exception(_LE('Default volume type is not found. '
                          'Please check default_volume_type config:'))

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


def add_volume_type_access(context, volume_type_id, project_id):
    """Add access to volume type for project_id."""
    if volume_type_id is None:
        msg = _("volume_type_id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    if is_public_volume_type(context, volume_type_id):
        msg = _("Type access modification is not applicable to public volume "
                "type.")
        raise exception.InvalidVolumeType(reason=msg)
    return db.volume_type_access_add(context, volume_type_id, project_id)


def remove_volume_type_access(context, volume_type_id, project_id):
    """Remove access to volume type for project_id."""
    if volume_type_id is None:
        msg = _("volume_type_id cannot be None")
        raise exception.InvalidVolumeType(reason=msg)
    if is_public_volume_type(context, volume_type_id):
        msg = _("Type access modification is not applicable to public volume "
                "type.")
        raise exception.InvalidVolumeType(reason=msg)
    return db.volume_type_access_remove(context, volume_type_id, project_id)


def is_encrypted(context, volume_type_id):
    return get_volume_type_encryption(context, volume_type_id) is not None


def get_volume_type_encryption(context, volume_type_id):
    if volume_type_id is None:
        return None

    encryption = db.volume_type_encryption_get(context, volume_type_id)
    return encryption


def get_volume_type_qos_specs(volume_type_id):
    ctxt = context.get_admin_context()
    res = db.volume_type_qos_specs_get(ctxt,
                                       volume_type_id)
    return res


def volume_types_diff(context, vol_type_id1, vol_type_id2):
    """Returns a 'diff' of two volume types and whether they are equal.

    Returns a tuple of (diff, equal), where 'equal' is a boolean indicating
    whether there is any difference, and 'diff' is a dictionary with the
    following format:
    {'extra_specs': {'key1': (value_in_1st_vol_type, value_in_2nd_vol_type),
                     'key2': (value_in_1st_vol_type, value_in_2nd_vol_type),
                     ...}
     'qos_specs': {'key1': (value_in_1st_vol_type, value_in_2nd_vol_type),
                   'key2': (value_in_1st_vol_type, value_in_2nd_vol_type),
                   ...}
     'encryption': {'cipher': (value_in_1st_vol_type, value_in_2nd_vol_type),
                   {'key_size': (value_in_1st_vol_type, value_in_2nd_vol_type),
                    ...}
    """
    def _fix_qos_specs(qos_specs):
        if qos_specs:
            qos_specs.pop('id', None)
            qos_specs.pop('name', None)
            qos_specs.update(qos_specs.pop('specs', {}))

    def _fix_encryption_specs(encryption):
        if encryption:
            encryption = dict(encryption)
            for param in ['volume_type_id', 'created_at', 'updated_at',
                          'deleted_at']:
                encryption.pop(param, None)
        return encryption

    def _dict_diff(dict1, dict2):
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
