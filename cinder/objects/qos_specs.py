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

from oslo_db import exception as db_exc
from oslo_log import log as logging

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields
from oslo_versionedobjects import fields

LOG = logging.getLogger(__name__)


@base.CinderObjectRegistry.register
class QualityOfServiceSpecs(base.CinderPersistentObject,
                            base.CinderObject,
                            base.CinderObjectDictCompat,
                            base.CinderComparableObject):
    # Version
    #   1.0: Initial version
    VERSION = "1.0"

    OPTIONAL_FIELDS = ['volume_types']

    fields = {
        'id': fields.UUIDField(),
        'name': fields.StringField(),
        'consumer': c_fields.QoSConsumerField(
            default=c_fields.QoSConsumerValues.BACK_END),
        'specs': fields.DictOfNullableStringsField(nullable=True),
        'volume_types': fields.ObjectField('VolumeTypeList', nullable=True),
    }

    def __init__(self, *args, **kwargs):
        super(QualityOfServiceSpecs, self).__init__(*args, **kwargs)
        self._init_specs = {}

    def __setattr__(self, name, value):
        try:
            super(QualityOfServiceSpecs, self).__setattr__(name, value)
        except ValueError:
            if name == 'consumer':
                # Give more descriptive error message for invalid 'consumer'
                msg = (_("Valid consumer of QoS specs are: %s") %
                       c_fields.QoSConsumerField())
                raise exception.InvalidQoSSpecs(reason=msg)
            else:
                raise

    def obj_reset_changes(self, fields=None, recursive=False):
        super(QualityOfServiceSpecs, self).obj_reset_changes(fields, recursive)
        if fields is None or 'specs' in fields:
            self._init_specs = self.specs.copy() if self.specs else {}

    def obj_what_changed(self):
        changes = super(QualityOfServiceSpecs, self).obj_what_changed()

        # Do comparison of what's in the dict vs. reference to the specs object
        if self.obj_attr_is_set('id'):
            if self.specs != self._init_specs:
                changes.add('specs')
            else:
                # If both dicts are equal don't consider anything gets changed
                if 'specs' in changes:
                    changes.remove('specs')

        return changes

    def obj_get_changes(self):
        changes = super(QualityOfServiceSpecs, self).obj_get_changes()
        if 'specs' in changes:
            # For specs, we only want what has changed in the dictionary,
            # because otherwise we'll individually overwrite the DB value for
            # every key in 'specs' even if it hasn't changed
            specs_changes = {}
            for key, val in self.specs.items():
                if val != self._init_specs.get(key):
                    specs_changes[key] = val
            changes['specs'] = specs_changes

            specs_keys_removed = (set(self._init_specs.keys()) -
                                  set(self.specs.keys()))
            if specs_keys_removed:
                # Special key notifying which specs keys have been deleted
                changes['specs_keys_removed'] = specs_keys_removed

        return changes

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'volume_types':
            self.volume_types = objects.VolumeTypeList.get_all_types_for_qos(
                self._context, self.id)

    @classmethod
    def _from_db_object(cls, context, qos_spec, db_qos_spec,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []

        for name, field in qos_spec.fields.items():
            if name not in cls.OPTIONAL_FIELDS:
                value = db_qos_spec.get(name)
                # 'specs' could be null if only a consumer is given, so make
                # it an empty dict instead of None
                if not value and isinstance(field, fields.DictOfStringsField):
                    value = {}
                setattr(qos_spec, name, value)

        if 'volume_types' in expected_attrs:
            volume_types = objects.VolumeTypeList.get_all_types_for_qos(
                context, db_qos_spec['id'])
            qos_spec.volume_types = volume_types

        qos_spec._context = context
        qos_spec.obj_reset_changes()
        return qos_spec

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.cinder_obj_get_changes()

        try:
            create_ret = db.qos_specs_create(self._context, updates)
        except db_exc.DBDataError:
            msg = _('Error writing field to database')
            LOG.exception(msg)
            raise exception.Invalid(msg)
        except db_exc.DBError:
            LOG.exception('DB error occurred when creating QoS specs.')
            raise exception.QoSSpecsCreateFailed(name=self.name,
                                                 qos_specs=self.specs)
        # Save ID with the object
        updates['id'] = create_ret['id']
        self._from_db_object(self._context, self, updates)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'specs_keys_removed' in updates.keys():
                for specs_key_to_remove in updates['specs_keys_removed']:
                    db.qos_specs_item_delete(
                        self._context, self.id, specs_key_to_remove)
                del updates['specs_keys_removed']
            db.qos_specs_update(self._context, self.id, updates)

        self.obj_reset_changes()

    def destroy(self, force=False):
        """Deletes the QoS spec.

        :param force: when force is True, all volume_type mappings for this QoS
                      are deleted.  When force is False and volume_type
                      mappings still exist, a QoSSpecsInUse exception is thrown
        """
        if self.volume_types:
            if not force:
                raise exception.QoSSpecsInUse(specs_id=self.id)
            # remove all association
            db.qos_specs_disassociate_all(self._context, self.id)
        updated_values = db.qos_specs_delete(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())


@base.CinderObjectRegistry.register
class QualityOfServiceSpecsList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('QualityOfServiceSpecs'),
    }

    @classmethod
    def get_all(cls, context, *args, **kwargs):
        specs = db.qos_specs_get_all(context, *args, **kwargs)
        return base.obj_make_list(context, cls(context),
                                  objects.QualityOfServiceSpecs, specs)
