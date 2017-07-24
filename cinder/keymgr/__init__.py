# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

from castellan import options as castellan_opts
from oslo_config import cfg
from oslo_log import log as logging
from oslo_log import versionutils
from oslo_utils import importutils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF

castellan_opts.set_defaults(CONF)


def log_deprecated_warning(deprecated_value, castellan):
    versionutils.deprecation_warning(deprecated_value,
                                     versionutils.deprecated.NEWTON,
                                     in_favor_of=castellan, logger=LOG)


# NOTE(kfarr): this method is for backwards compatibility, it is deprecated
# for removal
def set_overrides(conf):
    api_class = None
    should_override = False
    try:
        api_class = conf.key_manager.api_class
    except cfg.NoSuchOptError:
        LOG.warning("key_manager.api_class is not set, will use deprecated"
                    " option keymgr.api_class if set")
        try:
            api_class = CONF.keymgr.api_class
            should_override = True
        except cfg.NoSuchOptError:
            LOG.warning("keymgr.api_class is not set")

    deprecated_barbican = 'cinder.keymgr.barbican.BarbicanKeyManager'
    barbican = 'castellan.key_manager.barbican_key_manager.BarbicanKeyManager'
    deprecated_mock = 'cinder.tests.unit.keymgr.mock_key_mgr.MockKeyManager'
    castellan_mock = ('castellan.tests.unit.key_manager.mock_key_manager.'
                      'MockKeyManager')

    if api_class == deprecated_barbican:
        should_override = True
        log_deprecated_warning(deprecated_barbican, barbican)
        api_class = barbican
    elif api_class == deprecated_mock:
        should_override = True
        log_deprecated_warning(deprecated_mock, castellan_mock)
        api_class = castellan_mock
    elif api_class is None:
        should_override = True
        # TODO(kfarr): key_manager.api_class should be set in DevStack, and
        # this block can be removed
        LOG.warning("key manager not set, using insecure default %s",
                    castellan_mock)
        api_class = castellan_mock

    if should_override:
        conf.set_override('api_class', api_class, 'key_manager')


def API(conf=CONF):
    set_overrides(conf)
    cls = importutils.import_class(conf.key_manager.api_class)
    return cls(conf)
