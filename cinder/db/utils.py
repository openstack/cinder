# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from collections import abc

import sqlalchemy as sa

from cinder.i18n import _


def condition_db_filter(model, field, value):
    """Create matching filter.

    If value is an iterable other than a string, any of the values is
    a valid match (OR), so we'll use SQL IN operator.

    If it's not an iterator == operator will be used.
    """
    orm_field = getattr(model, field)
    # For values that must match and are iterables we use IN
    if isinstance(value, abc.Iterable) and not isinstance(value, str):
        # We cannot use in_ when one of the values is None
        if None not in value:
            return orm_field.in_(value)

        return sa.or_(orm_field == v for v in value)

    # For values that must match and are not iterables we use ==
    return orm_field == value


def condition_not_db_filter(model, field, value, auto_none=True):
    """Create non matching filter.

    If value is an iterable other than a string, any of the values is
    a valid match (OR), so we'll use SQL IN operator.

    If it's not an iterator == operator will be used.

    If auto_none is True then we'll consider NULL values as different as well,
    like we do in Python and not like SQL does.
    """
    result = ~condition_db_filter(model, field, value)  # pylint: disable=E1130

    if auto_none and (
        (
            isinstance(value, abc.Iterable)
            and not isinstance(value, str)
            and None not in value
        )
        or (value is not None)
    ):
        orm_field = getattr(model, field)
        result = sa.or_(result, orm_field.is_(None))

    return result


class Condition:
    """Class for normal condition values for conditional_update."""

    def __init__(self, value, field=None):
        self.value = value
        # Field is optional and can be passed when getting the filter
        self.field = field

    def get_filter(self, model, field=None):
        return condition_db_filter(model, self._get_field(field), self.value)

    def _get_field(self, field=None):
        # We must have a defined field on initialization or when called
        field = field or self.field
        if not field:
            raise ValueError(_('Condition has no field.'))
        return field


class Not(Condition):
    """Class for negated condition values for conditional_update.

    By default NULL values will be treated like Python treats None instead of
    how SQL treats it.

    So for example when values are (1, 2) it will evaluate to True when we have
    value 3 or NULL, instead of only with 3 like SQL does.
    """

    def __init__(self, value, field=None, auto_none=True):
        super().__init__(value, field)
        self.auto_none = auto_none

    def get_filter(self, model, field=None):
        return condition_not_db_filter(
            model,
            self._get_field(field),
            self.value,
            self.auto_none,
        )


class Case:
    """Class for conditional value selection for conditional_update."""

    def __init__(self, whens, value=None, else_=None):
        self.whens = whens
        self.value = value
        self.else_ = else_
