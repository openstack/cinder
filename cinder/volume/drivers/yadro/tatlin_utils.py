#  Copyright (C) 2021-2022 YADRO.
#  All rights reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import os

from oslo_log import log as logging

from cinder.utils import synchronized
from cinder.volume import volume_utils

LOG = logging.getLogger(__name__)


class TatlinVolumeConnections:
    """Auxiliary class to keep current host volume connections counted

    This class keeps connections of volumes to local host where this
    Cinder instance runs. It prevents disconnection of devices and
    termination of storage links in cases where two Cinder greenthreads
    use the same volume (e.g. creation of new volumes from image cache)
    or connection termination of Nova volume if Nova is collocated on
    the same host (e.g. with snapshots while volumes are attached).

    Once Tatlin implements clones and snaps this class should disappear.
    """

    def __init__(self, path):
        LOG.debug('Initialize counters for volume connections')
        self.counters = path
        self.create_store()

    @synchronized('tatlin-connections-store', external=True)
    def create_store(self):
        if not os.path.isdir(self.counters):
            os.mkdir(self.counters)

    # We won't intersect with other backend processes
    # because a volume belongs to one backend. Hence
    # no external flag need.
    @synchronized('tatlin-connections-store')
    def increment(self, id):
        counter = os.path.join(self.counters, id)
        connections = 0
        if os.path.exists(counter):
            with open(counter, 'r') as c:
                connections = int(c.read())
        connections += 1
        with open(counter, 'w') as c:
            c.write(str(connections))
        return connections

    @volume_utils.trace
    @synchronized('tatlin-connections-store')
    def decrement(self, id):
        counter = os.path.join(self.counters, id)
        if not os.path.exists(counter):
            return 0
        with open(counter, 'r') as c:
            connections = int(c.read())
        if connections == 1:
            os.remove(counter)
            return 0
        connections -= 1
        with open(counter, 'w') as c:
            c.write(str(connections))
        return connections

    @volume_utils.trace
    @synchronized('tatlin-connections-store')
    def get(self, id):
        counter = os.path.join(self.counters, id)
        if not os.path.exists(counter):
            return 0
        with open(counter, 'r') as c:
            connections = int(c.read())
        return connections
