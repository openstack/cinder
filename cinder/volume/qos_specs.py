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


from oslo.config import cfg
from oslo.db import exception as db_exc

from cinder import context
from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder.openstack.common import log as logging
from cinder.volume import volume_types


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

CONTROL_LOCATION = ['front-end', 'back-end', 'both']


def _verify_prepare_qos_specs(specs, create=True):
    """Check if 'consumer' value in qos specs is valid.

    Verify 'consumer' value in qos_specs is valid, raise
    exception if not. Assign default value to 'consumer', which
    is 'back-end' if input is empty.

    :params create a flag indicate if specs being verified is
    for create. If it's false, that means specs is for update,
    so that there's no need to add 'consumer' if that wasn't in
    specs.
    """

    # Check control location, if it's missing in input, assign default
    # control location: 'front-end'
    if not specs:
        specs = {}
    # remove 'name' since we will handle that elsewhere.
    if specs.get('name', None):
        del specs['name']
    try:
        if specs['consumer'] not in CONTROL_LOCATION:
            msg = _("Valid consumer of QoS specs are: %s") % CONTROL_LOCATION
            raise exception.InvalidQoSSpecs(reason=msg)
    except KeyError:
        # Default consumer is back-end, i.e Cinder volume service
        if create:
            specs['consumer'] = 'back-end'

    return specs


def create(context, name, specs=None):
    """Creates qos_specs.

    :param specs dictionary that contains specifications for QoS
          e.g. {'consumer': 'front-end',
                'total_iops_sec': 1000,
                'total_bytes_sec': 1024000}
    """
    _verify_prepare_qos_specs(specs)

    values = dict(name=name, qos_specs=specs)

    LOG.debug("Dict for qos_specs: %s" % values)

    try:
        qos_specs_ref = db.qos_specs_create(context, values)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.QoSSpecsCreateFailed(name=name,
                                             qos_specs=specs)
    return qos_specs_ref


def update(context, qos_specs_id, specs):
    """Update qos specs.

    :param specs dictionary that contains key/value pairs for updating
    existing specs.
        e.g. {'consumer': 'front-end',
              'total_iops_sec': 500,
              'total_bytes_sec': 512000,}
    """
    # need to verify specs in case 'consumer' is passed
    _verify_prepare_qos_specs(specs, create=False)
    LOG.debug('qos_specs.update(): specs %s' % specs)
    try:
        res = db.qos_specs_update(context, qos_specs_id, specs)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        raise exception.QoSSpecsUpdateFailed(specs_id=qos_specs_id,
                                             qos_specs=specs)

    return res


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

    # check if there is any entity associated with this qos specs
    res = db.qos_specs_associations_get(context, qos_specs_id)
    if res and not force:
        raise exception.QoSSpecsInUse(specs_id=qos_specs_id)
    elif res and force:
        # remove all association
        db.qos_specs_disassociate_all(context, qos_specs_id)

    db.qos_specs_delete(context, qos_specs_id)


def delete_keys(context, qos_specs_id, keys):
    """Marks specified key of target qos specs as deleted."""
    if qos_specs_id is None:
        msg = _("id cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    # make sure qos_specs_id is valid
    get_qos_specs(context, qos_specs_id)
    for key in keys:
        db.qos_specs_item_delete(context, qos_specs_id, key)


def get_associations(context, specs_id):
    """Get all associations of given qos specs."""
    try:
        # query returns a list of volume types associated with qos specs
        associates = db.qos_specs_associations_get(context, specs_id)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        msg = _('Failed to get all associations of '
                'qos specs %s') % specs_id
        LOG.warn(msg)
        raise exception.CinderException(message=msg)

    result = []
    for vol_type in associates:
        member = dict(association_type='volume_type')
        member.update(dict(name=vol_type['name']))
        member.update(dict(id=vol_type['id']))
        result.append(member)

    return result


def associate_qos_with_type(context, specs_id, type_id):
    """Associate qos_specs with volume type.

    Associate target qos specs with specific volume type. Would raise
    following exceptions:
        VolumeTypeNotFound  - if volume type doesn't exist;
        QoSSpecsNotFound  - if qos specs doesn't exist;
        InvalidVolumeType  - if volume type is already associated with
                             qos specs other than given one.
        QoSSpecsAssociateFailed -  if there was general DB error
    :param specs_id: qos specs ID to associate with
    :param type_id: volume type ID to associate with
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
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        LOG.warn(_('Failed to associate qos specs '
                   '%(id)s with type: %(vol_type_id)s') %
                 dict(id=specs_id, vol_type_id=type_id))
        raise exception.QoSSpecsAssociateFailed(specs_id=specs_id,
                                                type_id=type_id)


def disassociate_qos_specs(context, specs_id, type_id):
    """Disassociate qos_specs from volume type."""
    try:
        get_qos_specs(context, specs_id)
        db.qos_specs_disassociate(context, specs_id, type_id)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        LOG.warn(_('Failed to disassociate qos specs '
                   '%(id)s with type: %(vol_type_id)s') %
                 dict(id=specs_id, vol_type_id=type_id))
        raise exception.QoSSpecsDisassociateFailed(specs_id=specs_id,
                                                   type_id=type_id)


def disassociate_all(context, specs_id):
    """Disassociate qos_specs from all entities."""
    try:
        get_qos_specs(context, specs_id)
        db.qos_specs_disassociate_all(context, specs_id)
    except db_exc.DBError as e:
        LOG.exception(_('DB error: %s') % e)
        LOG.warn(_('Failed to disassociate qos specs %s.') % specs_id)
        raise exception.QoSSpecsDisassociateFailed(specs_id=specs_id,
                                                   type_id=None)


def get_all_specs(context, inactive=False, search_opts=None):
    """Get all non-deleted qos specs.

    Pass inactive=True as argument and deleted volume types would return
    as well.
    """
    search_opts = search_opts or {}
    qos_specs = db.qos_specs_get_all(context, inactive)

    if search_opts:
        LOG.debug("Searching by: %s" % search_opts)

        def _check_specs_match(qos_specs, searchdict):
            for k, v in searchdict.iteritems():
                if ((k not in qos_specs['specs'].keys() or
                     qos_specs['specs'][k] != v)):
                    return False
            return True

        # search_option to filter_name mapping.
        filter_mapping = {'qos_specs': _check_specs_match}

        result = {}
        for name, args in qos_specs.iteritems():
            # go over all filters in the list
            for opt, values in search_opts.iteritems():
                try:
                    filter_func = filter_mapping[opt]
                except KeyError:
                    # no such filter - ignore it, go to next filter
                    continue
                else:
                    if filter_func(args, values):
                        result[name] = args
                        break
        qos_specs = result
    return qos_specs


def get_qos_specs(ctxt, id):
    """Retrieves single qos specs by id."""
    if id is None:
        msg = _("id cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    if ctxt is None:
        ctxt = context.get_admin_context()

    return db.qos_specs_get(ctxt, id)


def get_qos_specs_by_name(context, name):
    """Retrieves single qos specs by name."""
    if name is None:
        msg = _("name cannot be None")
        raise exception.InvalidQoSSpecs(reason=msg)

    return db.qos_specs_get_by_name(context, name)
