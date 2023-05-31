#
#
#

import re

from boto3 import client
from botocore.config import Config


class _AuthMixin:
    def client(
        self,
        service_name,
        access_key_id,
        secret_access_key,
        session_token,
        role_arn,
        client_max_attempts,
        *args,
        **kwargs,
    ):
        self.log.debug(
            'client: service_name=%s, access_key_id=%s, secret_access_key=%s, session_token=%s, client_max_attempts=%s',
            service_name,
            access_key_id,
            secret_access_key is not None,
            session_token is not None,
            client_max_attempts,
        )

        if role_arn:
            self.log.debug('client:   assuming role %s', role_arn)
            sts_client = self.client(
                'sts',
                access_key_id,
                secret_access_key,
                session_token,
                None,
                client_max_attempts,
                *args,
                **kwargs,
            )

            ident = re.sub(r"[^a-zA-Z0-9_=,.@-]+", "-", self.id)

            credentials = sts_client.assume_role(
                RoleArn=role_arn, RoleSessionName="octodns-route53-" + ident
            )
            access_key_id = credentials['Credentials']['AccessKeyId']
            secret_access_key = credentials['Credentials']['SecretAccessKey']
            session_token = credentials['Credentials']['Expiration']

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

        if use_fallback_auth:
            return client(service_name, *args, config=config, **kwargs)

        return client(
            *args,
            service_name=service_name,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            aws_session_token=session_token,
            config=config,
            **kwargs,
        )
