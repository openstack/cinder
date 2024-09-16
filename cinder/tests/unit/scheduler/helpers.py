# Copyright 2024 Red Hat, Inc
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


from cinder.scheduler.filters import affinity_filter
from cinder.scheduler.filters import availability_zone_filter
from cinder.scheduler.filters import capabilities_filter
from cinder.scheduler.filters import capacity_filter
from cinder.scheduler.filters import driver_filter
from cinder.scheduler.filters import ignore_attempted_hosts_filter
from cinder.scheduler.filters import instance_locality_filter
from cinder.scheduler.filters import json_filter
from cinder.scheduler.weights import capacity
from cinder.scheduler.weights import chance
from cinder.scheduler.weights import goodness
from cinder.scheduler.weights import stochastic
from cinder.scheduler.weights import volume_number


ALL_FILTER_CLASSES = [
    availability_zone_filter.AvailabilityZoneFilter,
    capabilities_filter.CapabilitiesFilter,
    capacity_filter.CapacityFilter,
    affinity_filter.DifferentBackendFilter,
    driver_filter.DriverFilter,
    instance_locality_filter.InstanceLocalityFilter,
    ignore_attempted_hosts_filter.IgnoreAttemptedHostsFilter,
    json_filter.JsonFilter,
    affinity_filter.SameBackendFilter,
]

ALL_FILTERS = [filter_cls.__name__ for filter_cls in ALL_FILTER_CLASSES]

DEFAULT_SCHEDULER_FILTER_CLASSES = [
    availability_zone_filter.AvailabilityZoneFilter,
    capabilities_filter.CapabilitiesFilter,
    capacity_filter.CapacityFilter,
]

DEFAULT_SCHEDULER_FILTERS = [
    filter_cls.__name__ for filter_cls in DEFAULT_SCHEDULER_FILTER_CLASSES]

ALL_WEIGHER_CLASSES = [
    capacity.AllocatedCapacityWeigher,
    capacity.CapacityWeigher,
    chance.ChanceWeigher,
    goodness.GoodnessWeigher,
    stochastic.StochasticHostWeightHandler,
    volume_number.VolumeNumberWeigher,
]

ALL_WEIGHERS = [weigher.__name__ for weigher in ALL_WEIGHER_CLASSES]
