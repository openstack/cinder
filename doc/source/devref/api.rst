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
Currently there is support for the OpenStack API.

Common Components
-----------------

The :mod:`cinder.api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


Tests
-----

The :mod:`api` Module
~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`api.fakes` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api.fakes
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`api.openstack` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api.openstack
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`api.openstack.test_wsgi` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api.openstack.test_wsgi
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`test_auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api.middleware.test_auth
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`test_faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: cinder.tests.unit.api.middleware.test_faults
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:
