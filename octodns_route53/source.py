#
#
#

from ipaddress import IPv4Address, IPv6Address
from logging import getLogger

from octodns.idna import idna_encode
from octodns.source.base import BaseSource
from octodns.record import Record

from .auth import _AuthMixin


class Ec2Source(_AuthMixin, BaseSource):
    SUPPORTS_GEO = False
    SUPPORTS = ('A', 'AAAA', 'PTR')

    def __init__(
        self,
        id,
        region,
        access_key_id=None,
        secret_access_key=None,
        session_token=None,
        client_max_attempts=None,
        ttl=3600,
        tag_prefix='octodns',
        *args,
        **kwargs,
    ):
        self.log = getLogger(f'Ec2Source[{id}]')
        self.log.info(
            '__init__: id=%s, region=%s, access_key_id=%s, ttl=%d, tag_prefix=%s',
            id,
            region,
            access_key_id,
            ttl,
            tag_prefix,
        )
        self.ttl = ttl
        self.tag_prefix = tag_prefix

        super().__init__(id, *args, **kwargs)

        self._conn = self.client(
            service_name='ec2',
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            client_max_attempts=client_max_attempts,
            region_name=region,
        )

        self._instances = None

    @property
    def instances(self):
        if self._instances is None:
            resp = self._conn.describe_instances()
            instances = {}
            for reservation in resp['Reservations']:
                for instance in reservation['Instances']:
                    # process tags
                    fqdns = []
                    for tag in instance.get('Tags', []):
                        key = tag['Key']
                        val = tag['Value']
                        if key == 'Name':
                            fqdns.append(val)
                        elif key.startswith(self.tag_prefix):
                            fqdns.extend(val.split('/'))

                    fqdns = [f'{i}.' if i[-1] != '.' else i for i in fqdns]
                    instances[instance['InstanceId']] = {
                        'private_v4': instance.get('PrivateIpAddress'),
                        'v6': instance.get('Ipv6Address'),
                        'fqdns': fqdns,
                    }

            # so to get a determinate order, then discard the key
            instances = [i[1] for i in sorted(instances.items())]
            self._instances = instances

        return self._instances

    def _populate(self, zone):
        for instance in self.instances:
            for fqdn in instance['fqdns']:
                if not fqdn.endswith(zone.name):
                    # not interested in this one
                    continue

                name = zone.hostname_from_fqdn(fqdn)
                if instance['private_v4']:
                    a = Record.new(
                        zone,
                        name,
                        {
                            'type': 'A',
                            'ttl': self.ttl,
                            'value': instance['private_v4'],
                        },
                    )
                    zone.add_record(a)

                if instance['v6']:
                    aaaa = Record.new(
                        zone,
                        name,
                        {
                            'type': 'AAAA',
                            'ttl': self.ttl,
                            'value': instance['v6'],
                        },
                    )
                    zone.add_record(aaaa)

    def _populate_in_addr_arpa(self, zone):
        for instance in self.instances:
            if not instance['fqdns']:
                # not interested in this one
                continue

            private_v4 = instance['private_v4']
            if not private_v4:
                # not interested in this one
                continue

            rev = IPv4Address(private_v4).reverse_pointer
            rev = f'{rev}.'
            if not rev.endswith(zone.name):
                # not interested in this one
                continue

            rev = zone.hostname_from_fqdn(rev)
            ptr = Record.new(
                zone,
                rev,
                {'type': 'PTR', 'ttl': self.ttl, 'values': instance['fqdns']},
            )
            zone.add_record(ptr)

    def _populate_ip6_arpa(self, zone):
        for instance in self.instances:
            if not instance['fqdns']:
                # not interested in this one
                continue

            v6 = instance['v6']
            if not v6:
                # not interested in this one
                continue

            rev = IPv6Address(v6).reverse_pointer
            rev = f'{rev}.'
            if not rev.endswith(zone.name):
                # not interested in this one
                continue

            rev = zone.hostname_from_fqdn(rev)
            ptr = Record.new(
                zone,
                rev,
                {'type': 'PTR', 'ttl': self.ttl, 'values': instance['fqdns']},
            )
            zone.add_record(ptr)

    def populate(self, zone, target=False, lenient=False):
        self.log.debug('populate: zone=%s', zone.name)
        before = len(zone.records)

        if zone.name.endswith('in-addr.arpa.'):
            self._populate_in_addr_arpa(zone)
        elif zone.name.endswith('ip6.arpa.'):
            self._populate_ip6_arpa(zone)
        else:
            self._populate(zone)

        self.log.info(
            'populate:   found %s records', len(zone.records) - before
        )


class ElbSource(_AuthMixin, BaseSource):
    SUPPORTS_GEO = False
    SUPPORTS = ('ALIAS', 'CNAME')

    def __init__(
        self,
        id,
        region,
        access_key_id=None,
        secret_access_key=None,
        session_token=None,
        client_max_attempts=None,
        ttl=3600,
        tag_prefix='octodns',
        *args,
        **kwargs,
    ):
        self.log = getLogger(f'ElbSource[{id}]')
        self.log.info(
            '__init__: id=%s, region=%s, access_key_id=%s, ttl=%d, tag_prefix=%s',
            id,
            region,
            access_key_id,
            ttl,
            tag_prefix,
        )
        self.ttl = ttl
        self.tag_prefix = tag_prefix

        super().__init__(id, *args, **kwargs)

        self._conn = self.client(
            service_name='elbv2',
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            client_max_attempts=client_max_attempts,
            region_name=region,
        )

        self._lbs = None

    @property
    def lbs(self):
        if self._lbs is None:
            # build the list of load balancers
            resp = self._conn.describe_load_balancers()
            lbs = {}
            for lb in resp['LoadBalancers']:
                arn = lb['LoadBalancerArn']
                lbs[arn] = {
                    'dns_name': f'{lb["DNSName"]}.',
                    'fqdns': [lb['LoadBalancerName']],
                }

            # request tags and look through them for fqdns
            arns = list(lbs.keys())
            if arns:
                resp = self._conn.describe_tags(ResourceArns=arns)
                for td in resp['TagDescriptions']:
                    arn = td['ResourceArn']
                    lb = lbs[arn]
                    for tag in td.get('Tags', []):
                        key = tag['Key']
                        val = tag['Value']
                        if key.startswith(self.tag_prefix):
                            lb['fqdns'].extend(val.split('/'))

            for lb in lbs.values():
                fqdns = lb['fqdns']
                fqdns = [f'{i}.' if i[-1] != '.' else i for i in fqdns]
                lb['fqdns'] = fqdns

            # add .'s to fqdns that don't have them
            self._lbs = lbs.values()

        return self._lbs

    def populate(self, zone, target=False, lenient=False):
        self.log.debug('populate: zone=%s', zone.name)
        before = len(zone.records)

        for lb in self.lbs:
            for fqdn in lb['fqdns']:
                fqdn = idna_encode(fqdn)
                if fqdn == zone.name:
                    alias = Record.new(
                        zone,
                        '',
                        {
                            'type': 'ALIAS',
                            'ttl': self.ttl,
                            'value': lb['dns_name'],
                        },
                    )
                    zone.add_record(alias)
                elif fqdn.endswith(zone.name):
                    hostname = zone.hostname_from_fqdn(fqdn)
                    cname = Record.new(
                        zone,
                        hostname,
                        {
                            'type': 'CNAME',
                            'ttl': self.ttl,
                            'value': lb['dns_name'],
                        },
                    )
                    zone.add_record(cname)

        self.log.info(
            'populate:   found %s records', len(zone.records) - before
        )
