# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 OpenStack Foundation
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

"""Stubouts, mocks and fixtures for the test suite."""

from cinder import db


class FakeModel(object):
    """Stubs out for model."""
    def __init__(self, values):
        self.values = values

    def __getattr__(self, name):
        return self.values[name]

    def __getitem__(self, key):
        if key in self.values:
            return self.values[key]
        else:
            raise NotImplementedError()

    def __repr__(self):
        return '<FakeModel: %s>' % self.values


def stub_out(stubs, funcs):
    """Set the stubs in mapping in the db api."""
    for func in funcs:
        func_name = '_'.join(func.__name__.split('_')[1:])
        stubs.Set(db, func_name, func)
