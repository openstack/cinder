.. _block_storage:

=====================
Cinder Administration
=====================

The OpenStack Block Storage service works through the interaction of
a series of daemon processes named ``cinder-*`` that reside
persistently on the host machine or machines. You can run all the
binaries from a single node, or spread across multiple nodes. You can
also run them on the same node as other OpenStack services.

To administer the OpenStack Block Storage service, it is helpful to
understand a number of concepts. You must make certain choices when
you configure the Block Storage service in OpenStack. The bulk of the
options come down to two choices - single node or multi-node install.
You can read a longer discussion about `Storage Decisions`_ in the
`OpenStack Operations Guide`_.

OpenStack Block Storage enables you to add extra block-level storage
to your OpenStack Compute instances. This service is similar to the
Amazon EC2 Elastic Block Storage (EBS) offering.

.. toctree::
   :maxdepth: 1

   blockstorage-api-throughput.rst
   blockstorage-manage-volumes.rst
   blockstorage-troubleshoot.rst

.. _`Storage Decisions`: https://docs.openstack.org/ops-guide/arch-storage.html
.. _`OpenStack Operations Guide`: https://docs.openstack.org/ops-guide/
