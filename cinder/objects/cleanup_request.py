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

from cinder.objects import base


@base.CinderObjectRegistry.register
class CleanupRequest(base.CinderObject, base.ClusteredObject):
    """Versioned Object to send cleanup requests."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    # NOTE: When adding a field obj_make_compatible needs to be updated
    fields = {
        'service_id': fields.IntegerField(nullable=True),
        'cluster_name': fields.StringField(nullable=True),
        'host': fields.StringField(nullable=True),
        'binary': fields.StringField(nullable=True),
        'is_up': fields.BooleanField(default=False, nullable=True),
        'disabled': fields.BooleanField(nullable=True),
        'resource_id': fields.UUIDField(nullable=True),
        'resource_type': fields.StringField(nullable=True),
        'until': fields.DateTimeField(nullable=True),
    }

    def __init__(self, context=None, **kwargs):
        super(CleanupRequest, self).__init__(**kwargs)

        # Set non initialized fields with default or None values
        for field_name in self.fields:
            if not self.obj_attr_is_set(field_name):
                field = self.fields[field_name]
                if field.default != fields.UnspecifiedDefault:
                    setattr(self, field_name, field.default)
                elif field.nullable:
                    setattr(self, field_name, None)
