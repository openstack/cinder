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
from sqlalchemy import Column, Integer, String, Text, schema
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref, validates


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

    def delete(self, session):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)


class Service(BASE, CinderBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
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

    # Version columns to support rolling upgrade.
    # Current version is what the service is running now (i.e. minimum).
    # Available version is what the service can support (i.e. max).
    rpc_current_version = Column(String(36))
    rpc_available_version = Column(String(36))
    object_current_version = Column(String(36))
    object_available_version = Column(String(36))


class ConsistencyGroup(BASE, CinderBase):
    """Represents a consistencygroup."""
    __tablename__ = 'consistencygroups'
    id = Column(String(36), primary_key=True)

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    host = Column(String(255))
    availability_zone = Column(String(255))
    name = Column(String(255))
    description = Column(String(255))
    volume_type_id = Column(String(255))
    status = Column(String(255))
    cgsnapshot_id = Column(String(36))
    source_cgid = Column(String(36))


class Cgsnapshot(BASE, CinderBase):
    """Represents a cgsnapshot."""
    __tablename__ = 'cgsnapshots'
    id = Column(String(36), primary_key=True)

    consistencygroup_id = Column(String(36))
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    name = Column(String(255))
    description = Column(String(255))
    status = Column(String(255))

    consistencygroup = relationship(
        ConsistencyGroup,
        backref="cgsnapshots",
        foreign_keys=consistencygroup_id,
        primaryjoin='Cgsnapshot.consistencygroup_id == ConsistencyGroup.id')


class Volume(BASE, CinderBase):
    """Represents a block storage device that can be attached to a vm."""
    __tablename__ = 'volumes'
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

    consistencygroup_id = Column(String(36))

    deleted = Column(Boolean, default=False)
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


class VolumeMetadata(BASE, CinderBase):
    """Represents a metadata key/value pair for a volume."""
    __tablename__ = 'volume_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False)
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
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False)
    volume = relationship(Volume, backref="volume_admin_metadata",
                          foreign_keys=volume_id,
                          primaryjoin='and_('
                          'VolumeAdminMetadata.volume_id == Volume.id,'
                          'VolumeAdminMetadata.deleted == False)')


class VolumeAttachment(BASE, CinderBase):
    """Represents a volume attachment for a vm."""
    __tablename__ = 'volume_attachment'
    id = Column(String(36), primary_key=True)

    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=False)
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


class VolumeTypes(BASE, CinderBase):
    """Represent possible volume_types of volumes offered."""
    __tablename__ = "volume_types"
    id = Column(String(36), primary_key=True)
    name = Column(String(255))
    description = Column(String(255))
    # A reference to qos_specs entity
    qos_specs_id = Column(String(36),
                          ForeignKey('quality_of_service_specs.id'))
    is_public = Column(Boolean, default=True)
    volumes = relationship(Volume,
                           backref=backref('volume_type', uselist=False),
                           foreign_keys=id,
                           primaryjoin='and_('
                           'Volume.volume_type_id == VolumeTypes.id, '
                           'VolumeTypes.deleted == False)')


class VolumeTypeProjects(BASE, CinderBase):
    """Represent projects associated volume_types."""
    __tablename__ = "volume_type_projects"
    __table_args__ = (schema.UniqueConstraint(
        "volume_type_id", "project_id", "deleted",
        name="uniq_volume_type_projects0volume_type_id0project_id0deleted"),
    )
    id = Column(Integer, primary_key=True)
    volume_type_id = Column(Integer, ForeignKey('volume_types.id'),
                            nullable=False)
    project_id = Column(String(255))

    volume_type = relationship(
        VolumeTypes,
        backref="projects",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'VolumeTypeProjects.volume_type_id == VolumeTypes.id,'
        'VolumeTypeProjects.deleted == False)')


class VolumeTypeExtraSpecs(BASE, CinderBase):
    """Represents additional specs as key/value pairs for a volume_type."""
    __tablename__ = 'volume_type_extra_specs'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_type_id = Column(String(36),
                            ForeignKey('volume_types.id'),
                            nullable=False)
    volume_type = relationship(
        VolumeTypes,
        backref="extra_specs",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'VolumeTypeExtraSpecs.volume_type_id == VolumeTypes.id,'
        'VolumeTypeExtraSpecs.deleted == False)'
    )


class QualityOfServiceSpecs(BASE, CinderBase):
    """Represents QoS specs as key/value pairs.

    QoS specs is standalone entity that can be associated/disassociated
    with volume types (one to many relation).  Adjacency list relationship
    pattern is used in this model in order to represent following hierarchical
    data with in flat table, e.g, following structure

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
    specs_id = Column(String(36), ForeignKey(id))
    key = Column(String(255))
    value = Column(String(255))

    specs = relationship(
        "QualityOfServiceSpecs",
        cascade="all, delete-orphan",
        backref=backref("qos_spec", remote_side=id),
    )

    vol_types = relationship(
        VolumeTypes,
        backref=backref('qos_specs'),
        foreign_keys=id,
        primaryjoin='and_('
                    'or_(VolumeTypes.qos_specs_id == '
                    'QualityOfServiceSpecs.id,'
                    'VolumeTypes.qos_specs_id == '
                    'QualityOfServiceSpecs.specs_id),'
                    'QualityOfServiceSpecs.deleted == False)')


class VolumeGlanceMetadata(BASE, CinderBase):
    """Glance metadata for a bootable volume."""
    __tablename__ = 'volume_glance_metadata'
    id = Column(Integer, primary_key=True, nullable=False)
    volume_id = Column(String(36), ForeignKey('volumes.id'))
    snapshot_id = Column(String(36), ForeignKey('snapshots.id'))
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
    resource = Column(String(255))

    in_use = Column(Integer)
    reserved = Column(Integer)

    @property
    def total(self):
        return self.in_use + self.reserved

    until_refresh = Column(Integer, nullable=True)


class Reservation(BASE, CinderBase):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)

    usage_id = Column(Integer, ForeignKey('quota_usages.id'), nullable=False)

    project_id = Column(String(255), index=True)
    resource = Column(String(255))

    delta = Column(Integer)
    expire = Column(DateTime, nullable=False)

    usage = relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='and_(Reservation.usage_id == QuotaUsage.id,'
                    'QuotaUsage.deleted == 0)')


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

    volume_id = Column(String(36))
    cgsnapshot_id = Column(String(36))
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
        Cgsnapshot,
        backref="snapshots",
        foreign_keys=cgsnapshot_id,
        primaryjoin='Snapshot.cgsnapshot_id == Cgsnapshot.id')


class SnapshotMetadata(BASE, CinderBase):
    """Represents a metadata key/value pair for a snapshot."""
    __tablename__ = 'snapshot_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    snapshot_id = Column(String(36),
                         ForeignKey('snapshots.id'),
                         nullable=False)
    snapshot = relationship(Snapshot, backref="snapshot_metadata",
                            foreign_keys=snapshot_id,
                            primaryjoin='and_('
                            'SnapshotMetadata.snapshot_id == Snapshot.id,'
                            'SnapshotMetadata.deleted == False)')


class IscsiTarget(BASE, CinderBase):
    """Represents an iscsi target for a given host."""
    __tablename__ = 'iscsi_targets'
    __table_args__ = (schema.UniqueConstraint("target_num", "host"),
                      {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)
    target_num = Column(Integer)
    host = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume,
                          backref=backref('iscsi_target', uselist=False),
                          foreign_keys=volume_id,
                          primaryjoin='and_(IscsiTarget.volume_id==Volume.id,'
                          'IscsiTarget.deleted==False)')


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

    @validates('fail_reason')
    def validate_fail_reason(self, key, fail_reason):
        return fail_reason and fail_reason[:255] or ''


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
        VolumeTypes,
        backref="encryption",
        foreign_keys=volume_type_id,
        primaryjoin='and_('
        'Encryption.volume_type_id == VolumeTypes.id,'
        'Encryption.deleted == False)'
    )


class Transfer(BASE, CinderBase):
    """Represents a volume transfer request."""
    __tablename__ = 'transfers'
    id = Column(String(36), primary_key=True)
    volume_id = Column(String(36), ForeignKey('volumes.id'))
    display_name = Column(String(255))
    salt = Column(String(255))
    crypt_hash = Column(String(255))
    expires_at = Column(DateTime)
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
        {'mysql_engine': 'InnoDB'}
    )
    id = Column(Integer, primary_key=True, nullable=False)
    initiator = Column(String(255), index=True, nullable=False)
    namespace = Column(String(255), nullable=False)
    key = Column(String(255), nullable=False)
    value = Column(String(255))


class ImageVolumeCacheEntry(BASE, models.ModelBase):
    """Represents an image volume cache entry"""
    __tablename__ = 'image_volume_cache_entries'
    id = Column(Integer, primary_key=True, nullable=False)
    host = Column(String(255), index=True, nullable=False)
    image_id = Column(String(36), index=True, nullable=False)
    image_updated_at = Column(DateTime, nullable=False)
    volume_id = Column(String(36), nullable=False)
    size = Column(Integer, nullable=False)
    last_used = Column(DateTime, default=lambda: timeutils.utcnow())


def register_models():
    """Register Models and create metadata.

    Called from cinder.db.sqlalchemy.__init__ as part of loading the driver,
    it will never need to be called explicitly elsewhere unless the
    connection is lost and needs to be reestablished.
    """
    from sqlalchemy import create_engine
    models = (Backup,
              Service,
              Volume,
              VolumeMetadata,
              VolumeAdminMetadata,
              VolumeAttachment,
              SnapshotMetadata,
              Transfer,
              VolumeTypeExtraSpecs,
              VolumeTypes,
              VolumeGlanceMetadata,
              ConsistencyGroup,
              Cgsnapshot
              )
    engine = create_engine(CONF.database.connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
