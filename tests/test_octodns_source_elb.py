#
#
#

from unittest import TestCase

from botocore.stub import Stubber

from octodns.zone import Zone

from octodns_route53 import ElbSource


class TestElbSource(TestCase):
    load_balancers = {
        'LoadBalancers': [
            {
                # matches name
                'DNSName': 'foo.aws.com',
                'LoadBalancerArn': 'arn42',
                'LoadBalancerName': 'service.unit.tests.',
            },
            {
                # doesn't match
                'DNSName': 'bar.aws.com',
                'LoadBalancerArn': 'arn43',
                'LoadBalancerName': 'this.doesnt.match.',
            },
            {
                # matches, no trailing dot
                'DNSName': 'baz.aws.com',
                'LoadBalancerArn': 'arn44',
                'LoadBalancerName': 'no-dot.unit.tests',
            },
            {
                # name doesn't match, but tags will
                'DNSName': 'blip.aws.com',
                'LoadBalancerArn': 'arn45',
                'LoadBalancerName': 'tags.will.match.',
            },
            {
                # both name and tags match
                'DNSName': 'bang.aws.com',
                'LoadBalancerArn': 'arn46',
                'LoadBalancerName': 'both.unit.tests.',
            },
        ]
    }
    tags = {
        'TagDescriptions': [
            {
                'ResourceArn': 'arn42',
                'Tags': [{'Key': 'irrelevant', 'Value': 'doesnt matter'}],
            },
            {'ResourceArn': 'arn43'},
            {'ResourceArn': 'arn44'},
            {
                'ResourceArn': 'arn45',
                'Tags': [
                    {
                        'Key': 'octodns',
                        # multi-value: one matches w/dot. one matches w/o dot, one
                        # doesn't match
                        'Value': 'first.unit.tests./second.unit.tests/third.thing.',
                    }
                ],
            },
            {
                'ResourceArn': 'arn46',
                'Tags': [
                    {
                        'Key': 'octodns-1',
                        # matches
                        'Value': 'fourth.unit.tests.',
                    },
                    {
                        'Key': 'octodns-2',
                        # matches w/o dot
                        'Value': 'fifth.unit.tests',
                    },
                    {
                        'Key': 'octodns-2',
                        # doesn't match
                        'Value': 'sixth.doesnt.apply.',
                    },
                    {
                        'Key': 'octodns-3',
                        # apex match
                        'Value': 'unit.tests.',
                    },
                ],
            },
        ]
    }

    def _get_stubbed_source(self, **kwargs):
        source = ElbSource('test', 'us-east-1', 'abc', '123', **kwargs)

        # Use the stubber
        stubber = Stubber(source._conn)
        stubber.activate()

        return (source, stubber)

    def test_no_elbs(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])

        # no reservations
        stubber.add_response('describe_load_balancers', {'LoadBalancers': []})
        source.populate(zone)
        self.assertEqual(0, len(zone.records))

        # 2nd populate, no change (uses cached lbs) would error if it makes any
        # calls since we're stubbed and have no responses
        source.populate(zone)
        self.assertEqual(0, len(zone.records))

    def test_lbs(self):
        source, stubber = self._get_stubbed_source()

        zone = Zone('unit.tests.', [])

        stubber.add_response('describe_load_balancers', self.load_balancers)

        stubber.add_response('describe_tags', self.tags)

        source.populate(zone)

        records = {r.name: r for r in zone.records}
        self.assertEqual('foo.aws.com.', records['service'].value)
        self.assertEqual('baz.aws.com.', records['no-dot'].value)
        self.assertEqual('blip.aws.com.', records['first'].value)
        self.assertEqual('blip.aws.com.', records['second'].value)
        self.assertEqual('bang.aws.com.', records['both'].value)
        self.assertEqual('bang.aws.com.', records['fourth'].value)
        self.assertEqual('bang.aws.com.', records['fifth'].value)
        self.assertEqual('bang.aws.com.', records[''].value)
        # make sure there's no extras
        self.assertEqual(8, len(records))

        # apex is an ALIAS
        record = records.pop('')
        self.assertEqual('ALIAS', record._type)
        # rest are CNAMEs
        for record in records.values():
            self.assertEqual('CNAME', record._type)

    def test_conflicting_fqdns(self):
        pass
