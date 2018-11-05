# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
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

"""
SQLAlchemy models for cinder data.
"""

from oslo_config import cfg
from oslo_db.sqlalchemy import models
from oslo_utils import timeutils
from sqlalchemy import and_, func, select
from sqlalchemy import bindparam
from sqlalchemy import Column, Integer, String, Text, schema, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean, UniqueConstraint
from sqlalchemy.orm import backref, column_property, relationship, validates


CONF = cfg.CONF
BASE = declarative_base()


class CinderBase(models.TimestampMixin,
                 models.ModelBase):
    """Base class for Cinder Models."""

    __table_args__ = {'mysql_engine': 'InnoDB'}

    # TODO(rpodolyaka): reuse models.SoftDeleteMixin in the next stage
    #                   of implementing of BP db-cleanup
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)
    metadata = None

    @staticmethod
    def delete_values():
        return {'deleted': True,
                'deleted_at': timeutils.utcnow()}

    def delete(self, session):
        """Delete this object."""
        updated_values = self.delete_values()
        self.update(updated_values)
        self.save(session=session)
        return updated_values


class Service(BASE, CinderBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    # We want to overwrite default updated_at definition so we timestamp at
    # creation as well, so we only need to check updated_at for the heartbeat
    updated_at = Column(DateTime, default=timeutils.utcnow,
                        onupdate=timeutils.utcnow)
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    availability_zone = Column(String(255), default='cinder')
    disabled_reason = Column(String(255))
    # adding column modified_at to contain timestamp
    # for manual enable/disable of cinder services
    # updated_at column will now contain timestamps for
    # periodic updates
    modified_at = Column(DateTime)

    # Version columns to support rolling upgrade. These report the max RPC API
    # and objects versions that the manager of the service is able to support.
    rpc_current_version = Column(String(36))
    object_current_version = Column(String(36))

    # replication_status can be: enabled, disabled, not-capable, error,
    # failed-over or not-configured
    replication_status = Column(String(36), default="not-capable")
    active_backend_id = Column(String(255))
    frozen = Column(Boolean, nullable=False, default=False)

    cluster = relationship('Cluster',
                           backref='services',
                           foreign_keys=cluster_name,
                           primaryjoin='and_('
                                       'Service.cluster_name == Cluster.name,'
                                       'Service.deleted == False)')


class Cluster(BASE, CinderBase):
    """Represents a cluster of hosts."""
    __tablename__ = 'clusters'
    # To remove potential races on creation we have a constraint set on name
    # and race_preventer fields, and we set value on creation to 0, so 2
    # clusters with the same name will fail this constraint.  On deletion we
    # change this field to the same value as the id which will be unique and
    # will not conflict with the creation of another cluster with the same
    # name.
    __table_args__ = (UniqueConstraint('name', 'binary', 'race_preventer'),
                      CinderBase.__table_args__)

    id = Column(Integer, primary_key=True)
    # NOTE(geguileo): Name is constructed in the same way that Server.host but
    # using cluster configuration option instead of host.
    name = Column(String(255), nullable=False)
    binary = Column(String(255), nullable=False)
    disabled = Column(Boolean, default=False)
    disabled_reason = Column(String(255))
    race_preventer = Column(Integer, nullable=False, default=0)

    replication_status = Column(String(36), default="not-capable")
    active_backend_id = Column(String(255))
    frozen = Column(Boolean, nullable=False, default=False)

    # Last heartbeat reported by any of the services of this cluster.  This is
    # not deferred since we always want to load this field.
    last_heartbeat = column_property(
        select([func.max(Service.updated_at)]).
        where(and_(Service.cluster_name == name, ~Service.deleted)).
        correlate_except(Service), deferred=False)

    # Number of existing services for this cluster
    num_hosts = column_property(
        select([func.count(Service.id)]).
        where(and_(Service.cluster_name == name, ~Service.deleted)).
        correlate_except(Service),
        group='services_summary', deferred=True)

    # Number of services that are down for this cluster
    num_down_hosts = column_property(
        select([func.count(Service.id)]).
        where(and_(Service.cluster_name == name,
                   ~Service.deleted,
                   Service.updated_at < bindparam('expired'))).
        correlate_except(Service),
        group='services_summary', deferred=True)

    @staticmethod
    def delete_values():
        return {'race_preventer': Cluster.id,
                'deleted': True,
                'deleted_at': timeutils.utcnow()}


class ConsistencyGroup(BASE, CinderBase):
    """Represents a consistencygroup."""
    __tablename__ = 'consistencygroups'
    id = Column(String(36), primary_key=True)

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    cluster_name = Column(String(255), nullable=True)
    host = Column(String(255))
    availability_zone = Column(String(255))
    name = Column(String(255))
    description = Column(String(255))
    volume_type_id = Column(String(255))
    status = Column(String(255))
    cgsnapshot_id = Column(String(36))
    source_cgid = Column(String(36))


class Group(BASE, CinderBase):
    """Represents a generic volume group."""
    __tablename__ = 'groups'
    id = Column(String(36), primary_key=True)

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    cluster_name = Column(String(255))
    host = Column(String(255))
    availability_zone = Column(String(255))
    name = Column(String(255))
    description = Column(String(255))
    status = Column(String(255))
    group_type_id = Column(String(36))
    group_snapshot_id = Column(String(36))
    source_group_id = Column(String(36))

    replication_status = Column(String(255))


class CGSnapshot(BASE, CinderBase):
    """Represents a cgsnapshot."""
    __tablename__ = 'cgsnapshots'
    id = Column(String(36), primary_key=True)

    consistencygroup_id = Column(String(36), index=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    name = Column(String(255))
    description = Column(String(255))
    status = Column(String(255))

    consistencygroup = relationship(
        ConsistencyGroup,
        backref="cgsnapshots",
        foreign_keys=consistencygroup_id,
        primaryjoin='CGSnapshot.consistencygroup_id == ConsistencyGroup.id')


class GroupSnapshot(BASE, CinderBase):
    """Represents a group snapshot."""
    __tablename__ = 'group_snapshots'
    id = Column(String(36), primary_key=True)

    group_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(255))
    project_id = Column(String(255))

    name = Column(String(255))
    description = Column(String(255))
    status = Column(String(255))
    group_type_id = Column(String(36))

    group = relationship(
        Group,
        backref="group_snapshots",
        foreign_keys=group_id,
        primaryjoin='GroupSnapshot.group_id == Group.id')


class Volume(BASE, CinderBase):
    """Represents a block storage device that can be attached to a vm."""
    __tablename__ = 'volumes'
    __table_args__ = (Index('volumes_service_uuid_idx',
                            'deleted', 'service_uuid'),
                      CinderBase.__table_args__)

    id = Column(String(36), primary_key=True)
    _name_id = Column(String(36))  # Don't access/modify this directly!

    @property
    def name_id(self):
        return self.id if not self._name_id else self._name_id

    @name_id.setter
    def name_id(self, value):
        self._name_id = value

    @property
    def name(self):
        return CONF.volume_name_template % self.name_id

    ec2_id = Column(Integer)
    user_id = Column(String(255))
    project_id = Column(String(255))

    snapshot_id = Column(String(36))

    cluster_name = Column(String(255), nullable=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    size = Column(Integer)
    availability_zone = Column(String(255))  # TODO(vish): foreign key?
    status = Column(String(255))  # TODO(vish): enum?
    attach_status = Column(String(255))  # TODO(vish): enum
    migration_status = Column(String(255))

    scheduled_at = Column(DateTime)
    launched_at = Column(DateTime)
    terminated_at = Column(DateTime)

    display_name = Column(String(255))
    display_description = Column(String(255))

    provider_location = Column(String(255))
    provider_auth = Column(String(255))
    provider_geometry = Column(String(255))
    provider_id = Column(String(255))

    volume_type_id = Column(String(36))
    source_volid = Column(String(36))
    encryption_key_id = Column(String(36))

    consistencygroup_id = Column(String(36), index=True)
    group_id = Column(String(36), index=True)

    bootable = Column(Boolean, default=False)
    multiattach = Column(Boolean, default=False)

    replication_status = Column(String(255))
    replication_extended_status = Column(String(255))
    replication_driver_data = Column(String(255))

    previous_status = Column(String(255))

    consistencygroup = relationship(
        ConsistencyGroup,
        backref="volumes",
        foreign_keys=consistencygroup_id,
        primaryjoin='Volume.consistencygroup_id == ConsistencyGroup.id')

    group = relationship(
        Group,
        backref="volumes",
        foreign_keys=group_id,
        primaryjoin='Volume.group_id == Group.id')

    service_uuid = Column(String(36), index=True)
    service = relationship(Service,
                           backref="volumes",
                           foreign_keys=service_uuid,
                           primaryjoin='Volume.service_uuid == Service.uuid')
    shared_targets = Column(Boolean, default=True)  # make an FK of service?


class VolumeMetadata(BASE, CinderBase):
    """Represents a metadata key/value pair for a volume."""
    __tablename__ = 'volume_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False,
                       index=True)
    volume = relationship(Volume, backref="volume_metadata",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'VolumeMetadata.volume_id == Volume.id,'
                          'VolumeMetadata.deleted == False)')


class VolumeAdminMetadata(BASE, CinderBase):
    """Represents an administrator metadata key/value pair for a volume."""
    __tablename__ = 'volume_admin_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False,
                       index=True)
    volume = relationship(Volume, backref="volume_admin_metadata",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'VolumeAdminMetadata.volume_id == Volume.id,'
                          'VolumeAdminMetadata.deleted == False)')


class VolumeAttachment(BASE, CinderBase):
    """Represents a volume attachment for a vm."""
    __tablename__ = 'volume_attachment'
    id = Column(String(36), primary_key=True)

    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False,
                       index=True)
    volume = relationship(Volume, backref="volume_attachment",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'VolumeAttachment.volume_id == Volume.id,'
                          'VolumeAttachment.deleted == False)')
    instance_uuid = Column(String(36))
    attached_host = Column(String(255))
    mountpoint = Column(String(255))
    attach_time = Column(DateTime)
    detach_time = Column(DateTime)
    attach_status = Column(String(255))
    attach_mode = Column(String(255))
    connection_info = Column(Text)
    # Stores a serialized json dict of host connector information from brick.
    connector = Column(Text)


class VolumeType(BASE, CinderBase):
    """Represent possible volume_types of volumes offered."""
    __tablename__ = "volume_types"
    id = Column(String(36), primary_key=True)
    name = Column(String(255))
    description = Column(String(255))
    # A reference to qos_specs entity
    qos_specs_id = Column(String(36),
                          ForeignKey('quality_of_service_specs.id'),
                          index=True)
    is_public = Column(Boolean, default=True)
    volumes = relationship(Volume,
                           backref=backref('volume_type', uselist=False),
                           foreign_keys=id,
                           primaryjoin='and_('
                           'Volume.volume_type_id == VolumeType.id, '
                           'VolumeType.deleted == False)')


class GroupType(BASE, CinderBase):
    """Represent possible group_types of groups offered."""
    __tablename__ = "group_types"
    id = Column(String(36), primary_key=True)
    name = Column(String(255))
    description = Column(String(255))
    is_public = Column(Boolean, default=True)
    groups = relationship(Group,
                          backref=backref('group_type', uselist=False),
                          foreign_keys=id,
                          primaryjoin='and_('
                          'Group.group_type_id == GroupType.id, '
                          'GroupType.deleted == False)')


class GroupVolumeTypeMapping(BASE, CinderBase):
    """Represent mapping between groups and volume_types."""
    __tablename__ = "group_volume_type_mapping"
    id = Column(Integer, primary_key=True, nullable=False)
    volume_type_id = Column(String(36),
                            ForeignKey('volume_types.id'),
                            nullable=False, index=True)
    group_id = Column(String(36),
                      ForeignKey('groups.id'),
                      nullable=False, index=True)

    group = relationship(
        Group,
        backref="volume_types",
        foreign_keys=group_id,
        primaryjoin='and_('
        'GroupVolumeTypeMapping.group_id == Group.id,'
        'GroupVolumeTypeMapping.deleted == False)'
    )


class VolumeTypeProjects(BASE, CinderBase):
    """Represent projects associated volume_types."""
    __tablename__ = "volume_type_projects"
    __table_args__ = (schema.UniqueConstraint(
        "volume_type_id", "project_id", "deleted",
        name="uniq_volume_type_projects0volume_type_id0project_id0deleted"),
        CinderBase.__table_args__)
    id = Column(Integer, primary_key=True)
    volume_type_id = Column(String, ForeignKey('volume_types.id'),
                            nullable=False)
    project_id = Column(String(255))
    deleted = Column(Integer, default=0)

    volume_type = relationship(
        VolumeType,
        backref="projects",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'VolumeTypeProjects.volume_type_id == VolumeType.id,'
        'VolumeTypeProjects.deleted == 0)')


class GroupTypeProjects(BASE, CinderBase):
    """Represent projects associated group_types."""
    __tablename__ = "group_type_projects"
    __table_args__ = (schema.UniqueConstraint(
        "group_type_id", "project_id", "deleted",
        name="uniq_group_type_projects0group_type_id0project_id0deleted"),
        CinderBase.__table_args__)
    id = Column(Integer, primary_key=True)
    group_type_id = Column(String, ForeignKey('group_types.id'),
                           nullable=False)
    project_id = Column(String(255))

    group_type = relationship(
        GroupType,
        backref="projects",
        foreign_keys=group_type_id,
        primaryjoin='and_('
        'GroupTypeProjects.group_type_id == GroupType.id,'
        'GroupTypeProjects.deleted == False)')


class VolumeTypeExtraSpecs(BASE, CinderBase):
    """Represents additional specs as key/value pairs for a volume_type."""
    __tablename__ = 'volume_type_extra_specs'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_type_id = Column(String(36),
                            ForeignKey('volume_types.id'),
                            nullable=False, index=True)
    volume_type = relationship(
        VolumeType,
        backref="extra_specs",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'VolumeTypeExtraSpecs.volume_type_id == VolumeType.id,'
        'VolumeTypeExtraSpecs.deleted == False)'
    )


class GroupTypeSpecs(BASE, CinderBase):
    """Represents additional specs as key/value pairs for a group_type."""
    __tablename__ = 'group_type_specs'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    group_type_id = Column(String(36),
                           ForeignKey('group_types.id'),
                           nullable=False, index=True)
    group_type = relationship(
        GroupType,
        backref="group_specs",
        foreign_keys=group_type_id,
        primaryjoin='and_('
        'GroupTypeSpecs.group_type_id == GroupType.id,'
        'GroupTypeSpecs.deleted == False)'
    )


class QualityOfServiceSpecs(BASE, CinderBase):
    """Represents QoS specs as key/value pairs.

    QoS specs is standalone entity that can be associated/disassociated
    with volume types (one to many relation).  Adjacency list relationship
    pattern is used in this model in order to represent following hierarchical
    data with in flat table, e.g, following structure:

    .. code-block:: none

      qos-specs-1  'Rate-Limit'
           |
           +------>  consumer = 'front-end'
           +------>  total_bytes_sec = 1048576
           +------>  total_iops_sec = 500

      qos-specs-2  'QoS_Level1'
           |
           +------>  consumer = 'back-end'
           +------>  max-iops =  1000
           +------>  min-iops = 200

      is represented by:

        id       specs_id       key                  value
      ------     --------   -------------            -----
      UUID-1     NULL       QoSSpec_Name           Rate-Limit
      UUID-2     UUID-1       consumer             front-end
      UUID-3     UUID-1     total_bytes_sec        1048576
      UUID-4     UUID-1     total_iops_sec           500
      UUID-5     NULL       QoSSpec_Name           QoS_Level1
      UUID-6     UUID-5       consumer             back-end
      UUID-7     UUID-5       max-iops               1000
      UUID-8     UUID-5       min-iops               200
    """
    __tablename__ = 'quality_of_service_specs'
    id = Column(String(36), primary_key=True)
    specs_id = Column(String(36), ForeignKey(id), index=True)
    key = Column(String(255))
    value = Column(String(255))

    specs = relationship(
        "QualityOfServiceSpecs",
        cascade="all, delete-orphan",
        backref=backref("qos_spec", remote_side=id),
    )

    vol_types = relationship(
        VolumeType,
        backref=backref('qos_specs'),
        foreign_keys=id,
        primaryjoin='and_('
                    'or_(VolumeType.qos_specs_id == '
                    'QualityOfServiceSpecs.id,'
                    'VolumeType.qos_specs_id == '
                    'QualityOfServiceSpecs.specs_id),'
                    'QualityOfServiceSpecs.deleted == False)')


class VolumeGlanceMetadata(BASE, CinderBase):
    """Glance metadata for a bootable volume."""
    __tablename__ = 'volume_glance_metadata'
    id = Column(Integer, primary_key=True, nullable=False)
    volume_id = Column(String(36), ForeignKey('volumes.id'), index=True)
    snapshot_id = Column(String(36), ForeignKey('snapshots.id'), index=True)
    key = Column(String(255))
    value = Column(Text)
    volume = relationship(Volume, backref="volume_glance_metadata",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'VolumeGlanceMetadata.volume_id == Volume.id,'
                          'VolumeGlanceMetadata.deleted == False)')


class Quota(BASE, CinderBase):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then the
    default for the quota class is used.  If there is no row for a
    given quota class and resource, then the default for the
    deployment is used. If the row is present but the hard limit is
    Null, then the resource is unlimited.
    """

    __tablename__ = 'quotas'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255), index=True)

    resource = Column(String(255))
    hard_limit = Column(Integer, nullable=True)
    allocated = Column(Integer, default=0)


class QuotaClass(BASE, CinderBase):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    id = Column(Integer, primary_key=True)

    class_name = Column(String(255), index=True)

    resource = Column(String(255))
    hard_limit = Column(Integer, nullable=True)


class QuotaUsage(BASE, CinderBase):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255), index=True)
    resource = Column(String(300), index=True)

    in_use = Column(Integer)
    reserved = Column(Integer)

    @property
    def total(self):
        return self.in_use + self.reserved

    until_refresh = Column(Integer, nullable=True)


class Reservation(BASE, CinderBase):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    __table_args__ = (Index('reservations_deleted_expire_idx',
                            'deleted', 'expire'),
                      Index('reservations_deleted_uuid_idx',
                            'deleted', 'uuid'),
                      CinderBase.__table_args__)

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)

    usage_id = Column(Integer, ForeignKey('quota_usages.id'), nullable=True,
                      index=True)
    allocated_id = Column(Integer, ForeignKey('quotas.id'), nullable=True,
                          index=True)

    project_id = Column(String(255), index=True)
    resource = Column(String(255))

    delta = Column(Integer)
    expire = Column(DateTime, nullable=False)

    usage = relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='and_(Reservation.usage_id == QuotaUsage.id,'
                    'QuotaUsage.deleted == False)')
    quota = relationship(
        "Quota",
        foreign_keys=allocated_id,
        primaryjoin='and_(Reservation.allocated_id == Quota.id)')


class Snapshot(BASE, CinderBase):
    """Represents a snapshot of volume."""
    __tablename__ = 'snapshots'
    id = Column(String(36), primary_key=True)

    @property
    def name(self):
        return CONF.snapshot_name_template % self.id

    @property
    def volume_name(self):
        return self.volume.name  # pylint: disable=E1101

    user_id = Column(String(255))
    project_id = Column(String(255))

    volume_id = Column(String(36), index=True)
    cgsnapshot_id = Column(String(36), index=True)
    group_snapshot_id = Column(String(36), index=True)
    status = Column(String(255))
    progress = Column(String(255))
    volume_size = Column(Integer)

    display_name = Column(String(255))
    display_description = Column(String(255))

    encryption_key_id = Column(String(36))
    volume_type_id = Column(String(36))

    provider_location = Column(String(255))
    provider_id = Column(String(255))
    provider_auth = Column(String(255))

    volume = relationship(Volume, backref="snapshots",
                          foreign_keys=volume_id,
                          primaryjoin='Snapshot.volume_id == Volume.id')

    cgsnapshot = relationship(
        CGSnapshot,
        backref="snapshots",
        foreign_keys=cgsnapshot_id,
        primaryjoin='Snapshot.cgsnapshot_id == CGSnapshot.id')

    group_snapshot = relationship(
        GroupSnapshot,
        backref="snapshots",
        foreign_keys=group_snapshot_id,
        primaryjoin='Snapshot.group_snapshot_id == GroupSnapshot.id')


class SnapshotMetadata(BASE, CinderBase):
    """Represents a metadata key/value pair for a snapshot."""
    __tablename__ = 'snapshot_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    snapshot_id = Column(String(36),
                         ForeignKey('snapshots.id'),
                         nullable=False, index=True)
    snapshot = relationship(Snapshot, backref="snapshot_metadata",
                            foreign_keys=snapshot_id,
                            primaryjoin='and_('
                            'SnapshotMetadata.snapshot_id == Snapshot.id,'
                            'SnapshotMetadata.deleted == False)')


class Backup(BASE, CinderBase):
    """Represents a backup of a volume to Swift."""
    __tablename__ = 'backups'
    id = Column(String(36), primary_key=True)

    @property
    def name(self):
        return CONF.backup_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    volume_id = Column(String(36), nullable=False)
    host = Column(String(255))
    availability_zone = Column(String(255))
    display_name = Column(String(255))
    display_description = Column(String(255))
    container = Column(String(255))
    parent_id = Column(String(36))
    status = Column(String(255))
    fail_reason = Column(String(255))
    service_metadata = Column(String(255))
    service = Column(String(255))
    size = Column(Integer)
    object_count = Column(Integer)
    temp_volume_id = Column(String(36))
    temp_snapshot_id = Column(String(36))
    num_dependent_backups = Column(Integer)
    snapshot_id = Column(String(36))
    data_timestamp = Column(DateTime)
    restore_volume_id = Column(String(36))
    encryption_key_id = Column(String(36))

    @validates('fail_reason')
    def validate_fail_reason(self, key, fail_reason):
        return fail_reason and fail_reason[:255] or ''


class BackupMetadata(BASE, CinderBase):
    """Represents a metadata key/value pair for a backup."""
    __tablename__ = 'backup_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    backup_id = Column(String(36), ForeignKey('backups.id'), nullable=False,
                       index=True)
    backup = relationship(Backup, backref="backup_metadata",
                          foreign_keys=backup_id,
                          primaryjoin='and_('
                          'BackupMetadata.backup_id == Backup.id,'
                          'BackupMetadata.deleted == False)')


class Encryption(BASE, CinderBase):
    """Represents encryption requirement for a volume type.

    Encryption here is a set of performance characteristics describing
    cipher, provider, and key_size for a certain volume type.
    """

    __tablename__ = 'encryption'
    encryption_id = Column(String(36), primary_key=True)
    cipher = Column(String(255))
    key_size = Column(Integer)
    provider = Column(String(255))
    control_location = Column(String(255))
    volume_type_id = Column(String(36), ForeignKey('volume_types.id'))
    volume_type = relationship(
        VolumeType,
        backref="encryption",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'Encryption.volume_type_id == VolumeType.id,'
        'Encryption.deleted == False)'
    )


class Transfer(BASE, CinderBase):
    """Represents a volume transfer request."""
    __tablename__ = 'transfers'
    id = Column(String(36), primary_key=True)
    volume_id = Column(String(36), ForeignKey('volumes.id'), index=True)
    display_name = Column(String(255))
    salt = Column(String(255))
    crypt_hash = Column(String(255))
    expires_at = Column(DateTime)
    no_snapshots = Column(Boolean, default=False)
    source_project_id = Column(String(255), nullable=True)
    destination_project_id = Column(String(255), nullable=True)
    accepted = Column(Boolean, default=False)
    volume = relationship(Volume, backref="transfer",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'Transfer.volume_id == Volume.id,'
                          'Transfer.deleted == False)')


class DriverInitiatorData(BASE, models.TimestampMixin, models.ModelBase):
    """Represents private key-value pair specific an initiator for drivers"""
    __tablename__ = 'driver_initiator_data'
    __table_args__ = (
        schema.UniqueConstraint("initiator", "namespace", "key"),
        CinderBase.__table_args__)

    id = Column(Integer, primary_key=True, nullable=False)
    initiator = Column(String(255), index=True, nullable=False)
    namespace = Column(String(255), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(String(255))


class Message(BASE, CinderBase):
    """Represents a message"""
    __tablename__ = 'messages'
    id = Column(String(36), primary_key=True, nullable=False)
    project_id = Column(String(255), nullable=False)
    # Info/Error/Warning.
    message_level = Column(String(255), nullable=False)
    request_id = Column(String(255), nullable=True)
    resource_type = Column(String(255))
    # The UUID of the related resource.
    resource_uuid = Column(String(36), nullable=True)
    # Operation specific event ID.
    event_id = Column(String(255), nullable=False)
    # Message detail ID.
    detail_id = Column(String(10), nullable=True)
    # Operation specific action.
    action_id = Column(String(10), nullable=True)
    # After this time the message may no longer exist
    expires_at = Column(DateTime, nullable=True, index=True)


class ImageVolumeCacheEntry(BASE, models.ModelBase):
    """Represents an image volume cache entry"""
    __tablename__ = 'image_volume_cache_entries'

    id = Column(Integer, primary_key=True, nullable=False)
    host = Column(String(255), index=True, nullable=False)
    cluster_name = Column(String(255), nullable=True)
    image_id = Column(String(36), index=True, nullable=False)
    image_updated_at = Column(DateTime, nullable=False)
    volume_id = Column(String(36), nullable=False)
    size = Column(Integer, nullable=False)
    last_used = Column(DateTime, default=lambda: timeutils.utcnow())


class Worker(BASE, CinderBase):
    """Represents all resources that are being worked on by a node."""
    __tablename__ = 'workers'
    __table_args__ = (schema.UniqueConstraint('resource_type', 'resource_id'),
                      CinderBase.__table_args__)

    # We want to overwrite default updated_at definition so we timestamp at
    # creation as well
    updated_at = Column(DateTime, default=timeutils.utcnow,
                        onupdate=timeutils.utcnow)

    # Id added for convenience and speed on some operations
    id = Column(Integer, primary_key=True, autoincrement=True)

    # Type of the resource we are working on (Volume, Snapshot, Backup) it must
    # match the Versioned Object class name.
    resource_type = Column(String(40), primary_key=True, nullable=False)
    # UUID of the resource we are working on
    resource_id = Column(String(36), primary_key=True, nullable=False)

    # Status that should be cleaned on service failure
    status = Column(String(255), nullable=False)

    # Service that is currently processing the operation
    service_id = Column(Integer, nullable=True, index=True)

    # To prevent claiming and updating races
    race_preventer = Column(Integer, nullable=False, default=0)

    # This is a flag we don't need to store in the DB as it is only used when
    # we are doing the cleanup to let decorators know
    cleaning = False

    service = relationship(
        'Service',
        backref="workers",
        foreign_keys=service_id,
        primaryjoin='Worker.service_id == Service.id')


class AttachmentSpecs(BASE, CinderBase):
    """Represents attachment specs as k/v pairs for a volume_attachment.

    DO NOT USE - NOTHING SHOULD WRITE NEW DATA TO THIS TABLE

    The volume_attachment.connector column should be used instead.
    """

    __tablename__ = 'attachment_specs'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    attachment_id = Column(String(36), ForeignKey('volume_attachment.id'),
                           nullable=False, index=True)
    volume_attachment = relationship(
        VolumeAttachment,
        backref="attachment_specs",
        foreign_keys=attachment_id,
        primaryjoin='and_('
        'AttachmentSpecs.attachment_id == VolumeAttachment.id,'
        'AttachmentSpecs.deleted == False)'
    )
