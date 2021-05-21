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


class ManagedObjectReference(object):
    """A managed object reference is a remote identifier."""

    def __init__(self, name="ManagedObject", value=None):
        super(ManagedObjectReference, self)
        # Managed Object Reference value attributes
        # typically have values like vm-123 or
        # host-232 and not UUID.
        self.value = value
        self._value_1 = value
        # Managed Object Reference type
        # attributes hold the name of the type
        # of the vCenter object the value
        # attribute is the identifier for
        self.type = name
        self._type = name
