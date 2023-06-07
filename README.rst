================
OpenStack Cinder
================

.. image:: https://governance.openstack.org/tc/badges/cinder.svg
    :target: https://governance.openstack.org/tc/reference/tags/index.html

.. Change things from this point on

.. warning::
   The stable/wallaby branch of cinder does not contain a fix for
   CVE-2023-2088_.  Be aware that such a fix must span cinder, os-brick,
   nova, and, depending on your deployment configuration, glance_store
   and ironic.  *The Cinder project team advises against using the code
   in this branch unless a mitigation against CVE-2023-2088 is applied.*

   .. _CVE-2023-2088: https://nvd.nist.gov/vuln/detail/CVE-2023-2088

   References:

   * https://nvd.nist.gov/vuln/detail/CVE-2023-2088
   * https://bugs.launchpad.net/cinder/+bug/2004555
   * https://security.openstack.org/ossa/OSSA-2023-003.html
   * https://wiki.openstack.org/wiki/OSSN/OSSN-0092

OpenStack Cinder is a storage service for an open cloud computing service.

You can learn more about Cinder at:

* `Wiki <https://wiki.openstack.org/Cinder/>`__
* `Developer Docs <https://docs.openstack.org/cinder/latest/>`__
* `Blueprints <https://blueprints.launchpad.net/cinder/>`__
* `Release notes <https://docs.openstack.org/releasenotes/cinder/>`__
* `Design specifications <https://specs.openstack.org/openstack/cinder-specs/>`__

Getting Started
---------------

If you'd like to run from the master branch, you can clone the git repo:

    git clone https://opendev.org/openstack/cinder

If you'd like to contribute, please see the information in
`CONTRIBUTING.rst <https://opendev.org/openstack/cinder/src/branch/master/CONTRIBUTING.rst>`_

You can raise bugs on `Launchpad <https://bugs.launchpad.net/cinder>`__

Python client
-------------
`Python Cinderclient <https://opendev.org/openstack/python-cinderclient>`__
