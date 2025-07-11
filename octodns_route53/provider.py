#
#
#

import hashlib
import logging
import re
from collections import defaultdict
from ipaddress import AddressValueError, ip_address
from uuid import uuid4

from pycountry_convert import country_alpha2_to_continent_code

from octodns.equality import EqualityTupleMixin
from octodns.provider import ProviderException, SupportsException
from octodns.provider.base import BaseProvider
from octodns.record import Create, Record, Update
from octodns.record.geo import GeoCodes

from .auth import _AuthMixin
from .record import Route53AliasRecord

octal_re = re.compile(r'\\(\d\d\d)')


def _octal_replace(s):
    # See http://docs.aws.amazon.com/Route53/latest/DeveloperGuide/
    #     DomainNameFormat.html
    return octal_re.sub(lambda m: chr(int(m.group(1), 8)), s)


def _healthcheck_ref_prefix(version, record_type, record_fqdn):
    ref = f'{version}:{record_type}:{record_fqdn}'
    # the + 13 is to allow space for the uuid and ':'
    # it is allowing multiple healthchecks per record to exist
    if len(ref) + 13 > 64:
        hash_object = hashlib.sha512(record_fqdn.encode())
        hash_hex = hash_object.hexdigest()
        ref = f'{version}:{record_type}:{hash_hex[0:20]}'
    return ref


class _Route53Record(EqualityTupleMixin):
    @classmethod
    def _new_route53_alias(cls, provider, record, hosted_zone_id, creating):
        # HostedZoneId wants just the last bit, but the place we're getting
        # this from looks like /hostedzone/Z424CArX3BB224
        hosted_zone_id = hosted_zone_id.split('/', 2)[-1]

        # Use the value's hosted_zone_id if it has one (service symlink), if
        # not fall back to using the one for the current zone (local record
        # symlink)
        return set(
            [
                _Route53Alias(
                    provider,
                    value.hosted_zone_id or hosted_zone_id,
                    record,
                    value,
                    creating,
                )
                for value in record.values
            ]
        )

    @classmethod
    def _new_dynamic(cls, provider, record, hosted_zone_id, creating):
        # Creates the RRSets that correspond to the given dynamic record
        ret = set()

        # HostedZoneId wants just the last bit, but the place we're getting
        # this from looks like /hostedzone/Z424CArX3BB224
        hosted_zone_id = hosted_zone_id.split('/', 2)[-1]

        # Create the default pool which comes from the base `values` of the
        # record object. Its only used if all other values fail their
        # healthchecks, which hopefully never happens.
        fqdn = record.fqdn
        ret.add(
            _Route53Record(
                provider, record, creating, f'_octodns-default-pool.{fqdn}'
            )
        )

        # Pools
        for pool_name, pool in record.dynamic.pools.items():
            # Create the primary, this will be the rrset that geo targeted
            # rrsets will point to when they want to use a pool of values. It's
            # a primary and observes target health so if all the values for
            # this pool go red, we'll use the fallback/SECONDARY just below
            ret.add(
                _Route53DynamicPool(
                    provider, hosted_zone_id, record, pool_name, creating
                )
            )

            # Create the fallback for this pool
            fallback = pool.data.get('fallback', False)
            if fallback:
                # We have an explicitly configured fallback, another pool to
                # use if all our values go red. This RRSet configures that pool
                # as the next best option
                ret.add(
                    _Route53DynamicPool(
                        provider,
                        hosted_zone_id,
                        record,
                        pool_name,
                        creating,
                        target_name=fallback,
                    )
                )
            else:
                # We fallback on the default, no explicit fallback so if all of
                # this pool's values go red we'll fallback to the base
                # (non-health-checked) default pool of values
                ret.add(
                    _Route53DynamicPool(
                        provider,
                        hosted_zone_id,
                        record,
                        pool_name,
                        creating,
                        target_name='default',
                    )
                )

            # Create the values for this pool. These are health checked and in
            # general each unique value will have an associated healthcheck.
            # The PRIMARY pool up above will point to these RRSets which will
            # be served out according to their weights
            for i, value in enumerate(pool.data['values']):
                weight = value['weight']
                status = value['status']
                value = value['value']
                ret.add(
                    _Route53DynamicValue(
                        provider,
                        record,
                        pool_name,
                        value,
                        weight,
                        status,
                        i,
                        creating,
                    )
                )

        # Rules
        for i, rule in enumerate(record.dynamic.rules):
            pool_name = rule.data['pool']
            geos = rule.data.get('geos', [])
            if geos:
                for geo in geos:
                    # Create a RRSet for each geo in each rule that uses the
                    # desired target pool
                    ret.add(
                        _Route53DynamicRule(
                            provider,
                            hosted_zone_id,
                            record,
                            pool_name,
                            i,
                            creating,
                            geo=geo,
                        )
                    )
            else:
                # There's no geo's for this rule so it's the catchall that will
                # just point things that don't match any geo rules to the
                # specified pool
                ret.add(
                    _Route53DynamicRule(
                        provider, hosted_zone_id, record, pool_name, i, creating
                    )
                )

        return ret

    @classmethod
    def new(cls, provider, record, hosted_zone_id, creating):
        # Creates the RRSets that correspond to the given record

        if getattr(record, 'dynamic', False):
            ret = cls._new_dynamic(provider, record, hosted_zone_id, creating)
            return ret
        elif record._type == Route53AliasRecord._type:
            return cls._new_route53_alias(
                provider, record, hosted_zone_id, creating
            )

        # Its a simple record that translates into a single RRSet
        return set((_Route53Record(provider, record, creating),))

    def __init__(self, provider, record, creating, fqdn_override=None):
        self.fqdn = fqdn_override or record.fqdn
        self._type = record._type
        self.ttl = record.ttl
        self.record = record

        self._values = None

    @property
    def values(self):
        if self._values is None:
            _type = self._type.replace('/', '_')
            values_for = getattr(self, f'_values_for_{_type}')
            self._values = values_for(self.record)
        return self._values

    def mod(self, action, existing_rrsets):
        return {
            'Action': action,
            'ResourceRecordSet': {
                'Name': self.fqdn,
                'ResourceRecords': [{'Value': v} for v in self.values],
                'TTL': self.ttl,
                'Type': self._type,
            },
        }

    # NOTE: we're using __hash__ and ordering methods that consider
    # _Route53Records equivalent if they have the same class, fqdn, and _type.
    # Values are ignored. This is useful when computing diffs/changes.

    def __hash__(self):
        'sub-classes should never use this method'
        return f'{self.fqdn}:{self._type}'.__hash__()

    def _equality_tuple(self):
        '''Sub-classes should call up to this and return its value and add
        any additional fields they need to hav considered.'''
        return (self.__class__.__name__, self.fqdn, self._type)

    def __repr__(self):
        return (
            f'_Route53Record<{self.fqdn} {self._type} {self.ttl} {self.values}>'
        )

    def _value_convert_value(self, value, record):
        return value

    _value_convert_A = _value_convert_value
    _value_convert_AAAA = _value_convert_value
    _value_convert_NS = _value_convert_value
    _value_convert_CNAME = _value_convert_value
    _value_convert_PTR = _value_convert_value

    def _values_for_values(self, record):
        return record.values

    _values_for_A = _values_for_values
    _values_for_AAAA = _values_for_values
    _values_for_NS = _values_for_values

    def _value_convert_CAA(self, value, record):
        return f'{value.flags} {value.tag} "{value.value}"'

    def _values_for_CAA(self, record):
        return [self._value_convert_CAA(v, record) for v in record.values]

    def _values_for_value(self, record):
        return [record.value]

    _values_for_CNAME = _values_for_value
    _values_for_PTR = _values_for_value

    def _value_convert_MX(self, value, record):
        return f'{value.preference} {value.exchange}'

    def _values_for_MX(self, record):
        return [self._value_convert_MX(v, record) for v in record.values]

    def _value_convert_NAPTR(self, value, record):
        flags = value.flags if value.flags else ''
        service = value.service if value.service else ''
        regexp = value.regexp if value.regexp else ''
        return (
            f'{value.order} {value.preference} "{flags}" "{service}" '
            f'"{regexp}" {value.replacement}'
        )

    def _values_for_NAPTR(self, record):
        return [self._value_convert_NAPTR(v, record) for v in record.values]

    def _value_convert_quoted(self, value, record):
        return record.chunked_value(value)

    _value_convert_SPF = _value_convert_quoted
    _value_convert_TXT = _value_convert_quoted

    def _values_for_quoted(self, record):
        return record.chunked_values

    _values_for_SPF = _values_for_quoted
    _values_for_TXT = _values_for_quoted

    def _value_for_SRV(self, value, record):
        return f'{value.priority} {value.weight} {value.port} {value.target}'

    def _value_for_DS(self, value, record):
        return f'{value.key_tag} {value.algorithm} {value.digest_type} {value.digest}'

    def _values_for_SRV(self, record):
        return [self._value_for_SRV(v, record) for v in record.values]

    def _values_for_DS(self, record):
        return [self._value_for_DS(v, record) for v in record.values]


class _Route53Alias(_Route53Record):
    def __init__(self, provider, hosted_zone_id, record, value, creating):
        super().__init__(provider, record, creating)
        self.hosted_zone_id = hosted_zone_id
        self.fqdn = record.fqdn
        name = value.name
        if name:
            if Route53AliasRecord.is_service_alias(name):
                # It's a service symlink, just use it as is
                self.target_name = name
            else:
                # Add the zone name since Route53 expects the fqdn of the
                # target
                self.target_name = f'{value.name}.{record.zone.name}'
        else:
            # It targets the zone APEX
            self.target_name = record.zone.name
        self.target_type = value._type
        self.evaluate_target_health = value.evaluate_target_health

    def mod(self, action, existing_rrsets):
        return {
            'Action': action,
            'ResourceRecordSet': {
                'AliasTarget': {
                    'DNSName': self.target_name,
                    'EvaluateTargetHealth': self.evaluate_target_health,
                    'HostedZoneId': self.hosted_zone_id,
                },
                'Name': self.fqdn,
                'Type': self.target_type,
            },
        }

    def __hash__(self):
        return f'{self.fqdn}:{self.target_type}:{self.target_name}'.__hash__()

    def __repr__(self):
        return (
            f'_Route53Alias<{self.fqdn} {self.target_type} {self.target_name}>'
        )


class _Route53DynamicPool(_Route53Record):
    def __init__(
        self,
        provider,
        hosted_zone_id,
        record,
        pool_name,
        creating,
        target_name=None,
    ):
        fqdn_override = f'_octodns-{pool_name}-pool.{record.fqdn}'
        super().__init__(
            provider, record, creating, fqdn_override=fqdn_override
        )

        self.hosted_zone_id = hosted_zone_id
        self.pool_name = pool_name

        self.target_name = target_name
        if target_name:
            # We're pointing down the chain
            self.target_dns_name = f'_octodns-{target_name}-pool.{record.fqdn}'
        else:
            # We're a paimary, point at our values
            self.target_dns_name = f'_octodns-{pool_name}-value.{record.fqdn}'

    @property
    def mode(self):
        return 'Secondary' if self.target_name else 'Primary'

    @property
    def identifer(self):
        if self.target_name:
            return f'{self.pool_name}-{self.mode}-{self.target_name}'
        return f'{self.pool_name}-{self.mode}'

    def mod(self, action, existing_rrsets):
        return {
            'Action': action,
            'ResourceRecordSet': {
                'AliasTarget': {
                    'DNSName': self.target_dns_name,
                    'EvaluateTargetHealth': True,
                    'HostedZoneId': self.hosted_zone_id,
                },
                'Failover': 'SECONDARY' if self.target_name else 'PRIMARY',
                'Name': self.fqdn,
                'SetIdentifier': self.identifer,
                'Type': self._type,
            },
        }

    def __hash__(self):
        return f'{self.fqdn}:{self._type}:{self.identifer}'.__hash__()

    def __repr__(self):
        return f'_Route53DynamicPool<{self.fqdn} {self._type} {self.mode} {self.target_dns_name}>'


class _Route53DynamicRule(_Route53Record):
    def __init__(
        self,
        provider,
        hosted_zone_id,
        record,
        pool_name,
        index,
        creating,
        geo=None,
    ):
        super().__init__(provider, record, creating)

        self.hosted_zone_id = hosted_zone_id
        self.geo = geo
        self.pool_name = pool_name
        self.index = index

        self.target_dns_name = f'_octodns-{pool_name}-pool.{record.fqdn}'

    @property
    def identifer(self):
        return f'{self.index}-{self.pool_name}-{self.geo}'

    def mod(self, action, existing_rrsets):
        rrset = {
            'AliasTarget': {
                'DNSName': self.target_dns_name,
                'EvaluateTargetHealth': True,
                'HostedZoneId': self.hosted_zone_id,
            },
            'GeoLocation': {'CountryCode': '*'},
            'Name': self.fqdn,
            'SetIdentifier': self.identifer,
            'Type': self._type,
        }

        if self.geo:
            geo = GeoCodes.parse(self.geo)

            if geo['province_code']:
                rrset['GeoLocation'] = {
                    'CountryCode': geo['country_code'],
                    'SubdivisionCode': geo['province_code'],
                }
            elif geo['country_code']:
                rrset['GeoLocation'] = {'CountryCode': geo['country_code']}
            else:
                rrset['GeoLocation'] = {'ContinentCode': geo['continent_code']}

        return {'Action': action, 'ResourceRecordSet': rrset}

    def __hash__(self):
        return f'{self.fqdn}:{self._type}:{self.identifer}'.__hash__()

    def __repr__(self):
        return f'_Route53DynamicRule<{self.fqdn} {self._type} {self.index} {self.geo} {self.target_dns_name}>'


class _Route53DynamicValue(_Route53Record):
    def __init__(
        self,
        provider,
        record,
        pool_name,
        value,
        weight,
        status,
        index,
        creating,
    ):
        fqdn_override = f'_octodns-{pool_name}-value.{record.fqdn}'
        super().__init__(
            provider, record, creating, fqdn_override=fqdn_override
        )

        self.pool_name = pool_name
        self.status = status
        self.index = index
        value_convert = getattr(self, f'_value_convert_{record._type}')
        self.value = value_convert(value, record)
        self.weight = weight

        self.health_check_id = provider.get_health_check_id(
            record, self.value, self.status, creating
        )

    @property
    def identifer(self):
        return f'{self.pool_name}-{self.index:03d}'

    def mod(self, action, existing_rrsets):
        if action == 'DELETE':
            # When deleting records try and find the original rrset so that
            # we're 100% sure to have the complete & accurate data (this mostly
            # ensures we have the right health check id when there's multiple
            # potential matches)
            for existing in existing_rrsets:
                if self.fqdn == existing.get(
                    'Name'
                ) and self.identifer == existing.get('SetIdentifier', None):
                    return {'Action': action, 'ResourceRecordSet': existing}

        ret = {
            'Action': action,
            'ResourceRecordSet': {
                'Name': self.fqdn,
                'ResourceRecords': [{'Value': self.value}],
                'SetIdentifier': self.identifer,
                'TTL': self.ttl,
                'Type': self._type,
                'Weight': self.weight,
            },
        }

        if self.health_check_id:
            ret['ResourceRecordSet']['HealthCheckId'] = self.health_check_id

        return ret

    def __hash__(self):
        return f'{self.fqdn}:{self._type}:{self.identifer}'.__hash__()

    def __repr__(self):
        return f'_Route53DynamicValue<{self.fqdn} {self._type} {self.identifer} {self.value}>'


class Route53ProviderException(ProviderException):
    pass


def _mod_keyer(mod):
    rrset = mod['ResourceRecordSet']

    # Route53 requires that changes are ordered such that a target of an
    # AliasTarget is created or upserted prior to the record that targets it.
    # This is complicated by "UPSERT" appearing to be implemented as "DELETE"
    # before all changes, followed by a "CREATE", internally in the AWS API.
    # Because of this, we order changes as follows:
    #   - Delete any records that we wish to delete that are GEOS
    #      (because they are never targeted by anything)
    #   - Delete any records that we wish to delete that are SECONDARY
    #      (because they are no longer targeted by GEOS)
    #   - Delete any records that we wish to delete that are PRIMARY
    #      (because they are no longer targeted by SECONDARY)
    #   - Delete any records that we wish to delete that are VALUES
    #      (because they are no longer targeted by PRIMARY)
    #   - CREATE/UPSERT any records that are VALUES
    #      (because they don't depend on other records)
    #   - CREATE/UPSERT any records that are PRIMARY
    #      (because they always point to VALUES which now exist)
    #   - CREATE/UPSERT any records that are SECONDARY
    #      (because they now have PRIMARY records to target)
    #   - CREATE/UPSERT any records that are GEOS
    #      (because they now have all their PRIMARY pools to target)
    #   - :tada:
    #
    # In theory we could also do this based on actual target reference
    # checking, but that's more complex. Since our rules have a known
    # dependency order, we just rely on that.

    # Get the unique ID from the name/id to get a consistent ordering.
    if rrset.get('GeoLocation', False):
        unique_id = rrset['SetIdentifier']
    else:
        if 'SetIdentifier' in rrset:
            unique_id = f'{rrset["Name"]}-{rrset["SetIdentifier"]}'
        else:
            unique_id = rrset['Name']

    # Prioritise within the action_priority, ensuring targets come first.
    if rrset.get('GeoLocation', False):
        # Geos reference pools, so they come last.
        record_priority = 3
    elif rrset.get('AliasTarget', False):
        # We use an alias
        if rrset.get('Failover', False) == 'SECONDARY':
            # We're a secondary, which reference the primary (failover, P1).
            record_priority = 2
        else:
            # We're a primary, we reference values (P0).
            record_priority = 1
    else:
        # We're just a plain value, has no dependencies so first.
        record_priority = 0

    if mod['Action'] == 'DELETE':
        # Delete things first, so we can never trounce our own additions
        action_priority = 0
        # Delete in the reverse order of priority, e.g. start with the deepest
        # reference and work back to the values, rather than starting at the
        # values (still ref'd).
        record_priority = -record_priority
    else:
        # For CREATE and UPSERT, Route53 seems to treat them the same, so
        # interleave these, keeping the reference order described above.
        action_priority = 1

    return (action_priority, record_priority, unique_id)


def _parse_pool_name(n):
    # Parse the pool name out of _octodns-<pool-name>-pool...
    return n.split('.', 1)[0][9:-5]


class Route53Provider(_AuthMixin, BaseProvider):
    '''
    AWS Route53 Provider

    route53:
        class: octodns_route53.Route53Provider
        # The AWS access key id
        access_key_id:
        # The AWS secret access key
        secret_access_key:
        # The AWS session token (optional)
        # Only needed if using temporary security credentials
        session_token:
        # The AWS profile name (optional)
        profile:

    Alternatively, you may leave out access_key_id, secret_access_key
    and session_token.
    This will result in boto3 deciding authentication dynamically.

    In general the account used will need full permissions on Route53.
    '''

    SUPPORTS_GEO = True
    SUPPORTS_DYNAMIC = True
    SUPPORTS_POOL_VALUE_STATUS = True
    SUPPORTS_ROOT_NS = True
    SUPPORTS = set(
        (
            'A',
            'AAAA',
            'CAA',
            'CNAME',
            'DS',
            'MX',
            'NAPTR',
            'NS',
            'PTR',
            'SPF',
            'SRV',
            'TXT',
            Route53AliasRecord._type,
        )
    )

    # This should be bumped when there are underlying changes made to the
    # health check config.
    HEALTH_CHECK_VERSION = '0001'

    def __init__(
        self,
        id,
        access_key_id=None,
        secret_access_key=None,
        max_changes=1000,
        client_max_attempts=None,
        session_token=None,
        role_arn=None,
        profile=None,
        delegation_set_id=None,
        get_zones_by_name=False,
        private=None,
        *args,
        **kwargs,
    ):
        self.max_changes = max_changes
        self.delegation_set_id = delegation_set_id
        self.get_zones_by_name = get_zones_by_name
        self.private = private

        self.log = logging.getLogger(f'Route53Provider[{id}]')
        self.log.info(
            '__init__: id=%s, access_key_id=%s, max_changes=%d, delegation_set_id=%s, get_zones_by_name=%s',
            id,
            access_key_id,
            max_changes,
            delegation_set_id,
            get_zones_by_name,
        )
        super().__init__(id, *args, **kwargs)

        self._conn = self.client(
            service_name='route53',
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            role_arn=role_arn,
            profile=profile,
            client_max_attempts=client_max_attempts,
        )

        self._r53_zones = None
        self._r53_rrsets = {}
        self._health_checks = None

    def _get_zone_id_by_name(self, name):
        # attempt to get zone by name
        resp = self._conn.list_hosted_zones_by_name(
            DNSName=name, MaxItems="100"
        )
        id = None
        if len(resp['HostedZones']) != 0:
            for z in resp['HostedZones']:
                private_zone = z.get('Config', {}).get('PrivateZone', False)
                if self.private is not None and self.private != private_zone:
                    continue

                # if there is a response that starts with the name
                if _octal_replace(z['Name']).startswith(name):
                    if id is not None:
                        raise Route53ProviderException(
                            f'Multiple zones named "{z["Name"]}" were found.'
                        )
                    id = z['Id']
                    self.log.debug('get_zones_by_name:   id=%s', id)
        return id

    def update_r53_zones(self, name):
        if self._r53_zones is None:
            if self.get_zones_by_name:
                id = self._get_zone_id_by_name(name)
                zones = {}
                zones[name] = id
                self._r53_zones = zones
            else:
                self.log.debug('r53_zones: loading')
                zones = {}
                more = True
                start = {}
                while more:
                    resp = self._conn.list_hosted_zones(**start)
                    for z in resp['HostedZones']:
                        private_zone = z.get('Config', {}).get(
                            'PrivateZone', False
                        )
                        if (
                            self.private is not None
                            and self.private != private_zone
                        ):
                            continue
                        zname = _octal_replace(z['Name'])
                        if zname in zones:
                            raise Route53ProviderException(
                                f'Multiple zones named "{zname}" were found.'
                            )
                        zones[zname] = z['Id']
                    more = resp['IsTruncated']
                    start['Marker'] = resp.get('NextMarker', None)
                self._r53_zones = zones
        else:
            if name not in self._r53_zones and self.get_zones_by_name:
                id = self._get_zone_id_by_name(name)
                self._r53_zones[name] = id

    def _get_zone_id(self, name, create=False):
        self.log.debug('_get_zone_id: name=%s', name)
        self.update_r53_zones(name)
        id = None
        if name in self._r53_zones:
            id = self._r53_zones[name]
            self.log.debug('_get_zone_id:   id=%s', id)
        if create and not id:
            ref = uuid4().hex
            del_set = self.delegation_set_id
            self.log.debug(
                '_get_zone_id:   no matching zone, creating, ref=%s', ref
            )
            params = {"Name": name, "CallerReference": ref}
            if del_set:
                params["DelegationSetId"] = del_set
            if self.private is not None:
                params["HostedZoneConfig"] = {"PrivateZone": self.private}
            resp = self._conn.create_hosted_zone(**params)
            self._r53_zones[name] = id = resp['HostedZone']['Id']
        return id

    def _parse_geo(self, rrset):
        loc = rrset['GeoLocation']
        try:
            return loc['ContinentCode']
        except KeyError:
            # Must be country
            cc = loc['CountryCode']
            if cc == '*':
                # This is the default
                return
            cn = country_alpha2_to_continent_code(cc)
            try:
                return f'{cn}-{cc}-{loc["SubdivisionCode"]}'
            except KeyError:
                return f'{cn}-{cc}'

    def _data_for_A(self, rrset):
        return {
            'type': rrset['Type'],
            'values': [v['Value'] for v in rrset['ResourceRecords']],
            'ttl': int(rrset['TTL']),
        }

    _data_for_AAAA = _data_for_A

    def _data_for_CAA(self, rrset):
        values = []
        for rr in rrset['ResourceRecords']:
            flags, tag, value = rr['Value'].split(' ', 2)
            values.append({'flags': flags, 'tag': tag, 'value': value[1:-1]})
        return {
            'type': rrset['Type'],
            'values': values,
            'ttl': int(rrset['TTL']),
        }

    def _data_for_single(self, rrset):
        return {
            'type': rrset['Type'],
            'value': rrset['ResourceRecords'][0]['Value'],
            'ttl': int(rrset['TTL']),
        }

    _data_for_PTR = _data_for_single
    _data_for_CNAME = _data_for_single

    _fix_semicolons = re.compile(r'(?<!\\);')

    def _data_for_quoted(self, rrset):
        return {
            'type': rrset['Type'],
            'values': [
                self._fix_semicolons.sub('\\;', rr['Value'][1:-1])
                for rr in rrset['ResourceRecords']
            ],
            'ttl': int(rrset['TTL']),
        }

    _data_for_TXT = _data_for_quoted
    _data_for_SPF = _data_for_quoted

    def _data_for_MX(self, rrset):
        values = []
        for rr in rrset['ResourceRecords']:
            preference, exchange = rr['Value'].split()
            values.append({'preference': preference, 'exchange': exchange})
        return {
            'type': rrset['Type'],
            'values': values,
            'ttl': int(rrset['TTL']),
        }

    def _data_for_NAPTR(self, rrset):
        values = []
        for rr in rrset['ResourceRecords']:
            order, preference, flags, service, regexp, replacement = rr[
                'Value'
            ].split()
            flags = flags[1:-1]
            service = service[1:-1]
            regexp = regexp[1:-1]
            values.append(
                {
                    'order': order,
                    'preference': preference,
                    'flags': flags,
                    'service': service,
                    'regexp': regexp,
                    'replacement': replacement,
                }
            )
        return {
            'type': rrset['Type'],
            'values': values,
            'ttl': int(rrset['TTL']),
        }

    def _data_for_NS(self, rrset):
        return {
            'type': rrset['Type'],
            'values': [v['Value'] for v in rrset['ResourceRecords']],
            'ttl': int(rrset['TTL']),
        }

    def _data_for_SRV(self, rrset):
        values = []
        for rr in rrset['ResourceRecords']:
            priority, weight, port, target = rr['Value'].split()
            values.append(
                {
                    'priority': priority,
                    'weight': weight,
                    'port': port,
                    'target': target,
                }
            )
        return {
            'type': rrset['Type'],
            'values': values,
            'ttl': int(rrset['TTL']),
        }

    def _data_for_DS(self, rrset):
        values = []
        for rr in rrset['ResourceRecords']:
            # digest may contain whitespace
            key_tag, algorithm, digest_type, digest = rr['Value'].split(
                maxsplit=3
            )
            values.append(
                {
                    'key_tag': key_tag,
                    'algorithm': algorithm,
                    'digest_type': digest_type,
                    'digest': digest,
                }
            )
        return {
            'type': rrset['Type'],
            'values': values,
            'ttl': int(rrset['TTL']),
        }

    def _load_records(self, zone_id):
        if zone_id not in self._r53_rrsets:
            self.log.debug('_load_records: zone_id=%s loading', zone_id)
            rrsets = []
            more = True
            start = {}
            while more:
                resp = self._conn.list_resource_record_sets(
                    HostedZoneId=zone_id, **start
                )
                rrsets += resp['ResourceRecordSets']
                more = resp['IsTruncated']
                if more:
                    start = {
                        'StartRecordName': resp['NextRecordName'],
                        'StartRecordType': resp['NextRecordType'],
                    }
                    try:
                        start['StartRecordIdentifier'] = resp[
                            'NextRecordIdentifier'
                        ]
                    except KeyError:
                        pass

            self._r53_rrsets[zone_id] = rrsets

        return self._r53_rrsets[zone_id]

    def _data_for_dynamic(self, name, _type, rrsets):
        # This converts a bunch of RRSets into their corresponding dynamic
        # Record. It's used by populate.
        pools = defaultdict(lambda: {'values': []})
        # Data to build our rules will be collected here and "converted" into
        # their final form below
        rules = defaultdict(lambda: {'pool': None, 'geos': []})
        # Base/empty data
        data = {'dynamic': {'pools': pools, 'rules': []}}

        # For all the rrsets that comprise this dynamic record
        for rrset in rrsets:
            name = rrset['Name']
            if '-pool.' in name:
                # This is a pool rrset
                pool_name = _parse_pool_name(name)
                if pool_name == 'default':
                    # default becomes the base for the record and its
                    # value(s) will fill the non-dynamic values
                    data_for = getattr(self, f'_data_for_{_type}')
                    data.update(data_for(rrset))
                elif rrset['Failover'] == 'SECONDARY':
                    # This is a failover record, we'll ignore PRIMARY, but
                    # SECONDARY will tell us what the pool's fallback is
                    fallback_name = _parse_pool_name(
                        rrset['AliasTarget']['DNSName']
                    )
                    # Don't care about default fallbacks, anything else
                    # we'll record
                    if fallback_name != 'default':
                        pools[pool_name]['fallback'] = fallback_name
            elif 'GeoLocation' in rrset:
                # These are rules
                _id = rrset['SetIdentifier']
                # We record rule index as the first part of set-id, the 2nd
                # part just ensures uniqueness across geos and is ignored
                i = int(_id.split('-', 1)[0])
                target_pool = _parse_pool_name(rrset['AliasTarget']['DNSName'])
                # Record the pool
                rules[i]['pool'] = target_pool
                # Record geo if we have one
                geo = self._parse_geo(rrset)
                if geo:
                    rules[i]['geos'].append(geo)
            else:
                # These are the pool value(s)
                # Grab the pool name out of the SetIdentifier, format looks
                # like ...-000 where 000 is a zero-padded index for the value
                # it's ignored only used to make sure the value is unique
                pool_name = rrset['SetIdentifier'][:-4]
                value = rrset['ResourceRecords'][0]['Value']
                try:
                    health_check_id = rrset.get('HealthCheckId', None)
                    health_check = self.health_checks[health_check_id]
                    health_check_config = health_check['HealthCheckConfig']
                    if (
                        health_check_config['Disabled']
                        and health_check_config['Inverted']
                    ):
                        # disabled and inverted means down
                        status = 'down'
                    else:
                        # otherwise obey
                        status = 'obey'
                except KeyError:
                    # No healthcheck means status is up
                    status = 'up'
                pools[pool_name]['values'].append(
                    {
                        'status': status,
                        'value': value,
                        'weight': rrset['Weight'],
                    }
                )

        # Convert our map of rules into an ordered list now that we have all
        # the data
        for _, rule in sorted(rules.items()):
            r = {'pool': rule['pool']}
            geos = sorted(rule['geos'])
            if geos:
                r['geos'] = geos
            data['dynamic']['rules'].append(r)

        return data

    def _data_for_route53_alias(self, rrsets, zone_name):
        zone_name_len = len(zone_name) + 1
        values = []
        for rrset in rrsets:
            target = rrset['AliasTarget']
            name = target['DNSName']
            if Route53AliasRecord.is_service_alias(name):
                # We only set hosted_zone_id when it's a "service" alias, when
                # it's a pointer to the current zone it'll be None
                hosted_zone_id = target['HostedZoneId']
            else:
                # We'll trim off the zone name off the target
                name = name[:-zone_name_len]
                # hosted_zone_id is unused
                hosted_zone_id = None
            values.append(
                {
                    'evaluate-target-health': target['EvaluateTargetHealth'],
                    'hosted-zone-id': hosted_zone_id,
                    'name': name,
                    'type': rrset['Type'],
                }
            )
        return {'type': Route53AliasRecord._type, 'values': values}

    def _process_desired_zone(self, desired):
        for record in desired.records:
            if getattr(record, 'dynamic', False):
                protocol = record.healthcheck_protocol
                if protocol not in ('HTTP', 'HTTPS', 'TCP'):
                    msg = f'healthcheck protocol "{protocol}" not supported'
                    # no workable fallbacks so straight error
                    raise SupportsException(f'{self.id}: {msg}')

                # Make a copy of the record in case we have to muck with it
                dynamic = record.dynamic
                rules = []
                for i, rule in enumerate(dynamic.rules):
                    geos = rule.data.get('geos', [])
                    if not geos:
                        rules.append(rule)
                        continue
                    filtered_geos = [
                        g for g in geos if not g.startswith('NA-CA-')
                    ]
                    if not filtered_geos:
                        # We've removed all geos, we'll have to skip this rule
                        msg = f'NA-CA-* not supported for {record.fqdn}'
                        fallback = f'skipping rule {i}'
                        self.supports_warn_or_except(msg, fallback)
                        continue
                    elif geos != filtered_geos:
                        msg = f'NA-CA-* not supported for {record.fqdn}'
                        before = ', '.join(geos)
                        after = ', '.join(filtered_geos)
                        fallback = (
                            f'filtering rule {i} from ({before}) to '
                            f'({after})'
                        )
                        self.supports_warn_or_except(msg, fallback)
                        rule.data['geos'] = filtered_geos
                    rules.append(rule)

                if rules != dynamic.rules:
                    record = record.copy()
                    record.dynamic.rules = rules
                    desired.add_record(record, replace=True)

        return super()._process_desired_zone(desired)

    def list_zones(self):
        self.log.debug('list_zones:')
        hosted_zones = []
        params = {}
        if self.delegation_set_id:
            params['DelegationSetId'] = self.delegation_set_id
        more = True
        while more:
            resp = self._conn.list_hosted_zones(**params)
            for h in resp['HostedZones']:
                private_zone = h.get('Config', {}).get('PrivateZone', False)
                if self.private is not None and self.private != private_zone:
                    continue
                if h['Name'] in hosted_zones:
                    raise Route53ProviderException(
                        f'Multiple zones named "{h["Name"]}" were found.'
                    )
                hosted_zones.append(h['Name'])
            params['Marker'] = resp.get('NextMarker', None)
            more = resp['IsTruncated']

        hosted_zones.sort()
        return hosted_zones

    def populate(self, zone, target=False, lenient=False):
        self.log.debug(
            'populate: name=%s, target=%s, lenient=%s',
            zone.name,
            target,
            lenient,
        )

        before = len(zone.records)
        exists = False

        zone_id = self._get_zone_id(zone.name)
        if zone_id:
            exists = True
            records = defaultdict(lambda: defaultdict(list))
            dynamic = defaultdict(lambda: defaultdict(list))
            aliases = defaultdict(list)

            for rrset in self._load_records(zone_id):
                record_name = _octal_replace(rrset['Name'])
                record_name = zone.hostname_from_fqdn(record_name)
                record_type = rrset['Type']
                if record_type not in self.SUPPORTS:
                    # Skip stuff we don't support
                    continue
                if record_name.startswith('_octodns-'):
                    # Part of a dynamic record
                    try:
                        record_name = record_name.split('.', 1)[1]
                    except IndexError:
                        record_name = ''
                    dynamic[record_name][record_type].append(rrset)
                    continue
                elif 'AliasTarget' in rrset:
                    if rrset['AliasTarget']['DNSName'].startswith('_octodns-'):
                        # Part of a dynamic record
                        dynamic[record_name][record_type].append(rrset)
                    else:
                        aliases[record_name].append(rrset)
                    continue
                elif 'TrafficPolicyInstanceId' in rrset:
                    self.log.warning(
                        'TrafficPolicies are not supported, skipping %s',
                        rrset['Name'],
                    )
                    continue
                # A basic record (potentially including geo)
                data = getattr(self, f'_data_for_{record_type}')(rrset)
                records[record_name][record_type].append(data)

            # Convert the dynamic rrsets to Records
            for name, types in dynamic.items():
                for _type, rrsets in types.items():
                    data = self._data_for_dynamic(name, _type, rrsets)
                    record = Record.new(
                        zone, name, data, source=self, lenient=lenient
                    )
                    zone.add_record(record, lenient=lenient)

            # Convert the basic rrsets to records
            for name, types in records.items():
                for _type, data in types.items():
                    data = data[0]
                    record = Record.new(
                        zone, name, data, source=self, lenient=lenient
                    )
                    zone.add_record(record, lenient=lenient)

            # Route53 Aliases don't have TTLs so we're setting a dummy value
            # here and will ignore any ttl-only changes down below in
            # _include_change in order to avoid persistent changes that can't
            # be synced.  It's a bit ugly, but there's nothing we can do since
            # octoDNS requires a TTL and Route53 doesn't have one on their
            # ALIAS records.
            zone_name = zone.name
            for name, rrsets in aliases.items():
                data = self._data_for_route53_alias(rrsets, zone_name)
                data['ttl'] = 942942942
                record = Record.new(
                    zone, name, data, source=self, lenient=lenient
                )
                zone.add_record(record, lenient=lenient)

        self.log.info(
            'populate:   found %s records, exists=%s',
            len(zone.records) - before,
            exists,
        )
        return exists

    def _gen_mods(self, action, records, existing_rrsets):
        '''
        Turns `_Route53*`s in to `change_resource_record_sets` `Changes`
        '''
        return [r.mod(action, existing_rrsets) for r in records]

    @property
    def health_checks(self):
        if self._health_checks is None:
            # need to do the first load
            self.log.debug('health_checks: loading')
            checks = {}
            more = True
            start = {}
            while more:
                resp = self._conn.list_health_checks(**start)
                for health_check in resp['HealthChecks']:
                    # our format for CallerReference is dddd:hex-uuid
                    ref = health_check.get('CallerReference', 'xxxxx')
                    if len(ref) > 4 and ref[4] != ':':
                        # ignore anything else
                        continue
                    checks[health_check['Id']] = health_check

                more = resp['IsTruncated']
                start['Marker'] = resp.get('NextMarker', None)

            self._health_checks = checks

        # We've got a cached version use it
        return self._health_checks

    def _healthcheck_measure_latency(self, record):
        return (
            record.octodns.get('route53', {})
            .get('healthcheck', {})
            .get('measure_latency', True)
        )

    def _healthcheck_request_interval(self, record):
        interval = (
            record.octodns.get('route53', {})
            .get('healthcheck', {})
            .get('request_interval', 10)
        )
        if interval in [10, 30]:
            return interval
        else:
            raise Route53ProviderException(
                'route53.healthcheck.request_interval '
                'parameter must be either 10 or 30.'
            )

    def _healthcheck_failure_threshold(self, record):
        threshold = (
            record.octodns.get('route53', {})
            .get('healthcheck', {})
            .get('failure_threshold', 6)
        )
        if isinstance(threshold, int) and threshold >= 1 and threshold <= 10:
            return threshold
        else:
            raise Route53ProviderException(
                'route53.healthcheck.failure_threshold '
                'parameter must be an integer '
                'between 1 and 10.'
            )

    def _health_check_equivalent(
        self,
        host,
        path,
        protocol,
        port,
        measure_latency,
        request_interval,
        failure_threshold,
        health_check,
        value=None,
        disabled=None,
        inverted=None,
    ):
        config = health_check['HealthCheckConfig']

        # So interestingly Route53 normalizes IPv6 addresses to a funky, but
        # valid, form which will cause us to fail to find see things as
        # equivalent. To work around this we'll ip_address's returned objects
        # for equivalence.
        # E.g 2001:4860:4860:0:0:0:0:8842 -> 2001:4860:4860::8842
        if value:
            value = ip_address(str(value))
            config_ip_address = ip_address(str(config['IPAddress']))
        else:
            # No value so give this a None to match value's
            config_ip_address = None

        fully_qualified_domain_name = config.get(
            'FullyQualifiedDomainName', None
        )
        resource_path = config.get('ResourcePath', None)
        return (
            host == fully_qualified_domain_name
            and path == resource_path
            and protocol == config['Type']
            and port == config['Port']
            and measure_latency == config['MeasureLatency']
            and request_interval == config['RequestInterval']
            and failure_threshold == config['FailureThreshold']
            and (disabled is None or disabled == config['Disabled'])
            and (inverted is None or inverted == config['Inverted'])
            and value == config_ip_address
        )

    def get_health_check_id(self, record, value, status, create):
        # fqdn & the first value are special, we use them to match up health
        # checks to their records. Route53 health checks check a single ip and
        # we're going to assume that ips are interchangeable to avoid
        # health-checking each one independently
        fqdn = record.fqdn
        self.log.debug(
            'get_health_check_id: fqdn=%s, type=%s, value=%s, status=%s',
            fqdn,
            record._type,
            value,
            status,
        )

        if status == 'up':
            # status up means no health check
            self.log.debug('get_health_check_id:   status up, no health check')
            return None

        try:
            ip_address(str(value))
            # We're working with an IP, host is the Host header
            healthcheck_host = record.healthcheck_host(value=value)
        except (AddressValueError, ValueError):
            # This isn't an IP, host is the value, value should be None
            healthcheck_host = value
            value = None

        healthcheck_path = record.healthcheck_path
        healthcheck_protocol = record.healthcheck_protocol
        healthcheck_port = record.healthcheck_port
        healthcheck_latency = self._healthcheck_measure_latency(record)
        healthcheck_interval = self._healthcheck_request_interval(record)
        healthcheck_threshold = self._healthcheck_failure_threshold(record)
        if status == 'down':
            healthcheck_disabled = True
            healthcheck_inverted = True
        else:  # obey
            healthcheck_disabled = False
            healthcheck_inverted = False

        # we're looking for a healthcheck with the current version & our record
        # type, we'll ignore anything else
        expected_ref = _healthcheck_ref_prefix(
            self.HEALTH_CHECK_VERSION, record._type, record.fqdn
        )
        for id, health_check in self.health_checks.items():
            if not health_check['CallerReference'].startswith(expected_ref):
                # not match, ignore
                continue
            if self._health_check_equivalent(
                healthcheck_host,
                healthcheck_path,
                healthcheck_protocol,
                healthcheck_port,
                healthcheck_latency,
                healthcheck_interval,
                healthcheck_threshold,
                health_check,
                value=value,
                disabled=healthcheck_disabled,
                inverted=healthcheck_inverted,
            ):
                # this is the health check we're looking for
                self.log.debug('get_health_check_id:   found match id=%s', id)
                return id

        if not create:
            # no existing matches and not allowed to create, return none
            self.log.debug('get_health_check_id:   no matches, no create')
            return

        # no existing matches, we need to create a new health check
        config = {
            'Disabled': healthcheck_disabled,
            'Inverted': healthcheck_inverted,
            'EnableSNI': healthcheck_protocol == 'HTTPS',
            'FailureThreshold': healthcheck_threshold,
            'MeasureLatency': healthcheck_latency,
            'Port': healthcheck_port,
            'RequestInterval': healthcheck_interval,
            'Type': healthcheck_protocol,
        }
        if healthcheck_protocol != 'TCP':
            config['FullyQualifiedDomainName'] = healthcheck_host
            config['ResourcePath'] = healthcheck_path
        # we need either an IP address (A/AAAA) or a FullyQualifiedDomainName
        # (CNAME)
        if value:
            config['IPAddress'] = value
        else:
            config['FullyQualifiedDomainName'] = healthcheck_host

        expected_ref = _healthcheck_ref_prefix(
            self.HEALTH_CHECK_VERSION, record._type, record.fqdn
        )
        ref = f'{expected_ref}:' + uuid4().hex[:12]
        resp = self._conn.create_health_check(
            CallerReference=ref, HealthCheckConfig=config
        )
        health_check = resp['HealthCheck']
        id = health_check['Id']

        # Set a Name for the benefit of the UI
        value_or_host = value or healthcheck_host
        name = f'{record.fqdn}:{record._type} - {value_or_host}'
        self._conn.change_tags_for_resource(
            ResourceType='healthcheck',
            ResourceId=id,
            AddTags=[{'Key': 'Name', 'Value': name}],
        )
        # Manually add it to our cache
        health_check['Tags'] = {'Name': name}

        # store the new health check so that we'll be able to find it in the
        # future
        self._health_checks[id] = health_check
        self.log.info(
            'get_health_check_id: created id=%s, host=%s, '
            'path=%s, protocol=%s, port=%d, measure_latency=%r, '
            'request_interval=%d, value=%s',
            id,
            healthcheck_host,
            healthcheck_path,
            healthcheck_protocol,
            healthcheck_port,
            healthcheck_latency,
            healthcheck_interval,
            value,
        )
        return id

    def _gc_health_checks(self, record, new):
        if record._type not in ('A', 'AAAA', 'CNAME'):
            return
        self.log.debug('_gc_health_checks: record=%s', record)
        # Find the health checks we're using for the new route53 records
        in_use = set()
        for r in new:
            hc_id = getattr(r, 'health_check_id', False)
            if hc_id:
                in_use.add(hc_id)
        self.log.debug('_gc_health_checks:   in_use=%s', in_use)
        # Now we need to run through ALL the health checks looking for those
        # that apply to this record, deleting any that do and are no longer in
        # use
        expected_re = re.compile(fr'^\d\d\d\d:{record._type}:{record.fqdn}:')
        # UNITL 1.0: we'll clean out the previous version of Route53 health
        # checks as best as we can.
        expected_legacy_host = record.fqdn[:-1]
        expected_legacy = f'0000:{record._type}:'
        for id, health_check in self.health_checks.items():
            ref = health_check['CallerReference']
            if expected_re.match(ref) and id not in in_use:
                # this is a health check for this record, but not one we're
                # planning to use going forward
                self.log.info('_gc_health_checks:   deleting id=%s', id)
                self._conn.delete_health_check(HealthCheckId=id)
            elif ref.startswith(expected_legacy):
                config = health_check['HealthCheckConfig']
                if expected_legacy_host == config['FullyQualifiedDomainName']:
                    self.log.info(
                        '_gc_health_checks:   deleting legacy id=%s', id
                    )
                    self._conn.delete_health_check(HealthCheckId=id)

    def _gen_records(self, record, zone_id, creating=False):
        '''
        Turns an octodns.Record into one or more `_Route53*`s
        '''
        return _Route53Record.new(self, record, zone_id, creating)

    def _mod_Create(self, change, zone_id, existing_rrsets):
        # New is the stuff that needs to be created
        new_records = self._gen_records(change.new, zone_id, creating=True)
        # Now is a good time to clear out any unused health checks since we
        # know what we'll be using going forward
        self._gc_health_checks(change.new, new_records)
        return self._gen_mods('CREATE', new_records, existing_rrsets)

    def _mod_Update(self, change, zone_id, existing_rrsets):
        # See comments in _Route53Record for how the set math is made to do our
        # bidding here.
        existing_records = self._gen_records(
            change.existing, zone_id, creating=False
        )
        new_records = self._gen_records(change.new, zone_id, creating=True)
        # Now is a good time to clear out any unused health checks since we
        # know what we'll be using going forward
        self._gc_health_checks(change.new, new_records)
        # Things in existing, but not new are deletes
        deletes = existing_records - new_records
        # Things in new, but not existing are the creates
        creates = new_records - existing_records
        # Things in both need updating, we could optimize this and filter out
        # things that haven't actually changed, but that's for another day.
        # We can't use set math here b/c we won't be able to control which of
        # the two objects will be in the result and we need to ensure it's the
        # new one.
        upserts = set()
        for new_record in new_records:
            if new_record in existing_records:
                upserts.add(new_record)

        return (
            self._gen_mods('DELETE', deletes, existing_rrsets)
            + self._gen_mods('CREATE', creates, existing_rrsets)
            + self._gen_mods('UPSERT', upserts, existing_rrsets)
        )

    def _mod_Delete(self, change, zone_id, existing_rrsets):
        # Existing is the thing that needs to be deleted
        existing_records = self._gen_records(
            change.existing, zone_id, creating=False
        )
        # Now is a good time to clear out all the health checks since we know
        # we're done with them
        self._gc_health_checks(change.existing, [])
        return self._gen_mods('DELETE', existing_records, existing_rrsets)

    def _extra_changes_update_needed(self, record, rrset, statuses={}):
        value = rrset['ResourceRecords'][0]['Value']
        if record._type == 'CNAME':
            # For CNAME, healthcheck host by default points to the CNAME value
            healthcheck_host = value
        else:
            healthcheck_host = record.healthcheck_host()

        healthcheck_path = record.healthcheck_path
        healthcheck_protocol = record.healthcheck_protocol
        healthcheck_port = record.healthcheck_port
        healthcheck_latency = self._healthcheck_measure_latency(record)
        healthcheck_interval = self._healthcheck_request_interval(record)
        healthcheck_threshold = self._healthcheck_failure_threshold(record)

        status = statuses.get(value, 'obey')
        if status == 'up':
            if 'HealthCheckId' in rrset:
                self.log.info(
                    '_extra_changes_update_needed: health-check '
                    'found for status="up", causing update of %s:%s',
                    record.fqdn,
                    record._type,
                )
                return True
            else:
                # No health check needed
                return False

        try:
            health_check_id = rrset['HealthCheckId']
            health_check = self.health_checks[health_check_id]
            caller_ref = health_check['CallerReference']
            if caller_ref.startswith(self.HEALTH_CHECK_VERSION):
                if self._health_check_equivalent(
                    healthcheck_host,
                    healthcheck_path,
                    healthcheck_protocol,
                    healthcheck_port,
                    healthcheck_latency,
                    healthcheck_interval,
                    healthcheck_threshold,
                    health_check,
                ):
                    # it has the right health check
                    return False
        except (IndexError, KeyError):
            # no health check id or one that isn't the right version
            pass

        # no good, doesn't have the right health check, needs an update
        self.log.info(
            '_extra_changes_update_needed: health-check caused '
            'update of %s:%s',
            record.fqdn,
            record._type,
        )
        return True

    def _extra_changes_dynamic_needs_update(self, zone_id, record):
        # OK this is a record we don't have change for that does have dynamic
        # information. We need to look and see if it needs to be updated b/c of
        # a health check version bump or other mismatch
        self.log.debug(
            '_extra_changes_dynamic_needs_update: inspecting=%s, %s',
            record.fqdn,
            record._type,
        )

        fqdn = record.fqdn
        _type = record._type

        # map values to statuses
        statuses = {}
        for pool in record.dynamic.pools.values():
            for value in pool.data['values']:
                statuses[value['value']] = value.get('status', 'obey')

        # loop through all the r53 rrsets
        for rrset in self._load_records(zone_id):
            name = rrset['Name']
            # Break off the first piece of the name, it'll let us figure out if
            # this is an rrset we're interested in.
            maybe_meta, rest = name.split('.', 1)

            if (
                not maybe_meta.startswith('_octodns-')
                or not maybe_meta.endswith('-value')
                or '-default-' in name
            ):
                # We're only interested in non-default dynamic value records,
                # as that's where healthchecks live
                continue

            if rest != fqdn or _type != rrset['Type']:
                # rrset isn't for the current record
                continue

            if self._extra_changes_update_needed(record, rrset, statuses):
                # no good, doesn't have the right health check, needs an update
                self.log.info(
                    '_extra_changes_dynamic_needs_update: '
                    'health-check caused update of %s:%s',
                    record.fqdn,
                    record._type,
                )
                return True

        return False

    def _extra_changes(self, desired, changes, **kwargs):
        self.log.debug('_extra_changes: desired=%s', desired.name)
        zone_id = self._get_zone_id(desired.name)
        if not zone_id:
            # zone doesn't exist so no extras to worry about
            return []
        # we'll skip extra checking for anything we're already going to change
        changed = set([c.record for c in changes])
        # ok, now it's time for the reason we're here, we need to go over all
        # the desired records
        extras = []
        for record in desired.records:
            if record in changed:
                # already have a change for it, skipping
                continue

            if getattr(record, 'dynamic', False):
                if self._extra_changes_dynamic_needs_update(zone_id, record):
                    extras.append(Update(record, record))

        return extras

    def _include_change(self, change):
        return not (
            isinstance(change, Update)
            and change.new._type == Route53AliasRecord._type
            and change.new.values == change.existing.values
        )

    def _apply(self, plan):
        desired = plan.desired
        changes = plan.changes
        self.log.info(
            '_apply: zone=%s, len(changes)=%d', desired.name, len(changes)
        )

        batch = []
        batch_rs_count = 0
        zone_id = self._get_zone_id(desired.name, True)
        existing_rrsets = self._load_records(zone_id)
        for c in changes:
            # Generate the mods for this change
            if isinstance(c, Create):
                new = c.new
                if new._type == 'NS' and new.name == '':
                    # Root NS records are never created, they come w/the zone,
                    # convert the create into an Update
                    c = Update(new, new)
            klass = c.__class__.__name__
            mod_type = getattr(self, f'_mod_{klass}')
            mods = mod_type(c, zone_id, existing_rrsets)

            # Order our mods to make sure targets exist before alises point to
            # them and we CRUD in the desired order
            mods.sort(key=_mod_keyer)

            mods_rs_count = sum(
                [
                    len(m['ResourceRecordSet'].get('ResourceRecords', ''))
                    for m in mods
                ]
            )

            if mods_rs_count > self.max_changes:
                # a single mod resulted in too many ResourceRecords changes
                raise Exception(f'Too many modifications: {mods_rs_count}')

            # r53 limits changesets to 1000 entries
            if (batch_rs_count + mods_rs_count) < self.max_changes:
                # append to the batch
                batch += mods
                batch_rs_count += mods_rs_count
            else:
                self.log.info(
                    '_apply:   sending change request for batch of '
                    '%d mods, %d ResourceRecords',
                    len(batch),
                    batch_rs_count,
                )
                # send the batch
                self._really_apply(batch, zone_id)
                # start a new batch with the leftovers
                batch = mods
                batch_rs_count = mods_rs_count

        # the way the above process works there will always be something left
        # over in batch to process. In the case that we submit a batch up there
        # it was always the case that there was something pushing us over
        # max_changes and thus left over to submit.
        self.log.info(
            '_apply:   sending change request for batch of %d mods,'
            ' %d ResourceRecords',
            len(batch),
            batch_rs_count,
        )
        self._really_apply(batch, zone_id)

    def _really_apply(self, batch, zone_id):
        # Ensure this batch is ordered (deletes before creates etc.)
        batch.sort(key=_mod_keyer)
        uuid = uuid4().hex
        batch = {'Comment': f'Change: {uuid}', 'Changes': batch}
        self.log.debug(
            '_really_apply:   sending change request, comment=%s',
            batch['Comment'],
        )
        resp = self._conn.change_resource_record_sets(
            HostedZoneId=zone_id, ChangeBatch=batch
        )
        self.log.debug('_really_apply:   change info=%s', resp['ChangeInfo'])
