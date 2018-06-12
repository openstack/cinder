# Copyright (c) 2016 Red Hat, Inc.
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

from oslo_versionedobjects import fields

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields
from cinder import utils


@base.CinderObjectRegistry.register
class Cluster(base.CinderPersistentObject, base.CinderObject,
              base.CinderComparableObject):
    """Cluster Versioned Object.

    Method get_by_id supports as additional named arguments:
        - get_services: If we want to load all services from this cluster.
        - services_summary: If we want to load num_nodes and num_down_nodes
                            fields.
        - is_up: Boolean value to filter based on the cluster's up status.
        - read_deleted: Filtering based on delete status. Default value "no".
        - Any other cluster field will be used as a filter.
    """
    # Version 1.0: Initial version
    # Version 1.1: Add replication fields
    VERSION = '1.1'
    OPTIONAL_FIELDS = ('num_hosts', 'num_down_hosts', 'services')

    # NOTE(geguileo): We don't want to expose race_preventer field at the OVO
    # layer since it is only meant for the DB layer internal mechanism to
    # prevent races.
    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=False),
        'binary': fields.StringField(nullable=False),
        'disabled': fields.BooleanField(default=False, nullable=True),
        'disabled_reason': fields.StringField(nullable=True),
        'num_hosts': fields.IntegerField(default=0, read_only=True),
        'num_down_hosts': fields.IntegerField(default=0, read_only=True),
        'last_heartbeat': fields.DateTimeField(nullable=True, read_only=True),
        'services': fields.ObjectField('ServiceList', nullable=True,
                                       read_only=True),
        # Replication properties
        'replication_status': c_fields.ReplicationStatusField(nullable=True),
        'frozen': fields.BooleanField(default=False),
        'active_backend_id': fields.StringField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        """Make a cluster representation compatible with a target version."""
        # Convert all related objects
        super(Cluster, self).obj_make_compatible(primitive, target_version)

        # Before v1.1 we didn't have relication fields so we have to remove
        # them.
        if target_version == '1.0':
            for obj_field in ('replication_status', 'frozen',
                              'active_backend_id'):
                primitive.pop(obj_field, None)

    @classmethod
    def _get_expected_attrs(cls, context, *args, **kwargs):
        """Return expected attributes when getting a cluster.

        Expected attributes depend on whether we are retrieving all related
        services as well as if we are getting the services summary.
        """
        expected_attrs = []
        if kwargs.get('get_services'):
            expected_attrs.append('services')
        if kwargs.get('services_summary'):
            expected_attrs.extend(('num_hosts', 'num_down_hosts'))
        return expected_attrs

    @staticmethod
    def _from_db_object(context, cluster, db_cluster, expected_attrs=None):
        """Fill cluster OVO fields from cluster ORM instance."""
        expected_attrs = expected_attrs or tuple()
        for name, field in cluster.fields.items():
            # The only field that cannot be assigned using setattr is services,
            # because it is an ObjectField.   So we don't assign the value if
            # it's a non expected optional field or if it's services field.
            if ((name in Cluster.OPTIONAL_FIELDS
                 and name not in expected_attrs) or name == 'services'):
                continue
            value = getattr(db_cluster, name)
            setattr(cluster, name, value)

        cluster._context = context
        if 'services' in expected_attrs:
            cluster.services = base.obj_make_list(
                context,
                objects.ServiceList(context),
                objects.Service,
                db_cluster.services)

        cluster.obj_reset_changes()
        return cluster

    def obj_load_attr(self, attrname):
        """Lazy load services attribute."""
        # NOTE(geguileo): We only allow lazy loading services to raise
        # awareness of the high cost of lazy loading num_hosts and
        # num_down_hosts, so if we are going to need this information we should
        # be certain we really need it and it should loaded when retrieving the
        # data from the DB the first time we read the OVO.
        if attrname != 'services':
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        self.services = objects.ServiceList.get_all(
            self._context, {'cluster_name': self.name})

        self.obj_reset_changes(fields=('services',))

    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already created'))
        updates = self.cinder_obj_get_changes()
        if updates:
            for field in self.OPTIONAL_FIELDS:
                if field in updates:
                    raise exception.ObjectActionError(
                        action='create', reason=_('%s assigned') % field)

        db_cluster = db.cluster_create(self._context, updates)
        self._from_db_object(self._context, self, db_cluster)

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            for field in self.OPTIONAL_FIELDS:
                if field in updates:
                    raise exception.ObjectActionError(
                        action='save', reason=_('%s changed') % field)
            db.cluster_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.cluster_destroy(self._context, self.id)
        for field, value in updated_values.items():
            setattr(self, field, value)
        self.obj_reset_changes(updated_values.keys())

    @property
    def is_up(self):
        return (self.last_heartbeat and
                self.last_heartbeat >= utils.service_expired_time(True))

    def reset_service_replication(self):
        """Reset service replication flags on promotion.

        When an admin promotes a cluster, each service member requires an
        update to maintain database consistency.
        """
        actions = {
            'replication_status': 'enabled',
            'active_backend_id': None,
        }

        expectations = {
            'cluster_name': self.name,
        }

        db.conditional_update(self._context, objects.Service.model,
                              actions, expectations)


@base.CinderObjectRegistry.register
class ClusterList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {'objects': fields.ListOfObjectsField('Cluster')}

    @classmethod
    def get_all(cls, context, is_up=None, get_services=False,
                services_summary=False, read_deleted='no', **filters):
        """Get all clusters that match the criteria.

        :param is_up: Boolean value to filter based on the cluster's up status.
        :param get_services: If we want to load all services from this cluster.
        :param services_summary: If we want to load num_nodes and
                                 num_down_nodes fields.
        :param read_deleted: Filtering based on delete status. Default value is
                             "no".
        :param filters: Field based filters in the form of key/value.
        """

        expected_attrs = Cluster._get_expected_attrs(
            context,
            get_services=get_services,
            services_summary=services_summary)

        clusters = db.cluster_get_all(context, is_up=is_up,
                                      get_services=get_services,
                                      services_summary=services_summary,
                                      read_deleted=read_deleted,
                                      **filters)
        return base.obj_make_list(context, cls(context), Cluster, clusters,
                                  expected_attrs=expected_attrs)
