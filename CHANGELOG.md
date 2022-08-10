## v0.0.6 - 2022-??-?? -

* Internationalizing Domain Names in Applications (IDNA) support for zone and
  record names (record values and advanced records are not yet supported)

## v0.0.5 - 2022-07-14 - Support the root

* Enable SUPPORTS_ROOT_NS for management of root NS records. Requires
  octodns>=0.9.16.
* Add support for Route53Provider/ALIAS provider-specific type, see README for
  more information.
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
