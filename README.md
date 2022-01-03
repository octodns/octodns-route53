## Route53Provider provider for octoDNS

An [octoDNS](https://github.com/octodns/octodns/) provider that targets [Route53](https://aws.amazon.com/route53/).

### Installation

#### Command line

```
pip install octodns_route53
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades.

##### Versions

```
# Start with the latest versions and don't just copy what's here
octodns==0.9.14
octodns_route53==0.0.1
```

##### SHAs

```
# Start with the latest/specific versions and don't just copy what's here
-e git+https://git@github.com/octodns/octodns.git@9da19749e28f68407a1c246dfdf65663cdc1c422#egg=octodns
-e git+https://git@github.com/octodns/octodns_route53.git@ec9661f8b335241ae4746eea467a8509205e6a30#egg=octodns_powerdns
```

### Configuration

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
```

Alternatively, you may leave out access_key_id, secret_access_key and session_token.  This will result in boto3 deciding authentication dynamically.

In general the account used will need full permissions on Route53.

#### Processors

```yaml
processors:
    awsacm:
    class: octodns.processor.acme.AwsAcmMangingProcessor

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

A, AAAA, CAA, CNAME, MX, NAPTR, NS, PTR, SPF, SRV, TXT

#### Dynamic

Route53Provider supports dynamic records, CNAME health checks don't support a Host header.

### Developement

See the [/script/](/script/) directory for some tools to help with the development process. They generally follow the [Script to rule them all](https://github.com/github/scripts-to-rule-them-all) pattern. Most useful is `./script/bootstrap` which will create a venv and install both the runtime and development related requirements. It will also hook up a pre-commit hook that covers most of what's run by CI.
