#
#
#

from botocore.stub import Stubber
from unittest import TestCase

from octodns.zone import DuplicateRecordException, Zone

from octodns_route53 import Ec2Source


class TestEc2Source(TestCase):
    reservations = [
        {
            'Instances': [
                {
                    # all addresses
                    'InstanceId': 'a42',
                    'PrivateIpAddress': '10.0.0.14',
                    'PublicIpAddress': '44.200.16.238',
                    'Ipv6Address': 'fc00::1',
                    'Tags': [{'Key': 'Name', 'Value': 'all.unit.tests.'}],
                },
                {
                    # internal ipv4 only
                    'InstanceId': 'a43',
                    'PrivateIpAddress': '10.0.0.15',
                    'Tags': [
                        {
                            'Key': 'Name',
                            # no trailing dot
                            'Value': 'iv4.unit.tests',
                        },
                        {'Key': 'irrelevant', 'Value': 'dont matter'},
                    ],
                },
                {
                    # internal ipv4 only, another subnet
                    'InstanceId': 'a44',
                    'PrivateIpAddress': '10.0.1.99',
                    'Tags': [{'Key': 'Name', 'Value': 'iv4-other.unit.tests.'}],
                },
                {
                    # internal and public ipv4
                    'InstanceId': 'a45',
                    'PrivateIpAddress': '10.0.0.16',
                    'PublicIpAddress': '44.200.16.239',
                    'Tags': [
                        {
                            # no Name, does have matching prefix w/multiple fqdns
                            'Key': 'octodns',
                            'Value': 'v4.unit.tests./2nd.unit.tests',
                        }
                    ],
                },
                {
                    # ipv6 only
                    'InstanceId': 'a46',
                    'Ipv6Address': 'fc00::2',
                    'Tags': [
                        {
                            # both Name and matching prefix w/single fqdn
                            'Key': 'Name',
                            'Value': 'v6.unit.tests.',
                        },
                        {'Key': 'octodns-1', 'Value': '2nd-v6.unit.tests'},
                    ],
                },
            ]
        },
        {
            'Instances': [
                {
                    # non-matching name
                    'InstanceId': 'a47',
                    'PrivateIpAddress': '10.0.1.17',
                    'PublicIpAddress': '44.200.16.240',
                    'Ipv6Address': 'ab00::3',
                    'Tags': [{'Key': 'Name', 'Value': 'v6.other.zone.'}],
                },
                {
                    # missing name and fqdns
                    'InstanceId': 'a48',
                    'PrivateIpAddress': '10.0.0.18',
                    'PublicIpAddress': '44.200.16.241',
                    'Ipv6Address': 'fc00::4',
                },
            ]
        },
    ]

    def _get_stubbed_source(self, **kwargs):
        source = Ec2Source('test', 'us-east-1', 'abc', '123', **kwargs)

        # Use the stubber
        stubber = Stubber(source._conn)
        stubber.activate()

        return (source, stubber)

    def test_no_reservations(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])
        in_addr_arpa = Zone('0.0.10.in-addr.arpa.', [])
        ip6_arpa = Zone('0.0.0.0.fc00.in-addr.arpa.', [])

        # no reservations
        stubber.add_response('describe_instances', {'Reservations': []})
        source.populate(zone)
        self.assertEqual(0, len(zone.records))
        source.populate(in_addr_arpa)
        self.assertEqual(0, len(in_addr_arpa.records))
        source.populate(ip6_arpa)
        self.assertEqual(0, len(ip6_arpa.records))

    def test_no_instances(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])
        in_addr_arpa = Zone('0.0.10.in-addr.arpa.', [])
        ip6_arpa = Zone('0.0.0.0.fc00.ip6.arpa.', [])

        # no instances
        stubber.add_response(
            'describe_instances', {'Reservations': [{'Instances': []}]}
        )
        source.populate(zone)
        self.assertEqual(0, len(zone.records))
        source.populate(in_addr_arpa)
        self.assertEqual(0, len(in_addr_arpa.records))
        source.populate(ip6_arpa)
        self.assertEqual(0, len(ip6_arpa.records))

    def test_instances(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])
        in_addr_arpa = Zone('0.0.10.in-addr.arpa.', [])
        # not realistic, but tests everything just fine
        ip6_arpa = Zone('0.0.c.f.ip6.arpa.', [])

        stubber.add_response(
            'describe_instances', {'Reservations': self.reservations}
        )
        source.populate(zone)

        # expect 4 A and 2 AAAA
        records = {(r.name, r._type): r for r in zone.records}
        self.assertEqual(['10.0.0.14'], records[('all', 'A')].values)
        self.assertEqual(['10.0.0.15'], records[('iv4', 'A')].values)
        self.assertEqual(['10.0.1.99'], records[('iv4-other', 'A')].values)
        self.assertEqual(['10.0.0.16'], records[('v4', 'A')].values)
        self.assertEqual(['10.0.0.16'], records[('2nd', 'A')].values)
        self.assertEqual(['fc00::1'], records[('all', 'AAAA')].values)
        self.assertEqual(['fc00::2'], records[('v6', 'AAAA')].values)
        self.assertEqual(['fc00::2'], records[('2nd-v6', 'AAAA')].values)
        self.assertEqual(8, len(records))

        # expect 3 ipv4 PTRs
        source.populate(in_addr_arpa)
        records = {r.name: r for r in in_addr_arpa.records}
        self.assertEqual('all.unit.tests.', records['14'].value)
        self.assertEqual('iv4.unit.tests.', records['15'].value)
        self.assertEqual(
            ['2nd.unit.tests.', 'v4.unit.tests.'], records['16'].values
        )
        self.assertEqual(3, len(records))

        # expect 3 ipv6 PTRs
        source.populate(ip6_arpa)
        # we only vary in the last octect so pulling it out to avoid lots of 0.s
        records = {r.name.split('.', 1)[0]: r for r in ip6_arpa.records}
        self.assertEqual('all.unit.tests.', records['1'].value)
        self.assertEqual(
            ['2nd-v6.unit.tests.', 'v6.unit.tests.'], records['2'].values
        )
        self.assertEqual(2, len(records))

    def test_conflicting_fqdns(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])

        stubber.add_response(
            'describe_instances',
            {
                'Reservations': [
                    {
                        'Instances': [
                            {
                                # all addresses
                                'InstanceId': 'a42',
                                'PrivateIpAddress': '10.0.0.14',
                                'PublicIpAddress': '44.200.16.238',
                                'Ipv6Address': 'fc00::1',
                                'Tags': [
                                    {'Key': 'Name', 'Value': 'dup.unit.tests.'},
                                    {
                                        'Key': 'octodns',
                                        'Value': 'dup.unit.tests.',
                                    },
                                ],
                            }
                        ]
                    }
                ]
            },
        )
        with self.assertRaises(DuplicateRecordException):
            source.populate(zone)

    def test_conflicting_ips(self):
        source, stubber = self._get_stubbed_source()

        arpa = Zone('0.0.10.in-addr.arpa.', [])

        stubber.add_response(
            'describe_instances',
            {
                'Reservations': [
                    {
                        'Instances': [
                            {
                                # all addresses
                                'InstanceId': 'a42',
                                'PrivateIpAddress': '10.0.0.14',
                                'Tags': [
                                    {'Key': 'Name', 'Value': 'one.unit.tests.'}
                                ],
                            },
                            {
                                # all addresses
                                'InstanceId': 'a43',
                                'PrivateIpAddress': '10.0.0.14',
                                'Tags': [
                                    {'Key': 'Name', 'Value': 'two.unit.tests.'}
                                ],
                            },
                        ]
                    }
                ]
            },
        )
        with self.assertRaises(DuplicateRecordException):
            source.populate(arpa)
