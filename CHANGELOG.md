## v0.0.7 - 2023-??-?? - 

### Important

* Add `append_to_names` tag append parameter to sources
* Add `DS` record type support

## v0.0.6 - 2023-10-16 - Long overdue

### Important

* Adds Provider.list_zones to enable new dynamic zone config functionality
* Ec2Source added to support dynamically creating records for Ec2 instances
* ElbSource added to support dynamically creating records for ELBs
* role_name added to auth mix-in to support acquiring a specific role from existing credentials 
* Warn and skip records with TrafficPolicyInstanceId as they're not supported

### Misc

* Fixed issue with creating TCP healthchecks for dynamic CNAME records

## v0.0.5 - 2022-07-14 - Support the root

### Important

* Add support for Route53Provider/ALIAS provider-specific type, see README for
  more information. octoDNS will now see and try to manage existing Route53
  ALIAS records. See https://github.com/octodns/octodns-route53/issues/34#issuecomment-1228568776
  for more details on what this means and how to add them to your configs or
  ignore them.

### Misc

* Enable SUPPORTS_ROOT_NS for management of root NS records. Requires
  octodns>=0.9.16.
* Health checks ref's use a hash when ref > 64 chars, to support long fqdns.
* Add support for FailureThreashold in healthchecks
* Make sure health checks get deleted from CNAME records

## v0.0.4 - 2022-02-02 - pycountry-convert install_requires

* install_requires includes pycountry-convert as it's a runtime requirement
* other misc script/tooling improvements

## v0.0.3 - 2022-01-23 - What we really need

* Fix boto -> boto3 type-o/problem with setup.py
* Switch to pytest since nose is long :skull:ed

## v0.0.2 - 2022-01-11 - setup.py fixes

* setup.py now uses find_packages so that processors are now found/included

## v0.0.1 - 2022-01-03 - Moving

#### Nothworthy Changes

* Initial extraction of Route53Provider from octoDNS core
* Initial extraction of AwsAcmMangingProcessor

#### Stuff

* Nothing
