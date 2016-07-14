#    Copyright 2015 Intel Corp.
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
from oslo_utils import versionutils
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields

LOG = logging.getLogger(__name__)


@base.CinderObjectRegistry.register
class Service(base.CinderPersistentObject, base.CinderObject,
              base.CinderObjectDictCompat,
              base.CinderComparableObject):
    # Version 1.0: Initial version
    # Version 1.1: Add rpc_current_version and object_current_version fields
    # Version 1.2: Add get_minimum_rpc_version() and get_minimum_obj_version()
    # Version 1.3: Add replication fields
    VERSION = '1.3'

    fields = {
        'id': fields.IntegerField(),
        'host': fields.StringField(nullable=True),
        'binary': fields.StringField(nullable=True),
        'topic': fields.StringField(nullable=True),
        'report_count': fields.IntegerField(default=0),
        'disabled': fields.BooleanField(default=False, nullable=True),
        'availability_zone': fields.StringField(nullable=True,
                                                default='cinder'),
        'disabled_reason': fields.StringField(nullable=True),

        'modified_at': fields.DateTimeField(nullable=True),
        'rpc_current_version': fields.StringField(nullable=True),
        'object_current_version': fields.StringField(nullable=True),

        # Replication properties
        'replication_status': c_fields.ReplicationStatusField(nullable=True),
        'frozen': fields.BooleanField(default=False),
        'active_backend_id': fields.StringField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, service, db_service):
        for name, field in service.fields.items():
            value = db_service.get(name)
            if isinstance(field, fields.IntegerField):
                value = value or 0
            elif isinstance(field, fields.DateTimeField):
                value = value or None
            service[name] = value

        service._context = context
        service.obj_reset_changes()
        return service

    @base.remotable_classmethod
    def get_by_host_and_topic(cls, context, host, topic):
        db_service = db.service_get_by_host_and_topic(context, host, topic)
        return cls._from_db_object(context, cls(context), db_service)

    @base.remotable_classmethod
    def get_by_args(cls, context, host, binary_key):
        db_service = db.service_get_by_args(context, host, binary_key)
        return cls._from_db_object(context, cls(context), db_service)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.cinder_obj_get_changes()
        db_service = db.service_create(self._context, updates)
        self._from_db_object(self._context, self, db_service)

    @base.remotable
    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            db.service_update(self._context, self.id, updates)
            self.obj_reset_changes()

    @base.remotable
    def destroy(self):
        with self.obj_as_admin():
            db.service_destroy(self._context, self.id)

    @classmethod
    def _get_minimum_version(cls, attribute, context, binary):
        services = ServiceList.get_all_by_binary(context, binary)
        min_ver = None
        min_ver_str = None
        for s in services:
            ver_str = getattr(s, attribute)
            if ver_str is None:
                # FIXME(dulek) None in *_current_version means that this
                # service is in Liberty version, so we must assume this is the
                # lowest one. We use handy and easy to remember token to
                # indicate that. This may go away as soon as we drop
                # compatibility with Liberty, possibly in early N.
                return 'liberty'
            ver = versionutils.convert_version_to_int(ver_str)
            if min_ver is None or ver < min_ver:
                min_ver = ver
                min_ver_str = ver_str

        return min_ver_str

    @base.remotable_classmethod
    def get_minimum_rpc_version(cls, context, binary):
        return cls._get_minimum_version('rpc_current_version', context, binary)

    @base.remotable_classmethod
    def get_minimum_obj_version(cls, context, binary):
        return cls._get_minimum_version('object_current_version', context,
                                        binary)


@base.CinderObjectRegistry.register
class ServiceList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    # Version 1.1: Service object 1.2
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('Service'),
    }

    @base.remotable_classmethod
    def get_all(cls, context, filters=None):
        services = db.service_get_all(context, filters)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)

    @base.remotable_classmethod
    def get_all_by_topic(cls, context, topic, disabled=None):
        services = db.service_get_all_by_topic(context, topic,
                                               disabled=disabled)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)

    @base.remotable_classmethod
    def get_all_by_binary(cls, context, binary, disabled=None):
        services = db.service_get_all_by_binary(context, binary,
                                                disabled=disabled)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)
