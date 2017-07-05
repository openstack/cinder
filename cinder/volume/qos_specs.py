# Copyright (c) 2013 eBay Inc.
# Copyright (c) 2013 OpenStack Foundation
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

"""The QoS Specs Implementation"""


from oslo_db import exception as db_exc
from oslo_log import log as logging

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.volume import volume_types


LOG = logging.getLogger(__name__)

CONTROL_LOCATION = ['front-end', 'back-end', 'both']


def create(context, name, specs=None):
    """Creates qos_specs.

    :param specs dictionary that contains specifications for QoS
          e.g. {'consumer': 'front-end',
                'total_iops_sec': 1000,
                'total_bytes_sec': 1024000}
    """
    consumer = specs.get('consumer')
    if consumer:
        # If we need to modify specs, copy so we don't cause unintended
        # consequences for the caller
        specs = specs.copy()
        del specs['consumer']

    values = dict(name=name, consumer=consumer, specs=specs)

    LOG.debug("Dict for qos_specs: %s", values)
    qos_spec = objects.QualityOfServiceSpecs(context, **values)
    qos_spec.create()
    return qos_spec


def update(context, qos_specs_id, specs):
    """Update qos specs.

    :param specs: dictionary that contains key/value pairs for updating
                  existing specs.
          e.g. {'consumer': 'front-end',
                'total_iops_sec': 500,
                'total_bytes_sec': 512000,}
    """
    LOG.debug('qos_specs.update(): specs %s', specs)

    try:
        qos_spec = objects.QualityOfServiceSpecs.get_by_id(context,
                                                           qos_specs_id)

        if 'consumer' in specs:
            qos_spec.consumer = specs['consumer']
            # If we need to modify specs, copy so we don't cause unintended
            # consequences for the caller
            specs = specs.copy()
            del specs['consumer']

        # Update any values in specs dict
        qos_spec.specs.update(specs)

        qos_spec.save()
    except db_exc.DBError:
        LOG.exception('DB error:')
        raise exception.QoSSpecsUpdateFailed(specs_id=qos_specs_id,
                                             qos_specs=specs)

    return qos_spec


def delete(context, qos_specs_id, force=False):
    """Marks qos specs as deleted.

    'force' parameter is a flag to determine whether should destroy
    should continue when there were entities associated with the qos specs.
    force=True indicates caller would like to mark qos specs as deleted
    even if there was entities associate with target qos specs.
    Trying to delete a qos specs still associated with entities will
    cause QoSSpecsInUse exception if force=False (default).
    """
    if qos_specs_id is None:
        msg = _("id cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    qos_spec = objects.QualityOfServiceSpecs.get_by_id(
        context, qos_specs_id)

    qos_spec.destroy(force)


def delete_keys(context, qos_specs_id, keys):
    """Marks specified key of target qos specs as deleted."""
    if qos_specs_id is None:
        msg = _("id cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    qos_spec = objects.QualityOfServiceSpecs.get_by_id(context, qos_specs_id)

    # Previous behavior continued to delete keys until it hit first unset one,
    # so for now will mimic that. In the future it would be useful to have all
    # or nothing deletion of keys (or at least delete all set keys),
    # especially since order of keys from CLI to API is not preserved currently
    try:
        for key in keys:
            try:
                del qos_spec.specs[key]
            except KeyError:
                raise exception.QoSSpecsKeyNotFound(
                    specs_key=key, specs_id=qos_specs_id)
    finally:
        qos_spec.save()


def get_associations(context, qos_specs_id):
    """Get all associations of given qos specs."""
    try:
        types = objects.VolumeTypeList.get_all_types_for_qos(context,
                                                             qos_specs_id)
    except db_exc.DBError:
        LOG.exception('DB error:')
        msg = _('Failed to get all associations of '
                'qos specs %s') % qos_specs_id
        LOG.warning(msg)
        raise exception.CinderException(message=msg)

    result = []
    for vol_type in types:
        result.append({
            'association_type': 'volume_type',
            'name': vol_type.name,
            'id': vol_type.id
        })

    return result


def associate_qos_with_type(context, specs_id, type_id):
    """Associate qos_specs with volume type.

    Associate target qos specs with specific volume type.

    :param specs_id: qos specs ID to associate with
    :param type_id: volume type ID to associate with
    :raises VolumeTypeNotFound: if volume type doesn't exist
    :raises QoSSpecsNotFound: if qos specs doesn't exist
    :raises InvalidVolumeType: if volume type is already associated
                               with qos specs other than given one.
    :raises QoSSpecsAssociateFailed: if there was general DB error
    """
    try:
        get_qos_specs(context, specs_id)
        res = volume_types.get_volume_type_qos_specs(type_id)
        if res.get('qos_specs', None):
            if res['qos_specs'].get('id') != specs_id:
                msg = (_("Type %(type_id)s is already associated with another "
                         "qos specs: %(qos_specs_id)s") %
                       {'type_id': type_id,
                        'qos_specs_id': res['qos_specs']['id']})
                raise exception.InvalidVolumeType(reason=msg)
        else:
            db.qos_specs_associate(context, specs_id, type_id)
    except db_exc.DBError:
        LOG.exception('DB error:')
        LOG.warning('Failed to associate qos specs '
                    '%(id)s with type: %(vol_type_id)s',
                    dict(id=specs_id, vol_type_id=type_id))
        raise exception.QoSSpecsAssociateFailed(specs_id=specs_id,
                                                type_id=type_id)


def disassociate_qos_specs(context, specs_id, type_id):
    """Disassociate qos_specs from volume type."""
    try:
        get_qos_specs(context, specs_id)
        db.qos_specs_disassociate(context, specs_id, type_id)
    except db_exc.DBError:
        LOG.exception('DB error:')
        LOG.warning('Failed to disassociate qos specs '
                    '%(id)s with type: %(vol_type_id)s',
                    dict(id=specs_id, vol_type_id=type_id))
        raise exception.QoSSpecsDisassociateFailed(specs_id=specs_id,
                                                   type_id=type_id)


def disassociate_all(context, specs_id):
    """Disassociate qos_specs from all entities."""
    try:
        get_qos_specs(context, specs_id)
        db.qos_specs_disassociate_all(context, specs_id)
    except db_exc.DBError:
        LOG.exception('DB error:')
        LOG.warning('Failed to disassociate qos specs %s.', specs_id)
        raise exception.QoSSpecsDisassociateFailed(specs_id=specs_id,
                                                   type_id=None)


def get_all_specs(context, filters=None, marker=None, limit=None, offset=None,
                  sort_keys=None, sort_dirs=None):
    """Get all non-deleted qos specs."""
    return objects.QualityOfServiceSpecsList.get_all(
        context, filters=filters, marker=marker, limit=limit, offset=offset,
        sort_keys=sort_keys, sort_dirs=sort_dirs)


def get_qos_specs(ctxt, spec_id):
    """Retrieves single qos specs by id."""
    if spec_id is None:
        msg = _("id cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    if ctxt is None:
        ctxt = context.get_admin_context()

    return objects.QualityOfServiceSpecs.get_by_id(ctxt, spec_id)
