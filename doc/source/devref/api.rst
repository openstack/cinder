..
      Copyright 2010-2011 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration. 
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

API Endpoint
============

Cinder has a system for managing multiple APIs on different subdomains.
Currently there is support for the OpenStack API, as well as the Amazon EC2
API.

Common Components
-----------------

The :mod:`cinder.api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cinder.api.cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.cloud
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

OpenStack API
-------------

The :mod:`openstack` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.auth
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`backup_schedules` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.backup_schedules
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.faults
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`flavors` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.flavors
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`servers` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.servers
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`sharedipgroups` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: cinder.api.openstack.sharedipgroups
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

EC2 API
-------

The :mod:`cinder.api.ec2` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.ec2
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`apirequest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.ec2.apirequest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.ec2.cloud
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.ec2.images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`metadatarequesthandler` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api.ec2.metadatarequesthandler
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

Tests
-----

The :mod:`api_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api_unittest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api_integration` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api_integration
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.cloud_unittest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api.fakes` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.fakes
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api.test_wsgi` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.test_wsgi
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_auth
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_faults
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_flavors` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_flavors
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_images` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_servers` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_servers
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_sharedipgroups` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.api.openstack.test_sharedipgroups
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

