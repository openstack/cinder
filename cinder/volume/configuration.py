# Copyright (c) 2012 Rackspace Hosting
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

"""Configuration support for all drivers.

This module allows support for setting configurations either from default
or from a particular FLAGS group, to be able to set multiple configurations
for a given set of values.

For instance, two lvm configurations can be set by naming them in groups as

 [lvm1]
 volume_group=lvm-group-1
 ...

 [lvm2]
 volume_group=lvm-group-2
 ...

And the configuration group name will be passed in so that all calls to
configuration.volume_group within that instance will be mapped to the proper
named group.

This class also ensures the implementation's configuration is grafted into the
option group. This is due to the way cfg works. All cfg options must be defined
and registered in the group in which they are used.
"""


from oslo_config import cfg


CONF = cfg.CONF
SHARED_CONF_GROUP = 'backend_defaults'


class DefaultGroupConfiguration(object):
    """Get config options from only DEFAULT."""

    def __init__(self):
        # set the local conf so that __call__'s know what to use
        self.local_conf = CONF

    def _ensure_config_values(self, volume_opts):
        CONF.register_opts(volume_opts, group=None)

    def append_config_values(self, volume_opts):
        self._ensure_config_values(volume_opts)

    def safe_get(self, value):
        try:
            return self.__getattr__(value)
        except cfg.NoSuchOptError:
            return None

    def __getattr__(self, value):
        # Don't use self.local_conf to avoid reentrant call to __getattr__()
        local_conf = object.__getattribute__(self, 'local_conf')
        return getattr(local_conf, value)


class BackendGroupConfiguration(object):

    def __init__(self, volume_opts, config_group=None):
        """Initialize configuration.

        This takes care of grafting the implementation's config
        values into the config group and shared defaults. We will try to
        pull values from the specified 'config_group', but fall back to
        defaults from the SHARED_CONF_GROUP.
        """
        self.config_group = config_group

        # set the local conf so that __call__'s know what to use
        self._ensure_config_values(volume_opts)
        self.backend_conf = CONF._get(self.config_group)
        self.shared_backend_conf = CONF._get(SHARED_CONF_GROUP)

    def _safe_register(self, opt, group):
        try:
            CONF.register_opt(opt, group=group)
        except cfg.DuplicateOptError:
            pass  # If it's already registered ignore it

    def _ensure_config_values(self, volume_opts):
        """Register the options in the shared group.

        When we go to get a config option we will try the backend specific
        group first and fall back to the shared group. We override the default
        from all the config options for the backend group so we can know if it
        was set or not.
        """
        for opt in volume_opts:
            self._safe_register(opt, SHARED_CONF_GROUP)
            # Assuming they aren't the same groups, graft on the options into
            # the backend group and override its default value.
            if self.config_group != SHARED_CONF_GROUP:
                self._safe_register(opt, self.config_group)
                CONF.set_default(opt.name, None, group=self.config_group)

    def append_config_values(self, volume_opts):
        self._ensure_config_values(volume_opts)

    def set_default(self, opt_name, default):
        CONF.set_default(opt_name, default, group=SHARED_CONF_GROUP)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def safe_get(self, value):
        try:
            return self.__getattr__(value)
        except cfg.NoSuchOptError:
            return None

    def __getattr__(self, opt_name):
        # Don't use self.X to avoid reentrant call to __getattr__()
        backend_conf = object.__getattribute__(self, 'backend_conf')
        opt_value = getattr(backend_conf, opt_name)
        if opt_value is None:
            shared_conf = object.__getattribute__(self, 'shared_backend_conf')
            opt_value = getattr(shared_conf, opt_name)
        return opt_value


class Configuration(object):

    def __init__(self, volume_opts, config_group=None):
        """Initialize configuration.

        This shim will allow for compatibility with the DEFAULT
        style of backend configuration which is used by some of the users
        of this configuration helper, or by the volume drivers that have
        all been forced over to the config_group style.
        """
        self.config_group = config_group
        if config_group:
            self.conf = BackendGroupConfiguration(volume_opts, config_group)
        else:
            self.conf = DefaultGroupConfiguration()

    def append_config_values(self, volume_opts):
        self.conf.append_config_values(volume_opts)

    def safe_get(self, value):
        return self.conf.safe_get(value)

    def __getattr__(self, value):
        # Don't use self.conf to avoid reentrant call to __getattr__()
        conf = object.__getattribute__(self, 'conf')
        return getattr(conf, value)
