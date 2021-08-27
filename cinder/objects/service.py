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
from oslo_utils import uuidutils
from oslo_utils import versionutils
from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields
from cinder import utils


LOG = logging.getLogger(__name__)


@base.CinderObjectRegistry.register
class Service(base.CinderPersistentObject, base.CinderObject,
              base.CinderObjectDictCompat, base.CinderComparableObject,
              base.ClusteredObject):
    # Version 1.0: Initial version
    # Version 1.1: Add rpc_current_version and object_current_version fields
    # Version 1.2: Add get_minimum_rpc_version() and get_minimum_obj_version()
    # Version 1.3: Add replication fields
    # Version 1.4: Add cluster fields
    # Version 1.5: Add UUID field
    # Version 1.6: Modify UUID field to be not nullable
    VERSION = '1.6'

    OPTIONAL_FIELDS = ('cluster',)

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'id': fields.IntegerField(),
        'host': fields.StringField(nullable=True),
        'binary': fields.StringField(nullable=True),
        'cluster_name': fields.StringField(nullable=True),
        'cluster': fields.ObjectField('Cluster', nullable=True,
                                      read_only=True),
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

        'uuid': fields.StringField(),
    }

    @staticmethod
    def _from_db_object(context, service, db_service, expected_attrs=None):
        expected_attrs = expected_attrs or []
        for name, field in service.fields.items():
            if ((name == 'uuid' and not db_service.get(name)) or
                    name in service.OPTIONAL_FIELDS):
                continue

            value = db_service.get(name)
            if isinstance(field, fields.IntegerField):
                value = value or 0
            elif isinstance(field, fields.DateTimeField):
                value = value or None
            service[name] = value

        service._context = context
        if 'cluster' in expected_attrs:
            db_cluster = db_service.get('cluster')
            # If this service doesn't belong to a cluster the cluster field in
            # the ORM instance will have value of None.
            if db_cluster:
                service.cluster = objects.Cluster(context)
                objects.Cluster._from_db_object(context, service.cluster,
                                                db_cluster)
            else:
                service.cluster = None

        service.obj_reset_changes()

        return service

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        # NOTE(geguileo): We only have 1 optional field, so we don't need to
        # confirm that we are loading the cluster.
        # If this service doesn't belong to a cluster (cluster_name is empty),
        # then cluster field will be None.
        if self.cluster_name:
            self.cluster = objects.Cluster.get_by_id(self._context, None,
                                                     name=self.cluster_name)
        else:
            self.cluster = None
        self.obj_reset_changes(fields=(attrname,))

    @classmethod
    def get_by_host_and_topic(cls, context, host, topic, disabled=False):
        db_service = db.service_get(context, disabled=disabled, host=host,
                                    topic=topic)
        return cls._from_db_object(context, cls(context), db_service)

    @classmethod
    def get_by_args(cls, context, host, binary_key):
        db_service = db.service_get(context, host=host, binary=binary_key)
        return cls._from_db_object(context, cls(context), db_service)

    @classmethod
    def get_by_uuid(cls, context, service_uuid):
        db_service = db.service_get_by_uuid(context, service_uuid)
        return cls._from_db_object(context, cls(), db_service)

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.cinder_obj_get_changes()
        if 'cluster' in updates:
            raise exception.ObjectActionError(
                action='create', reason=_('cluster assigned'))
        if 'uuid' not in updates:
            updates['uuid'] = uuidutils.generate_uuid()
            self.uuid = updates['uuid']

        db_service = db.service_create(self._context, updates)
        self._from_db_object(self._context, self, db_service)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if 'cluster' in updates:
            raise exception.ObjectActionError(
                action='save', reason=_('cluster changed'))
        if updates:
            db.service_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.service_destroy(self._context, self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())

    @classmethod
    def _get_minimum_version(cls, attribute, context, binary):
        services = ServiceList.get_all_by_binary(context, binary)
        min_ver = None
        min_ver_str = None
        for s in services:
            ver_str = getattr(s, attribute)
            if ver_str is None:
                # NOTE(dulek) None in *_current_version means that this
                # service is in Liberty version, which we now don't provide
                # backward compatibility to.
                msg = _('Service %s is in Liberty version. We do not provide '
                        'backward compatibility with Liberty now, so you '
                        'need to upgrade it, release by release if live '
                        'upgrade is required. After upgrade you may need to '
                        'remove any stale service records via '
                        '"cinder-manage service remove".') % s.binary
                raise exception.ServiceTooOld(msg)
            ver = versionutils.convert_version_to_int(ver_str)
            if min_ver is None or ver < min_ver:
                min_ver = ver
                min_ver_str = ver_str

        return min_ver_str

    @classmethod
    def get_minimum_rpc_version(cls, context, binary):
        return cls._get_minimum_version('rpc_current_version', context, binary)

    @classmethod
    def get_minimum_obj_version(cls, context, binary=None):
        return cls._get_minimum_version('object_current_version', context,
                                        binary)

    @property
    def is_up(self):
        """Check whether a service is up based on last heartbeat."""
        return (self.updated_at and
                self.updated_at >= utils.service_expired_time(True))


@base.CinderObjectRegistry.register
class ServiceList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    # Version 1.1: Service object 1.2
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('Service'),
    }

    @classmethod
    def get_all(cls, context, filters=None):
        services = db.service_get_all(context, **(filters or {}))
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)

    @classmethod
    def get_all_by_topic(cls, context, topic, disabled=None):
        services = db.service_get_all(context, topic=topic, disabled=disabled)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)

    @classmethod
    def get_all_by_binary(cls, context, binary, disabled=None):
        services = db.service_get_all(context, binary=binary,
                                      disabled=disabled)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  services)
