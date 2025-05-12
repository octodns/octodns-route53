#
#
#

import re

from boto3 import Session
from botocore.config import Config


class _AuthMixin:
    def client(
        self,
        service_name,
        access_key_id,
        secret_access_key,
        session_token,
        role_arn,
        profile,
        client_max_attempts,
        *args,
        **kwargs,
    ):
        self.log.debug(
            'client: service_name=%s, access_key_id=%s, secret_access_key=%s, session_token=%s, client_max_attempts=%s, profile=%s',
            service_name,
            access_key_id,
            secret_access_key is not None,
            session_token is not None,
            client_max_attempts,
            profile,
        )

        if role_arn:
            self.log.debug('client:   assuming role %s', role_arn)
            # ~recursively call into ourselves to get an STS client with the
            # auth info provided
            sts_client = self.client(
                'sts',
                access_key_id,
                secret_access_key,
                session_token,
                None,
                profile,
                client_max_attempts,
                *args,
                **kwargs,
            )

            # make sure to only uses chars that are allowed in role session
            # names
            ident = re.sub(r"[^a-zA-Z0-9_=,.@-]+", "-", self.id)

            # assume the specified role with the base auth info
            credentials = sts_client.assume_role(
                RoleArn=role_arn, RoleSessionName="octodns-route53-" + ident
            )

            # and get new auth info for that role assumption, replacing the
            # stuff that was passed in and continue on to get the requested
            # client with the new auth
            access_key_id = credentials['Credentials']['AccessKeyId']
            secret_access_key = credentials['Credentials']['SecretAccessKey']
            session_token = credentials['Credentials']['SessionToken']

        use_fallback_auth = (
            access_key_id is None
            and secret_access_key is None
            and session_token is None
        )
        if use_fallback_auth:
            self.log.debug('client:   using fallback auth')

        config = None
        if client_max_attempts is not None:
            self.log.info(
                '__init__: setting max_attempts to %d', client_max_attempts
            )
            config = Config(retries={'max_attempts': client_max_attempts})

        session_kwargs = {}
        if profile is not None:
            session_kwargs['profile_name'] = profile

        if not use_fallback_auth:
            session_kwargs['aws_access_key_id'] = access_key_id
            session_kwargs['aws_secret_access_key'] = secret_access_key
            session_kwargs['aws_session_token'] = session_token

        session = Session(**session_kwargs)

        return session.client(
            *args, service_name=service_name, config=config, **kwargs
        )
