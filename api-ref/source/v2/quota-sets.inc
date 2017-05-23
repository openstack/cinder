.. -*- rst -*-

Quota sets extension (os-quota-sets)
====================================

Administrators only, depending on policy settings.

Shows, updates, and deletes quotas for a tenant.

Show quotas
~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_tenant_id}/os-quota-sets/{tenant_id}

Shows quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: quotas_tenant_id
   - admin_tenant_id: admin_tenant_id
   - usage: usage


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-response.json
   :language: javascript

Update quotas
~~~~~~~~~~~~~

.. rest_method::  PUT /v2/{admin_tenant_id}/os-quota-sets/{tenant_id}

Updates quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups
   - tenant_id: quotas_tenant_id
   - admin_tenant_id: admin_tenant_id

Request Example
---------------

.. literalinclude:: ./samples/quotas-update-request.json
   :language: javascript


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups

Response Example
----------------

.. literalinclude:: ./samples/quotas-update-response.json
   :language: javascript

Delete quotas
~~~~~~~~~~~~~

.. rest_method::  DELETE /v2/{admin_tenant_id}/os-quota-sets/{tenant_id}

Deletes quotas for a tenant so the quotas revert to default values.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: quotas_tenant_id
   - admin_tenant_id: admin_tenant_id

Response Example
----------------

.. literalinclude:: ./samples/quotas-delete-response.json
   :language: javascript

Get default quotas
~~~~~~~~~~~~~~~~~~

.. rest_method::  GET /v2/{admin_tenant_id}/os-quota-sets/{tenant_id}/defaults

Gets default quotas for a tenant.


Normal response codes: 200
Error response codes:


Request
-------

.. rest_parameters:: parameters.yaml

   - tenant_id: tenant_id
   - admin_tenant_id: admin_tenant_id


Response Parameters
-------------------

.. rest_parameters:: parameters.yaml

   - injected_file_content_bytes: injected_file_content_bytes
   - metadata_items: metadata_items
   - reserved: reserved
   - in_use: in_use
   - ram: ram
   - floating_ips: floating_ips
   - key_pairs: key_pairs
   - injected_file_path_bytes: injected_file_path_bytes
   - instances: instances
   - security_group_rules: security_group_rules
   - injected_files: injected_files
   - quota_set: quota_set
   - cores: cores
   - fixed_ips: fixed_ips
   - id: id
   - security_groups: security_groups


Response Example
----------------

.. literalinclude:: ./samples/quotas-show-defaults-response.json
   :language: javascript
