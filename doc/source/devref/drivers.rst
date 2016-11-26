..
      Copyright (c) 2013 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Drivers
=======

Cinder exposes an API to users to interact with different storage backend
solutions. The following are standards across all drivers for Cinder services
to properly interact with a driver.

Basic attributes
----------------

There are some basic attributes that all drivers classes should have:

* VERSION: Driver version in string format.  No naming convention is imposed,
  although semantic versioning is recommended.
* CI_WIKI_NAME: Must be the exact name of the `ThirdPartySystems wiki page
  <https://wiki.openstack.org/wiki/ThirdPartySystems>`_. This is used by our
  tooling system to associate jobs to drivers and track their CI reporting
  status correctly.

The tooling system will also use the name and docstring of the driver class.

Minimum Features
----------------

Minimum features are enforced to avoid having a grid of what features are
supported by which drivers and which releases. Cinder Core requires that all
drivers implement the following minimum features.

Core Functionality
------------------

* Volume Create/Delete
* Volume Attach/Detach
* Snapshot Create/Delete
* Create Volume from Snapshot
* Get Volume Stats
* Copy Image to Volume
* Copy Volume to Image
* Clone Volume
* Extend Volume

Volume Stats
------------

Volume stats are used by the different schedulers for the drivers to provide
a report on their current state of the backend. The following should be
provided by a driver.

* driver_version
* free_capacity_gb
* storage_protocol
* total_capacity_gb
* vendor_name
* volume_backend_name

**NOTE:** If the driver is unable to provide a value for free_capacity_gb or
total_capacity_gb, keywords can be provided instead. Please use 'unknown' if
the backend cannot report the value or 'infinite' if the backend has no upper
limit. But, it is recommended to report real values as the Cinder scheduler
assigns lowest weight to any storage backend reporting 'unknown' or 'infinite'.

Feature Enforcement
-------------------

All concrete driver implementations should use the
``cinder.interface.volumedriver`` decorator on the driver class::

    @interface.volumedriver
    class LVMVolumeDriver(driver.VolumeDriver):

This will register the driver and allow automated compliance tests to run
against and verify the compliance of the driver against the required interface
to support the `Core Functionality`_ listed above.

Running ``tox -e compliance`` will verify all registered drivers comply to
this interface. This can be used during development to perform self checks
along the way. Any missing method calls will be identified by the compliance
tests.

The details for the required volume driver interfaces can be found in the
``cinder/interface/volume_*_driver.py`` source.

Driver Development Documentations
---------------------------------

The LVM driver is our reference for all new driver implementations. The
information below can provide additional documentation for the methods that
volume drivers need to implement.

Base Driver Interface
`````````````````````
The methods documented below are the minimum required interface for a volume
driver to support. All methods from this interface must be implemented
in order to be an official Cinder volume driver.

.. automodule:: cinder.interface.volume_driver
  :members:


Snapshot Interface
``````````````````
Another required interface for a volume driver to be fully compatible is the
ability to create and manage snapshots. Due to legacy constraints, this
interface is not included in the base driver interface above.

Work is being done to address those legacy issues. Once that is complete, this
interface will be merged with the base driver interface.

.. automodule:: cinder.interface.volume_snapshot_driver
  :members:


Manage/Unmanage Support
```````````````````````
An optional feature a volume backend can support is the ability to manage
existing volumes or unmanage volumes - keep the volume on the storage backend
but no longer manage it through Cinder.

To support this functionality, volume drivers must implement these methods:

.. automodule:: cinder.interface.volume_management_driver
  :members:


Manage/Unmanage Snapshot Support
````````````````````````````````
In addition to the ability to manage and unmanage volumes, Cinder backend
drivers may also support managing and unmanaging volume snapshots. These
additional methods must be implemented to support these operations.

.. automodule:: cinder.interface.volume_snapshotmanagement_driver
  :members:


Volume Consistency Groups
`````````````````````````
Some storage backends support the ability to group volumes and create write
consistent snapshots across the group. In order to support these operations,
the following interface must be implemented by the driver.

.. automodule:: cinder.interface.volume_consistencygroup_driver
  :members:


Generic Volume Groups
`````````````````````
The generic volume groups feature provides the ability to manage a group of
volumes together. Because this feature is implemented at the manager level,
every driver gets this feature by default. If a driver wants to override
the default behavior to support additional functionalities such as consistent
group snapshot, the following interface must be implemented by the driver.
Once every driver supporting volume consistency groups has added the
consistent group snapshot capability to generic volume groups, we no longer
need the volume consistency groups interface listed above.

.. automodule:: cinder.interface.volume_group_driver
  :members:

