..
      Copyright 2010-2012 United States Government as represented by the
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

==============================================
OpenStack Block Storage (Cinder) documentation
==============================================

.. figure:: images/cinder.png
   :alt: Cinder logo
   :align: center

What is Cinder?
---------------

Cinder is the OpenStack Block Storage service for providing volumes to Nova
virtual machines, Ironic bare metal hosts, containers and more. Some of the
goals of Cinder are to be/have:

* **Component based architecture**: Quickly add new behaviors
* **Highly available**: Scale to very serious workloads
* **Fault-Tolerant**: Isolated processes avoid cascading failures
* **Recoverable**: Failures should be easy to diagnose, debug, and rectify
* **Open Standards**: Be a reference implementation for a community-driven api

For end users
-------------

As an end user of Cinder, you'll use Cinder to create and manage volumes using
the Horizon user interface, command line tools such as the
`python-cinderclient <https://docs.openstack.org/python-cinderclient/latest/>`_,
or by directly using the
`REST API <https://docs.openstack.org/api-ref/block-storage/>`_.

Tools for using Cinder
~~~~~~~~~~~~~~~~~~~~~~

* `Horizon <https://docs.openstack.org/horizon/latest/user/manage-volumes.html>`_:
  The official web UI for the OpenStack Project.
* `OpenStack Client <https://docs.openstack.org/python-openstackclient/latest/>`_:
  The official CLI for OpenStack Projects. You should use this as your CLI for
  most things, it includes not just nova commands but also commands for most of
  the projects in OpenStack.
* `Cinder Client <https://docs.openstack.org/python-cinderclient/latest/user/shell.html>`_:
  The **openstack** CLI is recommended, but there are some advanced features
  and administrative commands that are not yet available there. For CLI access
  to these commands, the **cinder** CLI can be used instead.

Using the Cinder API
~~~~~~~~~~~~~~~~~~~~

All features of Cinder are exposed via a REST API that can be used to build
more complicated logic or automation with Cinder. This can be consumed directly
or via various SDKs. The following resources can help you get started consuming
the API directly.

* `Cinder API <https://docs.openstack.org/api-ref/block-storage/>`_
* :doc:`Cinder microversion history </contributor/api_microversion_history>`

For operators
-------------

This section has details for deploying and maintaining Cinder services.

Installing Cinder
~~~~~~~~~~~~~~~~~

Cinder can be configured standalone using the configuration setting
``auth_strategy = noauth``, but in most cases you will want to at least have
the `Keystone <https://docs.openstack.org/keystone/latest/install/>`_ Identity
service and other
`OpenStack services <https://docs.openstack.org/latest/install/>`_ installed.

.. toctree::
   :maxdepth: 1

   Installation Guide <install/index>
   Upgrade Process <upgrade>

Administrating Cinder
~~~~~~~~~~~~~~~~~~~~~

Contents:

.. toctree::
   :maxdepth: 1

   admin/index

Reference
~~~~~~~~~

Contents:

.. toctree::
   :maxdepth: 1

   configuration/index

.. toctree::
   :maxdepth: 2
   :titlesonly:
   :includehidden:

   drivers-all-about

.. toctree::
   :maxdepth: 1

   cli/index

Additional resources
~~~~~~~~~~~~~~~~~~~~

* `Cinder release notes <https://docs.openstack.org/releasenotes/cinder/>`_

For contributors
----------------

Contributions to Cinder are welcome. There can be a lot of background
information needed to get started. This section should help get you started.
Please feel free to also ask any questions in the **#openstack-cinder** IRC
channel.

Getting started
~~~~~~~~~~~~~~~

* `OpenStack Contributor Guide <https://docs.openstack.org/contributors/>`_

Contributing to Cinder
~~~~~~~~~~~~~~~~~~~~~~

Contents:

.. toctree::
   :maxdepth: 1

   contributor/index
   API Microversions </contributor/api_microversion_dev/>

Additional reference
~~~~~~~~~~~~~~~~~~~~

Contents:

.. toctree::
   :maxdepth: 1

   common/glossary.rst


.. only:: html

   Indices and tables
   ~~~~~~~~~~~~~~~~~~

   Contents:

   * :ref:`genindex`
   * :ref:`search`
