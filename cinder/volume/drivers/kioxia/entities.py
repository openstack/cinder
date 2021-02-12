#    (c)  Copyright  Kioxia Corporation 2021 All Rights Reserved.
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

import json


class JsonClass(object):

    def __init__(self):
        pass

    def to_json(self):
        return json.dumps(
            self,
            default=lambda o: o.__dict__,
            sort_keys=True,
            indent=4)

    def __str__(self):
        return ', '.join(['{key}={value}'.format(
            key=key, value=self.__dict__.get(key)) for key in self.__dict__])

    def __getattr__(self, item):
        return "N/A"

    def set_items(self, json_object):
        json_keys = json_object.keys()
        for key in json_keys:
            if not isinstance(json_object[key], 'dict'):
                self.__dict__[key] = json_object[key]


class ProvisionerResponse(JsonClass):
    #
    # Provisioner response data
    #

    def __init__(
            self,
            prov_entities,
            res_id=None,
            status=None,
            description=None,
            path=None):
        JsonClass.__init__(self)
        self.prov_entities = prov_entities
        self.resID = res_id
        self.status = "Success" if status is None else status
        self.description = self.status if description is None else description
        self.path = path

    def __str__(self):
        items = ""
        if self.prov_entities:
            num_of_entities = len(self.prov_entities)
            if num_of_entities == 1:
                items = self.prov_entities[0]
            else:
                items = num_of_entities
        return "(" + str(items) + ", " + str(self.resID) + ", " + \
            str(self.status) + ", " + str(self.description) + ")"


class ProvisionerInfo(JsonClass):
    #
    # Provisioner Info data
    #

    def __init__(self, totalFreeSpace, version, syslogsBackend=None):
        self.totalFreeSpace = totalFreeSpace
        self.version = version
        self.syslogsBackend = syslogsBackend


class Backend(JsonClass):
    #
    # Backend data
    #

    def __init__(
            self,
            mgmt_ips=None,
            rack=None,
            region=None,
            zone=None,
            persistentID=None,
            inUse=None,
            hostId=None,
            state=None,
            totalCapacity=None,
            availableCapacity=None,
            lastProbTime=None,
            probeInterval=None,
            totalBW=None,
            availableBW=None,
            totalIOPS=None,
            availableIOPS=None):
        self.mgmtIPs = mgmt_ips
        self.rack = rack
        self.region = region
        self.zone = zone
        self.persistentID = persistentID
        self.inUse = inUse
        self.state = state
        self.totalCapacity = totalCapacity
        self.availableCapacity = availableCapacity
        self.lastProbTime = lastProbTime
        self.probeInterval = probeInterval
        self.totalBW = totalBW
        self.availableBW = availableBW
        self.totalIOPS = totalIOPS
        self.availableIOPS = availableIOPS
        self.hostId = hostId


class Replica(JsonClass):
    #
    # Backend data
    #

    def __init__(self, sameRackAllowed, racks, regions, zones):
        self.sameRackAllowed = sameRackAllowed
        self.racks = racks
        self.regions = regions
        self.zones = zones


class Location(JsonClass):
    #
    # Location data
    #

    def __init__(
            self,
            uuid=None,
            backend=None,
            replicaState=None,
            currentStateTime=None):
        self.uuid = uuid
        self.backend = backend
        self.replicaState = replicaState
        self.currentStateTime = currentStateTime


class VolumeProv(JsonClass):
    #
    # Provisioner Volume data
    #

    def __init__(
            self,
            uuid=None,
            alias=None,
            capacity=None,
            numReplicas=None,
            maxIOPS=None,
            desiredIOPS=None,
            maxBW=None,
            desiredBW=None,
            blockSize=None,
            maxReplicaDownTime=None,
            snapshotID=None,
            writable=None,
            reservedSpace=None,
            location=None):
        self.uuid = uuid
        self.alias = alias
        self.capacity = capacity
        self.numReplicas = numReplicas
        self.maxIOPS = maxIOPS
        self.desiredIOPS = desiredIOPS
        self.maxBW = maxBW
        self.desiredBW = desiredBW
        self.blockSize = blockSize
        self.maxReplicaDownTime = maxReplicaDownTime
        self.snapshotID = snapshotID
        self.writable = writable
        self.reservedSpacePercentage = reservedSpace
        self.location = location


class StorageClass(JsonClass):
    #
    # Provisioner Storage Class
    #

    def __init__(
            self,
            replicas,
            racks=None,
            regions=None,
            zones=None,
            blockSize=None,
            maxIOPSPerGB=None,
            desiredIOPSPerGB=None,
            maxBWPerGB=None,
            desiredBWPerGB=None,
            sameRackAllowed=None,
            maxReplicaDownTime=None,
            hostId=None,
            spanAllowed=None,
            name=None,
            shareSSDBetweenVolumes=None):
        self.numReplicas = replicas
        if racks is not None:
            self.racks = racks
        if regions is not None:
            self.regions = regions
        if zones is not None:
            self.zones = zones
        if blockSize is not None:
            self.blockSize = blockSize
        if maxIOPSPerGB is not None:
            self.maxIOPSPerGB = maxIOPSPerGB
        if desiredIOPSPerGB is not None:
            self.desiredIOPSPerGB = desiredIOPSPerGB
        if maxBWPerGB is not None:
            self.maxBWPerGB = maxBWPerGB
        if desiredBWPerGB is not None:
            self.desiredBWPerGB = desiredBWPerGB
        if sameRackAllowed is not None:
            self.sameRackAllowed = sameRackAllowed
        if maxReplicaDownTime is not None:
            self.maxReplicaDownTime = maxReplicaDownTime
        if hostId is not None:
            self.hostId = hostId
        if spanAllowed is not None:
            self.allowSpan = spanAllowed
        if name is not None:
            self.name = name
        if shareSSDBetweenVolumes is not None:
            self.shareSSDBetweenVolumes = shareSSDBetweenVolumes


class VolumeCreate(JsonClass):
    #
    # Provisioner Volume data for Create operation
    #

    def __init__(
            self,
            alias,
            capacity,
            storage_class,
            prov_type,
            reserved_space=None,
            protocol=None,
            uuid=None):
        self.alias = alias
        self.capacity = capacity
        self.storageClass = storage_class
        self.provisioningType = prov_type
        if reserved_space is not None:
            self.reservedSpacePercentage = reserved_space
        if protocol is not None:
            self.protocol = protocol
        if uuid is not None:
            self.uuid = uuid


class SyslogEntity(JsonClass):
    #
    # Syslog Entity object
    #

    def __init__(
            self,
            name=None,
            url=None,
            state=None,
            useTls=None,
            certFileName=None):
        self.name = name
        self.url = url
        self.state = state
        self.useTls = useTls
        self.certFileName = certFileName


class SnapshotCreate(JsonClass):
    #
    # Provisioner Snapshot data for Create operation
    #

    def __init__(
            self,
            alias,
            volumeID,
            reservedSpacePercentage=None,
            snapshotID=None):
        self.alias = alias
        self.volumeID = volumeID
        if reservedSpacePercentage is not None:
            self.reservedSpacePercentage = reservedSpacePercentage
        if snapshotID is not None:
            self.snapshotID = snapshotID


class SnapshotEntity(JsonClass):
    #
    # Provisioner Snapshot Entity data for Show operation
    #

    def __init__(
            self,
            alias=None,
            snapshotID=None,
            reservedSpace=None,
            volumeID=None,
            capacity=None,
            timestamp=None):
        self.alias = alias
        self.volumeID = volumeID
        self.reservedSpace = reservedSpace
        self.snapshotID = snapshotID
        self.capacity = capacity
        self.timestamp = timestamp


class SnapshotVolumeCreate(JsonClass):
    #
    # Provisioner Snapshot Volume data for Create operation
    #

    def __init__(
            self,
            alias,
            snapshotID,
            writable,
            reservedSpacePercentage=None,
            volumeID=None,
            maxIOPSPerGB=None,
            maxBWPerGB=None,
            protocol=None,
            spanAllowed=None,
            storageClassName=None):
        self.alias = alias
        self.snapshotID = snapshotID
        self.writable = writable
        if reservedSpacePercentage is not None:
            self.reservedSpacePercentage = reservedSpacePercentage
        if volumeID is not None:
            self.volumeID = volumeID
        if maxIOPSPerGB is not None:
            self.maxIOPSPerGB = maxIOPSPerGB
        if maxBWPerGB is not None:
            self.maxBWPerGB = maxBWPerGB
        if protocol is not None:
            self.protocol = protocol
        if spanAllowed is not None:
            self.allowSpan = spanAllowed
        if storageClassName is not None:
            self.storageClassName = storageClassName


class ForwardEntity(JsonClass):
    #
    # Provisioner Forward Entity data
    #

    def __init__(
            self,
            loggingType,
            level,
            host,
            appName,
            message,
            parametersList):
        self.loggingType = loggingType
        self.level = level
        self.host = host
        self.appName = appName
        self.message = message
        self.parametersList = parametersList


class LicenseEntity(JsonClass):
    #
    # Provisioner License Entity data
    #

    def __init__(
            self,
            license_type=None,
            expirationDate=None,
            maxBackends=None):
        self.type = license_type
        self.expirationDate = expirationDate
        self.maxBackends = maxBackends


class HostEntity(JsonClass):
    #
    # Provisioner Host Entity data
    #

    def __init__(
            self,
            nqn=None,
            uuid=None,
            name=None,
            clientType=None,
            version=None,
            state=None,
            lastProbeTime=None,
            duration=None):
        self.nqn = nqn
        self.uuid = uuid
        self.name = name
        self.clientType = clientType
        self.version = version
        self.state = state
        self.lastProbeTime = lastProbeTime
        self.duration = duration


class TargetEntity(JsonClass):
    #
    # Provisioner Target Entity data for Show operation
    #

    def __init__(self, alias=None):
        self.alias = alias


class TenantEntity(JsonClass):
    #
    # Provisioner Tenant Entity data for Show operation
    #

    def __init__(self, capacity, iops, bw, uuid=None, name=None):
        self.capacity = capacity
        self.totalIOPS = iops
        self.totalBW = bw
        if uuid is not None:
            self.tenantId = uuid
        if name is not None:
            self.name = name


class CloneEntity(JsonClass):
    #
    # Provisioner Clone Entity data
    #

    def __init__(self, sourceVolumeId, alias, volumeId=None,
                 reservedSpacePercentage=None,
                 capacity=None):
        self.sourceVolumeId = sourceVolumeId
        self.alias = alias
        if volumeId is not None:
            self.volumeId = volumeId
        if reservedSpacePercentage is not None:
            self.reservedSpacePercentage = reservedSpacePercentage
        if capacity is not None:
            self.capacity = capacity
