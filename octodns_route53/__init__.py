#
#
#

from .provider import Route53Provider, Route53ProviderException
from .record import Route53AliasRecord

__VERSION__ = '0.0.5'

# quell warnings
Route53AliasRecord
Route53Provider
Route53ProviderException
