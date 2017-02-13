#    Copyright 2015 Yahoo Inc.
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

from oslo_utils import versionutils

from cinder import db
from cinder import exception
from cinder.i18n import _
from cinder import objects
from cinder.objects import base
from cinder.objects import fields as c_fields
from oslo_versionedobjects import fields


@base.CinderObjectRegistry.register
class ConsistencyGroup(base.CinderPersistentObject, base.CinderObject,
                       base.CinderObjectDictCompat, base.ClusteredObject):
    # Version 1.0: Initial version
    # Version 1.1: Added cgsnapshots and volumes relationships
    # Version 1.2: Changed 'status' field to use ConsistencyGroupStatusField
    # Version 1.3: Added cluster fields
    # Version 1.4: Added from_group
    VERSION = '1.4'

    OPTIONAL_FIELDS = ('cgsnapshots', 'volumes', 'cluster')

    fields = {
        'id': fields.UUIDField(),
        'user_id': fields.StringField(),
        'project_id': fields.StringField(),
        'cluster_name': fields.StringField(nullable=True),
        'cluster': fields.ObjectField('Cluster', nullable=True,
                                      read_only=True),
        'host': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'name': fields.StringField(nullable=True),
        'description': fields.StringField(nullable=True),
        'volume_type_id': fields.StringField(nullable=True),
        'status': c_fields.ConsistencyGroupStatusField(nullable=True),
        'cgsnapshot_id': fields.UUIDField(nullable=True),
        'source_cgid': fields.UUIDField(nullable=True),
        'cgsnapshots': fields.ObjectField('CGSnapshotList', nullable=True),
        'volumes': fields.ObjectField('VolumeList', nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        """Make a CG representation compatible with a target version."""
        # Convert all related objects
        super(ConsistencyGroup, self).obj_make_compatible(primitive,
                                                          target_version)

        target_version = versionutils.convert_version_to_tuple(target_version)
        # Before v1.3 we didn't have cluster fields so we have to remove them.
        if target_version < (1, 3):
            for obj_field in ('cluster', 'cluster_name'):
                primitive.pop(obj_field, None)

    @classmethod
    def _from_db_object(cls, context, consistencygroup, db_consistencygroup,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for name, field in consistencygroup.fields.items():
            if name in cls.OPTIONAL_FIELDS:
                continue
            value = db_consistencygroup.get(name)
            setattr(consistencygroup, name, value)

        if 'cgsnapshots' in expected_attrs:
            cgsnapshots = base.obj_make_list(
                context, objects.CGSnapshotList(context),
                objects.CGSnapshot,
                db_consistencygroup['cgsnapshots'])
            consistencygroup.cgsnapshots = cgsnapshots

        if 'volumes' in expected_attrs:
            volumes = base.obj_make_list(
                context, objects.VolumeList(context),
                objects.Volume,
                db_consistencygroup['volumes'])
            consistencygroup.volumes = volumes

        if 'cluster' in expected_attrs:
            db_cluster = db_consistencygroup.get('cluster')
            # If this consistency group doesn't belong to a cluster the cluster
            # field in the ORM instance will have value of None.
            if db_cluster:
                consistencygroup.cluster = objects.Cluster(context)
                objects.Cluster._from_db_object(context,
                                                consistencygroup.cluster,
                                                db_cluster)
            else:
                consistencygroup.cluster = None

        consistencygroup._context = context
        consistencygroup.obj_reset_changes()
        return consistencygroup

    def create(self, cg_snap_id=None, cg_id=None):
        """Create a consistency group.

        If cg_snap_id or cg_id are specified then volume_type_id,
        availability_zone, and host will be taken from the source Consistency
        Group.
        """
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason=_('already_created'))
        updates = self.cinder_obj_get_changes()

        if 'cgsnapshots' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('cgsnapshots assigned'))

        if 'volumes' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason=_('volumes assigned'))

        if 'cluster' in updates:
            raise exception.ObjectActionError(
                action='create', reason=_('cluster assigned'))

        db_consistencygroups = db.consistencygroup_create(self._context,
                                                          updates,
                                                          cg_snap_id,
                                                          cg_id)
        self._from_db_object(self._context, self, db_consistencygroups)

    def from_group(self, group):
        """Convert a generic volume group object to a cg object."""
        self.id = group.id
        self.user_id = group.user_id
        self.project_id = group.project_id
        self.cluster_name = group.cluster_name
        self.host = group.host
        self.availability_zone = group.availability_zone
        self.name = group.name
        self.description = group.description
        self.volume_type_id = ""
        for v_type in group.volume_types:
            self.volume_type_id += v_type.id + ","
        self.status = group.status
        self.cgsnapshot_id = group.group_snapshot_id
        self.source_cgid = group.source_group_id

    def obj_load_attr(self, attrname):
        if attrname not in self.OPTIONAL_FIELDS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute %s not lazy-loadable') % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())

        if attrname == 'cgsnapshots':
            self.cgsnapshots = objects.CGSnapshotList.get_all_by_group(
                self._context, self.id)

        if attrname == 'volumes':
            self.volumes = objects.VolumeList.get_all_by_group(self._context,
                                                               self.id)

        # If this consistency group doesn't belong to a cluster (cluster_name
        # is empty), then cluster field will be None.
        if attrname == 'cluster':
            if self.cluster_name:
                self.cluster = objects.Cluster.get_by_id(
                    self._context, name=self.cluster_name)
            else:
                self.cluster = None

        self.obj_reset_changes(fields=[attrname])

    def save(self):
        updates = self.cinder_obj_get_changes()
        if updates:
            if 'cgsnapshots' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('cgsnapshots changed'))
            if 'volumes' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('volumes changed'))
            if 'cluster' in updates:
                raise exception.ObjectActionError(
                    action='save', reason=_('cluster changed'))

            db.consistencygroup_update(self._context, self.id, updates)
            self.obj_reset_changes()

    def destroy(self):
        with self.obj_as_admin():
            updated_values = db.consistencygroup_destroy(self._context,
                                                         self.id)
        self.update(updated_values)
        self.obj_reset_changes(updated_values.keys())


@base.CinderObjectRegistry.register
class ConsistencyGroupList(base.ObjectListBase, base.CinderObject):
    # Version 1.0: Initial version
    # Version 1.1: Add pagination support to consistency group
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('ConsistencyGroup')
    }

    @staticmethod
    def include_in_cluster(context, cluster, partial_rename=True, **filters):
        """Include all consistency groups matching the filters into a cluster.

        When partial_rename is set we will not set the cluster_name with
        cluster parameter value directly, we'll replace provided cluster_name
        or host filter value with cluster instead.

        This is useful when we want to replace just the cluster name but leave
        the backend and pool information as it is.  If we are using
        cluster_name to filter, we'll use that same DB field to replace the
        cluster value and leave the rest as it is.  Likewise if we use the host
        to filter.

        Returns the number of consistency groups that have been changed.
        """
        return db.consistencygroup_include_in_cluster(context, cluster,
                                                      partial_rename,
                                                      **filters)

    @classmethod
    def get_all(cls, context, filters=None, marker=None, limit=None,
                offset=None, sort_keys=None, sort_dirs=None):
        consistencygroups = db.consistencygroup_get_all(
            context, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context),
                                  objects.ConsistencyGroup,
                                  consistencygroups)

    @classmethod
    def get_all_by_project(cls, context, project_id, filters=None, marker=None,
                           limit=None, offset=None, sort_keys=None,
                           sort_dirs=None):
        consistencygroups = db.consistencygroup_get_all_by_project(
            context, project_id, filters=filters, marker=marker, limit=limit,
            offset=offset, sort_keys=sort_keys, sort_dirs=sort_dirs)
        return base.obj_make_list(context, cls(context),
                                  objects.ConsistencyGroup,
                                  consistencygroups)
