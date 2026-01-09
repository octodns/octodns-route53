## Route53Provider provider for octoDNS

An [octoDNS](https://github.com/octodns/octodns/) provider that targets [Route53](https://aws.amazon.com/route53/).

### Installation

#### Command line

```
pip install octodns-route53
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades.

##### Versions

```
# Start with the latest versions and don't just copy what's here
octodns==0.9.14
octodns-route53==0.0.1
```

##### SHAs

```
# Start with the latest/specific versions and don't just copy what's here
-e git+https://git@github.com/octodns/octodns.git@9da19749e28f68407a1c246dfdf65663cdc1c422#egg=octodns
-e git+https://git@github.com/octodns/octodns-route53.git@ec9661f8b335241ae4746eea467a8509205e6a30#egg=octodns_route53
```

### Configuration

#### Route53 Provider

```yaml
providers:
  route53:
    class: octodns_route53.Route53Provider
    # The AWS access key id
    access_key_id: env/AWS_ACCESS_KEY_ID
    # The AWS secret access key
    secret_access_key: env/AWS_SECRET_ACCESS_KEY
    # The AWS session token (optional)
    # Only needed if using temporary security credentials
    #session_token: env/AWS_SESSION_TOKEN
    # The AWS profile name (optional)
    #profile:
    # Optionally restrict hosted zone lookup to only private or public zones.
    # If zone creation is required and this option is set, zones will be created as private.
    # Set to true to only use private zones, false for public zones, or omit for no restriction.
    #private: False
    # Optionally restrict hosted zone lookup to zones associated with a specific VPC.
    # When specified, only zones associated with this VPC will be managed.
    # Zone creation will automatically create private zones with this VPC association.
    # Implies private=true (VPC-associated zones are always private).
    # Cannot be used with private=false.
    # Requires vpc_region to be specified.
    #vpc_id: vpc-12345678
    # The region of the VPC specified in vpc_id.
    # Required when vpc_id is specified.
    #vpc_region: us-east-1
```

Alternatively, you may leave out access_key_id, secret_access_key and session_token.  This will result in boto3 deciding authentication dynamically.

In general the account used will need full permissions on Route53.

#### Ec2Souce

```yaml
providers:
  ec2:
    class: octodns_route53.Ec2Source
    # auth options are the same as Route53Provider
    access_key_id: env/AWS_ACCESS_KEY_ID
    secret_access_key: env/AWS_SECRET_ACCESS_KEY
    # The region in which to look for EC2 instances, required.
    region: us-east-1
    # Prefix for tag keys containing fqdn(s)
    #tag_prefix: octodns
    # String to append to all names and tag values
    #append_to_names: mydomain.com.
    #ttl: 3600
```

In general the account used will need read permissions on EC2 instances.

Records are driven off of the tags attached to the EC2 instances. The "Name" tag and any tags starting with `tag_prefix` are considered.

The value of the tag should be one or more fqdns separated by a `/` character. You can append a string to the name and all tag values with `append_to_names`.

When a zone is being populated any fqdns matching the zone name will result in records. When the instance has a private IPv4 address an A record will be created. When the instance has an IPv6 address a AAAA record will be created.

When the zone is a sub-zone of in-addr.arpa. PTR records will be created for private IPv4 addresses that match the zone. The value(s) will be the fqdn(s) associated with that private IPv4 address.

When the zone is a sub-zone of ip6.arpa. PTR records will be created for IPv6 addresses that match the zone. The value(s) will be the fqdn(s) associated with that IPv6 address.

#### ElbSouce

```yaml
providers:
  elb:
    class: octodns_route53.ElbSource
    # auth options are the same as Route53Provider
    access_key_id: env/AWS_ACCESS_KEY_ID
    secret_access_key: env/AWS_SECRET_ACCESS_KEY
    # The region in which to look for ELB instances, required.
    region: us-east-1
    # Prefix for tag keys containing fqdn(s)
    #tag_prefix: octodns
    # String to append to all names and tag values
    #append_to_names: mydomain.com.
    #ttl: 3600
```

In general the account used will need read permissions on ELB instances and tags.

Records are driven off of the ELB name and the tags attached to the ELB instances. Any tag with `tag_prefix` is considered.

The value of the tag should be one or more fqdns separated by a `/` character. You can append a string to the name and all tag values with `append_to_names`.

When a zone is being populated any fqdns matching the zone name will result in records CNAME records with the target value being the DNSName of the ELB instance.

#### Example Tags for EC2/ELB

```yaml
# This will result in an ALIAS record for example.com. -> DNSName
octodns: example.com.

# This will result in a CNAME record for foo.example.com. -> DNSName
octodns: foo.example.com.

# This will result in CNAME records for foo.example.com. and bar.other.com.
# -> DNSName
octodns: foo.example.com./bar.other.com.

# Tags are limited to 255 characters so in order to support long and/or
# numerous fqdns tags prefixed with `tag_prefix` are considered. It is also
# acceptable to add multiple tags rather than separating things with `/`
octodns-1: foo.example.com.
octodns-2: bar.other.com.
```

#### Processors

Ignores AWS ACM validation CNAME records.

```yaml
processors:
    awsacm:
    class: octodns_route53.processor.AwsAcmMangingProcessor

...

zones:
    something.com.:
    ...
    processors:
    - awsacm
    ...
```

### Support Information

#### Records

A, AAAA, CAA, CNAME, DS, MX, NAPTR, NS, PTR, SPF, SRV, TXT

#### Root NS Records

Route53Provider supports full root NS record management.

#### Dynamic

Route53Provider supports dynamic records, CNAME health checks don't support a Host header.

#### Provider Specific Types

`Route53Provider/ALIAS` adds support for the Route53 specific symlink style alias records.

```yaml
# "symlink" to another record in the same zone
alias:
    type: Route53Provider/ALIAS
    values:
    # ALIAS for the zone APEX A record
    - type: A
    # ALIAS for www.whatever.com. AAAA
    - evaluate-target-health: false
      # same-zone aliases omit the zone name
      name: www
      type: AAAA
# "symlink" to a AWS service
alb:
    type: Route53Provider/ALIAS
    value:
        # default for evaluate-target-health is False
        evaluate-target-health: true
        # hosted-zone-id should only be used when pointing to service endpoints
        hosted-zone-id: Z42SXDOTRQ7X7K
        name: dualstack.octodns-testing-1165866977.us-east-1.elb.amazonaws.com.
        type: A
```

#### Health Check Options

See https://github.com/octodns/octodns/blob/master/docs/dynamic_records.md#health-checks for information on health checking for dynamic records. Route53Provider supports the following options:

| Key  | Description | Default |
|--|--|--|
| failure_threshold | Failure threshold before state change, 1-10 | 6 |
| measure_latency | Show latency in AWS console | true |
| request_interval | Healthcheck interval [10\|30] seconds | 10 |

```yaml
---
  octodns:
    healthcheck:
      host: my-host-name
      path: /dns-health-check
      port: 443
      protocol: HTTPS
    route53:
      healthcheck:
        failure_threshold: 3
        measure_latency: false
        request_interval: 30
```

### Development

See the [/script/](/script/) directory for some tools to help with the development process. They generally follow the [Script to rule them all](https://github.com/github/scripts-to-rule-them-all) pattern. Most useful is `./script/bootstrap` which will create a venv and install both the runtime and development related requirements. It will also hook up a pre-commit hook that covers most of what's run by CI.
