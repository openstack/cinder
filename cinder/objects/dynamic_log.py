# Copyright (c) 2017 Red Hat, Inc.
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
class LogLevel(base.CinderObject):
    """Versioned Object to send log change requests."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'prefix': fields.StringField(nullable=True),
        'level': fields.StringField(nullable=True),
    }

    def __init__(self, context=None, **kwargs):
        super(LogLevel, self).__init__(**kwargs)

        # Set non initialized fields with default or None values
        for field_name in self.fields:
            if not self.obj_attr_is_set(field_name):
                field = self.fields[field_name]
                if field.default != fields.UnspecifiedDefault:
                    setattr(self, field_name, field.default)
                elif field.nullable:
                    setattr(self, field_name, None)


@base.CinderObjectRegistry.register
class LogLevelList(base.ObjectListBase, base.CinderObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('LogLevel'),
    }
