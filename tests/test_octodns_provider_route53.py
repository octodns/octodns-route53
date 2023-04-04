#
#
#

from unittest import TestCase
from unittest.mock import patch

from botocore.exceptions import ClientError
from botocore.stub import ANY, Stubber

from octodns.record import Create, Delete, Record, Update
from octodns.zone import Zone

from octodns_route53 import Route53Provider, Route53ProviderException
from octodns_route53.geo_latency import GeoLatency
from octodns_route53.processor import AwsAcmMangingProcessor
from octodns_route53.provider import (
    _healthcheck_ref_prefix,
    _mod_keyer,
    _octal_replace,
    _Route53Alias,
    _Route53DynamicValue,
    _Route53GeoDefault,
    _Route53GeoRecord,
    _Route53Record,
)
from octodns_route53.record import Route53AliasRecord, _Route53AliasValue


class GeoProvider(object):
    SUPPORTS_GEO = True
    SUPPORTS_DYNAMIC = False
    id = 'test'

    def __init__(self, id='test'):
        pass

    def populate(self, zone, source=False, lenient=False):
        pass

    def supports(self, record):
        return True

    def __repr__(self):
        return self.__class__.__name__


class DummyR53Record(object):
    def __init__(self, health_check_id):
        self.health_check_id = health_check_id


class TestOctalReplace(TestCase):
    def test_basic(self):
        for expected, s in (
            ('', ''),
            ('abc', 'abc'),
            ('123', '123'),
            ('abc123', 'abc123'),
            ('*', '\\052'),
            ('abc*', 'abc\\052'),
            ('*abc', '\\052abc'),
            ('123*', '123\\052'),
            ('*123', '\\052123'),
            ('**', '\\052\\052'),
        ):
            self.assertEqual(expected, _octal_replace(s))


class TestHealthCheckRefPrefix(TestCase):
    def test_basic(self):
        for s in [
            'test.com',
            'this.is.a.very.longggggggg.record.for.testing.purposes.com',
        ]:
            self.assertLessEqual(
                len(
                    _healthcheck_ref_prefix(
                        Route53Provider.HEALTH_CHECK_VERSION, "CNAME", s
                    )
                ),
                (64 - 13),
            )

        for expected, s in (
            ('', ''),
            ('test.com', 'test.com'),
            (
                'just.enough.to.leave.fqdn.there.test.com',
                'just.enough.to.leave.fqdn.there.test.com',
            ),
            (
                '1195893dcaf4af70915e',
                'just.enough.not.leave.fqdn.there.test.com',
            ),
            (
                '008ffbe028b7fe7d8b16',
                '0001:CNAME:this.is.a.very.longggggggg.'
                'record.for.testing.purposes.com',
            ),
        ):
            self.assertEqual(
                f"{Route53Provider.HEALTH_CHECK_VERSION}:CNAME:{expected}",
                _healthcheck_ref_prefix(
                    Route53Provider.HEALTH_CHECK_VERSION, "CNAME", s
                ),
            )


dynamic_rrsets = [
    {
        'Name': '_octodns-default-pool.unit.tests.',
        'ResourceRecords': [{'Value': '1.1.2.1'}, {'Value': '1.1.2.2'}],
        'TTL': 60,
        'Type': 'A',
    },
    {
        'HealthCheckId': '76',
        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.4.1.1'}],
        'SetIdentifier': 'ap-southeast-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 2,
    },
    {
        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.4.1.2'}],
        'SetIdentifier': 'ap-southeast-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 2,
    },
    {
        'HealthCheckId': 'ab',
        'Name': '_octodns-eu-central-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.3.1.1'}],
        'SetIdentifier': 'eu-central-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '1e',
        'Name': '_octodns-eu-central-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.3.1.2'}],
        'SetIdentifier': 'eu-central-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '2a',
        'Name': '_octodns-us-east-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.5.1.1'}],
        'SetIdentifier': 'us-east-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '61',
        'Name': '_octodns-us-east-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.5.1.2'}],
        'SetIdentifier': 'us-east-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-default-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-us-east-1-pool.unit.tests.',
        'SetIdentifier': 'us-east-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-us-east-1-pool.unit.tests.',
        'SetIdentifier': 'us-east-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-eu-central-1-pool.unit.tests.',
        'SetIdentifier': 'eu-central-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-eu-central-1-pool.unit.tests.',
        'SetIdentifier': 'eu-central-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
        'SetIdentifier': 'ap-southeast-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
        'SetIdentifier': 'ap-southeast-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'CountryCode': 'JP'},
        'Name': 'unit.tests.',
        'SetIdentifier': '1-ap-southeast-1-AS-JP',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'CountryCode': 'CN'},
        'Name': 'unit.tests.',
        'SetIdentifier': '1-ap-southeast-1-AS-CN',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'ContinentCode': 'NA-US-FL'},
        'Name': 'unit.tests.',
        'SetIdentifier': '2-eu-central-1-NA-US-FL',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'ContinentCode': 'EU'},
        'Name': 'unit.tests.',
        'SetIdentifier': '2-eu-central-1-EU',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'CountryCode': '*'},
        'Name': 'unit.tests.',
        'SetIdentifier': '3-us-east-1-None',
        'Type': 'A',
    },
]
dynamic_rrsets_latency = [
    {
        'Name': '_octodns-default-pool.unit.tests.',
        'ResourceRecords': [{'Value': '1.1.2.1'}, {'Value': '1.1.2.2'}],
        'TTL': 60,
        'Type': 'A',
    },
    {
        'HealthCheckId': '76',
        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.4.1.1'}],
        'SetIdentifier': 'ap-southeast-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 2,
    },
    {
        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.4.1.2'}],
        'SetIdentifier': 'ap-southeast-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 2,
    },
    {
        'HealthCheckId': 'ab',
        'Name': '_octodns-eu-central-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.3.1.1'}],
        'SetIdentifier': 'eu-central-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '1e',
        'Name': '_octodns-eu-central-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.3.1.2'}],
        'SetIdentifier': 'eu-central-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '2a',
        'Name': '_octodns-us-east-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.5.1.1'}],
        'SetIdentifier': 'us-east-1-000',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'HealthCheckId': '61',
        'Name': '_octodns-us-east-1-value.unit.tests.',
        'ResourceRecords': [{'Value': '1.5.1.2'}],
        'SetIdentifier': 'us-east-1-001',
        'TTL': 60,
        'Type': 'A',
        'Weight': 1,
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-default-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-us-east-1-pool.unit.tests.',
        'SetIdentifier': 'us-east-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-us-east-1-pool.unit.tests.',
        'SetIdentifier': 'us-east-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-eu-central-1-pool.unit.tests.',
        'SetIdentifier': 'eu-central-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-eu-central-1-pool.unit.tests.',
        'SetIdentifier': 'eu-central-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'SECONDARY',
        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
        'SetIdentifier': 'ap-southeast-1-Secondary-default',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-value.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Failover': 'PRIMARY',
        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
        'SetIdentifier': 'ap-southeast-1-Primary',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Region': 'ap-northeast-1',
        'Name': 'unit.tests.',
        'SetIdentifier': '1-ap-southeast-1-AS-JP',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Region': 'ap-southeast-1',
        'Name': 'unit.tests.',
        'SetIdentifier': '1-ap-southeast-1-AS-SG',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Region': 'us-east-1',
        'Name': 'unit.tests.',
        'SetIdentifier': '2-eu-central-1-NA-US-VI',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'Region': 'eu-west-1',
        'Name': 'unit.tests.',
        'SetIdentifier': '2-eu-central-1-EU',
        'Type': 'A',
    },
    {
        'AliasTarget': {
            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
            'EvaluateTargetHealth': True,
            'HostedZoneId': 'Z2',
        },
        'GeoLocation': {'CountryCode': '*'},
        'Name': 'unit.tests.',
        'SetIdentifier': '3-us-east-1-None',
        'Type': 'A',
    },
]

dynamic_health_checks = {
    '76': {'HealthCheckConfig': {'Disabled': False, 'Inverted': False}},
    'ab': {'HealthCheckConfig': {'Disabled': True, 'Inverted': True}},
}

dynamic_record_data = {
    'dynamic': {
        'pools': {
            'ap-southeast-1': {
                'fallback': 'us-east-1',
                'values': [
                    {'weight': 2, 'value': '1.4.1.1', 'status': 'obey'},
                    {'weight': 2, 'value': '1.4.1.2', 'status': 'up'},
                ],
            },
            'eu-central-1': {
                'fallback': 'us-east-1',
                'values': [
                    {'weight': 1, 'value': '1.3.1.1', 'status': 'down'},
                    {'weight': 1, 'value': '1.3.1.2', 'status': 'up'},
                ],
            },
            'us-east-1': {
                'values': [
                    {'weight': 1, 'value': '1.5.1.1', 'status': 'up'},
                    {'weight': 1, 'value': '1.5.1.2', 'status': 'up'},
                ]
            },
        },
        'rules': [
            {'geos': ['AS-CN', 'AS-JP'], 'pool': 'ap-southeast-1'},
            {'geos': ['EU', 'NA-US-FL'], 'pool': 'eu-central-1'},
            {'pool': 'us-east-1'},
        ],
    },
    'ttl': 60,
    'type': 'A',
    'values': ['1.1.2.1', '1.1.2.2'],
}

dynamic_record_latency_data = {
    'dynamic': {
        'pools': {
            'ap-southeast-1': {
                'fallback': 'us-east-1',
                'values': [
                    {'weight': 2, 'value': '1.4.1.1', 'status': 'obey'},
                    {'weight': 2, 'value': '1.4.1.2', 'status': 'up'},
                ],
            },
            'eu-central-1': {
                'fallback': 'us-east-1',
                'values': [
                    {'weight': 1, 'value': '1.3.1.1', 'status': 'down'},
                    {'weight': 1, 'value': '1.3.1.2', 'status': 'up'},
                ],
            },
            'us-east-1': {
                'values': [
                    {'weight': 1, 'value': '1.5.1.1', 'status': 'up'},
                    {'weight': 1, 'value': '1.5.1.2', 'status': 'up'},
                ]
            },
        },
        'rules': [
            {'geos': ['AS-JP', 'AS-SG'], 'pool': 'ap-southeast-1'},
            {'geos': ['EU', 'NA-US-VI'], 'pool': 'eu-central-1'},
            {'pool': 'us-east-1'},
        ],
    },
    'ttl': 60,
    'type': 'A',
    'values': ['1.1.2.1', '1.1.2.2'],
    'octodns': {'route53': {'mode': 'latency'}},
}


class TestRoute53Provider(TestCase):
    expected = Zone('unit.tests.', [])
    for name, data in (
        ('simple', {'ttl': 60, 'type': 'A', 'values': ['1.2.3.4', '2.2.3.4']}),
        (
            '',
            {
                'ttl': 61,
                'type': 'A',
                'values': ['2.2.3.4', '3.2.3.4'],
                'geo': {
                    'AF': ['4.2.3.4'],
                    'NA-US': ['5.2.3.4', '6.2.3.4'],
                    'NA-US-CA': ['7.2.3.4'],
                },
            },
        ),
        ('cname', {'ttl': 62, 'type': 'CNAME', 'value': 'unit.tests.'}),
        (
            'txt',
            {
                'ttl': 63,
                'type': 'TXT',
                'values': ['Hello World!', 'Goodbye World?'],
            },
        ),
        (
            '',
            {
                'ttl': 64,
                'type': 'MX',
                'values': [
                    {'preference': 10, 'exchange': 'smtp-1.unit.tests.'},
                    {'preference': 20, 'exchange': 'smtp-2.unit.tests.'},
                ],
            },
        ),
        (
            'naptr',
            {
                'ttl': 65,
                'type': 'NAPTR',
                'value': {
                    'order': 10,
                    'preference': 20,
                    'flags': 'U',
                    'service': 'SIP+D2U',
                    'regexp': '!^.*$!sip:info@bar.example.com!',
                    'replacement': '.',
                },
            },
        ),
        (
            '_srv._tcp',
            {
                'ttl': 66,
                'type': 'SRV',
                'value': {
                    'priority': 10,
                    'weight': 20,
                    'port': 30,
                    'target': 'cname.unit.tests.',
                },
            },
        ),
        ('', {'ttl': 67, 'type': 'NS', 'values': ['ns1.unit.tests.']}),
        ('sub', {'ttl': 68, 'type': 'NS', 'values': ['5.2.3.4.', '6.2.3.4.']}),
        (
            '',
            {
                'ttl': 69,
                'type': 'CAA',
                'value': {'flags': 0, 'tag': 'issue', 'value': 'ca.unit.tests'},
            },
        ),
        (
            'alias',
            {
                'ttl': 942942942,
                'type': 'Route53Provider/ALIAS',
                'values': [
                    {'name': '', 'type': 'A'},
                    {'name': 'naptr', 'type': 'NAPTR'},
                ],
            },
        ),
        (
            'alb',
            {
                'ttl': 942942942,
                'type': 'Route53Provider/ALIAS',
                'values': [
                    {
                        'evaluate-target-health': True,
                        'hosted-zone-id': 'Z35SXDOTRQ7X7K',
                        'name': 'dualstack.octodns-testing-1425816977.us-east-1.elb.'
                        'amazonaws.com.',
                        'type': 'A',
                    }
                ],
            },
        ),
    ):
        record = Record.new(expected, name, data)
        expected.add_record(record)

    caller_ref = f'{Route53Provider.HEALTH_CHECK_VERSION}:A:unit.tests.:1324'

    health_checks = [
        {
            'Id': '42',
            'CallerReference': caller_ref,
            'HealthCheckConfig': {
                'Disabled': False,
                'EnableSNI': True,
                'Inverted': False,
                'Type': 'HTTPS',
                'FullyQualifiedDomainName': 'unit.tests',
                'IPAddress': '4.2.3.4',
                'ResourcePath': '/_dns',
                'Type': 'HTTPS',
                'Port': 443,
                'MeasureLatency': True,
                'RequestInterval': 10,
                'FailureThreshold': 6,
            },
            'HealthCheckVersion': 2,
        },
        {
            'Id': 'ignored-also',
            'CallerReference': 'something-else',
            'HealthCheckConfig': {
                'Disabled': False,
                'EnableSNI': True,
                'Inverted': False,
                'Type': 'HTTPS',
                'FullyQualifiedDomainName': 'unit.tests',
                'IPAddress': '5.2.3.4',
                'ResourcePath': '/_dns',
                'Type': 'HTTPS',
                'Port': 443,
                'MeasureLatency': True,
                'RequestInterval': 10,
                'FailureThreshold': 6,
            },
            'HealthCheckVersion': 42,
        },
        {
            'Id': '43',
            'CallerReference': caller_ref,
            'HealthCheckConfig': {
                'Disabled': False,
                'EnableSNI': True,
                'Inverted': False,
                'Type': 'HTTPS',
                'FullyQualifiedDomainName': 'unit.tests',
                'IPAddress': '5.2.3.4',
                'ResourcePath': '/_dns',
                'Type': 'HTTPS',
                'Port': 443,
                'MeasureLatency': True,
                'RequestInterval': 10,
                'FailureThreshold': 6,
            },
            'HealthCheckVersion': 2,
        },
        {
            'Id': '44',
            'CallerReference': caller_ref,
            'HealthCheckConfig': {
                'Disabled': False,
                'EnableSNI': True,
                'Inverted': False,
                'Type': 'HTTPS',
                'FullyQualifiedDomainName': 'unit.tests',
                'IPAddress': '7.2.3.4',
                'ResourcePath': '/_dns',
                'Type': 'HTTPS',
                'Port': 443,
                'MeasureLatency': True,
                'RequestInterval': 10,
                'FailureThreshold': 6,
            },
            'HealthCheckVersion': 2,
        },
        {
            'Id': '45',
            # won't match anything based on type
            'CallerReference': caller_ref.replace(':A:', ':AAAA:'),
            'HealthCheckConfig': {
                'Disabled': False,
                'EnableSNI': True,
                'Inverted': False,
                'Type': 'HTTPS',
                'FullyQualifiedDomainName': 'unit.tests',
                'IPAddress': '7.2.3.4',
                'ResourcePath': '/_dns',
                'Type': 'HTTPS',
                'Port': 443,
                'MeasureLatency': True,
                'RequestInterval': 10,
                'FailureThreshold': 6,
            },
            'HealthCheckVersion': 2,
        },
    ]

    def _get_stubbed_provider(self):
        provider = Route53Provider('test', 'abc', '123', strict_supports=False)

        # Use the stubber
        stubber = Stubber(provider._conn)
        stubber.activate()

        return (provider, stubber)

    def _get_stubbed_delegation_set_provider(self):
        provider = Route53Provider(
            'test',
            'abc',
            '123',
            delegation_set_id="ABCDEFG123456",
            strict_supports=False,
        )

        # Use the stubber
        stubber = Stubber(provider._conn)
        stubber.activate()

        return (provider, stubber)

    def _get_stubbed_fallback_auth_provider(self):
        provider = Route53Provider('test', strict_supports=False)

        # Use the stubber
        stubber = Stubber(provider._conn)
        stubber.activate()

        return (provider, stubber)

    def _get_stubbed_get_zones_by_name_enabled_provider(self):
        provider = Route53Provider(
            'test', 'abc', '123', get_zones_by_name=True, strict_supports=False
        )

        # Use the stubber
        stubber = Stubber(provider._conn)
        stubber.activate()

        return (provider, stubber)

    def test_update_r53_zones(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones = {
            'HostedZones': [
                {
                    'Id': 'z40',
                    'Name': 'unit.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }

        stubber.add_response('list_hosted_zones', list_hosted_zones)

        provider.update_r53_zones("unit.tests.")
        self.assertEqual(provider._r53_zones, {'unit.tests.': 'z40'})

    def test_update_r53_zones_with_get_zones_by_name(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        list_hosted_zones_by_name_resp = {
            'HostedZones': [
                {
                    'Id': 'z40',
                    'Name': 'unit.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': 'unit.tests.',
            'IsTruncated': False,
            'MaxItems': '1',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp,
            {'DNSName': 'unit.tests.', 'MaxItems': '1'},
        )

        provider.update_r53_zones("unit.tests.")
        self.assertEqual(provider._r53_zones, {'unit.tests.': 'z40'})

    def test_update_r53_zones_with_octal_replaced(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones = {
            'HostedZones': [
                {
                    'Id': 'z41',
                    'Name': '0\\05725.2.0.192.in-addr.arpa.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }

        stubber.add_response('list_hosted_zones', list_hosted_zones)

        provider.update_r53_zones("0/25.2.0.192.in-addr.arpa.")
        self.assertEqual(
            provider._r53_zones, {'0/25.2.0.192.in-addr.arpa.': 'z41'}
        )

    def test_update_r53_zones_with_get_zones_by_name_octal_replaced(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        list_hosted_zones_by_name_resp = {
            'HostedZones': [
                {
                    'Id': 'z41',
                    'Name': '0\\05725.2.0.192.in-addr.arpa.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': '0/25.2.0.192.in-addr.arpa.',
            'IsTruncated': False,
            'MaxItems': '1',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp,
            {'DNSName': '0/25.2.0.192.in-addr.arpa.', 'MaxItems': '1'},
        )

        provider.update_r53_zones("0/25.2.0.192.in-addr.arpa.")
        self.assertEqual(
            provider._r53_zones, {'0/25.2.0.192.in-addr.arpa.': 'z41'}
        )

    # with fallback boto makes an unstubbed call to the 169. metadata api, this
    # stubs that bit out
    @patch('botocore.credentials.CredentialResolver.load_credentials')
    def test_process_desired_zone(self, fetch_metadata_token_mock):
        provider, stubber = self._get_stubbed_fallback_auth_provider()
        fetch_metadata_token_mock.side_effect = [None]

        # No records, essentially a no-op
        desired = Zone('unit.tests.', [])
        ns_record = Record.new(
            desired,
            '',
            data={
                'type': 'NS',
                'ttl': 1800,
                'values': ('ns1.unit.tests.', 'ns2.unit.tests.'),
            },
        )
        desired.add_record(ns_record)
        got = provider._process_desired_zone(desired)
        self.assertEqual(desired.records, got.records)

        # Record without any geos
        desired = Zone('unit.tests.', [])
        desired.add_record(ns_record)
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {'one': {'values': [{'value': '2.2.3.4'}]}},
                    'rules': [{'pool': 'one'}],
                },
            },
        )
        desired.add_record(record)
        got = provider._process_desired_zone(desired)
        self.assertEqual(desired.records, got.records)
        dynamic = [r for r in got.records if r._type == 'A'][0]
        self.assertEqual(1, len(dynamic.dynamic.rules))
        self.assertFalse('geos' in dynamic.dynamic.rules[0].data)

        # Record where all geos are supported
        desired = Zone('unit.tests.', [])
        desired.add_record(ns_record)
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': '1.2.3.4'}]},
                        'two': {'values': [{'value': '2.2.3.4'}]},
                    },
                    'rules': [
                        {'geos': ['EU', 'NA-US-OR'], 'pool': 'two'},
                        {'pool': 'one'},
                    ],
                },
            },
        )
        desired.add_record(record)
        got = provider._process_desired_zone(desired)
        dynamic = [r for r in got.records if r._type == 'A'][0]
        self.assertEqual(2, len(dynamic.dynamic.rules))
        self.assertEqual(
            ['EU', 'NA-US-OR'], dynamic.dynamic.rules[0].data['geos']
        )
        self.assertFalse('geos' in dynamic.dynamic.rules[1].data)

        # Record with NA-CA-* only rule which is removed
        desired = Zone('unit.tests.', [])
        desired.add_record(ns_record)
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': '1.2.3.4'}]},
                        'two': {'values': [{'value': '2.2.3.4'}]},
                    },
                    'rules': [
                        {'geos': ['NA-CA-BC'], 'pool': 'two'},
                        {'pool': 'one'},
                    ],
                },
            },
        )
        desired.add_record(record)
        got = provider._process_desired_zone(desired)
        dynamic = [r for r in got.records if r._type == 'A'][0]
        self.assertEqual(1, len(dynamic.dynamic.rules))
        self.assertFalse('geos' in dynamic.dynamic.rules[0].data)

        # Record with NA-CA-* rule combined with other geos, filtered
        desired = Zone('unit.tests.', [])
        desired.add_record(ns_record)
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': '1.2.3.4'}]},
                        'two': {'values': [{'value': '2.2.3.4'}]},
                    },
                    'rules': [
                        {'geos': ['EU', 'NA-CA-NB', 'NA-US-OR'], 'pool': 'two'},
                        {'pool': 'one'},
                    ],
                },
            },
        )
        desired.add_record(record)
        got = provider._process_desired_zone(desired)
        dynamic = [r for r in got.records if r._type == 'A'][0]
        self.assertEqual(2, len(dynamic.dynamic.rules))
        self.assertEqual(
            ['EU', 'NA-US-OR'], dynamic.dynamic.rules[0].data['geos']
        )
        self.assertFalse('geos' in dynamic.dynamic.rules[1].data)

    # with fallback boto makes an unstubbed call to the 169. metadata api, this
    # stubs that bit out
    @patch('botocore.credentials.CredentialResolver.load_credentials')
    def test_populate_with_fallback(self, fetch_metadata_token_mock):
        provider, stubber = self._get_stubbed_fallback_auth_provider()
        fetch_metadata_token_mock.side_effect = [None]

        got = Zone('unit.tests.', [])
        with self.assertRaises(ClientError):
            stubber.add_client_error('list_hosted_zones')
            provider.populate(got)

    def test_populate(self):
        provider, stubber = self._get_stubbed_provider()

        got = Zone('unit.tests.', [])
        with self.assertRaises(ClientError):
            stubber.add_client_error('list_hosted_zones')
            provider.populate(got)

        with self.assertRaises(ClientError):
            list_hosted_zones_resp = {
                'HostedZones': [
                    {
                        'Name': 'unit.tests.',
                        'Id': 'z42',
                        'CallerReference': 'abc',
                    }
                ],
                'Marker': 'm',
                'IsTruncated': False,
                'MaxItems': '100',
            }
            stubber.add_response(
                'list_hosted_zones', list_hosted_zones_resp, {}
            )
            stubber.add_client_error(
                'list_resource_record_sets',
                expected_params={'HostedZoneId': u'z42'},
            )
            provider.populate(got)
            stubber.assert_no_pending_responses()

        # list_hosted_zones has been cached from now on so we don't have to
        # worry about stubbing it

        list_resource_record_sets_resp_p1 = {
            'ResourceRecordSets': [
                {
                    'Name': 'simple.unit.tests.',
                    'Type': 'A',
                    'ResourceRecords': [
                        {'Value': '1.2.3.4'},
                        {'Value': '2.2.3.4'},
                    ],
                    'TTL': 60,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [
                        {'Value': '2.2.3.4'},
                        {'Value': '3.2.3.4'},
                    ],
                    'TTL': 61,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'AF'},
                    'ResourceRecords': [{'Value': '4.2.3.4'}],
                    'TTL': 61,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': 'US'},
                    'ResourceRecords': [
                        {'Value': '5.2.3.4'},
                        {'Value': '6.2.3.4'},
                    ],
                    'TTL': 61,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {
                        'CountryCode': 'US',
                        'SubdivisionCode': 'CA',
                    },
                    'ResourceRecords': [{'Value': '7.2.3.4'}],
                    'TTL': 61,
                },
            ],
            'IsTruncated': True,
            'NextRecordName': 'next_name',
            'NextRecordType': 'next_type',
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp_p1,
            {'HostedZoneId': 'z42'},
        )

        list_resource_record_sets_resp_p2 = {
            'ResourceRecordSets': [
                {
                    'Name': 'cname.unit.tests.',
                    'Type': 'CNAME',
                    'ResourceRecords': [{'Value': 'unit.tests.'}],
                    'TTL': 62,
                },
                {
                    'Name': 'txt.unit.tests.',
                    'Type': 'TXT',
                    'ResourceRecords': [
                        {'Value': '"Hello World!"'},
                        {'Value': '"Goodbye World?"'},
                    ],
                    'TTL': 63,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'MX',
                    'ResourceRecords': [
                        {'Value': '10 smtp-1.unit.tests.'},
                        {'Value': '20  smtp-2.unit.tests.'},
                    ],
                    'TTL': 64,
                },
                {
                    'Name': 'naptr.unit.tests.',
                    'Type': 'NAPTR',
                    'ResourceRecords': [
                        {
                            'Value': '10 20 "U" "SIP+D2U" '
                            '"!^.*$!sip:info@bar.example.com!" .'
                        }
                    ],
                    'TTL': 65,
                },
                {
                    'Name': '_srv._tcp.unit.tests.',
                    'Type': 'SRV',
                    'ResourceRecords': [
                        {'Value': '10 20 30 cname.unit.tests.'}
                    ],
                    'TTL': 66,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'NS',
                    'ResourceRecords': [{'Value': 'ns1.unit.tests.'}],
                    'TTL': 67,
                },
                {
                    'Name': 'sub.unit.tests.',
                    'Type': 'NS',
                    'GeoLocation': {'ContinentCode': 'AF'},
                    'ResourceRecords': [
                        {'Value': '5.2.3.4.'},
                        {'Value': '6.2.3.4.'},
                    ],
                    'TTL': 68,
                },
                {
                    'Name': 'soa.unit.tests.',
                    'Type': 'SOA',
                    'ResourceRecords': [{'Value': 'ns1.unit.tests.'}],
                    'TTL': 69,
                },
                {
                    'Name': 'unit.tests.',
                    'Type': 'CAA',
                    'ResourceRecords': [{'Value': '0 issue "ca.unit.tests"'}],
                    'TTL': 69,
                },
                {
                    'AliasTarget': {
                        'HostedZoneId': 'Z119WBBTVP5WFX',
                        'EvaluateTargetHealth': False,
                        'DNSName': 'unit.tests.',
                    },
                    'Type': 'A',
                    'Name': 'alias.unit.tests.',
                },
                {
                    'AliasTarget': {
                        'HostedZoneId': 'Z119WBBTVP5WFX',
                        'EvaluateTargetHealth': False,
                        'DNSName': 'naptr.unit.tests.',
                    },
                    'Type': 'NAPTR',
                    'Name': 'alias.unit.tests.',
                },
                {
                    'AliasTarget': {
                        'HostedZoneId': 'Z35SXDOTRQ7X7K',
                        'EvaluateTargetHealth': True,
                        'DNSName': 'dualstack.octodns-testing-1425816977.'
                        'us-east-1.elb.amazonaws.com.',
                    },
                    'Type': 'A',
                    'Name': 'alb.unit.tests.',
                },
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp_p2,
            {
                'HostedZoneId': 'z42',
                'StartRecordName': 'next_name',
                'StartRecordType': 'next_type',
            },
        )

        # Load everything
        provider.populate(got)
        # Make sure we got what we expected
        changes = self.expected.changes(got, GeoProvider())
        self.assertEqual(0, len(changes))
        stubber.assert_no_pending_responses()

        # Populate a zone that doesn't exist
        nonexistent = Zone('does.not.exist.', [])
        provider.populate(nonexistent)
        self.assertEqual(set(), nonexistent.records)

    def test_populate_for_octal_replaced_domain_name(self):
        provider, stubber = self._get_stubbed_provider()

        expected = Zone('0/25.2.0.192.in-addr.arpa.', [])
        record = Record.new(
            expected,
            '1',
            {'ttl': 30, 'type': 'PTR', 'value': 'hostname.example.com.'},
        )
        expected.add_record(record)

        got = Zone('0/25.2.0.192.in-addr.arpa.', [])

        list_hosted_zones_resp = {
            'HostedZones': [
                {
                    'Name': '0\\05725.2.0.192.in-addr.arpa.',
                    'Id': 'z41',
                    'CallerReference': 'abc',
                }
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': '1.0\\05725.2.0.192.in-addr.arpa.',
                    'Type': 'PTR',
                    'ResourceRecords': [{'Value': 'hostname.example.com.'}],
                    'TTL': 30,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z41'},
        )

        # Load everything
        provider.populate(got)
        # Make sure we got what we expected
        changes = expected.changes(got, GeoProvider())
        self.assertEqual(0, len(changes))
        stubber.assert_no_pending_responses()

    def test_sync(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        plan = provider.plan(self.expected)
        self.assertEqual(12, len(plan.changes))
        self.assertTrue(plan.exists)
        for change in plan.changes:
            self.assertIsInstance(change, Create)
        stubber.assert_no_pending_responses()

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )
        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        self.assertEqual(12, provider.apply(plan))
        stubber.assert_no_pending_responses()

        # Delete by monkey patching in a populate that includes an extra record
        def add_extra_populate(existing, target, lenient):
            for record in self.expected.records:
                existing.add_record(record)
            record = Record.new(
                existing,
                'extra',
                {'ttl': 99, 'type': 'A', 'values': ['9.9.9.9']},
            )
            existing.add_record(record)

        provider.populate = add_extra_populate
        change_resource_record_sets_params = {
            'ChangeBatch': {
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': {
                            'Name': 'extra.unit.tests.',
                            'ResourceRecords': [{'Value': u'9.9.9.9'}],
                            'TTL': 99,
                            'Type': 'A',
                        },
                    }
                ],
                u'Comment': ANY,
            },
            'HostedZoneId': u'z42',
        }
        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            change_resource_record_sets_params,
        )
        plan = provider.plan(self.expected)
        self.assertEqual(1, len(plan.changes))
        self.assertIsInstance(plan.changes[0], Delete)
        self.assertEqual(1, provider.apply(plan))
        stubber.assert_no_pending_responses()

        # Update by monkey patching in a populate that modifies the A record
        # with geos
        def mod_geo_populate(existing, target, lenient):
            for record in self.expected.records:
                if record._type != 'A' or not record.geo:
                    existing.add_record(record)
            record = Record.new(
                existing,
                '',
                {
                    'ttl': 61,
                    'type': 'A',
                    'values': ['8.2.3.4', '3.2.3.4'],
                    'geo': {
                        'AF': ['4.2.3.4'],
                        'NA-US': ['5.2.3.4', '6.2.3.4'],
                        'NA-US-KY': ['7.2.3.4'],
                    },
                },
            )
            existing.add_record(record)

        provider.populate = mod_geo_populate
        change_resource_record_sets_params = {
            'ChangeBatch': {
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': {
                            'GeoLocation': {
                                'CountryCode': 'US',
                                'SubdivisionCode': 'KY',
                            },
                            'HealthCheckId': u'44',
                            'Name': 'unit.tests.',
                            'ResourceRecords': [{'Value': '7.2.3.4'}],
                            'SetIdentifier': 'NA-US-KY',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'GeoLocation': {'ContinentCode': 'AF'},
                            'Name': 'unit.tests.',
                            'HealthCheckId': u'42',
                            'ResourceRecords': [{'Value': '4.2.3.4'}],
                            'SetIdentifier': 'AF',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'GeoLocation': {'CountryCode': 'US'},
                            'HealthCheckId': u'43',
                            'Name': 'unit.tests.',
                            'ResourceRecords': [
                                {'Value': '5.2.3.4'},
                                {'Value': '6.2.3.4'},
                            ],
                            'SetIdentifier': 'NA-US',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'CREATE',
                        'ResourceRecordSet': {
                            'GeoLocation': {
                                'CountryCode': 'US',
                                'SubdivisionCode': 'CA',
                            },
                            'HealthCheckId': u'44',
                            'Name': 'unit.tests.',
                            'ResourceRecords': [{'Value': '7.2.3.4'}],
                            'SetIdentifier': 'NA-US-CA',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'GeoLocation': {'CountryCode': '*'},
                            'Name': 'unit.tests.',
                            'ResourceRecords': [
                                {'Value': '2.2.3.4'},
                                {'Value': '3.2.3.4'},
                            ],
                            'SetIdentifier': 'default',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                ],
                'Comment': ANY,
            },
            'HostedZoneId': 'z42',
        }
        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            change_resource_record_sets_params,
        )
        plan = provider.plan(self.expected)
        self.assertEqual(1, len(plan.changes))
        self.assertIsInstance(plan.changes[0], Update)
        self.assertEqual(1, provider.apply(plan))
        stubber.assert_no_pending_responses()

        # Update converting to non-geo by monkey patching in a populate that
        # modifies the A record with geos
        def mod_add_geo_populate(existing, target, lenient):
            for record in self.expected.records:
                if record._type != 'A' or record.geo:
                    existing.add_record(record)
            record = Record.new(
                existing,
                'simple',
                {
                    'ttl': 61,
                    'type': 'A',
                    'values': ['1.2.3.4', '2.2.3.4'],
                    'geo': {'OC': ['3.2.3.4', '4.2.3.4']},
                },
            )
            existing.add_record(record)

        provider.populate = mod_add_geo_populate
        change_resource_record_sets_params = {
            'ChangeBatch': {
                'Changes': [
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': {
                            'GeoLocation': {'ContinentCode': 'OC'},
                            'Name': 'simple.unit.tests.',
                            'ResourceRecords': [
                                {'Value': '3.2.3.4'},
                                {'Value': '4.2.3.4'},
                            ],
                            'SetIdentifier': 'OC',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'DELETE',
                        'ResourceRecordSet': {
                            'GeoLocation': {'CountryCode': '*'},
                            'Name': 'simple.unit.tests.',
                            'ResourceRecords': [
                                {'Value': '1.2.3.4'},
                                {'Value': '2.2.3.4'},
                            ],
                            'SetIdentifier': 'default',
                            'TTL': 61,
                            'Type': 'A',
                        },
                    },
                    {
                        'Action': 'CREATE',
                        'ResourceRecordSet': {
                            'Name': 'simple.unit.tests.',
                            'ResourceRecords': [
                                {'Value': '1.2.3.4'},
                                {'Value': '2.2.3.4'},
                            ],
                            'TTL': 60,
                            'Type': 'A',
                        },
                    },
                ],
                'Comment': ANY,
            },
            'HostedZoneId': 'z42',
        }
        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            change_resource_record_sets_params,
        )
        plan = provider.plan(self.expected)
        self.assertEqual(1, len(plan.changes))
        self.assertIsInstance(plan.changes[0], Update)
        self.assertEqual(1, provider.apply(plan))
        stubber.assert_no_pending_responses()

    def test_sync_create(self):
        provider, stubber = self._get_stubbed_provider()

        got = Zone('unit.tests.', [])

        list_hosted_zones_resp = {
            'HostedZones': [],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        plan = provider.plan(self.expected)
        self.assertEqual(12, len(plan.changes))
        self.assertFalse(plan.exists)
        for change in plan.changes:
            self.assertIsInstance(change, Create)
        stubber.assert_no_pending_responses()

        create_hosted_zone_resp = {
            'HostedZone': {
                'Name': 'unit.tests.',
                'Id': 'z42',
                'CallerReference': 'abc',
            },
            'ChangeInfo': {
                'Id': 'a12',
                'Status': 'PENDING',
                'SubmittedAt': '2017-01-29T01:02:03Z',
                'Comment': 'hrm',
            },
            'DelegationSet': {
                'Id': 'b23',
                'CallerReference': 'blip',
                'NameServers': ['n12.unit.tests.'],
            },
            'Location': 'us-east-1',
        }
        stubber.add_response(
            'create_hosted_zone',
            create_hosted_zone_resp,
            {'Name': got.name, 'CallerReference': ANY},
        )

        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        self.assertEqual(12, provider.apply(plan))
        stubber.assert_no_pending_responses()

    def test_sync_create_with_delegation_set(self):
        provider, stubber = self._get_stubbed_delegation_set_provider()

        got = Zone('unit.tests.', [])

        list_hosted_zones_resp = {
            'HostedZones': [],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        plan = provider.plan(self.expected)
        self.assertEqual(12, len(plan.changes))
        self.assertFalse(plan.exists)
        for change in plan.changes:
            self.assertIsInstance(change, Create)
        stubber.assert_no_pending_responses()

        create_hosted_zone_resp = {
            'HostedZone': {
                'Name': 'unit.tests.',
                'Id': 'z42',
                'CallerReference': 'abc',
            },
            'ChangeInfo': {
                'Id': 'a12',
                'Status': 'PENDING',
                'SubmittedAt': '2017-01-29T01:02:03Z',
                'Comment': 'hrm',
            },
            'DelegationSet': {
                'Id': 'b23',
                'CallerReference': 'blip',
                'NameServers': ['n12.unit.tests.'],
            },
            'Location': 'us-east-1',
        }
        stubber.add_response(
            'create_hosted_zone',
            create_hosted_zone_resp,
            {
                'Name': got.name,
                'CallerReference': ANY,
                'DelegationSetId': 'ABCDEFG123456',
            },
        )

        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        self.assertEqual(12, provider.apply(plan))
        stubber.assert_no_pending_responses()

    def test_health_checks_pagination(self):
        provider, stubber = self._get_stubbed_provider()

        health_checks_p1 = [
            {
                'Id': '42',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '43',
                'CallerReference': 'abc123',
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '9.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
        ]
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': health_checks_p1,
                'IsTruncated': True,
                'MaxItems': '2',
                'Marker': '',
                'NextMarker': 'moar',
            },
        )

        health_checks_p2 = [
            {
                'Id': '44',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '8.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            }
        ]
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': health_checks_p2,
                'IsTruncated': False,
                'MaxItems': '2',
                'Marker': 'moar',
            },
            {'Marker': 'moar'},
        )

        health_checks = provider.health_checks
        self.assertEqual(
            {'42': health_checks_p1[0], '44': health_checks_p2[0]},
            health_checks,
        )
        stubber.assert_no_pending_responses()

        # get without create
        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'A',
                'values': ['2.2.3.4', '3.2.3.4'],
                'geo': {'AF': ['4.2.3.4']},
            },
        )
        value = record.geo['AF'].values[0]
        id = provider.get_health_check_id(record, value, 'obey', True)
        self.assertEqual('42', id)

    def test_health_check_status_support(self):
        provider, stubber = self._get_stubbed_provider()

        health_checks = [
            {
                'Id': '42',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '1.1.1.1',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '43',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': True,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '2.2.2.2',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '44',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': True,
                    'EnableSNI': True,
                    'Inverted': True,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '3.3.3.3',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
        ]
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': health_checks,
                'IsTruncated': False,
                'MaxItems': '20',
                'Marker': '',
            },
        )

        health_checks = provider.health_checks

        # get without create
        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'A',
                'value': '5.5.5.5',
                'dynamic': {
                    'pools': {'main': {'values': [{'value': '6.6.6.6'}]}},
                    'rules': [{'pool': 'main'}],
                },
            },
        )
        self.assertEqual(
            '42', provider.get_health_check_id(record, '1.1.1.1', 'obey', False)
        )
        self.assertEqual(
            None, provider.get_health_check_id(record, '2.2.2.2', 'up', False)
        )
        self.assertEqual(
            '44', provider.get_health_check_id(record, '3.3.3.3', 'down', False)
        )

        # If we're not allowed to create we won't find a health check for
        # 1.1.1.1 with status up or down
        self.assertFalse(
            provider.get_health_check_id(record, '1.1.1.1', 'up', False)
        )
        self.assertFalse(
            provider.get_health_check_id(record, '1.1.1.1', 'down', False)
        )

    def test_health_check_create(self):
        provider, stubber = self._get_stubbed_provider()

        # No match based on type
        caller_ref = f'{Route53Provider.HEALTH_CHECK_VERSION}:AAAA:foo1234'
        health_checks = [
            {
                'Id': '42',
                # No match based on version
                'CallerReference': '9999:A:foo1234',
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '43',
                'CallerReference': caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
        ]
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        health_check_config = {
            'Disabled': False,
            'EnableSNI': False,
            'Inverted': False,
            'FailureThreshold': 6,
            'FullyQualifiedDomainName': 'foo.bar.com',
            'IPAddress': '4.2.3.4',
            'MeasureLatency': True,
            'Port': 8080,
            'RequestInterval': 10,
            'ResourcePath': '/_status',
            'Type': 'HTTP',
        }
        stubber.add_response(
            'create_health_check',
            {
                'HealthCheck': {
                    'Id': '42',
                    'CallerReference': self.caller_ref,
                    'HealthCheckConfig': health_check_config,
                    'HealthCheckVersion': 1,
                },
                'Location': 'http://url',
            },
            {'CallerReference': ANY, 'HealthCheckConfig': health_check_config},
        )
        stubber.add_response('change_tags_for_resource', {})

        health_check_config = {
            'Disabled': False,
            'EnableSNI': False,
            'Inverted': False,
            'FailureThreshold': 6,
            'FullyQualifiedDomainName': '4.2.3.4',
            'IPAddress': '4.2.3.4',
            'MeasureLatency': True,
            'Port': 8080,
            'RequestInterval': 10,
            'FailureThreshold': 6,
            'ResourcePath': '/_status',
            'Type': 'HTTP',
        }
        stubber.add_response(
            'create_health_check',
            {
                'HealthCheck': {
                    'Id': '43',
                    'CallerReference': self.caller_ref,
                    'HealthCheckConfig': health_check_config,
                    'HealthCheckVersion': 1,
                },
                'Location': 'http://url',
            },
            {'CallerReference': ANY, 'HealthCheckConfig': health_check_config},
        )
        stubber.add_response('change_tags_for_resource', {})

        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'A',
                'values': ['2.2.3.4', '3.2.3.4'],
                'geo': {'AF': ['4.2.3.4']},
                'octodns': {
                    'healthcheck': {
                        'host': 'foo.bar.com',
                        'path': '/_status',
                        'port': 8080,
                        'protocol': 'HTTP',
                    }
                },
            },
        )

        # if not allowed to create returns none
        value = record.geo['AF'].values[0]
        id = provider.get_health_check_id(record, value, 'obey', False)
        self.assertFalse(id)

        # when allowed to create we do
        id = provider.get_health_check_id(record, value, 'obey', True)
        self.assertEqual('42', id)

        # when allowed to create and when host is None
        record._octodns['healthcheck']['host'] = None
        id = provider.get_health_check_id(record, value, 'obey', True)
        self.assertEqual('43', id)
        stubber.assert_no_pending_responses()

        # A CNAME style healthcheck, without a value

        health_check_config = {
            'Disabled': False,
            'EnableSNI': False,
            'Inverted': False,
            'FailureThreshold': 6,
            'FullyQualifiedDomainName': 'target-1.unit.tests.',
            'MeasureLatency': True,
            'Port': 8080,
            'RequestInterval': 10,
            'FailureThreshold': 6,
            'ResourcePath': '/_status',
            'Type': 'HTTP',
        }
        stubber.add_response(
            'create_health_check',
            {
                'HealthCheck': {
                    'Id': '42',
                    'CallerReference': self.caller_ref,
                    'HealthCheckConfig': health_check_config,
                    'HealthCheckVersion': 1,
                },
                'Location': 'http://url',
            },
            {'CallerReference': ANY, 'HealthCheckConfig': health_check_config},
        )
        stubber.add_response('change_tags_for_resource', {})

        id = provider.get_health_check_id(
            record, 'target-1.unit.tests.', 'obey', True
        )
        self.assertEqual('42', id)
        stubber.assert_no_pending_responses()

        # TCP health check

        health_check_config = {
            'Disabled': False,
            'EnableSNI': False,
            'Inverted': False,
            'FailureThreshold': 6,
            'FullyQualifiedDomainName': 'target-1.unit.tests.',
            'MeasureLatency': True,
            'Port': 8080,
            'RequestInterval': 10,
            'FailureThreshold': 6,
            'Type': 'TCP',
        }
        stubber.add_response(
            'create_health_check',
            {
                'HealthCheck': {
                    'Id': '42',
                    'CallerReference': self.caller_ref,
                    'HealthCheckConfig': health_check_config,
                    'HealthCheckVersion': 1,
                },
                'Location': 'http://url',
            },
            {'CallerReference': ANY, 'HealthCheckConfig': health_check_config},
        )
        stubber.add_response('change_tags_for_resource', {})

        record._octodns['healthcheck']['protocol'] = 'TCP'
        id = provider.get_health_check_id(
            record, 'target-1.unit.tests.', 'obey', True
        )
        self.assertEqual('42', id)
        stubber.assert_no_pending_responses()

    def test_health_check_provider_options(self):
        provider, stubber = self._get_stubbed_provider()
        record = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '1.2.3.4',
                'octodns': {
                    'healthcheck': {},
                    'route53': {
                        'healthcheck': {
                            'measure_latency': True,
                            'request_interval': 10,
                            'failure_threshold': 3,
                        }
                    },
                },
            },
        )
        latency = provider._healthcheck_measure_latency(record)
        interval = provider._healthcheck_request_interval(record)
        threshold = provider._healthcheck_failure_threshold(record)
        self.assertTrue(latency)
        self.assertEqual(10, interval)
        self.assertEqual(3, threshold)

        record_default = Record.new(
            self.expected, 'a', {'ttl': 61, 'type': 'A', 'value': '1.2.3.4'}
        )
        latency = provider._healthcheck_measure_latency(record_default)
        interval = provider._healthcheck_request_interval(record_default)
        threshold = provider._healthcheck_failure_threshold(record_default)
        self.assertTrue(latency)
        self.assertEqual(10, interval)
        self.assertEqual(6, threshold)

        record = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '1.2.3.4',
                'octodns': {
                    'healthcheck': {},
                    'route53': {
                        'healthcheck': {
                            'measure_latency': False,
                            'request_interval': 30,
                            'failure_threshold': 10,
                        }
                    },
                },
            },
        )
        latency = provider._healthcheck_measure_latency(record)
        interval = provider._healthcheck_request_interval(record)
        threshold = provider._healthcheck_failure_threshold(record)
        self.assertFalse(latency)
        self.assertEqual(30, interval)
        self.assertEqual(10, threshold)

        record_invalid = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '1.2.3.4',
                'octodns': {
                    'healthcheck': {},
                    'route53': {'healthcheck': {'request_interval': 20}},
                },
            },
        )
        with self.assertRaises(Route53ProviderException):
            interval = provider._healthcheck_request_interval(record_invalid)

        record_invalid = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '1.2.3.4',
                'octodns': {
                    'healthcheck': {},
                    'route53': {'healthcheck': {'failure_threshold': 0}},
                },
            },
        )
        with self.assertRaises(Route53ProviderException):
            threshold = provider._healthcheck_failure_threshold(record_invalid)

        record_invalid = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '1.2.3.4',
                'octodns': {
                    'healthcheck': {},
                    'route53': {'healthcheck': {'failure_threshold': 1.1}},
                },
            },
        )
        with self.assertRaises(Route53ProviderException):
            threshold = provider._healthcheck_failure_threshold(record_invalid)

    def test_create_health_checks_provider_options(self):
        provider, stubber = self._get_stubbed_provider()

        health_check_config = {
            'Disabled': False,
            'EnableSNI': True,
            'Inverted': False,
            'FailureThreshold': 2,
            'FullyQualifiedDomainName': 'a.unit.tests',
            'IPAddress': '1.2.3.4',
            'MeasureLatency': False,
            'Port': 443,
            'RequestInterval': 30,
            'ResourcePath': '/_dns',
            'Type': 'HTTPS',
        }

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': [],
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'create_health_check',
            {
                'HealthCheck': {
                    'Id': '42',
                    'CallerReference': self.caller_ref,
                    'HealthCheckConfig': health_check_config,
                    'HealthCheckVersion': 1,
                },
                'Location': 'http://url',
            },
            {'CallerReference': ANY, 'HealthCheckConfig': health_check_config},
        )
        stubber.add_response('change_tags_for_resource', {})
        stubber.add_response('change_tags_for_resource', {})

        record = Record.new(
            self.expected,
            'a',
            {
                'ttl': 61,
                'type': 'A',
                'value': '2.2.3.4',
                'geo': {'AF': ['1.2.3.4']},
                'octodns': {
                    'healthcheck': {},
                    'route53': {
                        'healthcheck': {
                            'measure_latency': False,
                            'request_interval': 30,
                            'failure_threshold': 2,
                        }
                    },
                },
            },
        )

        value = record.geo['AF'].values[0]
        id = provider.get_health_check_id(record, value, 'obey', True)
        ml = provider.health_checks[id]['HealthCheckConfig']['MeasureLatency']
        ri = provider.health_checks[id]['HealthCheckConfig']['RequestInterval']
        self.assertFalse(ml)
        self.assertEqual(30, ri)

    def test_health_check_gc(self):
        provider, stubber = self._get_stubbed_provider()

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'A',
                'values': ['2.2.3.4', '3.2.3.4'],
                'geo': {
                    'AF': ['4.2.3.4'],
                    'NA-US': ['5.2.3.4', '6.2.3.4'],
                    # removed one geo
                },
            },
        )

        # gc no longer in_use records (directly)
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': '44'})
        provider._gc_health_checks(
            record, [DummyR53Record('42'), DummyR53Record('43')]
        )
        stubber.assert_no_pending_responses()

        # gc through _mod_Create
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': '44'})
        change = Create(record)
        provider._mod_Create(change, 'z43', [])
        stubber.assert_no_pending_responses()

        # gc through _mod_Update
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': '44'})
        # first record is ignored for our purposes, we have to pass something
        change = Update(record, record)
        provider._mod_Create(change, 'z43', [])
        stubber.assert_no_pending_responses()

        # gc through _mod_Delete, expect 3 to go away, can't check order
        # b/c it's not deterministic
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': ANY})
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': ANY})
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': ANY})
        change = Delete(record)
        provider._mod_Delete(change, 'z43', [])
        stubber.assert_no_pending_responses()

        # gc only AAAA, leave the A's alone
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': '45'})
        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'AAAA',
                'value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b',
            },
        )
        provider._gc_health_checks(record, [])
        stubber.assert_no_pending_responses()

    def test_legacy_health_check_gc(self):
        provider, stubber = self._get_stubbed_provider()

        old_caller_ref = '0000:A:3333'
        health_checks = [
            {
                'Id': '42',
                'CallerReference': self.caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '43',
                'CallerReference': old_caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
            {
                'Id': '44',
                'CallerReference': old_caller_ref,
                'HealthCheckConfig': {
                    'Disabled': False,
                    'EnableSNI': True,
                    'Inverted': False,
                    'Type': 'HTTPS',
                    'FullyQualifiedDomainName': 'other.unit.tests',
                    'IPAddress': '4.2.3.4',
                    'ResourcePath': '/_dns',
                    'Type': 'HTTPS',
                    'Port': 443,
                    'MeasureLatency': True,
                    'RequestInterval': 10,
                    'FailureThreshold': 6,
                },
                'HealthCheckVersion': 2,
            },
        ]

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        # No changes to the record itself
        record = Record.new(
            self.expected,
            '',
            {
                'ttl': 61,
                'type': 'A',
                'values': ['2.2.3.4', '3.2.3.4'],
                'geo': {
                    'AF': ['4.2.3.4'],
                    'NA-US': ['5.2.3.4', '6.2.3.4'],
                    'NA-US-CA': ['7.2.3.4'],
                },
            },
        )

        # Expect to delete the legacy hc for our record, but not touch the new
        # one or the other legacy record
        stubber.add_response('delete_health_check', {}, {'HealthCheckId': '43'})

        provider._gc_health_checks(record, [DummyR53Record('42')])

    def test_no_extra_changes(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # empty is empty
        desired = Zone('unit.tests.', [])
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

        # single record w/o geo is empty
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired, 'a', {'ttl': 30, 'type': 'A', 'value': '1.2.3.4'}
        )
        desired.add_record(record)
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

        # short-circuit for unknown zone
        other = Zone('other.tests.', [])
        extra = provider._extra_changes(desired=other, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

    def test_no_changes_with_get_zones_by_name(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        list_hosted_zones_by_name_resp_1 = {
            'HostedZones': [
                {
                    'Id': 'z42',
                    'Name': 'unit.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': 'unit.tests.',
            'HostedZoneId': 'z42',
            'IsTruncated': False,
            'MaxItems': 'string',
        }

        list_hosted_zones_by_name_resp_2 = {
            'HostedZones': [
                {
                    'Id': 'z43',
                    'Name': 'unit2.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': 'unit2.tests.',
            'HostedZoneId': 'z43',
            'IsTruncated': False,
            'MaxItems': 'string',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp_1,
            {'DNSName': 'unit.tests.', 'MaxItems': '1'},
        )

        # empty is empty
        desired = Zone('unit.tests.', [])
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp_2,
            {'DNSName': 'unit2.tests.', 'MaxItems': '1'},
        )

        # empty is empty
        desired = Zone('unit2.tests.', [])
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

    def test_zone_not_found_get_zones_by_name(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        list_hosted_zones_by_name_resp = {
            'HostedZones': [
                {
                    'Id': 'z43',
                    'Name': 'bad.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': 'unit.tests.',
            'HostedZoneId': 'z42',
            'IsTruncated': False,
            'MaxItems': 'string',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp,
            {'DNSName': 'unit.tests.', 'MaxItems': '1'},
        )

        # empty is empty
        desired = Zone('unit.tests.', [])
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual([], extra)
        stubber.assert_no_pending_responses()

    def test_plan_apply_with_get_zones_by_name_zone_not_exists(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        # this is an empty response
        # zone name not found
        list_hosted_zones_by_name_resp = {
            'HostedZones': [],
            'DNSName': 'unit.tests.',
            'HostedZoneId': 'z42',
            'IsTruncated': False,
            'MaxItems': 'string',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp,
            {'DNSName': 'unit.tests.', 'MaxItems': '1'},
        )

        plan = provider.plan(self.expected)
        self.assertEqual(12, len(plan.changes))

        create_hosted_zone_resp = {
            'HostedZone': {
                'Name': 'unit.tests.',
                'Id': 'z42',
                'CallerReference': 'abc',
            },
            'ChangeInfo': {
                'Id': 'a12',
                'Status': 'PENDING',
                'SubmittedAt': '2017-01-29T01:02:03Z',
                'Comment': 'hrm',
            },
            'DelegationSet': {
                'Id': 'b23',
                'CallerReference': 'blip',
                'NameServers': ['n12.unit.tests.'],
            },
            'Location': 'us-east-1',
        }
        stubber.add_response(
            'create_hosted_zone',
            create_hosted_zone_resp,
            {'Name': 'unit.tests.', 'CallerReference': ANY},
        )

        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        self.assertEqual(12, provider.apply(plan))
        stubber.assert_no_pending_responses()

    def test_plan_apply_with_get_zones_by_name_zone_exists(self):
        (
            provider,
            stubber,
        ) = self._get_stubbed_get_zones_by_name_enabled_provider()

        list_hosted_zones_by_name_resp = {
            'HostedZones': [
                {
                    'Id': 'z42',
                    'Name': 'unit.tests.',
                    'CallerReference': 'abc',
                    'Config': {'Comment': 'string', 'PrivateZone': False},
                    'ResourceRecordSetCount': 123,
                }
            ],
            'DNSName': 'unit.tests.',
            'HostedZoneId': 'z42',
            'IsTruncated': False,
            'MaxItems': 'string',
        }

        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }

        stubber.add_response(
            'list_hosted_zones_by_name',
            list_hosted_zones_by_name_resp,
            {'DNSName': 'unit.tests.', 'MaxItems': '1'},
        )

        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        plan = provider.plan(self.expected)
        self.assertEqual(13, len(plan.changes))

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        self.assertEqual(13, provider.apply(plan))
        stubber.assert_no_pending_responses()

    def test_extra_change_no_health_check(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo and no health check returns change
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'geo': {'NA': ['2.2.3.4']},
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

    def test_extra_change_has_wrong_health_check(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo and no health check returns change
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'geo': {'NA': ['2.2.3.4']},
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '42',
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': [
                    {
                        'Id': '42',
                        'CallerReference': 'foo',
                        'HealthCheckConfig': {
                            'Disabled': False,
                            'EnableSNI': True,
                            'Inverted': False,
                            'Type': 'HTTPS',
                            'FullyQualifiedDomainName': 'unit.tests',
                            'IPAddress': '2.2.3.4',
                            'ResourcePath': '/_dns',
                            'Type': 'HTTPS',
                            'Port': 443,
                            'MeasureLatency': True,
                            'RequestInterval': 10,
                            'FailureThreshold': 6,
                        },
                        'HealthCheckVersion': 2,
                    }
                ],
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

        for change in (Create(record), Update(record, record), Delete(record)):
            extra = provider._extra_changes(desired=desired, changes=[change])
            self.assertEqual(0, len(extra))
            stubber.assert_no_pending_responses()

    def test_extra_change_has_health_check(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo and no health check returns change
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'geo': {'NA': ['2.2.3.4']},
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    # other name
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                },
                {
                    # matching name, other type
                    'Name': 'a.unit.tests.',
                    'Type': 'AAAA',
                    'ResourceRecords': [
                        {'Value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b'}
                    ],
                    'TTL': 61,
                },
                {
                    # default geo
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                },
                {
                    # match w/correct geo
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'ContinentCode': 'NA'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '42',
                },
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': [
                    {
                        'Id': '42',
                        'CallerReference': self.caller_ref,
                        'HealthCheckConfig': {
                            'Disabled': False,
                            'EnableSNI': True,
                            'Inverted': False,
                            'Type': 'HTTPS',
                            'FullyQualifiedDomainName': 'a.unit.tests',
                            'IPAddress': '2.2.3.4',
                            'ResourcePath': '/_dns',
                            'Type': 'HTTPS',
                            'Port': 443,
                            'MeasureLatency': True,
                            'RequestInterval': 10,
                            'FailureThreshold': 6,
                        },
                        'HealthCheckVersion': 2,
                    }
                ],
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(0, len(extra))
        stubber.assert_no_pending_responses()

        # change b/c of healthcheck path
        record._octodns['healthcheck'] = {'path': '/_ready'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

    def test_extra_change_dynamic_has_health_check(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo and no health check returns change
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {'one': {'values': [{'value': '2.2.3.4'}]}},
                    'rules': [{'pool': 'one'}],
                },
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    # Not dynamic value and other name
                    'Name': 'unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                    # All the non-matches have a different Id so we'll fail if they
                    # match
                    'HealthCheckId': '33',
                },
                {
                    # Not dynamic value, matching name, other type
                    'Name': 'a.unit.tests.',
                    'Type': 'AAAA',
                    'ResourceRecords': [
                        {'Value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b'}
                    ],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # default value pool
                    'Name': '_octodns-default-value.a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # different record
                    'Name': '_octodns-two-value.other.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # same everything, but different type
                    'Name': '_octodns-one-value.a.unit.tests.',
                    'Type': 'AAAA',
                    'ResourceRecords': [
                        {'Value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b'}
                    ],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # same everything, sub
                    'Name': '_octodns-one-value.sub.a.unit.tests.',
                    'Type': 'A',
                    'ResourceRecords': [{'Value': '1.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # match
                    'Name': '_octodns-one-value.a.unit.tests.',
                    'Type': 'A',
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                    'HealthCheckId': '42',
                },
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )
        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': [
                    {
                        'Id': '42',
                        'CallerReference': self.caller_ref,
                        'HealthCheckConfig': {
                            'Disabled': False,
                            'EnableSNI': True,
                            'Inverted': False,
                            'Type': 'HTTPS',
                            'FullyQualifiedDomainName': 'a.unit.tests',
                            'IPAddress': '2.2.3.4',
                            'ResourcePath': '/_dns',
                            'Type': 'HTTPS',
                            'Port': 443,
                            'MeasureLatency': True,
                            'RequestInterval': 10,
                            'FailureThreshold': 6,
                        },
                        'HealthCheckVersion': 2,
                    }
                ],
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(0, len(extra))
        stubber.assert_no_pending_responses()

        # change b/c of healthcheck path
        record._octodns['healthcheck'] = {'path': '/_ready'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

        # change b/c of healthcheck host
        record._octodns['healthcheck'] = {'host': 'foo.bar.io'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

    def test_extra_change_dyamic_status_up(self):
        provider, stubber = self._get_stubbed_provider()

        zone = Zone('unit.tests.', [])
        record = Record.new(
            zone,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.1.1.1',
                'dynamic': {
                    'pools': {
                        'one': {
                            'values': [{'status': 'up', 'value': '1.2.3.4'}]
                        }
                    },
                    'rules': [{'pool': 'one'}],
                },
            },
        )

        # status up and no health check so we're good
        rrset = {'ResourceRecords': [{'Value': '1.2.3.4'}]}
        statuses = {'1.2.3.4': 'up'}
        self.assertFalse(
            provider._extra_changes_update_needed(record, rrset, statuses)
        )

        # status up and has a health check so update needed
        rrset = {
            'ResourceRecords': [{'Value': '1.2.3.4'}],
            'HealthCheckId': 'foo',
        }
        statuses = {'1.2.3.4': 'up'}
        self.assertTrue(
            provider._extra_changes_update_needed(record, rrset, statuses)
        )

    def test_extra_change_dynamic_latency(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo latency
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'a',
            {
                'ttl': 30,
                'type': 'A',
                'value': '1.2.3.4',
                'dynamic': {
                    'pools': {
                        'ap-southeast-1': {
                            'fallback': 'us-east-1',
                            'values': [
                                {
                                    'weight': 2,
                                    'value': '1.4.1.1',
                                    'status': 'obey',
                                },
                                {
                                    'weight': 2,
                                    'value': '1.4.1.2',
                                    'status': 'up',
                                },
                            ],
                        },
                        'eu-central-1': {
                            'fallback': 'us-east-1',
                            'values': [
                                {
                                    'weight': 1,
                                    'value': '1.3.1.1',
                                    'status': 'down',
                                },
                                {
                                    'weight': 1,
                                    'value': '1.3.1.2',
                                    'status': 'up',
                                },
                            ],
                        },
                        'us-east-1': {
                            'values': [
                                {
                                    'weight': 1,
                                    'value': '1.5.1.1',
                                    'status': 'up',
                                },
                                {
                                    'weight': 1,
                                    'value': '1.5.1.2',
                                    'status': 'up',
                                },
                            ]
                        },
                    },
                    'rules': [
                        {'geos': ['AS-JP', 'AS-SG'], 'pool': 'ap-southeast-1'},
                        {'geos': ['EU', 'NA-US-VI'], 'pool': 'eu-central-1'},
                        {'pool': 'us-east-1'},
                    ],
                },
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    'Name': 'a.unit.tests.',
                    'Type': 'A',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': '2.2.3.4'}],
                    'TTL': 61,
                }
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(0, len(extra))
        stubber.assert_no_pending_responses()

        record._octodns['route53'] = {'mode': 'latency'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

    def test_extra_change_dynamic_has_health_check_cname(self):
        provider, stubber = self._get_stubbed_provider()

        list_hosted_zones_resp = {
            'HostedZones': [
                {'Name': 'unit.tests.', 'Id': 'z42', 'CallerReference': 'abc'}
            ],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        # record with geo and no health check returns change
        desired = Zone('unit.tests.', [])
        record = Record.new(
            desired,
            'cname',
            {
                'ttl': 30,
                'type': 'CNAME',
                'value': 'cname.unit.tests.',
                'dynamic': {
                    'pools': {
                        'one': {'values': [{'value': 'one.cname.unit.tests.'}]}
                    },
                    'rules': [{'pool': 'one'}],
                },
            },
        )
        desired.add_record(record)
        list_resource_record_sets_resp = {
            'ResourceRecordSets': [
                {
                    # Not dynamic value and other name
                    'Name': 'unit.tests.',
                    'Type': 'CNAME',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': 'cname.unit.tests.'}],
                    'TTL': 61,
                    # All the non-matches have a different Id so we'll fail if they
                    # match
                    'HealthCheckId': '33',
                },
                {
                    # Not dynamic value, matching name, other type
                    'Name': 'cname.unit.tests.',
                    'Type': 'AAAA',
                    'ResourceRecords': [
                        {'Value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b'}
                    ],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # default value pool
                    'Name': '_octodns-default-value.cname.unit.tests.',
                    'Type': 'CNAME',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': 'cname.unit.tests.'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # different record
                    'Name': '_octodns-two-value.other.unit.tests.',
                    'Type': 'CNAME',
                    'GeoLocation': {'CountryCode': '*'},
                    'ResourceRecords': [{'Value': 'cname.unit.tests.'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # same everything, but different type
                    'Name': '_octodns-one-value.cname.unit.tests.',
                    'Type': 'AAAA',
                    'ResourceRecords': [
                        {'Value': '2001:0db8:3c4d:0015:0000:0000:1a2f:1a4b'}
                    ],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # same everything, sub
                    'Name': '_octodns-one-value.sub.cname.unit.tests.',
                    'Type': 'CNAME',
                    'ResourceRecords': [{'Value': 'cname.unit.tests.'}],
                    'TTL': 61,
                    'HealthCheckId': '33',
                },
                {
                    # match
                    'Name': '_octodns-one-value.cname.unit.tests.',
                    'Type': 'CNAME',
                    'ResourceRecords': [{'Value': 'one.cname.unit.tests.'}],
                    'TTL': 61,
                    'HealthCheckId': '42',
                },
            ],
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response(
            'list_resource_record_sets',
            list_resource_record_sets_resp,
            {'HostedZoneId': 'z42'},
        )

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': [
                    {
                        'Id': '42',
                        'CallerReference': self.caller_ref,
                        'HealthCheckConfig': {
                            'Disabled': False,
                            'EnableSNI': True,
                            'Inverted': False,
                            'Type': 'HTTPS',
                            'FullyQualifiedDomainName': 'one.cname.unit.tests.',
                            'ResourcePath': '/_dns',
                            'Type': 'HTTPS',
                            'Port': 443,
                            'MeasureLatency': True,
                            'RequestInterval': 10,
                            'FailureThreshold': 6,
                        },
                        'HealthCheckVersion': 2,
                    }
                ],
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(0, len(extra))
        stubber.assert_no_pending_responses()

        # change b/c of healthcheck path
        record._octodns['healthcheck'] = {'path': '/_ready'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(1, len(extra))
        stubber.assert_no_pending_responses()

        # no change b/c healthcheck host ignored for dynamic cname
        record._octodns['healthcheck'] = {'host': 'foo.bar.io'}
        extra = provider._extra_changes(desired=desired, changes=[])
        self.assertEqual(0, len(extra))
        stubber.assert_no_pending_responses()

    def _get_test_plan(self, max_changes):
        provider = Route53Provider('test', 'abc', '123', max_changes)

        # Use the stubber
        stubber = Stubber(provider._conn)
        stubber.activate()

        got = Zone('unit.tests.', [])

        list_hosted_zones_resp = {
            'HostedZones': [],
            'Marker': 'm',
            'IsTruncated': False,
            'MaxItems': '100',
        }
        stubber.add_response('list_hosted_zones', list_hosted_zones_resp, {})

        create_hosted_zone_resp = {
            'HostedZone': {
                'Name': 'unit.tests.',
                'Id': 'z42',
                'CallerReference': 'abc',
            },
            'ChangeInfo': {
                'Id': 'a12',
                'Status': 'PENDING',
                'SubmittedAt': '2017-01-29T01:02:03Z',
                'Comment': 'hrm',
            },
            'DelegationSet': {
                'Id': 'b23',
                'CallerReference': 'blip',
                'NameServers': ['n12.unit.tests.'],
            },
            'Location': 'us-east-1',
        }
        stubber.add_response(
            'create_hosted_zone',
            create_hosted_zone_resp,
            {'Name': got.name, 'CallerReference': ANY},
        )

        stubber.add_response(
            'list_health_checks',
            {
                'HealthChecks': self.health_checks,
                'IsTruncated': False,
                'MaxItems': '100',
                'Marker': '',
            },
        )

        stubber.add_response(
            'change_resource_record_sets',
            {
                'ChangeInfo': {
                    'Id': 'id',
                    'Status': 'PENDING',
                    'SubmittedAt': '2017-01-29T01:02:03Z',
                }
            },
            {'HostedZoneId': 'z42', 'ChangeBatch': ANY},
        )

        plan = provider.plan(self.expected)

        # filtering out the root NS here b/c all of these tests predated
        # support for it and accounting for it will require significant
        # rejiggering of the tests (it's not important to what's being tested)
        plan.changes = [
            c for c in plan.changes if c.new._type != 'NS' or c.new.name != ''
        ]

        return provider, plan

    # _get_test_plan() returns a plan with 11 modifications, 17 RRs

    @patch('octodns_route53.Route53Provider._load_records')
    @patch('octodns_route53.Route53Provider._really_apply')
    def test_apply_1(self, really_apply_mock, _):
        # 18 RRs with max of 19 should only get applied in one call
        provider, plan = self._get_test_plan(19)
        provider.apply(plan)
        really_apply_mock.assert_called_once()

    @patch('octodns_route53.Route53Provider._load_records')
    @patch('octodns_route53.Route53Provider._really_apply')
    def test_apply_2(self, really_apply_mock, _):
        # 18 RRs with max of 17 should only get applied in two calls
        provider, plan = self._get_test_plan(18)
        provider.apply(plan)
        self.assertEqual(2, really_apply_mock.call_count)

    @patch('octodns_route53.Route53Provider._load_records')
    @patch('octodns_route53.Route53Provider._really_apply')
    def test_apply_3(self, really_apply_mock, _):
        # with a max of seven modifications, three calls
        provider, plan = self._get_test_plan(7)
        provider.apply(plan)
        self.assertEqual(3, really_apply_mock.call_count)

    @patch('octodns_route53.Route53Provider._load_records')
    @patch('octodns_route53.Route53Provider._really_apply')
    def test_apply_4(self, really_apply_mock, _):
        # with a max of 11 modifications, two calls
        provider, plan = self._get_test_plan(11)
        provider.apply(plan)
        self.assertEqual(2, really_apply_mock.call_count)

    @patch('octodns_route53.Route53Provider._load_records')
    @patch('octodns_route53.Route53Provider._really_apply')
    def test_apply_bad(self, really_apply_mock, _):
        # with a max of 1 modifications, fail
        provider, plan = self._get_test_plan(1)
        with self.assertRaises(Exception) as ctx:
            provider.apply(plan)
        self.assertTrue('modifications' in str(ctx.exception))

    def test_semicolon_fixup(self):
        provider = Route53Provider('test', 'abc', '123')

        self.assertEqual(
            {
                'type': 'TXT',
                'ttl': 30,
                'values': ['abcd\\; ef\\;g', 'hij\\; klm\\;n'],
            },
            provider._data_for_quoted(
                {
                    'ResourceRecords': [
                        {'Value': '"abcd; ef;g"'},
                        {'Value': '"hij\\; klm\\;n"'},
                    ],
                    'TTL': 30,
                    'Type': 'TXT',
                }
            ),
        )

    def test_client_max_attempts(self):
        provider = Route53Provider('test', 'abc', '123', client_max_attempts=42)
        # NOTE: this will break if boto ever changes the impl details...
        self.assertEqual(
            {'mode': 'legacy', 'total_max_attempts': 43},
            provider._conn._client_config.retries,
        )

    def test_data_for_dynamic(self):
        provider = Route53Provider('test', 'abc', '123')
        provider._health_checks = dynamic_health_checks

        data = provider._data_for_dynamic('', 'A', dynamic_rrsets)
        self.assertEqual(dynamic_record_data, data)

    def test_data_for_dynamic_latency(self):
        provider = Route53Provider('test', 'abc', '123')
        provider._health_checks = dynamic_health_checks

        data = provider._data_for_dynamic('', 'A', dynamic_rrsets_latency)
        self.assertEqual(dynamic_record_latency_data, data)

    def test_geo_latency(self):
        self.assertEqual(
            {
                'continent_code': 'NA',
                'country_code': None,
                'province_code': None,
                'region': 'us-east-1',
            },
            GeoLatency.parse('NA'),
        )
        self.assertEqual(
            {
                'continent_code': 'NA',
                'country_code': 'US',
                'province_code': None,
                'region': 'us-east-1',
            },
            GeoLatency.parse('NA-US'),
        )
        self.assertEqual(
            {
                'continent_code': 'EU',
                'country_code': 'AD',
                'province_code': None,
                'region': None,
            },
            GeoLatency.parse('EU-AD'),
        )
        self.assertEqual(
            {
                'continent_code': 'NA',
                'country_code': 'US',
                'province_code': 'CA',
                'region': 'us-west-1',
            },
            GeoLatency.parse('NA-US-CA'),
        )
        self.assertEqual(
            {
                'continent_code': 'NA',
                'country_code': 'US',
                'province_code': 'AK',
                'region': None,
            },
            GeoLatency.parse('NA-US-AK'),
        )
        self.assertEqual(
            {
                'continent_code': 'OC',
                'country_code': None,
                'province_code': None,
                'region': None,
            },
            GeoLatency.parse('OC'),
        )
        self.assertEqual(
            {
                'continent_code': '',
                'country_code': None,
                'province_code': None,
                'region': None,
            },
            GeoLatency.parse(''),
        )

    @patch('octodns_route53.Route53Provider._get_zone_id')
    @patch('octodns_route53.Route53Provider._load_records')
    def test_dynamic_populate(self, load_records_mock, get_zone_id_mock):
        provider = Route53Provider('test', 'abc', '123')
        provider._health_checks = {}

        get_zone_id_mock.side_effect = ['z44']
        load_records_mock.side_effect = [dynamic_rrsets]

        got = Zone('unit.tests.', [])
        provider.populate(got)

        self.assertEqual(1, len(got.records))
        record = list(got.records)[0]
        self.assertEqual('', record.name)
        self.assertEqual('A', record._type)
        self.assertEqual(['1.1.2.1', '1.1.2.2'], record.values)
        self.assertTrue(record.dynamic)

        self.assertEqual(
            {
                'ap-southeast-1': {
                    'fallback': 'us-east-1',
                    'values': [
                        {'weight': 2, 'value': '1.4.1.1', 'status': 'up'},
                        {'weight': 2, 'value': '1.4.1.2', 'status': 'up'},
                    ],
                },
                'eu-central-1': {
                    'fallback': 'us-east-1',
                    'values': [
                        {'weight': 1, 'value': '1.3.1.1', 'status': 'up'},
                        {'weight': 1, 'value': '1.3.1.2', 'status': 'up'},
                    ],
                },
                'us-east-1': {
                    'fallback': None,
                    'values': [
                        {'weight': 1, 'value': '1.5.1.1', 'status': 'up'},
                        {'weight': 1, 'value': '1.5.1.2', 'status': 'up'},
                    ],
                },
            },
            {k: v.data for k, v in record.dynamic.pools.items()},
        )

        self.assertEqual(
            [
                {'geos': ['AS-CN', 'AS-JP'], 'pool': 'ap-southeast-1'},
                {'geos': ['EU', 'NA-US-FL'], 'pool': 'eu-central-1'},
                {'pool': 'us-east-1'},
            ],
            [r.data for r in record.dynamic.rules],
        )


class DummyProvider(object):
    def get_health_check_id(self, *args, **kwargs):
        return None


class TestRoute53Records(TestCase):
    existing = Zone('unit.tests.', [])
    record_a = Record.new(
        existing,
        '',
        {
            'geo': {
                'NA-US': ['2.2.2.2', '3.3.3.3'],
                'OC': ['4.4.4.4', '5.5.5.5'],
            },
            'ttl': 99,
            'type': 'A',
            'values': ['9.9.9.9'],
        },
    )

    def test_value_fors(self):
        route53_record = _Route53Record(None, self.record_a, False)

        for value in (None, '', 'foo', 'bar', '1.2.3.4'):
            converted = route53_record._value_convert_value(
                value, self.record_a
            )
            self.assertEqual(value, converted)

        record_txt = Record.new(
            self.existing,
            'txt',
            {'ttl': 98, 'type': 'TXT', 'value': 'Not Important'},
        )

        # We don't really have to test the details fo chunked_value as that's
        # tested elsewhere, we just need to make sure that it's plumbed up and
        # working
        self.assertEqual(
            '"Not Important"',
            route53_record._value_convert_quoted(
                record_txt.values[0], record_txt
            ),
        )

    def test_route53_record(self):
        a = _Route53Record(None, self.record_a, False)
        self.assertEqual(a, a)
        b = _Route53Record(
            None,
            Record.new(
                self.existing,
                '',
                {'ttl': 32, 'type': 'A', 'values': ['8.8.8.8', '1.1.1.1']},
            ),
            False,
        )
        self.assertEqual(b, b)
        c = _Route53Record(
            None,
            Record.new(
                self.existing,
                'other',
                {'ttl': 99, 'type': 'A', 'values': ['9.9.9.9']},
            ),
            False,
        )
        self.assertEqual(c, c)
        d = _Route53Record(
            None,
            Record.new(
                self.existing,
                '',
                {
                    'ttl': 42,
                    'type': 'MX',
                    'value': {'preference': 10, 'exchange': 'foo.bar.'},
                },
            ),
            False,
        )
        self.assertEqual(d, d)

        # Same fqdn & type is same record
        self.assertEqual(a, b)
        # Same name & different type is not the same
        self.assertNotEqual(a, d)
        # Different name & same type is not the same
        self.assertNotEqual(a, c)

        # Same everything, different class is not the same
        e = _Route53GeoDefault(None, self.record_a, False)
        self.assertNotEqual(a, e)

        provider = DummyProvider()
        f = _Route53GeoRecord(
            provider, self.record_a, 'NA-US', self.record_a.geo['NA-US'], False
        )
        self.assertEqual(f, f)
        g = _Route53GeoRecord(
            provider, self.record_a, 'OC', self.record_a.geo['OC'], False
        )
        self.assertEqual(g, g)

        # Geo and non-geo are not the same, using Geo as primary to get it's
        # __cmp__
        self.assertNotEqual(f, a)
        # Same everything, different geo's is not the same
        self.assertNotEqual(f, g)

        # Make sure it doesn't blow up
        a.__repr__()
        e.__repr__()
        f.__repr__()

    def test_route53_record_ordering(self):
        # Matches
        a = _Route53Record(None, self.record_a, False)
        b = _Route53Record(None, self.record_a, False)
        self.assertTrue(a == b)
        self.assertFalse(a != b)
        self.assertFalse(a < b)
        self.assertTrue(a <= b)
        self.assertFalse(a > b)
        self.assertTrue(a >= b)

        # Change the fqdn is greater
        fqdn = _Route53Record(None, self.record_a, False, fqdn_override='other')
        self.assertFalse(a == fqdn)
        self.assertTrue(a != fqdn)
        self.assertFalse(a < fqdn)
        self.assertFalse(a <= fqdn)
        self.assertTrue(a > fqdn)
        self.assertTrue(a >= fqdn)

        provider = DummyProvider()
        geo_a = _Route53GeoRecord(
            provider, self.record_a, 'NA-US', self.record_a.geo['NA-US'], False
        )
        geo_b = _Route53GeoRecord(
            provider, self.record_a, 'NA-US', self.record_a.geo['NA-US'], False
        )
        self.assertTrue(geo_a == geo_b)
        self.assertFalse(geo_a != geo_b)
        self.assertFalse(geo_a < geo_b)
        self.assertTrue(geo_a <= geo_b)
        self.assertFalse(geo_a > geo_b)
        self.assertTrue(geo_a >= geo_b)

        # Other base
        geo_fqdn = _Route53GeoRecord(
            provider, self.record_a, 'NA-US', self.record_a.geo['NA-US'], False
        )
        geo_fqdn.fqdn = 'other'
        self.assertFalse(geo_a == geo_fqdn)
        self.assertTrue(geo_a != geo_fqdn)
        self.assertFalse(geo_a < geo_fqdn)
        self.assertFalse(geo_a <= geo_fqdn)
        self.assertTrue(geo_a > geo_fqdn)
        self.assertTrue(geo_a >= geo_fqdn)

        # Other class
        self.assertFalse(a == geo_a)
        self.assertTrue(a != geo_a)
        self.assertFalse(a < geo_a)
        self.assertFalse(a <= geo_a)
        self.assertTrue(a > geo_a)
        self.assertTrue(a >= geo_a)

    def test_dynamic_value_delete(self):
        provider = DummyProvider()
        geo = _Route53DynamicValue(
            provider, self.record_a, 'iad', '2.2.2.2', 1, 'obey', 0, False
        )

        rrset = {
            'HealthCheckId': 'x12346z',
            'Name': '_octodns-iad-value.unit.tests.',
            'ResourceRecords': [{'Value': '2.2.2.2'}],
            'SetIdentifier': 'iad-000',
            'TTL': 99,
            'Type': 'A',
            'Weight': 1,
        }

        candidates = [
            # Empty, will test no SetIdentifier
            {},
            # Non-matching
            {'SetIdentifier': 'not-a-match'},
            # Same set-id, different name
            {'Name': 'not-a-match', 'SetIdentifier': 'x12346z'},
            rrset,
        ]

        # Provide a matching rrset so that we'll just use it for the delete
        # rathr than building up an almost identical one, note the way we'll
        # know that we got the one we passed in is that it'll have a
        # HealthCheckId and one that was created wouldn't since DummyProvider
        # stubs out the lookup for them
        mod = geo.mod('DELETE', candidates)
        self.assertEqual('x12346z', mod['ResourceRecordSet']['HealthCheckId'])

        # If we don't provide the candidate rrsets we get back exactly what we
        # put in minus the healthcheck
        del rrset['HealthCheckId']
        mod = geo.mod('DELETE', [])
        self.assertEqual(rrset, mod['ResourceRecordSet'])

    def test_geo_delete(self):
        provider = DummyProvider()
        geo = _Route53GeoRecord(
            provider, self.record_a, 'NA-US', self.record_a.geo['NA-US'], False
        )

        rrset = {
            'GeoLocation': {'CountryCode': 'US'},
            'HealthCheckId': 'x12346z',
            'Name': 'unit.tests.',
            'ResourceRecords': [{'Value': '2.2.2.2'}, {'Value': '3.3.3.3'}],
            'SetIdentifier': 'NA-US',
            'TTL': 99,
            'Type': 'A',
        }

        candidates = [
            # Empty, will test no SetIdentifier
            {},
            {'SetIdentifier': 'not-a-match'},
            # Same set-id, different name
            {'Name': 'not-a-match', 'SetIdentifier': 'x12346z'},
            rrset,
        ]

        # Provide a matching rrset so that we'll just use it for the delete
        # rathr than building up an almost identical one, note the way we'll
        # know that we got the one we passed in is that it'll have a
        # HealthCheckId and one that was created wouldn't since DummyProvider
        # stubs out the lookup for them
        mod = geo.mod('DELETE', candidates)
        self.assertEqual('x12346z', mod['ResourceRecordSet']['HealthCheckId'])

        # If we don't provide the candidate rrsets we get back exactly what we
        # put in minus the healthcheck
        del rrset['HealthCheckId']
        mod = geo.mod('DELETE', [])
        self.assertEqual(rrset, mod['ResourceRecordSet'])

    def test_new_dynamic(self):
        provider = Route53Provider('test', 'abc', '123')

        # Just so boto won't try and make any calls
        stubber = Stubber(provider._conn)
        stubber.activate()

        # We'll assume we create all healthchecks here, this functionality is
        # thoroughly tested elsewhere
        provider._health_checks = {}
        # When asked for a healthcheck return dummy info
        provider.get_health_check_id = lambda r, v, s, c: 'hc42'

        zone = Zone('unit.tests.', [])
        record = Record.new(zone, '', dynamic_record_data)

        # Convert a record into _Route53Records
        route53_records = _Route53Record.new(
            provider, record, 'z45', creating=True
        )
        self.assertEqual(18, len(route53_records))

        expected_mods = [r.mod('CREATE', []) for r in route53_records]
        # Sort so that we get a consistent order and don't rely on set ordering
        expected_mods.sort(key=_mod_keyer)

        # Convert the route53_records into mods
        self.assertEqual(
            [
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.4.1.1'}],
                        'SetIdentifier': 'ap-southeast-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 2,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.4.1.2'}],
                        'SetIdentifier': 'ap-southeast-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 2,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': '_octodns-default-pool.unit.tests.',
                        'ResourceRecords': [
                            {'Value': '1.1.2.1'},
                            {'Value': '1.1.2.2'},
                        ],
                        'TTL': 60,
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-eu-central-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.3.1.1'}],
                        'SetIdentifier': 'eu-central-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-eu-central-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.3.1.2'}],
                        'SetIdentifier': 'eu-central-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-us-east-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.5.1.1'}],
                        'SetIdentifier': 'us-east-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-us-east-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.5.1.2'}],
                        'SetIdentifier': 'us-east-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
                        'SetIdentifier': 'ap-southeast-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-eu-central-1-pool.unit.tests.',
                        'SetIdentifier': 'eu-central-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-us-east-1-pool.unit.tests.',
                        'SetIdentifier': 'us-east-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
                        'SetIdentifier': 'ap-southeast-1-Secondary-us-east-1',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-eu-central-1-pool.unit.tests.',
                        'SetIdentifier': 'eu-central-1-Secondary-us-east-1',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-default-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-us-east-1-pool.unit.tests.',
                        'SetIdentifier': 'us-east-1-Secondary-default',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {'CountryCode': 'CN'},
                        'Name': 'unit.tests.',
                        'SetIdentifier': '0-ap-southeast-1-AS-CN',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {'CountryCode': 'JP'},
                        'Name': 'unit.tests.',
                        'SetIdentifier': '0-ap-southeast-1-AS-JP',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {'ContinentCode': 'EU'},
                        'Name': 'unit.tests.',
                        'SetIdentifier': '1-eu-central-1-EU',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {
                            'CountryCode': 'US',
                            'SubdivisionCode': 'FL',
                        },
                        'Name': 'unit.tests.',
                        'SetIdentifier': '1-eu-central-1-NA-US-FL',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {'CountryCode': '*'},
                        'Name': 'unit.tests.',
                        'SetIdentifier': '2-us-east-1-None',
                        'Type': 'A',
                    },
                },
            ],
            expected_mods,
        )

        for route53_record in route53_records:
            # Smoke test stringification
            route53_record.__repr__()

        # check latency records creation
        record_latency = Record.new(zone, '', dynamic_record_latency_data)
        route53_latency_records = _Route53Record.new(
            provider, record_latency, 'z45', creating=True
        )
        self.assertEqual(18, len(route53_latency_records))

        expected_mods = [r.mod('CREATE', []) for r in route53_latency_records]
        # Sort so that we get a consistent order and don't rely on set ordering
        expected_mods.sort(key=_mod_keyer)

        # Convert the route53_latency_records into mods
        self.assertEqual(
            [
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.4.1.1'}],
                        'SetIdentifier': 'ap-southeast-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 2,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-ap-southeast-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.4.1.2'}],
                        'SetIdentifier': 'ap-southeast-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 2,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'Name': '_octodns-default-pool.unit.tests.',
                        'ResourceRecords': [
                            {'Value': '1.1.2.1'},
                            {'Value': '1.1.2.2'},
                        ],
                        'TTL': 60,
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-eu-central-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.3.1.1'}],
                        'SetIdentifier': 'eu-central-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-eu-central-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.3.1.2'}],
                        'SetIdentifier': 'eu-central-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-us-east-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.5.1.1'}],
                        'SetIdentifier': 'us-east-1-000',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'HealthCheckId': 'hc42',
                        'Name': '_octodns-us-east-1-value.unit.tests.',
                        'ResourceRecords': [{'Value': '1.5.1.2'}],
                        'SetIdentifier': 'us-east-1-001',
                        'TTL': 60,
                        'Type': 'A',
                        'Weight': 1,
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
                        'SetIdentifier': 'ap-southeast-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-eu-central-1-pool.unit.tests.',
                        'SetIdentifier': 'eu-central-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-value.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'PRIMARY',
                        'Name': '_octodns-us-east-1-pool.unit.tests.',
                        'SetIdentifier': 'us-east-1-Primary',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-ap-southeast-1-pool.unit.tests.',
                        'SetIdentifier': 'ap-southeast-1-Secondary-us-east-1',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-eu-central-1-pool.unit.tests.',
                        'SetIdentifier': 'eu-central-1-Secondary-us-east-1',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-default-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Failover': 'SECONDARY',
                        'Name': '_octodns-us-east-1-pool.unit.tests.',
                        'SetIdentifier': 'us-east-1-Secondary-default',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Region': 'ap-northeast-1',
                        'Name': 'unit.tests.',
                        'SetIdentifier': '0-ap-southeast-1-AS-JP',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-ap-southeast-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Region': 'ap-southeast-1',
                        'Name': 'unit.tests.',
                        'SetIdentifier': '0-ap-southeast-1-AS-SG',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Region': 'eu-west-1',
                        'Name': 'unit.tests.',
                        'SetIdentifier': '1-eu-central-1-EU',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-eu-central-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'Region': 'us-east-1',
                        'Name': 'unit.tests.',
                        'SetIdentifier': '1-eu-central-1-NA-US-VI',
                        'Type': 'A',
                    },
                },
                {
                    'Action': 'CREATE',
                    'ResourceRecordSet': {
                        'AliasTarget': {
                            'DNSName': '_octodns-us-east-1-pool.unit.tests.',
                            'EvaluateTargetHealth': True,
                            'HostedZoneId': 'z45',
                        },
                        'GeoLocation': {'CountryCode': '*'},
                        'Name': 'unit.tests.',
                        'SetIdentifier': '2-us-east-1-None',
                        'Type': 'A',
                    },
                },
            ],
            expected_mods,
        )

        for route53_latency_record in route53_latency_records:
            # Smoke test stringification
            route53_latency_record.__repr__()


class TestModKeyer(TestCase):
    def test_mod_keyer(self):
        # First "column" is the action priority for C/R/U

        # Deletes come first
        self.assertEqual(
            (0, 0, 'something'),
            _mod_keyer(
                {'Action': 'DELETE', 'ResourceRecordSet': {'Name': 'something'}}
            ),
        )

        # Creates come next
        self.assertEqual(
            (1, 0, 'another'),
            _mod_keyer(
                {'Action': 'CREATE', 'ResourceRecordSet': {'Name': 'another'}}
            ),
        )

        # Upserts are the same as creates
        self.assertEqual(
            (1, 0, 'last'),
            _mod_keyer(
                {'Action': 'UPSERT', 'ResourceRecordSet': {'Name': 'last'}}
            ),
        )

        # Second "column" value records tested above

        # AliasTarget primary second (to value)
        self.assertEqual(
            (0, -1, 'thing'),
            _mod_keyer(
                {
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'AliasTarget': 'some-target',
                        'Failover': 'PRIMARY',
                        'Name': 'thing',
                    },
                }
            ),
        )

        self.assertEqual(
            (1, 1, 'thing'),
            _mod_keyer(
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'AliasTarget': 'some-target',
                        'Failover': 'PRIMARY',
                        'Name': 'thing',
                    },
                }
            ),
        )

        # AliasTarget secondary third
        self.assertEqual(
            (0, -2, 'thing'),
            _mod_keyer(
                {
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'AliasTarget': 'some-target',
                        'Failover': 'SECONDARY',
                        'Name': 'thing',
                    },
                }
            ),
        )

        self.assertEqual(
            (1, 2, 'thing'),
            _mod_keyer(
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'AliasTarget': 'some-target',
                        'Failover': 'SECONDARY',
                        'Name': 'thing',
                    },
                }
            ),
        )

        # GeoLocation fourth
        self.assertEqual(
            (0, -3, 'some-id'),
            _mod_keyer(
                {
                    'Action': 'DELETE',
                    'ResourceRecordSet': {
                        'GeoLocation': 'some-target',
                        'SetIdentifier': 'some-id',
                    },
                }
            ),
        )

        self.assertEqual(
            (1, 3, 'some-id'),
            _mod_keyer(
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'GeoLocation': 'some-target',
                        'SetIdentifier': 'some-id',
                    },
                }
            ),
        )

        # The third "column" has already been tested above, Name/SetIdentifier


zone = Zone('unit.tests.', [])
records = {
    'root': Record.new(
        zone,
        '_deadbeef',
        {
            'ttl': 30,
            'type': 'CNAME',
            'value': '_0123456789abcdef.acm-validations.aws.',
        },
    ),
    'sub': Record.new(
        zone,
        '_deadbeef.sub',
        {
            'ttl': 30,
            'type': 'CNAME',
            'value': '_0123456789abcdef.acm-validations.aws.',
        },
    ),
    'not-cname': Record.new(
        zone, '_deadbeef.not-cname', {'ttl': 30, 'type': 'AAAA', 'value': '::1'}
    ),
    'not-acm': Record.new(
        zone,
        '_not-acm',
        {'ttl': 30, 'type': 'CNAME', 'value': 'localhost.unit.tests.'},
    ),
}


class TestAwsAcmMangingProcessor(TestCase):
    def test_process_zones(self):
        acm = AwsAcmMangingProcessor('acm')

        source = Zone(zone.name, [])
        # Unrelated stuff that should be untouched
        source.add_record(records['not-cname'])
        source.add_record(records['not-acm'])
        # ACM records that should be ignored
        source.add_record(records['root'])
        source.add_record(records['sub'])

        got = acm.process_source_zone(source)
        self.assertEqual(
            ['_deadbeef.not-cname', '_not-acm'],
            sorted([r.name for r in got.records]),
        )

        existing = Zone(zone.name, [])
        # Unrelated stuff that should be untouched
        existing.add_record(records['not-cname'])
        existing.add_record(records['not-acm'])
        # Stuff that will be ignored
        existing.add_record(records['root'])
        existing.add_record(records['sub'])

        got = acm.process_target_zone(existing)
        self.assertEqual(
            ['_deadbeef.not-cname', '_not-acm'],
            sorted([r.name for r in got.records]),
        )


class TestRoute53AliasRecord(TestCase):
    def test_basics(self):
        alias = Route53AliasRecord(
            zone,
            'alias',
            {
                'values': [
                    {'name': 'something', 'type': 'A'},
                    {'name': '', 'type': 'AAAA'},
                ],
                'ttl': 42,
            },
        )

        v0 = alias.values[0]
        v1 = alias.values[1]

        self.assertEqual(
            _Route53AliasValue(
                {
                    'evaluate-target-health': False,
                    'hosted-zone-id': None,
                    'name': 'something',
                    'type': 'A',
                }
            ),
            v0.data,
        )

        self.assertEqual(hash(v0), hash(v0))
        self.assertEqual(hash(v1), hash(v1))
        self.assertNotEqual(hash(v0), hash(v1))
        self.assertNotEqual(hash(v1), hash(v0))

        # make sure this doesn't blow up
        v0.__repr__()

        # No type
        self.assertEqual(
            ['missing type'],
            _Route53AliasValue.validate({}, Route53AliasRecord._type),
        )

        # service alias w/o hosted-zone-id
        self.assertEqual(
            ['service alias without hosted-zone-id'],
            _Route53AliasValue.validate(
                {
                    'name': 'foo.bar.amazonaws.com.cn',
                    'type': Route53AliasRecord._type,
                },
                Route53AliasRecord._type,
            ),
        )

        # local zone alias with hosted-zone-id
        self.assertEqual(
            ['hosted-zone-id on a non-service value'],
            _Route53AliasValue.validate(
                {
                    'name': 'www',
                    'hosted-zone-id': 'bad',
                    'type': Route53AliasRecord._type,
                },
                Route53AliasRecord._type,
            ),
        )

        # valid local zone
        self.assertEqual(
            [],
            _Route53AliasValue.validate(
                {'name': 'name', 'type': 'A'}, Route53AliasRecord._type
            ),
        )

        # valid service
        self.assertEqual(
            [],
            _Route53AliasValue.validate(
                {
                    'name': 'foo.bar.amazonaws.com.cn',
                    'hosted-zone-id': 'good',
                    'type': 'A',
                },
                Route53AliasRecord._type,
            ),
        )

        # valid service (cloudfront)
        self.assertEqual(
            [],
            _Route53AliasValue.validate(
                {
                    'name': 'foo.bar.cloudfront.net.',
                    'hosted-zone-id': 'good',
                    'type': 'A',
                },
                Route53AliasRecord._type,
            ),
        )

        # valid service (awsglobalaccelerator)
        self.assertEqual(
            [],
            _Route53AliasValue.validate(
                {
                    'name': 'foo.awsglobalaccelerator.com.',
                    'hosted-zone-id': 'good',
                    'type': 'A',
                },
                Route53AliasRecord._type,
            ),
        )

        # valid service (elasticbeanstalk)
        self.assertEqual(
            [],
            _Route53AliasValue.validate(
                {
                    'name': 'foo.bar.elasticbeanstalk.com.',
                    'hosted-zone-id': 'good',
                    'type': 'A',
                },
                Route53AliasRecord._type,
            ),
        )

    def test_route53_record_conversion(self):
        alias = Route53AliasRecord(
            zone,
            'alias',
            {
                'values': [
                    {'name': 'something', 'type': 'A'},
                    {'name': None, 'type': 'AAAA'},
                ],
                'ttl': 42,
            },
        )

        r53a0 = _Route53Alias(None, 'z42', alias, alias.values[0], True)
        self.assertEqual(
            {
                'Action': 'create',
                'ResourceRecordSet': {
                    'AliasTarget': {
                        'DNSName': 'something.unit.tests.',
                        'EvaluateTargetHealth': False,
                        'HostedZoneId': 'z42',
                    },
                    'Name': 'alias.unit.tests.',
                    'Type': 'A',
                },
            },
            r53a0.mod('create', None),
        )
        r53a1 = _Route53Alias(None, 'z42', alias, alias.values[1], True)
        self.assertEqual(
            {
                'Action': 'create',
                'ResourceRecordSet': {
                    'AliasTarget': {
                        'DNSName': 'unit.tests.',
                        'EvaluateTargetHealth': False,
                        'HostedZoneId': 'z42',
                    },
                    'Name': 'alias.unit.tests.',
                    'Type': 'AAAA',
                },
            },
            r53a1.mod('create', None),
        )

        self.assertEqual(hash(r53a0), hash(r53a0))
        self.assertEqual(hash(r53a1), hash(r53a1))
        self.assertNotEqual(hash(r53a0), hash(r53a1))
        self.assertNotEqual(hash(r53a1), hash(r53a0))

        # doesn't blow up
        r53a0.__repr__()
