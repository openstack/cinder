========
Security
========

Network traffic
~~~~~~~~~~~~~~~

Depending on your deployment's security requirements, you might be required to
encrypt network traffic.  This can be accomplished with TLS.

There are multiple deployment options, with the most common and recommended
ones being:

- Only encrypt traffic between clients and public endpoints. This approach
  results in fewer certificates to manage, and we refer to it as public TLS.
  Public endpoints, in this sense, are endpoints only exposed to end-users.
  Traffic between internal endpoints is not encrypted.

- Leverages TLS for all endpoints in the entire deployment, including internal
  endpoints of the OpenStack services and with auxiliary services such as the
  database and the message broker.

You can look at `TripleO's documentation on TLS`_ for examples on how to do
this.

Cinder drivers should support secure TLS/SSL communication between the cinder
volume service and the backend, as configured by the ``driver_ssl_cert_verify``
and ``driver_ssl_cert_path`` options in ``cinder.conf``.

If unsure whether your driver supports TLS/SSL, please check the driver's
specific page in the :ref:`volume-drivers` page or contact the vendor.

Data at rest
~~~~~~~~~~~~

Volumes' data can be secured at rest using Cinder's volume encryption feature.

For encryption keys Cinder uses a Key management service, with Barbican being
the recommended service.

More information on encryption can be found on the :ref:`volume-encryption`
section.

Data leakage
~~~~~~~~~~~~

Some users and admins worry about data leakage between OpenStack projects or
users caused by a new volume containing partial or full data from a previously
deleted volume.

These concerns are sometimes instigated by the ``volume_clear`` and
``volume_clear_size`` configuration options, but these options are only
relevant to the LVM driver, and only when using thick volumes (which are not
the default, thin volumes are).

Writing data on a Cinder volume as a generic mechanism to prevent data leakage
is not implemented for other drivers because it does not ensure that the data
will be actually erased on the physical disks, as the storage solution could be
doing copy-on-write or other optimizations.

Thin provisioned volumes return zeros for unallocated blocks, so we don't have
to worry about data leakage. As for thick volumes, each of the individual
Cinder drivers must ensure that data from a deleted volume can never leak to a
newly created volume.

This prevents other OpenStack projects and users from being able to get data
from deleted volumes, but since the data may still be present on the physical
disks, somebody with physical access to the disks may still be able to retrieve
that data.

For those concerned with this, we recommend using encrypted volumes or read
your storage solution's documentation or contact your vendor to see if they
have some kind of clear policy option available on their storage solution.

.. _TripleO's documentation on TLS: https://docs.openstack.org/project-deploy-guide/tripleo-docs/latest/features/tls-introduction.html
