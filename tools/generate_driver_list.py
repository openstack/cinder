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

import importlib
import inspect
import pkgutil
import pprint

from cinder.volume import drivers
from cinder.volume import driver

package = drivers


def get_driver_list():
    dr_list = []
    for _loader, modname, _ispkg in pkgutil.walk_packages(
            path=package.__path__,
            prefix=package.__name__ + '.',
            onerror=lambda x: None):
        try:
            mod = importlib.import_module(modname)
            list_classes = inspect.getmembers(mod, inspect.isclass)
            dr_list += [
                modname + '.' + dr_name for dr_name, dr in list_classes
                if driver.BaseVD in inspect.getmro(dr)]
        except ImportError:
            print("%s module ignored!!" % modname)
    return dr_list


def main():
    dr_list = get_driver_list()
    print("Drivers list:")
    pprint.pprint(dr_list)


if __name__ == '__main__':
    main()
