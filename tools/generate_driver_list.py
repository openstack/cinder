#! /usr/bin/env python
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

"""Generate list of cinder drivers"""

from cinder.interface import util


def format_description(desc):
    desc = desc or '<None>'
    lines = desc.rstrip('\n').split('\n')
    for line in lines:
        print('    %s' % line)


def print_drivers(drivers, config_name):
    # for driver in drivers.sort(key=lambda x: x.class_fqn):
    for driver in sorted(drivers, key=lambda x: x.class_fqn):
        print(driver.class_name)
        print('-' * len(driver.class_name))
        if driver.version:
            print('* Version: %s' % driver.version)
        print('* %s=%s' % (config_name, driver.class_fqn))
        print('* Description:')
        format_description(driver.desc)
        print('')
    print('')


def main():
    print('VOLUME DRIVERS')
    print('==============')
    print_drivers(util.get_volume_drivers(), 'volume_driver')

    print('BACKUP DRIVERS')
    print('==============')
    print_drivers(util.get_backup_drivers(), 'backup_driver')

    print('FC ZONE MANAGER DRIVERS')
    print('=======================')
    print_drivers(util.get_fczm_drivers(), 'zone_driver')


if __name__ == '__main__':
    main()
