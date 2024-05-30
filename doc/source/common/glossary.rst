========
Glossary
========

This glossary offers a list of terms and definitions to define a
vocabulary for Cinder concepts.

.. glossary::

    Logical Volume Manager (LVM)

        Provides a method of allocating space on mass-storage
        devices that is more flexible than conventional partitioning
        schemes.

    iSCSI Qualified Name (IQN)

        IQN is the format most commonly used for iSCSI names, which uniquely
        identify nodes in an iSCSI network.
        All IQNs follow the pattern ``iqn.yyyy-mm.domain:identifier``, where
        ``yyyy-mm`` is the year and month in which the domain was registered,
        ``domain`` is the reversed domain name of the issuing organization, and
        ``identifier`` is an optional string which makes each IQN under the same
        domain unique.

        For example: ``iqn.2015-10.org.openstack.408ae959bce1``

    NVMe Qualified Name (NQN)

        NQN is the format most commonly used for NVMe names, which uniquely
        identify hosts or NVM subsystems in a network.
        NQNs can follow one of two supported formats.

        The first format, used by organizations that own a domain, is
        ``nqn.yyyy-mm.domain:identifier``, where ``yyyy-mm`` is the year and
        month in which the domain was registered, ``domain`` is the reversed
        domain name of the issuing organization, and ``identifier`` is an
        optional string which makes each NQN unique under the same domain name.

        For example: ``nqn.2014-08.com.example:nvme:nvm-subsystem-sn-d78432``

        The second format is used to create unique identifiers when there is
        not a naming authority or there is not a requirement for a human
        interpretable string. This format is
        ``nqn.2014-08.org.nvmexpress:uuid:identifier``, where only the
        ``identifier`` is variable and consists of a 128-bit UUID based on the
        definition in RFC 4122 represented as a string.

        For example: ``nqn.2014-08.org.nvmexpress:uuid:f81d4fae-7dec-11d0-a765-00a0c91e6bf6``
