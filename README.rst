========================
Team and repository tags
========================

.. image:: https://governance.openstack.org/tc/badges/cinder.svg
    :target: https://governance.openstack.org/tc/reference/tags/index.html

.. Change things from this point on

======
CINDER
======

.. warning::
   The stable/train branch of cinder does not contain a fix for
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

You have come across a storage service for an open cloud computing service.
It has identified itself as `Cinder`. It was abstracted from the Nova project.

* Wiki: https://wiki.openstack.org/Cinder
* Developer docs: https://docs.openstack.org/cinder/latest/
* Blueprints: https://blueprints.launchpad.net/cinder
* Release notes: https://docs.openstack.org/releasenotes/cinder/
* Design specifications: https://specs.openstack.org/openstack/cinder-specs/

Getting Started
---------------

If you'd like to run from the master branch, you can clone the git repo:

    git clone https://opendev.org/openstack/cinder

For developer information please see
`HACKING.rst <https://opendev.org/openstack/cinder/src/branch/master/HACKING.rst>`_

You can raise bugs here https://bugs.launchpad.net/cinder

Python client
-------------
https://opendev.org/openstack/python-cinderclient
